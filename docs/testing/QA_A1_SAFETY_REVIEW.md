# QA A1 Safety Review (read-only) - before approving the disposable stack

Date: 2026-10-25 · Scope: `docs/testing/qa_harness/*`, test-infrastructure edits under `apps/api/tests` and `apps/mobile/test/live`. **No container, network, volume or database was created or started in this review; B1 was not run.**

## 0. What was executed vs. what is only proposed

**Executed during this review (all read-only or local file edits):** `cat/grep/find/stat/findmnt/df/free` on the repo and host; `docker ps`, `docker info`, `docker system df`, `docker image inspect` (metadata only; no pulls, no `docker run/exec/create/rm/stop/restart`); `bash -n` and `py_compile` on the harness; `pytest tests/unit/test_isolation_guard.py --noconftest` (26 passed; no Redis, DB or Docker involved); `ruff check/format`; edits to `stack.sh`, `entry.py`, `guard_check.py`, `b1/k1_privileges.py`, `tests/isolation_guard.py`, `tests/unit/test_isolation_guard.py`, the QA documents and the catalogue generator. *Earlier phases* (already reported): two short-lived in-memory `redis-server` processes on 127.0.0.1:16410, stopped; `qa_preserve_2026-10-25/` backup directory created.

**Never executed (proposed only):** every `stack.sh up | guard | migrate | pytest | py | psql | rerun-role-script | usage-probe-* | down` invocation (section 5).

## 1. Defects found by this review and fixed in the harness (script/test-infra edits only)

| # | Finding | Severity | Fix (uncommitted) |
|---|---|---|---|
| R1 | `docker network create --internal` removes the default route but **does not guarantee the host's bridge-gateway address is unreachable**; the shared stack publishes 5433/6380/9000 on `0.0.0.0`, so a container on that bridge could reach it via the gateway IP. The previous `guard_check.py` never probed the QA bridge's own gateway | High (isolation) | Replaced by a **holder container with `--network none`**; Postgres, Redis, MinIO and runners join it with `--network container:<holder>`. Namespace contains only `lo`: no bridge, gateway, route, DNS. `guard_check.py` asserts only-`lo`, empty route table, unresolvable names, and unreachable shared ports on `127.0.0.1`, host IPs and shared-container IPs |
| R2 | `QA_ROOT` could be overridden from the environment (`${QA_ROOT:-...}`), redirecting data to `/` and widening `down`'s `rm -rf` scope | High | Constant path; `assert_qa_root` requires a different filesystem than `/`, the approved parent, no symlinks |
| R3 | `up` reused an existing run directory (an old `pgdata` would skip init scripts) | Medium | `preflight` aborts if `$RDIR` exists |
| R4 | Whole repo mounted read-only exposed other secrets files: `HRMS/.env`, `apps/.env`, `apps/web/.env.local` (only `apps/api/.env` was masked) | Medium | `mask_args` masks **every** non-example `.env*` file found by `find`; `guard_check.py` re-walks the tree and fails if any is non-empty |
| R5 | Guard only inspected the database *name* of `DATABASE_URL` and one Redis URL; migrations/app/Celery URLs and host:port were unchecked; missing variables silently fell back to the shared defaults (`Settings` defaults: `localhost:5433/hrms_dev`, `localhost:6380/0`, S3 endpoint `None` = AWS) | High | `isolation_guard`: non-strict mode now checks all DB and Redis variables; new **strict mode** (`HRMS_QA_STRICT=1`, ignores `CI` and the override) is an allow-list: every DB named `hrms_qa_*`, every service literally `127.0.0.1` on a non-standard port (forbidden: 5432/5433/6379/6380/9000/9001/8000/3306), providers inert and token-free, `.env` absent or empty, missing variable = failure. 26 unit tests |
| R6 | Nothing forced the guard before running code in the sandbox | Medium | All Python in the sandbox goes through `entry.py`, which runs the strict check first (exit 97 on failure); `migrate/pytest/py/psql/probes` additionally require a **fresh `guard` proof bound to this holder's container ID** |
| R7 | Destructive/DB commands did not prove the target DB was the disposable one | Medium | `up` creates `qa.disposable(run)` in the new DB; `psql`, `rerun-role-script`, `usage-probe-*` and `k1_privileges.py` verify container labels/name **and** the marker equals the run id |
| R8 | `rerun-role-script` (changes grants) ran without an explicit gate; `usage-probe-install` issued `GRANT`s and created objects in `public` (default privileges would have granted `hrms_app` full DML on them) | Medium | `rerun-role-script` requires `--authorise-grant-change`; the probe uses schema `qa`, a `SECURITY DEFINER` trigger function, and **no GRANT statements** |
| R9 | `down` trusted label filters only | Low | Each container must also carry the `qa-<RUN>-` name prefix or **nothing** is removed |
| R10 | Disk gate was checked only at start | Medium | Every runner invocation re-checks `/` >= 2 GiB; memory caps added (runner 3 GB, PG 2 GB, MinIO 1 GB, Redis 512 MB); Redis tmpfs capped at 256 MB |
| R11 | **K-1 wording error**: `002_app_role.sh` never grants `TRUNCATE`; the exposure is `UPDATE`/`DELETE` | Info | Corrected in the defect register, baseline and case `ATT-PUNCH-006` |

