# TwoSleeves Optimized v1 — Build & Recreate Guide

How to recreate this project from scratch and reproduce the backtest results.

> **What this document is:** instructions to set up the directory, obtain data,
> run the backtest, and verify against the spec.
> **What it isn't:** the strategy spec itself. That's in
> [TwoSleeves_Optimized_Build_Guide_v1.md](TwoSleeves_Optimized_Build_Guide_v1.md).

---

## Final results (what you should reproduce)

| Metric | Target |
|---|---:|
| Final equity | **$35,448,247** |
| CAGR | **+25.10%** |
| Max drawdown | **−37.99%** |
| Sharpe ratio | **0.8373** |
| Real trades | **86** (38 QQQ + 48 SPY) |
| Bars | 6,594 |
| Period | 2000-01-03 → 2026-03-23 |

---

## Prerequisites

- **Python 3.9 or later** (stdlib only — no pip install required)
- About **15 MB free disk** for data files
- A terminal

Verify:

```bash
python3 --version    # must be 3.9+
```

No third-party packages. No virtual environment required. No API keys.
**No VectorVest data needed.**

---

## Directory structure to recreate

```
TwoSleeves/
├── README.md                                   ← this file
├── TwoSleeves_Optimized_Build_Guide_v1.md      ← strategy spec
├── TwoSleeves_Optimized_Build_Guide_v1.docx    ← strategy spec (Word)
├── backtest_two_sleeves_v1.py                  ← reference implementation
├── .gitignore
├── requirements.txt                            ← optional, mostly empty
└── json/
    ├── QQQ_US.json
    ├── TQQQ_US.json
    ├── SPY_US.json
    ├── SPXL_US.json
    └── GLD_US.json
```

The simulation script writes 3 CSV outputs on each run:

```
backtest_two_sleeves_v1_equity_curve.csv
backtest_two_sleeves_v1_trades.csv
backtest_two_sleeves_v1_rebalance_events.csv
```

---

## Step 1 — Create the directory

```bash
mkdir -p ~/Documents/Development/TwoSleeves/json
cd ~/Documents/Development/TwoSleeves
git init
```

---

## Step 2 — Obtain the data files

**Five JSON files** are required, formatted as EODHD-style daily bars:

```json
[
  { "date": "YYYY-MM-DD",
    "open":  ...,  "high": ...,  "low": ...,
    "close": ...,  "adjusted_close": ...,
    "volume": ... },
  ...
]
```

| File | Source convention | First bar required | Notes |
|---|---|---|---|
| `json/QQQ_US.json` | EODHD `QQQ.US` daily | 2000-01-03 | Real history only |
| `json/SPY_US.json` | EODHD `SPY.US` daily | 2000-01-03 | Real history only |
| `json/TQQQ_US.json` | EODHD `TQQQ.US` + synthetic splice | 2000-01-03 | Synthetic pre-2010-02-11 bars must have `"synthetic": true` |
| `json/SPXL_US.json` | EODHD `SPXL.US` + synthetic splice | 2000-01-03 | Synthetic pre-2008-11-05 bars must have `"synthetic": true` |
| `json/GLD_US.json` | EODHD `GLD.US` + synthetic splice | 2000-01-03 | Synthetic pre-2004-11-18 bars must have `"synthetic": true` |

### How to obtain these files

**Option A: Copy from an existing Oscillator workspace** (recommended if you have one)

```bash
SRC=~/Documents/Development/Oscillator/json
DST=~/Documents/Development/TwoSleeves/json
cp "$SRC/history/QQQ_US.json"  "$DST/"
cp "$SRC/history/SPY_US.json"  "$DST/"
cp "$SRC/spliced/TQQQ_US.json" "$DST/"
cp "$SRC/spliced/SPXL_US.json" "$DST/"
cp "$SRC/spliced/GLD_US.json"  "$DST/"
```

**Option B: Download from EODHD and splice yourself**

For QQQ and SPY, just download daily history from EODHD. They already cover
2000-01-03 onward as real data.

For TQQQ, SPXL, and GLD: you need to splice synthetic pre-inception bars onto
the real history. The synthetic series simulates a 3× daily-rebalanced ETF
on the underlying index with a ~10% annual cost drag (expense ratio + financing).

This project does **not** include the splice generator; the spliced files were
sourced from another internal project (Oscillator). If you need to rebuild the
splice from scratch:
- Use 3× daily compounding of the underlying's close-to-close returns
- Subtract ~0.04%/day cost drag (~10% annual)
- Anchor the synthetic series so its last synthetic bar's close is consistent
  with the real ETF's first open
- Mark every synthetic bar `"synthetic": true`

Reference splice builders in the FourSleeve workspace:
- `FourSleeve/build_synthetic_udow.py`
- `FourSleeve/build_synthetic_tecl.py`

These can be adapted for TQQQ/SPXL/GLD if needed.

### Verification of data load (Step 1 checkpoint from the spec)

After placing the files, verify the first bar values match the spec:

| Check | Expected |
|---|---|
| n (common bars) | 6,594 |
| common_dates[0] | '2000-01-03' |
| common_dates[-1] | '2026-03-23' |
| adj['GLD'][0] | 2.7908 |
| adj['TQQQ'][0] | 72.5115 |
| adj['SPXL'][0] | 19.9793 |
| adj['QQQ'][0] | 80.1346 |
| adj['SPY'][0] | 91.6138 |

