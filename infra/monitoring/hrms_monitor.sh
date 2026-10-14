#!/usr/bin/env bash
# Staff Spectrum HRMS — host-level health monitor (mission Phases 10/11, "Minimal tier").
#
# Read-only. It never restarts a container, flushes or deletes a queue, or changes data. It
# collects signals the stack already produces, decides pass/fail against provisional thresholds,
# prints ONE JSON report on stdout, and exits:
#   0 = all checks passed, 1 = at least one check failed, 2 = the monitor itself could not run.
#
# Signals:
#   * API readiness (`/health/ready`, inside the api container — no public URL needed)
#   * background jobs (`python -m hrms.ops.job_health` in the worker: scheduler heartbeat age,
#     queue depth, oldest queued message age — read-only LLEN/LINDEX)
#   * unhealthy containers, container restart counts, disk usage
#   * structured-log events in the last $HRMS_MONITOR_WINDOW (default 5m) from api + worker:
#     5xx responses, unhandled exceptions, database/limiter outages, integrity errors, security
#     events, task failures, partial runs, email and storage failures
#   * backup logs written by infra/backup/*.sh (last SUCCESS age, FAILED after last SUCCESS)
#
# Delivery: if any check fails and HRMS_ALERT_COMMAND is set, the JSON report is piped to it on
# stdin (e.g. a mail/chat webhook script the operator provides), bounded by HRMS_ALERT_TIMEOUT
# seconds (default 30) so a hung webhook cannot wedge cron. No destination is configured by
# default — choosing one is an open operational decision (see the execution report). The outcome
# is always stated on stderr as one JSON line: {"alert_delivery":"sent|failed|not_configured"},
# so "nobody was told" is visible in the cron log instead of silent. The monitor is stateless: it
# alerts on every failing run and sends no separate "recovered" message.
#
# Typical cron entry (every 5 minutes, from the deployment directory):
#   */5 * * * * cd /opt/hrms && BACKUP_ROOT=/opt/hrms/backups \
#     HRMS_ALERT_COMMAND=/opt/hrms/bin/notify.sh infra/monitoring/hrms_monitor.sh >> /var/log/hrms-monitor.log 2>&1
#
# Thresholds are PROVISIONAL starting points, not calibrated values; tune them after two to four
# weeks of real baseline (docs/operations/ALERTS_AND_RUNBOOKS.md).
set -uo pipefail

WINDOW="${HRMS_MONITOR_WINDOW:-5m}"
read -r -a COMPOSE <<< "${HRMS_COMPOSE_CMD:-docker compose -f docker-compose.prod.yml}"
DOCKER="${HRMS_DOCKER_CMD:-docker}"
PROJECT="${HRMS_COMPOSE_PROJECT:-hrms-prod}"
MAX_5XX="${HRMS_MAX_5XX:-5}"
MAX_DISK_PCT="${HRMS_MAX_DISK_PCT:-85}"
MAX_RESTARTS="${HRMS_MAX_RESTARTS:-3}"
MAX_BACKUP_AGE_HOURS="${HRMS_MAX_BACKUP_AGE_HOURS:-26}"
ALERT_TIMEOUT="${HRMS_ALERT_TIMEOUT:-30}"
# Compose services that are expected to be stopped after doing their job.
ONESHOT_SERVICES="${HRMS_ONESHOT_SERVICES:-minio-init migrate}"
DISK_PATHS="${HRMS_DISK_PATHS:-/}"

if ! command -v jq >/dev/null 2>&1; then
  echo '{"ok":false,"error":"jq_not_installed"}'
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
: > "$TMP/checks.jsonl"

# check NAME OK(true|false) VALUE THRESHOLD SEVERITY
check() {
  jq -nc --arg name "$1" --argjson ok "$2" --arg value "$3" --arg threshold "$4" --arg severity "$5" \
    '{name:$name, ok:$ok, value:($value|tonumber? // $value), threshold:($threshold|tonumber? // $threshold), severity:$severity}' \
    >> "$TMP/checks.jsonl"
}

bool() { if "$@"; then echo true; else echo false; fi; }

