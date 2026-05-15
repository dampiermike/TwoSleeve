#!/usr/bin/env python3
"""Two Sleeves w/Gold — full backtest from build guide v3.

Strategy: two equity sleeves (QQQ→TQQQ, SPY→SPXL) running an independent rotation
between a 3x vehicle, the defensive ETF, and cash. GLD safety holding alongside.
Pyramid sizing amplifies winning vehicle trades under a 1.33x broker cap.

All fills next-bar open. Phase order is canonical and must not be reordered.
"""

import json
import math
import os
from dataclasses import dataclass, field

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'json')

TOTAL_CAPITAL = 100_000.0
EQ_ALLOC = 45_000.0
GLD_ALLOC = 10_000.0
EQ_FRAC = 0.45
GLD_FRAC = 0.10

WMA_PERIOD = 20
SMA_PERIOD = 200
VOL_PERIOD = 20
ATR_PERIOD = 10

VOL_ENTRY_MAX = 16.0
VOL_EXIT_THRESH = 30.0

TP_MULT = 3.0
SL_MULT = 0.88
DEF_STOP_MULT = 0.82

COOLDOWN_BARS = 30
MIN_IDX = 200

PYR_THRESH = 0.05
PYR2_THRESH = 0.20

BROKER_MAX_MULT = 1.33


def get_pmp(vix):
    if vix < 20.0:
        return 1.30
    if vix < 32.0:
        return 1.10
    return 0.50


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_full_atr(bars):
    """Compute ATR% on a full single-ticker bar list. Returns dict date -> atr_pct."""
    out = {}
    trs = []
    prev_close = None
    for i, b in enumerate(bars):
        h, l, c = b['high'], b['low'], b['close']
        if prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
        if i >= ATR_PERIOD - 1:
            avg = sum(trs[i - ATR_PERIOD + 1: i + 1]) / ATR_PERIOD
            if c != 0:
                out[b['date']] = avg / c * 100.0
    return out


def load_all():
    raw = {}
    for t in ['GLD', 'QQQ', 'SPY', 'TQQQ', 'SPXL']:
        raw[t] = load_json(os.path.join(DATA_DIR, f'{t}_US.json'))
    vix = load_json(os.path.join(DATA_DIR, 'VIX_INDX.json'))
    vix_dict = {b['date']: b['close'] for b in vix}

    by_date = {}
    for t, bars in raw.items():
        filt = [b for b in bars if b['date'] >= '2000-01-01']
        filt.sort(key=lambda x: x['date'])
        by_date[t] = {b['date']: b for b in filt}

    common = set(by_date['GLD'].keys())
    for t in ['QQQ', 'SPY', 'TQQQ', 'SPXL']:
        common &= set(by_date[t].keys())
    common_dates = sorted(common)
    n = len(common_dates)

    closes, adj, opens, ratio = {}, {}, {}, {}
    for t in ['GLD', 'QQQ', 'SPY', 'TQQQ', 'SPXL']:
        c = [by_date[t][d]['close'] for d in common_dates]
        a = [by_date[t][d]['adjusted_close'] for d in common_dates]
        o = [by_date[t][d]['open'] for d in common_dates]
        r = [a[i] / c[i] if c[i] != 0 else 1.0 for i in range(n)]
        closes[t], adj[t], opens[t], ratio[t] = c, a, o, r

    wma, sma, hvol = {}, {}, {}
    denom = WMA_PERIOD * (WMA_PERIOD + 1) // 2  # 210
    for t in ['QQQ', 'SPY']:
        c = closes[t]
        w = [None] * n
        for i in range(WMA_PERIOD - 1, n):
            s = 0.0
            for j in range(WMA_PERIOD):
                s += c[i - WMA_PERIOD + 1 + j] * (j + 1)
            w[i] = s / denom
        wma[t] = w

        sa = [None] * n
        rs = sum(c[0:SMA_PERIOD])
        sa[SMA_PERIOD - 1] = rs / SMA_PERIOD
        for i in range(SMA_PERIOD, n):
            rs += c[i] - c[i - SMA_PERIOD]
            sa[i] = rs / SMA_PERIOD
        sma[t] = sa

        hv = [None] * n
        for i in range(VOL_PERIOD, n):
            lrs = [math.log(c[j] / c[j - 1]) for j in range(i - VOL_PERIOD + 1, i + 1)]
            mu = sum(lrs) / VOL_PERIOD
            var = sum((r - mu) ** 2 for r in lrs) / (VOL_PERIOD - 1)
            hv[i] = math.sqrt(var * 252) * 100.0
        hvol[t] = hv

    atr = {}
    for t in ['TQQQ', 'SPXL']:
        full = compute_full_atr(raw[t])
        all_dates = sorted(full.keys())
        arr = [None] * n
        last = None
        ai = 0
        for i, d in enumerate(common_dates):
            while ai < len(all_dates) and all_dates[ai] <= d:
                last = full[all_dates[ai]]
                ai += 1
            arr[i] = last
        atr[t] = arr

    vix_arr = [None] * n
    last_vix = None
    all_vix_dates = sorted(vix_dict.keys())
    vi = 0
    for i, d in enumerate(common_dates):
        while vi < len(all_vix_dates) and all_vix_dates[vi] <= d:
            last_vix = vix_dict[all_vix_dates[vi]]
            vi += 1
        vix_arr[i] = last_vix if last_vix is not None else 20.0

    return {
        'common_dates': common_dates,
        'n': n,
        'closes': closes,
        'adj': adj,
        'opens': opens,
        'ratio': ratio,
        'wma': wma,
        'sma': sma,
        'hvol': hvol,
        'atr': atr,
        'vix': vix_arr,
    }


