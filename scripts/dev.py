#!/usr/bin/env python3
"""Start local HRMS stack: Docker (Postgres, Redis, MinIO) + FastAPI API + Next.js web.

Usage: python3 scripts/dev.py   or   ./scripts/dev.py
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "apps" / "api"
WEB_DIR = ROOT / "apps" / "web"
LOG_DIR = ROOT / ".dev-logs"
COMPOSE_FILE = ROOT / "docker-compose.yml"

API_VENV_PYTHON = API_DIR / ".venv" / "bin" / "python"
API_PORT = 8000
WEB_PORT = 3000

processes: list[subprocess.Popen] = []
shutting_down = False


def log(msg: str) -> None:
    print(f"\n[{time.strftime('%H:%M:%S')}] {msg}")


def die(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def require_cmd(name: str) -> None:
    if shutil.which(name) is None:
        die(f"Missing required command: {name}")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check)


def resolve_docker_compose() -> list[str]:
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    die("Docker Compose is required (install Docker Desktop or the docker-compose plugin)")
    raise SystemExit  # unreachable, keeps type-checkers happy


def wait_for_postgres(compose_cmd: list[str]) -> None:
    log("Waiting for Postgres on localhost:5433...")
    for _ in range(60):
        result = subprocess.run(
            [*compose_cmd, "-f", str(COMPOSE_FILE), "exec", "-T", "postgres", "pg_isready", "-U", "hrms", "-d", "hrms_dev"],
            capture_output=True,
        )
        if result.returncode == 0:
            log("Postgres is ready")
            return
        time.sleep(1)
    die("Postgres did not become ready within 60s")


def start_infrastructure(compose_cmd: list[str]) -> None:
    log("Starting Docker services (postgres, redis, minio)...")
    run([*compose_cmd, "-f", str(COMPOSE_FILE), "up", "-d"])
    wait_for_postgres(compose_cmd)


def setup_api() -> None:
    log("Setting up API (uv sync, migrations)...")
    env_file = API_DIR / ".env"
    if not env_file.exists():
        shutil.copyfile(API_DIR / ".env.example", env_file)
        log("Created apps/api/.env from .env.example")

    require_cmd("uv")
    run(["uv", "sync", "--all-groups"], cwd=API_DIR)

    if not API_VENV_PYTHON.exists():
        die(f"Expected venv Python at {API_VENV_PYTHON} after 'uv sync' — check apps/api/.venv")

    # Invoke alembic via the venv's own Python (not "uv run" / bare "alembic") so migrations
    # can't accidentally pick up an unrelated Python on PATH (e.g. an active conda env).
    run([str(API_VENV_PYTHON), "-m", "alembic", "upgrade", "head"], cwd=API_DIR)


def setup_web() -> None:
    log("Setting up web (npm install)...")
    env_file = WEB_DIR / ".env.local"
    if not env_file.exists():
        shutil.copyfile(WEB_DIR / ".env.local.example", env_file)
        log("Created apps/web/.env.local from .env.local.example")

    if not (WEB_DIR / "node_modules").exists():
        run(["npm", "install"], cwd=WEB_DIR)


def stream_output(name: str, proc: subprocess.Popen, log_path: Path) -> None:
    with open(log_path, "a") as log_file:
        assert proc.stdout is not None
        for line in proc.stdout:
            log_file.write(line)
            log_file.flush()
            if not shutting_down:
                print(f"[{name}] {line}", end="")


def start_process(name: str, cmd: list[str], cwd: Path, log_path: Path) -> subprocess.Popen:
    log_path.write_text("")
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # New session/process-group so shutdown() can kill grandchildren too — e.g. "npm run
        # dev" spawns "next-server" as a child that survives if only the npm process is signaled.
        start_new_session=True,
    )
    processes.append(proc)
    threading.Thread(target=stream_output, args=(name, proc, log_path), daemon=True).start()
    return proc


def wait_for_url(url: str, name: str) -> None:
    for _ in range(45):
        try:
            urllib.request.urlopen(url, timeout=2)
            log(f"{name} is responding at {url}")
            return
        except Exception:
            time.sleep(1)
    log(f"Warning: {name} did not respond at {url} yet — check {LOG_DIR}")


def shutdown(*_args) -> None:
    global shutting_down
    if shutting_down:
        return
    shutting_down = True
    log("Stopping dev servers (Ctrl+C again to force)...")
    for proc in processes:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.time() + 10
    for proc in processes:
        remaining = max(0, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    sys.exit(0)


def main() -> None:
    require_cmd("docker")
    require_cmd("uv")
    require_cmd("node")
    require_cmd("npm")

    LOG_DIR.mkdir(exist_ok=True)

    compose_cmd = resolve_docker_compose()
    start_infrastructure(compose_cmd)

    setup_api()
    setup_web()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log(f"Starting FastAPI on http://localhost:{API_PORT} ...")
    start_process(
        "api",
        [str(API_VENV_PYTHON), "-m", "uvicorn", "entrypoints.api:app", "--reload", "--host", "0.0.0.0", "--port", str(API_PORT)],
        API_DIR,
        LOG_DIR / "api.log",
    )

    log(f"Starting Next.js on http://localhost:{WEB_PORT} ...")
    start_process("web", ["npm", "run", "dev"], WEB_DIR, LOG_DIR / "web.log")

    time.sleep(2)
    wait_for_url(f"http://localhost:{API_PORT}/health", "API")
    wait_for_url(f"http://localhost:{WEB_PORT}", "Web")

    print(f"""
{'━' * 50}
  HRMS local stack is running

  Frontend   http://localhost:{WEB_PORT}
  API        http://localhost:{API_PORT}
  API docs   http://localhost:{API_PORT}/docs
  MinIO UI   http://localhost:9001

  Logs       {LOG_DIR / 'api.log'}
             {LOG_DIR / 'web.log'}

  Press Ctrl+C to stop API and web (Docker keeps running).
  Stop Docker: docker compose down
{'━' * 50}
""")

    # Keep the main thread alive until a child process exits or Ctrl+C is pressed.
    while not shutting_down:
        for proc in processes:
            code = proc.poll()
            if code is not None and not shutting_down:
                log(f"Process exited unexpectedly (code {code}) — shutting down")
                shutdown()
        time.sleep(1)


if __name__ == "__main__":
    main()
