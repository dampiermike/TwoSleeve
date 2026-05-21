#!/usr/bin/env python3
"""
VIX crash-overlay test on Two-Sleeves Optimized v1.1.

Problem being addressed: in a crash the strategy exits in TWO steps —
vehicle -> defensive (-12%) -> cash/BIL (-18%). It eats both legs before
reaching safety. These overlays try to reach BIL faster.

Treatments:
  baseline        : v1.1 unchanged
  panic_X_Y       : when VIX >= X, force ALL sleeves straight to BIL
                    (skip defensive); block entries until VIX < Y.
  defaccel_X      : while a sleeve is in DEFENSIVE, if VIX >= X jump
                    straight to BIL immediately (don't wait for -18%).
                    Vehicle logic and re-entry signals untouched.
  vixroc          : VIX rate-of-change spike — if VIX >= 1.5x its value
                    10 bars ago AND VIX >= 25, force all sleeves to BIL;
                    block entries until the spike condition clears.

Everything else held at v1.1 spec.
"""

import json, math
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

TOTAL_CAPITAL   = 100_000.0
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

EQUITY_CONFIGS = [
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
    n, out = len(c), [None]*len(c); s = sum(c[:p]); out[p-1] = s/p
    for i in range(p, n):
        s += c[i] - c[i-p]; out[i] = s/p
    return out

def load_ticker(t):
    raw = json.load(open(DATA_DIR / f"{t}_US.json"))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    raw.sort(key=lambda r: r["date"])
    return {r["date"]: r for r in raw}

def load_vix():
    raw = json.load(open(DATA_DIR / "VIX_INDX.json"))
    raw = [r for r in raw if date.fromisoformat(r["date"]) >= BACKTEST_START]
    return {r["date"]: r["close"] for r in raw}


print("Loading data...", flush=True)
tickers = {"GLD", CASH_TICKER}
for s, v, d, _, _ in EQUITY_CONFIGS: tickers |= {s, v, d}
raw_data = {t: load_ticker(t) for t in tickers}
vix_data = load_vix()
common   = sorted(set.intersection(*[set(raw_data[t].keys()) for t in tickers]))
n = len(common)
print(f"  {n} bars  {common[0]} -> {common[-1]}\n")

arrays = {}
for tk, d in raw_data.items():
    closes = [d[day]["close"]          for day in common]
    adjs   = [d[day]["adjusted_close"] for day in common]
    opens  = [d[day]["open"]           for day in common]
    ratios = [a/c if c else 1.0 for a, c in zip(adjs, closes)]
    arrays[tk] = dict(closes=closes, adj=adjs, opens=opens, ratio=ratios)

for s, v, d, wma, sma in EQUITY_CONFIGS:
    c = arrays[s]["closes"]
    arrays[s]["wma"]  = compute_wma(c, wma)
    arrays[s]["sma"]  = compute_sma(c, sma)
    arrays[s]["hvol"] = compute_hvol(c, VOL_PERIOD)

# Forward-fill VIX onto common_dates
vix_arr = []; last = 20.0
for day in common:
    if day in vix_data: last = vix_data[day]
    vix_arr.append(last)

MIN_IDX = max(VOL_PERIOD, *(c[3] for c in EQUITY_CONFIGS), *(c[4] for c in EQUITY_CONFIGS))


def run(mode="baseline", panic_enter=None, panic_exit=None, defaccel=None,
        roc_mult=1.5, roc_lookback=10, roc_floor=25.0):
    def make_sleeve(signal, vehicle, defensive, wma, sma):
        return dict(signal=signal, vehicle=vehicle, defensive=defensive,
                    wma_period=wma, sma_period=sma,
                    state="cash", next_state=None,
                    v_shares=0.0, v_entry=0.0, d_shares=0.0, d_entry=0.0,
                    c_shares=0.0, cash=0.0, equity=EQ_ALLOC_EACH,
                    wma_was_below=True, entry_eligible=False, cooldown=0, trades=0)
    eq_sleeves = [make_sleeve(*cfg) for cfg in EQUITY_CONFIGS]
    cash_adj0 = arrays[CASH_TICKER]["adj"][0]
    for sl in eq_sleeves:
        sl["c_shares"] = EQ_ALLOC_EACH / cash_adj0
    gld_shares = SAFETY_INIT / arrays["GLD"]["adj"][0]
    gld_equity = SAFETY_INIT
    portfolio = []
    prev_year = int(common[0][:4])
    panic_active = False
    panic_exits  = 0   # count of forced sleeve exits

    for i in range(n):
        day = common[i]
        vix = vix_arr[i]

        # Phase 1: execute pending transitions
        for sl in eq_sleeves:
            if sl["next_state"] is None: continue
            veh = sl["vehicle"]; dfn = sl["defensive"]
            vo = arrays[veh]["opens"][i] * arrays[veh]["ratio"][i]
            do = arrays[dfn]["opens"][i] * arrays[dfn]["ratio"][i]
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

        for sl in eq_sleeves:
            if sl["cooldown"] > 0: sl["cooldown"] -= 1

        for sl in eq_sleeves:
            if sl["state"] == "vehicle":
                sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][i]
            elif sl["state"] == "defensive":
                sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][i]
            else:
                sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][i]
        gld_equity = gld_shares * arrays["GLD"]["adj"][i]

        cur_year = int(day[:4])
        if cur_year > prev_year:
            total_eq = sum(sl["equity"] for sl in eq_sleeves) + gld_equity
            eq_t = total_eq * 0.45; gld_t = total_eq * 0.10
            for sl in eq_sleeves:
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

        portfolio.append(sum(sl["equity"] for sl in eq_sleeves) + gld_equity)
        if i < MIN_IDX: continue

        # ── VIX overlay state ────────────────────────────────────────────────
        # Determine whether a "crash regime" is active this bar
        crash_now = False
        if mode.startswith("panic"):
            if not panic_active and vix >= panic_enter:
                panic_active = True
            elif panic_active and vix < panic_exit:
                panic_active = False
            crash_now = panic_active
        elif mode == "vixroc":
            ref = vix_arr[i - roc_lookback] if i >= roc_lookback else vix
            spiking = (ref > 0 and vix >= roc_mult * ref and vix >= roc_floor)
            if not panic_active and spiking:
                panic_active = True
            elif panic_active and not spiking:
                panic_active = False
            crash_now = panic_active

        # Panic / ROC: force every non-cash sleeve straight to BIL
        if crash_now:
            for sl in eq_sleeves:
                if sl["state"] != "cash" and sl["next_state"] is None:
                    sl["next_state"] = "cash"
                    panic_exits += 1

        # Signal logic
        for sl in eq_sleeves:
            sig = sl["signal"]; veh = sl["vehicle"]
            wa = arrays[sig]["wma"]; sa = arrays[sig]["sma"]; hva = arrays[sig]["hvol"]
            if any(v is None for v in [wa[i], sa[i], wa[i-1], sa[i-1]]): continue
            w, wp = wa[i], wa[i-1]; s, sp = sa[i], sa[i-1]
            hv = hva[i] if hva[i] is not None else 0.0
            cab = wp <= sp and w > s; cbl = wp >= sp and w < s

            if sl["state"] == "vehicle" and sl["next_state"] is None:
                vad = arrays[veh]["adj"][i]
                do_tp = vad >= sl["v_entry"] * (1 + TAKE_PROFIT_PCT/100)
                do_sl = vad <= sl["v_entry"] * (1 - STOP_LOSS_PCT/100)
                do_v  = hv >= VOL_EXIT_THRESH
                do_w  = cbl
                if do_tp or do_sl or do_v or do_w:
                    if do_sl: sl["cooldown"] = COOLDOWN_DAYS
                    sl["wma_was_below"] = False; sl["next_state"] = "defensive"

            if sl["state"] == "defensive" and sl["next_state"] is None:
                dad = arrays[sl["defensive"]]["adj"][i]
                hit_def = sl["d_entry"] > 0 and dad <= sl["d_entry"] * (1 - DEF_STOP_PCT/100)
                # VIX-accelerated defensive exit
                vix_accel = (mode == "defaccel" and vix >= defaccel)
                if hit_def or vix_accel:
                    sl["cooldown"] = COOLDOWN_DAYS; sl["next_state"] = "cash"

            if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
                if w < s: sl["wma_was_below"] = True; sl["entry_eligible"] = False
                if cab and sl["wma_was_below"]: sl["entry_eligible"] = True; sl["wma_was_below"] = False
                if sl["entry_eligible"] and w < s: sl["entry_eligible"] = False; sl["wma_was_below"] = True

            if sl["state"] in ("cash", "defensive") and sl["next_state"] is None:
                entry_ok = (sl["entry_eligible"] and hv <= VOL_ENTRY_MAX
                            and w > s and i + 1 < n and sl["cooldown"] == 0)
                if entry_ok and not crash_now:   # crash regime blocks new entries
                    sl["next_state"] = "vehicle"
                    sl["entry_eligible"] = False; sl["wma_was_below"] = False

    for sl in eq_sleeves:
        if sl["state"] == "vehicle":
            sl["equity"] = sl["v_shares"] * arrays[sl["vehicle"]]["adj"][-1]
        elif sl["state"] == "defensive":
            sl["equity"] = sl["d_shares"] * arrays[sl["defensive"]]["adj"][-1]
        else:
            sl["equity"] = sl["c_shares"] * arrays[CASH_TICKER]["adj"][-1]
    gld_equity = gld_shares * arrays["GLD"]["adj"][-1]
    portfolio[-1] = sum(sl["equity"] for sl in eq_sleeves) + gld_equity

    final_eq = portfolio[-1]
    years = (date.fromisoformat(common[-1]) - date.fromisoformat(common[0])).days / 365.25
    cagr = ((final_eq/TOTAL_CAPITAL)**(1/years) - 1)*100
    peak = TOTAL_CAPITAL; max_dd = 0.0
    for eq in portfolio:
        if eq > peak: peak = eq
        dd = (eq - peak)/peak * 100
        if dd < max_dd: max_dd = dd
    dr = [(portfolio[i]-portfolio[i-1])/portfolio[i-1] for i in range(1, len(portfolio)) if portfolio[i-1]]
    mu = sum(dr)/len(dr); sig = (sum((r-mu)**2 for r in dr)/(len(dr)-1))**0.5
    sharpe = mu/sig * math.sqrt(252) if sig else 0.0
    return dict(final_eq=final_eq, cagr=cagr, max_dd=max_dd, sharpe=sharpe,
                trades=sum(sl["trades"] for sl in eq_sleeves), panic_exits=panic_exits)


