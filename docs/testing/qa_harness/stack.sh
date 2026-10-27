#!/usr/bin/env bash
# QA disposable stack + hermetic test runner (v2, QA Phase 3 review).  NOTHING here runs unless you invoke it.
#
#   stack.sh preflight <RUN_ID>            read-only checks (disk, paths, names, images, mounts)
#   stack.sh up        <RUN_ID>            create dirs + holder/Postgres/Redis/MinIO containers + bucket + disposable marker  [CREATES INFRA]
#   stack.sh status    <RUN_ID>
#   stack.sh guard     <RUN_ID>            prove isolation from inside the runner (required before migrate/pytest/py)
#   stack.sh migrate   <RUN_ID>            alembic heads / upgrade head / current on the disposable DB
#   stack.sh pytest    <RUN_ID> <args>     pytest in the runner (artifacts -> $QA_ROOT/<RUN_ID>/artifacts)
#   stack.sh py        <RUN_ID> <args>     python in the runner (module: -m mod, or script path)
#   stack.sh psql      <RUN_ID> <sql>      owner-role SQL on the disposable DB (marker verified first)
#   stack.sh stats-snapshot <RUN_ID>                                READ-ONLY per-table write counters (pg_stat_user_tables)
#   stack.sh usage-probe-install --authorise-schema-change <RUN_ID> (NOT read-only: DDL) / usage-probe-report
#   stack.sh rerun-role-script <RUN_ID> --authorise-grant-change  K-1 experiment: re-run 002_app_role.sh (CHANGES GRANTS of the disposable DB)
#   stack.sh down      <RUN_ID> --confirm  remove ONLY containers labelled qa.run=<RUN_ID> (+ name prefix check) and its pgdata/minio dirs
#
# ISOLATION MODEL (replaces the earlier --internal bridge network, which can still leave the host's
# bridge-gateway address reachable): one tiny holder container with `--network none` owns a network
# namespace containing ONLY the loopback interface.  Postgres, Redis, MinIO and every runner join it with
# `--network container:<holder>`.  There is no bridge, no gateway, no route, no DNS, nothing published:
# the sandbox cannot reach the host, the shared dev stack, other containers, or the internet.
set -euo pipefail

die() { echo "ABORT: $*" >&2; exit 3; }

CMD="${1:-}"; RUN="${2:-}"
[[ -n "$CMD" && -n "$RUN" ]] || { sed -n 2,26p "$0"; exit 2; }
shift 2
[[ "$RUN" =~ ^[a-z0-9][a-z0-9-]{3,40}$ ]] || die "RUN_ID must match [a-z0-9-]{4,41}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
HARNESS="$REPO/docs/testing/qa_harness"
QA_ROOT="/media/varun/varun12/work/staff-spectrum/qa_runs"          # constant: NOT overridable from the environment
RDIR="$QA_ROOT/$RUN"
HOLD="qa-$RUN-net"; PG="qa-$RUN-pg"; RD="qa-$RUN-redis"; MN="qa-$RUN-minio"
DB="hrms_qa_${RUN//-/_}"
PGPORT_Q=15432; RDPORT_Q=16379; S3PORT_Q=19000                         # private ports inside the holder namespace
PGPW="qa_owner_pw_$RUN"; APPPW="hrms_app_dev_password"                 # repo-visible dev value; sandbox has no route in or out
MINIO_USER="qa_minio"; MINIO_PW="qa_minio_pw_$RUN"; BUCKET="hrms-documents"
UVPY="$(readlink -f "$REPO/apps/api/.venv/bin/python" | sed 's#/cpython-[^/]*/.*#/#')"
LABELS=(--label qa.disposable=true --label "qa.run=$RUN")
LOGOPT=(--log-driver local --log-opt max-size=5m --log-opt max-file=1 --log-opt compress=false)
ROOT_MIN_KB=$((3*1024*1024)); QA_MIN_KB=$((20*1024*1024)); RUNTIME_ROOT_MIN_KB=$((2*1024*1024))

for n in "$HOLD" "$PG" "$RD" "$MN"; do [[ "$n" == qa-* ]] || die "non-qa name $n"; done
[[ "$UVPY" == /home/varun/.local/share/uv/python/ ]] || die "unexpected uv python root: $UVPY"

