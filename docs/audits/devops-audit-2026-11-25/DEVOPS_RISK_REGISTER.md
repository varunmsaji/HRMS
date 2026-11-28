# DevOps risk register

Audit date: 2026-11-25. Likelihood and impact are High, Medium, or Low for this system in the next quarter, not in the abstract.

| ID | Risk | Likelihood | Impact | Priority | Evidence | Mitigation task |
|---|---|---|---|---|---|---|
| R-01 | A write-capable user pushes to `main` or merges a red PR, and the local hook never sees it | Medium | High | Critical | Branch protection 404. Hook is only in this clone. Repo is public, so the workflow is visible and the absence of a rule is visible | `P1-01`, `P1-02` |
| R-02 | The next copy of the repo onto the VPS boots code against schema `20261108090000` or migrates the live database without a rollback image | High if someone deploys from `test` | High | Critical | Images created 2026-11-04. Live Alembic `20261108090000`. Tree contains `20261109` through `20261125` revisions. `/opt/hrms` is not git | `P0-01`, `P3-01`, `P3-02`, `P4-01` |
| R-03 | The host runs out of memory because the worker holds about 2.2 GiB, Hirico shares the box, and nothing has a memory cap | Medium | High | Critical | `docker stats` sample. Limits are 0. CompreFace profile asks for 2–3 GiB more and is currently off | `P9-01` |
| R-04 | Disk or VPS loss loses up to one hour of database and up to one day of documents, and the rebuild takes longer than expected because nginx and images are not in one artifact | Low | High | High | `archive_mode` off. MinIO is daily-only. No timed drill. Age key location not confirmed | `P6-01`, `P6-02`, `P6-03` |
| R-05 | Beat or a scheduled job stops and nobody is told | Medium | High | High | Beat health check disabled. Monitor is the detector. Mail send not observed. Prometheus rules not loaded | `P5-01`, `P5-02` |
| R-06 | A compromised or malicious GitHub Action later receives a deploy key | Low today, High after a key is added | High | High | `allowed_actions: all`, floating tags, `gitleaks:latest` | `P1-03` before any deploy secret |
| R-07 | A new task fails quietly because the monitor's log patterns and the Prometheus rules were written for an older task list | Medium | Medium | High | Monitor greps event names. Rules name specific tasks. The November image does not contain the November 25 error-reference work or the later schedules if those schedules were added after the image | `P5-03` |
| R-08 | Root SSH key loss or theft is a full compromise of HRMS and Hirico, including the ability to delete Drive backups | Low | High | High | Only root can log in. rclone token is on the server. Drive has no object lock | `P7-02`, second backup destination is optional and listed under `P6-03` |
| R-09 | Pending OS updates include a kernel or OpenSSH fix that waits because 61 packages feels vague | Medium | Medium | Medium | `apt-get -s upgrade` count 61. unattended-upgrades is enabled, so some of this may be held for a reboot | `P7-03` |
| R-10 | Operator follows `DISASTER_RECOVERY.md` and looks for `pg_backup.sh` output that the timer no longer produces | Medium | Medium | Medium | That document and `BACKUPS_GOOGLE_DRIVE.md` disagree. The timer runs `hrms_backup.sh` | `P10-01` |
| R-11 | `hrms_prod` is restored or selected by mistake and the app serves the 15 MB database from `20261105` | Low | High | Medium | Both databases exist. API URL points at `hrms_demo`. The name `hrms_prod` sounds like the live one | `P10-01` documentation, and a later rename that is not in the first deploy |
| R-12 | Redis fills host memory because `maxmemory` is 0 and policy is `noeviction` | Low at 10 MB used | Medium | Medium | `CONFIG` read on the server | `P9-02` |
| R-13 | Certificate renewal fails and the site breaks on 2027-01-30 | Low | High | Low until the monitor ignores expiry | Timer is active and the cert is valid. No expiry check in the HRMS monitor was confirmed | `P5-04` |
| R-14 | ESLint or a dependency in the web app regresses and CI stays green | High for lint, by policy | Low | Low | `continue-on-error: true` | `P1-04` |
| R-15 | Artifact quota hides test reports, and a future change adds `continue-on-error` to a real test step by copying that pattern | Low | Medium | Low | Upload steps are already continue-on-error. Test steps are not | `P1-05` review comment in the workflow |

Accepted risks, recorded so they are not rediscovered as surprises:

- Single VPS and single disk, until the business pays for a second machine.
- Redis data loss on disk failure.
- Recreate deploys cause a short outage.
- Public source code, unless the owner changes visibility.
- No staging environment until the worker memory is understood.
- Hourly RPO rather than minutes.
