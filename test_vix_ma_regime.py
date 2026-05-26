#!/usr/bin/env python3
"""
B1 — VIX moving-average regime filter on Two-Sleeves v1.1.

Two changes proposed (testable independently and jointly):

  Entry gate:   add  VIX[i] < SMA(VIX, p)  to the existing entry conditions.
                Strictens entries — only fire when VIX is below its own MA.
  Spike exit:   while in vehicle, also exit if  VIX[i] > SMA(VIX, p) × mult.
                Adds a 5th vehicle-exit trigger (rotates to defensive, no cooldown).

Variants tested:
  A — entry gate only          (p ∈ {5, 10, 20, 60})              4 runs
  B — spike exit only          (p × mult: 4 × 4)                 16 runs
  C — both (user's full B1)    (p × mult: 4 × 4)                 16 runs
  plus a v1.1 baseline on the same 7-ticker date window for a fair compare.

Goal: any combination that improves Sharpe vs the baseline.
"""

import json, math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

# v1.1 spec
TOTAL_CAPITAL   = 100_000.0
SAFETY_INIT     = 10_000.0
EQ_ALLOC_EACH   = 45_000.0
BACKTEST_START  = date(2000, 1, 1)
CASH_TICKER     = "BIL"
VOL_PERIOD      = 20
VOL_ENTRY_MAX   = 16.0
VOL_EXIT_THRESH = 30.0
TAKE_PROFIT_PCT = 200.0
STOP_LOSS_PCT   = 12.0
DEF_STOP_PCT    = 18.0
COOLDOWN_DAYS   = 30
EQUITY_CONFIGS  = [
    ("QQQ", "TQQQ", "QQQ", 10, 175),
    ("SPY", "SPXL", "SPY",  5, 200),
]

MA_GRID    = [5, 10, 20, 60]
MULT_GRID  = [1.0, 1.2, 1.5, 2.0]


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

def load_ticker(t, suffix="_US"):
    raw = json.load(open(DATA_DIR / f"{t}{suffix}.json"))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