@dataclass
class Sleeve:
    name: str
    sig_t: str
    veh_t: str
    def_t: str
    state: str = 'cash'
    next_state: str = None
    v_entry: float = 0.0
    v_entry_idx: int = -1
    v_stop: float = 0.0
    v_shares: float = 0.0
    v_exit_rsn: str = ''
    margin_debt: float = 0.0
    pyramid1_pending: bool = False
    pyramid1_eq: float = 0.0
    pyramid1_pmp: float = 1.0
    pyramid1_done: bool = False
    pyramid2_pending: bool = False
    pyramid2_eq: float = 0.0
    pyramid2_done: bool = False
    d_shares: float = 0.0
    d_entry: float = 0.0
    d_entry_idx: int = -1
    cash: float = 0.0
    wma_was_below: bool = True
    entry_eligible: bool = False
    equity: float = 0.0
    cooldown: int = 0
    trades: list = field(default_factory=list)
    pyr1_events: list = field(default_factory=list)
    pyr2_events: list = field(default_factory=list)


def run_backtest(data, sleeves_to_run=('QQQ', 'SPY'), enable_gld=True, enable_rebal=True,
                 enable_pyr1=True, enable_pyr2=True, starting_cash=EQ_ALLOC):
    common_dates = data['common_dates']
    n = data['n']
    closes, adj, opens, ratio = data['closes'], data['adj'], data['opens'], data['ratio']
    wma, sma, hvol = data['wma'], data['sma'], data['hvol']
    vix = data['vix']

    sleeves = []
    if 'QQQ' in sleeves_to_run:
        sleeves.append(Sleeve('QQQ', 'QQQ', 'TQQQ', 'QQQ', cash=starting_cash, equity=starting_cash))
    if 'SPY' in sleeves_to_run:
        sleeves.append(Sleeve('SPY', 'SPY', 'SPXL', 'SPY', cash=starting_cash, equity=starting_cash))

    gld_shares = (GLD_ALLOC / adj['GLD'][0]) if enable_gld else 0.0
    gld_equity = GLD_ALLOC if enable_gld else 0.0

    equity_curve = []
    rebal_events = []

    def year_of(d):
        return int(d[:4])

    def phase_1a_pyramid(sleeve, i):
        """Execute pending pyramid fills at open[i] of vehicle."""
        if sleeve.state != 'vehicle':
            sleeve.pyramid1_pending = False
            sleeve.pyramid2_pending = False
            return

        veh = sleeve.veh_t
        fill = opens[veh][i] * ratio[veh][i]

        if sleeve.pyramid1_pending and not sleeve.pyramid1_done:
            pmp = sleeve.pyramid1_pmp
            if pmp > 1.0:
                cur_pos = sleeve.v_shares * fill
                true_eq = cur_pos + sleeve.cash - sleeve.margin_debt
                max_pos = true_eq * BROKER_MAX_MULT
                max_add = max(0.0, max_pos - cur_pos)
                requested = sleeve.pyramid1_eq * (pmp - 1.0)
                actual = min(requested, max_add)
                if actual > 0 and fill > 0:
                    sleeve.v_shares += actual / fill
                    sleeve.margin_debt += actual
            elif pmp < 1.0:
                sell_val = sleeve.v_shares * fill * (1.0 - pmp)
                if fill > 0:
                    sleeve.v_shares -= sell_val / fill
                repay = min(sleeve.margin_debt, sell_val)
                sleeve.margin_debt -= repay
                sleeve.cash += sell_val - repay
            sleeve.pyramid1_done = True
            sleeve.pyramid1_pending = False
            sleeve.pyr1_events.append({
                'date': common_dates[i],
                'pmp': pmp,
                'v_entry': sleeve.v_entry,
            })

        if sleeve.pyramid2_pending and not sleeve.pyramid2_done:
            cur_pos = sleeve.v_shares * fill
            true_eq = cur_pos + sleeve.cash - sleeve.margin_debt
            max_add = max(0.0, true_eq * BROKER_MAX_MULT - cur_pos)
            requested = sleeve.pyramid2_eq * 0.15
            actual = min(requested, max_add)
            if actual > 0 and fill > 0:
                sleeve.v_shares += actual / fill
                sleeve.margin_debt += actual
            sleeve.pyramid2_done = True
            sleeve.pyramid2_pending = False
            sleeve.pyr2_events.append({
                'date': common_dates[i],
                'v_entry': sleeve.v_entry,
            })

    def phase_1b_transition(sleeve, i):
        """Execute pending state transition at open[i]."""
        if sleeve.next_state is None:
            return
        target = sleeve.next_state
        sleeve.next_state = None
        veh, defn = sleeve.veh_t, sleeve.def_t

        if target == 'vehicle':
            if sleeve.state == 'cash':
                cash_avail = sleeve.cash
            elif sleeve.state == 'defensive':
                do = opens[defn][i] * ratio[defn][i]
                cash_avail = sleeve.d_shares * do
                sleeve.trades.append({
                    'type': 'defensive',
                    'entry_date': common_dates[sleeve.d_entry_idx] if sleeve.d_entry_idx >= 0 else None,
                    'exit_date': common_dates[i],
                    'entry_price': sleeve.d_entry,
                    'exit_price': do,
                    'pnl_pct': (do - sleeve.d_entry) / sleeve.d_entry * 100.0 if sleeve.d_entry else 0.0,
                    'exit_reason': 'def_to_vehicle',
                })
                sleeve.d_shares = 0.0
                sleeve.d_entry = 0.0
                sleeve.d_entry_idx = -1
            else:
                cash_avail = sleeve.cash
            vo = opens[veh][i] * ratio[veh][i]
            sleeve.v_shares = cash_avail / vo if vo > 0 else 0.0
            sleeve.v_entry = vo
            sleeve.v_stop = vo * SL_MULT
            sleeve.v_entry_idx = i
            sleeve.margin_debt = 0.0
            sleeve.pyramid1_done = False
            sleeve.pyramid2_done = False
            sleeve.pyramid1_pending = False
            sleeve.pyramid2_pending = False
            sleeve.cash = 0.0
            sleeve.state = 'vehicle'

        elif target == 'defensive':
            vo = opens[veh][i] * ratio[veh][i]
            proceeds = sleeve.v_shares * vo + sleeve.cash - sleeve.margin_debt
            sleeve.trades.append({
                'type': 'vehicle',
                'entry_date': common_dates[sleeve.v_entry_idx] if sleeve.v_entry_idx >= 0 else None,
                'exit_date': common_dates[i],
                'entry_price': sleeve.v_entry,
                'exit_price': vo,
                'pnl_pct': (vo - sleeve.v_entry) / sleeve.v_entry * 100.0 if sleeve.v_entry else 0.0,
                'exit_reason': sleeve.v_exit_rsn,
            })
            sleeve.v_shares = 0.0
            sleeve.v_entry = 0.0
            sleeve.v_stop = 0.0
            sleeve.margin_debt = 0.0
            sleeve.cash = 0.0
            do = opens[defn][i] * ratio[defn][i]
            sleeve.d_shares = proceeds / do if do > 0 else 0.0
            sleeve.d_entry = do
            sleeve.d_entry_idx = i
            sleeve.state = 'defensive'

        elif target == 'cash':
            do = opens[defn][i] * ratio[defn][i]
            proceeds = sleeve.d_shares * do
            sleeve.trades.append({
                'type': 'defensive',
                'entry_date': common_dates[sleeve.d_entry_idx] if sleeve.d_entry_idx >= 0 else None,
                'exit_date': common_dates[i],
                'entry_price': sleeve.d_entry,
                'exit_price': do,
                'pnl_pct': (do - sleeve.d_entry) / sleeve.d_entry * 100.0 if sleeve.d_entry else 0.0,
                'exit_reason': 'def_stop(18%)',
            })
            sleeve.cash = proceeds
            sleeve.d_shares = 0.0
            sleeve.d_entry = 0.0
            sleeve.d_entry_idx = -1
            sleeve.state = 'cash'

    def phase_3_mark(sleeve, i):
        veh, defn = sleeve.veh_t, sleeve.def_t
        if sleeve.state == 'vehicle':
            sleeve.equity = sleeve.v_shares * adj[veh][i] + sleeve.cash - sleeve.margin_debt
        elif sleeve.state == 'defensive':
            sleeve.equity = sleeve.d_shares * adj[defn][i] + sleeve.cash
        else:
            sleeve.equity = sleeve.cash

    def phase_4_pyramid_signal(sleeve, i):
        if sleeve.state != 'vehicle':
            return
        veh = sleeve.veh_t
        if sleeve.v_entry <= 0:
            return
        raw_gain = adj[veh][i] / sleeve.v_entry - 1.0
        if enable_pyr1 and not sleeve.pyramid1_done and not sleeve.pyramid1_pending \
                and raw_gain >= PYR_THRESH:
            sleeve.pyramid1_pending = True
            sleeve.pyramid1_pmp = get_pmp(vix[i])
            sleeve.pyramid1_eq = sleeve.equity
        if enable_pyr2 and sleeve.pyramid1_done and not sleeve.pyramid2_done \
                and not sleeve.pyramid2_pending \
                and raw_gain >= PYR2_THRESH and vix[i] < 20.0:
            sleeve.pyramid2_pending = True
            sleeve.pyramid2_eq = sleeve.equity

    def phase_5_rebalance(i):
        nonlocal gld_shares, gld_equity
        if not enable_rebal:
            return
        if i == 0:
            return
        if year_of(common_dates[i]) <= year_of(common_dates[i - 1]):
            return
        # Phase 3 totals
        total_eq = sum(s.equity for s in sleeves) + gld_equity
        eq_target = total_eq * EQ_FRAC
        gld_target = total_eq * GLD_FRAC
        for s in sleeves:
            veh, defn = s.veh_t, s.def_t
            if s.state == 'vehicle':
                s.v_shares = eq_target / adj[veh][i]
                s.v_stop = adj[veh][i] * SL_MULT
                s.margin_debt = 0.0
                s.cash = 0.0
                s.pyramid1_pending = False
                s.pyramid2_pending = False
            elif s.state == 'defensive':
                s.d_shares = eq_target / adj[defn][i]
            else:
                s.cash = eq_target
            s.equity = eq_target
        gld_shares = gld_target / adj['GLD'][i]
        gld_equity = gld_target
        rebal_events.append({
            'date': common_dates[i],
            'total': total_eq,
        })

    def phase_7_signals(sleeve, i):
        if i < MIN_IDX:
            return
        sig_t, veh_t, defn_t = sleeve.sig_t, sleeve.veh_t, sleeve.def_t
        w_prev, w_cur = wma[sig_t][i - 1], wma[sig_t][i]
        s_prev, s_cur = sma[sig_t][i - 1], sma[sig_t][i]
        if w_prev is None or w_cur is None or s_prev is None or s_cur is None:
            return
        cab = (w_prev <= s_prev) and (w_cur > s_cur)
        cbl = (w_prev >= s_prev) and (w_cur < s_cur)

        if sleeve.next_state is not None:
            return

        if sleeve.state == 'vehicle':
            a = adj[veh_t][i]
            rsn = None
            if a >= sleeve.v_entry * TP_MULT:
                rsn = 'take_profit'
            elif a <= sleeve.v_stop:
                rsn = 'stop_loss(12%)'
                sleeve.cooldown = COOLDOWN_BARS
            elif hvol[sig_t][i] is not None and hvol[sig_t][i] >= VOL_EXIT_THRESH:
                rsn = 'vol_exit'
            elif cbl:
                rsn = 'wma_cross_below'
            if rsn:
                sleeve.v_exit_rsn = rsn
                sleeve.wma_was_below = False
                sleeve.next_state = 'defensive'
                sleeve.pyramid1_pending = False
                sleeve.pyramid2_pending = False
            return

        if sleeve.state == 'defensive':
            if adj[defn_t][i] <= sleeve.d_entry * DEF_STOP_MULT:
                sleeve.cooldown = COOLDOWN_BARS
                sleeve.next_state = 'cash'
                sleeve.trades  # no trade log for defensive
                return

        # Latch logic (state == cash or defensive, next_state is None)
        if w_cur < s_cur:
            sleeve.wma_was_below = True
            sleeve.entry_eligible = False
        if cab and sleeve.wma_was_below:
            sleeve.entry_eligible = True
            sleeve.wma_was_below = False
        if sleeve.entry_eligible and w_cur < s_cur:
            sleeve.entry_eligible = False
            sleeve.wma_was_below = True

        if (sleeve.entry_eligible
                and hvol[sig_t][i] is not None and hvol[sig_t][i] <= VOL_ENTRY_MAX
                and w_cur > s_cur
                and sleeve.cooldown == 0
                and i + 1 < n):
            sleeve.next_state = 'vehicle'
            sleeve.entry_eligible = False
            sleeve.wma_was_below = False

    year_changes = []
    for i in range(n):
        # Phase 1A: pyramid fills at open[i]
        for s in sleeves:
            phase_1a_pyramid(s, i)
        # Phase 1B: state transitions at open[i]
        for s in sleeves:
            phase_1b_transition(s, i)
        # Phase 2: cooldown decrement
        for s in sleeves:
            if s.cooldown > 0:
                s.cooldown -= 1
        # Phase 3: mark to market
        for s in sleeves:
            phase_3_mark(s, i)
        if enable_gld:
            gld_equity = gld_shares * adj['GLD'][i]
        # Phase 4: pyramid signal detection
        for s in sleeves:
            phase_4_pyramid_signal(s, i)
        # Phase 5: annual rebalance
        if i > 0 and year_of(common_dates[i]) > year_of(common_dates[i - 1]):
            year_changes.append(common_dates[i])
        phase_5_rebalance(i)
        # Phase 6: record total equity
        total = sum(s.equity for s in sleeves) + (gld_equity if enable_gld else 0.0)
        equity_curve.append(total)
        # Phase 7: entry/exit signals
        for s in sleeves:
            phase_7_signals(s, i)

    # Step 6: end-of-data close-out (for trade log only)
    last_i = n - 1
    for s in sleeves:
        if s.state == 'vehicle' and s.v_entry > 0:
            last = adj[s.veh_t][last_i]
            s.trades.append({
                'type': 'vehicle',
                'entry_date': common_dates[s.v_entry_idx] if s.v_entry_idx >= 0 else None,
                'exit_date': common_dates[last_i],
                'entry_price': s.v_entry,
                'exit_price': last,
                'pnl_pct': (last - s.v_entry) / s.v_entry * 100.0,
                'exit_reason': 'end_of_data',
            })
        elif s.state == 'defensive' and s.d_shares > 0:
            last = adj[s.def_t][last_i]
            s.trades.append({
                'type': 'defensive',
                'entry_date': common_dates[s.d_entry_idx] if s.d_entry_idx >= 0 else None,
                'exit_date': common_dates[last_i],
                'entry_price': s.d_entry,
                'exit_price': last,
                'pnl_pct': (last - s.d_entry) / s.d_entry * 100.0 if s.d_entry else 0.0,
                'exit_reason': 'end_of_data',
            })

    return {
        'equity_curve': equity_curve,
        'sleeves': sleeves,
        'year_changes': year_changes,
        'rebal_events': rebal_events,
        'gld_shares': gld_shares,
        'gld_equity': gld_equity,
    }


