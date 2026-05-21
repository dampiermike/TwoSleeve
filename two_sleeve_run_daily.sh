#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  TwoSleeves Optimized v1.1 — Daily Runner
#  Step 1: refresh the 6 EODHD data files
#  Step 2: generate the daily signal
#  Step 3: notify — email (full report) + iMessage (short summary)
#  Output is tee'd to logs/daily-YYYY-MM-DD_HHMMSS.log
# ═══════════════════════════════════════════════════════════════════════════
set -o pipefail

# Run from this script's directory regardless of where it is invoked.
cd "$(dirname "$0")"

# Load credentials (EODHD_API_TOKEN, GOOGLE_EMAIL/APP_PASSWORD,
# PHOENIX_SMS_NUMBERS) if a profile defines them.
[ -f "$HOME/.bash_profile" ] && source "$HOME/.bash_profile"

# Pick an interpreter: project venv if present, else system python3.
if [ -x ".venv/bin/python3" ]; then
    PY=".venv/bin/python3"
else
    PY="python3"
fi

mkdir -p logs
TS="$(date '+%Y-%m-%d_%H%M%S')"
LOG="logs/daily-${TS}.log"

# ── Steps 1-2: refresh data, generate signal ─────────────────────────────────
# Runs in a subshell with `set -e` so the first failure aborts the pipeline;
# pipefail then propagates that status out through `tee`.
run_ok=1
(
    set -e
    echo "═══════════════════════════════════════════════════════════"
    echo "  TwoSleeves v1.1 — Daily Run — $(date)"
    echo "═══════════════════════════════════════════════════════════"
    echo
    echo "── Step 1: refresh EODHD data ──"
    "$PY" two_sleeve_update_data.py
    echo
    echo "── Step 2: daily signal ──"
    "$PY" two_sleeve_daily_signal.py
    echo
    echo "── Done — $(date) ──"
) 2>&1 | tee "$LOG" || run_ok=0

# ── Step 3: notify — email + iMessage (best-effort, never fails the run) ──────
if [ "$run_ok" -eq 1 ]; then
    "$PY" two_sleeve_notify.py ok "$LOG" || true
else
    "$PY" two_sleeve_notify.py fail "$LOG" || true
    exit 1
fi
