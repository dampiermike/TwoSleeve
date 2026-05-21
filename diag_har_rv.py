#!/usr/bin/env python3
"""
HAR-RV CRASH-PREDICTOR DIAGNOSTIC (research probe, not a backtest).

HAR-RV (Corsi 2009) — Heterogeneous AutoRegressive model of Realized
Volatility. Forecasts next-period realized variance from a regression on
its own daily / weekly(5d) / monthly(22d) components:

    RV[t+1] = b0 + b_d*RV_d[t] + b_w*RV_w[t] + b_m*RV_m[t]

Rationale: returns are ~unpredictable, but volatility clusters and IS
forecastable. The strategy currently gates on TRAILING HVol; HAR-RV
gives a FORECAST instead — a candidate forward-looking crash warning.

Data note: no intraday data, so daily RV uses the Parkinson range
estimator from the H/L range (more efficient than close-to-close):
    RV_park[t] = (1/(4 ln2)) * (ln(High/Low))^2

Look-ahead control: the HAR regression is fit on an EXPANDING window
(past data only), refit every 21 bars, producing genuine out-of-sample
1-step-ahead forecasts.

Tests:
  1. HAR regression coefficients (sanity vs Corsi's canonical result).
  2. Forecast accuracy vs a naive "tomorrow = today" benchmark.
  3. Signal quality — forward 20-bar return when the HAR forecast is
     ELEVATED, and when it is RISING FAST.
  4. Lead test — before each >20% drawdown, does the HAR forecast turn
     up EARLIER than the strategy's trailing HVol?
"""

import json, csv, math
from datetime import date
from pathlib import Path
import numpy as np

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"
BACKTEST_START = date(2000, 1, 1)
SIGNAL_TICKER  = "SPY"     # broad-market proxy for crash prediction

LN2 = math.log(2.0)


def load(ticker):
    raw = json.load(open(DATA_DIR / f"{ticker}_US.json"))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return raw


# ── Load SPY and build daily realized variance (Parkinson) ───────────────────
bars   = load(SIGNAL_TICKER)
dates  = [b["date"] for b in bars]
highs  = np.array([b["high"]  for b in bars], float)
lows   = np.array([b["low"]   for b in bars], float)
closes = np.array([b["close"] for b in bars], float)
n = len(bars)

# Parkinson daily realized variance
rv = np.zeros(n)
for i in range(n):
    if lows[i] > 0 and highs[i] > 0:
        rv[i] = (1.0 / (4.0 * LN2)) * (math.log(highs[i] / lows[i]) ** 2)

# HAR components: daily, weekly(5), monthly(22) trailing means of RV
rv_d = rv.copy()
rv_w = np.array([rv[max(0, i-4):i+1].mean()  for i in range(n)])
rv_m = np.array([rv[max(0, i-21):i+1].mean() for i in range(n)])


# ── Expanding-window HAR-RV — genuine out-of-sample 1-step forecasts ──────────
TRAIN_MIN = 500     # minimum training bars before first forecast
REFIT     = 21      # refit cadence (bars)

har_fc = np.full(n, np.nan)   # out-of-sample forecast of RV[t+1]
beta   = None
last_betas = []

for t in range(TRAIN_MIN, n - 1):
    if beta is None or (t - TRAIN_MIN) % REFIT == 0:
        # Fit on pairs (features[s], rv[s+1]) for s in [22, t-1]
        s = np.arange(22, t)
        X = np.column_stack([np.ones(len(s)), rv_d[s], rv_w[s], rv_m[s]])
        y = rv[s + 1]
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        last_betas.append((dates[t], beta))
    har_fc[t + 1] = beta[0] + beta[1]*rv_d[t] + beta[2]*rv_w[t] + beta[3]*rv_m[t]

har_fc = np.clip(har_fc, 1e-12, None)

# Annualised HAR vol forecast (%) — comparable to the strategy's HVol
har_vol = np.sqrt(har_fc * 252.0) * 100.0

# Strategy-style trailing HVol (close-to-close, 20d, sample var, annualised)
hvol = np.full(n, np.nan)
for i in range(20, n):
    lr = np.log(closes[i-19:i+1] / closes[i-20:i])
    hvol[i] = math.sqrt(lr.var(ddof=1) * 252.0) * 100.0


# ── 1. Regression coefficients ───────────────────────────────────────────────
print("=" * 90)
print("  HAR-RV  —  expanding-window regression  (final fitted coefficients)")
print("=" * 90)
d0, b = last_betas[-1]
print(f"  Last refit {d0}:  RV[t+1] = {b[0]:.2e} + {b[1]:.3f}*RV_d + {b[2]:.3f}*RV_w + {b[3]:.3f}*RV_m")
print(f"  Component weights sum = {b[1]+b[2]+b[3]:.3f}  (Corsi: all positive, sum < 1 → mean-reverting)")

# ── 2. Forecast accuracy vs naive ────────────────────────────────────────────
valid = ~np.isnan(har_fc)
valid[-1] = False
naive = np.concatenate([[np.nan], rv[:-1]])     # tomorrow = today
def rmse(pred):
    m = valid & ~np.isnan(pred)
    return math.sqrt(np.mean((pred[m] - rv[m])**2))
print()
print(f"  1-step RV forecast RMSE:  HAR-RV = {rmse(har_fc):.2e}   "
      f"naive(today) = {rmse(naive):.2e}")
better = (rmse(har_fc) < rmse(naive))
print(f"  HAR-RV {'beats' if better else 'does NOT beat'} the naive benchmark on RV forecasting.")