def compute_metrics(equity_curve, common_dates):
    from datetime import date
    d0 = date.fromisoformat(common_dates[0])
    d1 = date.fromisoformat(common_dates[-1])
    years = (d1 - d0).days / 365.25
    final_eq = equity_curve[-1]
    cagr = (final_eq / TOTAL_CAPITAL) ** (1.0 / years) - 1.0
    peak = TOTAL_CAPITAL
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    rets = []
    prev = TOTAL_CAPITAL
    for e in equity_curve:
        rets.append((e - prev) / prev if prev else 0.0)
        prev = e
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    sharpe = (mu / sd) * math.sqrt(252) if sd else 0.0
    return {
        'years': years,
        'final_equity': final_eq,
        'cagr': cagr,
        'max_dd': max_dd,
        'sharpe': sharpe,
    }


def verify_step1_step2(data):
    print('=' * 60)
    print('STEP 1 & 2 — Data load + indicators')
    print('=' * 60)
    cd = data['common_dates']
    n = data['n']
    adj = data['adj']
    print(f"n (common bars)         : {n}  (target 6594)")
    print(f"common_dates[0]         : {cd[0]}  (target 2000-01-03)")
    print(f"common_dates[-1]        : {cd[-1]}  (target 2026-03-23)")
    print(f"adj['GLD'][0]           : {adj['GLD'][0]:.4f}  (target 2.7908)")
    print(f"adj['TQQQ'][0]          : {adj['TQQQ'][0]:.4f}  (target 72.5115)")
    print(f"adj['SPXL'][0]          : {adj['SPXL'][0]:.4f}  (target 19.9793)")
    print(f"adj['QQQ'][0]           : {adj['QQQ'][0]:.4f}  (target 80.1346)")
    print(f"adj['SPY'][0]           : {adj['SPY'][0]:.4f}  (target 91.6138)")
    print(f"GLD initial shares      : {10000 / adj['GLD'][0]:.4f}  (target 3583.1705)")

    wma, sma, hvol, atr, vix = data['wma'], data['sma'], data['hvol'], data['atr'], data['vix']
    print(f"WMA['QQQ'][19] is real  : {wma['QQQ'][19] is not None};  [18] is None: {wma['QQQ'][18] is None}")
    print(f"SMA['QQQ'][199] is real : {sma['QQQ'][199] is not None};  [198] is None: {sma['QQQ'][198] is None}")
    print(f"HVol['QQQ'][20] is real : {hvol['QQQ'][20] is not None};  [19] is None: {hvol['QQQ'][19] is None}")
    idx = {d: i for i, d in enumerate(cd)}
    if '2008-10-10' in idx:
        i = idx['2008-10-10']
        print(f"HVol['QQQ'] 2008-10-10  : {hvol['QQQ'][i]:.1f}%  (target 51.7%)")
        print(f"ATR['TQQQ'] 2008-10-10  : {atr['TQQQ'][i]:.2f}%  (target 20.33%)")
        print(f"ATR['SPXL'] 2008-10-10  : {atr['SPXL'][i]:.2f}%  (target 25.13%)")
        print(f"VIX 2008-10-10          : {vix[i]:.2f}    (target 69.95)")
    if '2017-08-15' in idx:
        i = idx['2017-08-15']
        print(f"HVol['QQQ'] 2017-08-15  : {hvol['QQQ'][i]:.1f}%  (target 10.9%)")
    if '2020-03-16' in idx:
        i = idx['2020-03-16']
        print(f"VIX 2020-03-16          : {vix[i]:.2f}    (target 82.69)")


