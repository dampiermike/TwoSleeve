#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized v1.2  —  Reference Implementation
  Per spec: TwoSleeves_Optimized_Build_Guide_v1_2.md

  CHANGE FROM v1.1: adds a 5th vehicle exit — the VIX-spike exit. While in
  the vehicle, if VIX[i] > SMA(VIX, 20) × 2.0, exit to defensive next open.
  No cooldown (same policy as vol_exit).

  Walk-forward validated: improves Sharpe on BOTH the 2000-2014 in-sample
  and 2015-2026 out-of-sample halves. The 5 spike events that triggered
  in 26+ years are all real, named vol shocks:
    Flash Crash 2010-05-07, Volmageddon 2018-02-05,
    COVID 2020-02-27, Japan carry-trade unwind 2024-08-05.

  Locked spec data window: 2000-01-03 -> 2026-05-22 (6635 bars).
═══════════════════════════════════════════════════════════════════════════════

DATA DEPENDENCY (7 JSON files; zero external APIs, no VectorVest):
  json/QQQ_US.json    - signal + defensive for sleeve 1   (real history)
  json/TQQQ_US.json   - vehicle for sleeve 1              (spliced: synth + real)
  json/SPY_US.json    - signal + defensive for sleeve 2   (real history)
  json/SPXL_US.json   - vehicle for sleeve 2              (spliced: synth + real)
  json/GLD_US.json    - safety sleeve                     (spliced: synth + real)
  json/BIL_US.json    - cash-state holding (T-bills)      (spliced: synth + real)
  json/VIX_INDX.json  - VIX index (powers the spike exit) (real history)

NO external dependencies — stdlib only.

SLEEVE CONFIGURATION (unchanged from v1.1):
  Sleeve 1 (45%  $45,000) : QQQ -> TQQQ  (defensive: QQQ)   WMA=10  SMA=175
  Sleeve 2 (45%  $45,000) : SPY -> SPXL  (defensive: SPY)   WMA= 5  SMA=200
  Sleeve 3 (10%  $10,000) : GLD          (buy and hold)
  Cash state              : BIL          (held while a sleeve is "in cash")
  Vehicle 5th exit        : VIX > SMA(VIX,20) x 2.0  -> rotate to defensive

OUTPUTS (written to this directory):
  backtest_two_sleeves_v1_2_equity_curve.csv
  backtest_two_sleeves_v1_2_trades.csv
  backtest_two_sleeves_v1_2_rebalance_events.csv
