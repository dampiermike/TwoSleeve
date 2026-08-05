# Two-Sleeves Optimized — Build Guide v1.3 (CANDIDATE)

*Non-equity defensive state · Low-correlation sector sleeves · Per-sleeve vol gates · Monthly rebalance · Strictly causal pricing*

**Backtest:** 2000-01-03 → 2026-05-22 · $100,000 starting capital · 6,637 bars

> 🚧 **STATUS: CANDIDATE — NOT ADOPTED.** v1.2 remains the live traded strategy.
> `two_sleeve_daily_signal_v1_3.py` runs in shadow inside the daily job and its
> call appears in the email and text, clearly labelled, so it can be watched
> before any capital is committed. It shares no state with the v1.2 signal and
> cannot affect the live call.

---

## Why v1.3 Exists

v1.2's max drawdown of −39.32% happens in March 2020. The diagnostic that
produced this version: **at the COVID trough, both sleeves were already in the
`defensive` state.** Every exit rule fired correctly and on time. The portfolio
still lost 39% — because v1.2's `defensive` state holds the *unlevered signal
ETF* (QQQ/SPY), and unlevered QQQ/SPY fell ~34% in those 22 sessions.

So the drawdown was never a leverage-timing failure. It was a **defensive-asset
failure**. Appendix B of v1.2 had tested what the *cash* state holds
(`Cash → TLT/GLD`, rejected). It had never tested what the *defensive* state
holds. That was the untested lever, and it is the largest single improvement
found in roughly 70,000 backtested configurations.

---

## Changes From v1.2

| # | Change | v1.2 | v1.3 |
|---|---|---|---|
| 1 | **Core defensive holding** | QQQ (1× equity) | **TLT** |
| 2 | **Second sleeve** | SPY→SPXL (3×) | **XLE + XLV** (unlevered sectors) |
| 3 | **Vol entry gate** | 16% for both sleeves | **per-sleeve: 25% core, 12% sectors** |
| 4 | Safety allocation | 10% GLD | **5% GLD** |
| 5 | Rebalance | annual | **monthly** |
| 6 | Defensive stop | 18% | **14%** |
| 7 | VIX spike multiplier | 2.0× | **2.2×** |

Unchanged v1.2 mechanics: the entry latch, 30-bar cooldown, 200% take-profit,
12% hard stop, 30% vol exit, VIX-spike exit, BIL cash state, and strictly causal
next-open execution.

### 1. The defensive state stops holding equity

The core sleeve rotates to **TLT** instead of QQQ. Measured in isolation across
25 defensive-asset combinations, moving the defensive state out of unlevered
equity cut max drawdown from −39.32% to about −28% at equal-or-better CAGR. The
effect is structural, not fitted — nearly every non-equity defensive improved
drawdown substantially.

### 2. The second equity sleeve is replaced by uncorrelated sectors

SPY→SPXL correlates **0.55** with QQQ→TQQQ. It was largely a second helping of
the same bet. Measured daily-return correlation against the core sleeve:

| Sleeve | Correlation to core | Standalone CAGR |
|---|---:|---:|
| SPY→SPXL | 0.55 | 25.4% |
| XLK | 0.48 | 16.1% |
| **XLV** | **0.23** | 12.9% |
| **XLE** | **0.14** | 15.0% |
| TMF (3× treasuries) | 0.02 | 14.0% |
| UGL (2× gold) | 0.00 | 13.3% |

XLE and XLV are the sweet spot: low enough correlation to cut drawdown, high
enough return to earn their weight. TMF and UGL are *perfectly* uncorrelated but
too low-returning to carry capital — tested and rejected (see Appendix B).

Energy is the specific reason this fixes the historical weak spot: XLE compounded
about **30%/yr through 2003–2007**, precisely the stretch where v1.2 earns 12%.

### 3. Per-sleeve volatility gates

A single HVol ≤ 16% entry gate is calibrated for large-cap equity. Applied to a
sector sleeve it is wrong. The core runs a **looser 25%** gate (it is the return
engine and should stay invested); the sector sleeves run a **tight 12%** gate
(they exist to be calm ballast, not to chase).

---

## Target Numbers — Final System

| Metric | Target |
|---|---:|
| Final equity | **$85,168,113** |
| CAGR | **+29.14%** |
| Max drawdown | **−29.80%** |
| Sharpe ratio | **1.0966** |
| Real trades | **143** |
| Rebalance events | 316 |
| VIX spike-driven exits | 4 |
| Bars | 6,637 |
| Period | 2000-01-03 → 2026-05-22 |

> **Precision rules** (same as v1.2):
> - Final equity: match to the dollar
> - CAGR / MaxDD: match to 2 decimal places
> - Sharpe: match to 4 decimal places
> - Trade counts: match exactly

### Versus v1.2, same data

| | v1.2 | **v1.3** |
|---|---:|---:|
| Final equity | $37,913,438 | **$85,168,113** |
| CAGR | +25.24% | **+29.14%** |
| Max drawdown | −39.32% | **−29.80%** |
| Sharpe | 0.9666 | **1.0966** |