def summarize_sleeve(sleeve, label):
    reasons = {}
    for t in sleeve.trades:
        reasons[t['exit_reason']] = reasons.get(t['exit_reason'], 0) + 1
    veh_trades = [t for t in sleeve.trades if t['type'] == 'vehicle']
    print(f"{label}: trade_rows={len(sleeve.trades)}  vehicle_trades={len(veh_trades)}  "
          f"reasons={reasons}")


def report_metrics(label, equity_curve, common_dates, starting):
    from datetime import date
    d0 = date.fromisoformat(common_dates[0])
    d1 = date.fromisoformat(common_dates[-1])
    years = (d1 - d0).days / 365.25
    final_eq = equity_curve[-1]
    cagr = (final_eq / starting) ** (1.0 / years) - 1.0
    peak = starting
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    rets = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        rets.append((equity_curve[i] - prev) / prev if prev else 0.0)
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    sharpe = (mu / sd) * math.sqrt(252) if sd else 0.0
    print(f"  {label}: Final=${final_eq:,.0f}  CAGR={cagr*100:.2f}%  "
          f"MaxDD={max_dd*100:.2f}%  Sharpe={sharpe:.4f}")
    return {'final': final_eq, 'cagr': cagr, 'max_dd': max_dd, 'sharpe': sharpe}