# --- API readiness -------------------------------------------------------------------------
ready_code=$("${COMPOSE[@]}" exec -T api python -c \
  "import urllib.request,sys
try:
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).status == 200 else 1)
except Exception:
    sys.exit(1)" >/dev/null 2>&1; echo $?)
check api_ready "$(bool test "$ready_code" -eq 0)" "$ready_code" 0 critical

# --- Background jobs -----------------------------------------------------------------------
jobs_json=$("${COMPOSE[@]}" exec -T worker python -m hrms.ops.job_health 2>/dev/null)
jobs_code=$?
if ! printf '%s' "$jobs_json" | jq -e . >/dev/null 2>&1; then
  jobs_json='{"ok":false,"error":"job_health_unavailable"}'
fi
check job_health "$(bool test "$jobs_code" -eq 0)" "$jobs_code" 0 high

# --- Containers ----------------------------------------------------------------------------
unhealthy=$("$DOCKER" ps --filter "label=com.docker.compose.project=$PROJECT" --filter health=unhealthy -q 2>/dev/null | wc -l)
check containers_unhealthy "$(bool test "$unhealthy" -eq 0)" "$unhealthy" 0 critical

# A stopped, dead or crash-looping service is not "unhealthy" in Docker's sense (that needs a
# running healthcheck), so a stopped MinIO, worker or Redis would otherwise pass this section.
not_running=0
while read -r service state; do
  [ -z "${service:-}" ] && continue
  case " $ONESHOT_SERVICES " in *" $service "*) continue ;; esac
  [ "$state" = "running" ] || not_running=$((not_running + 1))
done < <("$DOCKER" ps -a --filter "label=com.docker.compose.project=$PROJECT" \
  --format '{{.Label "com.docker.compose.service"}} {{.State}}' 2>/dev/null)
check containers_not_running "$(bool test "$not_running" -eq 0)" "$not_running" 0 critical

restarts=0
for id in $("$DOCKER" ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null); do
  n=$("$DOCKER" inspect -f '{{.RestartCount}}' "$id" 2>/dev/null || echo 0)
  restarts=$((restarts + ${n:-0}))
done
check container_restarts "$(bool test "$restarts" -le "$MAX_RESTARTS")" "$restarts" "$MAX_RESTARTS" high