# ── 3. Signal quality — forward 20-bar return vs HAR forecast state ───────────
fwd = np.full(n, np.nan)
for i in range(n - 20):
    fwd[i] = (closes[i+20] / closes[i] - 1) * 100.0

def stats(mask):
    m = mask & ~np.isnan(fwd) & valid
    v = fwd[m]
    if len(v) == 0: return (0, 0.0, 0.0)
    return (len(v), float(v.mean()), float((v < 0).mean() * 100))

print()
print("=" * 90)
print("  SIGNAL QUALITY — forward 20-bar SPY return conditioned on the HAR-RV forecast")
print("=" * 90)

# (a) forecast LEVEL: top third vs bottom third
hv = har_vol.copy(); hv[~valid] = np.nan
q33, q67 = np.nanpercentile(hv, [33, 67])
hi = valid & (har_vol >= q67)
lo = valid & (har_vol <= q33)
_, hi_m, hi_neg = stats(hi)
_, lo_m, lo_neg = stats(lo)
print(f"\n  (a) Forecast LEVEL")
print(f"      HAR vol HIGH (top third, ≥{q67:.1f}%):  fwd ret {hi_m:+.2f}%   %neg {hi_neg:.0f}%")
print(f"      HAR vol LOW  (bot third, ≤{q33:.1f}%):  fwd ret {lo_m:+.2f}%   %neg {lo_neg:.0f}%")
print(f"      edge (high − low): {hi_m - lo_m:+.2f}%   "
      f"({'correct sign' if hi_m < lo_m else 'WRONG sign'})")

# (b) forecast RISING fast: forecast up >30% vs its value 5 bars ago, still low
rising = np.zeros(n, bool)
for i in range(5, n):
    if valid[i] and valid[i-5] and har_vol[i-5] > 0:
        rising[i] = (har_vol[i] / har_vol[i-5] >= 1.30)
_, ri_m, ri_neg = stats(valid & rising)
_, fl_m, fl_neg = stats(valid & ~rising)
print(f"\n  (b) Forecast RISING FAST  (HAR vol up ≥30% in 5 bars)")
print(f"      rising:     fwd ret {ri_m:+.2f}%   %neg {ri_neg:.0f}%   ({int((valid&rising).sum())} days)")
print(f"      not rising: fwd ret {fl_m:+.2f}%   %neg {fl_neg:.0f}%")
print(f"      edge (rising − not): {ri_m - fl_m:+.2f}%   "
      f"({'correct sign' if ri_m < fl_m else 'WRONG sign'})")

# (c) forecast rising fast WHILE still moderate (<20%) — early-warning ideal
early = np.zeros(n, bool)
for i in range(5, n):
    if valid[i] and rising[i] and har_vol[i] < 20.0:
        early[i] = True
_, ea_m, ea_neg = stats(valid & early)
print(f"\n  (c) EARLY WARNING  (forecast rising ≥30% in 5 bars AND still <20% vol)")
print(f"      early-warning days: fwd ret {ea_m:+.2f}%   %neg {ea_neg:.0f}%   "
      f"({int((valid&early).sum())} days)")

# ── 4. Lead test — HAR forecast vs trailing HVol before each drawdown ─────────
with open(WORKSPACE / "backtest_two_sleeves_v1_1_equity_curve.csv") as f:
    curve = list(csv.DictReader(f))
eq_dates = [r["date"] for r in curve]
eq = [float(r["equity"]) for r in curve]
peak = eq[0]; pkd = eq_dates[0]; tv = peak; td = eq_dates[0]; dds = []
for i, e in enumerate(eq):
    if e > peak:
        if tv < peak*0.80: dds.append((pkd, td, (tv-peak)/peak*100))
        peak = e; pkd = eq_dates[i]; tv = e; td = eq_dates[i]
    elif e < tv: tv = e; td = eq_dates[i]
if tv < peak*0.80: dds.append((pkd, td, (tv-peak)/peak*100))

didx = {d: i for i, d in enumerate(dates)}
def near(dstr):
    if dstr in didx: return didx[dstr]
    c = [i for i, d in enumerate(dates) if d <= dstr]
    return c[-1] if c else 0

print()
print("=" * 90)
print("  LEAD TEST — does the HAR-RV forecast turn up BEFORE trailing HVol?")
print("  (first bar in [peak−30, peak] each measure rose ≥20% off its window minimum)")
print("=" * 90)
def first_rise(series, p0, p1, thr=1.20):
    seg = series[p0:p1+1]
    mn = np.nanmin(seg)
    if not np.isfinite(mn) or mn <= 0: return None
    for k in range(p0, p1+1):
        if np.isfinite(series[k]) and series[k] >= mn*thr:
            return k
    return None

har_leads = 0; counted = 0
for pkd, td, dd in dds:
    pk = near(pkd); p0 = max(0, pk-30)
    fh = first_rise(har_vol, p0, pk)
    fv = first_rise(hvol,    p0, pk)
    if fh is None and fv is None:
        verdict = "neither rose"
    elif fh is None:
        verdict = "only HVol rose"
    elif fv is None:
        verdict = "HAR only"; har_leads += 1; counted += 1
    else:
        counted += 1
        lead = fv - fh
        if lead > 0: har_leads += 1
        verdict = f"HAR {dates[fh]}  vs  HVol {dates[fv]}   HAR leads by {lead}d"
    print(f"  peak {pkd} ({dd:+.0f}%)   {verdict}")
print(f"\n  HAR forecast led trailing HVol in {har_leads}/{counted} drawdowns.")