def verify_step3f(data):
    print('=' * 60)
    print('STEP 3f — Sleeve isolation ($45K, no GLD, no rebal, no pyramid)')
    print('=' * 60)
    # QQQ isolation
    r = run_backtest(data, sleeves_to_run=('QQQ',), enable_gld=False,
                     enable_rebal=False, enable_pyr1=False, enable_pyr2=False)
    print("QQQ→TQQQ isolation (target: 37 rows, Final $10,412,846, CAGR 23.08%, MaxDD -45.18%, Sharpe 0.7874)")
    report_metrics('QQQ', r['equity_curve'], data['common_dates'], EQ_ALLOC)
    summarize_sleeve(r['sleeves'][0], '  QQQ')
    # Print first 3 vehicle trades
    veh = [t for t in r['sleeves'][0].trades if t['type'] == 'vehicle']
    print("  First 3 QQQ→TQQQ vehicle trades:")
    for t in veh[:3]:
        print(f"    {t['entry_date']} → {t['exit_date']}  {t['pnl_pct']:+.4f}%  {t['exit_reason']}")

    # SPY isolation
    r = run_backtest(data, sleeves_to_run=('SPY',), enable_gld=False,
                     enable_rebal=False, enable_pyr1=False, enable_pyr2=False)
    print("\nSPY→SPXL isolation (target: 37 rows, Final $4,613,615, CAGR 19.32%, MaxDD -45.92%, Sharpe 0.7320)")
    report_metrics('SPY', r['equity_curve'], data['common_dates'], EQ_ALLOC)
    summarize_sleeve(r['sleeves'][0], '  SPY')
    veh = [t for t in r['sleeves'][0].trades if t['type'] == 'vehicle']
    print("  First 3 SPY→SPXL vehicle trades:")
    for t in veh[:3]:
        print(f"    {t['entry_date']} → {t['exit_date']}  {t['pnl_pct']:+.4f}%  {t['exit_reason']}")