print("Loading data...", flush=True)
tickers = {"GLD", CASH_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS: tickers |= {s, v, d}
raw_data = {t: load_ticker(t) for t in tickers}
vix_data = load_ticker("VIX_INDX", suffix="")
# Intersect strategy data with VIX dates
common = sorted(set.intersection(*[set(raw_data[t].keys()) for t in tickers]) & set(vix_data.keys()))
n = len(common)
print(f"  {n} bars  {common[0]} -> {common[-1]}  (limited by VIX freshness)\n")

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

vix_arr = [vix_data[d]["close"] for d in common]
# Precompute VIX MAs for each tested period
vix_sma_by_p = {p: compute_sma(vix_arr, p) for p in MA_GRID}

MIN_IDX_BASE = max(VOL_PERIOD, *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


def run(use_entry_gate, use_spike_exit, ma_period, spike_mult):
    """Modified v1.1 with optional VIX MA entry gate and/or spike exit."""
    vix_sma = vix_sma_by_p[ma_period] if (use_entry_gate or use_spike_exit) else None
    min_idx = max(MIN_IDX_BASE, ma_period) if vix_sma is not None else MIN_IDX_BASE

    def mk(signal, vehicle, defensive, wma, sma):
        return dict(signal=signal, vehicle=vehicle, defensive=defensive,
                    wma_period=wma, sma_period=sma,
                    state="cash", next_state=None,
                    v_shares=0.0, v_entry=0.0, d_shares=0.0, d_entry=0.0,
                    c_shares=0.0, cash=0.0, equity=EQ_ALLOC_EACH,
                    wma_was_below=True, entry_eligible=False, cooldown=0, trades=0,
                    spike_exits=0)
    sl_list = [mk(*cfg) for cfg in EQUITY_CONFIGS]
    cash_adj0 = arrays[CASH_TICKER]["adj"][0]
    for sl in sl_list:
        sl["c_shares"] = EQ_ALLOC_EACH / cash_adj0
    gld_shares = SAFETY_INIT / arrays["GLD"]["adj"][0]
    gld_equity = SAFETY_INIT
    portfolio = []
    prev_year = int(common[0][:4])
    blocked_entries = 0

    for i in range(n):
        day = common[i]

        for sl in sl_list:
            if sl["next_state"] is None: continue
            veh, dfn = sl["vehicle"], sl["defensive"]
            vo = arrays[veh]["opens"][i]         * arrays[veh]["ratio"][i]
            do = arrays[dfn]["opens"][i]         * arrays[dfn]["ratio"][i]
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

        for sl in sl_list:
            if sl["cooldown"] > 0: sl["cooldown"] -= 1

        for sl in sl_list:
            if sl["state"] == "vehicle":
                sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i]
            elif sl["state"] == "defensive":
                sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
            else:
                sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][i]
        gld_equity = gld_shares * arrays["GLD"]["adj"][i]

        cur_year = int(day[:4])
        if cur_year > prev_year:
            total_eq = sum(s["equity"] for s in sl_list) + gld_equity
            eq_t  = total_eq * (EQ_ALLOC_EACH / TOTAL_CAPITAL)
            gld_t = total_eq * (SAFETY_INIT   / TOTAL_CAPITAL)
            for sl in sl_list:
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

        portfolio.append(sum(s["equity"] for s in sl_list) + gld_equity)
        if i < min_idx: continue

        # VIX state at bar i (None if not enough history yet)
        vix_now = vix_arr[i]
        vix_ma_now = vix_sma[i] if vix_sma is not None else None
        vix_below_ma = (vix_ma_now is not None and vix_now < vix_ma_now)
        vix_spike    = (vix_ma_now is not None and vix_now > vix_ma_now * spike_mult)

        for sl in sl_list:
            sig, veh = sl["signal"], sl["vehicle"]
            wa, sa, hva = arrays[sig]["wma"], arrays[sig]["sma"], arrays[sig]["hvol"]
            if any(x is None for x in [wa[i], sa[i], wa[i-1], sa[i-1]]):
                continue
            w, wp = wa[i], wa[i-1]; s, sp = sa[i], sa[i-1]
            hv = hva[i] if hva[i] is not None else 0.0
            cab = wp <= sp and w > s; cbl = wp >= sp and w < s

            if sl["state"] == "vehicle" and sl["next_state"] is None:
                vad = arrays[veh]["adj"][i]
                do_tp = vad >= sl["v_entry"] * (1 + TAKE_PROFIT_PCT/100)
                do_sl = vad <= sl["v_entry"] * (1 - STOP_LOSS_PCT/100)
                do_v  = hv >= VOL_EXIT_THRESH
                do_w  = cbl
                # B1 spike exit (no cooldown — same policy as vol_exit)
                do_spike = (use_spike_exit and vix_ma_now is not None and vix_spike)
                if do_tp or do_sl or do_v or do_w or do_spike:
                    if do_sl: sl["cooldown"] = COOLDOWN_DAYS
                    if do_spike and not (do_tp or do_sl or do_v or do_w):
                        sl["spike_exits"] += 1
                    sl["wma_was_below"] = False; sl["next_state"] = "defensive"

            if sl["state"] == "defensive" and sl["next_state"] is None:
                dad = arrays[sl["defensive"]]["adj"][i]
                if sl["d_entry"] > 0 and dad <= sl["d_entry"] * (1 - DEF_STOP_PCT/100):
                    sl["cooldown"] = COOLDOWN_DAYS; sl["next_state"] = "cash"

            if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
                if w < s: sl["wma_was_below"] = True; sl["entry_eligible"] = False
                if cab and sl["wma_was_below"]: sl["entry_eligible"] = True; sl["wma_was_below"] = False
                if sl["entry_eligible"] and w < s: sl["entry_eligible"] = False; sl["wma_was_below"] = True

            if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
                base_ok = (sl["entry_eligible"] and hv <= VOL_ENTRY_MAX
                           and w > s and i + 1 < n and sl["cooldown"] == 0)
                vix_ok  = (not use_entry_gate) or vix_below_ma
                if base_ok and vix_ok:
                    sl["next_state"] = "vehicle"
                    sl["entry_eligible"] = False; sl["wma_was_below"] = False
                elif base_ok and not vix_ok:
                    blocked_entries += 1

    for sl in sl_list:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][-1]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][-1]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1]
    gld_equity = gld_shares * arrays["GLD"]["adj"][-1]
    portfolio[-1] = sum(s["equity"] for s in sl_list) + gld_equity

    final = portfolio[-1]
    years = (date.fromisoformat(common[-1]) - date.fromisoformat(common[0])).days / 365.25
    cagr = ((final/TOTAL_CAPITAL)**(1/years) - 1)*100
    peak = TOTAL_CAPITAL; max_dd = 0.0
    for eq in portfolio:
        if eq > peak: peak = eq
        dd = (eq - peak)/peak * 100
        if dd < max_dd: max_dd = dd
    dr = [(portfolio[i]-portfolio[i-1])/portfolio[i-1] for i in range(1, len(portfolio)) if portfolio[i-1]]
    mu = sum(dr)/len(dr); sig = (sum((r-mu)**2 for r in dr)/(len(dr)-1))**0.5
    sharpe = mu/sig * math.sqrt(252) if sig else 0.0
    return dict(final=final, cagr=cagr, max_dd=max_dd, sharpe=sharpe,
                trades=sum(s["trades"] for s in sl_list),
                spikes=sum(s["spike_exits"] for s in sl_list),
                blocked=blocked_entries)


