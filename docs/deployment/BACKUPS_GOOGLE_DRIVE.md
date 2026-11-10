# HRMS backups to Google Drive

Encrypted, hourly, offsite backups for the Hostinger VPS. Script: `infra/backup/hrms_backup.sh`. Units: `infra/backup/systemd/`. This replaces `pg_backup.sh`/`minio_backup.sh` on the VPS. Those scripts dump only `$POSTGRES_DB` (`hrms_prod`), not `hrms_demo`, which the app actually runs on.

## What runs

| When | What |
|---|---|
| Every hour at :15 UTC | `pg_dumpall --globals-only` + `pg_dump -Fc` of every DB in `BACKUP_DATABASES`, each checked with `pg_restore --list`; manifest of row counts and alembic head; `tar \| age` encrypted; uploaded to `HRMS-Backups/hourly/` |
| First run after 00:00 UTC (05:30 IST) | The hourly backup above, plus: a restore test of every dump into a throwaway, network-less container with row counts and alembic head compared; an encrypted copy of the MinIO volume; the compose and app env files (they hold `PII_MASTER_KEY`). Copied to `daily/`, on Sundays also `weekly/`, on the 1st `monthly/`, on 1 Jan `yearly/` |

Retention:

| Tier | Local (`/var/backups/hrms`) | Google Drive |
|---|---|---|
| Hourly | 48 h | 2 days |
| Daily | 7 days | 14 days |
| Weekly | — | 8 weeks |
| Monthly | — | 12 months |
| Yearly | — | 7 years |

Files Drive deletes go to its trash and stay recoverable for 30 days.

## Security model

- Only the age **public** key is on the server (`/etc/hrms-backup/age-recipients.txt`). The server can write backups but cannot read them. The private key is kept offline: in the password manager plus one other offline copy. **Losing it makes every backup unreadable.**
- rclone uses the Drive `drive.file` scope, so it can only see files it created. The token is in `/root/.config/rclone/rclone.conf` (600).
- Drive has no write-only credential. Anyone with root on the VPS could delete the Drive copies (they would sit in the trash for 30 days). If that matters later, add a second destination with object lock (Backblaze B2).
- Plaintext dumps exist only in `/var/backups/hrms/.work-*` (700) during a run and are removed at the end.

## Setup (one time)

1. On the owner's computer: `sudo apt install age rclone`, then `age-keygen -o ~/hrms-backup-age.key`. Keep the file in the password manager. Put the printed `age1…` public key on the server in `/etc/hrms-backup/age-recipients.txt` (mode 600).
2. Connect Drive with the `drive.file` scope. The owner's laptop has rclone 1.53, which cannot pass a scope to `rclone authorize`, so run the authorisation on the server (1.60) through an SSH tunnel:
   ```bash
   ssh -t -L 53682:127.0.0.1:53682 -i ~/.ssh/hostinger_hrms root@147.93.103.147 \
     rclone authorize drive eyJzY29wZSI6ImRyaXZlLmZpbGUifQ --auth-no-open-browser
   ```
   The last argument is unpadded URL-safe base64 of `{"scope":"drive.file"}`. Open the printed `http://127.0.0.1:53682/auth?...` link in the laptop browser and sign in. The consent screen must offer access only to files rclone creates. Then write `/root/.config/rclone/rclone.conf` (600) on the server:
   ```ini
   [hrms-gdrive]
   type = drive
   scope = drive.file
   token = <the "token" value: base64-decode the blob rclone prints, then take its "token" field>
   ```
   Don't paste the token into chats or tickets. Check with `rclone about hrms-gdrive:`.
3. `cp infra/backup/systemd/hrms-backup.env.example /etc/hrms-backup/hrms-backup.env` (already done), edit if needed.
4. First run: `systemctl start hrms-backup.service`. It is a daily run automatically, because no daily file exists yet today. Watch it with `journalctl -fu hrms-backup`.
5. `systemctl enable --now hrms-backup.timer`.

## Checking

```bash
systemctl list-timers hrms-backup.timer
tail -5 /var/backups/hrms/postgres/backup.log      # SUCCESS / FAILED lines, read by hrms_monitor.sh
journalctl -u hrms-backup --since today
rclone lsl hrms-gdrive:HRMS-Backups/daily/postgres/
```

## Restoring

On a machine that holds the private key:

```bash
rclone copy hrms-gdrive:HRMS-Backups/daily/postgres/hrms_<TS>_daily.tar.age .     # or download from drive.google.com
sha256sum -c hrms_<TS>_daily.tar.age.sha256
mkdir restore && age -d -i ~/hrms-backup-age.key hrms_<TS>_daily.tar.age | tar -C restore -xf -
cat restore/manifest.txt
```

`restore/` contains `globals.sql`, `<db>.dump` per database, `manifest.txt` and (daily) `config/`. Then follow `DISASTER_RECOVERY.md`:
1. Restore into a **new** database name: `pg_restore --no-owner -d hrms_restored <db>.dump`, run inside the postgres container.
2. Compare the row counts with the manifest.
3. Re-apply grants with `infra/docker/postgres/init/002_app_role.sh`, then the append-only REVOKEs (below).
4. Switch `DATABASE_URL`.

A blanket `GRANT … ON ALL TABLES` after a restore re-opens the append-only tables. Always re-run:

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log, leave_ledger, leave_application_action,
  platform_audit_log, email_log, leave_year_end_run FROM hrms_app;
```

MinIO: `age -d -i key minio_<TS>_daily.tar.age | tar -C <empty minio data dir> -xf -`, with MinIO stopped.

## Alerts (email)

- `infra/monitoring/hrms_notify_email.py` sends mail via Gmail SMTP using a Google **app password**. Config is in `/etc/hrms-alerts/smtp.env` (600). Recipient: `ALERT_TO`.
- `hrms-backup.service` has `OnFailure=hrms-alert@%n.service`: a failed backup emails the last 80 journal lines.
- `hrms-monitor.timer` runs `hrms_monitor.sh` every 5 min. It checks:
  - API readiness, the Celery heartbeat and queue;
  - unhealthy, stopped or restarting containers;
  - disk;
  - 5xx responses, task failures and other error events in the logs;
  - backup age (over 26 h counts as failed).

  Failing checks are emailed. The same set is not re-sent for 6 h (`ALERT_REPEAT_HOURS`). No "recovered" mail is sent.
- Test: `/opt/hrms/infra/monitoring/hrms_notify_email.py --test`.

## Host hardening (10 Nov 2026)

Backups of the changed files are in `/opt/hrms-backups/hardening-20261110-133323/`.
- SSH: `/etc/ssh/sshd_config.d/00-hrms-hardening.conf` turns off password and keyboard-interactive login and X11 forwarding, and sets root to key-only and a 30 s login grace. Rollback: delete the file, `systemctl reload ssh`. If you are ever locked out, use the hPanel browser console.
- Swap: 4 GB `/swapfile` (in `/etc/fstab`), `vm.swappiness=10` (`/etc/sysctl.d/99-hrms-swap.conf`).
- nginx: `server_tokens off`; global `ssl_protocols TLSv1.2 TLSv1.3`; HSTS and nosniff headers on `storage.krewoxa.com`. `www` and `api` already send their own headers from the app.
- `/opt/hrms/local_data.dump` and `local_full.dump` changed to mode 600.

## Change log

| Date | Change |
|---|---|
| 2026-11-10 | Script, units and Drive destination added. `hrms_app` UPDATE/DELETE/TRUNCATE revoked on the six append-only tables in `hrms_demo` and `hrms_prod` (`mkdemo.sh`'s blanket GRANT had re-opened them). |