None of these fixes has been exercised against Docker (that needs creation of resources). The strict guard logic is unit-tested; shell syntax is checked with `bash -n`.

## 2. Decision table

Legend: **V** verified (observed or unit-tested here) · **D** verified by design reading, runtime proof pending · **N** not verified · **F** failed (fixed in this review, re-check pending).

| # | Requirement | Evidence examined | Result | File:line | Remaining risk | Required remediation |
|---|---|---|---|---|---|---|
| 1 | Every resource-changing command listed | full read of `stack.sh` v2 | **V** (list in section 3) | `stack.sh:139-244` | `docker` runs as the operator's own docker-group account (full daemon control), by necessity | none beyond approval of A1 |
| 2 | Volumes/bind mounts and resolved host paths | `readlink -f`, `stat -c %D`, `findmnt`, `docker image inspect` (declared `VOLUME`s) | **V** (resolved) / **D** (runtime) | `stack.sh:32, 47-54, 160-168, 106-113` | postgres/redis/silo images declare `VOLUME`s; all three are overridden (bind or tmpfs) so no anonymous volume lands under `/var/lib/docker` - confirm with `docker volume ls` before/after | none; add the before/after volume diff to the run log |
| 3 | DB, Redis, MinIO, logs, artifacts stay on the non-root drive | paths on device `801` (`/dev/sda1`) vs `/` device `nvme0n1p6`; Redis in RAM tmpfs; log driver `local` capped | **D**; **N** for container writable layers | `stack.sh:47-54` (asserts different device), `:41` (log caps) | Container logs (<= 5 MB x 4 + one transient runner) and metadata are on `/var/lib/docker` (root). Writable-layer growth of PG/MinIO outside their bind mounts is unmeasured | measure `docker system df -v` and `du` of the three container dirs after B1; keep 5 MB caps |
| 4 | `.env` masking; alternative env files/secrets | `find` of all `.env*` (4 non-example files: `HRMS/.env`, `apps/.env`, `apps/web/.env.local`, `apps/api/.env`); `Settings` has `env_file=".env"` (cwd-relative) only; `alembic/env.py:26-27` reads `.env` from cwd | **D** | `stack.sh:56-60, 109`; `settings.py:86`; `guard_check.py:48-58`; `isolation_guard.py:110-112` | `-v /dev/null:<file>:ro` over a file inside a read-only bind mount is standard but unproven on this daemon; if it fails `docker run` aborts (fail closed). Other secrets in the repo (e.g. `docs/development/DEMO_SEED_CREDENTIALS.md`) are readable but the sandbox has no egress | none |
| 5 | Reach shared services by name/IP/host network/published ports | design: `--network container:<holder>` whose namespace has only `lo`; no `-p`; shared services are in `hrms_default` and published on `0.0.0.0:5433/6380/9000` | **D**; **F -> fixed** (R1) | `stack.sh:157-170`; `guard_check.py:42-45, 69-90` | Whether the old `--internal` design leaked is unproven (not needed - replaced). New design unproven until `guard` runs | run `guard`; abort on `NOT PROVED` |
| 6 | Egress/route/proxy | no `~/.docker/config.json`, no `/etc/docker/daemon.json`, dockerd `Environment=` empty, no `*_proxy` in shell; namespace has no interface but `lo` | **V** (host proxy config absent) / **D** (namespace) | `guard_check.py:43-47, 60, 85-90` | none known | none |
| 7 | Docker socket / control of other containers | runner mounts only: repo (ro), uv python (ro), 3 harness files (ro), artifacts (rw); `--cap-drop ALL`, `no-new-privileges`, non-root uid, read-only rootfs, no `--privileged`/`--pid`/`--ipc=host`; no `docker.sock` | **D** | `stack.sh:106-113`; `guard_check.py:59-62` | Mounted repo includes `.git` (read-only) | none |
| 8 | Cleanup can remove only run-labelled resources | `down`: label AND name-prefix check before any `docker rm`; data removal is `rm -rf /d/pgdata /d/minio` inside a `--network none` alpine container whose only mount is `$RDIR` (asserted non-symlink, correct device) | **D**; **F -> fixed** (R2, R9) | `stack.sh:227-237, 47-54` | Removing `$RDIR/pgdata|minio` is irreversible (disposable by design); artifacts are kept | none |
| 9 | Unique ports, names, labels, run IDs | no host ports published at all; names `qa-<RUN>-*`; labels `qa.run=<RUN>`, `qa.disposable=true`; `preflight` refuses existing names and existing `$RDIR` | **D** | `stack.sh:35, 144-147, 143` | A reused RUN_ID after `down` is allowed (dir absent again); private in-namespace ports (15432/16379/19000) cannot collide because each run has its own namespace | choose a fresh RUN_ID per attempt |
| 10 | Failures/interruption leave shared env untouched | every mutating command targets `qa-<RUN>-*` objects or `$RDIR`; `up` has an ERR/INT/TERM trap printing the cleanup command; runners use `--rm` | **D** | `stack.sh:155, 178` (trap) | Hard kill of the shell mid-`up` can leave labelled partial resources (shared stack unaffected); the only reads of shared objects are `docker inspect` of the three shared containers (IP list for the unreachability probe) | `down --confirm` |
| 11 | External email/payment/AI/storage providers | `Settings.email_provider` default `logging`; `tests/conftest.py` forces `EMAIL_PROVIDER=logging`, face `disabled`; runner env blanks Mailtrap/Hostinger/Face++/SMTP secrets; S3 endpoint explicit (default `None` = AWS) and strict mode requires it set; no payment or AI code exists; namespace has no egress | **V** (conftest, strict unit tests) / **D** | `tests/conftest.py:31, 38`; `stack.sh:66-84`; `isolation_guard.py:76-114` | A test that tries a real provider fails (fail closed) instead of leaking | none |
| 12 | 3 GiB root gate sufficiency | `df`: 5.3-5.4 GiB free (drifting 5.0 -> 5.4 -> 5.3 during the work); `docker system df`: images 14 GB (reclaimable 6 GB, not touched), 13 containers = 97 MB writable layers total; images are **all present locally (no pull)**; container logs capped; Redis tmpfs is RAM; runner `--rm` | **D**; actual B1 writes to `/` **N** (not measurable before creation) | `stack.sh:41-42, 101-103, 141` | Estimated upper bound: logs 20 MB + one transient runner log 5 MB + container metadata (KBs) + layer writes that bypass the bind mounts (unmeasured, expected < 100 MB). The larger risk is **concurrent growth by the shared dev stack** (its containers use Docker's default `json-file` driver with no rotation on the same disk) eating the 5.3 GiB while B1 runs. RAM: 15.8 GB total, ~6 GB available; caps total 6.5 GB (not reservations) | the added per-invocation re-check (>= 2 GiB) mitigates; owner to create headroom outside this task if desired; record `df` and `docker system df` before/after |

### Database safety (explicit conditions)

| Condition | Result | Evidence |
|---|---|---|
| `tests/security/test_rls_runtime_role.py` derives every connection from the supplied URL | **V** by reading | `test_rls_runtime_role.py:66-88` (`_role_urls`), used at `:97, :103, :169, :300`; no literal host/port/db remains (grep) |
| URL missing | **V** (unit) | non-sandbox: `conftest.py` default-fills `hrms_dev` -> refused unless `CI`/override (`isolation_guard.py:116-135`); sandbox: `entry.py` runs strict check before conftest and treats a missing variable as failure (`isolation_guard.py:84-88`; tests `test_strict_treats_a_missing_variable_as_a_failure`) |
| URL resolves to `hrms_dev` | **V** (unit) | refused for `DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, `HRMS_APP_DATABASE_URL`, any host; strict mode also rejects any name not `hrms_qa_*` |
| Host or port is the shared dev DB | **V** in strict mode (forbidden ports 5432/5433, non-loopback or non-literal-`127.0.0.1` hosts) / **not enforced in non-strict mode** | a differently-named DB on `localhost:5433` (e.g. `hrms_test`, used on purpose by `run_full_tests.py`) is still accepted outside the sandbox - accepted residual risk, documented |
| Fallback config would use shared `.env` | **V** (unit) / **D** | strict mode fails if `./.env` is non-empty; sandbox masks all `.env*` with `/dev/null`; `guard_check.py` verifies sizes |
| Destructive operation cannot prove disposability | **D** | sandbox commands need guard proof + strict check + DB marker row; tests themselves rely on the conftest/strict guard (`tenant_wipe.py` has no own check); `CI=true` disables the **non-strict** guard (strict ignores it) |

### K-1 safety

| Requirement | Result | Evidence |
|---|---|---|
| Scripts touch only the disposable DB | **D** | `k1_privileges.py:19-27` strict check, loopback + `hrms_qa_*`, marker; `stack.sh` K-1 commands call `assert_marker` |
| Inspection only | **D** | owner connection is read-only queries (`has_table_privilege`, `pg_*`); `hrms_app` probes are `UPDATE/DELETE ... WHERE false` and `TRUNCATE` inside transactions that are always rolled back (`k1_privileges.py:84-94`); privileges are checked before rows are scanned |
| No grants changed in B1 setup unless authorised | **D** | `up` runs the repository's own init scripts once (initial provisioning of the new cluster, identical to dev compose); `usage-probe-install` has no GRANTs; the only grant-changing command is `rerun-role-script`, hard-gated by `--authorise-grant-change` and listed last |
| Expected matrix | stated | `k1_privileges.py:30-36`: target tables SELECT+INSERT only (UPDATE/DELETE/TRUNCATE all false) - **expected to differ today for UPDATE/DELETE on the three K-1 tables**; `employee` full DML minus TRUNCATE; `idempotency_key` no DELETE/TRUNCATE |

## 3. Every resource-changing command in `stack.sh` v2

| Command | Creates / starts | Stops / deletes | Modifies |
|---|---|---|---|
| `preflight` | nothing | nothing | nothing (reads df, docker ps/images, find) |
| `up` | dirs `$RDIR/{pgdata,minio,artifacts,logs}`; containers `qa-<RUN>-net` (holder, `--network none`), `qa-<RUN>-pg`, `qa-<RUN>-redis`, `qa-<RUN>-minio`; throwaway `--rm` containers: 2 x alpine `chown`, 1 x `pgsty/mc` (bucket); host temp env files are not used here | throwaway containers self-remove | chown of the two new data dirs; new DB `hrms_qa_<RUN>` + roles via the repo's init scripts; bucket `hrms-documents` in the private MinIO; schema `qa` + marker row |
| `guard` | one `--rm` runner; host temp env file (mode 600) | removes the temp file | writes `artifacts/preflight_isolation.json` |
| `migrate`, `pytest`, `py` | one `--rm` runner each (+ host temp env file) | removes temp file | disposable DB contents (alembic / test data and teardown), private Redis keys, private bucket objects, artifacts |
| `psql <sql>` | - | - | whatever SQL you pass, disposable DB only |
| `usage-probe-install` | objects in schema `qa` (table, function) and triggers on 3 tables | drops/recreates its own triggers | disposable DB; no grants |
| `usage-probe-report` | - | - | read-only |
| `rerun-role-script --authorise-grant-change` | - | - | **grants of the disposable DB** (re-applies `GRANT ... ON ALL TABLES`) |
| `down --confirm` | one `--network none` alpine `--rm` | `docker rm -f` of this run's containers (label + name prefix); `rm -rf $RDIR/pgdata $RDIR/minio` | nothing else; artifacts kept |

Resolved host paths (**V**): repo `/media/varun/varun12/work/staff-spectrum/HRMS` (device 801, `/dev/sda1`); QA root `/media/varun/varun12/work/staff-spectrum/qa_runs` (parent device 801; does not exist yet); uv python `/home/varun/.local/share/uv/python/` (device 10306 = `/`, mounted read-only, nothing written); host temp files in `/tmp` (device 10306 = `/`, KBs, mode 600, removed after use). Runner mounts: `$REPO`->same path ro, 4 masked `.env*` files, uv python ro, `qa_harness/b1`->`/qa/b1` ro, `guard_check.py`, `entry.py` ro, `$RDIR/artifacts`->`/artifacts` rw. Postgres: `$RDIR/pgdata`->`/var/lib/postgresql/data`, `infra/docker/postgres/init`->`/docker-entrypoint-initdb.d` ro. MinIO: `$RDIR/minio`->`/data`. Redis: tmpfs `/data` 256 MB.

## 4. Open items that remain after the fixes (not blockers for approval, but known)

1. Nothing in the new design has been exercised against a live daemon; `guard` is the first runtime proof and B1 stops if it prints `NOT PROVED`.
2. `-v /dev/null:...:ro` masking and `--network container:` joins of three stateful containers are standard Docker features but untested here.
3. The non-sandbox guard cannot recognise a shared server under a different database name or alias (deny-list); `CI=true` in a developer shell disables it.
4. Container writable-layer writes on `/` are unmeasured until after the first run.
5. Mobile live-test fix and `LV-28` replacement remain unvalidated (Flutter absent / no API).

## 5. Proposed A1 commands (**not executed**)

```bash
cd /media/varun/varun12/work/staff-spectrum/HRMS
H=docs/testing/qa_harness/stack.sh; RUN=b1-20261025a

# 0. read-only; safe to run before approval, repeat of what already passed on v1
$H preflight $RUN

# 1. CREATES: dirs under /media/varun/varun12/work/staff-spectrum/qa_runs/$RUN, containers qa-$RUN-{net,pg,redis,minio}, DB hrms_qa_${RUN//-/_}, bucket, schema qa
$H up $RUN
# 2. STOP here unless this prints "ISOLATION PROVED"
$H guard $RUN
# 3. B1 (disposable DB only)
$H migrate $RUN
$H py $RUN /qa/b1/k1_privileges.py after-migrate
$H pytest $RUN tests/unit/test_isolation_guard.py --noconftest -q
$H pytest $RUN tests/security/test_rls_runtime_role.py -q
$H pytest $RUN tests/integration/core/test_runtime_role_grants.py tests/integration/modules/payroll/test_b05_db_immutability.py -q
$H pytest $RUN /qa/b1/test_b1_attendance.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q
# 4. Optional K-1 observation (separate approval recommended): no grants changed
$H usage-probe-install $RUN
$H pytest $RUN tests/integration/modules/attendance -q
$H usage-probe-report $RUN
# 5. Optional K-1 experiment - CHANGES the disposable DB's grants; only with explicit authorisation
$H rerun-role-script $RUN --authorise-grant-change
$H py $RUN /qa/b1/k1_privileges.py after-rerun
# 6. Teardown (irreversible for this run's pgdata/minio only)
$H down $RUN --confirm
```

**Would create:** 4 long-lived containers (holder alpine, postgres:16-alpine, redis:7-alpine, pgsty/silo), 3-4 short-lived `--rm` containers per command, 0 networks, 0 named/anonymous volumes (expected; verify), 0 published ports, 3 bind directories (~ tens of MB for the DB, MinIO objects and artifacts), 1 private database, 1 private bucket, host temp files of a few hundred bytes.

**Explicitly outside A1:** pulling images, touching `hrms-*` containers or volumes, any change under `/var/lib/docker`, committing, freeing disk space.

**Waiting for explicit approval. Nothing above has been run.**


## 6. Post-approval execution note (2026-10-25)

A1 was approved with conditions and executed: see `QA_BASELINE_RESULTS.md` sections 15-17. Deviations from section 5: memory caps were reduced first (runner 1.5 GB, PG 512 MB, MinIO 512 MB, Redis 192 MB); `compress=false` was added to the Docker log options after the first `up` failed; the optional steps 4 and 5 (usage probe, role-script rerun) were **not** run; a second `up/guard/down` cycle was run on a fresh RUN_ID to prove repeatability.


## 7. Follow-up (B2 phase)

`usage-probe-install` was reviewed and judged **not read-only** (DDL on three public tables plus a schema `qa` table/function); it now requires `--authorise-schema-change` and was not run. `stats-snapshot` (read-only `pg_stat_user_tables` through a read-only session) replaced it for the approved K-1 evidence. Runner memory caps were lowered before B1 (runner 1.5 GB); `/qa/b2` was added as a read-only mount.