Terminal wealth **2.25×**, drawdown **9.5 points shallower**, Sharpe **+0.13**.

---

## Walk-Forward Validation

The project's standard: a change is only credible if it improves **both** halves
of a 2000-2014 / 2015-2026 split. Every rejection in v1.2's Appendix B failed
this test. v1.3 passes it.

| Window | v1.2 | **v1.3** |
|---|---|---|
| IS 2000–2014 | 20.20% / −37.46% / 0.8430 | **27.91% / −26.87% / 1.0257** |
| OOS 2015–2026 | 31.84% / −39.32% / 1.1247 | **30.46% / −29.80% / 1.2285** |
| Full 2000–2026 | 25.24% / −39.32% / 0.9666 | **29.14% / −29.80% / 1.0966** |

In-sample it is better on all three metrics by a wide margin. Out-of-sample it
gives up **1.4 points of CAGR** and buys **9.5 points of drawdown** and **+0.10
Sharpe**. That is the honest trade being made.

### By era

| Era | v1.2 CAGR / DD | v1.3 CAGR / DD |
|---|---|---|
| 2000–2002 dot-com | 1.1% / −8.5% | **4.4% / −0.9%** |
| 2003–2007 | 12.0% / −24.3% | **16.1% / −22.9%** |
| 2008–2009 GFC | 19.0% / −14.9% | **30.7% / −13.9%** |
| 2010–2014 | 29.9% / −28.0% | 26.0% / −26.9% |
| 2015–2019 | 24.7% / −24.1% | **25.2% / −21.0%** |
| 2020–2026 | 23.6% / −28.2% | **26.9% / −24.2%** |

*(era figures on drag-calibrated data — see caveat below)*

v1.3 wins decisively in the crisis eras and gives back ground only in 2010–2014,
a uniformly strong tech bull market where the sector sleeves were a drag.

---

## ⚠ Synthetic-History Caveat — Read Before Trusting These Numbers

TQQQ's pre-2010 bars are modelled as exactly **3.00× QQQ with ZERO drag**. That
is the convention already used by v1, v1.1 and v1.2. Measured against the real
fund over its live history, the convention **overstates returns by ~7%/yr**,
because it ignores expense ratio, financing cost and daily-reset volatility
decay. Across the leveraged universe the gap is 4–7%/yr (24%/yr for SOXL).

Recalculated with drag calibrated per fund by OLS on each fund's real overlap
(`r_fund = β·r_underlying + α`):

| | v1.2 | **v1.3** |
|---|---:|---:|
| CAGR | 24.70% | **28.52%** |
| Max drawdown | −39.32% | **−29.80%** |
| Sharpe | 0.9523 | **1.0823** |
| Final equity | $33,805,440 | **$74,969,117** |

**The relative improvement is preserved on either convention.** The headline
numbers in this guide use the repo convention so they stay comparable with v1.1
and v1.2; the drag-calibrated figures are the more realistic ones.

---

## Data Dependency

Nine files (was seven). `two_sleeve_update_data.py` maintains all of them.

| File | Role | History |
|---|---|---|
| `QQQ_US.json` | core signal | real |
| `TQQQ_US.json` | core vehicle | spliced (synthetic pre-2010-02) |
| `TLT_US.json` | core defensive | spliced (synthetic 2000-01 → 2002-07) |
| `XLE_US.json` | energy sleeve signal + vehicle | real from 1999 |
| `XLV_US.json` | healthcare sleeve signal + vehicle | real from 1999 |
| `GLD_US.json` | safety sleeve + sector defensive | spliced (synthetic pre-2004-11) |
| `BIL_US.json` | cash state | spliced |
| `VIX_INDX.json` | VIX spike exit | real |

`SPY_US.json` and `SPXL_US.json` are retained for v1.1/v1.2 but unused by v1.3.

> GLD's splice was corrected in `eb6cc39` — see the v1.2 guide's Data Integrity
> section. All v1.3 figures are computed on the corrected series.

---

## Configuration

```python
TOTAL_CAPITAL   = 100_000.0
SAFETY_TICKER   = "GLD";  SAFETY_ALLOC = 0.05
CASH_TICKER     = "BIL"
VOL_PERIOD      = 20
VOL_EXIT_THRESH = 30.0
TAKE_PROFIT_PCT = 200.0
STOP_LOSS_PCT   = 12.0
DEF_STOP_PCT    = 14.0
COOLDOWN_DAYS   = 30
REBAL_FREQ      = "monthly"
VIX_MA_PERIOD   = 20;  VIX_SPIKE_MULT = 2.2

# (signal, vehicle, defensive, wma, sma, weight, vol_entry_max)
SLEEVE_CONFIGS = [
    ("QQQ", "TQQQ", "TLT",  5, 200, 75, 25.0),
    ("XLE", "XLE",  "GLD", 16, 175, 14, 12.0),
    ("XLV", "XLV",  "GLD", 16, 125, 11, 12.0),
]
```

