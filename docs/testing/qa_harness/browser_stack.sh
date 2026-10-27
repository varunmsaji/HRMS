#!/usr/bin/env bash
# Loopback-only disposable stack for browser tests.
#
# The hermetic QA harness (stack.sh) keeps Postgres inside a --network none namespace and
# publishes nothing, so a browser on this machine cannot reach it. This script does not change
# that harness, its memory limits, or its guards. It starts a separate pair of containers whose
# host ports are bound to 127.0.0.1 only, on ports that are not the shared development ports
# (Postgres 5433, Redis 6380, database hrms_dev).
#
#   browser_stack.sh up       <RUN_ID>
#   browser_stack.sh prove    <RUN_ID>     # writes isolation.json; required before migrate/serve
#   browser_stack.sh migrate  <RUN_ID>     # alembic + plan catalogue, disposable DB only
#   browser_stack.sh serve    <RUN_ID>     # API 127.0.0.1:18080 and web 127.0.0.1:13000
#   browser_stack.sh hash     <RUN_ID> <company-uuid>
#   browser_stack.sh psql     <RUN_ID> <sql>
#   browser_stack.sh verify-email <RUN_ID> <email>
#   browser_stack.sh link-employee <RUN_ID> <company-uuid> <employee-uuid> <email>
#   browser_stack.sh insert-protected <RUN_ID> <company-uuid> <legal-entity-uuid> <start> <end>
#   browser_stack.sh mark-pending <RUN_ID> <company-uuid> <YYYY-MM-DD>
#   browser_stack.sh e2e      <RUN_ID>     # prove, then playwright
#   browser_stack.sh down     <RUN_ID> --confirm
#
# Data lives under /media/varun/varun12/work/staff-spectrum/qa_runs/<RUN_ID>/ (mode 700).
# The env file there holds the disposable passwords. It is not in the git repo.
# Nothing here connects to hrms_dev. `down` removes only containers labelled for this RUN_ID.
set -euo pipefail

die() { echo "ABORT: $*" >&2; exit 3; }

CMD="${1:-}"; RUN="${2:-}"
[[ -n "$CMD" && -n "$RUN" ]] || { sed -n '4,22p' "$0"; exit 2; }
shift 2
[[ "$RUN" =~ ^browser-[a-z0-9][a-z0-9-]{2,32}$ ]] || die "RUN_ID must look like browser-cal5a"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
HARNESS="$REPO/docs/testing/qa_harness"
QA_ROOT="/media/varun/varun12/work/staff-spectrum/qa_runs"
RDIR="$QA_ROOT/$RUN"
PG="qa-$RUN-pg"
RD="qa-$RUN-redis"
DB="hrms_browser_${RUN//-/_}"
PG_PORT=15433
RD_PORT=16380
API_PORT=18080
WEB_PORT=13000
ENV_FILE="$RDIR/browser.env"
PY="$REPO/apps/api/.venv/bin/python"

for n in "$PG" "$RD"; do [[ "$n" == qa-browser-* ]] || die "non-browser name $n"; done
[[ "$DB" == hrms_browser_* && "$DB" != *hrms_dev* ]] || die "refusing database name $DB"
[[ "$PG_PORT" != 5433 && "$PG_PORT" != 5432 && "$RD_PORT" != 6380 && "$RD_PORT" != 6379 ]] || die "refusing a shared port"

assert_root() {
  local parent; parent="$(dirname "$QA_ROOT")"
  [[ "$(readlink -f "$parent")" == /media/varun/varun12/work/staff-spectrum ]] || die "QA root parent moved"
  [[ "$(stat -c %D "$parent")" != "$(stat -c %D /)" ]] || die "QA root is on the root filesystem"
  [[ ! -L "$QA_ROOT" && ! -L "$RDIR" ]] || die "symlinked QA path"
}

