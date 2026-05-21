# Two-Sleeves Optimized — Build Guide v1.1

*Per-sleeve optimum WMA/SMA · Cash state earns the risk-free rate (BIL) · No pyramid · Strictly causal pricing · Verify every PRECISE checkpoint before continuing*

**Backtest:** 2000-01-03 → 2026-03-23 · $100,000 starting capital · 6,594 bars

---

## Changelog

| Version | Change |
|---|---|
| v1 | Per-sleeve optimum WMA/SMA (QQQ 10/175, SPY 5/200). Cash state held 0%-yield dollars. → $35,448,247 |
| **v1.1** | **Cash state now holds BIL (1–3 month T-bills) instead of 0%-yield dollars.** A sleeve only reaches the cash state after a defensive stop (a confirmed bear); parking that capital in T-bills earns the risk-free rate through long crisis stretches. This is also the more realistic model — brokers sweep idle cash into money-market funds automatically. → **$50,081,555** |

The BIL change improves **every** metric vs v1: +$14.6M final equity, +1.66 CAGR points, −0.53 MaxDD points (drawdown slightly better), +0.0379 Sharpe.

---

## What You Are Building

A two-sleeve tactical rotation strategy where each equity sleeve uses **its own individually-optimized WMA/SMA cross**. Each sleeve independently rotates between a 3× leveraged vehicle (the "go" position), the underlying ETF as a defensive holding (the "wait" position), and a T-bill cash position (the "stand down" position). A GLD safety allocation runs continuously in the background.

Differences from Two-Sleeves w/Gold v3:

1. **WMA/SMA is per-sleeve.** QQQ→TQQQ uses WMA=10/SMA=175. SPY→SPXL uses WMA=5/SMA=200. Discovered via a 56-point grid sweep optimizing CAGR/|MaxDD|.
2. **Cash state holds BIL.** When a sleeve is "in cash" it holds 1–3 month T-bills, earning the risk-free rate rather than 0%.
3. **No pyramid sizing.** The pyramid layer in v3 is not included. Deferred to v2.
4. **Allocations remain 45/45/10.**

## Target Numbers — Final System

| Metric | Target |
|---|---:|
| Final equity | **$50,081,555** |
| CAGR | **+26.76%** |
| Max drawdown | **−37.46%** |
| Sharpe ratio | **0.8752** |
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
| **CASH_TICKER** | **BIL** | **Ticker held while a sleeve is in the cash state** |
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

---

## Per-Bar Phase Order — Canonical

Every bar executes these phases in this exact sequence.

| Phase | Name | Key constraint |
|---|---|---|
| 1 | State transitions at open[i] | Uses next_state set at Phase 6 of bar i−1. Fill = opens[i] × ratio[i]. Includes buying/selling BIL on entry to / exit from the cash state. |
| 2 | Cooldown decrement | Decrement all sleeves before any mark-to-market. |
| 3 | Mark to market at close[i] | adj[i] for all positions INCLUDING GLD and BIL. Must happen before Phase 4. |
| 4 | Annual rebalance | Reads Phase 3 equity (including GLD). Only fires if year(i) > year(i−1). |
| 5 | Record portfolio equity | Append post-rebalance total equity to curve. |
| 6 | Entry/exit signal detection | Only fires if i ≥ MIN_IDX. Sets next_state for bar i+1. |

> **⚠ GLD must be marked to market in Phase 3 BEFORE the rebalance reads equity in Phase 4.** Same applies to BIL holdings in cash-state sleeves.

---

## Reporting Format

At every STOP checkpoint, fill in the 'Your Value' column and mark ✓ or ✗.

| Metric | Target | Your Value | Type |
|---|---|---|---|
| Bars (n) | 6,594 | | **PRECISE** |
| First date | 2000-01-03 | | **PRECISE** |
| Last date | 2026-03-23 | | **PRECISE** |
| Real trades | 86 | | **PRECISE** |
| Final equity | $50,081,555 | | **PRECISE** |
| CAGR | +26.76% | | **PRECISE** |
| Max DD | −37.46% | | **PRECISE** |
| Sharpe | 0.8752 | | **PRECISE** |

---

## Build Plan

| Step | Build | Checkpoint type |
|---|---|---|
| 1 | Load 6 JSON files, date intersection, per-ticker arrays | PRECISE: n=6594, adj spot checks |
| 2 | Per-sleeve WMA/SMA, HVol20 (QQQ + SPY) | PRECISE: HVol spot checks |
| 3a | Single sleeve loop — no signals | PRECISE: equity flat, 26 year events |
| 3b | Entry-eligibility latch — track only | PRECISE: cab events on QQQ (WMA=10/SMA=175) |
| 3c | Entries only — no exits | PRECISE: first entry 2003-09-04 at $0.2724 |
| 3d | Four vehicle exits | PRECISE: first 3 QQQ trades |
| 3e | Defensive stop → cash (BIL) | PRECISE: cash state holds BIL |
| 3f | Sleeve isolation verification | PRECISE: per-sleeve trade counts |
| 4 | Add SPY sleeve + GLD + annual rebalance | PRECISE: 86 trades, $50,081,555 |

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
| **BIL_US.json** | **Cash-state holding (T-bills)** | **Synthetic pre-2007-05-30 bars; models the risk-free rate** |

