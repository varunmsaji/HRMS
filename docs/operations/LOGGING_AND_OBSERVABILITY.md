# Logging and Observability — Contract, Event Catalogue, Retention

This describes what the API, worker and Beat actually emit. It was written against the code on
2026-10-14, after the autonomous logging mission
(`docs/audits/LOGGING_ERROR_HANDLING_AUTONOMOUS_EXECUTION_REPORT.md`). If code and this document
disagree, the code is right and this file is stale.

## 1. Format

Every API, worker and Beat line is one JSON object on stdout. Celery's startup banner and
shutdown notice are the only plain-text lines. Processor order
(`apps/api/src/hrms/core/observability/logging.py`):

`merge_contextvars → add_log_level → TimeStamper(iso, UTC) → {service, environment} →
format_exc_info → redact_event → JSONRenderer`

Worker and Beat run the stdlib tree (Celery, kombu, httpx) through the same chain.

The sink is a stdout proxy (`_ResilientStdout`) with two properties:

- it resolves `sys.stdout` at write time;
- a failed write is dropped and counted, never raised. A broken log pipe can never turn into a
  business failure, and it never recurses into more logging.

## 2. Fields

| Field | When | Notes |
|---|---|---|
| `timestamp`, `level`, `event`, `service`, `environment` | always | `event` is the stable name and the contract. `service` is `api`, `worker` or `beat`. |
| `request_id` | API requests, and tasks enqueued by a request | Validated: 1–64 chars of `A-Za-z0-9._:-`, otherwise replaced with a UUID. Also on every response (`X-Request-Id`), in every error body, and in `audit_log.request_id`. |
| `task_id`, `task_name` | inside a Celery task | Bound for the task's duration. |
| `http_method`, `http_path` | request events | `http_path` is the **route template** (`/v1/payroll/pay-runs/{run_id}/approve`), never a raw token-bearing path. |
| `status_code`, `duration_ms`, `error_code` | `http_request` | `error_code` is the envelope code of a handled error (`CONFLICT`, `PERMISSION_DENIED`, …). |
| `company_id`, `user_id` | after membership verification only | An unverified `X-Company-Id` header is never logged. |
| `exception_type`, `error_category`, `error_code`, `sqlstate`, `driver_error`, `cause_type` | failures | From `safe_error()`. Never `str(exc)`. |
| `exception` | unexpected failures only | Rendered traceback, after redaction, bounded to 16 000 chars. |

`error_category` is a fixed vocabulary (`core/observability/classification.py`):

- `db_timeout`, `db_pool_exhausted`, `db_deadlock`, `db_serialization`, `db_connection`
- `db_integrity`, `db_invalid_input`, `db_error`
- `dependency_unreachable`, `timeout`, `unexpected`

## 3. Levels

| Level | Used for |
|---|---|
| INFO | Lifecycle: `http_request`, `celery_task_finished`, `business.audit_recorded`, `security.login.succeeded`, `email.provider.accepted`, routine `security.*` outcomes. |
| WARNING | Handled and degraded: per-item failures, retries, transient dependency failures (`db_wait_timeout`, `db_pool_exhausted`, 503 `app_error`), security failures, email delivery failures. |
| ERROR | Unexpected failures and 500s with traceback, task final failure, integrity events, short fan-outs, orphaned biometric/storage objects. |

Expected 4xx business outcomes are **not** logged as errors. They show up only as
`http_request` with `error_code`.

## 4. Event catalogue

### HTTP and errors
| Event | Level | Meaning |
|---|---|---|
| `http_request` | info | One per request (successful health probes excluded). |
| `unhandled_exception` | error | An exception escaped the stack; logged once, with traceback, and answered with the 500 envelope. |
| `app_error` | error (500) / warning (502–504) | A 5xx `AppError` (rate limiter down, encryption key problem, provider failure). |
| `db_error` | error | Unmapped database error, answered with 500. |
| `db_wait_timeout`, `db_pool_exhausted`, `db_deadlock`, `db_serialization` | warning | Retryable; answered with `503 DATABASE_BUSY` and `Retry-After: 2`. |
| `db_rollback_failed` | warning | A rollback failed after an earlier failure. The original error is still the one handled. |
| `readiness_dependency_failed` | warning | `/health/ready` found `database` or `redis` failing. |
| `rate_limiter_unavailable` | warning | Redis was unreachable for the onboarding-upload limiter (503). |
| `log_redaction_failed` | — | Redaction itself failed, so only structural fields were emitted. |

