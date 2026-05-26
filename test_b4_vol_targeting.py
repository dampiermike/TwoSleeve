#!/usr/bin/env python3
"""
B4 — Volatility-targeted position sizing overlay on Two-Sleeves v1.2.

The change:
  At vehicle entry AND at the annual rebalance (only — NOT daily),
  scale the vehicle position by:
      vol_scale = min(1.0, vol_target / realized_vol_at_event)
  The sleeve splits its cash into:
      v_shares      = (eq * vol_scale) / vehicle_price   (the leveraged piece)
      c_shares (BIL)= (eq * (1-vol_scale)) / BIL_price   (sideline cash)
  Both legs are held until the vehicle position is exited.

Three vol estimators tested:
  HVol20  — existing 20-bar SMA of squared log returns (sample variance)
  HVol60  — same but 60-bar window
  EWMA20  — exponentially weighted, half-life 20 bars (RiskMetrics-style)

Grid: 4 vol_targets × 3 estimators = 12 candidates + baseline.

Walk-forward split at 2015-01-01 (IS / OOS) so we can validate that any
Sharpe improvement holds out-of-sample, not just over the full window.
"""

import json, math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

# v1.2 spec (unchanged base)
TOTAL_CAPITAL   = 100_000.0
SAFETY_INIT     = 10_000.0
EQ_ALLOC_EACH   = 45_000.0
BACKTEST_START  = date(2000, 1, 1)
SPLIT_DATE      = date(2015, 1, 1)
CASH_TICKER     = "BIL"
VIX_TICKER      = "VIX_INDX"
VOL_PERIOD      = 20
VOL_ENTRY_MAX   = 16.0
VOL_EXIT_THRESH = 30.0
TAKE_PROFIT_PCT = 200.0
STOP_LOSS_PCT   = 12.0
DEF_STOP_PCT    = 18.0
COOLDOWN_DAYS   = 30
VIX_MA_PERIOD   = 20
VIX_SPIKE_MULT  = 2.0

EQUITY_CONFIGS  = [
    ("QQQ", "TQQQ", "QQQ", 10, 175),
    ("SPY", "SPXL", "SPY",  5, 200),
]

# B4 sweep
VOL_TARGETS  = [15.0, 20.0, 25.0, 30.0]
EWMA_HALFLIFE = 20    # bars


def compute_hvol(c, w):
    n, out = len(c), [None]*len(c)
    for i in range(w, n):
        lr = [math.log(c[j]/c[j-1]) for j in range(i-w+1, i+1)]
        m = sum(lr)/w; v = sum((r-m)**2 for r in lr)/(w-1)
        out[i] = math.sqrt(v*252)*100.0
    return out

def compute_ewma_vol(c, half_life):
    """EWMA realized vol (annualised %)."""
    n = len(c)
    if n < 2: return [None]*n
    lam = 0.5 ** (1.0 / half_life)
    log_ret = [None] + [math.log(c[i]/c[i-1]) for i in range(1, n)]
    # Seed from first half_life sample variance
    out = [None]*n
    seed_window = max(half_life, 20)
    if n <= seed_window: return out
    lr_seed = log_ret[1:seed_window+1]
    m = sum(lr_seed)/len(lr_seed)
    var_init = sum((r-m)**2 for r in lr_seed) / (len(lr_seed)-1)
    var = var_init
    out[seed_window] = math.sqrt(var*252)*100.0
    for i in range(seed_window+1, n):
        r = log_ret[i] if log_ret[i] is not None else 0.0
        var = (1-lam)*r*r + lam*var
        out[i] = math.sqrt(var*252)*100.0
    return out

def compute_wma(c, p):
    n, out = len(c), [None]*len(c); denom = p*(p+1)/2
    for i in range(p-1, n):
        out[i] = sum(c[i-p+1+j]*(j+1) for j in range(p)) / denom
    return out

def compute_sma(c, p):
    n, out = len(c), [None]*len(c)
    if n < p: return out
    s = sum(c[:p]); out[p-1] = s/p
    for i in range(p, n):
        s += c[i] - c[i-p]; out[i] = s/p
    return out

def load_ticker(t):
    path = DATA_DIR / f"{t}.json" if t == VIX_TICKER else DATA_DIR / f"{t}_US.json"
    raw = json.load(open(path))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


