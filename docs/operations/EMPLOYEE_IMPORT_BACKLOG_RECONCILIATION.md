# Employee-import backlog reconciliation

> **Purpose.** Before a worker is allowed to drain the `reports_exports` queue (decision D-B),
> an operator needs to know which queued `employee_import.process_batch` messages refer to which
> batches, and what state those batches are in. This procedure and the read-only tool
> `hrms.ops.import_backlog` give that picture. **They never decide, and never perform, a
> replay or a discard.** Whether old business data is imported is an explicit decision made by
> the tenant's HR owner and the operator.

## 1. What is guaranteed, and what is not

| Guaranteed (tested) | Not guaranteed |
|---|---|
| A batch is processed only if it is atomically claimed `PENDING → PROCESSING`. A redelivered, duplicated or concurrent message is skipped (`employee_import.batch.skipped`, `reason=not_pending`). | That an *old* `PENDING` batch is still wanted. The claim does not look at age. |
| A message for a missing batch is logged and ignored (`reason=missing`). | That a queued message means the batch was never run. The batch row is the only source of truth. |
| A batch marked `FAILED` before the worker starts is skipped without being touched (counters, version and timestamps unchanged). | That employees created by a past run can be traced to a batch: `employee` has **no link to the import batch**. Compare counters and the audit log instead. |
| The tool changes nothing: Redis gets only `LLEN`/`LRANGE`; every Postgres session is `SET TRANSACTION READ ONLY` and rolled back. | |

## 2. Run the report

From the deployment directory, **before starting or restarting the worker against the queue**.
It can be run from the `api` container, which does not consume the queue:

```bash
docker compose -f docker-compose.prod.yml exec -T api python -m hrms.ops.import_backlog > /tmp/import_backlog.json
```

Options:

| Option | Meaning |
|---|---|
| `--company-id <uuid>` (repeatable) | Also scan this tenant for `PENDING`/`PROCESSING` batches that have **no** queued message. Without it, only companies named in queued messages are inspected. |
| `--all-companies` | Scan every company. Needs a database role that may list `company`; with the application's RLS role this can return nothing. |
| `--stale-pending-hours N` | A `PENDING` batch older than this is `STALE_PENDING` (default 24; provisional). |
| `--queue NAME` | Inspect a different queue list (default `reports_exports`). |

Exit code is 0 when the report was produced, 2 if Redis is unreachable.

The tool reads the database as the **application role**, so row-level security applies: it can only
see a company's batches because the company ID in the message is used as the tenant scope. A
batch it cannot see is reported `NOT_VISIBLE`, never guessed.

## 3. Reading the report

`queue` gives the depth and how many messages are import tasks (`other_tasks` counts any other task
found on the queue, plus `unparseable`). `summary` counts recommendations. Each entry in `items`:

| `state` | `recommendation` | Meaning | What the worker will do if the message is drained |
|---|---|---|---|
| `PENDING` | `ELIGIBLE_TO_RUN` | `PENDING`, exactly one message, younger than the stale threshold, no later batch with the same filename. | Process it, once. |
| `STALE_PENDING` | `MANUAL_REVIEW` | `PENDING` for longer than the threshold. The file may be outdated. | **Process it.** The guard does not know it is old. |
| `PENDING` | `MANUAL_REVIEW` | Duplicate messages for the batch, or a later batch for the same company and filename (possible manual resubmission). | Process it once (first claim wins). |
| `PENDING_NO_MESSAGE` | `MANUAL_REVIEW` | `PENDING` with nothing queued: the message was lost, consumed, or never enqueued. | Nothing. It stays `PENDING` until someone resubmits. |
| `AMBIGUOUS` | `MANUAL_REVIEW` | `PENDING` with non-zero progress counters, or an unknown status. | Possibly process it. Investigate first. |
| `IN_PROGRESS` | `SAFE_TO_DRAIN` | `PROCESSING` and younger than twice the 3600 s hard limit. | Skip (`not_pending`). |
| `STALE_PROCESSING` | `MANUAL_REVIEW` | `PROCESSING` far beyond the hard limit: the run died. Rows may be partly created. | Skip. **Do not re-run blindly**: the pipeline is create-only. |
| `TERMINAL` | `SAFE_TO_DRAIN` | `COMPLETED`, `COMPLETED_WITH_ERRORS` or `FAILED`. | Skip (`not_pending`). |
| `NOT_VISIBLE` | `MANUAL_REVIEW` | No batch row visible for that company and ID (deleted, wrong company, or RLS). | Log `missing` and ignore. |
| `UNIDENTIFIED_MESSAGE` | `MANUAL_REVIEW` | The message arguments could not be read. | Unknown. |

