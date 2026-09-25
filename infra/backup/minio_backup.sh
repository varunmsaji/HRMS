#!/usr/bin/env bash
# RELEASE_HARDENING_PHASE_3B §9 — scheduled MinIO (document storage) backup for the self-hosted
# VPS deployment. Postgres holds *references* to documents (employee.<doc>_document_key columns
# etc pointing at S3 object keys); MinIO holds the actual bytes — a Postgres-only backup strategy
# would restore a database full of dangling references to objects that no longer exist. This
# script and pg_backup.sh are both required, not either/or (STEP 9: "Do not treat PostgreSQL
# backup as sufficient").
#
# Uses `mc mirror` (the same `minio/mc` image already used by the `minio-init` compose service)
# to copy every object in the documents bucket to a dated local directory — not a live second
# MinIO instance, since a single-VPS deployment has nowhere else to mirror to without adding a
# paid external destination (see docs/deployment/PRODUCTION_DEPLOYMENT.md for the tradeoff this
# implies, and the off-VPS-copy requirement in the disaster-recovery doc).
#
# Usage:
#   BACKUP_ROOT=/opt/hrms/backups ./infra/backup/minio_backup.sh
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:?BACKUP_ROOT must be set (e.g. /opt/hrms/backups)}"
RETENTION_DAYS="${MINIO_BACKUP_RETENTION_DAYS:-14}"
MINIO_SERVICE="${MINIO_SERVICE:-minio}"

BACKUP_DIR="${BACKUP_ROOT}/minio"
LOG_FILE="${BACKUP_DIR}/backup.log"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SNAPSHOT_DIR="${BACKUP_DIR}/snapshot_${TIMESTAMP}"
ARCHIVE_FILE="${BACKUP_DIR}/hrms_minio_${TIMESTAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

log() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "${LOG_FILE}"
}

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    log "FAILED: neither 'docker compose' nor 'docker-compose' is available"
    exit 1
fi

cd "${COMPOSE_PROJECT_DIR}"

if [ -z "${MINIO_ROOT_USER:-}" ] || [ -z "${MINIO_ROOT_PASSWORD:-}" ] || [ -z "${MINIO_BUCKET_DOCUMENTS:-}" ]; then
    if [ -f .env ]; then
        # shellcheck disable=SC1091
        set -a; . ./.env; set +a
    fi
fi
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER must be set (exported, or present in ./.env)}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD must be set (exported, or present in ./.env)}"
: "${MINIO_BUCKET_DOCUMENTS:?MINIO_BUCKET_DOCUMENTS must be set (exported, or present in ./.env)}"

log "Starting MinIO backup of bucket '${MINIO_BUCKET_DOCUMENTS}' -> ${ARCHIVE_FILE}"

mkdir -p "${SNAPSHOT_DIR}"

# Run `mc` as a one-off container on the same compose network as `minio` (not the long-lived
# `minio-init` service) so this script needs no `mc` binary on the host itself — matches how
# `minio-init` already talks to MinIO in both docker-compose.yml (dev) and docker-compose.prod.yml.
if ! "${COMPOSE[@]}" -f "${COMPOSE_FILE}" run --rm -T \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "${SNAPSHOT_DIR}:/backup" \
    --entrypoint /bin/sh \
    minio-init -c "
        mc alias set local http://${MINIO_SERVICE}:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}' &&
        mc mirror --quiet local/${MINIO_BUCKET_DOCUMENTS} /backup
    "; then
    log "FAILED: mc mirror exited non-zero"
    rm -rf "${SNAPSHOT_DIR}"
    exit 1
fi

# Compress the snapshot directory into a single dated archive, then discard the uncompressed copy
# — matches pg_backup.sh's own "one file per run" retention model below.
tar -C "${SNAPSHOT_DIR}" -czf "${ARCHIVE_FILE}.partial" .
rm -rf "${SNAPSHOT_DIR}"

if [ ! -s "${ARCHIVE_FILE}.partial" ]; then
    log "FAILED: archive is empty — removing"
    rm -f "${ARCHIVE_FILE}.partial"
    exit 1
fi

mv "${ARCHIVE_FILE}.partial" "${ARCHIVE_FILE}"
SIZE=$(du -h "${ARCHIVE_FILE}" | cut -f1)
log "SUCCESS: ${ARCHIVE_FILE} (${SIZE})"

DELETED=$(find "${BACKUP_DIR}" -maxdepth 1 -name 'hrms_minio_*.tar.gz' -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
if [ "${DELETED}" -gt 0 ]; then
    log "Retention: deleted ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
fi
