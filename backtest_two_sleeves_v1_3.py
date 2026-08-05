#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized v1.3  —  Reference Implementation  (CANDIDATE)
  Per spec: TwoSleeves_Optimized_Build_Guide_v1_3.md

  STATUS: candidate, NOT adopted. v1.2 remains the live strategy. The daily
  runner reports v1.3 alongside v1.2 so its signals can be watched before any
  real capital is committed.

  CHANGES FROM v1.2 — three structural moves, all validated on both halves of
  a 2000-2014 / 2015-2026 walk-forward:

    1. DEFENSIVE STATE IS NO LONGER 1x EQUITY. v1.2's defensive state held the
       unlevered signal ETF (QQQ/SPY). At the COVID trough BOTH sleeves were
       already defensive — the exits fired correctly — yet the portfolio still
       lost 39% because 1x QQQ/SPY fell ~34% too. The core sleeve now rotates
       to TLT instead. This is the single largest drawdown lever found.

    2. THE SECOND EQUITY SLEEVE IS GONE. SPY->SPXL correlates 0.55 with
       QQQ->TQQQ and only added a second helping of the same bet. It is
       replaced by two LOW-CORRELATION unlevered sector sleeves: XLE (energy,
       0.14 correlation to the core) and XLV (healthcare, 0.23). Energy
       compounded ~30%/yr through 2003-2008 precisely when tech did not.

    3. PER-SLEEVE VOLATILITY GATES. A single HVol<=16% entry gate is calibrated
       for large-cap equity and is wrong for other assets. The core runs a
       looser 25% gate (it is the return engine); the sector sleeves run a
       tight 12% gate (they exist to be calm ballast).

  Everything else is v1.2 mechanics, unchanged: the entry latch, 30-bar
  cooldown, take-profit, hard stop, vol exit, VIX-spike exit, defensive stop,
  BIL cash state and strictly causal next-open execution.

  Locked spec window: 2000-01-03 -> 2026-05-22 (6637 bars).
═══════════════════════════════════════════════════════════════════════════════

DATA DEPENDENCY (9 JSON files; stdlib only, no external APIs):
  json/QQQ_US.json    - core signal                       (real history)
  json/TQQQ_US.json   - core vehicle                      (spliced: synth + real)
  json/TLT_US.json    - core defensive                    (spliced: synth + real)
  json/XLE_US.json    - energy sleeve, signal + vehicle   (real history)
  json/XLV_US.json    - healthcare sleeve, signal + vehicle (real history)
  json/GLD_US.json    - safety sleeve + sector defensive  (spliced: synth + real)
  json/BIL_US.json    - cash state                        (spliced: synth + real)
  json/VIX_INDX.json  - VIX index (powers the spike exit) (real history)

⚠ SYNTHETIC-HISTORY CAVEAT: TQQQ's pre-2010 bars are modelled as exactly
  3.00x QQQ with ZERO drag. Measured against the real fund that convention
  overstates returns by ~7%/yr, because it ignores expense ratio, financing
  cost and daily-reset volatility decay. The numbers below inherit that
  optimism (as do v1.1 and v1.2). On drag-calibrated synthetic history this
  configuration returns 28.57% CAGR / -29.91% MaxDD / 1.081 Sharpe, and v1.2
  returns 24.70% / -39.32% / 0.952 — the RELATIVE improvement is preserved.
