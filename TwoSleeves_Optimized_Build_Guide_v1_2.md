# Two-Sleeves Optimized — Build Guide v1.2

*Per-sleeve optimum WMA/SMA · Cash earns risk-free rate (BIL) · VIX spike exit · No pyramid · Strictly causal pricing · Verify every PRECISE checkpoint before continuing*

**Backtest:** 2000-01-03 → 2026-05-22 · $100,000 starting capital · 6,637 bars

---

## Changelog

| Version | Change | Final equity |
|---|---|---:|
| v1 | Per-sleeve optimum WMA/SMA (QQQ 10/175, SPY 5/200). Cash state held 0%-yield dollars. | $35,448,247 |
| v1.1 | Cash state now holds BIL (1–3 month T-bills) — earns the risk-free rate through long crisis stretches. | $50,081,555 |
| **v1.2** | **Adds a 5th vehicle exit: VIX > SMA(VIX, 20) × 2.0 → rotate to defensive.** Walk-forward validated on a 2000-2014 / 2015-2026 split — improves Sharpe on BOTH halves. 5 spike events fired in 26+ years, every one a real named vol shock (Flash Crash, Volmageddon, COVID, Japan carry-trade unwind). | **$69,376,087** |

The v1.2 change improves Sharpe by **+0.013** at the cost of ~1.9 points of MaxDD. Validated on out-of-sample data.

---

## What You Are Building

A two-sleeve tactical rotation strategy where each equity sleeve uses its own individually-optimized WMA/SMA cross. Each sleeve independently rotates between a 3× leveraged vehicle, the underlying ETF as defensive, and a T-bill cash position. A GLD safety allocation runs continuously. **A VIX-spike circuit-breaker exits the vehicle when implied volatility doubles its 20-day average — catching real vol shocks before they become drawdowns.**

Differences from Two-Sleeves w/Gold v3:

1. **WMA/SMA is per-sleeve.** QQQ→TQQQ uses WMA=10/SMA=175. SPY→SPXL uses WMA=5/SMA=200.
2. **Cash state holds BIL** (T-bills), not 0%-yield dollars.
3. **VIX spike exit** as a 5th vehicle exit (v1.2 addition).
4. **No pyramid sizing.** Deferred to v2.
5. **Allocations remain 45/45/10.**

## Target Numbers — Final System

| Metric | Target |
|---|---:|
| Final equity | **$69,376,087** |
| CAGR | **+28.14%** |
| Max drawdown | **−39.32%** |
| Sharpe ratio | **0.9132** |
| Real trades | **88** (39 QQQ + 49 SPY) |
| Rebalance events | 26 |
| VIX spike-driven exits | 5 |
| Bars | 6,637 |
| Period | 2000-01-03 → 2026-05-22 |

> **Precision rules:**
> - Final equity: match to the dollar
> - CAGR / MaxDD: match to 2 decimal places
> - Sharpe: match to 4 decimal places
> - Trade counts: match exactly
> - INFORMATIONAL rows: orientation only

---

## Parameters — Complete Reference

