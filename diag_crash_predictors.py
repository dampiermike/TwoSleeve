#!/usr/bin/env python3
"""
CRASH-PREDICTOR DIAGNOSTIC (not a backtest — a research probe).

Question: do candidate LEADING indicators flash a warning BEFORE the
drawdowns that hurt Two-Sleeves v1.1?

Method:
  1. Find every >20% drawdown in the v1.1 portfolio equity curve.
  2. Build candidate leading indicators from full-history data.
  3. For each drawdown peak, measure whether (and how early) each
     indicator was in "warning" state.
  4. Measure false positives: total % of time the indicator warns.

A USEFUL predictor: warns within ~20 trading days BEFORE most peaks,
AND spends little total time warning (few false alarms).

Candidate indicators (all built from 2000-01-03 full-history data):
  XLY/XLP    : consumer discretionary vs staples — risk appetite gauge.
               Warn when XLY/XLP ratio < its own 50-bar SMA.
  OFF/DEF    : (XLK+XLY+XLF) vs (XLU+XLP+XLV) — offense vs defense.
               Warn when the ratio < its own 50-bar SMA.
  XLU>SPY    : utilities outperforming the market over 20 bars.
               Warn when XLU 20-bar return − SPY 20-bar return > +2%.
  VIX>MA50   : VIX above its own 50-bar SMA (vol regime turning up —
               uses VIX as a TREND, not a level).
"""

import json, math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"
OSC_HIST  = Path("/Users/mikedampier/Documents/Development/Oscillator/json/history")
BACKTEST_START = date(2000, 1, 1)


def load_series(ticker, src_dir, suffix="_US"):
    raw = json.load(open(src_dir / f"{ticker}{suffix}.json"))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}

def sma(series, p):
    n, out = len(series), [None]*len(series)
    if n < p: return out
    s = sum(series[:p]); out[p-1] = s/p
    for i in range(p, n):
        s += series[i] - series[i-p]; out[i] = s/p
    return out


# ── Load v1.1 equity curve & find drawdowns ──────────────────────────────────
import csv
with open(WORKSPACE / "backtest_two_sleeves_v1_1_equity_curve.csv") as f:
    curve = list(csv.DictReader(f))
dates  = [r["date"] for r in curve]
equity = [float(r["equity"]) for r in curve]

# Detect drawdowns deeper than 20%
peak = equity[0]; cur_peak_date = dates[0]
trough_v = peak; trough_d = dates[0]
drawdowns = []
for i, e in enumerate(equity):
    if e > peak:
        if trough_v < peak * 0.80:
            drawdowns.append(dict(peak_date=cur_peak_date, peak_val=peak,
                                  trough_date=trough_d, trough_val=trough_v,
                                  dd=(trough_v-peak)/peak*100))
        peak = e; cur_peak_date = dates[i]; trough_v = e; trough_d = dates[i]
    elif e < trough_v:
        trough_v = e; trough_d = dates[i]
if trough_v < peak * 0.80:
    drawdowns.append(dict(peak_date=cur_peak_date, peak_val=peak,
                          trough_date=trough_d, trough_val=trough_v,
                          dd=(trough_v-peak)/peak*100))

print("=" * 92)
print(f"  v1.1 portfolio drawdowns > 20%  ({len(drawdowns)} found)")
print("=" * 92)
for d in drawdowns:
    print(f"  peak {d['peak_date']}  ->  trough {d['trough_date']}   {d['dd']:+.1f}%")
print()

# ── Build common date axis from sector data ──────────────────────────────────
need = ["XLY", "XLP", "XLK", "XLF", "XLU", "XLV", "SPY"]
data = {t: load_series(t, OSC_HIST) for t in need}
vix  = load_series("VIX_INDX", DATA_DIR, suffix="")

common = sorted(set.intersection(*[set(data[t].keys()) for t in need]) & set(vix.keys()))
idx = {d: i for i, d in enumerate(common)}
n = len(common)

closes = {t: [data[t][d]["close"] for d in common] for t in need}
vix_c  = [vix[d]["close"] for d in common]


# ── Build candidate indicators → boolean "warning" arrays ────────────────────
def ratio_below_sma(num, den, p=50):
    r = [num[i]/den[i] if den[i] else 1.0 for i in range(n)]
    m = sma(r, p)
    return [(m[i] is not None and r[i] < m[i]) for i in range(n)]

# XLY/XLP
warn_xlyxlp = ratio_below_sma(closes["XLY"], closes["XLP"])

# OFF/DEF composite (normalized equal-weight baskets)
def basket(tickers):
    # normalize each ticker to its first value, then average
    norm = []
    for t in tickers:
        c = closes[t]; base = c[0]
        norm.append([v/base for v in c])
    return [sum(norm[k][i] for k in range(len(tickers)))/len(tickers) for i in range(n)]