"""
import csv
import json
import math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"
OUT_DIR   = WORKSPACE

# ── Portfolio config ──────────────────────────────────────────────────────────
TOTAL_CAPITAL    = 100_000.0
SAFETY_TICKER    = "GLD"
SAFETY_ALLOC     = 0.05                  # v1.2 used 0.10
CASH_TICKER      = "BIL"
BACKTEST_START   = date(2000, 1, 1)
BACKTEST_END     = date(2026, 5, 22)     # v1.3 locked spec window

# ── Strategy config (unchanged from v1.2 unless noted) ────────────────────────
VOL_PERIOD       = 20
VOL_EXIT_THRESH  = 30.0
TAKE_PROFIT_PCT  = 200.0
STOP_LOSS_PCT    = 12.0
DEF_STOP_PCT     = 14.0                  # v1.2: 18.0
COOLDOWN_DAYS    = 30
REBAL_FREQ       = "monthly"             # v1.2: annual

VIX_TICKER       = "VIX_INDX"
VIX_MA_PERIOD    = 20
VIX_SPIKE_MULT   = 2.2                   # v1.2: 2.0

# (signal, vehicle, defensive, wma, sma, weight, vol_entry_max)
# weights are relative and are normalised to fill (1 - SAFETY_ALLOC)
SLEEVE_CONFIGS = [
    ("QQQ", "TQQQ", "TLT",  5, 200, 75, 25.0),
    ("XLE", "XLE",  "GLD", 16, 175, 14, 12.0),
    ("XLV", "XLV",  "GLD", 16, 125, 11, 12.0),
]

MIN_IDX = max(VOL_PERIOD, VIX_MA_PERIOD,
              *(c[3] for c in SLEEVE_CONFIGS), *(c[4] for c in SLEEVE_CONFIGS))


# ── Indicator helpers (identical to v1.2) ─────────────────────────────────────
def compute_hvol(closes, window):
    """20-bar annualised realised vol on log returns. SAMPLE variance (/N-1)."""
    n, out = len(closes), [None] * len(closes)
    for i in range(window, n):
        lr   = [math.log(closes[j] / closes[j-1]) for j in range(i - window + 1, i + 1)]
        mean = sum(lr) / window
        var  = sum((r - mean)**2 for r in lr) / (window - 1)
        out[i] = math.sqrt(var * 252) * 100.0
    return out

def compute_wma(closes, period):
    n, out = len(closes), [None] * len(closes)
    denom  = period * (period + 1) / 2
    for i in range(period - 1, n):
        out[i] = sum(closes[i - period + 1 + j] * (j + 1) for j in range(period)) / denom
    return out

def compute_sma(closes, period):
    n, out = len(closes), [None] * len(closes)
    if n < period: return out
    s = sum(closes[:period]); out[period - 1] = s / period
    for i in range(period, n):
        s += closes[i] - closes[i - period]; out[i] = s / period
    return out


# ── Data loader ───────────────────────────────────────────────────────────────
def load_ticker(ticker):
    path = DATA_DIR / (f"{ticker}.json" if ticker == VIX_TICKER else f"{ticker}_US.json")
    if not path.exists():
        raise FileNotFoundError(f"Required data file missing: {path}")
    raw = json.load(open(path))
    raw = [r for r in raw
           if BACKTEST_START <= date.fromisoformat(r["date"]) <= BACKTEST_END]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


print()
print("=" * 80)
print("  TWO-SLEEVES OPTIMIZED v1.3 (CANDIDATE)  —  Core + low-correlation sectors")
print(f"  Safety sleeve  : {SAFETY_ALLOC:.0%} {SAFETY_TICKER} (buy & hold)")
print(f"  Cash state     : holds {CASH_TICKER} (T-bills)")
print(f"  VIX spike exit : exit vehicle when VIX > SMA(VIX,{VIX_MA_PERIOD}) x {VIX_SPIKE_MULT}")
print(f"  Rebalance      : {REBAL_FREQ}")
for s, v, d, w, sm, wt, vem in SLEEVE_CONFIGS:
    print(f"  {s:<3}->{v:<5} def={d:<4} WMA={w:>2}/SMA={sm:>3} | weight={wt:>3}"
          f" | VolEntry<={vem:.0f}% VolExit>={VOL_EXIT_THRESH:.0f}%")
print("=" * 80)

all_tickers = {SAFETY_TICKER, CASH_TICKER, VIX_TICKER}
for s, v, d, _, _, _, _ in SLEEVE_CONFIGS:
    all_tickers |= {s, v, d}

print("  Loading data ...", end="", flush=True)
raw_data = {t: load_ticker(t) for t in sorted(all_tickers)}
print("  done.")

common = sorted(set.intersection(*[set(raw_data[t].keys()) for t in all_tickers]))
n = len(common)
print(f"  Common date range: {common[0]} -> {common[-1]}  ({n} bars)\n")

arrays = {}
for ticker, d in raw_data.items():
    closes = [d[day]["close"]          for day in common]
    adjs   = [d[day]["adjusted_close"] for day in common]
    opens  = [d[day]["open"]           for day in common]
    arrays[ticker] = dict(closes=closes, adj=adjs, opens=opens,
                          ratio=[(a / c if c else 1.0) for a, c in zip(adjs, closes)])

for s, v, d, wma, sma, wt, vem in SLEEVE_CONFIGS:
    c = arrays[s]["closes"]
    arrays[s][f"wma{wma}"] = compute_wma(c, wma)
    arrays[s][f"sma{sma}"] = compute_sma(c, sma)
    arrays[s]["hvol"]      = compute_hvol(c, VOL_PERIOD)

vix_close = arrays[VIX_TICKER]["closes"]
vix_sma   = compute_sma(vix_close, VIX_MA_PERIOD)


# ── Sleeve setup ──────────────────────────────────────────────────────────────
raw_w = [c[5] for c in SLEEVE_CONFIGS]
tot_w = sum(raw_w)
weights = [w / tot_w * (1.0 - SAFETY_ALLOC) for w in raw_w]

sleeves = []
for (s, v, d, wma, sma, _, vem), w in zip(SLEEVE_CONFIGS, weights):
    init = TOTAL_CAPITAL * w
    sleeves.append(dict(
        signal=s, vehicle=v, defensive=d, wma_period=wma, sma_period=sma,
        weight=w, vem=vem, label=f"{s}->{v}",
        state="cash", next_state=None,
        v_shares=0.0, v_entry=0.0, v_entry_date="", v_exit_rsn="",
        d_shares=0.0, d_entry=0.0, d_entry_date="", d_exit_rsn="",
        c_shares=0.0, cash=init, equity=init,
        wma_was_below=True, entry_eligible=False, cooldown=0,
    ))

cash_adj0 = arrays[CASH_TICKER]["adj"][0]
for sl in sleeves:
    sl["c_shares"] = sl["cash"] / cash_adj0; sl["cash"] = 0.0

safety_init = TOTAL_CAPITAL * SAFETY_ALLOC
gld_shares  = safety_init / arrays[SAFETY_TICKER]["adj"][0]
gld_equity  = safety_init


# ── Simulation ────────────────────────────────────────────────────────────────
portfolio_curve, rebalance_events, all_trades = [], [], []
prev_m = (int(common[0][:4]), int(common[0][5:7]))
spike_exit_count = 0

for i in range(n):
    day = common[i]

    # Phase 1: execute pending transitions at today's open
    for sl in sleeves:
        if sl["next_state"] is None:
            continue
        veh, dfn = sl["vehicle"], sl["defensive"]
        vo = arrays[veh]["opens"][i]         * arrays[veh]["ratio"][i]
        do = arrays[dfn]["opens"][i]         * arrays[dfn]["ratio"][i]
        co = arrays[CASH_TICKER]["opens"][i] * arrays[CASH_TICKER]["ratio"][i]

        if sl["state"] == "vehicle":
            proceeds = sl["v_shares"] * vo
            all_trades.append({
                "sleeve": sl["label"], "vehicle": veh,
                "entry_date": sl["v_entry_date"], "entry_price": round(sl["v_entry"], 4),
                "exit_date": day, "exit_price": round(vo, 4),
                "pnl_pct": round((vo - sl["v_entry"]) / sl["v_entry"] * 100.0, 4),
                "hold_days": (date.fromisoformat(day)
                              - date.fromisoformat(sl["v_entry_date"])).days,
                "exit_reason": sl["v_exit_rsn"]})
            sl["cash"] = proceeds; sl["v_shares"] = 0.0; sl["v_entry"] = 0.0
        elif sl["state"] == "defensive":
            proceeds = sl["d_shares"] * do
            all_trades.append({
                "sleeve": sl["label"], "vehicle": f"{dfn}_DEF",
                "entry_date": sl["d_entry_date"], "entry_price": round(sl["d_entry"], 4),
                "exit_date": day, "exit_price": round(do, 4),
                "pnl_pct": round(((do - sl["d_entry"]) / sl["d_entry"] * 100.0)
                                 if sl["d_entry"] else 0.0, 4),
                "hold_days": (date.fromisoformat(day)
                              - date.fromisoformat(sl["d_entry_date"])).days,
                "exit_reason": sl["d_exit_rsn"] or "def_to_" + sl["next_state"]})
            sl["cash"] = proceeds; sl["d_shares"] = 0.0
            sl["d_entry"] = 0.0; sl["d_exit_rsn"] = ""
        elif sl["state"] == "cash":
            sl["cash"] = sl["c_shares"] * co; sl["c_shares"] = 0.0

        if sl["next_state"] == "vehicle":
            sl["v_shares"] = sl["cash"] / vo; sl["v_entry"] = vo
            sl["v_entry_date"] = day; sl["cash"] = 0.0
        elif sl["next_state"] == "defensive":
            sl["d_shares"] = sl["cash"] / do; sl["d_entry"] = do
            sl["d_entry_date"] = day; sl["cash"] = 0.0
        elif sl["next_state"] == "cash":
            sl["c_shares"] = sl["cash"] / co; sl["cash"] = 0.0

        sl["state"] = sl["next_state"]; sl["next_state"] = None

    # Phase 2: cooldown
    for sl in sleeves:
        if sl["cooldown"] > 0:
            sl["cooldown"] -= 1

    # Phase 3: mark to market
    for sl in sleeves:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][i]
    gld_equity = gld_shares * arrays[SAFETY_TICKER]["adj"][i]

    # Phase 4: monthly rebalance to target weights
    cur_m = (int(day[:4]), int(day[5:7]))
    if cur_m > prev_m:
        total_eq   = sum(sl["equity"] for sl in sleeves) + gld_equity
        gld_target = total_eq * SAFETY_ALLOC
        event = {"date": day, "total_equity": round(total_eq, 2)}
        for sl in sleeves:
            tgt = total_eq * sl["weight"]
            pre = sl["equity"]
            if sl["state"] == "vehicle":
                sl["v_shares"] = tgt / arrays[sl["vehicle"]]["adj"][i]
            elif sl["state"] == "defensive":
                sl["d_shares"] = tgt / arrays[sl["defensive"]]["adj"][i]
            else:
                sl["c_shares"] = tgt / arrays[CASH_TICKER]["adj"][i]
            sl["equity"] = tgt
            event[f"{sl['label']}_pre"]   = round(pre, 2)
            event[f"{sl['label']}_delta"] = round(tgt - pre, 2)
        event["GLD_pre"]   = round(gld_equity, 2)
        event["GLD_delta"] = round(gld_target - gld_equity, 2)
        gld_shares = gld_target / arrays[SAFETY_TICKER]["adj"][i]
        gld_equity = gld_target
        rebalance_events.append(event)
    prev_m = cur_m

    # Phase 5: record
    port_eq = sum(sl["equity"] for sl in sleeves) + gld_equity
    row = {"date": day, "equity": round(port_eq, 2)}
    for sl in sleeves:
        row[f"{sl['label']}_eq"]    = round(sl["equity"], 2)
        row[f"{sl['label']}_state"] = sl["state"]
    row["safety_gld"] = round(gld_equity, 2)
    row["vix"]        = round(vix_close[i], 2)
    row["vix_sma"]    = round(vix_sma[i], 2) if vix_sma[i] is not None else None
    portfolio_curve.append(row)

    if i < MIN_IDX:
        continue

    vma = vix_sma[i]
    vix_spike = (vma is not None and vix_close[i] > vma * VIX_SPIKE_MULT)

    # Phase 6: signals for bar i+1
    for sl in sleeves:
        sig, veh = sl["signal"], sl["vehicle"]
        wa  = arrays[sig][f"wma{sl['wma_period']}"]
        sa  = arrays[sig][f"sma{sl['sma_period']}"]
        hva = arrays[sig]["hvol"]
        if any(x is None for x in (wa[i], sa[i], wa[i-1], sa[i-1])):
            continue
        w, wp, s, sp = wa[i], wa[i-1], sa[i], sa[i-1]
        hv  = hva[i] if hva[i] is not None else 0.0
        cab = wp <= sp and w >  s
        cbl = wp >= sp and w <  s

        if sl["state"] == "vehicle" and sl["next_state"] is None:
            vad   = arrays[veh]["adj"][i]
            do_tp = vad >= sl["v_entry"] * (1 + TAKE_PROFIT_PCT / 100)
            do_sl = vad <= sl["v_entry"] * (1 - STOP_LOSS_PCT   / 100)
            do_v  = hv >= VOL_EXIT_THRESH
            if do_tp or do_sl or do_v or cbl or vix_spike:
                if   do_tp: sl["v_exit_rsn"] = f"take_profit({TAKE_PROFIT_PCT:.0f}%)"
                elif do_sl:
                    sl["v_exit_rsn"] = f"stop_loss({STOP_LOSS_PCT:.0f}%)"
                    sl["cooldown"] = COOLDOWN_DAYS
                elif do_v:  sl["v_exit_rsn"] = f"vol_exit({hv:.1f}%)"
                elif cbl:   sl["v_exit_rsn"] = "wma_cross_below"
                else:
                    sl["v_exit_rsn"] = f"vix_spike({VIX_SPIKE_MULT}x_MA{VIX_MA_PERIOD})"
                    spike_exit_count += 1
                sl["wma_was_below"] = False
                sl["next_state"]    = "defensive"

        if sl["state"] == "defensive" and sl["next_state"] is None:
            dad = arrays[sl["defensive"]]["adj"][i]
            if sl["d_entry"] > 0 and dad <= sl["d_entry"] * (1 - DEF_STOP_PCT / 100):
                sl["d_exit_rsn"] = f"def_stop({DEF_STOP_PCT:.0f}%)"
                sl["cooldown"]   = COOLDOWN_DAYS
                sl["next_state"] = "cash"

        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if w < s: sl["wma_was_below"] = True; sl["entry_eligible"] = False
            if cab and sl["wma_was_below"]:
                sl["entry_eligible"] = True; sl["wma_was_below"] = False
            if sl["entry_eligible"] and w < s:
                sl["entry_eligible"] = False; sl["wma_was_below"] = True

        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if (sl["entry_eligible"] and hv <= sl["vem"] and w > s
                    and i + 1 < n and sl["cooldown"] == 0):
                sl["next_state"] = "vehicle"
                sl["entry_eligible"] = False; sl["wma_was_below"] = False


# ── Close open positions at last bar (trade log only) ─────────────────────────
last_day = common[-1]
for sl in sleeves:
    if sl["state"] == "vehicle" and sl["v_shares"] > 0:
        last = arrays[sl["vehicle"]]["adj"][-1]
        all_trades.append({
            "sleeve": sl["label"], "vehicle": sl["vehicle"],
            "entry_date": sl["v_entry_date"], "entry_price": round(sl["v_entry"], 4),
            "exit_date": last_day, "exit_price": round(last, 4),
            "pnl_pct": round((last - sl["v_entry"]) / sl["v_entry"] * 100.0, 4),
            "hold_days": (date.fromisoformat(last_day)
                          - date.fromisoformat(sl["v_entry_date"])).days,
            "exit_reason": "end_of_data"})
        sl["equity"] = sl["v_shares"] * last
    elif sl["state"] == "defensive" and sl["d_shares"] > 0:
        last = arrays[sl["defensive"]]["adj"][-1]
        all_trades.append({
            "sleeve": sl["label"], "vehicle": f"{sl['defensive']}_DEF",
            "entry_date": sl["d_entry_date"], "entry_price": round(sl["d_entry"], 4),
            "exit_date": last_day, "exit_price": round(last, 4),
            "pnl_pct": round(((last - sl["d_entry"]) / sl["d_entry"] * 100.0)
                             if sl["d_entry"] else 0.0, 4),
            "hold_days": (date.fromisoformat(last_day)
                          - date.fromisoformat(sl["d_entry_date"])).days,
            "exit_reason": "end_of_data"})
        sl["equity"] = sl["d_shares"] * last
    elif sl["state"] == "cash" and sl["c_shares"] > 0:
        sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1]

gld_equity = gld_shares * arrays[SAFETY_TICKER]["adj"][-1]
port_final = sum(sl["equity"] for sl in sleeves) + gld_equity
portfolio_curve[-1]["equity"] = round(port_final, 2)


# ── Metrics (identical definitions to v1.2) ───────────────────────────────────
def calc_metrics(curve, init_eq):
    final_eq = curve[-1]["equity"]
    years = (date.fromisoformat(curve[-1]["date"])
             - date.fromisoformat(curve[0]["date"])).days / 365.25
    cagr = ((final_eq / init_eq) ** (1.0 / years) - 1) * 100.0 if years > 0 else 0.0
    peak, max_dd = init_eq, 0.0
    for row in curve:
        eq = row["equity"]
        if eq > peak: peak = eq
        dd = (eq - peak) / peak * 100.0
        if dd < max_dd: max_dd = dd
    dr = [(curve[i]["equity"] - curve[i-1]["equity"]) / curve[i-1]["equity"]
          for i in range(1, len(curve)) if curve[i-1]["equity"]]
    if len(dr) > 1:
        mu  = sum(dr) / len(dr)
        sig = (sum((r - mu)**2 for r in dr) / (len(dr) - 1)) ** 0.5
        sharpe = mu / sig * 252**0.5 if sig > 0 else 0.0
    else:
        sharpe = 0.0
    return dict(final_eq=final_eq, cagr=cagr, max_dd=max_dd, sharpe=sharpe, years=years)

m = calc_metrics(portfolio_curve, TOTAL_CAPITAL)


# ── Save CSVs ─────────────────────────────────────────────────────────────────
eq_csv  = OUT_DIR / "backtest_two_sleeves_v1_3_equity_curve.csv"
tr_csv  = OUT_DIR / "backtest_two_sleeves_v1_3_trades.csv"
reb_csv = OUT_DIR / "backtest_two_sleeves_v1_3_rebalance_events.csv"

with open(eq_csv, "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=portfolio_curve[0].keys())
    wr.writeheader(); wr.writerows(portfolio_curve)
if all_trades:
    with open(tr_csv, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=all_trades[0].keys())
        wr.writeheader(); wr.writerows(all_trades)
if rebalance_events:
    keys = sorted({k for e in rebalance_events for k in e})
    with open(reb_csv, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader(); wr.writerows(rebalance_events)


# ── Report ────────────────────────────────────────────────────────────────────
print()
print("=" * 80)
print("  RESULT — TwoSleeves v1.3 (CANDIDATE)")
print("=" * 80)
print(f"  Final equity                  ${m['final_eq']:>14,.0f}")
print(f"  CAGR                            {m['cagr']:>+13.2f}%")
print(f"  Max Drawdown                    {m['max_dd']:>+13.2f}%")
print(f"  Sharpe                          {m['sharpe']:>14.4f}")
print(f"  Real trades                     {len(all_trades):>14d}")
print(f"  Bars                            {n:>14d}")
print()
for sl in sleeves:
    cnt = sum(1 for t in all_trades if t["sleeve"] == sl["label"]
              and not t["vehicle"].endswith("_DEF"))
    print(f"  {sl['label']:<12} weight {sl['weight']:>6.2%}   vehicle trades {cnt:>3}")
print(f"  Rebalance events: {len(rebalance_events)}")
print(f"  VIX spike-driven exits: {spike_exit_count}")
print(f"  Period: {common[0]} -> {common[-1]} ({m['years']:.2f} years)")
print()
print("  v1.2 reference (same data): $37,913,438  +25.24%  -39.32%  0.9666")
print()
print(f"  Saved: {eq_csv.name}")
print(f"  Saved: {tr_csv.name}")
print(f"  Saved: {reb_csv.name}")
