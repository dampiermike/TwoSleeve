#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized v1.3  —  Daily Signal Generator  (CANDIDATE / SHADOW)
  Per spec: TwoSleeves_Optimized_Build_Guide_v1_3.md

  ⚠ v1.3 IS NOT LIVE. v1.2 remains the traded strategy; this script runs
    alongside it so the v1.3 signal can be watched in the daily email/text
    before any capital is committed. It places no orders and shares no state
    with the v1.2 signal.

  Same stateless design as the v1.2 signal: re-runs the full simulation over
  every available bar, so the final sleeve states ARE the signal. No positions
  file to drift.

  Causal timing: signals are detected at today's close; trades execute at the
  NEXT session's open.

  Emits one machine-readable line for the notifier:
      V13_SUMMARY: <one-line summary>

  Usage:  python3 two_sleeve_daily_signal_v1_3.py
═══════════════════════════════════════════════════════════════════════════════
"""
import json
import math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

# ── Config — must stay in lockstep with backtest_two_sleeves_v1_3.py ──────────
TOTAL_CAPITAL   = 100_000.0
SAFETY_TICKER   = "GLD"
SAFETY_ALLOC    = 0.05
CASH_TICKER     = "BIL"
VOL_PERIOD      = 20
VOL_EXIT_THRESH = 30.0
TAKE_PROFIT_PCT = 200.0
STOP_LOSS_PCT   = 12.0
DEF_STOP_PCT    = 14.0
COOLDOWN_DAYS   = 30
VIX_TICKER      = "VIX_INDX"
VIX_MA_PERIOD   = 20
VIX_SPIKE_MULT  = 2.2

SLEEVE_CONFIGS = [
    ("QQQ", "TQQQ", "TLT",  5, 200, 75, 25.0),
    ("XLE", "XLE",  "GLD", 16, 175, 14, 12.0),
    ("XLV", "XLV",  "GLD", 16, 125, 11, 12.0),
]
MIN_IDX = max(VOL_PERIOD, VIX_MA_PERIOD,
              *(c[3] for c in SLEEVE_CONFIGS), *(c[4] for c in SLEEVE_CONFIGS))


def compute_hvol(c, p):
    n, out = len(c), [None]*len(c)
    for i in range(p, n):
        lr = [math.log(c[j]/c[j-1]) for j in range(i-p+1, i+1)]
        mu = sum(lr)/p
        out[i] = math.sqrt(sum((r-mu)**2 for r in lr)/(p-1)*252)*100.0
    return out

def compute_wma(c, p):
    n, out = len(c), [None]*len(c); den = p*(p+1)/2
    for i in range(p-1, n):
        out[i] = sum(c[i-p+1+j]*(j+1) for j in range(p))/den
    return out

def compute_sma(c, p):
    n, out = len(c), [None]*len(c)
    if n < p: return out
    s = sum(c[:p]); out[p-1] = s/p
    for i in range(p, n):
        s += c[i]-c[i-p]; out[i] = s/p
    return out

def load_ticker(t):
    path = DATA_DIR / (f"{t}.json" if t == VIX_TICKER else f"{t}_US.json")
    if not path.exists():
        raise FileNotFoundError(f"Required data file missing: {path}")
    raw = json.load(open(path)); raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}


all_tickers = {SAFETY_TICKER, CASH_TICKER, VIX_TICKER}
for s, v, d, _, _, _, _ in SLEEVE_CONFIGS:
    all_tickers |= {s, v, d}
raw_data = {t: load_ticker(t) for t in sorted(all_tickers)}
common = sorted(set.intersection(*[set(raw_data[t]) for t in all_tickers]))
n = len(common)

arrays = {}
for t, d in raw_data.items():
    closes = [d[x]["close"] for x in common]
    adjs   = [d[x]["adjusted_close"] for x in common]
    opens  = [d[x]["open"] for x in common]
    arrays[t] = dict(closes=closes, adj=adjs, opens=opens,
                     ratio=[(a/c if c else 1.0) for a, c in zip(adjs, closes)])
for s, v, d, wma, sma, wt, vem in SLEEVE_CONFIGS:
    c = arrays[s]["closes"]
    arrays[s][f"wma{wma}"] = compute_wma(c, wma)
    arrays[s][f"sma{sma}"] = compute_sma(c, sma)
    arrays[s]["hvol"]      = compute_hvol(c, VOL_PERIOD)
vix_close = arrays[VIX_TICKER]["closes"]
vix_sma   = compute_sma(vix_close, VIX_MA_PERIOD)

raw_w = [c[5] for c in SLEEVE_CONFIGS]; tot_w = sum(raw_w)
weights = [w/tot_w*(1.0-SAFETY_ALLOC) for w in raw_w]

sleeves = []
for (s, v, d, wma, sma, _, vem), w in zip(SLEEVE_CONFIGS, weights):
    init = TOTAL_CAPITAL*w
    sleeves.append(dict(signal=s, vehicle=v, defensive=d, wma_period=wma,
                        sma_period=sma, weight=w, vem=vem, label=f"{s}->{v}",
                        state="cash", next_state=None,
                        v_shares=0.0, v_entry=0.0, v_entry_date="", v_exit_rsn="",
                        d_shares=0.0, d_entry=0.0, d_entry_date="", d_exit_rsn="",
                        c_shares=0.0, cash=init, equity=init,
                        wma_was_below=True, entry_eligible=False, cooldown=0))
for sl in sleeves:
    sl["c_shares"] = sl["cash"]/arrays[CASH_TICKER]["adj"][0]; sl["cash"] = 0.0
gld_shares = TOTAL_CAPITAL*SAFETY_ALLOC/arrays[SAFETY_TICKER]["adj"][0]

prev_m = (int(common[0][:4]), int(common[0][5:7]))
for i in range(n):
    day = common[i]
    for sl in sleeves:
        if sl["next_state"] is None: continue
        veh, dfn = sl["vehicle"], sl["defensive"]
        vo = arrays[veh]["opens"][i]*arrays[veh]["ratio"][i]
        do = arrays[dfn]["opens"][i]*arrays[dfn]["ratio"][i]
        co = arrays[CASH_TICKER]["opens"][i]*arrays[CASH_TICKER]["ratio"][i]
        if sl["state"] == "vehicle":
            sl["cash"] = sl["v_shares"]*vo; sl["v_shares"] = 0.0; sl["v_entry"] = 0.0
        elif sl["state"] == "defensive":
            sl["cash"] = sl["d_shares"]*do; sl["d_shares"] = 0.0
            sl["d_entry"] = 0.0; sl["d_exit_rsn"] = ""
        else:
            sl["cash"] = sl["c_shares"]*co; sl["c_shares"] = 0.0
        if sl["next_state"] == "vehicle":
            sl["v_shares"] = sl["cash"]/vo; sl["v_entry"] = vo
            sl["v_entry_date"] = day; sl["cash"] = 0.0
        elif sl["next_state"] == "defensive":
            sl["d_shares"] = sl["cash"]/do; sl["d_entry"] = do
            sl["d_entry_date"] = day; sl["cash"] = 0.0
        else:
            sl["c_shares"] = sl["cash"]/co; sl["cash"] = 0.0
        sl["state"] = sl["next_state"]; sl["next_state"] = None
    for sl in sleeves:
        if sl["cooldown"] > 0: sl["cooldown"] -= 1
    for sl in sleeves:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"]*arrays[sl["vehicle"]]["adj"][i]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"]*arrays[sl["defensive"]]["adj"][i]
        else:
            sl["equity"] = sl["c_shares"]*arrays[CASH_TICKER]["adj"][i]
    gld_equity = gld_shares*arrays[SAFETY_TICKER]["adj"][i]

    cur_m = (int(day[:4]), int(day[5:7]))
    if cur_m > prev_m:
        total = sum(sl["equity"] for sl in sleeves)+gld_equity
        for sl in sleeves:
            tgt = total*sl["weight"]
            if sl["state"] == "vehicle":
                sl["v_shares"] = tgt/arrays[sl["vehicle"]]["adj"][i]
            elif sl["state"] == "defensive":
                sl["d_shares"] = tgt/arrays[sl["defensive"]]["adj"][i]
            else:
                sl["c_shares"] = tgt/arrays[CASH_TICKER]["adj"][i]
            sl["equity"] = tgt
        gld_shares = total*SAFETY_ALLOC/arrays[SAFETY_TICKER]["adj"][i]
        gld_equity = total*SAFETY_ALLOC
    prev_m = cur_m

    if i < MIN_IDX: continue
    vma = vix_sma[i]
    vix_spike = (vma is not None and vix_close[i] > vma*VIX_SPIKE_MULT)

    for sl in sleeves:
        sig, veh = sl["signal"], sl["vehicle"]
        wa = arrays[sig][f"wma{sl['wma_period']}"]; sa = arrays[sig][f"sma{sl['sma_period']}"]
        hva = arrays[sig]["hvol"]
        if any(x is None for x in (wa[i], sa[i], wa[i-1], sa[i-1])): continue
        w, wp, s, sp = wa[i], wa[i-1], sa[i], sa[i-1]
        hv = hva[i] if hva[i] is not None else 0.0
        cab = wp <= sp and w > s; cbl = wp >= sp and w < s
        if sl["state"] == "vehicle" and sl["next_state"] is None:
            vad = arrays[veh]["adj"][i]
            do_tp = vad >= sl["v_entry"]*(1+TAKE_PROFIT_PCT/100)
            do_sl = vad <= sl["v_entry"]*(1-STOP_LOSS_PCT/100)
            do_v  = hv >= VOL_EXIT_THRESH
            if do_tp or do_sl or do_v or cbl or vix_spike:
                if   do_tp: sl["v_exit_rsn"] = f"take_profit({TAKE_PROFIT_PCT:.0f}%)"
                elif do_sl: sl["v_exit_rsn"] = f"stop_loss({STOP_LOSS_PCT:.0f}%)"; sl["cooldown"] = COOLDOWN_DAYS
                elif do_v:  sl["v_exit_rsn"] = f"vol_exit({hv:.1f}%)"
                elif cbl:   sl["v_exit_rsn"] = "wma_cross_below"
                else:       sl["v_exit_rsn"] = f"vix_spike({VIX_SPIKE_MULT}x_MA{VIX_MA_PERIOD})"
                sl["wma_was_below"] = False; sl["next_state"] = "defensive"
        if sl["state"] == "defensive" and sl["next_state"] is None:
            dad = arrays[sl["defensive"]]["adj"][i]
            if sl["d_entry"] > 0 and dad <= sl["d_entry"]*(1-DEF_STOP_PCT/100):
                sl["d_exit_rsn"] = f"def_stop({DEF_STOP_PCT:.0f}%)"
                sl["cooldown"] = COOLDOWN_DAYS; sl["next_state"] = "cash"
        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if w < s: sl["wma_was_below"] = True; sl["entry_eligible"] = False
            if cab and sl["wma_was_below"]: sl["entry_eligible"] = True; sl["wma_was_below"] = False
            if sl["entry_eligible"] and w < s: sl["entry_eligible"] = False; sl["wma_was_below"] = True
        if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
            if (sl["entry_eligible"] and hv <= sl["vem"] and w > s
                    and i+1 < n and sl["cooldown"] == 0):
                sl["next_state"] = "vehicle"
                sl["entry_eligible"] = False; sl["wma_was_below"] = False

# ── Report ────────────────────────────────────────────────────────────────────
last = common[-1]
today = date.today()
age = (today - date.fromisoformat(last)).days
port = sum(sl["equity"] for sl in sleeves) + gld_shares*arrays[SAFETY_TICKER]["adj"][-1]

BAR = "=" * 70
print(BAR)
print(f"  TWO-SLEEVES v1.3 (CANDIDATE — NOT LIVE)  —  SIGNAL  —  {today}")
print(f"  Last data bar : {last}")
if age > 5:
    print(f"  !  DATA IS {age} CALENDAR DAYS OLD — refresh json/ before trading")
print(BAR)

HOLD = "No trades — hold all current positions."
pending = []
for sl in sleeves:
    if sl["next_state"]:
        frm = {"vehicle": sl["vehicle"], "defensive": sl["defensive"],
               "cash": CASH_TICKER}[sl["state"]]
        to  = {"vehicle": sl["vehicle"], "defensive": sl["defensive"],
               "cash": CASH_TICKER}[sl["next_state"]]
        why = sl["v_exit_rsn"] or sl["d_exit_rsn"] or "entry_signal"
        pending.append(f"{sl['label']}: SELL {frm} -> BUY {to}   ({why})")

print()
print("  PENDING TRADES — v1.3 CANDIDATE  (market-on-open, next session)")
print("  " + "-" * 66)
if pending:
    for p in pending: print(f"  {p}")
else:
    print(f"  {HOLD}")

print()
print("  CURRENT POSITIONS — v1.3 CANDIDATE")
print("  " + "-" * 66)
for sl in sleeves:
    held = {"vehicle": sl["vehicle"], "defensive": sl["defensive"],
            "cash": CASH_TICKER}[sl["state"]]
    pct = sl["equity"]/port*100 if port else 0
    print(f"  {sl['label']:<12} {sl['state'].upper():<10} holding {held:<5} "
          f"{pct:5.1f}% of portfolio   (target {sl['weight']:.1%})")
    if sl["state"] == "vehicle" and sl["v_entry"]:
        nowp = arrays[sl["vehicle"]]["adj"][-1]
        print(f"               entry {sl['v_entry']:.4f} on {sl['v_entry_date']}   "
              f"now {nowp:.4f}   P&L {(nowp/sl['v_entry']-1)*100:+.2f}%")
    elif sl["state"] == "defensive" and sl["d_entry"]:
        nowp = arrays[sl["defensive"]]["adj"][-1]
        print(f"               entry {sl['d_entry']:.4f} on {sl['d_entry_date']}   "
              f"now {nowp:.4f}   P&L {(nowp/sl['d_entry']-1)*100:+.2f}%   "
              f"def stop at -{DEF_STOP_PCT:.0f}%")
gpct = (gld_shares*arrays[SAFETY_TICKER]["adj"][-1])/port*100 if port else 0
print(f"  {'GLD safety':<12} {'HOLD':<10} buy & hold gold {gpct:5.1f}% of portfolio"
      f"   (target {SAFETY_ALLOC:.1%})")

print()
print("  KEY INDICATORS (last bar)")
print("  " + "-" * 66)
for sl in sleeves:
    sig = sl["signal"]
    w = arrays[sig][f"wma{sl['wma_period']}"][-1]
    s = arrays[sig][f"sma{sl['sma_period']}"][-1]
    hv = arrays[sig]["hvol"][-1]
    trend = "BULL" if w > s else "BEAR"
    print(f"  {sig:<4} WMA{sl['wma_period']:<3}={w:>9.2f}  SMA{sl['sma_period']:<3}={s:>9.2f}  "
          f"HVol={hv:5.1f}% (gate <={sl['vem']:.0f}%)  [{trend}]")
vs = vix_sma[-1]
print(f"  VIX  now={vix_close[-1]:>8.2f}  SMA{VIX_MA_PERIOD}={vs:>8.2f}  "
      f"ratio {vix_close[-1]/vs:.2f}x  (spike trigger {VIX_SPIKE_MULT}x)")
print()
print(f"  v1.3 tracked equity (since $100k on {common[0]}): ${port:,.0f}")
print("  NOTE: v1.3 is a CANDIDATE. v1.2 remains the live strategy.")
print(BAR)

# machine-readable line consumed by two_sleeve_notify.py
summary = " | ".join(pending) if pending else "No trades - hold"
print(f"V13_SUMMARY: {summary}")
