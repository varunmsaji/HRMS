# DevOps maturity assessment

Audit date: 2026-11-25. Scores are 0 absent, 1 ad hoc, 2 partial, 3 standardized, 4 automated and monitored, 5 mature and tested and still improved. A tool that is installed but idle does not raise the score. Overall **2.4** is the unweighted mean of the sixteen scores (38 / 16).

| Category | Score | Why this number |
|---|---|---|
| Source control | 3 | `test` and `main` are real, pull requests are the normal path, auto-merge matches the tested SHA and holds Alembic changes. GitHub does not enforce any of it. No tags or releases. Score stays at standardized convention, not at enforced automation |
| CI | 3 | Six jobs, real Postgres, Redis, and MinIO, migration job that fails closed, blocking secret and dependency scans, latest run green on `de83274`. ESLint does not fail the build, images are not built, actions are not pinned, coverage is not gated. That is a standard pipeline with known holes, not yet "automated and monitored" |
| CD | 1 | Release is SSH, copy, and build on the server. Documented for the web app. Not automated |
| Docker | 3 | Multi-stage Dockerfiles, non-root app users, health checks, network split, MinIO pinned, and those containers are actually healthy on the VPS. Tags for Postgres, Redis, and the app are mutable. No resource limits. Compose is standard and in use, not yet pinned and measured |
| Infrastructure management | 2 | Compose and systemd units are in git. The host was built by hand, `/opt/hrms` is not a checkout, live nginx is outside git, 61 packages are pending. Partial |
| Environment separation | 2 | Example files exist for dev, qa, staging, and production. CI is isolated. There is one VPS. The live database is named `hrms_demo` and an older `hrms_prod` sits beside it |
| Monitoring | 2 | Health URLs work. The five-minute monitor runs and last exited 0. Prometheus, node_exporter, and Grafana are written down and not running, so there is no time series |
| Logging | 3 | Structured logs, request IDs, redaction, and size caps are designed and the containers that would emit them are up. There is no central search. Standardized, not aggregated |
| Alerting | 2 | The mailer is wired and deduplicated. Prometheus rules are not loaded. A message was not observed, because the last monitor run did not fail. Partial, not proven |
| Security | 2 | Strong pieces: UFW, SSH passwords off, fail2ban, TLS, non-root app, CI secret scan, dependency audit, no production secrets in CI. Weak pieces: no branch protection, root is the only admin, unpinned actions, no image scan, pending OS updates, public repo. The mix is partial |
| Backups | 4 | Hourly encrypted off-site dumps are scheduled and today's daily and hourly runs logged SUCCESS. The daily script includes a restore test. Remote objects were not listed from this workstation, so this is not a 5 |
| Disaster recovery | 2 | Backups make recovery possible. WAL is off. A full rebuild has not been timed. Two documents disagree. Partial |
| Database operations | 3 | PostgreSQL 16 is healthy, init role is defined, CI migrates a real server, dumps are automated. No PITR, default memory settings, no slow-query setting observed, confusing database names. Standard single-node operation |
| Release management | 1 | `main`, `test`, and the VPS are three versions. Images are `latest` from 4 November. One local backup tag. Ad hoc |
| Reliability engineering | 2 | Restart policies, idempotent task policy, worker health check, and three weeks without restarts. Beat cannot be detected hung by Docker. No resource limits. No proof that a missed business job alerts. Partial |
| Documentation | 3 | Runbooks exist for deploy, backup, and alerts, and several were accurate enough to find the server. Superseded disaster-recovery text and a runbook that says it was never executed sit beside a web procedure that was used. Standardized and in need of a single index |

## What would move the scores

| To reach 4 | Needs |
|---|---|
| Source control | `P1-01` and `P1-02` in force, and a tag per production digest |
| CI | Image build plus pinned actions, ESLint either fixed or removed from the false sense of a green lint step |
| CD | `P3-01` and `P4-01` used for one real release |
| Monitoring | `P5-01` storing data for a week |
| Alerting | `P5-02` a received test message |
| Backups toward 5 | `P6-02` a restore on a different machine with the offline key |
| Release management | Production digest equals a `main` SHA, written down |

None of these are a 5. A 5 needs the control to have failed once, been fixed, and still be watched. This system has not had that loop for deploys or for alerts.