load_env() {
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE (run up first)"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  [[ "${DATABASE_URL:-}" == *"127.0.0.1:${PG_PORT}/${DB}"* ]] || die "DATABASE_URL is not the disposable database"
  [[ "${DATABASE_URL}" != *hrms_dev* && "${DATABASE_URL}" != *":5433/"* && "${DATABASE_URL}" != *":6380/"* ]] || die "DATABASE_URL points at a shared service"
  [[ "${REDIS_URL:-}" == "redis://127.0.0.1:${RD_PORT}/2" ]] || die "REDIS_URL is not the disposable redis"
  [[ "${MIGRATIONS_DATABASE_URL:-}" == *"127.0.0.1:${PG_PORT}/${DB}"* ]] || die "MIGRATIONS_DATABASE_URL is not the disposable database"
  [[ "${MIGRATIONS_DATABASE_URL}" != *hrms_dev* ]] || die "migrations URL points at hrms_dev"
}

case "$CMD" in
up)
  assert_root
  [[ ! -e "$RDIR" ]] || die "$RDIR already exists (refusing to reuse data)"
  docker image inspect postgres:16-alpine >/dev/null 2>&1 || die "image missing: postgres:16-alpine"
  docker image inspect redis:7-alpine >/dev/null 2>&1 || die "image missing: redis:7-alpine"
  ! docker ps -a --format '{{.Names}}' | grep -E "^qa-${RUN}-" >/dev/null || die "container names in use"
  if command -v ss >/dev/null 2>&1; then
    busy="$(ss -ltn | awk '{print $4}' | grep -E ":${PG_PORT}$|:${RD_PORT}$|:${API_PORT}$|:${WEB_PORT}$" || true)"
    [[ -z "$busy" ]] || die "a required port is already listening: $busy"
  fi
  mkdir -p "$RDIR/pgdata" "$RDIR/artifacts" "$RDIR/logs"
  chmod 700 "$RDIR"
  OWNER_PW="browser_owner_${RUN}_$(openssl rand -hex 8)"
  APP_PW="browser_app_${RUN}_$(openssl rand -hex 8)"
  umask 077
  cat > "$ENV_FILE" <<ENV
ENVIRONMENT=development
TZ=UTC
COMPANY_APPROVAL_REQUIRED=false
DATABASE_URL=postgresql://hrms_app:${APP_PW}@127.0.0.1:${PG_PORT}/${DB}
MIGRATIONS_DATABASE_URL=postgresql://hrms:${OWNER_PW}@127.0.0.1:${PG_PORT}/${DB}
REDIS_URL=redis://127.0.0.1:${RD_PORT}/2
CELERY_BROKER_URL=redis://127.0.0.1:${RD_PORT}/15
CELERY_RESULT_BACKEND=redis://127.0.0.1:${RD_PORT}/15
JWT_ACCESS_SECRET=browser-access-secret-min-16
JWT_REFRESH_SECRET=browser-refresh-secret-min-16
WEB_APP_BASE_URL=http://127.0.0.1:${WEB_PORT}
CORS_ALLOWED_ORIGINS=http://127.0.0.1:${WEB_PORT}
EMAIL_PROVIDER=logging
FACE_VERIFICATION_PROVIDER=disabled
FACE_LIVENESS_ENGINE=disabled
FACEPP_API_KEY=
FACEPP_API_SECRET=
S3_ENDPOINT_URL=http://127.0.0.1:9
S3_BUCKET_DOCUMENTS=browser-unused
AWS_ACCESS_KEY_ID=browser
AWS_SECRET_ACCESS_KEY=browser
AWS_REGION=ap-south-1
LOG_TO_FILES=false
E2E_API_URL=http://127.0.0.1:${API_PORT}
E2E_WEB_URL=http://127.0.0.1:${WEB_PORT}
E2E_RUN_ID=${RUN}
E2E_ARTIFACTS=${RDIR}/artifacts
ENV
  chmod 600 "$ENV_FILE"
  docker run -d --name "$PG" \
    --label qa.disposable=true --label "qa.run=$RUN" --label qa.purpose=browser \
    -p "127.0.0.1:${PG_PORT}:5432" \
    -e POSTGRES_USER=hrms -e POSTGRES_PASSWORD="$OWNER_PW" -e POSTGRES_DB="$DB" \
    -e HRMS_APP_PASSWORD="$APP_PW" \
    -v "$RDIR/pgdata:/var/lib/postgresql/data" \
    -v "$REPO/infra/docker/postgres/init:/docker-entrypoint-initdb.d:ro" \
    --memory 512m \
    postgres:16-alpine \
    -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null
  docker run -d --name "$RD" \
    --label qa.disposable=true --label "qa.run=$RUN" --label qa.purpose=browser \
    -p "127.0.0.1:${RD_PORT}:6379" \
    --memory 192m \
    redis:7-alpine redis-server --bind 0.0.0.0 --save "" --appendonly no >/dev/null
  for _ in $(seq 1 90); do
    docker exec "$PG" pg_isready -U hrms -d "$DB" >/dev/null 2>&1 && break
    sleep 1
  done
  docker exec "$PG" pg_isready -U hrms -d "$DB"
  docker exec "$PG" psql -U hrms -d "$DB" -v ON_ERROR_STOP=1 -c \
    "CREATE SCHEMA IF NOT EXISTS qa; CREATE TABLE IF NOT EXISTS qa.disposable(run text PRIMARY KEY, created timestamptz DEFAULT now()); INSERT INTO qa.disposable(run) VALUES ('$RUN') ON CONFLICT DO NOTHING;"
  echo "UP: run=$RUN db=$DB pg=127.0.0.1:$PG_PORT redis=127.0.0.1:$RD_PORT dir=$RDIR"
  echo "Next: $0 prove $RUN && $0 migrate $RUN && $0 serve $RUN"
  ;;