| Parameter | Value | Description |
|---|---|---|
| TOTAL_CAPITAL | $100,000 | Starting portfolio value |
| EQ_ALLOC (per sleeve) | $45,000 (45%) | Initial per-equity-sleeve allocation |
| GLD_ALLOC | $10,000 (10%) | GLD safety allocation |
| EQ_FRAC | 0.45 | Equity sleeve rebalance target fraction |
| GLD_FRAC | 0.10 | GLD rebalance target fraction |
| CASH_TICKER | BIL | Held while a sleeve is in the cash state |
| WMA_PERIOD (QQQ sleeve) | 10 bars | WMA window for QQQ signal |
| SMA_PERIOD (QQQ sleeve) | 175 bars | SMA window for QQQ signal |
| WMA_PERIOD (SPY sleeve) | 5 bars | WMA window for SPY signal |
| SMA_PERIOD (SPY sleeve) | 200 bars | SMA window for SPY signal |
| VOL_PERIOD | 20 bars | HVol window (both signal tickers) |
| HVol variance | Sample (÷N−1) | Use N−1 denominator, NOT N |
| HVol annualization | × √252 × 100 | Produces a percentage (e.g. 16.0 = 16%) |
| VOL_ENTRY_MAX | 16.0% | Max signal HVol to allow new vehicle entry |
| VOL_EXIT_THRESH | 30.0% | Signal HVol that forces vehicle exit |
| TAKE_PROFIT | +200% (×3.0) | Exit when vehicle adj ≥ v_entry × 3.0 |
| STOP_LOSS | −12% (×0.88) | Exit when vehicle adj ≤ v_entry × 0.88 |
| DEF_STOP | −18% (×0.82) | Exit when defensive adj ≤ d_entry × 0.82 |
| COOLDOWN | 30 bars | Cooldown triggered by: hard stop AND defensive stop ONLY |
| **VIX_TICKER** | **VIX_INDX** | **EODHD symbol VIX.INDX, file VIX_INDX.json** |
| **VIX_MA_PERIOD** | **20 bars** | **SMA window on VIX close** |
| **VIX_SPIKE_MULT** | **2.0** | **Exit vehicle when VIX[i] > SMA(VIX, 20) × 2.0** |
| MIN_IDX | max(SMA periods) = 200 | First bar where signals can fire |
| REBAL_TRIGGER | year(i) > year(i−1) | First trading bar of each new calendar year |

---

## Per-Bar Phase Order — Canonical

| Phase | Name | Key constraint |
|---|---|---|
| 1 | State transitions at open[i] | Uses next_state set at Phase 6 of bar i−1. Includes buy/sell of BIL on cash transitions. |
| 2 | Cooldown decrement | Decrement all sleeves before mark-to-market. |
| 3 | Mark to market at close[i] | adj[i] for all positions INCLUDING GLD and BIL. Must precede Phase 4. |
| 4 | Annual rebalance | Reads Phase 3 equity. Only fires if year(i) > year(i−1). |
| 5 | Record portfolio equity | Append post-rebalance total equity to curve. |
| 6 | Entry/exit signal detection | Only fires if i ≥ MIN_IDX. Sets next_state for bar i+1. **v1.2: also reads VIX vs SMA(VIX, 20) and may set next_state='defensive' on a spike.** |

---

## Step 1 — Load the Data

### Input Files (7)

| File | EODHD symbol | Role | Splice notes |
|---|---|---|---|
| QQQ_US.json | QQQ.US | Sleeve 1 signal + defensive | Real history back to 2000 |
| TQQQ_US.json | TQQQ.US | Sleeve 1 vehicle (3× QQQ) | Synthetic pre-2010-02-11 |
| SPY_US.json | SPY.US | Sleeve 2 signal + defensive | Real history back to 2000 |
| SPXL_US.json | SPXL.US | Sleeve 2 vehicle (3× SPY) | Synthetic pre-2008-11-05 |
| GLD_US.json | GLD.US | GLD safety sleeve | Synthetic pre-2004-11-18 |
| BIL_US.json | BIL.US | Cash-state holding (T-bills) | Synthetic pre-2007-05-30 |
| **VIX_INDX.json** | **VIX.INDX** | **VIX index (powers the spike exit)** | **Real history; no splice needed** |

> **DATA SPLICING:** TQQQ, SPXL, GLD, BIL carry synthetic pre-inception history. Use as-is. VIX is real-only.

### Common Date Intersection

Intersect across **all 7** tickers. CRITICAL: do not pad or interpolate.

### Per-Ticker Arrays

For each ticker: `closes`, `adj`, `opens`, `ratio = adj/closes`. Fill price at bar i open = `opens[i] × ratio[i]`.

