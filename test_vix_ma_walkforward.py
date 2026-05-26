#!/usr/bin/env python3
"""
Walk-forward validation of the B1 VIX moving-average regime filter.

Question: is the +0.013 Sharpe improvement (Variant B, p∈{20,60}, mult=2.0)
real, or is it 5 lucky events in 26 years?

Method:
  - Full 2000-2026 sim for each candidate (state carries through naturally).
  - Slice the daily-return series at 2015-01-01 -> IS (15 yrs) and OOS (11.3 yrs).
  - Compute Sharpe / CAGR / MaxDD per slice for baseline AND each candidate.
  - Real edge => Sharpe improvement on BOTH IS and OOS.
  - Pure walk-forward: select IS-best candidate, then validate on OOS.
  - Record spike-event dates so we know which side of the split they fired on.
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
SPLIT_DATE      = date(2015, 1, 1)        # IS / OOS boundary
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

# Candidates from the original B1 sweep. Variant B (spike exit only) was best.
# Add a few promising Variant A and C combos for completeness.
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
common = sorted(set.intersection(*[set(raw_data[t].keys()) for t in tickers]) & set(vix_data.keys()))
n = len(common)

# Find the split index — first bar >= SPLIT_DATE
split_idx = next((i for i, d in enumerate(common) if date.fromisoformat(d) >= SPLIT_DATE), n)
print(f"  {n} bars  {common[0]} -> {common[-1]}")
print(f"  IS:  {common[0]} -> {common[split_idx-1]}   ({split_idx} bars)")
print(f"  OOS: {common[split_idx]} -> {common[-1]}   ({n - split_idx} bars)\n")

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
vix_sma_by_p = {p: compute_sma(vix_arr, p) for p in MA_GRID}

MIN_IDX_BASE = max(VOL_PERIOD, *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


def run_full(use_entry_gate, use_spike_exit, ma_period, spike_mult):
    """Run the full v1.1 sim with optional B1 hooks. Returns equity curve + spike dates."""
    vix_sma = vix_sma_by_p[ma_period] if (use_entry_gate or use_spike_exit) else None
    min_idx = max(MIN_IDX_BASE, ma_period) if vix_sma is not None else MIN_IDX_BASE

    def mk(signal, vehicle, defensive, wma, sma):
        return dict(signal=signal, vehicle=vehicle, defensive=defensive,
                    wma_period=wma, sma_period=sma,
                    state="cash", next_state=None,
                    v_shares=0.0, v_entry=0.0, d_shares=0.0, d_entry=0.0,
                    c_shares=0.0, cash=0.0, equity=EQ_ALLOC_EACH,
                    wma_was_below=True, entry_eligible=False, cooldown=0)
    sl_list = [mk(*cfg) for cfg in EQUITY_CONFIGS]
    cash_adj0 = arrays[CASH_TICKER]["adj"][0]
    for sl in sl_list:
        sl["c_shares"] = EQ_ALLOC_EACH / cash_adj0
    gld_shares = SAFETY_INIT / arrays["GLD"]["adj"][0]
    gld_equity = SAFETY_INIT
    portfolio = []
    spike_dates = []
    prev_year = int(common[0][:4])

    for i in range(n):
        day = common[i]
        for sl in sl_list:
            if sl["next_state"] is None: continue
            veh, dfn = sl["vehicle"], sl["defensive"]
            vo = arrays[veh]["opens"][i]         * arrays[veh]["ratio"][i]
            do = arrays[dfn]["opens"][i]         * arrays[dfn]["ratio"][i]
            co = arrays[CASH_TICKER]["opens"][i] * arrays[CASH_TICKER]["ratio"][i]
            if sl["state"] == "vehicle":
                sl["cash"] = sl["v_shares"]*vo; sl["v_shares"] = 0.0; sl["v_entry"] = 0.0
            elif sl["state"] == "defensive":
                sl["cash"] = sl["d_shares"]*do; sl["d_shares"] = 0.0; sl["d_entry"] = 0.0
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
                do_spike = (use_spike_exit and vix_ma_now is not None and vix_spike)
                if do_tp or do_sl or do_v or do_w or do_spike:
                    if do_sl: sl["cooldown"] = COOLDOWN_DAYS
                    # Record only spike-DRIVEN exits (not coincidental)
                    if do_spike and not (do_tp or do_sl or do_v or do_w):
                        spike_dates.append(day)
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

    for sl in sl_list:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][-1]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][-1]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1]
    gld_equity = gld_shares * arrays["GLD"]["adj"][-1]
    portfolio[-1] = sum(s["equity"] for s in sl_list) + gld_equity
    return portfolio, spike_dates


def window_metrics(curve, lo, hi):
    """Sharpe/CAGR/MaxDD computed on curve[lo:hi+1]. Equity restarts from curve[lo] as 'initial'."""
    seg = curve[lo:hi+1]
    if len(seg) < 2: return None
    final, init = seg[-1], seg[0]
    years = (date.fromisoformat(common[hi]) - date.fromisoformat(common[lo])).days / 365.25
    cagr = ((final/init)**(1/years) - 1)*100 if (init > 0 and years > 0) else 0.0
    peak = init; max_dd = 0.0
    for eq in seg:
        if eq > peak: peak = eq
        dd = (eq - peak)/peak * 100
        if dd < max_dd: max_dd = dd
    dr = [(seg[i]-seg[i-1])/seg[i-1] for i in range(1, len(seg)) if seg[i-1] > 0]
    if len(dr) < 2: return None
    mu = sum(dr)/len(dr); sig = (sum((r-mu)**2 for r in dr)/(len(dr)-1))**0.5
    sharpe = mu/sig * math.sqrt(252) if sig > 0 else 0.0
    return dict(final=final, cagr=cagr, max_dd=max_dd, sharpe=sharpe, init=init)


# ── Run baseline + every candidate, capture full-period equity curves ─────────
configs = [("baseline", False, False, 10, 1.0)]
for p in MA_GRID:
    configs.append((f"A p={p}", True, False, p, 1.0))
for p in MA_GRID:
    for m in MULT_GRID:
        configs.append((f"B p={p} m={m}", False, True, p, m))
for p in MA_GRID:
    for m in MULT_GRID:
        configs.append((f"C p={p} m={m}", True, True, p, m))

results = []
for label, eg, se, p, m in configs:
    curve, spikes = run_full(eg, se, p, m)
    is_m  = window_metrics(curve, 0, split_idx - 1)
    oos_m = window_metrics(curve, split_idx, n - 1)
    full_m = window_metrics(curve, 0, n - 1)
    spikes_is  = [d for d in spikes if date.fromisoformat(d) <  SPLIT_DATE]
    spikes_oos = [d for d in spikes if date.fromisoformat(d) >= SPLIT_DATE]
    results.append((label, is_m, oos_m, full_m, spikes_is, spikes_oos))

baseline_label, is_b, oos_b, full_b, _, _ = results[0]

print("=" * 116)
print(f"  WALK-FORWARD: B1 VIX MA filter   IS={common[0]}..{common[split_idx-1]}   "
      f"OOS={common[split_idx]}..{common[-1]}")
print("=" * 116)
print(f"\n  BASELINE (no VIX filter)")
print(f"    IS   Sharpe {is_b['sharpe']:.4f}  CAGR {is_b['cagr']:+.2f}%  MaxDD {is_b['max_dd']:+.2f}%")
print(f"    OOS  Sharpe {oos_b['sharpe']:.4f}  CAGR {oos_b['cagr']:+.2f}%  MaxDD {oos_b['max_dd']:+.2f}%")
print(f"    full Sharpe {full_b['sharpe']:.4f}  CAGR {full_b['cagr']:+.2f}%  MaxDD {full_b['max_dd']:+.2f}%")

print()
print("─" * 116)
print(f"  PER-CANDIDATE — Sharpe deltas vs baseline (★ = beats baseline)")
print(f"  {'Candidate':<18}  {'IS Sharpe':>10}  {'ΔIS':>8}  {'OOS Sharpe':>11}  {'ΔOOS':>8}  "
      f"{'Full Sharpe':>12}  {'ΔFull':>8}  {'spk IS':>6}  {'spk OOS':>7}")
print("─" * 116)
for label, is_m, oos_m, full_m, sp_is, sp_oos in results[1:]:
    d_is   = is_m["sharpe"]  - is_b["sharpe"]
    d_oos  = oos_m["sharpe"] - oos_b["sharpe"]
    d_full = full_m["sharpe"]- full_b["sharpe"]
    is_mark   = "★" if d_is  > 0 else " "
    oos_mark  = "★" if d_oos > 0 else " "
    both_mark = "  ★ BOTH" if (d_is > 0 and d_oos > 0) else ""
    print(f"  {label:<18}  {is_m['sharpe']:>10.4f}  {d_is:>+7.4f}{is_mark}  "
          f"{oos_m['sharpe']:>11.4f}  {d_oos:>+7.4f}{oos_mark}  "
          f"{full_m['sharpe']:>12.4f}  {d_full:>+7.4f}  {len(sp_is):>6}  {len(sp_oos):>7}{both_mark}")

# ── Pure walk-forward — pick IS-best, validate on OOS ────────────────────────
print()
print("=" * 116)
print("  PURE WALK-FORWARD VALIDATION")
print("  (1) Among ALL candidates, find the one with best IS Sharpe")
print("  (2) Check whether that same candidate also beats baseline OOS")
print("=" * 116)

# Sort candidates by IS Sharpe
cand_sorted = sorted(results[1:], key=lambda r: r[1]["sharpe"], reverse=True)
print(f"\n  Top 5 candidates by IS Sharpe:")
for label, is_m, oos_m, full_m, sp_is, sp_oos in cand_sorted[:5]:
    d_oos = oos_m["sharpe"] - oos_b["sharpe"]
    holds = "✓ holds OOS"  if d_oos > 0 else "✗ FAILS OOS"
    print(f"    {label:<18}  IS Sharpe {is_m['sharpe']:.4f}  -> OOS Sharpe {oos_m['sharpe']:.4f}  "
          f"(baseline OOS {oos_b['sharpe']:.4f}, ΔOOS {d_oos:+.4f})   {holds}")

is_winner = cand_sorted[0]
print(f"\n  IS-WINNER: {is_winner[0]}")
print(f"    IS  : Sharpe {is_winner[1]['sharpe']:.4f}  vs baseline {is_b['sharpe']:.4f}  "
      f"(Δ {is_winner[1]['sharpe']-is_b['sharpe']:+.4f})")
print(f"    OOS : Sharpe {is_winner[2]['sharpe']:.4f}  vs baseline {oos_b['sharpe']:.4f}  "
      f"(Δ {is_winner[2]['sharpe']-oos_b['sharpe']:+.4f})")

# Spike-date diagnostic for the previously-flagged best
flagged = [r for r in results if r[0] in ("B p=20 m=2.0", "B p=60 m=2.0")]
if flagged:
    print()
    print("  Spike-event dates for previously-flagged best (Variant B mult=2.0):")
    for label, _, _, _, sp_is, sp_oos in flagged:
        print(f"    {label}:  IS spikes {sp_is}   OOS spikes {sp_oos}")