> **DATA SPLICING:** TQQQ, SPXL, GLD, and BIL JSON files contain synthetic pre-inception history. Use these files as-is. Do NOT recompute or validate the splice.

### JSON Schema

```json
[ { "date": "YYYY-MM-DD", "open": ..., "high": ..., "low": ...,
    "close": ..., "adjusted_close": ..., "volume": ... }, ... ]
```

### Common Date Intersection

For each ticker: drop bars with date < '2000-01-01', sort ascending, index by date string. Compute the intersection of **all six** date sets. This is your master common_dates array — n bars used everywhere.

CRITICAL: do not pad or interpolate missing dates. Intersection only.

### Per-Ticker Arrays

For each ticker build four parallel arrays indexed to common_dates:

```
closes[i] = bar['close']
adj[i]    = bar['adjusted_close']
opens[i]  = bar['open']
ratio[i]  = adj[i] / closes[i]    (1.0 if close == 0)
```

Fill price at bar i open: `fill = opens[i] × ratio[i]`

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
> | adj['BIL'][0] | 56.9642 | PRECISE |
> | GLD initial shares | 10000 / 2.7908 = 3583.1705 | PRECISE |
> | BIL initial shares (per sleeve) | 45000 / 56.9642 = 789.9699 | PRECISE |

---

## Step 2 — Compute Indicators

All indicators use raw closes (not adjusted close). Indicators are computed **only on the two signal tickers** (QQQ, SPY). BIL and GLD need no indicators.

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
var    = sum((r − mu)² for r in lr) / 19                     # sample variance, ÷N−1
HVol[i] = sqrt(var × 252) × 100.0                            for i ≥ 20
HVol[i] = None                                                for i <  20
```

**CRITICAL: denominator is 19 (N−1 = sample variance).**

> 🛑 **STOP AND VERIFY**
>
> | Check | Target | Type |
> |---|---|---|
> | WMA['QQQ'][9] is real, WMA['QQQ'][8] is None | (period 10) | PRECISE |
> | WMA['SPY'][4] is real, WMA['SPY'][3] is None | (period 5) | PRECISE |
> | SMA['QQQ'][174] is real, SMA['QQQ'][173] is None | (period 175) | PRECISE |
> | SMA['SPY'][199] is real, SMA['SPY'][198] is None | (period 200) | PRECISE |
> | HVol['QQQ'][20] is real, HVol['QQQ'][19] is None | (period 20) | PRECISE |
> | HVol['QQQ'] on 2008-10-10 | 51.7% | PRECISE |
> | HVol['QQQ'] on 2017-08-15 | 10.9% | PRECISE |

---

## Step 3 — Build a Single Equity Sleeve

Build QQQ→TQQQ (sleeve 1, WMA=10/SMA=175) in isolation first.

### Sleeve State Object — Initial Values

| Field | Initial | Reset on | Notes |
|---|---|---|---|
| state | 'cash' | — | cash / vehicle / defensive |
| next_state | None | Phase 1 execution | Set in Phase 6, cleared in Phase 1 |
| v_entry | 0.0 | Vehicle entry | Adj open fill price of vehicle |
| v_stop | 0.0 | Vehicle entry | v_entry × 0.88 — checked vs adj close |
| v_shares | 0.0 | Vehicle exit | Shares of vehicle currently held |
| d_shares | 0.0 | Defensive exit | Shares of defensive (QQQ or SPY) |
| d_entry | 0.0 | Defensive entry | Adj open fill price of defensive |
| **c_shares** | **see below** | **Cash entry/exit** | **Shares of BIL held while in cash state** |
| cash | 0.0 | — | Transient $ bridge used only during a Phase 1 transition |
| wma_was_below | True | See latch logic | Arms the latch after WMA dips below SMA |
| entry_eligible | False | See latch logic | True after a valid cross-above fires |
| equity | 45000.0 | Phase 3 each bar | Mark-to-market sleeve value |
| cooldown | 0 | Phase 2 (decrements) | Blocks entry when > 0 |

> **⚠ Both sleeves start in the cash state.** At initialization, convert each sleeve's $45,000 into BIL shares:
> `c_shares = 45000 / adj['BIL'][0]`. The sleeve's `cash` field is a transient dollar bridge — it is non-zero only momentarily during a Phase 1 state transition.

### 3a — Loop Only, No Signals

Build Phases 1–5. No signal logic — sleeve stays in cash, holding BIL the whole time.

> 🛑 **STOP AND VERIFY**
>
> - Loop completes 6,594 bars without exception · PRECISE
> - With no signals, the sleeve holds BIL throughout — its equity tracks BIL's adjusted close × c_shares (NOT flat $45,000) · PRECISE
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
    wma_was_below = True
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

Phase 1 executes on bar i+1 — note the cash→vehicle path liquidates BIL first:

```
co = opens['BIL'][i+1]  × ratio['BIL'][i+1]
vo = opens['TQQQ'][i+1] × ratio['TQQQ'][i+1]
cash      = c_shares × co     # liquidate BIL
c_shares  = 0
v_shares  = cash / vo
v_entry   = vo
v_stop    = vo × 0.88
cash      = 0
state     = 'vehicle'
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

