# Two-Sleeves Optimized — Build Guide v1

*Per-sleeve optimum WMA/SMA · No pyramid · Strictly causal pricing · Verify every PRECISE checkpoint before continuing*

**Backtest:** 2000-01-03 → 2026-03-23 · $100,000 starting capital · 6,594 bars

---

## What You Are Building

A two-sleeve tactical rotation strategy where each equity sleeve uses **its own individually-optimized WMA/SMA cross**. Each sleeve independently rotates between a 3× leveraged vehicle (the "go" position), the underlying ETF as a defensive holding (the "wait" position), and cash (the "stand down" position). A GLD safety allocation runs continuously in the background.

This is a refinement of Two-Sleeves w/Gold v3. The differences:

1. **WMA/SMA is now per-sleeve.** QQQ→TQQQ uses WMA=10/SMA=175. SPY→SPXL uses WMA=5/SMA=200. Discovered via a 56-point grid sweep optimizing CAGR/|MaxDD|.
2. **No pyramid sizing.** The pyramid layer in v3 (pyr1 + pyr2 + VIX-scaled, broker-capped at 1.33×) is not included. Pyramid testing on top of the optimized base is a future direction, not part of v1.
3. **Allocations remain 45/45/10** (same as v3 baseline).

## Target Numbers — Final System

| Metric | Target |
|---|---:|
| Final equity | **$35,448,247** |
| CAGR | **+25.10%** |
| Max drawdown | **−37.99%** |
| Sharpe ratio | **0.8373** |
| Real trades | **86** (38 QQQ + 48 SPY) |
| Rebalance events | 26 |
| Bars | 6,594 |
| Period | 2000-01-03 → 2026-03-23 |

> **Precision rules** — used in every verification table:
> - Final equity: match to the dollar
> - CAGR / MaxDD: match to 2 decimal places
> - Sharpe: match to 4 decimal places
> - Trade counts: match exactly
> - INFORMATIONAL rows: orientation only — do not stop the build if off

---

## Parameters — Complete Reference

All magic numbers in one place. If a number appears anywhere else in this guide, this table is the authority.

| Parameter | Value | Description |
|---|---|---|
| TOTAL_CAPITAL | $100,000 | Starting portfolio value |
| EQ_ALLOC (per sleeve) | $45,000 (45%) | Initial per-equity-sleeve allocation |
| GLD_ALLOC | $10,000 (10%) | GLD safety allocation |
| EQ_FRAC | 0.45 | Equity sleeve rebalance target fraction |
| GLD_FRAC | 0.10 | GLD rebalance target fraction |
| **WMA_PERIOD (QQQ sleeve)** | **10 bars** | WMA window for QQQ signal |
| **SMA_PERIOD (QQQ sleeve)** | **175 bars** | SMA window for QQQ signal |
| **WMA_PERIOD (SPY sleeve)** | **5 bars** | WMA window for SPY signal |
| **SMA_PERIOD (SPY sleeve)** | **200 bars** | SMA window for SPY signal |
| VOL_PERIOD | 20 bars | HVol window (both signal tickers) |
| HVol variance | Sample (÷N−1) | Use N−1 denominator, NOT N |
| HVol annualization | × √252 × 100 | Produces a percentage (e.g. 16.0 = 16%) |
| VOL_ENTRY_MAX | 16.0% | Max signal HVol to allow new vehicle entry |
| VOL_EXIT_THRESH | 30.0% | Signal HVol that forces vehicle exit |
| TAKE_PROFIT | +200% (×3.0) | Exit when vehicle adj ≥ v_entry × 3.0 |
| STOP_LOSS | −12% (×0.88) | Exit when vehicle adj ≤ v_entry × 0.88 |
| DEF_STOP | −18% (×0.82) | Exit when defensive adj ≤ d_entry × 0.82 |
| COOLDOWN | 30 bars | Cooldown triggered by: hard stop AND defensive stop ONLY |
| MIN_IDX | max(SMA periods) = 200 | First bar where signals can fire |
| REBAL_TRIGGER | year(i) > year(i−1) | First trading bar of each new calendar year |