`ELIGIBLE_TO_RUN` is a statement about the batch row, not an instruction.

## 4. Decide, per batch (operator and HR owner)

1. `SAFE_TO_DRAIN` and `NOT_VISIBLE`: no action. The messages are harmless once a worker drains them.
2. `ELIGIBLE_TO_RUN`: leave alone if the tenant still wants the import.
3. `STALE_PENDING`, duplicates, possible resubmissions: ask the tenant's HR owner.
   - **Wanted:** leave it `PENDING`. The worker will process it.
   - **Not wanted:** mark the batch `FAILED` **before** the worker starts (below). The queued
     message is then skipped.
4. `STALE_PROCESSING` and `AMBIGUOUS`: inspect `GET /employee-imports/{id}/errors` and the
   employees in question. Resolve by a fresh, smaller import for rows that did not land. Do not
   change the batch status.
5. `PENDING_NO_MESSAGE`: the tenant resubmits through the UI if they still want it.

Marking a batch `FAILED` (admin role, one batch at a time, after the HR owner has agreed; this is
a change to production data and needs the operator's own authorisation):

```sql
UPDATE employee_import_batch
SET status = 'FAILED', completed_at = now(), updated_at = now()
WHERE id = '<batch id>' AND company_id = '<company id>' AND status = 'PENDING';
```

Record who decided, when, and why, alongside the saved report file. Never `FLUSHDB`, `DEL`,
`LTRIM` or `LREM` the queue: the report and the status guard make deleting messages unnecessary,
and deleted messages cannot be audited.

## 5. After the decision

1. Re-run the report. Every remaining `PENDING` entry should be one that was explicitly kept.
2. Start the worker. Watch `employee_import.batch.skipped` and `employee_import.batch.started`
   events; the count of `started` events must equal the number of batches kept.
3. Keep the before/after reports with the change record.

## 6. Local evidence (development machine, 2026-10-14)

`reports_exports` in Redis DB 0 held **224** messages, all `employee_import.process_batch` (no
other task). The report classified all 224 as `NOT_VISIBLE`: 224 distinct company IDs, none with
a visible batch. That is consistent with test data from deleted tenants, and a worker would log
`reason=missing` for each. The queue depth was 224 before and after every run in this phase. The
**production** count is unknown and must be measured with this tool.

## 7. Tests

- `tests/unit/ops/test_import_backlog.py`: parsing, the classification matrix, resubmission
  detection, and proof that only `LLEN`/`LRANGE` are issued.
- `tests/integration/modules/employee_import/test_import_backlog_reconciliation.py`: real
  Celery-published messages (isolated broker DB 15, throw-away queue) against real batch rows;
  asserts queue depth and every batch row are unchanged by the report, that the database refuses
  writes from the tool's session, and that a batch pre-marked `FAILED` is skipped untouched.
- `tests/integration/modules/employee_import/test_import_idempotency.py`: sequential and
  concurrent claims.

## 8. Measuring the production backlog (separately authorised operator only)

This was **not** done in any development phase and must not be done by automation or by a
developer without the operator's explicit authorisation and a change record.

1. Authorisation: the platform owner approves in writing who runs the measurement and when.
2. From the production deployment directory, **using the `api` container, never `worker`** (the
   worker consumes). Confirm no worker is currently consuming `reports_exports`
   (`docker compose ps`); if one is, stop here and consult the owner: the backlog may already be draining.
3. `docker compose -f docker-compose.prod.yml exec -T api python -m hrms.ops.import_backlog > backlog_$(date +%F).json`.
   The tool issues only `LLEN`/`LRANGE` and read-only SQL. Save the file with the change record.
4. Independently of Redis, list database batches that are still open (admin role, read-only):

   ```sql
   SELECT company_id, id, status, original_filename, created_at, started_at, processed_rows
   FROM employee_import_batch
   WHERE status IN ('PENDING','PROCESSING') ORDER BY created_at;
   ```
5. Compare the two. **Queue depth alone proves nothing**: it counts messages, not batches; one batch can
   have several messages, a `PENDING` batch can have none, and many messages can belong to batches that
   already finished or no longer exist. The code's idempotency guard prevents *duplicate* processing; it does not
   say a stale batch is *wanted*.
6. Obtain the tenant HR owner's decision for every `STALE_PENDING`, duplicate and possible-resubmission
   entry (§4). Record it. Only then may anything be marked `FAILED`.
7. **No production worker may start consuming the historical messages until steps 3 to 6 are complete and
   the owner has approved in writing.**