VARIANTS = [
    ("baseline (v1.1)",   dict(mode="baseline")),
    ("panic 30/22",       dict(mode="panic", panic_enter=30, panic_exit=22)),
    ("panic 35/25",       dict(mode="panic", panic_enter=35, panic_exit=25)),
    ("panic 40/30",       dict(mode="panic", panic_enter=40, panic_exit=30)),
    ("panic 45/32",       dict(mode="panic", panic_enter=45, panic_exit=32)),
    ("defaccel VIX>=25",  dict(mode="defaccel", defaccel=25)),
    ("defaccel VIX>=30",  dict(mode="defaccel", defaccel=30)),
    ("defaccel VIX>=35",  dict(mode="defaccel", defaccel=35)),
    ("vixroc 1.5x/10bar", dict(mode="vixroc", roc_mult=1.5, roc_lookback=10, roc_floor=25.0)),
]

print("=" * 104)
print("  VIX CRASH-OVERLAY TEST  —  can we reach BIL faster without wrecking returns?")
print("=" * 104)
print(f"  {'Treatment':<20} {'Final $':>15} {'CAGR':>8} {'MaxDD':>9} {'Sharpe':>8} {'Trades':>7} {'Forced exits':>13}")
print("-" * 104)
BASE_EQ, BASE_DD = 50_081_555, -37.46
for label, kw in VARIANTS:
    m = run(**kw)
    deq = m["final_eq"] - BASE_EQ
    ddd = m["max_dd"] - BASE_DD
    note = ""
    if label.startswith("baseline"):
        note = "  ← v1.1"
    elif ddd > 0.5 and deq > -2_000_000:
        note = "  ★ DD better, eq ~kept"
    elif ddd > 0.5:
        note = f"  DD {ddd:+.1f}, eq {deq:+,.0f}"
    print(f"  {label:<20} ${m['final_eq']:>14,.0f} {m['cagr']:>+7.2f}% {m['max_dd']:>+8.2f}% "
          f"{m['sharpe']:>8.4f} {m['trades']:>7} {m['panic_exits']:>13}{note}")
print()
print("  baseline v1.1: $50,081,555  +26.76%  -37.46%  Sharpe 0.8752")