> 🛑 **STOP AND VERIFY**
>
> QQQ→TQQQ first 3 vehicle trades:
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2003-09-04 | 2003-09-26 | −14.47% | stop_loss(12%) |
> | 2004-06-01 | 2004-07-14 | −11.27% | wma_cross_below |
> | 2004-10-07 | 2005-03-23 | +0.15% | wma_cross_below |

### 3e — Add Defensive Stop → Cash (BIL)

While state == 'defensive' with no pending transition:

```
if adj['QQQ'][i] ≤ d_entry × 0.82:
    d_exit_rsn = 'def_stop(18%)'
    cooldown = 30
    next_state = 'cash'
```

Phase 1 fill for defensive → cash — the proceeds buy BIL:

```
do = opens['QQQ'][i+1] × ratio['QQQ'][i+1]
co = opens['BIL'][i+1] × ratio['BIL'][i+1]
cash     = d_shares × do      # liquidate defensive
d_shares = 0
c_shares = cash / co          # buy BIL
cash     = 0
state    = 'cash'
```

While in the cash state the sleeve holds BIL. Phase 3 marks it to market:
`equity = c_shares × adj['BIL'][i]`.

### 3f — Sleeve Isolation Verification

Run each sleeve in isolation: $100K starting capital, no GLD, no rebalance, cash state holding BIL.

Trade counts and entry/exit dates are unchanged from v1 — BIL does not touch the signal logic, only what idle capital earns. Only the equity totals differ.

---

## Step 4 — Add SPY Sleeve, GLD, and Annual Rebalance

### Sleeve Configurations

| Sleeve | Signal | Vehicle | Defensive | Cash holding | WMA | SMA | Initial $ |
|---|---|---|---|---|---:|---:|---:|
| QQQ | QQQ | TQQQ | QQQ | BIL | 10 | 175 | $45,000 |
| SPY | SPY | SPXL | SPY | BIL | 5 | 200 | $45,000 |
| GLD | — | — | — | — | — | — | $10,000 (buy at adj[0] and hold) |

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
    v_stop   = adj[vehicle][i] × 0.88
if state == 'defensive':
    d_shares = eq_target / adj[defensive][i]
if state == 'cash':
    c_shares = eq_target / adj['BIL'][i]      # resize the BIL holding

