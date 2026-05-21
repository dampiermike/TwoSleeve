#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized v1.1  —  Incremental Data Refresh
═══════════════════════════════════════════════════════════════════════════════

Updates the 6 EODHD JSON files that two_sleeve_daily_signal.py needs:

  QQQ, SPY            — real history (no splice)
  TQQQ, SPXL, GLD, BIL — SPLICED: synthetic pre-inception bars + real bars

Only bars on/after each file's latest existing date are fetched, and merged
by date. New real bars are appended; recent bars are refreshed in case the
provider revised them. The synthetic pre-inception bars are NEVER touched —
they sit decades before the fetch window, so the provider never returns them.

  ⚠ Never run a full re-fetch on the spliced tickers — it would drop their
    synthetic history. This script only ever does incremental appends.

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

# The 6 tickers v1.1 depends on. Spliced tickers carry synthetic history.
TICKERS  = ["QQQ", "TQQQ", "SPY", "SPXL", "GLD", "BIL"]
SPLICED  = {"TQQQ", "SPXL", "GLD", "BIL"}

TOKEN   = os.environ.get("EODHD_API_TOKEN")
TIMEOUT = 60.0
SLEEP   = 0.4          # politeness pause between requests
REFRESH_TAIL = 3       # also re-fetch this many trailing bars (catch revisions)


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


def update_ticker(ticker, end_date):
    """Incrementally update one ticker file. Returns a status string."""
    path = DATA_DIR / f"{ticker}_US.json"

    if not path.exists():
        # Never seed a spliced file from scratch — that would lose synthetic history.
        if ticker in SPLICED:
            return f"  {ticker:<5} ERROR — file missing; restore {path.name} from the repo " \
                   f"(spliced files must not be re-seeded)"
        return f"  {ticker:<5} ERROR — file missing: {path.name}"

    rows = json.load(open(path))
    by_date = {r["date"]: r for r in rows if isinstance(r, dict) and "date" in r}
    if not by_date:
        return f"  {ticker:<5} ERROR — {path.name} has no dated rows"

    latest = max(date.fromisoformat(d) for d in by_date)
    if latest >= end_date:
        return f"  {ticker:<5} up to date (latest {latest.isoformat()})"

    # Fetch from a few bars before `latest` so recent revisions are caught.
    start = latest - timedelta(days=REFRESH_TAIL)

    try:
        new_rows = fetch_history(f"{ticker}.US", start, end_date, TOKEN)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        return f"  {ticker:<5} HTTP error {code}"
    except requests.RequestException as exc:
        return f"  {ticker:<5} request failed: {exc}"

    if not new_rows:
        return f"  {ticker:<5} no data returned (latest stays {latest.isoformat()})"

    before = len(by_date)
    syn_before = sum(1 for r in by_date.values() if r.get("synthetic"))
    for nr in new_rows:
        d = nr.get("date")
        if not d:
            continue
        # Safety: never let a fetched row overwrite a synthetic bar.
        if d in by_date and by_date[d].get("synthetic"):
            continue
        by_date[d] = nr

    added = len(by_date) - before
    syn_after = sum(1 for r in by_date.values() if r.get("synthetic"))

    merged = [by_date[d] for d in sorted(by_date)]
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(merged, f, indent=2)
    tmp.replace(path)        # atomic write

    new_latest = max(date.fromisoformat(d) for d in by_date)
    tag = " [spliced — synthetic preserved]" if ticker in SPLICED else ""
    syn_note = "" if syn_before == syn_after else \
               f"  ⚠ synthetic count changed {syn_before}->{syn_after}"
    return (f"  {ticker:<5} +{added:>3} rows  ->  latest {new_latest.isoformat()}"
            f"{tag}{syn_note}")


def main():
    print()
    print("=" * 70)
    print(f"  TWO-SLEEVES v1.1  —  DATA REFRESH  —  {date.today().isoformat()}")
    print("=" * 70)

    if not TOKEN:
        print("\n  ERROR: EODHD_API_TOKEN is not set.")
        print("  Set it in your shell, e.g.  export EODHD_API_TOKEN=your_token")
        sys.exit(1)

    end_date = date.today()
    results = []
    for ticker in TICKERS:
        msg = update_ticker(ticker, end_date)
        print(msg, flush=True)
        results.append(msg)
        time.sleep(SLEEP)

    errors = [m for m in results if "ERROR" in m or "error" in m or "failed" in m]
    print("=" * 70)
    if errors:
        print(f"  COMPLETED WITH {len(errors)} PROBLEM(S) — review above before trading.")
        sys.exit(1)
    print("  All 6 data files refreshed. Run:  python3 two_sleeve_daily_signal.py")
    print("=" * 70)


if __name__ == "__main__":
    main()
