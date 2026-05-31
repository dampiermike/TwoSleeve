#!/usr/bin/env python3
"""
B2 — VIX term-structure regime gate (VIX/VIX3M ratio).

The user spec calls for VX1/VX2 (front/second-month VIX futures). Those
aren't in EODHD; the cleanest equivalent CBOE index pair is VIX (spot,
1-month forward) and VIX3M (3-month forward). The ratio has the same
interpretation:
    ratio < 1   => contango (calm)
    ratio > 1   => backwardation (stress)

ts_ratio[i]  = VIX[i] / VIX3M[i]
ts_smooth[i] = 5-bar SMA of ts_ratio   (per user spec)

Three variants tested (HVol gate, cooldown, TP, hard stop, vol exit,
VIX spike, defensive rotation, BIL cash, latch all retained):
  A — entry gate only        : entry only if ts_smooth < entry_thresh
  B — forced vehicle exit    : exit if ts_smooth > exit_thresh
  C — both                   : combined gate + exit

Data caveat: VIX3M starts 2007-11-13. Pre that date, the filter is
neutral (no entry restriction, no forced exit). So IS coverage is
2007-11-13..2014-12-31 (~7 yrs, includes GFC) and OOS is the full
2015-01-02..2026-05-22.

Walk-forward split at 2015-01-01.
"""

import json, math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

# v1.2 spec
TOTAL_CAPITAL   = 100_000.0
SAFETY_INIT     = 10_000.0
EQ_ALLOC_EACH   = 45_000.0
BACKTEST_START  = date(2000, 1, 1)
SPLIT_DATE      = date(2015, 1, 1)
CASH_TICKER     = "BIL"
VIX_TICKER      = "VIX_INDX"
VIX3M_TICKER    = "VIX3M_INDX"
VOL_PERIOD      = 20
VOL_ENTRY_MAX   = 16.0
VOL_EXIT_THRESH = 30.0
TAKE_PROFIT_PCT = 200.0
STOP_LOSS_PCT   = 12.0
DEF_STOP_PCT    = 18.0
COOLDOWN_DAYS   = 30
VIX_MA_PERIOD   = 20
VIX_SPIKE_MULT  = 2.0
TS_SMOOTH       = 5     # 5-bar SMA of ts_ratio per spec

EQUITY_CONFIGS  = [
    ("QQQ", "TQQQ", "QQQ", 10, 175),
    ("SPY", "SPXL", "SPY",  5, 200),
]


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
    n, out = len(c), [None]*len(c)
    if n < p: return out
    s = sum(c[:p]); out[p-1] = s/p
    for i in range(p, n):
        s += c[i] - c[i-p]; out[i] = s/p
    return out


def load(t):
    name = f"{t}.json" if t in (VIX_TICKER, VIX3M_TICKER) else f"{t}_US.json"
    raw = json.load(open(DATA_DIR / name))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