assert_qa_root() {   # QA data must live on a different filesystem than / and under the approved prefix
  local parent; parent="$(dirname "$QA_ROOT")"
  [[ "$(readlink -f "$parent")" == /media/varun/varun12/work/staff-spectrum ]] || die "QA root parent moved"
  [[ "$(stat -c %D "$parent")" != "$(stat -c %D /)" ]] || die "QA root is on the root filesystem"
  [[ ! -L "$QA_ROOT" && ! -L "$RDIR" ]] || die "symlinked QA path"
}
root_free_kb() { df --output=avail -k / | tail -1 | tr -d ' '; }
require_root_space() { [[ $(root_free_kb) -ge $1 ]] || die "free space on / below $(( $1/1024/1024 )) GiB ($(root_free_kb) KiB)"; }

mask_args() {        # mask EVERY non-example .env* file in the repo with /dev/null
  find "$REPO" \( -name node_modules -o -name .venv -o -name .git \) -prune -o -type f \
       \( -name '.env' -o -name '.env.*' \) ! -name '*.example' ! -name '*.template' -print \
    | while IFS= read -r f; do printf -- '-v\n/dev/null:%s:ro\n' "$f"; done
}

runner_env() {
  cat <<ENV
ENVIRONMENT=development
TZ=UTC
HOME=/tmp
PYTHONDONTWRITEBYTECODE=1
CI=
HRMS_TEST_ALLOW_SHARED_DEV=
HRMS_QA_STRICT=1
DATABASE_URL=postgresql://hrms:$PGPW@127.0.0.1:$PGPORT_Q/$DB
MIGRATIONS_DATABASE_URL=postgresql://hrms:$PGPW@127.0.0.1:$PGPORT_Q/$DB
HRMS_APP_DATABASE_URL=postgresql://hrms_app:$APPPW@127.0.0.1:$PGPORT_Q/$DB
REDIS_URL=redis://127.0.0.1:$RDPORT_Q/2
CELERY_BROKER_URL=redis://127.0.0.1:$RDPORT_Q/15
CELERY_RESULT_BACKEND=redis://127.0.0.1:$RDPORT_Q/15
JWT_ACCESS_SECRET=qa-access-secret-min-16-chars
JWT_REFRESH_SECRET=qa-refresh-secret-min-16-chars
S3_ENDPOINT_URL=http://127.0.0.1:$S3PORT_Q
S3_BUCKET_DOCUMENTS=$BUCKET
AWS_ACCESS_KEY_ID=$MINIO_USER
AWS_SECRET_ACCESS_KEY=$MINIO_PW
AWS_REGION=ap-south-1
EMAIL_PROVIDER=logging
FACE_VERIFICATION_PROVIDER=disabled
FACEPP_API_KEY=
FACEPP_API_SECRET=
MAILTRAP_API_TOKEN=
HOSTINGER_MAIL_API_TOKEN=
HOSTINGER_MAIL_MAILBOX_ID=
SMTP_PASSWORD=
LOG_TO_FILES=false
COMPANY_APPROVAL_REQUIRED=false
MAX_LEGAL_ENTITIES_PER_COMPANY=0
QA_ARTIFACTS=/artifacts
QA_RUN_ID=$RUN
QA_HOLD_ID=$(docker inspect -f '{{.Id}}' "$HOLD" 2>/dev/null || true)
ENV
}

runner_raw() {       # runner_raw <script> [args]  -- no proof check (used by `guard` itself)
  require_root_space "$RUNTIME_ROOT_MIN_KB"
  assert_qa_root
  local rc=0 envfile masks; envfile="$(mktemp)"; chmod 600 "$envfile"; runner_env > "$envfile"
  mapfile -t masks < <(mask_args)
  docker run --rm --name "qa-$RUN-runner-$$" "${LABELS[@]}" "${LOGOPT[@]}" \
    --network "container:$HOLD" --user "$(id -u):$(id -g)" --read-only --tmpfs /tmp:rw,size=256m \
    --cap-drop ALL --security-opt no-new-privileges --memory 1536m --pids-limit 1024 \
    -v "$REPO:$REPO:ro" "${masks[@]}" \
    -v "$UVPY:$UVPY:ro" -v "$HARNESS/b1:/qa/b1:ro" -v "$HARNESS/b2:/qa/b2:ro" -v "$HARNESS/b3:/qa/b3:ro" -v "$HARNESS/b4:/qa/b4:ro" -v "$HARNESS/b6:/qa/b6:ro" -v "$HARNESS/b7:/qa/b7:ro" -v "$HARNESS/b5:/qa/b5:ro" -v "$HARNESS/b10:/qa/b10:ro" -v "$HARNESS/b11:/qa/b11:ro" -v "$HARNESS/b12:/qa/b12:ro" -v "$HARNESS/b13:/qa/b13:ro" -v "$HARNESS/guard_check.py:/qa/guard_check.py:ro" \
    -v "$HARNESS/entry.py:/qa/entry.py:ro" \
    -v "$RDIR/artifacts:/artifacts:rw" --env-file "$envfile" ${QA_EXTRA_ENV:+--env-file "$QA_EXTRA_ENV"} \
    -w "$REPO/apps/api" python:3.12-slim "$REPO/apps/api/.venv/bin/python" "$@" || rc=$?
  rm -f "$envfile"; return "$rc"
}

