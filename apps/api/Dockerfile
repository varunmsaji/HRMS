# syntax=docker/dockerfile:1

# Builder — installs uv and resolves the locked dependency set. Never part of the runtime image,
# so pip/uv and any build tools they pull in stay out of what actually ships to production.
FROM python:3.12-slim AS builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv

# Dependency-only layer, cached independently of application code changes. `--no-install-project`
# is required here: `pyproject.toml` declares `readme = "README.md"` and builds `hrms` itself as
# an editable install, so a `uv sync` before `src/`/`README.md` exist fails trying to build the
# local package — this was a real, previously-undiscovered bug in the pre-3B Dockerfile (never
# actually built via `docker build` before RELEASE_HARDENING_PHASE_3B's own verification).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra liveness --no-install-project
COPY src ./src
COPY entrypoints ./entrypoints
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
RUN uv sync --frozen --no-dev --extra liveness

# Face-liveness model assets (Apache-2.0, see models/liveness/minifasnet-v1/README.md). Shipped in
# every image but inert unless FACE_LIVENESS_ENGINE=minifasnet. The build fails here if a file is
# missing, differs from the SHA-256 pinned in liveness.py, or cannot be loaded — it never ships a
# model it has not verified. Runs in the builder, where the venv is not on PATH.
COPY models ./models
RUN /app/.venv/bin/python scripts/liveness/verify_assets.py models/liveness/minifasnet-v1

# Open-source face engine assets (YuNet MIT + SFace Apache-2.0; docs/operations/
# OPEN_SOURCE_FACE_ATTENDANCE_SETUP.md). OFF by default: Face++ images do not carry them and nothing
# downloads at runtime. `--build-arg FACE_OS_ASSETS=true` fetches them once at BUILD time and fails
# the build unless every file matches the SHA-256 pinned in opensource_face/assets.py. Still inert
# unless FACE_VERIFICATION_PROVIDER=opensource AND FACE_OS_ENABLED=true.
ARG FACE_OS_ASSETS=false
RUN if [ "$FACE_OS_ASSETS" = "true" ]; then \
      /app/.venv/bin/python scripts/face/fetch_opensource_assets.py models/face/opensource-v1 \
      && /app/.venv/bin/python -m hrms.modules.attendance.opensource_face.assets models/face/opensource-v1; \
    fi

# Runtime — a fresh stage, not derived from the builder, so uv/pip and apt's package cache never
# reach the image that actually runs in production (RELEASE_HARDENING_PHASE_3B §2).
FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    TZ=UTC

# Matches the non-root, dedicated-user pattern applied nowhere else needs changing — the
# application itself never requires root (no privileged port bind: uvicorn/gunicorn bind
# 0.0.0.0:8000, not <1024; Nginx is the only thing in this stack that terminates on 80/443).
RUN groupadd --gid 1000 hrms && useradd --uid 1000 --gid hrms --no-create-home --shell /usr/sbin/nologin hrms

COPY --from=builder --chown=hrms:hrms /app /app

# Local per-module log files (docs/operations/LOGGING_GUIDE.md). Created and owned by the
# runtime user so a named volume mounted here inherits writable ownership on first creation.
# Persistence across container re-creation needs that volume (docker-compose.prod.yml `api_logs`).
RUN mkdir -p /app/logs && chown hrms:hrms /app/logs
ENV LOG_DIR=/app/logs

# Prometheus multi-process metric files (docs/architecture/OBSERVABILITY_ARCHITECTURE.md). The
# directory exists and is writable by the runtime user; it is only *used* when a container sets
# PROMETHEUS_MULTIPROC_DIR (docker-compose.prod.yml shares one volume across api, worker, beat).
RUN mkdir -p /app/metrics && chown hrms:hrms /app/metrics

USER hrms

EXPOSE 8000

# Liveness-only probe (RELEASE_HARDENING_PHASE_3B §7) — deliberately hits /health/live, not
# /health/ready: a container healthcheck restarting the process because a *dependency* (Postgres/
# Redis) is briefly down would cause restart storms instead of letting the dependency recover.
# Readiness (dependency-aware) is a separate endpoint consumed by the orchestrator/load balancer,
# not by Docker's own healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"

# Default: API process, run under gunicorn (already a pinned dependency) with the uvicorn worker
# class — gunicorn's arbiter forwards SIGTERM to workers and waits up to --graceful-timeout before
# force-killing them, so in-flight requests finish cleanly on `docker stop`/rolling deploy.
# `exec` replaces the shell so gunicorn itself is PID 1 and receives signals directly (no
# intermediate `sh` swallowing them). Override `command:` in compose for worker/beat/ingestion —
# same image, four entrypoints (docs/product/13_DevOps_Architecture.md §2).
# No `--access-logfile`: the app emits one structured JSON `http_request` event per request
# (request id, route template, status, duration — `core/observability/request_context.py`), which
# replaces gunicorn/uvicorn's plaintext access line. Without it gunicorn's access logger has no
# handler, so that line is dropped rather than duplicated.
CMD ["sh", "-c", "exec gunicorn entrypoints.api:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-2} --timeout ${GUNICORN_TIMEOUT:-60} --graceful-timeout 30 --error-logfile -"]
