#!/usr/bin/env bash
# Encrypted, offsite HRMS backup for the Hostinger VPS (docker-compose.vps.yml). Supersedes
# pg_backup.sh/minio_backup.sh there; see docs/deployment/BACKUPS_GOOGLE_DRIVE.md.
#
# Every run (hourly, via infra/backup/systemd/hrms-backup.timer):
#   1. pg_dump -Fc of every database in BACKUP_DATABASES, plus pg_dumpall --globals-only, taken
#      inside the postgres container (Postgres is never exposed), each checked with pg_restore --list.
#   2. A manifest of row counts and the alembic head per database.
#   3. tar | age -R <recipients> -> $BACKUP_ROOT/postgres/. Only the PUBLIC key is on the server, so
#      the server can write backups but cannot read them; the private key is kept offline.
#   4. rclone copy to $RCLONE_REMOTE/<tier>/ and remote retention per tier.
# The first run after 00:00 UTC is the "daily" run. It also restores every dump into a throwaway,
# network-less postgres container and compares row counts, backs up the MinIO volume, and includes
# the compose/app env files (they hold PII_MASTER_KEY; without it a restore cannot decrypt PII).
#
# Writes "<UTC ISO> SUCCESS: ..." / "<UTC ISO> FAILED: ..." to $BACKUP_ROOT/{postgres,minio}/backup.log,
# the format infra/monitoring/hrms_monitor.sh checks. Read-only towards the application: it never
# stops, restarts or writes to any HRMS container.
#
# Configuration: /etc/hrms-backup/hrms-backup.env (EnvironmentFile of the systemd unit). No secrets
# live in it; the Google Drive token is in rclone's own config (root, mode 600).
set -Eeuo pipefail
umask 077

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/opt/hrms}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
BACKUP_DATABASES="${BACKUP_DATABASES:?BACKUP_DATABASES must list the databases to back up}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/hrms}"
AGE_RECIPIENTS_FILE="${AGE_RECIPIENTS_FILE:-/etc/hrms-backup/age-recipients.txt}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
MINIO_VOLUME="${MINIO_VOLUME:-hrms-prod_minio_data}"
ENV_FILES="${ENV_FILES:-/opt/hrms/.env /opt/hrms/apps/api/env/.env.production}"
RESTORE_TEST_IMAGE="${RESTORE_TEST_IMAGE:-postgres:16-alpine}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"
# Tables whose counts go in the manifest and are compared by the restore test (missing ones skipped).
COUNT_TABLES="${COUNT_TABLES:-company user employment employee punch attendance_day leave_ledger pay_run audit_log}"
# Local retention: hourly files 48 h, daily files 7 days. Remote retention per tier is below.
LOCAL_HOURLY_MINUTES="${LOCAL_HOURLY_MINUTES:-2880}"
LOCAL_DAILY_DAYS="${LOCAL_DAILY_DAYS:-7}"
REMOTE_KEEP_hourly="${REMOTE_KEEP_hourly:-2d}"
REMOTE_KEEP_daily="${REMOTE_KEEP_daily:-14d}"
REMOTE_KEEP_weekly="${REMOTE_KEEP_weekly:-56d}"
REMOTE_KEEP_monthly="${REMOTE_KEEP_monthly:-365d}"
REMOTE_KEEP_yearly="${REMOTE_KEEP_yearly:-2555d}"
# Set FORCE_DAILY=1 for a manual run that does everything the daily run does.
FORCE_DAILY="${FORCE_DAILY:-0}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
PG_DIR="$BACKUP_ROOT/postgres"
MINIO_DIR="$BACKUP_ROOT/minio"
WORK="$BACKUP_ROOT/.work-$TS"
RESTORE_CONTAINER="hrms-restore-test-$TS"
mkdir -p "$PG_DIR" "$MINIO_DIR"
chmod 700 "$BACKUP_ROOT"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$CURRENT_LOG"; }
CURRENT_LOG="$PG_DIR/backup.log"

ping_hc() {
    [ -n "$HEALTHCHECK_URL" ] || return 0
    curl -fsS -m 10 --retry 3 -o /dev/null "$HEALTHCHECK_URL$1" || true
}

cleanup() {
    docker rm -f "$RESTORE_CONTAINER" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}

on_error() {
    local line="$1"
    log "FAILED: backup run $TS stopped at line $line (see journalctl -u hrms-backup)"
    ping_hc /fail
}

fail() {
    trap - ERR
    log "FAILED: $*"
    ping_hc /fail
    exit 1
}
trap 'on_error $LINENO' ERR
trap cleanup EXIT

exec 9>/run/hrms-backup.lock
flock -n 9 || { echo "another hrms-backup run is in progress" >&2; exit 0; }

[ -s "$AGE_RECIPIENTS_FILE" ] || fail "$AGE_RECIPIENTS_FILE is missing"
command -v age >/dev/null || fail "age is not installed"
command -v rclone >/dev/null || fail "rclone is not installed"