print("Loading data...", flush=True)
tickers = {"GLD", CASH_TICKER, VIX_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS: tickers |= {s, v, d}
raw_data = {t: load_ticker(t) for t in tickers}
common = sorted(set.intersection(*[set(raw_data[t].keys()) for t in tickers]))
n = len(common)
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
    arrays[s]["wma"]   = compute_wma(c, wma)
    arrays[s]["sma"]   = compute_sma(c, sma)
    arrays[s]["hvol20"]= compute_hvol(c, 20)
    arrays[s]["hvol60"]= compute_hvol(c, 60)
    arrays[s]["ewma"]  = compute_ewma_vol(c, EWMA_HALFLIFE)

vix_close = arrays[VIX_TICKER]["closes"]
vix_sma   = compute_sma(vix_close, VIX_MA_PERIOD)
MIN_IDX   = max(VOL_PERIOD, VIX_MA_PERIOD, 60,         # 60 from HVol60
                *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


def run(vol_target=None, estimator=None):
    """
    vol_target=None means baseline v1.2 (no vol scaling).
    estimator: 'hvol20', 'hvol60', or 'ewma'.
    """
    apply_vt = vol_target is not None and estimator is not None

    def get_vol(sig, i):
        return arrays[sig][estimator][i]

    def vol_scale_at(sig, i):
        if not apply_vt: return 1.0
        v = get_vol(sig, i)
        if v is None or v <= 0: return 1.0
        return min(1.0, vol_target / v)

    def mk(signal, vehicle, defensive, wma, sma):
        return dict(signal=signal, vehicle=vehicle, defensive=defensive,
                    wma_period=wma, sma_period=sma,
                    state="cash", next_state=None,
                    v_shares=0.0, v_entry=0.0,
                    d_shares=0.0, d_entry=0.0,
                    c_shares=0.0,        # BIL sidecar (and cash-state BIL holding)
                    cash=0.0, equity=EQ_ALLOC_EACH,
                    wma_was_below=True, entry_eligible=False, cooldown=0,
                    vol_scale=1.0)

    sl_list = [mk(*cfg) for cfg in EQUITY_CONFIGS]
    cash_adj0 = arrays[CASH_TICKER]["adj"][0]
    for sl in sl_list:
        sl["c_shares"] = EQ_ALLOC_EACH / cash_adj0
    gld_shares = SAFETY_INIT / arrays["GLD"]["adj"][0]
    gld_equity = SAFETY_INIT
    portfolio = []
    prev_year = int(common[0][:4])

    for i in range(n):
        day = common[i]

        # Phase 1 — execute pending transitions
        for sl in sl_list:
            if sl["next_state"] is None: continue
            veh, dfn = sl["vehicle"], sl["defensive"]
            vo = arrays[veh]["opens"][i]         * arrays[veh]["ratio"][i]
            do = arrays[dfn]["opens"][i]         * arrays[dfn]["ratio"][i]
            co = arrays[CASH_TICKER]["opens"][i] * arrays[CASH_TICKER]["ratio"][i]

            # Liquidate current state -> sl["cash"]  (vehicle includes BIL sidecar)
            if sl["state"] == "vehicle":
                sl["cash"] = sl["v_shares"]*vo + sl["c_shares"]*co
                sl["v_shares"] = 0.0; sl["v_entry"] = 0.0
                sl["c_shares"] = 0.0
            elif sl["state"] == "defensive":
                sl["cash"] = sl["d_shares"]*do
                sl["d_shares"] = 0.0; sl["d_entry"] = 0.0
            elif sl["state"] == "cash":
                sl["cash"] = sl["c_shares"]*co
                sl["c_shares"] = 0.0

            # Deploy into next state
            if sl["next_state"] == "vehicle":
                # B4: vol-target scale at entry, split into vehicle + BIL sidecar
                vs = vol_scale_at(sl["signal"], i)
                sl["vol_scale"] = vs
                invest   = sl["cash"] * vs
                sideline = sl["cash"] * (1 - vs)
                sl["v_shares"] = invest   / vo if vo > 0 else 0.0
                sl["c_shares"] = sideline / co if co > 0 else 0.0
                sl["v_entry"]  = vo
            elif sl["next_state"] == "defensive":
                sl["d_shares"] = sl["cash"]/do; sl["d_entry"] = do
                sl["vol_scale"] = 1.0
            elif sl["next_state"] == "cash":
                sl["c_shares"] = sl["cash"]/co
                sl["vol_scale"] = 1.0

            sl["cash"] = 0.0
            sl["state"] = sl["next_state"]; sl["next_state"] = None

        # Phase 2 — cooldown
        for sl in sl_list:
            if sl["cooldown"] > 0: sl["cooldown"] -= 1

        # Phase 3 — mark to market (vehicle = v_shares + BIL sidecar)
        for sl in sl_list:
            if sl["state"] == "vehicle":
                sl["equity"] = (sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i] +
                                sl["c_shares"] * arrays[CASH_TICKER]["adj"][i])
            elif sl["state"] == "defensive":
                sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
            else:
                sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][i]
        gld_equity = gld_shares * arrays["GLD"]["adj"][i]

        # Phase 4 — annual rebalance (vol-scale recomputed for vehicle sleeves)
        cur_year = int(day[:4])
        if cur_year > prev_year:
            total_eq = sum(s["equity"] for s in sl_list) + gld_equity
            eq_t  = total_eq * (EQ_ALLOC_EACH / TOTAL_CAPITAL)
            gld_t = total_eq * (SAFETY_INIT   / TOTAL_CAPITAL)
            for sl in sl_list:
                if sl["state"] == "vehicle":
                    vs = vol_scale_at(sl["signal"], i)
                    sl["vol_scale"] = vs
                    invest   = eq_t * vs
                    sideline = eq_t * (1 - vs)
                    sl["v_shares"] = invest   / arrays[sl["vehicle"]]["adj"][i]
                    sl["c_shares"] = sideline / arrays[CASH_TICKER]["adj"][i]
                elif sl["state"] == "defensive":
                    sl["d_shares"] = eq_t / arrays[sl["defensive"]]["adj"][i]
                    sl["c_shares"] = 0.0
                else:
                    sl["c_shares"] = eq_t / arrays[CASH_TICKER]["adj"][i]
                sl["equity"] = eq_t
            gld_shares = gld_t / arrays["GLD"]["adj"][i]
            gld_equity = gld_t
        prev_year = cur_year

        portfolio.append(sum(s["equity"] for s in sl_list) + gld_equity)
        if i < MIN_IDX: continue

        # v1.2 VIX spike state
        vix_now = vix_close[i]
        vix_ma_now = vix_sma[i]
        vix_spike  = (vix_ma_now is not None and vix_now > vix_ma_now * VIX_SPIKE_MULT)

        for sl in sl_list:
            sig, veh = sl["signal"], sl["vehicle"]
            wa, sa = arrays[sig]["wma"], arrays[sig]["sma"]
            hva = arrays[sig]["hvol20"]   # the entry/exit gate uses HVol20 by spec
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
                do_spike = vix_spike
                if do_tp or do_sl or do_v or do_w or do_spike:
                    if do_sl: sl["cooldown"] = COOLDOWN_DAYS
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
                if (sl["entry_eligible"] and hv <= VOL_ENTRY_MAX
                        and w > s and i + 1 < n and sl["cooldown"] == 0):
                    sl["next_state"] = "vehicle"
                    sl["entry_eligible"] = False; sl["wma_was_below"] = False

    # Last-bar mark-to-market
    for sl in sl_list:
        if sl["state"] == "vehicle":
            sl["equity"] = (sl["v_shares"] * arrays[sl["vehicle"]]["adj"][-1] +
                            sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1])
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][-1]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1]
    gld_equity = gld_shares * arrays["GLD"]["adj"][-1]
    portfolio[-1] = sum(s["equity"] for s in sl_list) + gld_equity
    return portfolio


