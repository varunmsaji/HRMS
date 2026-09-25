#!/usr/bin/env bash
# RELEASE_HARDENING_PHASE_3B §8 — scheduled PostgreSQL backup for the self-hosted VPS deployment.
# Runs `pg_dump` *inside* the running `postgres` container (via `docker compose exec`) so it never
# needs direct network exposure of Postgres's port, and never needs the database password on the
# host's own command line/shell history — it reads `POSTGRES_USER`/`POSTGRES_PASSWORD` from the
# container's own environment (the same values docker-compose.prod.yml already injected).
#
# Usage (see docs/deployment/PRODUCTION_DEPLOYMENT.md for cron setup):
#   BACKUP_ROOT=/opt/hrms/backups ./infra/backup/pg_backup.sh
#
# Output: $BACKUP_ROOT/postgres/hrms_<UTC timestamp>.dump.gz (pg_dump custom format, `-Fc`,
# piped through gzip — custom format is already compressed internally at a lower ratio than a
# plain-SQL dump gzipped afterward, but this keeps the on-disk extension self-documenting and the
# retention/cleanup logic below agnostic to which of the two ever changes).
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:?BACKUP_ROOT must be set (e.g. /opt/hrms/backups)}"
RETENTION_DAYS="${PG_BACKUP_RETENTION_DAYS:-14}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"

BACKUP_DIR="${BACKUP_ROOT}/postgres"
LOG_FILE="${BACKUP_DIR}/backup.log"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
# `.partial` suffix, renamed only on success (below) — protects against a later restore ever
# picking up a truncated file from a backup run that crashed or was killed mid-dump (STEP 8: "no
# database credentials in scripts committed to Git" and "protection against accidental
# overwrite" — the timestamped, never-reused filename is the overwrite protection; this is the
# matching protection against a *partial* file masquerading as a complete one).
OUT_FILE="${BACKUP_DIR}/hrms_${TIMESTAMP}.dump.gz"
TMP_FILE="${OUT_FILE}.partial"

mkdir -p "${BACKUP_DIR}"

log() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "${LOG_FILE}"
}

# `docker compose` (plugin, v2) vs `docker-compose` (standalone binary) — same duality
# scripts/dev.py's own `resolve_docker_compose()` already handles for local dev.
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "Neither 'docker compose' nor 'docker-compose' is available" >&2
    exit 1
fi

cd "${COMPOSE_PROJECT_DIR}"

log "Starting Postgres backup -> ${OUT_FILE}"

if ! "${COMPOSE[@]}" -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    | gzip > "${TMP_FILE}"; then
    log "FAILED: pg_dump/gzip exited non-zero — removing partial file"
    rm -f "${TMP_FILE}"
    exit 1
fi

if [ ! -s "${TMP_FILE}" ]; then
    log "FAILED: backup file is empty — removing"
    rm -f "${TMP_FILE}"
    exit 1
fi

mv "${TMP_FILE}" "${OUT_FILE}"
SIZE=$(du -h "${OUT_FILE}" | cut -f1)
log "SUCCESS: ${OUT_FILE} (${SIZE})"

# Retention: delete completed backups (never `.partial` — those are already handled above)
# older than RETENTION_DAYS. `find -mtime` on the *completed* file's own mtime, set by `mv` above
# at completion time, not dump-start time.
DELETED=$(find "${BACKUP_DIR}" -maxdepth 1 -name 'hrms_*.dump.gz' -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
if [ "${DELETED}" -gt 0 ]; then
    log "Retention: deleted ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
fi