# --- Disk ----------------------------------------------------------------------------------
disk_max=0
for path in $DISK_PATHS; do
  pct=$(df -P "$path" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')
  [ -n "${pct:-}" ] && [ "$pct" -gt "$disk_max" ] && disk_max=$pct
done
check disk_usage_pct "$(bool test "$disk_max" -le "$MAX_DISK_PCT")" "$disk_max" "$MAX_DISK_PCT" high

# --- Structured log events -----------------------------------------------------------------
# Only JSON lines are considered; banners and plain-text lines are skipped.
logs() {
  "${COMPOSE[@]}" logs --no-color --no-log-prefix --since "$WINDOW" "$1" 2>/dev/null \
    | jq -Rc 'fromjson? | select(type == "object")'
}
logs api > "$TMP/api.jsonl"
logs worker > "$TMP/worker.jsonl"

count() { jq -s "[.[] | select($2)] | length" "$1"; }

n=$(count "$TMP/api.jsonl" '.event == "http_request" and (.status_code // 0) >= 500')
check api_5xx "$(bool test "$n" -le "$MAX_5XX")" "$n" "$MAX_5XX" high
n=$(count "$TMP/api.jsonl" '.event == "unhandled_exception"')
check api_unhandled_exceptions "$(bool test "$n" -eq 0)" "$n" 0 high
n=$(count "$TMP/api.jsonl" '(.error_category // "") | test("^db_(connection|pool_exhausted)$")')
check db_connectivity_errors "$(bool test "$n" -eq 0)" "$n" 0 critical
n=$(count "$TMP/api.jsonl" '.event == "http_request" and .error_code == "RATE_LIMITER_UNAVAILABLE"')
check rate_limiter_unavailable "$(bool test "$n" -eq 0)" "$n" 0 critical
n=$(count "$TMP/api.jsonl" '.event == "app_error" and ((.error_code // "") | test("^(DECRYPTION_FAILED|MALFORMED_CIPHERTEXT|UNKNOWN_KEY_VERSION)$"))')
check pii_integrity_errors "$(bool test "$n" -eq 0)" "$n" 0 critical
n=$(count "$TMP/api.jsonl" '.event == "security.refresh_token_reuse_detected"')
check refresh_token_reuse "$(bool test "$n" -eq 0)" "$n" 0 medium
n=$(count "$TMP/api.jsonl" '.event == "security.account.locked"')
check account_lockouts "$(bool test "$n" -le 10)" "$n" 10 medium
n=$(cat "$TMP/api.jsonl" "$TMP/worker.jsonl" | count /dev/stdin '.event == "email.delivery.failed"')
check email_delivery_failures "$(bool test "$n" -le 5)" "$n" 5 high
n=$(cat "$TMP/api.jsonl" "$TMP/worker.jsonl" | count /dev/stdin '.event == "log_writes_dropped"')
check log_writes_dropped "$(bool test "$n" -eq 0)" "$n" 0 high
n=$(count "$TMP/worker.jsonl" '.event == "celery_task_failed" or .event == "celery_task_unknown" or .event == "celery_fanout_incomplete"')
check task_failures "$(bool test "$n" -eq 0)" "$n" 0 high
n=$(count "$TMP/worker.jsonl" '(.event // "") | test("_incomplete$")')
check partial_runs "$(bool test "$n" -eq 0)" "$n" 0 high
n=$(cat "$TMP/api.jsonl" "$TMP/worker.jsonl" | count /dev/stdin '(.event // "") | test("^(employee_import\\.batch\\.storage_failed|face_review_photo_delete_failed|face_enrollment_orphaned_provider_person)$")')
check storage_and_orphan_failures "$(bool test "$n" -eq 0)" "$n" 0 high

# --- Backups -------------------------------------------------------------------------------
if [ -n "${BACKUP_ROOT:-}" ]; then
  now=$(date -u +%s)
  for kind in postgres minio; do
    log_file="$BACKUP_ROOT/$kind/backup.log"
    last_success=$(grep ' SUCCESS: ' "$log_file" 2>/dev/null | tail -1 | cut -d' ' -f1)
    if [ -z "$last_success" ]; then
      check "backup_$kind" false missing "${MAX_BACKUP_AGE_HOURS}h" high
      continue
    fi
    age_h=$(( (now - $(date -u -d "$last_success" +%s)) / 3600 ))
    failed_after=$(awk -v ts="$last_success" '$1 > ts && / FAILED: /' "$log_file" | wc -l)
    check "backup_$kind" "$(bool test "$age_h" -le "$MAX_BACKUP_AGE_HOURS" -a "$failed_after" -eq 0)" \
      "$age_h" "$MAX_BACKUP_AGE_HOURS" high
  done
fi

# --- Report --------------------------------------------------------------------------------
report=$(jq -sc --arg window "$WINDOW" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson jobs "$jobs_json" \
  '{ok: (all(.[]; .ok)), checked_at: $at, window: $window,
    failing: [.[] | select(.ok | not) | .name], checks: ., job_health: $jobs}' \
  "$TMP/checks.jsonl")
echo "$report"

if [ "$(printf '%s' "$report" | jq -r .ok)" != "true" ]; then
  if [ -n "${HRMS_ALERT_COMMAND:-}" ]; then
    run_alert=(sh -c "$HRMS_ALERT_COMMAND")
    command -v timeout >/dev/null 2>&1 && run_alert=(timeout "$ALERT_TIMEOUT" "${run_alert[@]}")
    if printf '%s\n' "$report" | "${run_alert[@]}" >/dev/null; then
      echo '{"alert_delivery":"sent"}' >&2
    else
      echo '{"alert_delivery":"failed"}' >&2
    fi
  else
    echo '{"alert_delivery":"not_configured"}' >&2
  fi
  exit 1
fi
exit 0