> 🛑 **STOP AND VERIFY — every PRECISE row must match exactly**
>
> | Check | Target | Type |
> |---|---|---|
> | n (common bars) | 6,637 | PRECISE |
> | common_dates[0] | '2000-01-03' | PRECISE |
> | common_dates[-1] | '2026-05-22' | PRECISE |
> | adj['GLD'][0] | 2.7908 | PRECISE |
> | adj['TQQQ'][0] | 72.5115 | PRECISE |
> | adj['SPXL'][0] | 19.9793 | PRECISE |
> | adj['QQQ'][0] | 80.1346 | PRECISE |
> | adj['SPY'][0] | 91.6138 | PRECISE |
> | adj['BIL'][0] | 56.9642 | PRECISE |
> | **adj['VIX_INDX'][0]** | **24.21** | **PRECISE** |
> | GLD initial shares | 10000 / 2.7908 = 3583.1705 | PRECISE |
> | BIL initial shares (per sleeve) | 45000 / 56.9642 = 789.9699 | PRECISE |

---

## Step 2 — Compute Indicators

Indicators are computed on the two **signal tickers** (QQQ, SPY) and on **VIX**.

### WMA, SMA, HVol — unchanged from v1.1

```
WMA[i]   = sum(closes[i−period+1+j] × (j+1) for j in 0..period-1) / (period×(period+1)/2)
SMA[i]   = SMA[i−1] + (closes[i] − closes[i−period]) / period
HVol[i]  = sqrt(var(log_returns_20, ddof=1) × 252) × 100      # SAMPLE variance, ÷19
```

QQQ: WMA=10, SMA=175. SPY: WMA=5, SMA=200. Both: HVol=20-bar sample variance.

### VIX SMA — new in v1.2

```
vix_sma[i] = SMA(vix['close'], 20)
```

20-bar simple moving average of the VIX close. Same `compute_sma` function as for signal tickers — applied to VIX close.

> 🛑 **STOP AND VERIFY**
>
> | Check | Target | Type |
> |---|---|---|
> | WMA['QQQ'][9] real, [8] None | (period 10) | PRECISE |
> | SMA['SPY'][199] real, [198] None | (period 200) | PRECISE |
> | HVol['QQQ'][20] real, [19] None | (period 20) | PRECISE |
> | HVol['QQQ'] on 2008-10-10 | 51.7% | PRECISE |
> | HVol['QQQ'] on 2017-08-15 | 10.9% | PRECISE |
> | **vix_sma[19] real, [18] None** | **(period 20)** | **PRECISE** |

---

## Step 3 — Build a Single Equity Sleeve

Build QQQ→TQQQ first. Sleeve state object identical to v1.1 (plus the existing `c_shares` for BIL).

### 3a–3c — Loop, latch, entries (unchanged from v1.1)

(See v1.1 guide.)

### 3d — Vehicle Exits — **now FIVE, not four**

Evaluate in priority order while state == 'vehicle' and next_state is None:

| Priority | Exit | Trigger | Cooldown? |
|---|---|---|:--:|
| 1 | Take profit | adj[vehicle][i] ≥ v_entry × 3.0 | no |
| 2 | Hard stop | adj[vehicle][i] ≤ v_entry × 0.88 | **yes (30 bars)** |
| 3 | Vol exit | HVol[signal][i] ≥ 30% | no |
| 4 | WMA cross below | cbl on signal | no |
| **5** | **VIX spike** | **vix[i] > vix_sma[i] × 2.0** | **no** |

On any exit: set next_state = 'defensive', wma_was_below = False. If the **hard stop** fires, also set cooldown = 30. **No cooldown on the VIX spike exit** (same policy as vol_exit).

> The VIX spike exit reads the *closing* VIX of bar i and triggers a defensive fill at bar i+1's open. Standard causal timing.

### 3e — Defensive Stop → Cash (BIL) — unchanged from v1.1

### 3f — Sleeve Isolation Verification

Run each sleeve in isolation: $100K starting capital, no GLD, no rebalance, cash state holding BIL, VIX spike exit active. The early trade history (pre-2009) is identical to v1.1 because the first spike-driven exit doesn't fire until 2009-08-05.