equity = eq_target
gld_shares = gld_target / adj['GLD'][i]
```

> 🛑 **STOP AND VERIFY — Full System** PRECISE
>
> | Metric | Target |
> |---|---:|
> | Real trades | 86 (38 QQQ→TQQQ + 48 SPY→SPXL) |
> | Rebalance events | 26 |
> | Final equity | $50,081,555 |
> | CAGR | +26.76% |
> | Max DD | −37.46% |
> | Sharpe | 0.8752 |
>
> **QQQ→TQQQ first 3 vehicle trades (full system):** PRECISE
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2003-09-04 | 2003-09-26 | −14.47% | stop_loss(12%) |
> | 2004-06-01 | 2004-07-14 | −11.27% | wma_cross_below |
> | 2004-10-07 | 2005-03-23 | +0.15% | wma_cross_below |
>
> **SPY→SPXL first 3 vehicle trades (full system):** PRECISE
>
> | Entry | Exit | P&L | Reason |
> |---|---|---:|---|
> | 2002-03-22 | 2002-03-27 | −1.28% | wma_cross_below |
> | 2003-05-16 | 2004-07-20 | +63.58% | wma_cross_below |
> | 2004-09-07 | 2004-09-24 | −2.58% | wma_cross_below |

> Note: trade dates, entry/exit prices, and the 86-trade count are **identical to v1** — BIL changes only what idle capital earns, never the signal logic.

---

## Step 5 — Final Position Close-Out & Metrics

### Close-Out

After the last bar, mark open positions to the last adjusted close for the trade log. A sleeve still in the cash state is simply marked at `c_shares × adj['BIL'][-1]` (cash periods are not logged as trades).

### Metrics

| Metric | Exact formula |
|---|---|
| years | (last_date − first_date).days / 365.25 = 9576 / 365.25 = 26.2108 |
| CAGR | (final_equity / 100,000)^(1 / years) − 1, as % |
| Max DD | min of (equity[i] − running_peak) / running_peak across all i; running_peak starts at 100,000 |
| Sharpe | mean(daily_ret) / std(daily_ret, ddof=1) × √252; risk-free=0 |
| Total return | (final_equity − 100,000) / 100,000 × 100 |

---

## Causal Timing — Complete Reference

| Action | Signal bar | Fill bar | Fill price |
|---|---|---|---|
| Vehicle entry | Phase 6, bar i | Phase 1, bar i+1 | opens[veh][i+1] × ratio[veh][i+1] |
| Vehicle exit — all types | Phase 6, bar i | Phase 1, bar i+1 | opens[veh][i+1] × ratio[veh][i+1] |
| Defensive entry | Phase 6, bar i | Phase 1, bar i+1 | opens[def][i+1] × ratio[def][i+1] |
| Defensive exit → cash | Phase 6, bar i | Phase 1, bar i+1 | opens[def][i+1] × ratio[def][i+1], then buy BIL at opens[BIL][i+1] × ratio[BIL][i+1] |
| Cash → vehicle | Phase 6, bar i | Phase 1, bar i+1 | sell BIL at opens[BIL][i+1] × ratio[BIL][i+1], then buy veh |
| Annual rebalance | year change, bar i | Phase 4, bar i | adj[ticker][i] (close of first Jan bar) |

---

## Appendix A — Common Builder Errors

### 1. Stranding the initial capital when the cash state holds BIL

Both sleeves start in the cash state. If you initialize `cash = 45000` but read `c_shares` (which is 0) for cash-state mark-to-market, the starting capital is invisible. **Fix:** at initialization convert `c_shares = 45000 / adj['BIL'][0]` and set `cash = 0`.

### 2. Marking GLD/BIL to market after the rebalance reads equity

The rebalance uses Phase 3 equity from all positions including GLD and any BIL holdings. Mark everything to market in Phase 3, before Phase 4.

### 3. Same-bar fills

All fills must use `opens[i+1] × ratio[i+1]` — including the BIL leg of cash transitions.

### 4. HVol with population variance (÷N instead of ÷N−1)

Use sample variance (N−1=19) throughout.

### 5. Cooldown on non-stop exits

Only the hard stop (−12%) and defensive stop (−18%) set cooldown=30.

### 6. Rotating to cash directly on vehicle exit

All four vehicle exits rotate to the DEFENSIVE holding — not cash. Only the defensive stop rotates to cash (BIL).

### 7. Logging cash (BIL) periods as trades

The cash state holding BIL is NOT a logged trade. Trade count stays 86 (vehicle legs + defensive legs only). The BIL holding period is bracketed by the defensive-exit trade and the next vehicle-entry — neither the buy nor the sell of BIL is a trade-log row.

---

## Appendix B — What Was Excluded (And Why)

Investigated and rejected during v1 / v1.1 design:

| Feature | Result | Status |
|---|---|---|
| **Cash → BIL (T-bills)** | **+$14.6M, all metrics better** | **ADOPTED in v1.1** |
| Cash → TLT (long Treasuries) | +$10.0M but more volatile (2022 crash) | Rejected — BIL better |
| Cash → GLD (gold) | +$10.9M but MaxDD worsens to −47.78% | Rejected — DD cost |
| Pyramid sizing (v3-style) | Un-tested on this optimized base | Deferred to v2 |
| 3rd sleeve: SMH/DIA/XLK | All dilute the portfolio, Sharpe drops | Rejected |
| ATR / VIX entry sizing | No effect / unfavorable CAGR-for-DD trade | Rejected |
| Trailing stop on winners | Cost $19–31M | Rejected |
| Take-profit ≠ +200% | +200% is a sharp peak; both directions worse | Confirmed +200% |
| Hard-stop tightening / regime filter / circuit breaker | All unfavorable | Rejected |

---

## Appendix C — Reference Implementation

Working Python reference: `backtest_two_sleeves_v1_1.py` (same directory). Pure stdlib, no external dependencies, **no VectorVest data**.

Data files required (`json/` subdirectory):

- `QQQ_US.json`, `SPY_US.json` — real history
- `TQQQ_US.json`, `SPXL_US.json`, `GLD_US.json`, `BIL_US.json` — spliced (synthetic + real)

VIX is not required for v1.1 (no pyramid). It will be required for v2.

---

*Two-Sleeves Optimized · Build Guide v1.1 · Backtest does not guarantee future results*