> The MIN_IDX warmup is determined by the longest SMA across both sleeves (200 for SPY here).
> Individual sleeves can fire earlier if their own SMA is warmed up.

---

## Per-Bar Phase Order — Canonical

Every bar executes these phases in this exact sequence.

| Phase | Name | Key constraint |
|---|---|---|
| 1 | State transitions at open[i] | Uses next_state set at Phase 5 of bar i−1. Fill = opens[i] × ratio[i]. |
| 2 | Cooldown decrement | Decrement all sleeves before any mark-to-market. |
| 3 | Mark to market at close[i] | adj[i] for all positions INCLUDING GLD. Must happen before Phase 4. |
| 4 | Annual rebalance | Reads Phase 3 equity (including GLD). Only fires if year(i) > year(i−1). |
| 5 | Record portfolio equity | Append post-rebalance total equity to curve. |
| 6 | Entry/exit signal detection | Only fires if i ≥ MIN_IDX. Sets next_state for bar i+1. |

> **⚠ GLD must be marked to market in Phase 3 BEFORE the rebalance reads equity in Phase 4.** If GLD is marked after Phase 4, the rebalance uses stale GLD equity and undersizes GLD's share-count reset — producing a final equity error of roughly 0.5–0.7%.

---

## Reporting Format

At every STOP checkpoint, fill in the 'Your Value' column and mark ✓ or ✗. PRECISE rows must match. INFORMATIONAL rows are orientation only.

| Metric | Target | Your Value | Type |
|---|---|---|---|
| Bars (n) | 6,594 | | **PRECISE** |
| First date | 2000-01-03 | | **PRECISE** |
| Last date | 2026-03-23 | | **PRECISE** |
| Real trades | 86 | | **PRECISE** |
| Final equity | $35,448,247 | | **PRECISE** |
| CAGR | +25.10% | | **PRECISE** |
| Max DD | −37.99% | | **PRECISE** |
| Sharpe | 0.8373 | | **PRECISE** |

---

## Build Plan

| Step | Build | Checkpoint type |
|---|---|---|
| 1 | Load 5 JSON files, date intersection, per-ticker arrays | PRECISE: n=6594, adj spot checks |
| 2 | Per-sleeve WMA/SMA, HVol20 (QQQ + SPY) | PRECISE: HVol spot checks |
| 3a | Single sleeve loop — no signals | PRECISE: equity flat, 26 year events |
| 3b | Entry-eligibility latch — track only | PRECISE: cab events on QQQ (WMA=10/SMA=175) |
| 3c | Entries only — no exits | PRECISE: first entry 2003-09-04 at $0.2724 |
| 3d | Four vehicle exits | PRECISE: first 3 QQQ trades |
| 3e | Defensive stop | PRECISE: isolation totals |
| 3f | Sleeve isolation verification | PRECISE: per-sleeve trade counts and finals |
| 4 | Add SPY sleeve + GLD + annual rebalance | PRECISE: 86 trades, $35,448,247 |

---

## Step 1 — Load the Data

### Input Files

| File | Role | Splice notes |
|---|---|---|
| QQQ_US.json | Sleeve 1 signal + defensive | No splice needed — real history back to 2000 |
| TQQQ_US.json | Sleeve 1 vehicle (3× QQQ) | Synthetic pre-2010-02-11 bars have synthetic=true |
| SPY_US.json | Sleeve 2 signal + defensive | No splice needed — real history back to 2000 |
| SPXL_US.json | Sleeve 2 vehicle (3× SPY) | Synthetic pre-2008-11-05 bars have synthetic=true |
| GLD_US.json | GLD safety sleeve | Synthetic pre-2004-11-18 bars extending history back to 2000 |

> **DATA SPLICING:** TQQQ_US.json, SPXL_US.json, and GLD_US.json contain synthetic pre-inception history. Use these files as-is. Do NOT attempt to recompute or validate the splice.