---

## Step 4 — Add SPY Sleeve, GLD, and Annual Rebalance

### Sleeve Configurations (unchanged from v1.1)

| Sleeve | Signal | Vehicle | Defensive | Cash | WMA | SMA | $ |
|---|---|---|---|---|---:|---:|---:|
| QQQ | QQQ | TQQQ | QQQ | BIL | 10 | 175 | $45,000 |
| SPY | SPY | SPXL | SPY | BIL | 5 | 200 | $45,000 |
| GLD | — | — | — | — | — | — | $10,000 |

### Annual Rebalance (unchanged from v1.1)

On the first bar of each new year, rebalance to 45/45/10. The locked v1.2 spec window is **2000-01-03 → 2026-05-22**, giving exactly **26 rebalance events**.

> 🛑 **STOP AND VERIFY — Full System** PRECISE
>
> | Metric | Target |
> |---|---:|
> | Real trades | 88 (39 QQQ→TQQQ + 49 SPY→SPXL) |
> | Rebalance events | 26 |
> | VIX spike-driven exits | 5 |
> | Final equity | $69,376,087 |
> | CAGR | +28.14% |
> | Max DD | −39.32% |
> | Sharpe | 0.9132 |
>
> **QQQ→TQQQ first 5 vehicle trades** (full system): PRECISE
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2003-09-04 | 2003-09-26 | −14.47% | stop_loss(12%) |
> | 2004-06-01 | 2004-07-14 | −11.27% | wma_cross_below |
> | 2004-10-07 | 2005-03-23 | +0.15% | wma_cross_below |
> | 2005-05-25 | 2005-06-28 | −5.20% | wma_cross_below |
> | 2005-07-14 | 2006-05-18 | −1.34% | wma_cross_below |
>
> **SPY→SPXL first 5 vehicle trades** (full system): PRECISE
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2002-03-22 | 2002-03-27 | −1.28% | wma_cross_below |
> | 2003-05-16 | 2004-07-20 | +63.58% | wma_cross_below |
> | 2004-09-07 | 2004-09-24 | −2.58% | wma_cross_below |
> | 2004-10-05 | 2004-10-14 | −8.45% | wma_cross_below |
> | 2004-11-01 | 2005-04-19 | +7.32% | wma_cross_below |
>
> **All 5 VIX spike-exit trades:** PRECISE
>
> | Sleeve | Entry | Exit (spike) | P&L | VIX event |
> |---|---|---|---:|---|
> | QQQ→TQQQ | 2009-08-05 | 2010-05-10 | +52.44% | Flash Crash (2010-05-06/07) |
> | SPY→SPXL | 2009-08-05 | 2010-05-10 | +49.72% | Flash Crash |
> | SPY→SPXL | 2016-03-17 | 2018-02-06 | +110.07% | Volmageddon (2018-02-05) |
> | QQQ→TQQQ | 2019-02-27 | 2020-02-28 | +34.68% | COVID onset (2020-02-27) |
> | SPY→SPXL | 2023-11-06 | 2024-08-06 | +54.12% | Japan carry-trade unwind (2024-08-05) |
>
> All 5 spike exits **locked in profit** before a major vol shock — the mechanism is correct.

---

## Step 5 — Final Position Close-Out & Metrics — unchanged from v1.1

---

## Causal Timing — Complete Reference

| Action | Signal bar | Fill bar | Fill price |
|---|---|---|---|
| Vehicle entry | Phase 6, bar i | Phase 1, bar i+1 | opens[veh][i+1] × ratio[veh][i+1] |
| Vehicle exit — TP / hard stop / vol / WMA / **VIX spike** | Phase 6, bar i | Phase 1, bar i+1 | opens[veh][i+1] × ratio[veh][i+1] |
| Defensive entry | Phase 6, bar i | Phase 1, bar i+1 | opens[def][i+1] × ratio[def][i+1] |
| Defensive exit → cash | Phase 6, bar i | Phase 1, bar i+1 | opens[def][i+1] × ratio[def][i+1], then buy BIL at opens[BIL][i+1] × ratio[BIL][i+1] |
| Cash → vehicle | Phase 6, bar i | Phase 1, bar i+1 | sell BIL at opens[BIL][i+1] × ratio[BIL][i+1], then buy veh |
| Annual rebalance | year change, bar i | Phase 4, bar i | adj[ticker][i] |

