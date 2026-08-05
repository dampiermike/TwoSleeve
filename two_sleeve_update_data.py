#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized — Incremental Data Refresh
═══════════════════════════════════════════════════════════════════════════════

Updates the 10 EODHD JSON files used by the TwoSleeves family:

  QQQ.US,  SPY.US             — real history (no splice)
  TQQQ.US, SPXL.US, GLD.US, BIL.US — SPLICED: synthetic pre-inception + real
  TLT.US                      — SPLICED (synthetic 2000-01..2002-07); v1.3's
                                core-sleeve defensive holding
  XLE.US,  XLV.US             — real history (no splice); v1.3 sector sleeves
  VIX.INDX                    — VIX index (real history, no splice; needed
                                by v1.2's VIX-MA spike-exit overlay)

Only bars on/after each file's latest existing date are fetched, and merged
by date. New real bars are appended; recent bars are refreshed in case the
provider revised them. The synthetic pre-inception bars are NEVER touched —
they sit decades before the fetch window, so the provider never returns them.

  ⚠ Never run a full re-fetch on the spliced tickers — it would drop their
    synthetic history. This script only ever does incremental appends.

Filenames are derived from the EODHD symbol by replacing `.` with `_`:
    BIL.US  -> BIL_US.json
    VIX.INDX -> VIX_INDX.json

Requires:  EODHD_API_TOKEN environment variable
           `requests` package  (pip install requests>=2.32.0)

Usage:     python3 two_sleeve_update_data.py
"""

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: the 'requests' package is required.  pip install requests>=2.32.0",
          file=sys.stderr)
    sys.exit(1)

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR  = WORKSPACE / "json"

# EODHD symbols (filenames derive from these via sanitize: '.' -> '_')
SYMBOLS = [
    "QQQ.US", "TQQQ.US",
    "SPY.US", "SPXL.US",
    "GLD.US",
    "BIL.US",
    "VIX.INDX",         # VIX index — needed by v1.2's spike-exit overlay
    # v1.3 candidate additions
    "TLT.US",           # core sleeve's defensive holding
    "XLE.US",           # energy sleeve (signal + vehicle, unlevered)
    "XLV.US",           # healthcare sleeve (signal + vehicle, unlevered)
]
# Spliced files carry synthetic pre-inception bars and must never be re-seeded.
# TLT is spliced too: its 2000-01-03..2002-07-25 bars are synthetic.
SPLICED = {"TQQQ.US", "SPXL.US", "GLD.US", "BIL.US", "TLT.US"}

TOKEN   = os.environ.get("EODHD_API_TOKEN")
TIMEOUT = 60.0
SLEEP   = 0.4          # politeness pause between requests
REFRESH_TAIL = 3       # also re-fetch this many trailing bars (catch revisions)


def sanitize(symbol):
    """EODHD symbol -> filename basename (BIL.US -> BIL_US, VIX.INDX -> VIX_INDX)."""
    return symbol.replace("/", "_").replace(".", "_")


def fetch_history(symbol, start, end, token):
    """EODHD table.csv endpoint — months are zero-indexed."""
    url = (
        "https://eodhd.com/api/table.csv"
        f"?s={symbol}"
        f"&a={start.month-1}&b={start.day}&c={start.year}"
        f"&d={end.month-1}&e={end.day}&f={end.year}"
        f"&g=d&api_token={token}&fmt=json"
    )
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def update_symbol(symbol, end_date):
    """Incrementally update one symbol's file. Returns a status string."""
    name = sanitize(symbol)
    path = DATA_DIR / f"{name}.json"
    label = name.replace("_", ".").ljust(9)   # display: BIL.US, VIX.INDX

    if not path.exists():
        if symbol in SPLICED:
            return f"  {label} ERROR — file missing; restore {path.name} from the repo " \
                   f"(spliced files must not be re-seeded)"
        return f"  {label} ERROR — file missing: {path.name}"

    rows = json.load(open(path))
    by_date = {r["date"]: r for r in rows if isinstance(r, dict) and "date" in r}
    if not by_date:
        return f"  {label} ERROR — {path.name} has no dated rows"

    latest = max(date.fromisoformat(d) for d in by_date)
    if latest >= end_date:
        return f"  {label} up to date (latest {latest.isoformat()})"

    start = latest - timedelta(days=REFRESH_TAIL)

    try:
        new_rows = fetch_history(symbol, start, end_date, TOKEN)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        return f"  {label} HTTP error {code}"
    except requests.RequestException as exc:
        return f"  {label} request failed: {exc}"

    if not new_rows:
        return f"  {label} no data returned (latest stays {latest.isoformat()})"

    before = len(by_date)
    syn_before = sum(1 for r in by_date.values() if r.get("synthetic"))
    for nr in new_rows:
        d = nr.get("date")
        if not d:
            continue
        if d in by_date and by_date[d].get("synthetic"):
            continue
        by_date[d] = nr

    added = len(by_date) - before
    syn_after = sum(1 for r in by_date.values() if r.get("synthetic"))

    merged = [by_date[d] for d in sorted(by_date)]
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(merged, f, indent=2)
    tmp.replace(path)

    new_latest = max(date.fromisoformat(d) for d in by_date)
    tag = " [spliced — synthetic preserved]" if symbol in SPLICED else ""
    syn_note = "" if syn_before == syn_after else \
               f"  ⚠ synthetic count changed {syn_before}->{syn_after}"
    return (f"  {label} +{added:>3} rows  ->  latest {new_latest.isoformat()}"
            f"{tag}{syn_note}")


def main():
    print()
    print("=" * 72)
    print(f"  TWO-SLEEVES  —  DATA REFRESH  —  {date.today().isoformat()}")
    print("=" * 72)

    if not TOKEN:
        print("\n  ERROR: EODHD_API_TOKEN is not set.")
        print("  Set it in your shell, e.g.  export EODHD_API_TOKEN=your_token")
        sys.exit(1)

    end_date = date.today()
    results = []
    for symbol in SYMBOLS:
        msg = update_symbol(symbol, end_date)
        print(msg, flush=True)
        results.append(msg)
        time.sleep(SLEEP)

    errors = [m for m in results if "ERROR" in m or "error" in m or "failed" in m]
    print("=" * 72)
    if errors:
        print(f"  COMPLETED WITH {len(errors)} PROBLEM(S) — review above before trading.")
        sys.exit(1)
    print(f"  All {len(SYMBOLS)} data files refreshed. "
          f"Run:  python3 two_sleeve_daily_signal_v1_3.py")
    print("=" * 72)


if __name__ == "__main__":
    main()