### JSON Schema

```json
[ { "date": "YYYY-MM-DD", "open": ..., "high": ..., "low": ...,
    "close": ..., "adjusted_close": ..., "volume": ... }, ... ]
```

### Common Date Intersection

For each ticker: drop bars with date < '2000-01-01', sort ascending, index by date string. Compute the intersection of all five date sets. This is your master common_dates array — n bars used everywhere.

CRITICAL: do not pad or interpolate missing dates. Intersection only — every bar must have a real price for every ticker.

### Per-Ticker Arrays

For each ticker build four parallel arrays indexed to common_dates:

```
closes[i] = bar['close']
adj[i]    = bar['adjusted_close']
opens[i]  = bar['open']
ratio[i]  = adj[i] / closes[i]    (1.0 if close == 0)
```

Fill price at bar i open: `fill = opens[i] × ratio[i]`

This converts the raw open to a split/dividend-adjusted value consistent with the adj series.

> 🛑 **STOP AND VERIFY — do not continue until every PRECISE row matches exactly**
>
> | Check | Target | Type |
> |---|---|---|
> | n (common bars) | 6,594 | PRECISE |
> | common_dates[0] | '2000-01-03' | PRECISE |
> | common_dates[-1] | '2026-03-23' | PRECISE |
> | adj['GLD'][0] | 2.7908 | PRECISE |
> | adj['TQQQ'][0] | 72.5115 | PRECISE |
> | adj['SPXL'][0] | 19.9793 | PRECISE |
> | adj['QQQ'][0] | 80.1346 | PRECISE |
> | adj['SPY'][0] | 91.6138 | PRECISE |
> | GLD initial shares | 10000 / 2.7908 = 3583.1705 | PRECISE |

---

## Step 2 — Compute Indicators

All indicators use raw closes (not adjusted close).

### WMA — Weighted Moving Average (per-sleeve period)

```
denom    = period × (period + 1) / 2
WMA[i]   = sum(closes[i−period+1+j] × (j+1) for j in 0..period-1) / denom    for i ≥ period − 1
WMA[i]   = None                                                              for i <  period − 1
```

QQQ uses period=10 (denom=55). SPY uses period=5 (denom=15).

### SMA — Simple Moving Average (per-sleeve period)

```
SMA[period-1] = mean(closes[0:period])
SMA[i]        = SMA[i−1] + (closes[i] − closes[i−period]) / period          for i ≥ period
SMA[i]        = None                                                         for i <  period − 1
```

QQQ uses period=175. SPY uses period=200. Use a rolling-sum approach.

### HVol20 — Annualised Realised Volatility (QQQ and SPY)

```
lr     = [log(closes[j] / closes[j−1]) for j in i−19..i]    # 20 log returns
mu     = mean(lr)
var    = sum((r − mu)² for r in lr) / 19                     # sample variance, divide by N−1
HVol[i] = sqrt(var × 252) × 100.0                            for i ≥ 20
HVol[i] = None                                                for i <  20
```

**CRITICAL: denominator is 19 (N−1 = sample variance). Using N=20 (population variance) shifts every HVol value slightly and will cause verification mismatches.**

> 🛑 **STOP AND VERIFY**
>
> | Check | Target | Type |
> |---|---|---|
> | WMA['QQQ'][9] is real, WMA['QQQ'][8] is None | (period 10) | PRECISE |
> | WMA['SPY'][4] is real, WMA['SPY'][3] is None | (period 5) | PRECISE |
> | SMA['QQQ'][174] is real, SMA['QQQ'][173] is None | (period 175) | PRECISE |
> | SMA['SPY'][199] is real, SMA['SPY'][198] is None | (period 200) | PRECISE |
> | HVol['QQQ'][20] is real, HVol['QQQ'][19] is None | (period 20) | PRECISE |
> | HVol['QQQ'] on 2008-10-10 | 51.7% (GFC peak vol) | PRECISE |
> | HVol['QQQ'] on 2017-08-15 | 10.9% (quiet bull market) | PRECISE |