def verify_step4(data):
    print('=' * 60)
    print('STEP 4 — Full baseline (no pyramid)')
    print('=' * 60)
    r = run_backtest(data, enable_pyr1=False, enable_pyr2=False)
    print("Target: 76 trades, $33,858,674, CAGR 24.88%, MaxDD -39.65%, Sharpe 0.8209")
    report_metrics('Baseline', r['equity_curve'], data['common_dates'], TOTAL_CAPITAL)
    total_v = 0
    for s in r['sleeves']:
        veh = [t for t in s.trades if t['type'] == 'vehicle']
        total_v += len(veh)
        summarize_sleeve(s, f"  {s.name}")
    print(f"  Real vehicle trades total: {total_v}")
    print(f"  Rebalance events: {len(r['rebal_events'])}")
    for s in r['sleeves']:
        veh = [t for t in s.trades if t['type'] == 'vehicle']
        print(f"\n  First 5 {s.name}→{s.veh_t} vehicle trades:")
        for t in veh[:5]:
            print(f"    {t['entry_date']} → {t['exit_date']}  {t['pnl_pct']:+.4f}%  {t['exit_reason']}")
    print("\n  Rebalance spot checks:")
    yr_check = {'2001-01-02', '2010-01-04', '2020-01-02', '2026-01-02'}
    for ev in r['rebal_events']:
        if ev['date'] in yr_check:
            print(f"    {ev['date']} total=${ev['total']:,.0f}")