require_proof() {    # every command that runs code or SQL requires a fresh isolation proof for THIS holder
  [[ -f "$RDIR/artifacts/preflight_isolation.json" ]] || die "run '$0 guard $RUN' first (no isolation proof)"
  local hid; hid="$(docker inspect -f '{{.Id}}' "$HOLD")"
  python3 - "$RDIR/artifacts/preflight_isolation.json" "$RUN" "$hid" <<'PY' || die "isolation proof missing/failed/stale for this holder"
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if d.get("all_ok") is True and d.get("run") == sys.argv[2] and d.get("hold_container_id") == sys.argv[3] else 1)
PY
}
runner() { require_proof; runner_raw /qa/entry.py "$@"; }     # entry.py re-checks strict isolation before running anything

assert_ours() {      # the target container is ours: name prefix + both labels
  local c="$1"
  [[ "$c" == qa-$RUN-* ]] || die "container $c is not ours"
  [[ "$(docker inspect -f '{{index .Config.Labels "qa.run"}}/{{index .Config.Labels "qa.disposable"}}' "$c")" == "$RUN/true" ]] || die "labels on $c do not match run $RUN"
}
assert_marker() {    # affirmative proof the database is the disposable one created by `up`
  assert_ours "$PG"
  [[ "$(docker exec -e PGPORT=$PGPORT_Q "$PG" psql -U hrms -d "$DB" -tA -c 'select run from qa.disposable')" == "$RUN" ]] || die "disposable marker in $DB is not '$RUN'"
}

case "$CMD" in
preflight)
  assert_qa_root
  echo "== resolved paths"; printf '  repo      %s\n  harness   %s\n  qa root   %s (device %s; / is device %s)\n  uv python %s\n' "$REPO" "$HARNESS" "$QA_ROOT" "$(stat -c %D "$(dirname "$QA_ROOT")")" "$(stat -c %D /)" "$UVPY"
  echo "== disk"; df -h / "$(dirname "$QA_ROOT")" | cat
  [[ $(root_free_kb) -ge $ROOT_MIN_KB ]] && echo "root OK (>= 3 GiB)" || die "root free below 3 GiB"
  [[ $(df --output=avail -k "$(dirname "$QA_ROOT")" | tail -1 | tr -d ' ') -ge $QA_MIN_KB ]] && echo "qa volume OK (>= 20 GiB)" || die "QA volume free below 20 GiB"
  echo "== run directory must not exist yet"; [[ ! -e "$RDIR" ]] && echo "  $RDIR absent" || die "$RDIR already exists (refusing to reuse data)"
  echo "== name collisions"; ! docker ps -a --format '{{.Names}}' | grep -E "^qa-$RUN-" || die "container names in use"; echo none
  echo "== images present locally (no pull will occur)"
  for i in postgres:16-alpine redis:7-alpine pgsty/silo:latest pgsty/mc:latest python:3.12-slim alpine:latest; do
    docker image inspect "$i" >/dev/null 2>&1 && echo "  ok $i" || die "image missing: $i"; done
  echo "== masked env files"; mask_args | awk 'NR%2==0' | sed 's#^/dev/null:##; s#:ro$##; s#^#  #'
  echo "== nothing below is published or shared: no -p, no docker.sock, no host/bridge network, no named volumes"
  ;;
