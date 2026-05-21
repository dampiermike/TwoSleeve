#!/usr/bin/env python3
"""
TIME-IN-STATE DIAGNOSTIC for Two-Sleeves v1.1.

Each sleeve is, every bar, in exactly one of three states:
    3x  = leveraged vehicle (TQQQ / SPXL)
    1x  = defensive underlying (QQQ / SPY)
    BIL = cash state (T-bills)

This probe answers: are we in the RIGHT state at the right time?

For every bar, it records the actual state AND the return that bar of all
three instruments. Then per state it reports:
  - what the state we WERE in actually earned
  - the COUNTERFACTUAL: what the other two states would have earned over
    those same bars.

Reading it:
  * BIL bars where 3x would have CRASHED  -> BIL well-timed (saved us)
  * BIL bars where 3x would have RALLIED  -> too conservative (cost us)
  * 1x bars where 3x would have RALLIED   -> defensive left money behind
  * 1x bars where 3x would have CRASHED   -> defensive was right to wait
"""

import json, csv, math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"
BACKTEST_START = date(2000, 1, 1)


def load(ticker):
    raw = json.load(open(DATA_DIR / f"{ticker}_US.json"))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


# Equity curve gives per-bar state for each sleeve
with open(WORKSPACE / "backtest_two_sleeves_v1_1_equity_curve.csv") as f:
    curve = list(csv.DictReader(f))
dates = [r["date"] for r in curve]
n = len(dates)

tickers = ["TQQQ", "QQQ", "SPXL", "SPY", "BIL"]
raw = {t: load(t) for t in tickers}
adj = {t: [raw[t][d]["adjusted_close"] for d in dates] for t in tickers}

# Daily returns per instrument
ret = {}
for t in tickers:
    a = adj[t]
    ret[t] = [0.0] + [(a[i]/a[i-1] - 1) for i in range(1, n)]

SLEEVES = [
    dict(label="QQQ->TQQQ", state_col="s1_state", veh="TQQQ", dfn="QQQ"),
    dict(label="SPY->SPXL", state_col="s2_state", veh="SPXL", dfn="SPY"),
]

TRADING_YEAR = 252

def annualize(daily_rets):
    """Annualised return from a list of daily simple returns."""
    if not daily_rets: return 0.0
    growth = 1.0
    for r in daily_rets: growth *= (1 + r)
    yrs = len(daily_rets) / TRADING_YEAR
    return (growth ** (1/yrs) - 1) * 100 if yrs > 0 else 0.0

def cum(daily_rets):
    g = 1.0
    for r in daily_rets: g *= (1 + r)
    return (g - 1) * 100

def maxdd(daily_rets):
    peak = 1.0; g = 1.0; mdd = 0.0
    for r in daily_rets:
        g *= (1 + r)
        if g > peak: peak = g
        dd = (g - peak)/peak * 100
        if dd < mdd: mdd = dd
    return mdd


print("=" * 96)
print("  TIME-IN-STATE DIAGNOSTIC  —  Two-Sleeves v1.1")
print("=" * 96)

for sl in SLEEVES:
    states = [r[sl["state_col"]] for r in curve]
    veh, dfn = sl["veh"], sl["dfn"]

    # bucket bar indices by actual state
    buckets = {"vehicle": [], "defensive": [], "cash": []}
    for i in range(1, n):
        buckets[states[i]].append(i)

    print(f"\n{'='*96}")
    print(f"  {sl['label']}")
    print(f"{'='*96}")
    tot = n - 1
    for st, name, inst in [("vehicle", "3x  ("+veh+")", veh),
                           ("defensive", "1x  ("+dfn+")", dfn),
                           ("cash", "BIL (T-bills)", "BIL")]:
        idxs = buckets[st]
        share = len(idxs) / tot * 100
        actual = [ret[inst][i] for i in idxs]
        # counterfactual returns over the SAME bars
        cf_3x  = [ret[veh][i] for i in idxs]
        cf_1x  = [ret[dfn][i] for i in idxs]
        cf_bil = [ret["BIL"][i] for i in idxs]
        print(f"\n  ── State: {name}   {len(idxs)} bars ({share:.1f}% of time) ──")
        print(f"     ACTUAL ({inst:<4}) earned over these bars : cum {cum(actual):>+10.1f}%   "
              f"annlzd {annualize(actual):>+7.2f}%   maxDD {maxdd(actual):>+7.1f}%")
        print(f"     counterfactual — same bars held in:")
        print(f"        3x  {veh:<5}: cum {cum(cf_3x):>+10.1f}%   annlzd {annualize(cf_3x):>+7.2f}%   maxDD {maxdd(cf_3x):>+7.1f}%")
        print(f"        1x  {dfn:<5}: cum {cum(cf_1x):>+10.1f}%   annlzd {annualize(cf_1x):>+7.2f}%   maxDD {maxdd(cf_1x):>+7.1f}%")
        print(f"        BIL      : cum {cum(cf_bil):>+10.1f}%   annlzd {annualize(cf_bil):>+7.2f}%")

# Combined verdict block
print(f"\n{'='*96}")
print("  KEY QUESTIONS")
print(f"{'='*96}")
for sl in SLEEVES:
    states = [r[sl["state_col"]] for r in curve]
    veh, dfn = sl["veh"], sl["dfn"]
    cash_idx = [i for i in range(1, n) if states[i] == "cash"]
    def_idx  = [i for i in range(1, n) if states[i] == "defensive"]

    cash_3x = cum([ret[veh][i] for i in cash_idx])
    cash_bil = cum([ret["BIL"][i] for i in cash_idx])
    def_3x  = cum([ret[veh][i] for i in def_idx])
    def_1x  = cum([ret[dfn][i] for i in def_idx])

    print(f"\n  {sl['label']}:")
    verdict_cash = "BIL well-timed — 3x would have lost money" if cash_3x < cash_bil \
                   else "too conservative — 3x would have beaten BIL"
    print(f"    BIL bars : 3x would have returned {cash_3x:+.1f}%  vs BIL's {cash_bil:+.1f}%  -> {verdict_cash}")
    verdict_def = "defensive correct — 3x would have lost more" if def_3x < def_1x \
                  else "defensive left money behind — 3x would have beaten 1x"
    print(f"    1x  bars : 3x would have returned {def_3x:+.1f}%  vs 1x's {def_1x:+.1f}%  -> {verdict_def}")