def verify_step5a(data):
    print('=' * 60)
    print('STEP 5a — Pyramid 1 only')
    print('=' * 60)
    r = run_backtest(data, enable_pyr1=True, enable_pyr2=False)
    print("Target: 28 pyr1 events (22 pmp1.30, 6 pmp1.10), 76 trades, $56,546,900, CAGR 27.35%")
    report_metrics('Pyr1', r['equity_curve'], data['common_dates'], TOTAL_CAPITAL)
    total_pyr1 = 0
    pmps = {}
    total_v = 0
    for s in r['sleeves']:
        total_pyr1 += len(s.pyr1_events)
        for e in s.pyr1_events:
            pmps[e['pmp']] = pmps.get(e['pmp'], 0) + 1
        veh = [t for t in s.trades if t['type'] == 'vehicle']
        total_v += len(veh)
    print(f"  Total pyr1 events: {total_pyr1}  by pmp: {pmps}")
    print(f"  Real vehicle trades: {total_v}")
    for s in r['sleeves']:
        if s.pyr1_events:
            e = s.pyr1_events[0]
            print(f"  First {s.name} pyr1 fill: {e['date']}  pmp={e['pmp']}")


def verify_step5b(data):
    print('=' * 60)
    print('STEP 5b — Pyramid 1 + Pyramid 2 (final system)')
    print('=' * 60)
    r = run_backtest(data, enable_pyr1=True, enable_pyr2=True)
    print("Target: 22 pyr2 events, 76 trades, $66,719,924, CAGR 28.15%, MaxDD -39.65%, Sharpe 0.8537")
    report_metrics('Final', r['equity_curve'], data['common_dates'], TOTAL_CAPITAL)
    tot_pyr1, tot_pyr2, tot_v = 0, 0, 0
    for s in r['sleeves']:
        tot_pyr1 += len(s.pyr1_events)
        tot_pyr2 += len(s.pyr2_events)
        veh = [t for t in s.trades if t['type'] == 'vehicle']
        tot_v += len(veh)
        print(f"  {s.name}: pyr1={len(s.pyr1_events)}  pyr2={len(s.pyr2_events)}  veh_trades={len(veh)}")
    print(f"  Totals: pyr1={tot_pyr1}  pyr2={tot_pyr2}  real_trades={tot_v}")
    for s in r['sleeves']:
        if s.pyr2_events:
            e = s.pyr2_events[0]
            print(f"  First {s.name} pyr2 fill: {e['date']}")


if __name__ == '__main__':
    data = load_all()
    verify_step1_step2(data)
    print()
    verify_step3f(data)
    print()
    verify_step4(data)
    print()
    verify_step5a(data)
    print()
    verify_step5b(data)