def window_metrics(curve, lo, hi):
    seg = curve[lo:hi+1]
    if len(seg) < 2: return None
    init, final = seg[0], seg[-1]
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
    return dict(final=final, cagr=cagr, max_dd=max_dd, sharpe=sharpe)


# ── Baseline + every candidate ────────────────────────────────────────────────
configs = [("baseline v1.2", None, None)]
for est in ("hvol20", "hvol60", "ewma"):
    for vt in VOL_TARGETS:
        configs.append((f"B4 {est:6} vt={vt:.0f}%", vt, est))

results = []
for label, vt, est in configs:
    curve = run(vt, est)
    is_m   = window_metrics(curve, 0, split_idx-1)
    oos_m  = window_metrics(curve, split_idx, n-1)
    full_m = window_metrics(curve, 0, n-1)
    results.append((label, is_m, oos_m, full_m))

baseline_label, is_b, oos_b, full_b = results[0]

print("=" * 120)
print(f"  B4 WALK-FORWARD VALIDATION   IS={common[0]}..{common[split_idx-1]}   "
      f"OOS={common[split_idx]}..{common[-1]}")
print("=" * 120)
print(f"\n  BASELINE v1.2 (no vol-targeting)")
print(f"    IS   Sharpe {is_b['sharpe']:.4f}  CAGR {is_b['cagr']:+.2f}%  MaxDD {is_b['max_dd']:+.2f}%")
print(f"    OOS  Sharpe {oos_b['sharpe']:.4f}  CAGR {oos_b['cagr']:+.2f}%  MaxDD {oos_b['max_dd']:+.2f}%")
print(f"    full Sharpe {full_b['sharpe']:.4f}  CAGR {full_b['cagr']:+.2f}%  MaxDD {full_b['max_dd']:+.2f}%   "
      f"Final ${full_b['final']:,.0f}")