print("Loading data...", flush=True)
# Common date set is the intersection of strategy tickers + VIX (always present).
# VIX3M is sparse in early years — we handle it separately (None when missing).
strat = {"GLD", CASH_TICKER, VIX_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS: strat |= {s, v, d}
raw_data  = {t: load(t) for t in strat}
vix3m_raw = load(VIX3M_TICKER)

common = sorted(set.intersection(*[set(raw_data[t].keys()) for t in strat]))
n = len(common)
split_idx = next((i for i, d in enumerate(common) if date.fromisoformat(d) >= SPLIT_DATE), n)
print(f"  {n} bars  {common[0]} -> {common[-1]}")
print(f"  IS:  {common[0]} -> {common[split_idx-1]}   ({split_idx} bars)")
print(f"  OOS: {common[split_idx]} -> {common[-1]}   ({n - split_idx} bars)")
print(f"  VIX3M coverage: starts {sorted(vix3m_raw.keys())[0]}")
print(f"    bars with VIX3M data: {sum(1 for d in common if d in vix3m_raw)}/{n}\n")

arrays = {}
for tk, d in raw_data.items():
    closes = [d[day]["close"]          for day in common]
    adjs   = [d[day]["adjusted_close"] for day in common]
    opens  = [d[day]["open"]           for day in common]
    ratios = [a/c if c else 1.0 for a, c in zip(adjs, closes)]
    arrays[tk] = dict(closes=closes, adj=adjs, opens=opens, ratio=ratios)

for sig, _, _, wma, sma in EQUITY_CONFIGS:
    c = arrays[sig]["closes"]
    arrays[sig]["wma"]  = compute_wma(c, wma)
    arrays[sig]["sma"]  = compute_sma(c, sma)
    arrays[sig]["hvol"] = compute_hvol(c, VOL_PERIOD)

vix_close = arrays[VIX_TICKER]["closes"]
vix_sma   = compute_sma(vix_close, VIX_MA_PERIOD)

# Build VIX3M aligned to common dates (None where missing)
vix3m_close = [vix3m_raw[d]["close"] if d in vix3m_raw else None for d in common]

# ts_ratio = VIX / VIX3M  (None when VIX3M unavailable)
ts_ratio = [(vix_close[i] / vix3m_close[i]) if vix3m_close[i] else None
            for i in range(n)]

# 5-bar SMA of ts_ratio (skipping leading Nones)
def smooth_ts(series, w):
    n = len(series); out = [None]*n
    for i in range(w-1, n):
        window = series[i-w+1:i+1]
        if any(v is None for v in window): continue
        out[i] = sum(window) / w
    return out
ts_smooth = smooth_ts(ts_ratio, TS_SMOOTH)

cov_is  = sum(1 for x in ts_smooth[:split_idx] if x is not None)
cov_oos = sum(1 for x in ts_smooth[split_idx:] if x is not None)
print(f"  ts_smooth coverage:  IS {cov_is}/{split_idx} ({cov_is/split_idx*100:.0f}%)  "
      f"OOS {cov_oos}/{n-split_idx} ({cov_oos/(n-split_idx)*100:.0f}%)\n")

MIN_IDX = max(VOL_PERIOD, VIX_MA_PERIOD,
              *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


def run(entry_thresh=None, exit_thresh=None):
    """
    entry_thresh: if set, block vehicle entry when ts_smooth >= entry_thresh
                  (when ts_smooth is None, gate is neutral — entries allowed)
    exit_thresh : if set, force vehicle->defensive when ts_smooth >  exit_thresh
                  (when ts_smooth is None, no forced exit)
    Both None  -> baseline v1.2
    """
    def mk(signal, vehicle, defensive, wma, sma):
        return dict(signal=signal, vehicle=vehicle, defensive=defensive,
                    wma_period=wma, sma_period=sma,
                    state="cash", next_state=None,
                    v_shares=0.0, v_entry=0.0, d_shares=0.0, d_entry=0.0,
                    c_shares=0.0, cash=0.0, equity=EQ_ALLOC_EACH,
                    wma_was_below=True, entry_eligible=False, cooldown=0,
                    trades=0)
    sl_list = [mk(*cfg) for cfg in EQUITY_CONFIGS]
    cash_adj0 = arrays[CASH_TICKER]["adj"][0]
    for sl in sl_list:
        sl["c_shares"] = EQ_ALLOC_EACH / cash_adj0
    gld_shares = SAFETY_INIT / arrays["GLD"]["adj"][0]
    gld_equity = SAFETY_INIT
    portfolio = []
    prev_year = int(common[0][:4])
    ts_blocks  = 0
    ts_exits   = 0

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
        if i < MIN_IDX: continue

        vix_now = vix_close[i]; vix_ma_now = vix_sma[i]
        vix_spike = (vix_ma_now is not None and vix_now > vix_ma_now * VIX_SPIKE_MULT)

        ts_now = ts_smooth[i]
        ts_backwardation_exit = (exit_thresh is not None and ts_now is not None
                                 and ts_now > exit_thresh)
        ts_block_entry        = (entry_thresh is not None and ts_now is not None
                                 and ts_now >= entry_thresh)

        for sl in sl_list:
            sig, veh = sl["signal"], sl["vehicle"]
            wa, sa = arrays[sig]["wma"], arrays[sig]["sma"]
            hva = arrays[sig]["hvol"]
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
                do_ts = ts_backwardation_exit
                if do_tp or do_sl or do_v or do_w or do_spike or do_ts:
                    if do_sl: sl["cooldown"] = COOLDOWN_DAYS
                    if do_ts and not (do_tp or do_sl or do_v or do_w or do_spike):
                        ts_exits += 1
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
                if base_ok:
                    if ts_block_entry:
                        ts_blocks += 1
                        # entry blocked — keep latch armed so we can fire when ts clears
                    else:
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
    return portfolio, sum(s["trades"] for s in sl_list), ts_blocks, ts_exits


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


# Baseline
b_curve, b_trades, _, _ = run(None, None)
base_is   = window_metrics(b_curve, 0, split_idx-1)
base_oos  = window_metrics(b_curve, split_idx, n-1)
base_full = window_metrics(b_curve, 0, n-1)

print("=" * 132)
print(f"  B2 VIX TERM-STRUCTURE GATE   IS={common[0]}..{common[split_idx-1]}   OOS={common[split_idx]}..{common[-1]}")
print("=" * 132)
print(f"\n  BASELINE v1.2 (no term-structure filter)")
print(f"    IS   Sharpe {base_is['sharpe']:.4f}   CAGR {base_is['cagr']:+.2f}%   MaxDD {base_is['max_dd']:+.2f}%")
print(f"    OOS  Sharpe {base_oos['sharpe']:.4f}   CAGR {base_oos['cagr']:+.2f}%   MaxDD {base_oos['max_dd']:+.2f}%")
print(f"    full Sharpe {base_full['sharpe']:.4f}   Final ${base_full['final']:,.0f}   CAGR {base_full['cagr']:+.2f}%   Trades {b_trades}")

variants = []
# Variant A — entry gate only
for et in (0.95, 1.00, 1.05):
    variants.append((f"A entry<{et:.2f}", et, None))
# Variant B — forced vehicle exit only
for xt in (1.00, 1.05, 1.10):
    variants.append((f"B exit>{xt:.2f}", None, xt))
# Variant C — both
for et, xt in [(1.00, 1.05), (1.05, 1.05), (1.00, 1.10)]:
    variants.append((f"C entry<{et:.2f}+exit>{xt:.2f}", et, xt))

print()
print("─" * 132)
print(f"  {'Variant':<28}  {'IS Shp':>7}  {'ΔIS':>8}  {'OOS Shp':>8}  {'ΔOOS':>8}  "
      f"{'Full Shp':>9}  {'ΔFull':>8}  {'Final $':>13}  {'Trades':>6}  {'Blocks':>6}  {'TSExits':>7}")
print("─" * 132)

cands = []
for label, et, xt in variants:
    curve, trades, blocks, exits = run(et, xt)
    is_m   = window_metrics(curve, 0, split_idx-1)
    oos_m  = window_metrics(curve, split_idx, n-1)
    full_m = window_metrics(curve, 0, n-1)
    cands.append((label, is_m, oos_m, full_m, trades, blocks, exits))

cands.sort(key=lambda r: r[1]["sharpe"], reverse=True)
for label, is_m, oos_m, full_m, trades, blocks, exits in cands:
    d_is   = is_m["sharpe"]  - base_is["sharpe"]
    d_oos  = oos_m["sharpe"] - base_oos["sharpe"]
    d_full = full_m["sharpe"]- base_full["sharpe"]
    mark = "  ★ BOTH" if (d_is > 0 and d_oos > 0) else ""
    print(f"  {label:<28}  {is_m['sharpe']:>7.4f}  {d_is:>+7.4f}  "
          f"{oos_m['sharpe']:>8.4f}  {d_oos:>+7.4f}  "
          f"{full_m['sharpe']:>9.4f}  {d_full:>+7.4f}  ${full_m['final']:>12,.0f}  {trades:>6}  {blocks:>6}  {exits:>7}{mark}")

print()
print("=" * 132)
print("  PURE WALK-FORWARD VALIDATION")
print("=" * 132)
print("  Top 5 candidates by IS Sharpe:")
for label, is_m, oos_m, *_ in cands[:5]:
    d_oos = oos_m["sharpe"] - base_oos["sharpe"]
    holds = "✓ holds OOS"  if d_oos > 0 else "✗ FAILS OOS"
    print(f"    {label:<28}  IS Sharpe {is_m['sharpe']:.4f}  -> OOS Sharpe {oos_m['sharpe']:.4f}  "
          f"(baseline OOS {base_oos['sharpe']:.4f}, ΔOOS {d_oos:+.4f})   {holds}")

w = cands[0]
print(f"\n  IS-WINNER: {w[0]}")
print(f"    IS  : Sharpe {w[1]['sharpe']:.4f}  vs baseline {base_is['sharpe']:.4f}  "
      f"(Δ {w[1]['sharpe']-base_is['sharpe']:+.4f})")
print(f"    OOS : Sharpe {w[2]['sharpe']:.4f}  vs baseline {base_oos['sharpe']:.4f}  "
      f"(Δ {w[2]['sharpe']-base_oos['sharpe']:+.4f})")
print(f"    full: Sharpe {w[3]['sharpe']:.4f}  Final ${w[3]['final']:,.0f}  "
      f"CAGR {w[3]['cagr']:+.2f}%  MaxDD {w[3]['max_dd']:+.2f}%  Trades {w[4]}")
verdict_is  = "✓" if w[1]["sharpe"]  > base_is["sharpe"]  else "✗"
verdict_oos = "✓" if w[2]["sharpe"] > base_oos["sharpe"] else "✗"
print(f"\n  Walk-forward verdict:  IS {verdict_is}   OOS {verdict_oos}")