Weights are relative and normalised to fill `1 − SAFETY_ALLOC`, giving effective
portfolio weights of **71.25% / 13.30% / 10.45% / 5.00% GLD**.

Weights were rounded from the raw search output (75.37 / 13.54 / 11.10) with no
material change (28.57% → 28.52% CAGR, −29.91% → −29.80% DD on drag-calibrated
data). The optimum is not knife-edge — neighbouring splits 75/15/10 and 74/14/12
land within 0.2pp of CAGR. But note **76/14/10 tips drawdown to −30.27%**, so
the drawdown constraint is genuinely tight and core weight should not be nudged
upward without re-checking.

---

## Appendix A — What Was Excluded From v1.3 (And Why)

Search scope: ~70,000 configurations. Expanded instrument universe fetched from
EODHD (TMF, UGL, UPRO, UDOW, QLD, SSO, SOXL, TNA, SMH, XLK, XLE, XLV, XLF, DIA,
IWM, EFA, EEM, IEF), with synthetic pre-inception history built by the same
method as the existing TQQQ/SPXL bars.

| Feature | Result | Status |
|---|---|---|
| **Defensive → TLT/GLD instead of 1× equity** | −39.32% → ~−28% DD at equal CAGR; better on both walk-forward halves | **ADOPTED** |
| **XLE + XLV replacing SPY→SPXL** | Correlation 0.14/0.23 vs 0.55; adds CAGR *and* cuts DD | **ADOPTED** |
| **Per-sleeve vol gates** | Core 25% / sectors 12% beats a shared 16% | **ADOPTED** |
| TMF (3× treasuries) sleeve | Correlation 0.02 — a perfect diversifier, but only 14.0% standalone CAGR. Earns no weight without diluting below target. | Rejected |
| UGL (2× gold) sleeve | Correlation 0.00, 13.3% standalone CAGR. Same problem as TMF. | Rejected |
| Unlevered GLD/TLT third sleeve | Improves Sharpe and DD but dilutes CAGR 26.68% → 20.58% | Rejected |
| **Timing diversification** (2–4 TQQQ sleeves on different WMA/SMA) | Seemed like a free lunch — same asset CAGR, decorrelated entries. **Fails: differently-tuned TQQQ sleeves correlate 0.80–1.00.** Big drawdowns are asset-driven, not timing-driven. Best result 26.57% CAGR, worse than the adopted config. | Rejected |
| SOXL / TNA sleeves | SMH and IWM history begins 2000-05, truncating the window past the dot-com crash and *flattering* results. Excluded to keep the window fixed at 2000-01-03. | Excluded |
| Cash state → GLD / TLT | Re-tested on corrected GLD data; BIL still best. v1.2's Appendix B conclusion holds. | Rejected |
| Leveraged safety sleeve (UGL/TMF buy & hold) | No improvement over 5% GLD | Rejected |
| VIX spike exit | Still mildly positive at 2.2× — but note it is **near-redundant** once the defensive state is non-equity. Its original job was escaping 3× into 1× equity; with TLT as defensive there is far less left to save. Retained at low conviction. | Retained |

### The target that was not reached

The goal set for this exploration was **CAGR > 30% with max drawdown < 30% over
the full 2000–2026 window.** v1.3 does not reach it (29.14% / −29.80%), and the
search establishes that it is **not reachable with this architecture**:

- **0 hits in ~70,000 configurations.**
- No single sleeve exceeds **32.03% CAGR**, and that one carries **−62.80% DD**.
- Portfolio CAGR is approximately the weighted mean of sleeve CAGRs, so clearing
  30% requires ~90% concentration in the core, which forces drawdown back above
  36%.
- Frontier at the corner: best CAGR with DD < 30% is **28.57%**; shallowest DD
  with CAGR > 30% is **−35.85%**. The two do not meet.

The binding constraint is the 2000–2007 stretch, where the strategy earns 1–16%.
Reaching 30% would require either a shorter evaluation window (the target *is*
reachable on 2010–2026, and v1.3 already achieves **30.46% / −29.80%** on the
2015–2026 half), or a departure from the sleeve state machine — dynamic leverage
sizing, a portfolio-level circuit breaker, or inverse exposure in confirmed
downtrends.

---

## Appendix B — Operational Notes

`two_sleeve_run_daily.sh` runs v1.3 as **Step 2b**, after the live v1.2 signal:

- The v1.3 section appears in the **daily email** in full.
- The **text message** carries the live v1.2 call as its headline, plus a second
  line: `[v1.3 candidate, not live] …`.
- v1.3 failure is caught and cannot fail the run or affect the v1.2 signal.
- The two signals share no state — both are stateless replays of full history.

**To promote v1.3 to live**, swap the script invoked in Step 2 of
`two_sleeve_run_daily.sh` and drop Step 2b. Do not do this until the shadow
signals have been watched long enough to trust, and note that it changes the
traded universe — v1.3 holds TLT, XLE and XLV, which the v1.2 portfolio never
touches.

---

*Two-Sleeves Optimized · Build Guide v1.3 (candidate) · Backtest does not guarantee future results*