### Security (`security.*`, `core/observability/security_events.py`)
| Event | Level |
|---|---|
| `security.login.succeeded` | info |
| `security.login.failed` (`reason`: `unknown_account`, `bad_password`, `account_locked`, `inactive_account`, `email_not_verified`, `no_membership`, `company_not_member`) | warning |
| `security.account.locked` | warning |
| `security.refresh.rejected` (`reason`: `unknown_token`, `expired`, `session_revoked`, `inactive_account`, `membership_invalid`, `incomplete_record`) | info / warning |
| `security.refresh_token_reuse_detected` | warning |
| `security.logout` | info |
| `security.password_reset.requested` / `.completed` / `.failed` | info / info / warning |
| `security.email_verification.completed` / `.failed` | info / warning |
| `security.rate_limited` (first over-limit request per key per window only) | warning |
| `security.authorization.denied` | info |
| `security.tenant.rejected` | warning |
| `security.access_token.rejected` (a valid token refused because of server-side state) | info / warning |

Accounts are identified by `user_id`. When the account is unknown, `subject_hash` is used
instead: a keyed HMAC of the submitted address. It is pseudonymous, not anonymous. Passwords,
tokens and raw addresses are never logged, and nothing derived from these events reaches the
client.

### Business lifecycle
`business.audit_recorded` (info) is emitted once per audited business transition, and **only after
the transaction commits**. That covers employee lifecycle, onboarding, leave, regularization,
pay-run state, documents and more. It carries:

- `action`, `entity_type`, `entity_id`
- `company_id`, `actor_user_id`
- `from_status`, `to_status` — only when the snapshot `status` is a fixed state code

`before`/`after`, IP and user agent stay in `audit_log`. The mechanism is
`core/observability/business_events.py`; an event raised inside a rolled-back transaction or
SAVEPOINT is discarded.

Module events:

- `employee_import.batch.{finished,skipped,storage_failed}`
- `account_invite.auto_issue_{skipped,failed}`
- `attendance_scheduled_calculate_{failed,timed_out,incomplete}`
- `leave_accrual_{employee_failed,incomplete}`, `leave_year_end_{employee_failed,incomplete}`
- `face_enrollment_orphaned_provider_person`, `face_review_photo_delete_failed` (with the
  identifiers needed for clean-up)
- `face_provider_request_failed`, `face_provider_request_rejected`, `face_provider_unrecognised_response`

### Email
| Event | Level | Meaning |
|---|---|---|
| `email.provider.accepted` | info | The provider **accepted** the request. This is not delivery: bounces happen later and are invisible. |
| `email.delivery.failed` | warning (transport) / error (internal) | One per lost email. Fields: `email_kind`, IDs, `provider`, `failure_class` (`auth`, `rejected`, `rate_limited`, `provider_error`, `network`, `timeout`, `internal`), `retryable`, `outcome` (`not_sent` or `unknown`). |
| `email.logged_not_sent` | info | Development-only logging sender. The readable copy goes to stderr. |

Senders classify the failure; callers log it once (`log_email_failure`). Delivery stays
best-effort: no outbox and no automatic retry (decision D4 in the observability plan).

### Celery
| Event | Level |
|---|---|
| `celery_task_finished` (`state`, `duration_ms`) | info |
| `celery_task_retry` | warning |
| `celery_task_failed` (retry exhaustion and time limits included) | error |
| `celery_task_unknown`, `celery_task_rejected` | error |
| `celery_task_dispatch_failed` | warning |
| `celery_fanout_incomplete` | error |
| `leave_task_failed`, `leave_task_dispatch_failed` | error / warning |

Celery's own "Task … raised unexpected" record carries the single traceback.

## 5. Correlation flow

1. **Client → Nginx.** The client sends `X-Request-Id`, or Nginx generates `$request_id` and
   forwards it.
2. **Nginx → API.** `RequestContextMiddleware`, the outermost middleware, validates or replaces
   the ID, then binds it.