up)
  "$0" preflight "$RUN"
  trap 'echo "INTERRUPTED/FAILED: partial resources (if any) carry label qa.run='"$RUN"'; clean with: $0 down '"$RUN"' --confirm" >&2' ERR INT TERM
  mkdir -p "$RDIR/pgdata" "$RDIR/minio" "$RDIR/artifacts" "$RDIR/logs"; assert_qa_root
  docker run -d --name "$HOLD" --network none "${LABELS[@]}" "${LOGOPT[@]}" --memory 16m alpine:latest sleep 2147483647 >/dev/null
  docker run --rm --network none "${LABELS[@]}" -v "$RDIR/pgdata:/d" alpine:latest chown 70:70 /d
  docker run --rm --network none "${LABELS[@]}" -v "$RDIR/artifacts:/d" alpine:latest chown "$(id -u):$(id -g)" /d
  docker run -d --name "$PG" --network "container:$HOLD" "${LABELS[@]}" "${LOGOPT[@]}" --memory 512m \
    -e POSTGRES_USER=hrms -e POSTGRES_PASSWORD="$PGPW" -e POSTGRES_DB="$DB" -e HRMS_APP_PASSWORD="$APPPW" \
    -v "$RDIR/pgdata:/var/lib/postgresql/data" -v "$REPO/infra/docker/postgres/init:/docker-entrypoint-initdb.d:ro" \
    postgres:16-alpine -c port=$PGPORT_Q -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null
  docker run -d --name "$RD" --network "container:$HOLD" "${LABELS[@]}" "${LOGOPT[@]}" --memory 192m --tmpfs /data:rw,size=64m redis:7-alpine \
    redis-server --port $RDPORT_Q --bind 127.0.0.1 --save "" --appendonly no >/dev/null
  docker run -d --name "$MN" --network "container:$HOLD" "${LABELS[@]}" "${LOGOPT[@]}" --memory 512m \
    -e MINIO_ROOT_USER="$MINIO_USER" -e MINIO_ROOT_PASSWORD="$MINIO_PW" -v "$RDIR/minio:/data" \
    pgsty/silo:latest server /data --address "127.0.0.1:$S3PORT_Q" --console-address "127.0.0.1:19001" >/dev/null
  for i in $(seq 1 90); do docker exec "$PG" pg_isready -p $PGPORT_Q -U hrms -d "$DB" >/dev/null 2>&1 && break; sleep 1; done
  docker exec "$PG" pg_isready -p $PGPORT_Q -U hrms -d "$DB"
  docker exec "$RD" redis-cli -p $RDPORT_Q ping
  for i in $(seq 1 60); do docker exec "$MN" bash -c "timeout 1 bash -c '</dev/tcp/127.0.0.1/$S3PORT_Q'" >/dev/null 2>&1 && break; sleep 1; done
  docker run --rm --network "container:$HOLD" "${LABELS[@]}" --entrypoint /bin/sh pgsty/mc:latest -c \
    "mc alias set local http://127.0.0.1:$S3PORT_Q $MINIO_USER $MINIO_PW && mc mb --ignore-existing local/$BUCKET && mc anonymous set none local/$BUCKET"
  # disposable marker lives in its own schema so it never appears in `public` schema audits
  docker exec -e PGPORT=$PGPORT_Q "$PG" psql -U hrms -d "$DB" -v ON_ERROR_STOP=1 -c \
    "CREATE SCHEMA qa; CREATE TABLE qa.disposable(run text PRIMARY KEY, created timestamptz DEFAULT now()); INSERT INTO qa.disposable(run) VALUES ('$RUN');"
  trap - ERR INT TERM
  echo "UP: run=$RUN db=$DB holder=$HOLD dir=$RDIR   (nothing published; next: $0 guard $RUN)"
  ;;
status)
  docker ps -a --filter "label=qa.run=$RUN" --format '{{.Names}}\t{{.Status}}\t{{.Image}}'
  du -sh "$RDIR" 2>/dev/null || true; echo "root free KiB: $(root_free_kb)"
  ;;
guard)
  assert_ours "$HOLD"
  ge="$(mktemp)"; chmod 600 "$ge"
  printf 'SHARED_NAMES=%s\nSHARED_IPS=%s\nHOST_IPS=%s\n' "hrms-postgres,hrms-redis,hrms-minio" \
    "$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' hrms-postgres hrms-redis hrms-minio | tr -s ' \n' ',')" \
    "$(hostname -I | tr -s ' ' ',')" > "$ge"
  rc=0; QA_EXTRA_ENV="$ge" runner_raw /qa/guard_check.py || rc=$?; rm -f "$ge"; exit $rc
  ;;
migrate)
  runner -m alembic -c alembic.ini heads
  runner -m alembic -c alembic.ini upgrade head
  runner -m alembic -c alembic.ini current
  ;;