off = basket(["XLK", "XLY", "XLF"])
dfn = basket(["XLU", "XLP", "XLV"])
warn_offdef = ratio_below_sma(off, dfn)

# XLU 20-bar return minus SPY 20-bar return > +2%
warn_xlu = [False]*n
for i in range(20, n):
    xlu_r = closes["XLU"][i]/closes["XLU"][i-20] - 1
    spy_r = closes["SPY"][i]/closes["SPY"][i-20] - 1
    warn_xlu[i] = (xlu_r - spy_r) > 0.02

# VIX above its own 50-bar SMA
vix_ma = sma(vix_c, 50)
warn_vixma = [(vix_ma[i] is not None and vix_c[i] > vix_ma[i]) for i in range(n)]

INDICATORS = [
    ("XLY/XLP < SMA50",  warn_xlyxlp),
    ("OFF/DEF < SMA50",  warn_offdef),
    ("XLU 20d > SPY+2%", warn_xlu),
    ("VIX > its SMA50",  warn_vixma),
]


# ── Diagnostic: lead time before each drawdown peak + false-positive rate ─────
def nearest_idx(dstr):
    """Index in `common` of the date, or the last date <= dstr."""
    if dstr in idx: return idx[dstr]
    cand = [i for i, d in enumerate(common) if d <= dstr]
    return cand[-1] if cand else 0

print("=" * 92)
print("  LEAD-TIME DIAGNOSTIC — was each indicator warning BEFORE the drawdown peak?")
print("  (lead = trading days before peak the warning first turned on and stayed on)")
print("=" * 92)

for name, warn in INDICATORS:
    total_warn = sum(1 for w in warn if w)
    pct_warn = total_warn / n * 100
    print(f"\n── {name} ──   (warns {pct_warn:.0f}% of all bars)")
    hits = 0
    for d in drawdowns:
        pk = nearest_idx(d["peak_date"])
        # warning state on the peak bar?
        at_peak = warn[pk]
        # lead: scan back up to 40 bars — how many consecutive(ish) warning bars before peak
        lead = 0
        for back in range(0, 41):
            j = pk - back
            if j < 0: break
            if warn[j]:
                lead = back
            else:
                # allow it to be the contiguous run ending at/near peak
                if back <= 2:   # small gap tolerance near the peak
                    continue
                break
        warned_window = any(warn[max(0,pk-20):pk+1])
        if warned_window: hits += 1
        flag = "✓" if warned_window else "·"
        print(f"  {flag} peak {d['peak_date']} ({d['dd']:+.0f}%)  "
              f"at-peak={'WARN' if at_peak else 'calm':<4}  "
              f"first-warned ~{lead:>2}d before peak")
    print(f"  → caught {hits}/{len(drawdowns)} drawdowns within 20d before the peak")


# ── Signal-quality test: forward 20-bar SPY return, warning vs calm ───────────
# A real predictor makes forward returns meaningfully WORSE when it warns.
print()
print("=" * 92)
print("  SIGNAL-QUALITY TEST — forward 20-bar SPY return: WARNING days vs CALM days")
print("  (a genuine predictor → warning-day forward returns clearly worse than calm)")
print("=" * 92)
spy = closes["SPY"]
fwd = [None]*n
for i in range(n - 20):
    fwd[i] = (spy[i+20]/spy[i] - 1) * 100.0

def stats(mask):
    vals = [fwd[i] for i in range(n) if fwd[i] is not None and mask[i]]
    if not vals: return (0, 0.0, 0.0)
    mean = sum(vals)/len(vals)
    neg  = sum(1 for v in vals if v < 0)/len(vals)*100
    return (len(vals), mean, neg)

print(f"  {'Indicator':<20} {'warn fwd-ret':>14} {'calm fwd-ret':>14} {'edge':>9} {'warn %neg':>11}")
print("-" * 92)
for name, warn in INDICATORS:
    calm = [not w for w in warn]
    wn, wm, wneg = stats(warn)
    cn, cm, cneg = stats(calm)
    edge = wm - cm
    print(f"  {name:<20} {wm:>+13.2f}% {cm:>+13.2f}% {edge:>+8.2f}% {wneg:>10.0f}%")

# Composite: require all four to agree
allwarn = [warn_xlyxlp[i] and warn_offdef[i] and warn_xlu[i] and warn_vixma[i]
           for i in range(n)]
calm = [not w for w in allwarn]
wn, wm, wneg = stats(allwarn)
cn, cm, cneg = stats(calm)
print("-" * 92)
print(f"  {'ALL 4 agree':<20} {wm:>+13.2f}% {cm:>+13.2f}% {wm-cm:>+8.2f}% {wneg:>10.0f}%")
print(f"  (composite warns {sum(allwarn)/n*100:.1f}% of bars — {wn} warning days)")