---

## Step 3 — Build a Single Equity Sleeve

Build QQQ→TQQQ (sleeve 1, WMA=10/SMA=175) in isolation first.

### Sleeve State Object — Initial Values

| Field | Initial | Reset on | Notes |
|---|---|---|---|
| state | 'cash' | — | cash / vehicle / defensive |
| next_state | None | Phase 1 execution | Set in Phase 6, cleared in Phase 1 |
| v_entry | 0.0 | Vehicle entry | Adj open fill price of vehicle |
| v_entry_idx | −1 | Vehicle entry | Bar index of vehicle entry fill |
| v_stop | 0.0 | Vehicle entry | v_entry × 0.88 — checked vs adj close |
| v_shares | 0.0 | Vehicle exit | Shares of vehicle currently held |
| d_shares | 0.0 | Defensive exit | Shares of defensive (QQQ or SPY) |
| d_entry | 0.0 | Defensive entry | Adj open fill price of defensive |
| cash | 45000.0 | Vehicle entry (→ 0) | Sleeve cash balance |
| wma_was_below | True | See latch logic | Arms the latch after WMA dips below SMA |
| entry_eligible | False | See latch logic | True after a valid cross-above fires |
| equity | 45000.0 | Phase 3 each bar | Mark-to-market sleeve value |
| cooldown | 0 | Phase 2 (decrements) | Blocks entry when > 0 |

### 3a — Loop Only, No Signals

Build Phases 1–5 (record). No signal logic — next_state always None, sleeve stays in cash.

> 🛑 **STOP AND VERIFY**
>
> - Loop completes 6,594 bars without exception · PRECISE
> - Sleeve equity = $45,000.00 every bar · PRECISE
> - Year-change events fire on exactly 26 dates · PRECISE

### 3b — Add Entry-Eligibility Latch (Track Only)

Latch logic — runs in Phase 6 when state is cash or defensive, no pending transition:

```
cab = (WMA[i−1] ≤ SMA[i−1]) and (WMA[i] >  SMA[i])    # cross above
cbl = (WMA[i−1] ≥ SMA[i−1]) and (WMA[i] <  SMA[i])    # cross below

if WMA[i] < SMA[i]:
    wma_was_below = True
    entry_eligible = False

if cab and wma_was_below:
    entry_eligible = True
    wma_was_below = False

if entry_eligible and WMA[i] < SMA[i]:
    entry_eligible = False
    wma_was_below = True    # reversed before entry — reset
```

### 3c — Add Entries Only (No Exits)

Entry fires in Phase 6 when latch is armed:

```
if (entry_eligible
    and HVol['QQQ'][i] ≤ 16.0
    and WMA['QQQ'][i] > SMA['QQQ'][i]
    and cooldown == 0
    and i + 1 < n):
        next_state = 'vehicle'
        entry_eligible = False
        wma_was_below = False
```

Phase 1 executes on bar i+1:

```
vo = opens['TQQQ'][i+1] × ratio['TQQQ'][i+1]
v_shares = cash / vo
v_entry = vo
v_stop = vo × 0.88
v_entry_idx = i+1
cash = 0
state = 'vehicle'
```

> 🛑 **STOP AND VERIFY**
>
> - First QQQ→TQQQ entry: **signal bar 2003-09-03 → fill 2003-09-04** · PRECISE
> - fill price (opens['TQQQ']['2003-09-04'] × ratio): **$0.2724** · PRECISE

### 3d — Add Four Vehicle Exits

Evaluate in this priority order while state == 'vehicle' and next_state is None:

| Priority | Exit | Trigger | Side effect |
|---|---|---|---|
| 1 | Take profit | adj['TQQQ'][i] ≥ v_entry × 3.0 | none |
| 2 | Hard stop | adj['TQQQ'][i] ≤ v_stop (v_entry × 0.88) | cooldown = 30 |
| 3 | Vol exit | HVol['QQQ'][i] ≥ 30.0 | none |
| 4 | WMA cross below | cbl is True on QQQ signal | none |