# Baseline (no VIX filter) on the SAME 7-ticker date window — fair compare
print("=" * 108)
print("  B1 — VIX moving-average regime filter sweep on Two-Sleeves v1.1")
print(f"  Date window: {common[0]} -> {common[-1]} ({n} bars, limited by VIX freshness)")
print("=" * 108)
base = run(False, False, 10, 1.0)
print(f"\n  v1.1 BASELINE (no VIX filter, this window):")
print(f"    Final ${base['final']:,.0f}   CAGR {base['cagr']:+.2f}%   MaxDD {base['max_dd']:+.2f}%   "
      f"Sharpe {base['sharpe']:.4f}   Trades {base['trades']}\n")

def show(label, m):
    deq    = m["final"]  - base["final"]
    dsharp = m["sharpe"] - base["sharpe"]
    ddd    = m["max_dd"] - base["max_dd"]
    extras = []
    if m["spikes"]:  extras.append(f"spikes={m['spikes']}")
    if m["blocked"]: extras.append(f"blocked={m['blocked']}")
    ex = "  " + " ".join(extras) if extras else ""
    marker = ""
    if dsharp > 0:
        marker = "  ★ SHARPE BETTER"
    return (f"  {label:<24} final ${m['final']:>14,.0f}  CAGR {m['cagr']:>+6.2f}%  "
            f"MaxDD {m['max_dd']:>+6.2f}%  Sharpe {m['sharpe']:>7.4f}  "
            f"Trades {m['trades']:>3}{ex}{marker}")

print("─" * 108)
print("  VARIANT A — entry gate only  (block entry when VIX > SMA(VIX,p))")
print("─" * 108)
for p in MA_GRID:
    m = run(True, False, p, 1.0)
    print(show(f"A  p={p:>2}", m))

print()
print("─" * 108)
print("  VARIANT B — spike exit only  (exit vehicle when VIX > SMA(VIX,p) × mult)")
print("─" * 108)
for p in MA_GRID:
    for mult in MULT_GRID:
        m = run(False, True, p, mult)
        print(show(f"B  p={p:>2} mult={mult:.1f}", m))

print()
print("─" * 108)
print("  VARIANT C — both (user's full B1 proposal)")
print("─" * 108)
for p in MA_GRID:
    for mult in MULT_GRID:
        m = run(True, True, p, mult)
        print(show(f"C  p={p:>2} mult={mult:.1f}", m))

print()
print("=" * 108)
print(f"  Baseline (this window) Sharpe = {base['sharpe']:.4f}   "
      f"v1.1 spec target Sharpe (through 2026-03-23) = 0.8752")
