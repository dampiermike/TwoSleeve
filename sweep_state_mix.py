#!/usr/bin/env python3
"""
STATE-MIX SWEEP for Two-Sleeves v1.1.

Jointly sweeps the two parameters that shift the 3x / 1x / BIL time mix
WITHOUT needing a better crash predictor — they only move where the
boundaries are drawn:

  VOL_ENTRY_MAX  (v1.1 = 16.0)  — looser gate => more 3x time
  COOLDOWN_DAYS  (v1.1 = 30)    — shorter => faster 3x re-entry, less dead time

Everything else held at v1.1 spec. Reports final equity, CAGR, MaxDD,
Sharpe, and the resulting time-in-state mix for each combination.
"""

import json, math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

TOTAL_CAPITAL   = 100_000.0
SAFETY_INIT     = 10_000.0
EQ_ALLOC_EACH   = 45_000.0
BACKTEST_START  = date(2000, 1, 1)
CASH_TICKER     = "BIL"

VOL_PERIOD      = 20
VOL_EXIT_THRESH = 30.0
TAKE_PROFIT_PCT = 200.0
STOP_LOSS_PCT   = 12.0
DEF_STOP_PCT    = 18.0

EQUITY_CONFIGS = [
    ("QQQ", "TQQQ", "QQQ", 10, 175),
    ("SPY", "SPXL", "SPY",  5, 200),
]

VOL_ENTRY_SWEEP = [12.0, 14.0, 16.0, 18.0, 20.0, 24.0]
COOLDOWN_SWEEP  = [0, 10, 20, 30, 45, 60]


def compute_hvol(c, w):
    n, out = len(c), [None]*len(c)
    for i in range(w, n):
        lr = [math.log(c[j]/c[j-1]) for j in range(i-w+1, i+1)]
        m = sum(lr)/w; v = sum((r-m)**2 for r in lr)/(w-1)
        out[i] = math.sqrt(v*252)*100.0
    return out
def compute_wma(c, p):
    n, out = len(c), [None]*len(c); denom = p*(p+1)/2
    for i in range(p-1, n):
        out[i] = sum(c[i-p+1+j]*(j+1) for j in range(p)) / denom
    return out
def compute_sma(c, p):
    n, out = len(c), [None]*len(c); s = sum(c[:p]); out[p-1] = s/p
    for i in range(p, n):
        s += c[i] - c[i-p]; out[i] = s/p
    return out

def load_ticker(t):
    raw = json.load(open(DATA_DIR / f"{t}_US.json"))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


