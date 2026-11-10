#!/usr/bin/env python3
"""Email an HRMS operations alert. Standard library only, so it runs on the VPS host itself.

Two callers:
  * infra/monitoring/hrms_monitor.sh pipes its JSON report on stdin (HRMS_ALERT_COMMAND) when a check
    fails. The subject names the failing checks. The same set of failing checks is not re-sent for
    ALERT_REPEAT_HOURS, because the monitor runs every 5 minutes and would otherwise send ~12 mails/hour.
  * systemd's hrms-alert@.service pipes a unit's recent journal with --subject when that unit fails
    (e.g. the backup). Always sent.

Configuration: /etc/hrms-alerts/smtp.env (root, 600), KEY=VALUE lines:
  ALERT_SMTP_HOST=smtp.gmail.com  ALERT_SMTP_PORT=587  ALERT_SMTP_USER=<gmail address>
  ALERT_SMTP_PASSWORD=<Google app password>  ALERT_TO=<recipient>  ALERT_REPEAT_HOURS=6
Docs: docs/deployment/BACKUPS_GOOGLE_DRIVE.md ("Alerts").
"""

import argparse
import hashlib
import json
import os
import smtplib
import socket
import sys
import time
from email.message import EmailMessage
from pathlib import Path

CONFIG = Path(os.environ.get("HRMS_ALERT_CONFIG", "/etc/hrms-alerts/smtp.env"))
STATE = Path(os.environ.get("HRMS_ALERT_STATE", "/var/lib/hrms-alerts/last-monitor-alert.json"))


def load_config() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in CONFIG.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("ALERT_SMTP_USER", "ALERT_SMTP_PASSWORD", "ALERT_TO"):
        if not cfg.get(key):
            raise SystemExit(f"{CONFIG}: {key} is not set")
    return cfg


def monitor_message(report: dict, repeat_hours: float) -> tuple[str, str] | None:
    """Subject and body for a monitor report, or None when this failure set was sent recently."""
    failing = [c for c in report.get("checks", []) if not c.get("ok")]
    names = sorted(c.get("name", "?") for c in failing)
    key = hashlib.sha256(",".join(names).encode()).hexdigest()
    now = time.time()
    try:
        last = json.loads(STATE.read_text())
        if last.get("key") == key and now - last.get("sent_at", 0) < repeat_hours * 3600:
            return None
    except (OSError, ValueError):
        pass
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"key": key, "sent_at": now, "checks": names}))

    worst = "critical" if any(c.get("severity") == "critical" for c in failing) else "high"
    subject = f"[HRMS {worst.upper()}] {len(names)} check(s) failing: {', '.join(names)[:150]}"
    lines = [f"Host: {socket.gethostname()}", f"At: {report.get('checked_at', '?')} (UTC)", "", "Failing checks:"]
    for c in failing:
        lines.append(
            f"  - {c.get('name')}: value={c.get('value')} threshold={c.get('threshold')} "
            f"severity={c.get('severity')}"
        )
    lines += [
        "",
        f"The same set of failures is not re-sent for {repeat_hours:g} h.",
        "Runbook: docs/operations/ALERTS_AND_RUNBOOKS.md",
        "",
        "Full report:",
        json.dumps(report, indent=2),
    ]
    return subject, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", help="send stdin as a plain alert with this subject")
    parser.add_argument("--test", action="store_true", help="send a test message")
    args = parser.parse_args()
    cfg = load_config()

    if args.test:
        subject = f"[HRMS] Test alert from {socket.gethostname()}"
        body = "Alert email from the HRMS VPS works. No action needed."
    elif args.subject:
        subject, body = args.subject, sys.stdin.read()[-20000:]
    else:
        raw = sys.stdin.read()
        try:
            report = json.loads(raw)
        except ValueError:
            subject, body = f"[HRMS ALERT] monitor output on {socket.gethostname()}", raw[-20000:]
        else:
            msg = monitor_message(report, float(cfg.get("ALERT_REPEAT_HOURS", "6")))
            if msg is None:
                print('{"alert_email":"skipped_repeat"}', file=sys.stderr)
                return 0
            subject, body = msg

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{cfg.get('ALERT_FROM_NAME', 'HRMS VPS alerts')} <{cfg['ALERT_SMTP_USER']}>"
    message["To"] = cfg["ALERT_TO"]
    message.set_content(body)
    with smtplib.SMTP(cfg.get("ALERT_SMTP_HOST", "smtp.gmail.com"), int(cfg.get("ALERT_SMTP_PORT", "587")), timeout=20) as smtp:
        smtp.starttls()
        smtp.login(cfg["ALERT_SMTP_USER"], cfg["ALERT_SMTP_PASSWORD"])
        smtp.send_message(message)
    print('{"alert_email":"sent"}', file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