On any exit: set v_exit_rsn, set wma_was_below = False, set next_state = 'defensive'.

Phase 1 fill for vehicle → defensive:

```
vo = opens['TQQQ'][i+1] × ratio['TQQQ'][i+1]
proceeds = v_shares × vo
log trade: exit_price=vo, pnl_pct=(vo − v_entry)/v_entry × 100
v_shares = 0; v_entry = 0; cash = 0

do = opens['QQQ'][i+1] × ratio['QQQ'][i+1]
d_shares = proceeds / do; d_entry = do; state = 'defensive'
```

> 🛑 **STOP AND VERIFY**
>
> QQQ→TQQQ first 3 vehicle trades (full system, includes rebalance effect):
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2003-09-04 | 2003-09-26 | −14.47% | stop_loss(12%) |
> | 2004-06-01 | 2004-07-14 | −11.27% | wma_cross_below |
> | 2004-10-07 | 2005-03-23 | +0.15% | wma_cross_below |
>
> All PRECISE.

### 3e — Add Defensive Stop

While state == 'defensive' with no pending transition:

```
if adj['QQQ'][i] ≤ d_entry × 0.82:
    d_exit_rsn = 'def_stop(18%)'
    cooldown = 30
    next_state = 'cash'
```

Phase 1 fill for defensive → cash:

```
do = opens['QQQ'][i+1] × ratio['QQQ'][i+1]
proceeds = d_shares × do
cash = proceeds; d_shares = 0; d_entry = 0; state = 'cash'
```

### 3f — Sleeve Isolation Verification

Run each sleeve in isolation: $100K starting capital, no GLD, no rebalance, no other sleeve. Verify against the per-sleeve sweep results.

> 🛑 **STOP AND VERIFY** — values at $100K isolation
>
> **QQQ→TQQQ (WMA=10 / SMA=175):** PRECISE
> - Final: $31,090,431 · CAGR: +24.47% · MaxDD: −45.18% · Sharpe: 0.827 · 37 trade rows
>
> **SPY→SPXL (WMA=5 / SMA=200):** PRECISE
> - Final: $11,067,358 · CAGR: +19.66% · MaxDD: −40.03% · Sharpe: 0.747 · 47 trade rows
>
> First SPY→SPXL vehicle trades (isolation): PRECISE
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2002-03-22 | 2002-03-27 | −1.28% | wma_cross_below |
> | 2003-05-16 | 2004-07-20 | +63.58% | wma_cross_below |
> | 2004-09-07 | 2004-09-24 | −2.58% | wma_cross_below |

---

## Step 4 — Add SPY Sleeve, GLD, and Annual Rebalance

### Sleeve Configurations

| Sleeve | Signal | Vehicle | Defensive | WMA | SMA | Initial $ |
|---|---|---|---|---:|---:|---:|
| QQQ | QQQ | TQQQ | QQQ | 10 | 175 | $45,000 |
| SPY | SPY | SPXL | SPY | 5 | 200 | $45,000 |
| GLD | — | — | — | — | — | $10,000 (buy at adj[0] and hold) |

### Annual Rebalance

On the first bar of each new year (year(i) > year(i−1)), after Phase 3 mark-to-market:

```
total_eq   = sleeve1.equity + sleeve2.equity + gld_equity       # Phase 3 values
eq_target  = total_eq × 0.45
gld_target = total_eq × 0.10
```

For each equity sleeve:

```
if state == 'vehicle':
    v_shares = eq_target / adj[vehicle][i]
    v_stop   = adj[vehicle][i] × 0.88    # reset to current price
    cash     = 0.0

if state == 'defensive':
    d_shares = eq_target / adj[defensive][i]

if state == 'cash':
    cash = eq_target

equity = eq_target

gld_shares = gld_target / adj['GLD'][i]
```