rerun-role-script)
  [[ "${1:-}" == "--authorise-grant-change" ]] || die "this CHANGES grants of the disposable DB; add --authorise-grant-change only with explicit approval"
  require_proof; assert_marker
  docker exec -e PGPORT=$PGPORT_Q -e POSTGRES_USER=hrms -e POSTGRES_DB="$DB" -e HRMS_APP_PASSWORD="$APPPW" "$PG" sh /docker-entrypoint-initdb.d/002_app_role.sh
  ;;
usage-probe-install)  # NOT read-only: DDL (table, function, triggers on 3 public tables) + inserts. Needs its own explicit authorisation.
  [[ "${1:-}" == "--authorise-schema-change" ]] || die "usage-probe-install creates a table, a function and triggers (DDL) - not read-only; use stats-snapshot instead, or add --authorise-schema-change with explicit approval"
  require_proof; assert_marker
  docker exec -i -e PGPORT=$PGPORT_Q "$PG" psql -U hrms -d "$DB" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS qa.probe(id bigserial PRIMARY KEY, ts timestamptz DEFAULT now(), tbl text, op text, query text, app text, usr text);
CREATE OR REPLACE FUNCTION qa.probe_fn() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, qa AS $f$
BEGIN
  INSERT INTO qa.probe(tbl, op, query, app, usr) VALUES (TG_TABLE_NAME, TG_OP, left(current_query(), 400), current_setting('application_name'), session_user);
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSIF TG_OP = 'UPDATE' THEN RETURN NEW; END IF; RETURN NULL;
END $f$;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['punch','attendance_regularization_action','attendance_period_action'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS qa_probe_row ON public.%I', t);
  EXECUTE format('CREATE TRIGGER qa_probe_row BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION qa.probe_fn()', t);
  EXECUTE format('DROP TRIGGER IF EXISTS qa_probe_trunc ON public.%I', t);
  EXECUTE format('CREATE TRIGGER qa_probe_trunc BEFORE TRUNCATE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION qa.probe_fn()', t);
END LOOP; END $$;
SQL
  ;;
stats-snapshot)   # strictly READ-ONLY: Postgres' own per-table write counters (session forced read-only)
  require_proof; assert_marker
  sleep 2   # statistics are flushed asynchronously
  docker exec -e PGPORT=$PGPORT_Q -e PGOPTIONS="-c default_transaction_read_only=on" "$PG" psql -U hrms -d "$DB" -P pager=off -tA -F '|' -c \
    "select relname, n_tup_ins, n_tup_upd, n_tup_del, n_tup_hot_upd, n_live_tup from pg_stat_user_tables where relname in ('punch','attendance_regularization_action','attendance_period_action','attendance_regularization_request','attendance_period','attendance_day','audit_log','leave_ledger','leave_application','leave_application_action','leave_day_projection') order by 1"
  ;;
usage-probe-report)
  require_proof; assert_marker
  docker exec -e PGPORT=$PGPORT_Q "$PG" psql -U hrms -d "$DB" -P pager=off -c "select tbl, op, left(query,110) as query, count(*) n from qa.probe group by 1,2,3 order by 4 desc"
  ;;
pytest) runner -m pytest -p no:cacheprovider "$@" ;;
py)     runner "$@" ;;
psql)   require_proof; assert_marker; docker exec -e PGPORT=$PGPORT_Q "$PG" psql -U hrms -d "$DB" -v ON_ERROR_STOP=1 -P pager=off -c "$1" ;;
down)
  [[ "${1:-}" == "--confirm" ]] || die "add --confirm to remove resources labelled qa.run=$RUN"
  assert_qa_root
  mapfile -t found < <(docker ps -a --filter "label=qa.run=$RUN" --filter "label=qa.disposable=true" --format '{{.ID}} {{.Names}}')
  for line in "${found[@]:-}"; do [[ -z "$line" ]] && continue; [[ "${line#* }" == qa-$RUN-* ]] || die "labelled container with foreign name: $line (nothing removed)"; done
  for line in "${found[@]:-}"; do [[ -z "$line" ]] && continue; docker rm -f "${line%% *}" >/dev/null; done
  if [[ -d "$RDIR" ]]; then
    docker run --rm --network none "${LABELS[@]}" -v "$RDIR:/d" alpine:latest sh -c 'rm -rf /d/pgdata /d/minio'
  fi
  echo "removed this run's containers and its pgdata/minio dirs; artifacts kept in $RDIR/artifacts"
  ;;
*) sed -n 2,26p "$0"; exit 2;;
esac
