#!/usr/bin/env bash
# RELEASE_HARDENING_PHASE_3B §8 — restores a backup produced by pg_backup.sh into a NEW,
# empty database — never into the live production database directly, so a bad restore can never
# clobber a good one. See docs/deployment/DISASTER_RECOVERY.md for the full real-outage procedure
# (which includes repointing the application at the restored database); this script only proves
# the backup file itself is usable and performs the actual data restore step.
#
# Usage:
#   ./infra/backup/pg_restore.sh /opt/hrms/backups/postgres/hrms_20260925T080000Z.dump.gz [target_db_name]
#
# `target_db_name` defaults to `hrms_restore_check` — always suffixed, never `$POSTGRES_DB`
# itself, so an operator cannot restore over the live database by omitting the argument.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"

BACKUP_FILE="${1:?Usage: pg_restore.sh <backup_file.dump.gz> [target_db_name]}"
TARGET_DB="${2:-hrms_restore_check}"

if [ "${TARGET_DB}" = "hrms_prod" ] || [ "${TARGET_DB}" = "${POSTGRES_DB:-}" ]; then
    echo "Refusing to restore over what looks like the live database name (${TARGET_DB})." >&2
    echo "Pass an explicit, different target_db_name." >&2
    exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "Backup file not found: ${BACKUP_FILE}" >&2
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

echo "Restoring $(basename "${BACKUP_FILE}") into database '${TARGET_DB}'..."

# Create the target database (drop-and-recreate so a repeated restore-test run is idempotent),
# then pipe the decompressed dump into pg_restore inside the same running Postgres container the
# backup itself was taken from — no separate restore-target container, no credentials outside the
# container's own environment.
"${COMPOSE[@]}" -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"'"${TARGET_DB}"'\";" -c "CREATE DATABASE \"'"${TARGET_DB}"'\";"'

gunzip -c "${BACKUP_FILE}" | "${COMPOSE[@]}" -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    sh -c 'pg_restore -U "$POSTGRES_USER" -d '"${TARGET_DB}"' --no-owner --role="$POSTGRES_USER"'

echo "Restore complete. Verifying row counts on a few core tables..."
"${COMPOSE[@]}" -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    sh -c 'psql -U "$POSTGRES_USER" -d '"${TARGET_DB}"' -c "SELECT '"'"'company'"'"' AS table_name, count(*) FROM company UNION ALL SELECT '"'"'\"user\"'"'"', count(*) FROM \"user\" UNION ALL SELECT '"'"'employment'"'"', count(*) FROM employment;"'

echo ""
echo "Restore-test database '${TARGET_DB}' left in place for manual inspection."
echo "Drop it when done:"
echo "  ${COMPOSE[*]} -f ${COMPOSE_FILE} exec ${POSTGRES_SERVICE} psql -U \$POSTGRES_USER -d postgres -c 'DROP DATABASE \"${TARGET_DB}\";'"
