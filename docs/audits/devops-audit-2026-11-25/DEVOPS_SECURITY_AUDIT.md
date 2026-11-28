# Security and DevSecOps audit

Audit date: 2026-11-25. This is an infrastructure and delivery assessment. It is not a penetration test and it does not list exploit procedures. Findings are ordered by whether an attacker or an ordinary mistake can use them on this system as it runs today.

Secret values were not read and are not included.

## 1. What actually blocks a release

| Check | Blocks auto-merge to `main`? | Blocks the VPS? |
|---|---|---|
| API tests, types, ruff, boundaries | Yes, if the merge goes through the auto-merge workflow | No. The VPS does not consult CI |
| Migration job | Yes, same condition | No |
| Web typecheck, Vitest, build | Yes | No |
| Mobile analyze and test | Yes | No |
| Gitleaks on the tree | Yes | No |
| `pip-audit` and production `npm audit` at high | Yes | No |
| ESLint | No | No |
| Container scan | Does not exist | No |
| Branch protection | Does not exist | No |
| Image signature | Does not exist | No |

Development-time checks and production runtime controls are different systems. A green pull request never becomes a running container by itself. A red pull request can still be what someone copies to the server, or they can copy files that were never pushed.

## 2. Findings

### S-01. `main` and `test` are not protected on GitHub

Priority: critical for the engineering process, high for production because production does not track `main` automatically.

Evidence: protection API 404, rulesets empty, repository public, default branch `main`. The refusing hook is `.git/hooks/pre-push` in one clone.

Impact: anyone with write access can push or force-push `main` from a clone that does not have the hook, or merge a red pull request in the UI. A force-push was not attempted. The absence of a rule is the finding.

Task: `P1-01`. Risk: `R-01`.

### S-02. Production admin is root over SSH

Priority: high.

Evidence: `permitrootlogin without-password`, password authentication off, only uid 0 has a shell, fail2ban active, UFW allows 22 from anywhere.

Impact: the key is the whole machine, including Hirico, the age recipient is public-only so backups stay unreadable, and the rclone token can delete Drive copies. Theft of the laptop key is a full compromise. There is no second account to lock root out with.

Task: `P7-02`.

### S-03. Shared kernel with another application

Priority: high as a blast-radius issue, not as a confirmed vulnerability.

Evidence: Hirico containers and a root uvicorn on `0.0.0.0:8000` from `/root/hirico`. UFW does not allow 8000. External reachability was not tested.

Impact: a fault in either app can fill the disk or the memory of both. An exposed port on the host is not filtered by Docker's network. UFW is the control, and it is on.

Task: `P9-01` for limits. Do not change Hirico as part of HRMS work.

### S-04. Actions are unpinned and any action is allowed

Priority: medium until a deploy secret exists, high the day a deploy key is added to GitHub.

Evidence: `allowed_actions: all`, `sha_pinning_required: false`, floating tags listed in the CI audit, `gitleaks:latest`.

Impact today: a compromised action can read the repository and the CI workspace. It cannot read production env files, because they are not in CI. Impact later: the same action could exfiltrate a registry token or an SSH key.

Task: `P1-03`, `P7-01`.

### S-05. Redis has no authentication and no memory cap

Priority: medium.

Evidence: production example URL has no password. Server `CONFIG GET appendonly` is yes, `maxmemory` is 0, policy `noeviction`. The container is on the `data` network and is not published.

Impact: any process that joins the Docker network can read the broker. That means a compromised API or a mistaken compose publish. It is not reachable on the public interface today. `noeviction` with no cap means Redis will grow until the host OOM killer runs.

Task: `P9-02`.

### S-06. OS packages are behind

Priority: medium until the list is classified.

Evidence: `unattended-upgrades` is enabled and `apt-get -s upgrade` reports 61 upgradable packages. This audit did not run an upgrade and did not print package names.

Impact: unknown without the list. The control exists and has not drained the queue.

Task: `P7-03`.

