#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized v1.2  —  Daily Signal Generator
  Per spec: TwoSleeves_Optimized_Build_Guide_v1_2.md

  Re-runs the full v1.2 simulation through every available bar. The final
  sleeve states — plus any pending transition — ARE the daily signal.
  Stateless: no positions file to drift; correct by construction.

  v1.2 adds a 5th vehicle exit: VIX > SMA(VIX,20) × 2.0  -> rotate to defensive.

  Causal timing: signals are detected at today's close; trades execute at the
  NEXT session's open. So a run after today's close yields the order to place
  at tomorrow's open.

  Usage:   python3 two_sleeve_daily_signal.py
═══════════════════════════════════════════════════════════════════════════════

DATA: json/{QQQ,TQQQ,SPY,SPXL,GLD,BIL}_US.json + json/VIX_INDX.json
NO external dependencies — stdlib only. NO VectorVest, NO web requests.
"""

import json
import math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

# ── Config (identical to backtest_two_sleeves_v1_2.py, no end-date cap) ───────
TOTAL_CAPITAL   = 100_000.0
SAFETY_TICKER   = "GLD"
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

# v1.2 additions
VIX_TICKER      = "VIX_INDX"
VIX_MA_PERIOD   = 20
VIX_SPIKE_MULT  = 2.0

EQUITY_CONFIGS = [
    ("QQQ", "TQQQ", "QQQ", 10, 175),
    ("SPY", "SPXL", "SPY",  5, 200),
]
MIN_IDX = max(VOL_PERIOD, VIX_MA_PERIOD,
              *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


# ── Indicators ────────────────────────────────────────────────────────────────
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


def load_ticker(t):
    # VIX_INDX has no _US suffix; everything else does.
    path = DATA_DIR / f"{t}.json" if t == VIX_TICKER else DATA_DIR / f"{t}_US.json"
    if not path.exists():
        raise FileNotFoundError(f"Required data file missing: {path}")
    raw = json.load(open(path))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


# ── Load data (7 tickers: 6 strategy + VIX) ───────────────────────────────────
all_tickers = {SAFETY_TICKER, CASH_TICKER, VIX_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS:
    all_tickers |= {s, v, d}
raw_data = {t: load_ticker(t) for t in sorted(all_tickers)}
common = sorted(set.intersection(*[set(raw_data[t].keys()) for t in all_tickers]))
n = len(common)

arrays = {}
for t, d in raw_data.items():
    closes = [d[day]["close"]          for day in common]
    adjs   = [d[day]["adjusted_close"] for day in common]
    opens  = [d[day]["open"]           for day in common]
    ratios = [a/c if c else 1.0 for a, c in zip(adjs, closes)]
    arrays[t] = dict(closes=closes, adj=adjs, opens=opens, ratio=ratios)
for s, v, d, wma, sma in EQUITY_CONFIGS:
    c = arrays[s]["closes"]
    arrays[s]["wma"]  = compute_wma(c, wma)
    arrays[s]["sma"]  = compute_sma(c, sma)
    arrays[s]["hvol"] = compute_hvol(c, VOL_PERIOD)

vix_close = arrays[VIX_TICKER]["closes"]
vix_sma   = compute_sma(vix_close, VIX_MA_PERIOD)


# ── Sleeve init ───────────────────────────────────────────────────────────────
def make_sleeve(signal, vehicle, defensive, wma_period, sma_period):
    return dict(
        signal=signal, vehicle=vehicle, defensive=defensive,
        wma_period=wma_period, sma_period=sma_period, label=f"{signal}->{vehicle}",
        state="cash", next_state=None,
        v_shares=0.0, v_entry=0.0, v_entry_date="", v_exit_rsn="",
        d_shares=0.0, d_entry=0.0, d_entry_date="",
        c_shares=0.0, c_entry_date=common[0], cash=0.0, equity=EQ_ALLOC_EACH,
        wma_was_below=True, entry_eligible=False, cooldown=0,
    )

eq_sleeves = [make_sleeve(s, v, d, w, sm) for s, v, d, w, sm in EQUITY_CONFIGS]
cash_adj0  = arrays[CASH_TICKER]["adj"][0]
for sl in eq_sleeves:
    sl["c_shares"] = EQ_ALLOC_EACH / cash_adj0
gld_shares = SAFETY_INIT / arrays[SAFETY_TICKER]["adj"][0]
gld_equity = SAFETY_INIT
prev_year  = int(common[0][:4])


# ── Simulation (identical to v1.2 backtest, uncapped) ─────────────────────────
for i in range(n):
    day = common[i]

    for sl in eq_sleeves:
        if sl["next_state"] is None:
            continue
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
            sl["v_shares"] = sl["cash"]/vo; sl["v_entry"] = vo; sl["v_entry_date"] = day
        elif sl["next_state"] == "defensive":
            sl["d_shares"] = sl["cash"]/do; sl["d_entry"] = do; sl["d_entry_date"] = day
        elif sl["next_state"] == "cash":
            sl["c_shares"] = sl["cash"]/co; sl["c_entry_date"] = day
        sl["cash"] = 0.0
        sl["state"] = sl["next_state"]; sl["next_state"] = None

    for sl in eq_sleeves:
        if sl["cooldown"] > 0:
            sl["cooldown"] -= 1

    for sl in eq_sleeves:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][i]
    gld_equity = gld_shares * arrays[SAFETY_TICKER]["adj"][i]

    cur_year = int(day[:4])
    if cur_year > prev_year:
        total_eq = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
        eq_t  = total_eq * (EQ_ALLOC_EACH / TOTAL_CAPITAL)
        gld_t = total_eq * (SAFETY_INIT   / TOTAL_CAPITAL)
        for sl in eq_sleeves:
            if sl["state"] == "vehicle":
                sl["v_shares"] = eq_t / arrays[sl["vehicle"]]["adj"][i]
            elif sl["state"] == "defensive":
                sl["d_shares"] = eq_t / arrays[sl["defensive"]]["adj"][i]
            else:
                sl["c_shares"] = eq_t / arrays[CASH_TICKER]["adj"][i]
            sl["equity"] = eq_t
        gld_shares = gld_t / arrays[SAFETY_TICKER]["adj"][i]
        gld_equity = gld_t
    prev_year = cur_year

    if i < MIN_IDX:
        continue

    # v1.2: VIX spike condition
    vix_now = vix_close[i]
    vix_ma_now = vix_sma[i]
    vix_spike  = (vix_ma_now is not None and vix_now > vix_ma_now * VIX_SPIKE_MULT)

    for sl in eq_sleeves:
        sig, veh = sl["signal"], sl["vehicle"]
        wa, sa, hva = arrays[sig]["wma"], arrays[sig]["sma"], arrays[sig]["hvol"]
        if any(x is None for x in [wa[i], sa[i], wa[i-1], sa[i-1]]):
            continue
        w, wp = wa[i], wa[i-1]; s, sp = sa[i], sa[i-1]
        hv  = hva[i] if hva[i] is not None else 0.0
        cab = wp <= sp and w >  s
        cbl = wp >= sp and w <  s

        if sl["state"] == "vehicle" and sl["next_state"] is None:
            vad   = arrays[veh]["adj"][i]
            do_tp = vad >= sl["v_entry"] * (1 + TAKE_PROFIT_PCT/100)
            do_sl = vad <= sl["v_entry"] * (1 - STOP_LOSS_PCT/100)
            do_v  = hv >= VOL_EXIT_THRESH
            do_w  = cbl
            do_spike = vix_spike     # v1.2
            if do_tp or do_sl or do_v or do_w or do_spike:
                if do_tp:    sl["v_exit_rsn"] = f"take_profit({TAKE_PROFIT_PCT:.0f}%)"
                elif do_sl:  sl["v_exit_rsn"] = f"stop_loss({STOP_LOSS_PCT:.0f}%)"; sl["cooldown"] = COOLDOWN_DAYS
                elif do_v:   sl["v_exit_rsn"] = f"vol_exit({hv:.1f}%)"
                elif do_w:   sl["v_exit_rsn"] = "wma_cross_below"
                else:        sl["v_exit_rsn"] = f"vix_spike({VIX_SPIKE_MULT}x_MA{VIX_MA_PERIOD})"
                sl["wma_was_below"] = False
                sl["next_state"] = "defensive"

        if sl["state"] == "defensive" and sl["next_state"] is None:
            dad = arrays[sl["defensive"]]["adj"][i]
            if sl["d_entry"] > 0 and dad <= sl["d_entry"] * (1 - DEF_STOP_PCT/100):
                sl["cooldown"] = COOLDOWN_DAYS
                sl["next_state"] = "cash"

        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if w < s: sl["wma_was_below"] = True; sl["entry_eligible"] = False
            if cab and sl["wma_was_below"]: sl["entry_eligible"] = True; sl["wma_was_below"] = False
            if sl["entry_eligible"] and w < s: sl["entry_eligible"] = False; sl["wma_was_below"] = True

        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if (sl["entry_eligible"] and hv <= VOL_ENTRY_MAX
                    and w > s and i + 1 < n and sl["cooldown"] == 0):
                sl["next_state"] = "vehicle"
                sl["entry_eligible"] = False; sl["wma_was_below"] = False


# ── Live-entry check on the LAST bar (drop the backtest's i+1<n guard) ────────
last = n - 1
for sl in eq_sleeves:
    if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
        sig = sl["signal"]
        wa, sa, hva = arrays[sig]["wma"], arrays[sig]["sma"], arrays[sig]["hvol"]
        if any(x is None for x in [wa[last], sa[last], wa[last-1], sa[last-1]]):
            continue
        w, s = wa[last], sa[last]
        hv = hva[last] if hva[last] is not None else 0.0
        if (sl["entry_eligible"] and hv <= VOL_ENTRY_MAX
                and w > s and sl["cooldown"] == 0):
            sl["next_state"] = "vehicle"


# ── Report ────────────────────────────────────────────────────────────────────
last_day   = common[-1]
total_eq   = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
days_stale = (date.today() - date.fromisoformat(last_day)).days
vix_last   = vix_close[-1]
vix_ma_last= vix_sma[-1]
vix_trig   = vix_ma_last * VIX_SPIKE_MULT if vix_ma_last is not None else None

def fmt_pct(x):  return f"{x:+.2f}%"
def held(d):     return (date.fromisoformat(last_day) - date.fromisoformat(d)).days

BAR = "═" * 70
DSH = "─" * 70
print()
print(BAR)
print(f"  TWO-SLEEVES v1.2  —  DAILY SIGNAL  —  {date.today().isoformat()}")
print(f"  Last data bar : {last_day}")
if days_stale > 4:
    print(f"  ⚠  DATA IS {days_stale} CALENDAR DAYS OLD — refresh json/ before trading")
print(BAR)

# Pending trades
print()
print("  PENDING TRADES  (place as market-on-open orders for the next session)")
print(DSH)
pending = [sl for sl in eq_sleeves if sl["next_state"] is not None]
if not pending:
    print("  No trades — hold all current positions.")
else:
    for sl in pending:
        cur = {"vehicle": sl["vehicle"], "defensive": sl["defensive"], "cash": CASH_TICKER}[sl["state"]]
        nxt_tkr = {"vehicle": sl["vehicle"], "defensive": sl["defensive"], "cash": CASH_TICKER}[sl["next_state"]]
        reason = sl.get("v_exit_rsn", "") if sl["state"] == "vehicle" else \
                 ("def_stop(18%)" if sl["next_state"] == "cash" else "entry signal")
        print(f"  {sl['label']:<12}  SELL {cur:<5} → BUY {nxt_tkr:<5}   ({sl['state']} → {sl['next_state']})")
        print(f"  {'':<12}  trigger: {reason}")

# Current positions
print()
print("  CURRENT POSITIONS")
print(DSH)
for sl in eq_sleeves:
    sig, veh, dfn = sl["signal"], sl["vehicle"], sl["defensive"]
    wa, sa, hva = arrays[sig]["wma"], arrays[sig]["sma"], arrays[sig]["hvol"]
    w, s = wa[-1], sa[-1]
    hv = hva[-1] if hva[-1] is not None else 0.0
    wt = sl["equity"] / total_eq * 100

    if sl["state"] == "vehicle":
        vad = arrays[veh]["adj"][-1]
        pnl = (vad - sl["v_entry"]) / sl["v_entry"] * 100
        tp_lvl = sl["v_entry"] * (1 + TAKE_PROFIT_PCT/100)
        sl_lvl = sl["v_entry"] * (1 - STOP_LOSS_PCT/100)
        print(f"  {sl['label']:<12}  VEHICLE  holding {veh}   {wt:.1f}% of portfolio")
        print(f"  {'':<12}  entry {sl['v_entry']:.4f} on {sl['v_entry_date']}   "
              f"now {vad:.4f}   P&L {fmt_pct(pnl)}   held {held(sl['v_entry_date'])}d")
        print(f"  {'':<12}  EXIT CRITERIA (whichever fires first → rotate to {dfn}):")
        print(f"  {'':<12}    take profit : adj ≥ {tp_lvl:.4f}   (+200%)   gap {(tp_lvl/vad-1)*100:+.1f}%")
        print(f"  {'':<12}    hard stop   : adj ≤ {sl_lvl:.4f}   (−12%)    cushion {(vad/sl_lvl-1)*100:+.1f}%")
        print(f"  {'':<12}    vol exit    : {sig} HVol ≥ 30%   (now {hv:.1f}%)")
        print(f"  {'':<12}    WMA cross   : {sig} WMA{sl['wma_period']} {w:.2f} vs SMA{sl['sma_period']} {s:.2f}"
              f"  ({'BULL +' if w>s else 'BEAR '}{w-s:+.2f})")
        if vix_trig is not None:
            print(f"  {'':<12}    VIX spike   : VIX > {vix_trig:.2f}   "
                  f"(now {vix_last:.2f}, MA{VIX_MA_PERIOD}={vix_ma_last:.2f}, "
                  f"ratio {vix_last/vix_ma_last:.2f}x)")

    elif sl["state"] == "defensive":
        dad = arrays[dfn]["adj"][-1]
        pnl = (dad - sl["d_entry"]) / sl["d_entry"] * 100 if sl["d_entry"] else 0.0
        ds_lvl = sl["d_entry"] * (1 - DEF_STOP_PCT/100)
        print(f"  {sl['label']:<12}  DEFENSIVE  holding {dfn}   {wt:.1f}% of portfolio")
        print(f"  {'':<12}  entry {sl['d_entry']:.4f} on {sl['d_entry_date']}   "
              f"now {dad:.4f}   P&L {fmt_pct(pnl)}   held {held(sl['d_entry_date'])}d")
        print(f"  {'':<12}  EXIT CRITERIA:")
        print(f"  {'':<12}    def stop    : adj ≤ {ds_lvl:.4f}   (−18% → cash/BIL)   "
              f"cushion {(dad/ds_lvl-1)*100:+.1f}%")
        cd = f"cooldown {sl['cooldown']}d left" if sl["cooldown"] > 0 else "cooldown clear"
        latch = "ARMED" if sl["entry_eligible"] else "not armed"
        print(f"  {'':<12}  RE-ENTRY to {veh} needs: WMA>SMA + HVol≤16% + cooldown=0")
        print(f"  {'':<12}    {sig} WMA{sl['wma_period']} {w:.2f} vs SMA{sl['sma_period']} {s:.2f}"
              f"  ({'BULL' if w>s else 'BEAR'})   HVol {hv:.1f}%   latch {latch}   {cd}")

    else:  # cash
        print(f"  {sl['label']:<12}  CASH  holding {CASH_TICKER} (T-bills)   {wt:.1f}% of portfolio")
        cd = f"cooldown {sl['cooldown']}d left" if sl["cooldown"] > 0 else "cooldown clear"
        latch = "ARMED" if sl["entry_eligible"] else "not armed"
        print(f"  {'':<12}  RE-ENTRY to {veh} needs: WMA>SMA + HVol≤16% + cooldown=0")
        print(f"  {'':<12}    {sig} WMA{sl['wma_period']} {w:.2f} vs SMA{sl['sma_period']} {s:.2f}"
              f"  ({'BULL' if w>s else 'BEAR'})   HVol {hv:.1f}%   latch {latch}   {cd}")

gld_wt = gld_equity / total_eq * 100
next_rebal = f"{int(last_day[:4])+1}-01-02 (approx — first trading day of next year)"
print(f"  {'GLD':<12}  HOLD  buy & hold gold   {gld_wt:.1f}% of portfolio")
print(f"  {'':<12}  next annual rebalance: {next_rebal}")

# Key indicators
print()
print("  KEY INDICATORS  (last bar)")
print(DSH)
for sl in eq_sleeves:
    sig = sl["signal"]
    wa, sa, hva = arrays[sig]["wma"], arrays[sig]["sma"], arrays[sig]["hvol"]
    w, s = wa[-1], sa[-1]
    hv = hva[-1] if hva[-1] is not None else 0.0
    regime = "BULL" if w > s else "BEAR"
    print(f"  {sig:<4} WMA{sl['wma_period']:<3}={w:>9.2f}   SMA{sl['sma_period']:<3}={s:>9.2f}   "
          f"HVol={hv:>5.1f}%   [{regime}]")
if vix_ma_last is not None:
    ratio = vix_last / vix_ma_last
    flag = "  ⚠ SPIKE" if ratio > VIX_SPIKE_MULT else ""
    print(f"  VIX  now ={vix_last:>9.2f}   SMA{VIX_MA_PERIOD:<3}={vix_ma_last:>9.2f}   "
          f"ratio {ratio:.2f}x  (spike trigger {VIX_SPIKE_MULT}x){flag}")

print()
print(f"  Strategy tracked equity (since $100k on {common[0]}): ${total_eq:,.0f}")
print(f"  Sleeve weights:  QQQ→TQQQ {eq_sleeves[0]['equity']/total_eq*100:.1f}%   "
      f"SPY→SPXL {eq_sleeves[1]['equity']/total_eq*100:.1f}%   GLD {gld_wt:.1f}%   (targets 45/45/10)")
print(BAR)
