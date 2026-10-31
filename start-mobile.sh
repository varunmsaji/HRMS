#!/usr/bin/env bash
# Start the mobile stack: Docker infra + FastAPI (:8000) + light Android emulator + Flutter app.
# Usage: ./start-mobile.sh [avd-name]   (default AVD: Hirico_Light)
# Ctrl+C / 'q' stops the app, API and emulator (Docker keeps running).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/.dev-logs"; mkdir -p "$LOG_DIR"
AVD="${1:-Hirico_Light}"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
export PATH="$HOME/flutter/bin:$SDK/platform-tools:$PATH"

unset CONDA_PREFIX CONDA_DEFAULT_ENV VIRTUAL_ENV
PIDS=()
trap 'echo; echo "Stopping..."; adb emu kill >/dev/null 2>&1 || true; for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true' EXIT INT TERM

if docker compose version >/dev/null 2>&1; then
  DOCKER=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER=(docker-compose)
else
  echo "Docker Compose is required" >&2
  exit 1
fi

echo "Starting Docker services..."
"${DOCKER[@]}" -f "$ROOT/docker-compose.yml" up -d
until "${DOCKER[@]}" -f "$ROOT/docker-compose.yml" exec -T postgres pg_isready -U hrms -d hrms_dev >/dev/null 2>&1; do sleep 1; done

cd "$ROOT/apps/api"
[[ -f .env ]] || cp .env.example .env
uv sync --all-groups
uv run --no-sync python -m alembic upgrade head
uv run --no-sync python -m uvicorn entrypoints.api:app --host 0.0.0.0 --port 8000 >"$LOG_DIR/api.log" 2>&1 &
PIDS+=("$!")
until curl -fsS localhost:8000/health >/dev/null 2>&1; do sleep 1; done
echo "API is up on :8000"

if ! adb devices | grep -q "emulator-.*device$"; then
  echo "Starting emulator $AVD (low-memory, software rendering)..."
  "$SDK/emulator/emulator" -avd "$AVD" -no-snapshot-save -no-boot-anim -no-audio \
    -gpu swiftshader_indirect -memory 1536 -cores 2 >"$LOG_DIR/emulator.log" 2>&1 &
  PIDS+=("$!")
fi
echo "Waiting for emulator to boot..."
until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do sleep 3; done

cd "$ROOT/apps/mobile"
flutter pub get >/dev/null
# Foreground so you get hot reload (r), hot restart (R) and quit (q).
flutter run -d emulator-5554 --dart-define=API_BASE_URL=http://10.0.2.2:8000