VIX is checked at close of bar i (same time as HVol and WMA/SMA). The vehicle exit it triggers fills at bar i+1's open — standard causal.

---

## Appendix A — Common Builder Errors

(All v1.1 errors plus:)

### 8. Triggering VIX spike on the wrong condition

The check is `vix[i] > vix_sma[i] × 2.0`. Common mistakes:
- Using `vix[i] >= 2 × something_else` — wrong (it's relative to the *moving average*, not an absolute level)
- Using `vix_sma[i+1]` — look-ahead; only `[i]` is known at close-of-bar-i
- Triggering on defensive-state — wrong; the spike exit is **vehicle-only**

### 9. Adding cooldown to the VIX spike exit

The hard stop and def_stop set `cooldown=30`. The VIX spike exit does **NOT** — same policy as vol_exit. Adding cooldown blocks profitable re-entries during the post-shock recovery.

### 10. Forgetting MIN_IDX = max(VOL_PERIOD, VIX_MA_PERIOD, all SMAs)

The signal-detection guard now must include `VIX_MA_PERIOD = 20` so that vix_sma[i] is real before the spike check fires.

---

## Appendix B — What Was Excluded From v1.2 (And Why)

| Feature | Result | Status |
|---|---|---|
| **Cash → BIL** | +$14.6M, all metrics better | **ADOPTED in v1.1** |
| **VIX spike exit (B1 Variant B, p=20, mult=2.0)** | **+0.013 Sharpe, walk-forward validated on IS and OOS, 5 real named vol events** | **ADOPTED in v1.2** |
| B1 Variant A (entry gate on VIX < SMA) | Hurt Sharpe on both IS and OOS | Rejected |
| B1 Variant C (entry gate + spike exit) | Slightly worse than spike exit alone | Rejected |
| B1 mult ∈ {1.0, 1.2, 1.5} | Over-triggers, sells the bottom | Rejected |
| Pyramid sizing (v3-style) | Un-tested on this base | Deferred to v2 |
| 3rd sleeve: SMH / DIA / XLK | All dilute portfolio, Sharpe drops | Rejected |
| ATR / VIX-level / VIX-RoC entry sizing | No effect / unfavorable CAGR-for-DD | Rejected |
| Trailing stop on winners | Cost $19–31M | Rejected |
| Defensive-rotation crash predictors | 3 of 4 wrong-signed | Rejected |
| HAR-RV crash predictor | Good vol model, but doesn't lead existing HVol gate | Rejected |
| Cash → TLT / GLD | Lower Sharpe than BIL | Rejected |
| **B4 vol-targeting overlay** (vehicle position scaled by `target_vol/realized_vol`, applied at entry + annual rebalance, vol_target ∈ {15,20,25,30}%, estimator ∈ {HVol20, HVol60, EWMA halflife-20}; 12 combos walk-forward tested) | **No-op or worse on both IS and OOS.** vt≥25% never fires (HVol≤16% entry gate already screens calm regimes, so vol_scale = min(1.0, 25/16) = 1.0 → no scaling). vt=15-20% costs CAGR with no Sharpe gain — the strategy's existing HVol gate + BIL cash state + VIX spike exit already do vol-aware sizing, making the overlay redundant. Best OOS candidate ties baseline; IS-winner is also a tie. Evidence: `test_b4_vol_targeting.py`. | **Rejected** |
| **A1 Hull MA crossover** (replace fast WMA with HMA per Hull's formula `HMA(n) = WMA(2·WMA(n/2) − WMA(n), √n)`, slow leg kept as SMA; per-sleeve sweep of 25 combos each: fast HMA ∈ {5,8,10,13,16}, slow SMA ∈ {100,150,175,200,250}, then joint test of each sleeve's IS-best HMA configuration; walk-forward 2000-2014 IS / 2015-2026 OOS) | **Textbook overfitting — rejected.** Joint IS-best (QQQ HMA16/SMA175 + SPY HMA13/SMA250) gained IS Sharpe +0.042 but lost OOS Sharpe −0.182 and $17.5M of terminal wealth ($69.4M → $51.9M). Every single top-10 candidate in both per-sleeve sweeps lost on OOS — none survived walk-forward. HMA's lower lag amplifies signal noise that the strategy's existing latch + 30-bar cooldown were designed to filter out. (Oxford Strategies' positive HMA result was on 42 raw futures markets without those filters.) | **Rejected** |
| **TSMOM (time-series momentum) signal swap** (replace entry latch + WMA-cross-above with `mom[i] > threshold`, replace vehicle exit `wma_cross_below` with `mom[i] < threshold`; sweep lookback ∈ {126, 189, 252 bars} × excess-over-BIL ∈ {N, Y} × Antonacci skip-last-21-bars ∈ {N, Y} = 12 candidates; HVol gate, cooldown, TP, hard stop, vol exit, VIX spike, defensive rotation, BIL cash all retained; walk-forward 2000-2014 IS / 2015-2026 OOS) | **Most decisive rejection in this exploration.** ALL 12 candidates lose on BOTH IS and OOS — no fitted-then-broken pattern, the signal just doesn't work in this context. IS-best (L=126, excess=Y, skip=N) lost IS Sharpe −0.034 and OOS Sharpe −0.310 ($69.4M → $29.6M, −$39.7M). Worst combos lost OOS −0.45. Trade churn doubled (142–214 vs baseline 86). Mechanism: TSMOM is slow to confirm entries (misses early bull legs), slow to exit (mom12 doesn't flip negative until weeks into a crash — repeated −12% hard stops on the way down), oscillates around the 0 threshold causing whipsaws the latch+cooldown previously filtered, and is direction-only with no vol awareness (the strategy's HVol gate adds info TSMOM lacks). The Moskowitz/Ooi/Pedersen "Sharpe ~1.0" result is on a diversified 58-instrument portfolio where diversification across uncorrelated markets drives the Sharpe — not from single-asset signal quality. | **Rejected** |
| **KAMA (Kaufman Adaptive MA) as fast leg** (replace fast WMA with KAMA per Kaufman's formula `KAMA[i] = KAMA[i-1] + SC[i]·(c[i] − KAMA[i-1])` where `SC[i] = (ER[i]·(2/3 − 2/31) + 2/31)²` and `ER[i]` is the efficiency ratio over the lookback; slow SMA leg unchanged; per-sleeve sweep of ER ∈ {10, 14, 20} = 3 combos each, then joint test of IS-best; walk-forward 2000-2014 IS / 2015-2026 OOS) | **Rejected — every candidate loses on both halves.** Joint IS-best (QQQ ER=20 + SPY ER=20) lost IS Sharpe −0.017, OOS Sharpe −0.049, $17.7M of terminal wealth ($69.4M → $51.6M). All 6 candidates across both per-sleeve sweeps lost on IS and OOS — no overfitting pattern, KAMA just doesn't add value. Mechanism: KAMA's chop-flattening is redundant with the existing latch+cooldown (whipsaws already filtered), while its squared-SC formula caps trend responsiveness even at high efficiency ratio (`max SC = (2/3)² = 0.444`), making KAMA inherently slower than WMA(10) in confirmed trends → delayed entries and exits. The StratBase BTC result was on raw moving-average crossovers without latch/cooldown machinery. | **Rejected** |
| **Donchian breakout signal swap** (replace entry latch + WMA-cross-above with `close[i] ≥ donchian_high[i-1]` AND `close[i] > SMA[i]` trend filter; replace vehicle exit `wma_cross_below` with `close[i] ≤ donchian_low[i-1]`; both lookups use bar i-1 for strict causality; sweep entry lookback ∈ {20, 40, 55, 100} × exit lookback ∈ {10, 20} = 8 candidates; HVol gate, cooldown, TP, hard stop, vol exit, VIX spike, defensive rotation, BIL cash all retained; walk-forward 2000-2014 IS / 2015-2026 OOS) | **Worst rejection in this exploration — catastrophic on both halves.** IS-best (entry=40, exit=20) lost IS Sharpe −0.149, OOS Sharpe −0.322, $61.3M of terminal wealth ($69.4M → $8.0M). ALL 8 candidates collapsed to $3.9M–$8.0M final equity. Trade churn 218–434 vs baseline 86 (2.5×–5×). Mechanism: (1) breakout entries fire on confirmed new highs, weeks AFTER the WMA cross — Donchian misses the early leg of every move, disproportionately costly in 3× vehicles; (2) without the latch+cooldown, daily noise around the breakout level produces rapid entry/exit/re-entry cycles; (3) exit=10 triggers on routine pullbacks (~350-435 trades), exit=20 holds through deep TQQQ drawdowns — neither asymmetry works; (4) leveraged compounding hates churn. Faith's original Turtle worked on a diversified 24-instrument unleveraged futures portfolio with ATR-scaled wide stops — none of those conditions hold here. | **Rejected** |
| **B2 VIX term-structure regime gate** (VIX/VIX3M ratio as proxy for VX1/VX2 — same contango/backwardation interpretation; CBOE VIX3M index from EODHD covers 2007-11-13 onwards, pre-that-date filter is neutral; ts_ratio = VIX/VIX3M smoothed with 5-bar SMA; 3 variant families: A entry gate `ts<entry_thresh` ∈ {0.95, 1.00, 1.05}, B forced vehicle exit `ts>exit_thresh` ∈ {1.00, 1.05, 1.10}, C both combined; 9 candidates; HVol gate, cooldown, TP, hard stop, vol exit, VIX spike, defensive rotation, BIL cash all retained; walk-forward 2000-2014 IS / 2015-2026 OOS) | **Rejected — redundant with existing v1.2 machinery.** Variant A (entry gate) is a literal no-op across all 3 thresholds: ts_blocks=0, IS/OOS/Full Sharpe identical to baseline. The HVol≤16% entry gate already restricts entries to calm regimes where VIX/VIX3M is virtually always <0.95 deep contango — the term-structure gate has nothing to do. Variant B (exit at 1.10) also no-op. Variant B (exit at 1.05) fires 2 spike exits during OOS — same Volmageddon/COVID events the v1.2 VIX-spike already catches, so adding the term-structure exit is double-counting (lost $23M and OOS Sharpe −0.10). Variant B (exit at 1.00) over-triggers with 14 exits and destroys $54M ($69.4M → $15.5M). Variant C results identical to corresponding B variants since A contributes nothing. Term structure is a different *measure* of the same vol regime v1.2 already detects via HVol and VIX-spike — same overlap pattern as B4 vol-targeting and KAMA. | **Rejected** |

---

## Appendix C — Reference Implementation

Working Python reference: `backtest_two_sleeves_v1_2.py`. Pure stdlib, no external deps.

Operational tools (also pure stdlib + `requests` for the data refresh):
- `two_sleeve_daily_signal.py` — daily signal generator (uses all available data)
- `two_sleeve_update_data.py` — incremental EODHD refresh for all 7 files
- `two_sleeve_run_daily.sh` — chains refresh → signal, logs to `logs/`

Walk-forward validation evidence: `test_vix_ma_walkforward.py` (committed alongside).

---

*Two-Sleeves Optimized · Build Guide v1.2 · Backtest does not guarantee future results*