prove)
  load_env
  bind="$(docker port "$PG" 5432)"
  [[ "$bind" == 127.0.0.1:* ]] || die "postgres is not bound to loopback only: $bind"
  rdbind="$(docker port "$RD" 6379)"
  [[ "$rdbind" == 127.0.0.1:* ]] || die "redis is not bound to loopback only: $rdbind"
  [[ "$bind" != *":5433" && "$rdbind" != *":6380" ]] || die "published port is a shared development port"
  marker="$(docker exec "$PG" psql -U hrms -d "$DB" -tA -c 'select run from qa.disposable')"
  [[ "$marker" == "$RUN" ]] || die "disposable marker is '$marker', expected '$RUN'"
  load_env
  PYTHONPATH="$REPO/apps/api/src" "$PY" "$HARNESS/browser_support.py" prove "$RUN" "$RDIR/artifacts/isolation.json"
  ;;
migrate)
  load_env
  [[ -f "$RDIR/artifacts/isolation.json" ]] || die "run prove first"
  PYTHONPATH="$REPO/apps/api/src" "$PY" "$HARNESS/browser_support.py" assert-proven "$RDIR/artifacts/isolation.json" "$RUN"
  (
    cd "$REPO/apps/api"
    export DATABASE_URL="$MIGRATIONS_DATABASE_URL"
    [[ "$DATABASE_URL" == *"/${DB}"* && "$DATABASE_URL" != *hrms_dev* ]] || die "refusing to migrate"
    "$PY" -m alembic -c alembic.ini upgrade head
    "$PY" scripts/seed_plans.py
  )
  echo "MIGRATED: $DB"
  ;;