> 🛑 **STOP AND VERIFY — Full System** PRECISE
>
> | Metric | Target |
> |---|---:|
> | Real trades | 86 (38 QQQ→TQQQ + 48 SPY→SPXL) |
> | Rebalance events | 26 |
> | Final equity | $35,448,247 |
> | CAGR | +25.10% |
> | Max DD | −37.99% |
> | Sharpe | 0.8373 |
>
> **QQQ→TQQQ first 5 vehicle trades (full system):** PRECISE
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2003-09-04 | 2003-09-26 | −14.47% | stop_loss(12%) |
> | 2004-06-01 | 2004-07-14 | −11.27% | wma_cross_below |
> | 2004-10-07 | 2005-03-23 | +0.15% | wma_cross_below |
>
> **SPY→SPXL first 5 vehicle trades (full system):** PRECISE
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2002-03-22 | 2002-03-27 | −1.28% | wma_cross_below |
> | 2003-05-16 | 2004-07-20 | +63.58% | wma_cross_below |
> | 2004-09-07 | 2004-09-24 | −2.58% | wma_cross_below |
>
> **Per-sleeve exit reason counts:** INFORMATIONAL
>
> - QQQ→TQQQ: def_to_vehicle=16, wma_cross_below=10, take_profit=3, vol_exit=4, def_stop=2, stop_loss=2, end_of_data=1 (38 total)
> - SPY→SPXL: def_to_vehicle=20, wma_cross_below=19, def_stop=3, stop_loss=2, take_profit=2, vol_exit=1, end_of_data=1 (48 total)

---

## Step 5 — Final Position Close-Out & Metrics

### Close-Out

After the last bar, mark open positions to the last adjusted close for the trade log:

```
for each sleeve:
    if state == 'vehicle' and v_entry > 0:
        last = adj[vehicle][-1]
        log trade: exit_reason='end_of_data', exit_price=last
    elif state == 'defensive' and d_shares > 0:
        last = adj[defensive][-1]
        log trade: exit_reason='end_of_data', exit_price=last
```

This close-out is for reporting only. It does not affect the daily equity curve.

### Metrics

| Metric | Exact formula |
|---|---|
| years | (last_date − first_date).days / 365.25 = 9576 / 365.25 = 26.2108 |
| CAGR | (final_equity / 100,000)^(1 / years) − 1, as % |
| Max DD | min of (equity[i] − running_peak) / running_peak across all i; running_peak starts at 100,000 |
| Sharpe | mean(daily_ret) / std(daily_ret, ddof=1) × √252; daily_ret[i] = (eq[i]−eq[i-1])/eq[i-1]; risk-free=0 |
| Total return | (final_equity − 100,000) / 100,000 × 100 |

---

## Causal Timing — Complete Reference

Every price reference in the system must follow these rules. Signal bar = bar where condition is detected at EOD. Fill bar = next bar where trade executes at open.

| Action | Signal bar | Fill bar | Fill price |
|---|---|---|---|
| Vehicle entry | Phase 6, bar i | Phase 1, bar i+1 | opens[veh][i+1] × ratio[veh][i+1] |
| Vehicle exit — all types | Phase 6, bar i | Phase 1, bar i+1 | opens[veh][i+1] × ratio[veh][i+1] |
| Defensive entry | Phase 6, bar i | Phase 1, bar i+1 | opens[def][i+1] × ratio[def][i+1] |
| Swap: defensive → vehicle | Phase 6, bar i | Phase 1, bar i+1 | Both legs at bar i+1 open |
| Defensive exit | Phase 6, bar i | Phase 1, bar i+1 | opens[def][i+1] × ratio[def][i+1] |
| Annual rebalance | year change, bar i | Phase 4, bar i | adj[ticker][i] (close of first Jan bar) |

The annual rebalance is the only action using close rather than next-bar open.

---

## Appendix A — Common Builder Errors

### 1. Marking GLD to market after the rebalance reads equity

The rebalance uses Phase 3 equity values from all positions including GLD. If GLD is marked to market in Phase 4 or later, the rebalance sees stale GLD equity and undersizes the GLD share reset. Final equity error of roughly 0.5–0.7%. Fix: mark GLD to market in Phase 3 alongside the equity sleeves.