print("Loading data...", flush=True)
tickers = {"GLD", CASH_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS: tickers |= {s, v, d}
raw_data = {t: load_ticker(t) for t in tickers}
common   = sorted(set.intersection(*[set(raw_data[t].keys()) for t in tickers]))
n = len(common)
print(f"  {n} bars  {common[0]} -> {common[-1]}\n")

arrays = {}
for tk, d in raw_data.items():
    closes = [d[day]["close"]          for day in common]
    adjs   = [d[day]["adjusted_close"] for day in common]
    opens  = [d[day]["open"]           for day in common]
    ratios = [a/c if c else 1.0 for a, c in zip(adjs, closes)]
    arrays[tk] = dict(closes=closes, adj=adjs, opens=opens, ratio=ratios)

for s, v, d, wma, sma in EQUITY_CONFIGS:
    c = arrays[s]["closes"]
    arrays[s]["wma"]  = compute_wma(c, wma)
    arrays[s]["sma"]  = compute_sma(c, sma)
    arrays[s]["hvol"] = compute_hvol(c, VOL_PERIOD)

MIN_IDX = max(VOL_PERIOD, *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


def run(vol_entry_max, cooldown_days):
    def make_sleeve(signal, vehicle, defensive, wma, sma):
        return dict(signal=signal, vehicle=vehicle, defensive=defensive,
                    wma_period=wma, sma_period=sma,
                    state="cash", next_state=None,
                    v_shares=0.0, v_entry=0.0, d_shares=0.0, d_entry=0.0,
                    c_shares=0.0, cash=0.0, equity=EQ_ALLOC_EACH,
                    wma_was_below=True, entry_eligible=False, cooldown=0, trades=0)
    eq_sleeves = [make_sleeve(*cfg) for cfg in EQUITY_CONFIGS]
    cash_adj0 = arrays[CASH_TICKER]["adj"][0]
    for sl in eq_sleeves:
        sl["c_shares"] = EQ_ALLOC_EACH / cash_adj0
    gld_shares = SAFETY_INIT / arrays["GLD"]["adj"][0]
    gld_equity = SAFETY_INIT
    portfolio = []
    prev_year = int(common[0][:4])
    # state-bar counters (summed across both sleeves)
    bars_3x = bars_1x = bars_bil = 0

    for i in range(n):
        day = common[i]
        for sl in eq_sleeves:
            if sl["next_state"] is None: continue
            veh = sl["vehicle"]; dfn = sl["defensive"]
            vo = arrays[veh]["opens"][i] * arrays[veh]["ratio"][i]
            do = arrays[dfn]["opens"][i] * arrays[dfn]["ratio"][i]
            co = arrays[CASH_TICKER]["opens"][i] * arrays[CASH_TICKER]["ratio"][i]
            if sl["state"] == "vehicle":
                sl["cash"] = sl["v_shares"]*vo; sl["trades"] += 1
                sl["v_shares"] = 0.0; sl["v_entry"] = 0.0
            elif sl["state"] == "defensive":
                sl["cash"] = sl["d_shares"]*do; sl["trades"] += 1
                sl["d_shares"] = 0.0; sl["d_entry"] = 0.0
            elif sl["state"] == "cash":
                sl["cash"] = sl["c_shares"]*co; sl["c_shares"] = 0.0
            if sl["next_state"] == "vehicle":
                sl["v_shares"] = sl["cash"]/vo; sl["v_entry"] = vo
            elif sl["next_state"] == "defensive":
                sl["d_shares"] = sl["cash"]/do; sl["d_entry"] = do
            elif sl["next_state"] == "cash":
                sl["c_shares"] = sl["cash"]/co
            sl["cash"] = 0.0
            sl["state"] = sl["next_state"]; sl["next_state"] = None

        for sl in eq_sleeves:
            if sl["cooldown"] > 0: sl["cooldown"] -= 1

        for sl in eq_sleeves:
            if sl["state"] == "vehicle":
                sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i]
                bars_3x += 1
            elif sl["state"] == "defensive":
                sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
                bars_1x += 1
            else:
                sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][i]
                bars_bil += 1
        gld_equity = gld_shares * arrays["GLD"]["adj"][i]

        cur_year = int(day[:4])
        if cur_year > prev_year:
            total_eq = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
            eq_t = total_eq * 0.45; gld_t = total_eq * 0.10
            for sl in eq_sleeves:
                if sl["state"] == "vehicle":
                    sl["v_shares"] = eq_t / arrays[sl["vehicle"]]["adj"][i]
                elif sl["state"] == "defensive":
                    sl["d_shares"] = eq_t / arrays[sl["defensive"]]["adj"][i]
                else:
                    sl["c_shares"] = eq_t / arrays[CASH_TICKER]["adj"][i]
                sl["equity"] = eq_t
            gld_shares = gld_t / arrays["GLD"]["adj"][i]
            gld_equity = gld_t
        prev_year = cur_year

        portfolio.append(sum(sl["equity"] for sl in eq_sleeves) + gld_equity)
        if i < MIN_IDX: continue

        for sl in eq_sleeves:
            sig = sl["signal"]; veh = sl["vehicle"]
            wa = arrays[sig]["wma"]; sa = arrays[sig]["sma"]; hva = arrays[sig]["hvol"]
            if any(v is None for v in [wa[i], sa[i], wa[i-1], sa[i-1]]): continue
            w, wp = wa[i], wa[i-1]; s, sp = sa[i], sa[i-1]
            hv = hva[i] if hva[i] is not None else 0.0
            cab = wp <= sp and w > s; cbl = wp >= sp and w < s

            if sl["state"] == "vehicle" and sl["next_state"] is None:
                vad = arrays[veh]["adj"][i]
                do_tp = vad >= sl["v_entry"] * (1 + TAKE_PROFIT_PCT/100)
                do_sl = vad <= sl["v_entry"] * (1 - STOP_LOSS_PCT/100)
                do_v  = hv >= VOL_EXIT_THRESH
                do_w  = cbl
                if do_tp or do_sl or do_v or do_w:
                    if do_sl: sl["cooldown"] = cooldown_days
                    sl["wma_was_below"] = False; sl["next_state"] = "defensive"

            if sl["state"] == "defensive" and sl["next_state"] is None:
                dad = arrays[sl["defensive"]]["adj"][i]
                if sl["d_entry"] > 0 and dad <= sl["d_entry"] * (1 - DEF_STOP_PCT/100):
                    sl["cooldown"] = cooldown_days; sl["next_state"] = "cash"

            if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
                if w < s: sl["wma_was_below"] = True; sl["entry_eligible"] = False
                if cab and sl["wma_was_below"]: sl["entry_eligible"] = True; sl["wma_was_below"] = False
                if sl["entry_eligible"] and w < s: sl["entry_eligible"] = False; sl["wma_was_below"] = True

            if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
                if (sl["entry_eligible"] and hv <= vol_entry_max
                        and w > s and i + 1 < n and sl["cooldown"] == 0):
                    sl["next_state"] = "vehicle"
                    sl["entry_eligible"] = False; sl["wma_was_below"] = False

    for sl in eq_sleeves:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][-1]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][-1]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1]
    gld_equity = gld_shares * arrays["GLD"]["adj"][-1]
    portfolio[-1] = sum(sl["equity"] for sl in eq_sleeves) + gld_equity

    final_eq = portfolio[-1]
    years = (date.fromisoformat(common[-1]) - date.fromisoformat(common[0])).days / 365.25
    cagr = ((final_eq/TOTAL_CAPITAL)**(1/years) - 1)*100
    peak = TOTAL_CAPITAL; max_dd = 0.0
    for eq in portfolio:
        if eq > peak: peak = eq
        dd = (eq - peak)/peak * 100
        if dd < max_dd: max_dd = dd
    dr = [(portfolio[i]-portfolio[i-1])/portfolio[i-1] for i in range(1, len(portfolio)) if portfolio[i-1]]
    mu = sum(dr)/len(dr); sig = (sum((r-mu)**2 for r in dr)/(len(dr)-1))**0.5
    sharpe = mu/sig * math.sqrt(252) if sig else 0.0
    tot_sb = bars_3x + bars_1x + bars_bil
    return dict(final_eq=final_eq, cagr=cagr, max_dd=max_dd, sharpe=sharpe,
                trades=sum(sl["trades"] for sl in eq_sleeves),
                pct_3x=bars_3x/tot_sb*100, pct_1x=bars_1x/tot_sb*100,
                pct_bil=bars_bil/tot_sb*100)