serve)
  load_env
  PYTHONPATH="$REPO/apps/api/src" "$PY" "$HARNESS/browser_support.py" assert-proven "$RDIR/artifacts/isolation.json" "$RUN"
  if [[ -f "$RDIR/api.pid" ]] && kill -0 "$(cat "$RDIR/api.pid")" 2>/dev/null; then
    echo "API already running (pid $(cat "$RDIR/api.pid"))"
  else
  (
    cd "$REPO/apps/api"
    set -a; source "$ENV_FILE"; set +a
    exec "$PY" -m uvicorn entrypoints.api:app --host 127.0.0.1 --port "$API_PORT"
  ) >>"$RDIR/logs/api.log" 2>&1 &
  echo $! > "$RDIR/api.pid"
  fi
  if [[ -f "$RDIR/web.pid" ]] && kill -0 "$(cat "$RDIR/web.pid")" 2>/dev/null; then
    echo "web already running (pid $(cat "$RDIR/web.pid"))"
  else
  (
    cd "$REPO/apps/web"
    export NEXT_PUBLIC_API_URL="http://127.0.0.1:${API_PORT}"
    export NEXT_DIST_DIR=".next-e2e"
    exec npx next dev --hostname 127.0.0.1 --port "$WEB_PORT" --webpack
  ) >>"$RDIR/logs/web.log" 2>&1 &
  echo $! > "$RDIR/web.pid"
  fi
  for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:${API_PORT}/health/ready" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -sf "http://127.0.0.1:${API_PORT}/health/ready" >/dev/null || die "API did not become ready; see $RDIR/logs/api.log"
  for _ in $(seq 1 90); do
    curl -sf -o /dev/null "http://127.0.0.1:${WEB_PORT}/login" && break
    sleep 1
  done
  curl -sf -o /dev/null "http://127.0.0.1:${WEB_PORT}/login" || die "web did not become ready; see $RDIR/logs/web.log"
  ss -ltn | awk '{print $4}' | grep -E ":${API_PORT}$" | grep -v '127.0.0.1' && die "API is not loopback-only" || true
  echo "SERVING: api=http://127.0.0.1:${API_PORT} web=http://127.0.0.1:${WEB_PORT}"
  ;;
hash|verify-email|link-employee|insert-protected|mark-pending)
  load_env
  PYTHONPATH="$REPO/apps/api/src${PYTHONPATH:+:$PYTHONPATH}" "$PY" "$HARNESS/browser_support.py" "$CMD" "$@"
  ;;
psql)
  load_env
  sql="${1:-}"
  [[ -n "$sql" ]] || die "SQL required"
  # Read-only guard: browser tests pass explicit statements through browser_support instead.
  # This command is for inspection and refuses anything that is not a single SELECT or WITH.
  [[ "$sql" =~ ^[[:space:]]*(SELECT|WITH)[[:space:]] ]] || die "psql helper accepts only SELECT/WITH"
  docker exec "$PG" psql -U hrms -d "$DB" -v ON_ERROR_STOP=1 -c "$sql"
  ;;
e2e)
  load_env
  PYTHONPATH="$REPO/apps/api/src" "$PY" "$HARNESS/browser_support.py" assert-proven "$RDIR/artifacts/isolation.json" "$RUN"
  curl -sf "http://127.0.0.1:${API_PORT}/health/ready" >/dev/null || die "API is not ready"
  curl -sf -o /dev/null "http://127.0.0.1:${WEB_PORT}/login" || die "web is not ready"
  cd "$REPO/apps/web"
  export E2E_API_URL E2E_WEB_URL E2E_RUN_ID E2E_ARTIFACTS
  export E2E_STACK="$HARNESS/browser_stack.sh"
  npx playwright test -c playwright.config.ts
  ;;
down)
  [[ "${1:-}" == "--confirm" ]] || die "down removes this run's containers; pass --confirm"
  if [[ -f "$RDIR/api.pid" ]]; then
    pid="$(cat "$RDIR/api.pid")"
    if [[ -d "/proc/$pid" ]] && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "port ${API_PORT}"; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$RDIR/api.pid"
  fi
  if [[ -f "$RDIR/web.pid" ]]; then
    pid="$(cat "$RDIR/web.pid")"
    if [[ -d "/proc/$pid" ]] && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "port ${WEB_PORT}"; then
      kill "$pid" 2>/dev/null || true
      # next dev may leave a child; stop only children whose command line includes this port
      pkill -P "$pid" 2>/dev/null || true
    fi
    rm -f "$RDIR/web.pid"
  fi
  sleep 1
  for c in $(docker ps -aq --filter "label=qa.run=$RUN" --filter "label=qa.purpose=browser"); do
    name="$(docker inspect -f '{{.Name}}' "$c")"
    [[ "$name" == "/qa-$RUN-"* ]] || die "refusing to remove $name"
    docker rm -f "$c" >/dev/null
  done
  echo "DOWN: removed containers for $RUN. Data dir left at $RDIR (delete it by hand if you want the bytes gone)."
  ;;
*)
  die "unknown command $CMD"
  ;;
esac