### 2. Same WMA/SMA for both sleeves

This is the v3 mistake. v1 of *this* guide uses per-sleeve optimal values:

- **QQQ→TQQQ: WMA=10 / SMA=175**
- **SPY→SPXL: WMA=5 / SMA=200**

Using 20/200 for both sleeves yields $33.86M (v3 baseline) instead of $35.45M. The improvement is small but real.

### 3. Same-bar fills

Using adj[i] (the close that generated the signal) as the fill price. All fills must use `opens[i+1] × ratio[i+1]`.

### 4. HVol with population variance (÷N instead of ÷N−1)

Using N=20 as the variance denominator instead of N−1=19 gives slightly different HVol values that won't match the spot checks. Use sample variance (N−1) throughout.

### 5. Cooldown on non-stop exits

Only the hard stop (−12%) and defensive stop (−18%) set cooldown=30. Take-profit, vol exit, and WMA cross do NOT. Setting cooldown on all exits prevents re-entry after clean exits and reduces trade count below 86.

### 6. Rotating to cash directly on vehicle exit

All four vehicle exits (TP, stop, vol, WMA) rotate to the DEFENSIVE holding — not cash. Only the defensive stop rotates to cash. Going vehicle→cash directly misses the defensive period, changes trade count, and loses the partial recovery contribution from the defensive holding.

### 7. Different period bar warmups not honored

MIN_IDX must be max(WMA periods, SMA periods, VOL_PERIOD) across both sleeves. For this strategy: max(10, 5, 175, 200, 20) = 200. Each sleeve's signal can still fire as soon as its own indicators are warmed up (QQQ at bar 175, SPY at bar 200), but the global MIN_IDX gate stays at 200.

---

## Appendix B — What Was Excluded From v1 (And Why)

These were investigated and rejected during the v1 design:

| Feature | Result | Status |
|---|---|---|
| **Pyramid sizing (v3-style)** | Boost to $66.7M in v3 baseline; un-tested on this optimized base | Deferred to v2 |
| **3rd sleeve: SMH/SOXL** | Cut portfolio to $16.2M, Sharpe 0.76 | Rejected |
| **3rd sleeve: DIA/UDOW** | Cut portfolio to $17.5M, Sharpe 0.76 | Rejected |
| **3rd sleeve: XLK/TECL** | Cut portfolio to $29.0M, Sharpe 0.81 | Rejected — best of the rejects but still drag |
| **ATR-based entry sizing** | No effect — HVol gate already screens vol | Rejected |
| **VIX-based entry sizing** | 1:1 trade of CAGR for DD, Sharpe drops | Rejected |
| **Trailing stop on winners** | Cost $19–31M for modest DD improvement | Rejected |
| **Hard stop tightening (−10%)** | $384K cost for 0.58 pts DD, +0.005 Sharpe | Available as a free-win toggle |
| **Bear-regime filter (SPY vs SMA200)** | Filter never fires — strategy already regime-aware | Rejected (redundant) |
| **DD circuit breaker** | Catastrophic ($329K final) | Rejected |
| **Cooldown on all exit types** | $3.5M cost, no DD improvement | Rejected |

---

## Appendix C — Reference Implementation

A working Python reference is in [FourSleeve/backtest_two_sleeve_optimized.py](../FourSleeve/backtest_two_sleeve_optimized.py). The data files used:

- `json/QQQ_US.json` — copied from Oscillator/json/history
- `json/SPY_US.json` — copied from Oscillator/json/history
- `json/TQQQ_US.json` — copied from Oscillator/json/spliced (synthetic pre-2010)
- `json/SPXL_US.json` — copied from Oscillator/json/spliced (synthetic pre-2008)
- `json/GLD_US.json` — copied from Oscillator/json/spliced (synthetic pre-2004)

VIX is not required for v1 (no pyramid). It will be required for v2.

---

*Two-Sleeves Optimized · Build Guide v1 · Backtest does not guarantee future results*