### S-07. No container or image scanning

Priority: medium.

Evidence: no Trivy or equivalent in workflows. Base images float.

Task: `P7-01`, `P2-02`.

### S-08. Public source repository

Priority: low to medium, depending on policy.

Evidence: GitHub reports `visibility: public`.

Impact: design and schema are public. Gitleaks is the control against committed secrets. Customer data is not in git. If the business assumption was a private repository, this is a policy miss. This audit does not recommend making it public or private. It records the fact.

### S-09. TLS and HTTP hardening that is in place

These are controls, not findings.

- Public HTTPS works for the site and the API.
- Certificate is Let's Encrypt, expires 2027-01-30, renewal timer is active.
- HSTS string is in the live site file.
- HRMS app containers are not published on the public interface.
- API refuses to boot in non-development without an explicit CORS origin, an https web origin, and an S3 endpoint, according to `apps/api/env/.env.production.example` and the settings guards those comments point at. The running process is up, so those guards passed for the current env file. The values were not printed.
- Application logs redact token paths in the repo nginx template and in API code (`redaction.py` is referenced from nginx comments). A live log line was not sampled, so redaction in the running host config is implemented in the repo and unverified on the host file.
- RLS: CI proves the unprivileged role. The production role's attributes were not re-queried, to avoid a broad catalog query. Init script `002_app_role.sh` is mounted. Whether it ran on the current data directory depends on that directory having been empty at first boot. Status: implemented in the repo, not re-verified inside the live database.
- Backup encryption: age public key only on the server, by the script's design. The recipients file was not printed. The script refuses to run if the file is missing or empty, and backups are succeeding, so the file is non-empty.
- Gitleaks and dependency audit block the auto-merge path. See the CI audit.

### S-10. Logging of secrets

`hide_parameters=True` on the SQLAlchemy engine. Nginx repo config strips query strings and masks token path segments. The email alert script reads SMTP settings from a root-only file and was not opened. Status: designed and unit-tested in the repo (`test_log_redaction.py` exists). Production log files were not grepped, because a grep for secrets would risk printing them.

## 3. Network exposure summary

| Port | Process | Public by UFW? |
|---|---|---|
| 22 | sshd | Yes |
| 80, 443 | host nginx | Yes |
| 8001, 3001, 9100 | HRMS, loopback | No |
| 5432, 6379 | Hirico, loopback | No |
| 8000 | Hirico uvicorn, all interfaces | Not in the allow list. Not probed |
| HRMS Postgres and Redis | Docker network only | No |

Docker-published ports on `0.0.0.0` would bypass UFW. HRMS does not publish that way. Hirico's database and Redis do not either. The uvicorn on 8000 is a host process, so UFW applies.

## 4. Identity and secrets storage

| Secret class | Where it lives | In git? | In CI? |
|---|---|---|---|
| JWT, database, MinIO, PII key | Server env files under `/opt/hrms` | Examples only, with placeholders | No |
| Google Drive rclone token | Root rclone config, per the backup doc | No | No |
| Age private key | Documented as offline, not on the server | No | No |
| Alert SMTP | `/etc/hrms-alerts/smtp.env`, per the script | No | No |
| SSH admin key | Owner workstation `~/.ssh/hostinger_hrms` | No | No |
| Dev passwords | Compose and CI, marked as development | Yes, by design | Yes, by design |

Configuration validation at API boot is a real control for missing production settings. It was not re-executed with an empty env in this audit. The code path is `Settings` guards described in the production example.

## 5. Difference between the pipeline and the runtime

The pipeline answers "does this commit pass tests and contain no obvious secret or high-severity production dependency advisory?"

The runtime answers "is the host patched, is SSH limited, is the database unreachable from the internet, is TLS valid, are backups encrypted?"

Both are partly true. Neither is tied to the other. The highest-value join is: branch protection so `main` means "CI passed", image build so the artifact is that commit, and a deploy of that artifact so production means `main`.