3. **Within the request.** Every event, the `audit_log` row and the response header/body carry
   the ID.
4. **Request → task.** `.delay()` publishes the ID in the `hrms_request_id` header, together with
   `hrms_enqueued_at`. The worker binds `request_id` alongside `task_id`.
5. **Clients.** On a server or connectivity failure the web and mobile clients show
   "Reference: <request id>". When there is no response body they fall back to the ID they sent.
   To look it up:
   `docker compose -f docker-compose.prod.yml logs api worker nginx | grep '<id>'`.

## 6. Redaction

`redact_event` is the last processor on every pipeline.

**Masked by field name** (whole `_`-separated word):

- password, secret, token, authorization, cookie, api_key, otp, signature, credential
- aadhaar, pan, account_number, ifsc, salary, ctc
- body, face_template, embedding

Names ending `_id`, `_type`, `_kind`, `_count`, `_version`, `_status` or `_reason` are kept.

**Masked by value pattern**, in any string including tracebacks and stdlib messages:

- JWTs and Bearer/Basic credentials;
- presigned-URL signatures and credentials;
- `scheme://user:password@`;
- Postgres `Key (col)=(value)`;
- email addresses;
- PAN numbers;
- token path segments. Route-template `{token}` placeholders are kept.

**Bounds and failure behaviour:**

- Strings are bounded (2 000 chars; 16 000 for tracebacks).
- Bytes become `[BYTES n]`.
- Unknown objects are rendered and then redacted.
- Redaction failure emits only the structural fields.

The engine runs with `hide_parameters=True`, so SQL bound values never enter error text.

Log injection is not possible: values are JSON-escaped, so a newline in a value can never start a
new log line. This is tested.

## 7. Retention, access and failure modes (Phase 12 assessment)

| Store | What it holds | Bound today | Owner decision still needed |
|---|---|---|---|
| Container logs (Docker `json-file`) | Operational and security events | Size only: 10 MB × 5 files per container (`x-logging`). Time span depends on traffic. | **Retention period (D2)**. No legally mandated period is assumed here. |
| Nginx access log | Edge requests: masked path, no query string, `request_id`, client IP, user agent | Same `x-logging` bound | Same as above. IP and user agent are personal data under DPDP. |
| `audit_log` (Postgres) | Business and security audit trail | Unbounded. Immutable by design. | Governed separately from logs; unchanged by this work. |
| Backups | Database and object store | `*_BACKUP_RETENTION_DAYS` (default 14) | Existing setting. |
| Mobile `AppDiagnostics` | Last 20 failure entries: type, code, status, request ID, code location. No message text. | In memory, lost on app exit | — |
| Browser | Nothing persisted. `console.error` in development builds only. | — | — |

**Retention options for D2** (pick per stream, with legal/compliance input):

| Option | What it means | Trade-off |
|---|---|---|
| (a) Keep size-bounded only | Today's behaviour. | The time span is unpredictable. |
| (b) Ship to a self-hosted store on the same VPS | e.g. Loki with a time-based retention. | Operational logs could be days to weeks; security events longer. Data stays on the VPS. |
| (c) Separate security-event stream | Filter `security.*`, then rotate and archive it to a restricted location. | Longer retention for security events only. |

**Access.** Anyone in the `docker` group on the VPS can read every container log. Treat that
group as privileged. Tokens and PII are redacted, but IPs, user IDs and company IDs remain.

**Clock.** All timestamps are UTC ISO-8601 (`TimeStamper(utc=True)` is the structlog default).
Business dates use the company time zone, separately.

**Failure modes:**

- *Disk full or closed stdout.* Log writes are dropped and counted
  (`_ResilientStdout.dropped_writes`); requests and tasks continue.
- *Redaction bug.* Structural fields only.
- *High volume.*
  - Health probes are not logged.
  - Rate-limit trips are logged once per key per window.
  - Transient dependency failures log one compact line per request, with no traceback.
- *Duplicate exception records.* Exactly one traceback per failure:
  - API: `unhandled_exception`, `app_error`/`db_error` at 500;
  - worker: Celery's record. The `celery_task_failed` and `leave_task_failed` summaries are
    compact.
- *Third-party telemetry.* None is configured. Sending employee data to an external service
  needs the privacy/security decision D3 first.