print()
print("─" * 120)
print(f"  CANDIDATES")
print(f"  {'Config':<22}  {'IS Sharpe':>10}  {'ΔIS':>8}  {'OOS Sharpe':>11}  {'ΔOOS':>8}  "
      f"{'Full Sharpe':>12}  {'ΔFull':>8}  {'Final $':>14}")
print("─" * 120)
for label, is_m, oos_m, full_m in results[1:]:
    d_is   = is_m["sharpe"]  - is_b["sharpe"]
    d_oos  = oos_m["sharpe"] - oos_b["sharpe"]
    d_full = full_m["sharpe"]- full_b["sharpe"]
    mark = "  ★ BOTH" if (d_is > 0 and d_oos > 0) else ""
    print(f"  {label:<22}  {is_m['sharpe']:>10.4f}  {d_is:>+7.4f}  "
          f"{oos_m['sharpe']:>11.4f}  {d_oos:>+7.4f}  "
          f"{full_m['sharpe']:>12.4f}  {d_full:>+7.4f}  ${full_m['final']:>13,.0f}{mark}")

# Pure walk-forward — pick IS-best and validate on OOS
cand_sorted = sorted(results[1:], key=lambda r: r[1]["sharpe"], reverse=True)
print()
print("=" * 120)
print("  PURE WALK-FORWARD VALIDATION")
print("=" * 120)
print("  Top 5 candidates by IS Sharpe:")
for label, is_m, oos_m, full_m in cand_sorted[:5]:
    d_oos = oos_m["sharpe"] - oos_b["sharpe"]
    holds = "✓ holds OOS"  if d_oos > 0 else "✗ FAILS OOS"
    print(f"    {label:<22}  IS Sharpe {is_m['sharpe']:.4f}  -> OOS Sharpe {oos_m['sharpe']:.4f}  "
          f"(baseline OOS {oos_b['sharpe']:.4f}, ΔOOS {d_oos:+.4f})   {holds}")

w = cand_sorted[0]
print(f"\n  IS-WINNER: {w[0]}")
print(f"    IS  : Sharpe {w[1]['sharpe']:.4f}  vs baseline {is_b['sharpe']:.4f}  "
      f"(Δ {w[1]['sharpe']-is_b['sharpe']:+.4f})")
print(f"    OOS : Sharpe {w[2]['sharpe']:.4f}  vs baseline {oos_b['sharpe']:.4f}  "
      f"(Δ {w[2]['sharpe']-oos_b['sharpe']:+.4f})")
print(f"    full: Sharpe {w[3]['sharpe']:.4f}  Final ${w[3]['final']:,.0f}  "
      f"CAGR {w[3]['cagr']:+.2f}%  MaxDD {w[3]['max_dd']:+.2f}%")