Quick sanity check from the command line:

```bash
python3 -c "
import json
for t in ['QQQ', 'SPY', 'TQQQ', 'SPXL', 'GLD']:
    d = json.load(open(f'json/{t}_US.json'))
    d.sort(key=lambda r: r['date'])
    d = [r for r in d if r['date'] >= '2000-01-01']
    print(f'{t:<5} first={d[0][\"date\"]} adj={d[0][\"adjusted_close\"]:.4f}  bars={len(d)}')
"
```

Expected output (any of the closes can differ slightly from these to the 5th
decimal place — only the spec's 4-decimal checkpoints must match):

```
QQQ   first=2000-01-03 adj=80.1346  bars=6607
SPY   first=2000-01-03 adj=91.6138  bars=6607
TQQQ  first=2000-01-03 adj=72.5115  bars=6607
SPXL  first=2000-01-03 adj=19.9793  bars=6607
GLD   first=2000-01-03 adj=2.7908   bars=6607
```

(Each ticker has 6,607 bars individually; the *intersection* across all five
gives 6,594 bars — the strategy's working window.)

---

## Step 3 — Copy in the spec and the backtest

If you're recreating from this workspace, copy:

```bash
cp <source>/TwoSleeves_Optimized_Build_Guide_v1.md   .
cp <source>/TwoSleeves_Optimized_Build_Guide_v1.docx .
cp <source>/backtest_two_sleeves_v1.py               .
```

If you're rebuilding from the spec alone, implement the strategy following
[TwoSleeves_Optimized_Build_Guide_v1.md](TwoSleeves_Optimized_Build_Guide_v1.md)
step-by-step. The spec is self-contained and includes every parameter, phase
order, and PRECISE checkpoint.

---

## Step 4 — Run the backtest

```bash
cd ~/Documents/Development/TwoSleeves
python3 backtest_two_sleeves_v1.py
```

Expected runtime: **under 5 seconds** on a modern laptop.

---

## Step 5 — Verify the output

The script prints a self-checking results table. **All six PRECISE rows must
show ✓**:

```
================================================================================
  RESULT  vs  SPEC TARGETS (TwoSleeves_Optimized_Build_Guide_v1.md)
================================================================================
  Final equity                  $   35,448,247  target       $   35,448,247  ✓
  CAGR                                 +25.10%  target              +25.10%  ✓
  Max Drawdown                         -37.99%  target              -37.99%  ✓
  Sharpe                                0.8373  target               0.8373  ✓
  Real trades                               86  target                   86  ✓
  Bars                                    6594  target                 6594  ✓
```

If any row shows ✗, the data files or the implementation has diverged from
spec. Common causes:

- HVol using population variance (÷N) instead of sample variance (÷N−1)
- Same-bar fills instead of next-bar opens
- GLD marked to market after rebalance reads equity (Phase 4 ordering)
- Cooldown applied to wrong exit types
- Sleeve params swapped (QQQ should be 10/175, SPY should be 5/200)

Full diagnosis list in Appendix A of the strategy spec.

### Output files

Three CSVs land in the project root:

- `backtest_two_sleeves_v1_equity_curve.csv` — 6,594 rows, daily portfolio
  equity + per-sleeve breakdown
- `backtest_two_sleeves_v1_trades.csv` — 86 rows, full entry/exit log
- `backtest_two_sleeves_v1_rebalance_events.csv` — 26 rows, annual rebalance
  deltas

---

## Step 6 — Optional: archive

If everything verifies, commit a snapshot:

```bash
git add .gitignore *.md *.py *.docx json/
git commit -m "TwoSleeves Optimized v1 — baseline working build"
```

The CSV outputs are gitignored by default (they regenerate on every run).

---

## What's deliberately NOT in v1

| Feature | Status | Where it lives |
|---|---|---|
| Pyramid sizing (pyr1+pyr2, VIX-scaled, broker-capped) | Deferred to v2 | Original v3 spec only |
| Third sleeve (SMH, DIA, XLK) | Tested and rejected | Appendix B of v1 spec |
| ATR / VIX entry sizing | Tested and rejected | Appendix B of v1 spec |
| Trailing stops, regime filter, circuit breaker | Tested and rejected | Appendix B of v1 spec |
| VectorVest signals or data | Not used, never tested | n/a |

If you want to revisit any of these, the reference experiments are in the
sibling `FourSleeve/` workspace where they were originally explored.

---

## Quick reference card

```
# What you build:
QQQ → TQQQ sleeve     45%   WMA=10  SMA=175
SPY → SPXL sleeve     45%   WMA=5   SMA=200
GLD safety sleeve     10%   buy & hold

# What you get:
$100K → $35,448,247    +25.10% CAGR    -37.99% MaxDD    0.8373 Sharpe
86 trades over 26.22 years (2000-01-03 → 2026-03-23)

# How to run:
python3 backtest_two_sleeves_v1.py
```

---

*TwoSleeves Optimized v1 · Build Reproduction Guide · Backtest does not guarantee future results*
