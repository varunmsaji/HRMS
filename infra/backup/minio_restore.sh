#!/usr/bin/env bash
# RELEASE_HARDENING_PHASE_3B §9 — restores a minio_backup.sh archive into a NEW bucket, never the
# live documents bucket, so a bad restore can never overwrite good live data. See
# docs/deployment/DISASTER_RECOVERY.md for the real-outage procedure (which includes repointing
# `S3_BUCKET_DOCUMENTS` at a restored bucket); this script proves the archive itself is usable.
#
# Usage:
#   ./infra/backup/minio_restore.sh /opt/hrms/backups/minio/hrms_minio_20260925T080000Z.tar.gz [target_bucket]
#
# `target_bucket` defaults to `hrms-restore-check` — always distinct, never
# `$MINIO_BUCKET_DOCUMENTS` itself, mirroring pg_restore.sh's own same-shaped guard.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
MINIO_SERVICE="${MINIO_SERVICE:-minio}"

ARCHIVE_FILE="${1:?Usage: minio_restore.sh <archive.tar.gz> [target_bucket]}"
TARGET_BUCKET="${2:-hrms-restore-check}"

if [ ! -f "${ARCHIVE_FILE}" ]; then
    echo "Archive not found: ${ARCHIVE_FILE}" >&2
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "Neither 'docker compose' nor 'docker-compose' is available" >&2
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

if [ "${TARGET_BUCKET}" = "${MINIO_BUCKET_DOCUMENTS:-}" ]; then
    echo "Refusing to restore over the live documents bucket (${TARGET_BUCKET})." >&2
    echo "Pass an explicit, different target_bucket." >&2
    exit 1
fi

RESTORE_TMP="$(mktemp -d)"
trap 'rm -rf "${RESTORE_TMP}"' EXIT

echo "Extracting $(basename "${ARCHIVE_FILE}")..."
tar -xzf "${ARCHIVE_FILE}" -C "${RESTORE_TMP}"

OBJECT_COUNT=$(find "${RESTORE_TMP}" -type f | wc -l)
echo "Restoring ${OBJECT_COUNT} object(s) into bucket '${TARGET_BUCKET}'..."

"${COMPOSE[@]}" -f "${COMPOSE_FILE}" run --rm -T \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "${RESTORE_TMP}:/restore" \
    --entrypoint /bin/sh \
    minio-init -c "
        mc alias set local http://${MINIO_SERVICE}:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}' &&
        mc mb --ignore-existing local/${TARGET_BUCKET} &&
        mc mirror --quiet /restore local/${TARGET_BUCKET} &&
        mc ls --recursive local/${TARGET_BUCKET} | wc -l
    "

echo ""
echo "Restore-test bucket '${TARGET_BUCKET}' left in place for manual inspection."
echo "Drop it when done:"
echo "  ${COMPOSE[*]} -f ${COMPOSE_FILE} run --rm --entrypoint /bin/sh minio-init -c \\"
echo "    \"mc alias set local http://${MINIO_SERVICE}:9000 \\\$MINIO_ROOT_USER \\\$MINIO_ROOT_PASSWORD && mc rb --force local/${TARGET_BUCKET}\""
