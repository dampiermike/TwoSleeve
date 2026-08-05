#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  TwoSleeves Optimized v1.1  —  Daily Notifier

  Sends the daily-run result two ways:
    • email    — the full signal report (or a failure tail) to GOOGLE_EMAIL
    • iMessage — a short summary to every number in PHOENIX_SMS_NUMBERS

  Invoked by two_sleeve_run_daily.sh:
      python3 two_sleeve_notify.py ok   logs/daily-YYYY-MM-DD_HHMMSS.log
      python3 two_sleeve_notify.py fail logs/daily-YYYY-MM-DD_HHMMSS.log

  Best-effort: any send failure is logged to stderr but never raises, so a
  notification problem can't fail the daily run.

  Credentials (from ~/.bash_profile, sourced by the runner):
      GOOGLE_EMAIL, GOOGLE_APP_PASSWORD   — Gmail SMTP
      PHOENIX_SMS_NUMBERS                 — comma-separated, e.g. +1225...,+1303...
      PHOENIX_SMS_FORCE                   — numbers to send as green-bubble SMS
                                            instead of iMessage (optional)
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import smtplib
import subprocess
import sys
from datetime import date
from email.mime.text import MIMEText

GMAIL_USER  = os.environ.get("GOOGLE_EMAIL", "")
GMAIL_PASS  = os.environ.get("GOOGLE_APP_PASSWORD", "")
SMS_NUMBERS = [n.strip() for n in os.environ.get("PHOENIX_SMS_NUMBERS", "").split(",") if n.strip()]
SMS_FORCE   = {n.strip() for n in os.environ.get("PHOENIX_SMS_FORCE", "").split(",") if n.strip()}


V13_TAG = "V13_SUMMARY:"


def extract_report(log_text: str) -> str:
    """Pull the clean daily-signal report out of the full run log.

    Spans Step 2 (live v1.2) through Step 2b (v1.3 candidate), so the email
    carries both. The machine-readable V13_SUMMARY line is stripped — it is
    for build_summary(), not for the reader.
    """
    marker, end = "── Step 2: daily signal ──", "── Done"
    if marker in log_text:
        body = log_text.split(marker, 1)[1]
        if end in body:
            body = body.split(end, 1)[0]
    else:
        body = log_text
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith(V13_TAG)]
    return "\n".join(lines).strip("\n")


def extract_v13(log_text: str) -> str:
    """The v1.3 candidate's one-line summary, or '' if it did not run."""
    for ln in log_text.splitlines():
        s = ln.strip()
        if s.startswith(V13_TAG):
            return s[len(V13_TAG):].strip()
    return ""


def build_summary(report: str, today: str, v13: str = "") -> tuple[str, str]:
    """Return (subject, sms_body) from the report's PENDING TRADES block.

    The subject and headline come from the LIVE v1.2 signal only — v1.3 is a
    candidate and must never drive the alert. Its call is appended as a
    clearly-labelled second line so it can be watched over time.
    """
    pending: list[str] = []
    stale = ""
    capture = False
    for ln in report.splitlines():
        if "DATA IS" in ln and "OLD" in ln:
            stale = ln.strip()
        if "PENDING TRADES" in ln:
            capture = True
            continue
        if capture:
            s = ln.strip()
            if s.startswith("─"):     # divider under the heading
                continue
            if not s:                 # blank line ends the block
                break
            pending.append(s)

    no_trades = (not pending) or any("No trades" in p for p in pending)
    if no_trades:
        verb = "No trades — hold all positions"
        subject = f"TwoSleeves {today}: No trades"
    else:
        trades = [p for p in pending if "→" in p]
        verb = " | ".join(trades) if trades else " | ".join(pending)
        subject = f"TwoSleeves {today}: TRADE SIGNAL"

    sms = f"TwoSleeves {today}\n{verb}"
    if stale:
        sms += f"\n{stale}"
    if v13:
        sms += f"\n[v1.3 candidate, not live] {v13}"
    return subject, sms


def send_email(subject: str, body: str) -> None:
    if not (GMAIL_USER and GMAIL_PASS):
        print("notify: GOOGLE_EMAIL/GOOGLE_APP_PASSWORD not set — skipping email",
              file=sys.stderr)
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, [GMAIL_USER], msg.as_string())
        print(f"notify: email sent → {GMAIL_USER}")
    except Exception as e:
        print(f"notify: email failed — {e}", file=sys.stderr)


def send_imessage(numbers: list[str], body: str) -> None:
    """Send a short message via Messages.app (Continuity / paired iPhone)."""
    for num in numbers:
        service = "SMS" if num in SMS_FORCE else "iMessage"
        # `service` is injected as a bare AppleScript enum (iMessage / SMS).
        script = f'''
on run argv
    set targetNumber to "{num}"
    set msgBody to (item 1 of argv)
    tell application "Messages"
        set targetBuddy to participant targetNumber of (first service whose service type = {service})
        send msgBody to targetBuddy
    end tell
end run
'''
        try:
            subprocess.run(["osascript", "-e", script, body],
                           check=True, capture_output=True)
            print(f"notify: iMessage sent → {num} ({service})")
        except subprocess.CalledProcessError as e:
            print(f"notify: iMessage to {num} failed — {e.stderr.decode().strip()}",
                  file=sys.stderr)
        except Exception as e:
            print(f"notify: iMessage to {num} failed — {e}", file=sys.stderr)


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("ok", "fail"):
        print("usage: two_sleeve_notify.py <ok|fail> <logfile>", file=sys.stderr)
        return 2

    status, log_path = sys.argv[1], sys.argv[2]
    today = date.today().isoformat()

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            log_text = f.read()
    except Exception as e:
        log_text = f"(could not read log {log_path}: {e})"

    if status == "ok":
        report = extract_report(log_text)
        subject, sms = build_summary(report, today, extract_v13(log_text))
        send_email(subject, report)
    else:
        tail = "\n".join(log_text.splitlines()[-50:])
        subject = f"❌ TwoSleeves daily FAILED — {today}"
        report = (f"TwoSleeves v1.1 daily run FAILED ({today}).\n"
                  f"Log: {log_path}\n\n─── last 50 log lines ───\n{tail}")
        sms = f"TwoSleeves {today}\n❌ Daily run FAILED — check logs"
        send_email(subject, report)

    if SMS_NUMBERS:
        send_imessage(SMS_NUMBERS, sms)
    else:
        print("notify: PHOENIX_SMS_NUMBERS empty — skipping iMessage", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