print("=" * 108)
print("  STATE-MIX SWEEP  —  VOL_ENTRY_MAX x COOLDOWN_DAYS")
print("  v1.1 spec = VOL_ENTRY_MAX 16.0, COOLDOWN 30  ->  $50,081,555 / +26.76% / -37.46% / 0.8752")
print("=" * 108)
print(f"  {'VolEntry':>9} {'Cooldown':>9} {'Final $':>15} {'CAGR':>8} {'MaxDD':>9} {'Sharpe':>8} "
      f"{'3x%':>6} {'1x%':>6} {'BIL%':>6}")
print("-" * 108)

best = None
for ve in VOL_ENTRY_SWEEP:
    for cd in COOLDOWN_SWEEP:
        m = run(ve, cd)
        is_spec = (abs(ve-16.0) < 1e-6 and cd == 30)
        score = m["cagr"] / abs(m["max_dd"]) if m["max_dd"] else 0
        if best is None or m["final_eq"] > best[2]["final_eq"]:
            best = (ve, cd, m)
        tag = "  <- v1.1 spec" if is_spec else ""
        print(f"  {ve:>8.0f}% {cd:>9d} ${m['final_eq']:>14,.0f} {m['cagr']:>+7.2f}% "
              f"{m['max_dd']:>+8.2f}% {m['sharpe']:>8.4f} "
              f"{m['pct_3x']:>5.1f}% {m['pct_1x']:>5.1f}% {m['pct_bil']:>5.1f}%{tag}")

ve, cd, m = best
print()
print(f"  Highest final equity: VolEntry={ve:.0f}%  Cooldown={cd}  "
      f"-> ${m['final_eq']:,.0f}  CAGR {m['cagr']:+.2f}%  MaxDD {m['max_dd']:+.2f}%  Sharpe {m['sharpe']:.4f}")