cd "$COMPOSE_PROJECT_DIR"
PG=(docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_SERVICE")
psql_at() { "${PG[@]}" sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -At' _ "$1"; }

# Tiers: hourly always; the first run of the UTC day is daily, and on Sundays/the 1st/1 January also
# weekly/monthly/yearly. "First run of the day" is hour 00 or no daily file yet today (missed runs).
TIERS=(hourly)
TODAY="$(date -u +%Y%m%d)"
if [ "$FORCE_DAILY" = 1 ] || [ "$(date -u +%H)" = 00 ] \
    || ! ls "$PG_DIR"/hrms_"$TODAY"T*_daily.tar.age >/dev/null 2>&1; then
    TIERS+=(daily)
    if [ "$(date -u +%u)" = 7 ]; then TIERS+=(weekly); fi
    if [ "$(date -u +%d)" = 01 ]; then TIERS+=(monthly); fi
    if [ "$(date -u +%m%d)" = 0101 ]; then TIERS+=(yearly); fi
fi
DAILY=0
SUFFIX=""
if [[ " ${TIERS[*]} " == *" daily "* ]]; then DAILY=1; SUFFIX="_daily"; fi

log "Starting backup $TS tiers=${TIERS[*]}"
mkdir -p "$WORK/postgres"

# --- 1/2. Dumps, verification and manifest ----------------------------------------------------
"${PG[@]}" sh -c 'pg_dumpall -U "$POSTGRES_USER" --globals-only' > "$WORK/postgres/globals.sql"
[ -s "$WORK/postgres/globals.sql" ]

MANIFEST="$WORK/postgres/manifest.txt"
{
    echo "backup=$TS"
    echo "host=$(hostname)"
    echo "tiers=${TIERS[*]}"
    "${PG[@]}" sh -c 'psql -U "$POSTGRES_USER" -d postgres -Atc "select version()"' | sed 's/^/server=/'
} > "$MANIFEST"

for db in $BACKUP_DATABASES; do
    out="$WORK/postgres/$db.dump"
    "${PG[@]}" sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$1"' _ "$db" > "$out"
    [ -s "$out" ]
    # pg_restore reads the archive from stdin inside the container (no client tools on the host).
    "${PG[@]}" pg_restore --list < "$out" > /dev/null
    echo "dump.$db.bytes=$(stat -c %s "$out")" >> "$MANIFEST"
    echo "dump.$db.sha256=$(sha256sum "$out" | cut -d' ' -f1)" >> "$MANIFEST"
    echo "db.$db.alembic=$(psql_at "$db" <<<'select version_num from alembic_version' 2>/dev/null || echo none)" >> "$MANIFEST"
    for t in $COUNT_TABLES; do
        exists=$(psql_at "$db" <<<"select to_regclass('public.\"$t\"') is not null")
        if [ "$exists" = t ]; then
            echo "count.$db.$t=$(psql_at "$db" <<<"select count(*) from public.\"$t\"")" >> "$MANIFEST"
        fi
    done
done

# --- Daily: restore test into a throwaway container ------------------------------------------
if [ "$DAILY" = 1 ]; then
    docker run -d --name "$RESTORE_CONTAINER" --network none --memory 768m \
        -e POSTGRES_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')" \
        "$RESTORE_TEST_IMAGE" >/dev/null
    # The image's first start runs initdb behind a temporary server and then restarts it, so
    # pg_isready alone can pass too early; wait for the init-complete line as well.
    ready=0
    for _ in $(seq 1 90); do
        if docker logs "$RESTORE_CONTAINER" 2>&1 | grep -q 'init process complete' \
            && docker exec "$RESTORE_CONTAINER" pg_isready -U postgres -q 2>/dev/null; then
            ready=1
            break
        fi
        sleep 1
    done
    [ "$ready" = 1 ] || fail "restore-test container did not become ready"
    # Policies and grants name hrms/hrms_app, so the roles must exist for the restore to succeed.
    docker exec "$RESTORE_CONTAINER" psql -U postgres -qAtc "create role hrms nologin; create role hrms_app nologin" >/dev/null
    for db in $BACKUP_DATABASES; do
        docker exec "$RESTORE_CONTAINER" createdb -U postgres "r_$db"
        docker exec -i "$RESTORE_CONTAINER" pg_restore -U postgres -d "r_$db" --no-owner \
            --exit-on-error < "$WORK/postgres/$db.dump"
        for t in $COUNT_TABLES; do
            want=$(sed -n "s/^count\.$db\.$t=//p" "$MANIFEST")
            [ -n "$want" ] || continue
            got=$(docker exec "$RESTORE_CONTAINER" psql -U postgres -d "r_$db" -Atc "select count(*) from public.\"$t\"")
            # The counts were read just after the dump, so a few new rows are possible; allow 1 % (min 5).
            diff=$(( got > want ? got - want : want - got ))
            tol=$(( want / 100 > 5 ? want / 100 : 5 ))
            if [ "$diff" -gt "$tol" ]; then
                fail "restore test $db.$t restored $got rows, expected about $want"
            fi
        done
        want=$(sed -n "s/^db\.$db\.alembic=//p" "$MANIFEST")
        got=$(docker exec "$RESTORE_CONTAINER" psql -U postgres -d "r_$db" -Atc "select version_num from alembic_version" 2>/dev/null || echo none)
        [ "$got" = "$want" ] || fail "restore test $db alembic $got != $want"
        echo "restore_test.$db=ok" >> "$MANIFEST"
    done
    docker rm -f "$RESTORE_CONTAINER" >/dev/null
    log "Restore test passed for: $BACKUP_DATABASES"

    mkdir -p "$WORK/postgres/config"
    for f in $ENV_FILES; do
        if [ -f "$f" ]; then cp -p "$f" "$WORK/postgres/config/$(echo "$f" | sed 's#^/##; s#/#__#g')"; fi
    done
fi

# --- 3. Encrypt -----------------------------------------------------------------------------
PG_OUT="$PG_DIR/hrms_${TS}${SUFFIX}.tar.age"
tar -C "$WORK/postgres" -cf - . | age -R "$AGE_RECIPIENTS_FILE" -o "$PG_OUT.partial"
mv "$PG_OUT.partial" "$PG_OUT"
sha256sum "$PG_OUT" | sed "s#  .*/#  #" > "$PG_OUT.sha256"
UPLOADS=("$PG_OUT")

MINIO_OUT=""
if [ "$DAILY" = 1 ]; then
    MINIO_OUT="$MINIO_DIR/minio_${TS}_daily.tar.age"
    # Read-only mount of the live volume. MinIO writes are rare here (documents), and objects are
    # immutable files, so a file-level copy is consistent enough; the bucket metadata is in .minio.sys.
    docker run --rm -v "$MINIO_VOLUME":/data:ro "$RESTORE_TEST_IMAGE" tar -C /data -cf - . \
        | age -R "$AGE_RECIPIENTS_FILE" -o "$MINIO_OUT.partial"
    mv "$MINIO_OUT.partial" "$MINIO_OUT"
    sha256sum "$MINIO_OUT" | sed "s#  .*/#  #" > "$MINIO_OUT.sha256"
fi

# --- 4. Offsite -----------------------------------------------------------------------------
[ -n "$RCLONE_REMOTE" ] || fail "RCLONE_REMOTE is not set, backup $PG_OUT is local only"
for tier in "${TIERS[@]}"; do
    rclone copy --no-traverse "$PG_OUT" "$RCLONE_REMOTE/$tier/postgres/"
    rclone copy --no-traverse "$PG_OUT.sha256" "$RCLONE_REMOTE/$tier/postgres/"
    if [ -n "$MINIO_OUT" ]; then
        rclone copy --no-traverse "$MINIO_OUT" "$RCLONE_REMOTE/$tier/minio/"
        rclone copy --no-traverse "$MINIO_OUT.sha256" "$RCLONE_REMOTE/$tier/minio/"
    fi
done
# Confirm the hourly copy landed with the right size before calling the run a success.
remote_size=$(rclone lsf --files-only --format s --include "/$(basename "$PG_OUT")" "$RCLONE_REMOTE/hourly/postgres/")
[ "$remote_size" = "$(stat -c %s "$PG_OUT")" ] || fail "offsite size mismatch for $PG_OUT (remote '$remote_size')"

# Remote retention (Drive moves deleted files to its trash, recoverable for 30 days).
# A tier folder appears with its first upload (weekly/monthly/yearly can be weeks away). List the top
# folder once: on Drive, listing a folder that does not exist spends about a minute on retries.
REMOTE_TIERS=" $(rclone lsf --dirs-only "$RCLONE_REMOTE/" | tr -d / | tr '\n' ' ') "
for tier in hourly daily weekly monthly yearly; do
    keep_var="REMOTE_KEEP_$tier"
    [[ "$REMOTE_TIERS" == *" $tier "* ]] || continue
    if ! rclone delete --min-age "${!keep_var}" "$RCLONE_REMOTE/$tier/" 2>/dev/null; then
        log "WARNING: remote retention for $tier did not complete (backup itself is fine)"
    fi
done

# Local retention.
find "$PG_DIR" "$MINIO_DIR" -maxdepth 1 -name '*.partial' -mmin +120 -delete
find "$PG_DIR" -maxdepth 1 \( -name 'hrms_*.tar.age' -o -name 'hrms_*.tar.age.sha256' \) \
    ! -name '*_daily*' -mmin "+$LOCAL_HOURLY_MINUTES" -delete
find "$PG_DIR" "$MINIO_DIR" -maxdepth 1 -name '*_daily.tar.age*' -mtime "+$LOCAL_DAILY_DAYS" -delete

log "SUCCESS: $PG_OUT ($(du -h "$PG_OUT" | cut -f1)) offsite=$RCLONE_REMOTE tiers=${TIERS[*]}"
if [ -n "$MINIO_OUT" ]; then
    CURRENT_LOG="$MINIO_DIR/backup.log"
    log "SUCCESS: $MINIO_OUT ($(du -h "$MINIO_OUT" | cut -f1)) offsite=$RCLONE_REMOTE"
fi
ping_hc ""
