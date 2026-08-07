#!/usr/bin/env bash
# Start local HRMS stack: Docker (Postgres, Redis, MinIO) + FastAPI API + Next.js web.
# Usage: ./scripts/dev.sh   or   npm run dev

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
WEB_DIR="$ROOT/apps/web"
LOG_DIR="$ROOT/.dev-logs"

PIDS=()
DOCKER_CMD=()

log() {
  printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

resolve_docker() {
  if docker compose version >/dev/null 2>&1; then
    DOCKER_CMD=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_CMD=(docker-compose)
  else
    die "Docker Compose is required (install Docker Desktop or docker-compose plugin)"
  fi
}

cleanup() {
  log "Stopping dev servers (Ctrl+C again to force)..."
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

wait_for_postgres() {
  local attempts=0
  local max=60
  log "Waiting for Postgres on localhost:5433..."
  while (( attempts < max )); do
    if "${DOCKER_CMD[@]}" -f "$ROOT/docker-compose.yml" exec -T postgres \
      pg_isready -U hrms -d hrms_dev >/dev/null 2>&1; then
      log "Postgres is ready"
      return 0
    fi
    sleep 1
    attempts=$((attempts + 1))
  done
  die "Postgres did not become ready within ${max}s"
}

start_infrastructure() {
  log "Starting Docker services (postgres, redis, minio)..."
  "${DOCKER_CMD[@]}" -f "$ROOT/docker-compose.yml" up -d
  wait_for_postgres
}

setup_api() {
  log "Setting up API (uv sync, migrations)..."
  cd "$API_DIR"

  if [[ ! -f .env ]]; then
    cp .env.example .env
    log "Created apps/api/.env from .env.example"
  fi

  uv sync --all-groups
  uv run alembic upgrade head
}

start_api() {
  log "Starting FastAPI on http://localhost:8000 ..."
  mkdir -p "$LOG_DIR"
  cd "$API_DIR"
  uv run uvicorn entrypoints.api:app --reload --host 0.0.0.0 --port 8000 \
    >"$LOG_DIR/api.log" 2>&1 &
  PIDS+=("$!")
}

setup_web() {
  log "Setting up web (npm install)..."
  cd "$WEB_DIR"

  if [[ ! -f .env.local ]]; then
    cp .env.local.example .env.local
    log "Created apps/web/.env.local from .env.local.example"
  fi

  if [[ ! -d node_modules ]]; then
    npm install
  fi
}

start_web() {
  log "Starting Next.js on http://localhost:3000 ..."
  mkdir -p "$LOG_DIR"
  cd "$WEB_DIR"
  npm run dev >"$LOG_DIR/web.log" 2>&1 &
  PIDS+=("$!")
}

wait_for_url() {
  local url="$1"
  local name="$2"
  local attempts=0
  local max=45
  while (( attempts < max )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name is responding at $url"
      return 0
    fi
    sleep 1
    attempts=$((attempts + 1))
  done
  log "Warning: $name did not respond at $url yet — check $LOG_DIR"
}

main() {
  require_cmd docker
  require_cmd uv
  require_cmd node
  require_cmd npm
  require_cmd curl

  resolve_docker
  mkdir -p "$LOG_DIR"

  start_infrastructure
  setup_api
  start_api
  setup_web
  start_web

  sleep 2
  wait_for_url "http://localhost:8000/health" "API" || true
  wait_for_url "http://localhost:3000" "Web" || true

  cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  HRMS local stack is running

  Frontend   http://localhost:3000
  API        http://localhost:8000
  API docs   http://localhost:8000/docs
  MinIO UI   http://localhost:9001

  Logs       $LOG_DIR/api.log
             $LOG_DIR/web.log

  Press Ctrl+C to stop API and web (Docker keeps running).
  Stop Docker: npm run dev:down
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EOF

  # Keep script alive until API or web exits, or user sends Ctrl+C
  wait "${PIDS[@]}"
}

main
