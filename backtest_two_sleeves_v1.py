#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized v1  —  Reference Implementation
  Per spec: TwoSleeves_Optimized_Build_Guide_v1.md

  Target numbers (PRECISE):
    Final equity : $35,448,247
    CAGR         : +25.10%
    Max DD       : -37.99%
    Sharpe       : 0.8373
    Real trades  : 86  (38 QQQ->TQQQ + 48 SPY->SPXL)
    Bars         : 6,594  (2000-01-03 -> 2026-03-23)
═══════════════════════════════════════════════════════════════════════════════

DATA DEPENDENCY (zero external APIs, no VectorVest, pure JSON files):
  json/QQQ_US.json   - signal + defensive for sleeve 1   (real history)
  json/TQQQ_US.json  - vehicle for sleeve 1              (spliced: synth + real)
  json/SPY_US.json   - signal + defensive for sleeve 2   (real history)
  json/SPXL_US.json  - vehicle for sleeve 2              (spliced: synth + real)
  json/GLD_US.json   - safety sleeve                     (spliced: synth + real)

  VIX is NOT required for v1 (no pyramid sizing). Future v2 with pyramid
  will need json/VIX_INDX.json.

NO external dependencies — stdlib only (json, csv, math, datetime, pathlib).
NO VectorVest data, NO web requests, NO third-party packages.

SLEEVE CONFIGURATION:
  Sleeve 1 (45%  $45,000) : QQQ -> TQQQ  (defensive: QQQ)   WMA=10  SMA=175
  Sleeve 2 (45%  $45,000) : SPY -> SPXL  (defensive: SPY)   WMA= 5  SMA=200
  Sleeve 3 (10%  $10,000) : GLD          (buy and hold)

OUTPUTS (written to this directory):
  backtest_two_sleeves_v1_equity_curve.csv      — daily portfolio + per-sleeve
  backtest_two_sleeves_v1_trades.csv            — entry/exit trade log
  backtest_two_sleeves_v1_rebalance_events.csv  — annual rebalance detail