"""

import json
import csv
import math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"
OUT_DIR   = WORKSPACE

# ── Portfolio config ──────────────────────────────────────────────────────────
TOTAL_CAPITAL    = 100_000.0
SAFETY_TICKER    = "GLD"
SAFETY_ALLOC     = 0.10
SAFETY_INIT      = TOTAL_CAPITAL * SAFETY_ALLOC          # $10,000
EQ_ALLOC_EACH    = (TOTAL_CAPITAL - SAFETY_INIT) / 2     # $45,000 each
BACKTEST_START   = date(2000, 1, 1)
BACKTEST_END     = date(2026, 5, 22)     # v1.2 locked spec window
CASH_TICKER      = "BIL"

# ── Strategy config ───────────────────────────────────────────────────────────
VOL_PERIOD       = 20
VOL_ENTRY_MAX    = 16.0
VOL_EXIT_THRESH  = 30.0
TAKE_PROFIT_PCT  = 200.0
STOP_LOSS_PCT    = 12.0
DEF_STOP_PCT     = 18.0
COOLDOWN_DAYS    = 30

# ── NEW in v1.2: VIX spike exit ───────────────────────────────────────────────
VIX_TICKER       = "VIX_INDX"
VIX_MA_PERIOD    = 20            # SMA window on VIX close
VIX_SPIKE_MULT   = 2.0           # exit vehicle if VIX > SMA(VIX,20) * 2.0

# Per-sleeve optimum WMA/SMA (unchanged from v1.1)
EQUITY_CONFIGS = [
    ("QQQ", "TQQQ", "QQQ", 10, 175),
    ("SPY", "SPXL", "SPY",  5, 200),
]

MIN_IDX = max(VOL_PERIOD, VIX_MA_PERIOD,
              *(c[3] for c in EQUITY_CONFIGS),
              *(c[4] for c in EQUITY_CONFIGS))


# ── Indicator helpers ─────────────────────────────────────────────────────────
def compute_hvol(closes, window):
    """20-bar annualised realised vol on log returns. SAMPLE variance (÷N-1)."""
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
    path = DATA_DIR / f"{ticker}.json" if ticker == VIX_TICKER else DATA_DIR / f"{ticker}_US.json"
    if not path.exists():
        raise FileNotFoundError(f"Required data file missing: {path}")
    raw  = json.load(open(path))
    raw  = [r for r in raw
            if BACKTEST_START <= date.fromisoformat(r["date"]) <= BACKTEST_END]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


# ── Load all 7 tickers ────────────────────────────────────────────────────────
print()
print("=" * 80)
print("  TWO-SLEEVES OPTIMIZED v1.2  —  Per-Sleeve WMA/SMA  ·  Cash→BIL  ·  VIX spike exit")
print(f"  Equity sleeves : ${EQ_ALLOC_EACH:,.0f} each × 2  (90%)")
print(f"  Safety sleeve  : ${SAFETY_INIT:,.0f}        (10% GLD, buy & hold)")
print(f"  Cash state     : holds BIL (T-bills)")
print(f"  VIX spike exit : exit vehicle when VIX > SMA(VIX,{VIX_MA_PERIOD}) × {VIX_SPIKE_MULT}")
for s, v, d, wma, sma in EQUITY_CONFIGS:
    print(f"  {s:<3}->{v:<5} WMA={wma:>2} / SMA={sma:>3} | TP={TAKE_PROFIT_PCT:.0f}% "
          f"SL={STOP_LOSS_PCT:.0f}% VolEntry≤{VOL_ENTRY_MAX:.0f}% VolExit≥{VOL_EXIT_THRESH:.0f}%")
print("=" * 80)

all_tickers = {SAFETY_TICKER, CASH_TICKER, VIX_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS:
    all_tickers |= {s, v, d}

print("  Loading data …", end="", flush=True)
raw_data = {t: load_ticker(t) for t in sorted(all_tickers)}
print("  done.")

# Common date intersection across ALL 7 tickers
common = sorted(set.intersection(*[set(raw_data[t].keys()) for t in all_tickers]))
n = len(common)
print(f"  Common date range: {common[0]} -> {common[-1]}  ({n} bars)\n")


# ── Per-ticker arrays ─────────────────────────────────────────────────────────
arrays = {}
for ticker, d in raw_data.items():
    closes = [d[day]["close"]          for day in common]
    adjs   = [d[day]["adjusted_close"] for day in common]
    opens  = [d[day]["open"]           for day in common]
    ratios = [a / c if c else 1.0 for a, c in zip(adjs, closes)]
    arrays[ticker] = dict(closes=closes, adj=adjs, opens=opens, ratio=ratios)

for s, v, d, wma, sma in EQUITY_CONFIGS:
    c = arrays[s]["closes"]
    arrays[s]["wma"]  = compute_wma(c, wma)
    arrays[s]["sma"]  = compute_sma(c, sma)
    arrays[s]["hvol"] = compute_hvol(c, VOL_PERIOD)

# v1.2: VIX series + its 20-bar SMA
vix_close = arrays[VIX_TICKER]["closes"]
vix_sma   = compute_sma(vix_close, VIX_MA_PERIOD)


# ── Sleeve initializer ────────────────────────────────────────────────────────
def make_sleeve(signal, vehicle, defensive, wma_period, sma_period, init_equity):
    return dict(
        signal=signal, vehicle=vehicle, defensive=defensive,
        wma_period=wma_period, sma_period=sma_period,
        label=f"{signal}->{vehicle}",
        state="cash", next_state=None,
        v_shares=0.0, v_entry=0.0, v_entry_date="", v_exit_rsn="",
        d_shares=0.0, d_entry=0.0, d_entry_date="", d_exit_rsn="",
        c_shares=0.0, cash=init_equity, equity=init_equity,
        wma_was_below=True, entry_eligible=False,
        cooldown=0,
    )

eq_sleeves = [make_sleeve(s, v, d, w, sm, EQ_ALLOC_EACH) for s, v, d, w, sm in EQUITY_CONFIGS]

# Both sleeves start in cash — convert initial $ into BIL
cash_adj0 = arrays[CASH_TICKER]["adj"][0]
for sl in eq_sleeves:
    sl["c_shares"] = sl["cash"] / cash_adj0
    sl["cash"]     = 0.0

gld_adj0   = arrays[SAFETY_TICKER]["adj"][0]
gld_shares = SAFETY_INIT / gld_adj0
gld_equity = SAFETY_INIT


# ── Simulation loop ───────────────────────────────────────────────────────────
portfolio_curve  = []
rebalance_events = []
all_trades       = []
prev_year        = int(common[0][:4])
spike_exit_count = 0

for i in range(n):
    day = common[i]

    # Phase 1: execute pending transitions
    for sl in eq_sleeves:
        if sl["next_state"] is None:
            continue
        veh, dfn = sl["vehicle"], sl["defensive"]
        vo  = arrays[veh]["opens"][i]         * arrays[veh]["ratio"][i]
        do  = arrays[dfn]["opens"][i]         * arrays[dfn]["ratio"][i]
        co  = arrays[CASH_TICKER]["opens"][i] * arrays[CASH_TICKER]["ratio"][i]

        if sl["state"] == "vehicle":
            proceeds = sl["v_shares"] * vo
            pnl_pct  = (vo - sl["v_entry"]) / sl["v_entry"] * 100.0
            hold     = (date.fromisoformat(day) - date.fromisoformat(sl["v_entry_date"])).days
            all_trades.append({
                "sleeve": sl["label"], "vehicle": sl["vehicle"],
                "entry_date": sl["v_entry_date"], "entry_price": round(sl["v_entry"], 4),
                "exit_date": day, "exit_price": round(vo, 4),
                "pnl_pct": round(pnl_pct, 4), "hold_days": hold,
                "exit_reason": sl["v_exit_rsn"],
            })
            sl["cash"] = proceeds; sl["v_shares"] = 0.0; sl["v_entry"] = 0.0
        elif sl["state"] == "defensive":
            proceeds = sl["d_shares"] * do
            pnl_pct  = (do - sl["d_entry"]) / sl["d_entry"] * 100.0 if sl["d_entry"] else 0.0
            hold     = (date.fromisoformat(day) - date.fromisoformat(sl["d_entry_date"])).days
            reason   = sl["d_exit_rsn"] if sl["d_exit_rsn"] else "def_to_" + sl["next_state"]
            all_trades.append({
                "sleeve": sl["label"], "vehicle": f"{sl['defensive']}_DEF",
                "entry_date": sl["d_entry_date"], "entry_price": round(sl["d_entry"], 4),
                "exit_date": day, "exit_price": round(do, 4),
                "pnl_pct": round(pnl_pct, 4), "hold_days": hold,
                "exit_reason": reason,
            })
            sl["cash"] = proceeds; sl["d_shares"] = 0.0; sl["d_entry"] = 0.0; sl["d_exit_rsn"] = ""
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

    # Phase 2: cooldown decrement
    for sl in eq_sleeves:
        if sl["cooldown"] > 0:
            sl["cooldown"] -= 1

    # Phase 3: mark to market (INCLUDING GLD and BIL)
    for sl in eq_sleeves:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][i]
    gld_equity = gld_shares * arrays[SAFETY_TICKER]["adj"][i]

    # Phase 4: annual rebalance
    cur_year = int(day[:4])
    if cur_year > prev_year:
        total_eq   = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
        eq_target  = total_eq * (EQ_ALLOC_EACH / TOTAL_CAPITAL)
        gld_target = total_eq * (SAFETY_INIT   / TOTAL_CAPITAL)

        event = {"date": day, "total_equity": round(total_eq, 2),
                 "eq_target": round(eq_target, 2), "gld_target": round(gld_target, 2)}

        for sl in eq_sleeves:
            pre = sl["equity"]
            if sl["state"] == "vehicle":
                sl["v_shares"] = eq_target / arrays[sl["vehicle"]]["adj"][i]
                sl["equity"]   = eq_target
            elif sl["state"] == "defensive":
                sl["d_shares"] = eq_target / arrays[sl["defensive"]]["adj"][i]
                sl["equity"]   = eq_target
            else:
                sl["c_shares"] = eq_target / arrays[CASH_TICKER]["adj"][i]
                sl["equity"]   = eq_target
            event[f"{sl['label']}_pre"]   = round(pre, 2)
            event[f"{sl['label']}_delta"] = round(eq_target - pre, 2)

        gld_pre    = gld_equity
        gld_shares = gld_target / arrays[SAFETY_TICKER]["adj"][i]
        gld_equity = gld_target
        event["GLD_pre"]   = round(gld_pre, 2)
        event["GLD_delta"] = round(gld_target - gld_pre, 2)

        rebalance_events.append(event)

    prev_year = cur_year

    # Phase 5: record portfolio equity
    port_eq = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
    portfolio_curve.append({
        "date": day, "equity": round(port_eq, 2),
        "s1_qqq_tqqq": round(eq_sleeves[0]["equity"], 2),
        "s2_spy_spxl": round(eq_sleeves[1]["equity"], 2),
        "s3_gld":      round(gld_equity, 2),
        "s1_state":    eq_sleeves[0]["state"],
        "s2_state":    eq_sleeves[1]["state"],
        "vix":         round(vix_close[i], 2),
        "vix_sma":     round(vix_sma[i], 2) if vix_sma[i] is not None else None,
    })

    if i < MIN_IDX:
        continue

    # v1.2: VIX spike condition for this bar
    vix_now = vix_close[i]
    vix_ma_now = vix_sma[i]
    vix_spike  = (vix_ma_now is not None and vix_now > vix_ma_now * VIX_SPIKE_MULT)

    # Phase 6: signal logic — sets next_state for bar i+1
    for sl in eq_sleeves:
        sig, veh = sl["signal"], sl["vehicle"]
        wa  = arrays[sig]["wma"]; sa = arrays[sig]["sma"]; hva = arrays[sig]["hvol"]
        if any(v is None for v in [wa[i], sa[i], wa[i-1], sa[i-1]]):
            continue

        w, wp = wa[i], wa[i-1]; s, sp = sa[i], sa[i-1]
        hv    = hva[i] if hva[i] is not None else 0.0
        cab   = wp <= sp and w >  s
        cbl   = wp >= sp and w <  s

        if sl["state"] == "vehicle" and sl["next_state"] is None:
            vad   = arrays[veh]["adj"][i]
            tp_p  = sl["v_entry"] * (1 + TAKE_PROFIT_PCT / 100)
            sl_p  = sl["v_entry"] * (1 - STOP_LOSS_PCT   / 100)
            do_tp = vad >= tp_p
            do_sl = vad <= sl_p
            do_v  = hv >= VOL_EXIT_THRESH
            do_w  = cbl
            do_spike = vix_spike      # v1.2: 5th vehicle exit
            if do_tp or do_sl or do_v or do_w or do_spike:
                if do_tp:    sl["v_exit_rsn"] = f"take_profit({TAKE_PROFIT_PCT:.0f}%)"
                elif do_sl:
                    sl["v_exit_rsn"] = f"stop_loss({STOP_LOSS_PCT:.0f}%)"
                    sl["cooldown"] = COOLDOWN_DAYS
                elif do_v:   sl["v_exit_rsn"] = f"vol_exit({hv:.1f}%)"
                elif do_w:   sl["v_exit_rsn"] = "wma_cross_below"
                else:
                    sl["v_exit_rsn"] = f"vix_spike({VIX_SPIKE_MULT}x_MA{VIX_MA_PERIOD})"
                    spike_exit_count += 1
                sl["wma_was_below"] = False
                sl["next_state"]    = "defensive"

        # Defensive stop -> cash
        if sl["state"] == "defensive" and sl["next_state"] is None:
            dad = arrays[sl["defensive"]]["adj"][i]
            if sl["d_entry"] > 0 and dad <= sl["d_entry"] * (1 - DEF_STOP_PCT / 100):
                sl["d_exit_rsn"] = f"def_stop({DEF_STOP_PCT:.0f}%)"
                sl["cooldown"]   = COOLDOWN_DAYS
                sl["next_state"] = "cash"

        # Latch
        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if w < s: sl["wma_was_below"] = True; sl["entry_eligible"] = False
            if cab and sl["wma_was_below"]: sl["entry_eligible"] = True; sl["wma_was_below"] = False
            if sl["entry_eligible"] and w < s: sl["entry_eligible"] = False; sl["wma_was_below"] = True

        # Vehicle entry
        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if (sl["entry_eligible"] and hv <= VOL_ENTRY_MAX
                    and w > s and i + 1 < n and sl["cooldown"] == 0):
                sl["next_state"] = "vehicle"
                sl["entry_eligible"] = False; sl["wma_was_below"] = False


# ── Close open positions at last bar (for trade log only) ─────────────────────
last_day = common[-1]
for sl in eq_sleeves:
    veh = sl["vehicle"]; dfn = sl["defensive"]
    if sl["state"] == "vehicle" and sl["v_shares"] > 0:
        last = arrays[veh]["adj"][-1]
        pnl  = (last - sl["v_entry"]) / sl["v_entry"] * 100.0
        hold = (date.fromisoformat(last_day) - date.fromisoformat(sl["v_entry_date"])).days
        all_trades.append({
            "sleeve": sl["label"], "vehicle": veh,
            "entry_date": sl["v_entry_date"], "entry_price": round(sl["v_entry"], 4),
            "exit_date": last_day, "exit_price": round(last, 4),
            "pnl_pct": round(pnl, 4), "hold_days": hold, "exit_reason": "end_of_data",
        })
        sl["equity"] = sl["v_shares"] * last
    elif sl["state"] == "defensive" and sl["d_shares"] > 0:
        last = arrays[dfn]["adj"][-1]
        pnl  = (last - sl["d_entry"]) / sl["d_entry"] * 100.0
        hold = (date.fromisoformat(last_day) - date.fromisoformat(sl["d_entry_date"])).days
        all_trades.append({
            "sleeve": sl["label"], "vehicle": f"{dfn}_DEF",
            "entry_date": sl["d_entry_date"], "entry_price": round(sl["d_entry"], 4),
            "exit_date": last_day, "exit_price": round(last, 4),
            "pnl_pct": round(pnl, 4), "hold_days": hold, "exit_reason": "end_of_data",
        })
        sl["equity"] = sl["d_shares"] * last
    elif sl["state"] == "cash" and sl["c_shares"] > 0:
        sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1]

gld_equity = gld_shares * arrays[SAFETY_TICKER]["adj"][-1]
port_final = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
portfolio_curve[-1]["equity"]      = round(port_final, 2)
portfolio_curve[-1]["s1_qqq_tqqq"] = round(eq_sleeves[0]["equity"], 2)
portfolio_curve[-1]["s2_spy_spxl"] = round(eq_sleeves[1]["equity"], 2)
portfolio_curve[-1]["s3_gld"]      = round(gld_equity, 2)


# ── Metrics ───────────────────────────────────────────────────────────────────
def calc_metrics(curve, init_eq):
    final_eq = curve[-1]["equity"]
    total_return = (final_eq - init_eq) / init_eq * 100.0
    years = (date.fromisoformat(curve[-1]["date"]) - date.fromisoformat(curve[0]["date"])).days / 365.25
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
    return dict(final_eq=final_eq, total_return=total_return, cagr=cagr,
                max_dd=max_dd, sharpe=sharpe, years=years)

port_m = calc_metrics(portfolio_curve, TOTAL_CAPITAL)


# ── Save CSVs ─────────────────────────────────────────────────────────────────
eq_csv  = OUT_DIR / "backtest_two_sleeves_v1_2_equity_curve.csv"
tr_csv  = OUT_DIR / "backtest_two_sleeves_v1_2_trades.csv"
reb_csv = OUT_DIR / "backtest_two_sleeves_v1_2_rebalance_events.csv"

with open(eq_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=portfolio_curve[0].keys())
    writer.writeheader(); writer.writerows(portfolio_curve)
if all_trades:
    with open(tr_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_trades[0].keys())
        writer.writeheader(); writer.writerows(all_trades)
if rebalance_events:
    with open(reb_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rebalance_events[0].keys())
        writer.writeheader(); writer.writerows(rebalance_events)


# ── Report ────────────────────────────────────────────────────────────────────
qqq_trades = sum(1 for t in all_trades if t["sleeve"] == "QQQ->TQQQ")
spy_trades = sum(1 for t in all_trades if t["sleeve"] == "SPY->SPXL")
spike_logged = [t for t in all_trades if t["exit_reason"].startswith("vix_spike")]

print()
print("=" * 80)
print("  RESULT — TwoSleeves v1.2")
print("=" * 80)
print(f"  Final equity                  ${port_m['final_eq']:>14,.0f}")
print(f"  CAGR                            {port_m['cagr']:>+13.2f}%")
print(f"  Max Drawdown                    {port_m['max_dd']:>+13.2f}%")
print(f"  Sharpe                          {port_m['sharpe']:>14.4f}")
print(f"  Real trades                     {len(all_trades):>14d}")
print(f"  Bars                            {n:>14d}")
print()
print(f"  Trade breakdown: QQQ->TQQQ={qqq_trades}  SPY->SPXL={spy_trades}")
print(f"  Rebalance events: {len(rebalance_events)}")
print(f"  VIX spike-driven exits: {spike_exit_count}")
if spike_logged:
    print("  Spike-exit trades logged:")
    for t in spike_logged:
        print(f"    {t['sleeve']:<12} {t['entry_date']} -> {t['exit_date']}  "
              f"pnl {float(t['pnl_pct']):+7.2f}%   {t['exit_reason']}")
print(f"  Period: {common[0]} -> {common[-1]} ({port_m['years']:.2f} years)")
print()
print(f"  Saved: {eq_csv.name}")
print(f"  Saved: {tr_csv.name}")
print(f"  Saved: {reb_csv.name}")
