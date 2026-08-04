#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  TwoSleeves Optimized v1.1 — Daily Runner
#  Step 1: refresh the 6 EODHD data files
#  Step 2: generate the daily signal
#  Step 3: commit the refreshed json/ data and push to origin/main
#  Step 4: notify — email (full report) + iMessage (short summary)
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

# ── Step 3: commit refreshed data and push ───────────────────────────────────
# Runs only after a clean data+signal run. Stages json/ only — backtest CSVs and
# code stay under manual control. Best-effort: any git failure is logged and
# warned about but never fails the daily run, since the signal already produced.
# Runs before Step 4 so that git warnings land in $LOG and reach the email.
#
#   GIT_TERMINAL_PROMPT=0    never block on a credential prompt under launchd
#   credential.helper reset  drop the system-level osxkeychain helper, which
#                            can't prompt headlessly and logs errSecInteraction
#                            (-25308) noise before ~/.gitconfig's `store` wins
#   http.lowSpeed*           abort a stalled transfer instead of hanging
#   pull --rebase --autostash  replay our data commit on top of origin/main, and
#                            shelve/restore any unrelated dirty files around it
if [ "$run_ok" -eq 1 ]; then
    {
        echo
        echo "── Step 3: commit data to git ──"
        if ! git rev-parse --git-dir >/dev/null 2>&1; then
            echo "Not a git repository — skipping."
        else
            export GIT_TERMINAL_PROMPT=0
            GIT="git -c credential.helper= -c credential.helper=store
                     -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30"

            $GIT add -A json
            if $GIT diff --cached --quiet -- json; then
                echo "No data changes to commit."
            elif ! $GIT commit -q -m "Daily data update — $(date '+%Y-%m-%d')" -- json; then
                echo "WARNING: commit failed — data left uncommitted."
            else
                echo "Committed: $($GIT log -1 --oneline)"

                # Sync with origin before pushing. On conflict, abort cleanly and
                # leave the commit local rather than leaving a half-rebased tree.
                if ! $GIT pull --rebase --autostash origin main; then
                    $GIT rebase --abort 2>/dev/null
                    echo "WARNING: rebase onto origin/main failed (conflict?)."
                    echo "         Commit is local only — reconcile by hand."
                elif $GIT push origin HEAD:main; then
                    echo "Pushed to origin/main."
                else
                    echo "WARNING: push failed — commit is local only."
                fi
            fi
        fi
        echo "── Done — $(date) ──"
    } 2>&1 | tee -a "$LOG"
fi

# ── Step 4: notify — email + iMessage (best-effort, never fails the run) ──────
if [ "$run_ok" -eq 1 ]; then
    "$PY" two_sleeve_notify.py ok "$LOG" || true
else
    "$PY" two_sleeve_notify.py fail "$LOG" || true
    exit 1
fi