"""

import json
import csv
import math
from datetime import date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
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

# ── Strategy config ───────────────────────────────────────────────────────────
VOL_PERIOD       = 20         # HVol window (both signal tickers)
VOL_ENTRY_MAX    = 16.0       # Max signal HVol to allow new vehicle entry
VOL_EXIT_THRESH  = 30.0       # Signal HVol that forces vehicle exit
TAKE_PROFIT_PCT  = 200.0      # +200% (vehicle ≥ 3.0× entry)
STOP_LOSS_PCT    = 12.0       # -12%
DEF_STOP_PCT     = 18.0       # -18% defensive stop
COOLDOWN_DAYS    = 30         # Cooldown after hard stop OR defensive stop

# Per-sleeve optimum WMA/SMA — v1's core change from v3
EQUITY_CONFIGS = [
    # (signal, vehicle, defensive, wma_period, sma_period)
    ("QQQ", "TQQQ", "QQQ", 10, 175),
    ("SPY", "SPXL", "SPY",  5, 200),
]

# MIN_IDX = longest warmup across both sleeves (must reach for any signal)
MIN_IDX = max(VOL_PERIOD, *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


# ── Indicator helpers ─────────────────────────────────────────────────────────
def compute_hvol(closes, window):
    """20-bar annualised realised vol on log returns. SAMPLE variance (÷N-1)."""
    n, out = len(closes), [None] * len(closes)
    for i in range(window, n):
        lr   = [math.log(closes[j] / closes[j-1]) for j in range(i - window + 1, i + 1)]
        mean = sum(lr) / window
        var  = sum((r - mean)**2 for r in lr) / (window - 1)   # ÷N-1 sample var
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
    s = sum(closes[:period]); out[period - 1] = s / period
    for i in range(period, n):
        s += closes[i] - closes[i - period]; out[i] = s / period
    return out


# ── Data loader ───────────────────────────────────────────────────────────────
def load_ticker(ticker):
    """Load a single JSON file. Filters to BACKTEST_START and sorts ascending."""
    path = DATA_DIR / f"{ticker}_US.json"
    if not path.exists():
        raise FileNotFoundError(f"Required data file missing: {path}")
    raw  = json.load(open(path))
    raw  = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


# ── Load all tickers ──────────────────────────────────────────────────────────
print()
print("=" * 80)
print("  TWO-SLEEVES OPTIMIZED v1  —  Per-Sleeve WMA/SMA")
print(f"  Equity sleeves : ${EQ_ALLOC_EACH:,.0f} each × 2  (90%)")
print(f"  Safety sleeve  : ${SAFETY_INIT:,.0f}        (10% GLD, buy & hold)")
for s, v, d, wma, sma in EQUITY_CONFIGS:
    print(f"  {s:<3}->{v:<5} WMA={wma:>2} / SMA={sma:>3} | TP={TAKE_PROFIT_PCT:.0f}% "
          f"SL={STOP_LOSS_PCT:.0f}% VolEntry≤{VOL_ENTRY_MAX:.0f}% VolExit≥{VOL_EXIT_THRESH:.0f}%")
print("=" * 80)

all_tickers = {SAFETY_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS:
    all_tickers |= {s, v, d}

print("  Loading data …", end="", flush=True)
raw_data = {t: load_ticker(t) for t in sorted(all_tickers)}
print("  done.")

# Common date intersection across ALL tickers
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

# Indicators per equity sleeve (signal ticker only)
for s, v, d, wma, sma in EQUITY_CONFIGS:
    c = arrays[s]["closes"]
    arrays[s]["wma"]  = compute_wma(c, wma)
    arrays[s]["sma"]  = compute_sma(c, sma)
    arrays[s]["hvol"] = compute_hvol(c, VOL_PERIOD)


# ── Sleeve initializer ────────────────────────────────────────────────────────
def make_sleeve(signal, vehicle, defensive, wma_period, sma_period, init_equity):
    return dict(
        signal=signal, vehicle=vehicle, defensive=defensive,
        wma_period=wma_period, sma_period=sma_period,
        label=f"{signal}->{vehicle}",
        state="cash", next_state=None,
        v_shares=0.0, v_entry=0.0, v_entry_date="", v_exit_rsn="",
        d_shares=0.0, d_entry=0.0, d_entry_date="", d_exit_rsn="",
        cash=init_equity, equity=init_equity,
        wma_was_below=True, entry_eligible=False,
        cooldown=0,
    )

eq_sleeves = [make_sleeve(s, v, d, w, sm, EQ_ALLOC_EACH) for s, v, d, w, sm in EQUITY_CONFIGS]

# GLD safety sleeve
gld_adj0   = arrays[SAFETY_TICKER]["adj"][0]
gld_shares = SAFETY_INIT / gld_adj0
gld_equity = SAFETY_INIT


# ── Simulation loop ───────────────────────────────────────────────────────────
portfolio_curve  = []
rebalance_events = []
all_trades       = []
prev_year        = int(common[0][:4])

for i in range(n):
    day = common[i]

    # ── Phase 1: execute pending transitions at today's open ──────────────────
    for sl in eq_sleeves:
        if sl["next_state"] is None:
            continue
        veh = sl["vehicle"]; dfn = sl["defensive"]
        vo  = arrays[veh]["opens"][i] * arrays[veh]["ratio"][i]
        do  = arrays[dfn]["opens"][i] * arrays[dfn]["ratio"][i]

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

        if sl["next_state"] == "vehicle":
            sl["v_shares"] = sl["cash"] / vo; sl["v_entry"] = vo
            sl["v_entry_date"] = day; sl["cash"] = 0.0
        elif sl["next_state"] == "defensive":
            sl["d_shares"] = sl["cash"] / do; sl["d_entry"] = do
            sl["d_entry_date"] = day; sl["cash"] = 0.0

        sl["state"] = sl["next_state"]; sl["next_state"] = None

    # ── Phase 2: cooldown decrement ───────────────────────────────────────────
    for sl in eq_sleeves:
        if sl["cooldown"] > 0:
            sl["cooldown"] -= 1

    # ── Phase 3: mark to market (INCLUDING GLD — must precede rebalance) ──────
    for sl in eq_sleeves:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
        else:
            sl["equity"] = sl["cash"]

    gld_equity = gld_shares * arrays[SAFETY_TICKER]["adj"][i]

    # ── Phase 4: annual rebalance ─────────────────────────────────────────────
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
                sl["cash"]   = eq_target
                sl["equity"] = eq_target
            event[f"{sl['label']}_pre"]   = round(pre, 2)
            event[f"{sl['label']}_delta"] = round(eq_target - pre, 2)

        gld_pre    = gld_equity
        gld_shares = gld_target / arrays[SAFETY_TICKER]["adj"][i]
        gld_equity = gld_target
        event["GLD_pre"]   = round(gld_pre, 2)
        event["GLD_delta"] = round(gld_target - gld_pre, 2)

        rebalance_events.append(event)

    prev_year = cur_year

    # ── Phase 5: record portfolio equity ──────────────────────────────────────
    port_eq = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
    portfolio_curve.append({
        "date": day, "equity": round(port_eq, 2),
        "s1_qqq_tqqq": round(eq_sleeves[0]["equity"], 2),
        "s2_spy_spxl": round(eq_sleeves[1]["equity"], 2),
        "s3_gld":      round(gld_equity, 2),
        "s1_state":    eq_sleeves[0]["state"],
        "s2_state":    eq_sleeves[1]["state"],
    })

    if i < MIN_IDX:
        continue

    # ── Phase 6: signal logic — sets next_state for bar i+1 ───────────────────
    for sl in eq_sleeves:
        sig = sl["signal"]; veh = sl["vehicle"]
        wa  = arrays[sig]["wma"]; sa = arrays[sig]["sma"]; hva = arrays[sig]["hvol"]
        if any(v is None for v in [wa[i], sa[i], wa[i-1], sa[i-1]]):
            continue

        w, wp = wa[i], wa[i-1]; s, sp = sa[i], sa[i-1]
        hv    = hva[i] if hva[i] is not None else 0.0
        cab   = wp <= sp and w >  s   # cross above
        cbl   = wp >= sp and w <  s   # cross below

        # Vehicle exits (priority order)
        if sl["state"] == "vehicle" and sl["next_state"] is None:
            vad   = arrays[veh]["adj"][i]
            tp_p  = sl["v_entry"] * (1 + TAKE_PROFIT_PCT / 100)
            sl_p  = sl["v_entry"] * (1 - STOP_LOSS_PCT   / 100)
            do_tp = vad >= tp_p
            do_sl = vad <= sl_p
            do_v  = hv >= VOL_EXIT_THRESH
            do_w  = cbl
            if do_tp or do_sl or do_v or do_w:
                if do_tp:    sl["v_exit_rsn"] = f"take_profit({TAKE_PROFIT_PCT:.0f}%)"
                elif do_sl:
                    sl["v_exit_rsn"] = f"stop_loss({STOP_LOSS_PCT:.0f}%)"
                    sl["cooldown"] = COOLDOWN_DAYS
                elif do_v:   sl["v_exit_rsn"] = f"vol_exit({hv:.1f}%)"
                else:        sl["v_exit_rsn"] = "wma_cross_below"
                sl["wma_was_below"] = False
                sl["next_state"]    = "defensive"

        # Defensive stop -> cash
        if sl["state"] == "defensive" and sl["next_state"] is None:
            dad = arrays[sl["defensive"]]["adj"][i]
            if sl["d_entry"] > 0 and dad <= sl["d_entry"] * (1 - DEF_STOP_PCT / 100):
                sl["d_exit_rsn"] = f"def_stop({DEF_STOP_PCT:.0f}%)"
                sl["cooldown"]   = COOLDOWN_DAYS
                sl["next_state"] = "cash"

        # Latch logic (cash / defensive states)
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
eq_csv  = OUT_DIR / "backtest_two_sleeves_v1_equity_curve.csv"
tr_csv  = OUT_DIR / "backtest_two_sleeves_v1_trades.csv"
reb_csv = OUT_DIR / "backtest_two_sleeves_v1_rebalance_events.csv"

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

print()
print("=" * 80)
print("  RESULT  vs  SPEC TARGETS (TwoSleeves_Optimized_Build_Guide_v1.md)")
print("=" * 80)
TARGETS = dict(final_eq=35_448_247, cagr=25.10, max_dd=-37.99, sharpe=0.8373,
               trades=86, bars=6594)

def check(name, value, target, fmt, tol=None, eq=False):
    if eq:
        ok = abs(value - target) < (tol or 1)
    else:
        ok = abs(value - target) < (tol or 0.01)
    mark = "✓" if ok else "✗"
    return f"  {name:<22}  {fmt.format(value):>20}  target {fmt.format(target):>20}  {mark}"

print(check("Final equity",     port_m["final_eq"], TARGETS["final_eq"], "${:>13,.0f}", tol=1, eq=True))
print(check("CAGR",             port_m["cagr"],     TARGETS["cagr"],     "{:>+7.2f}%"))
print(check("Max Drawdown",     port_m["max_dd"],   TARGETS["max_dd"],   "{:>+7.2f}%"))
print(check("Sharpe",           port_m["sharpe"],   TARGETS["sharpe"],   "{:>8.4f}",  tol=0.0001))
print(check("Real trades",      len(all_trades),    TARGETS["trades"],   "{:>3d}",    tol=1, eq=True))
print(check("Bars",             n,                  TARGETS["bars"],     "{:>5d}",    tol=1, eq=True))
print()
print(f"  Trade breakdown: QQQ->TQQQ={qqq_trades}  SPY->SPXL={spy_trades}")
print(f"  Rebalance events: {len(rebalance_events)}")
print(f"  Period: {common[0]} -> {common[-1]} ({port_m['years']:.2f} years)")
print()
print(f"  Saved: {eq_csv.name}")
print(f"  Saved: {tr_csv.name}")
print(f"  Saved: {reb_csv.name}")
