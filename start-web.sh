#!/usr/bin/env bash
# Start the web stack: Docker infra (Postgres/Redis/MinIO) + FastAPI (:8000) + Next.js (:3000).
# Ctrl+C stops API and web (Docker keeps running; `npm run dev:down` stops it).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/.dev-logs"; mkdir -p "$LOG_DIR"

# Don't let an active conda env shadow the project's Python 3.12.
unset CONDA_PREFIX CONDA_DEFAULT_ENV VIRTUAL_ENV
PIDS=()
trap 'echo; echo "Stopping API and web..."; for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true' EXIT INT TERM

echo "Starting Docker services..."
docker compose -f "$ROOT/docker-compose.yml" up -d
until docker compose -f "$ROOT/docker-compose.yml" exec -T postgres pg_isready -U hrms -d hrms_dev >/dev/null 2>&1; do sleep 1; done

cd "$ROOT/apps/api"
[[ -f .env ]] || cp .env.example .env
uv sync --all-groups
uv run --no-sync python -m alembic upgrade head
uv run --no-sync python -m uvicorn entrypoints.api:app --reload --host 0.0.0.0 --port 8000 >"$LOG_DIR/api.log" 2>&1 &
PIDS+=("$!")

cd "$ROOT/apps/web"
[[ -f .env.local ]] || cp .env.local.example .env.local
[[ -d node_modules ]] || npm install
npm run dev >"$LOG_DIR/web.log" 2>&1 &
PIDS+=("$!")

cat <<MSG

  Web        http://localhost:3000
  API        http://localhost:8000   (docs: /docs)
  MinIO UI   http://localhost:9001
  Logs       $LOG_DIR/api.log, $LOG_DIR/web.log
  Ctrl+C to stop.
MSG
wait "${PIDS[@]}"
