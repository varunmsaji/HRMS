# ADR-0012: Outbox Pattern for Domain Events Touching Money or Compliance

**Status:** Accepted

## Context

Cross-module side effects that are asynchronous by nature go through domain events on the queue,
not direct calls (Doc 03 §4, rule 4) — e.g. `LeaveApproved` triggers attendance recompute and a
payroll LOP flag; `PayRunFinalised` triggers payslip notifications and the accounting export
(Doc 03 §4.1). A naive "commit the DB write, then publish to the queue" sequence has a real gap:
if the process crashes between the commit and the publish, the state change happened but dependent
modules never hear about it — for events like `PayRunFinalised` or `ExitFinalised`, that gap means
money moved or an employee was terminated in the system with no notification ever firing, no
accounting export ever queued, silently.

## Decision

Events that touch money or compliance are **persisted in the same database transaction as the
state change itself** (an outbox table), and only published to the queue afterward by a separate
relay process reading the outbox. Never fire-and-forget for anything in this category (Doc 03 §4.1,
closing line).

## Consequences

- **Positive:** the domain event and the state change it describes are atomically consistent —
  either both happened or neither did. There is no window where a pay run is finalised in the
  database but the notification/accounting/leave-encashment consumers never find out.
- **Positive:** the relay process can retry publishing independently of the original transaction,
  so a transient queue outage doesn't lose events — it delays them.
- **Negative:** an extra table and a relay process to operate and monitor (queue depth, oldest
  message age — Doc 14 §6.1 already tracks this at the platform level) compared to publishing
  directly from application code.
- **Negative:** consumers must still be idempotent (Doc 14 §5: "all jobs: idempotent, resumable")
  since outbox relay, like any at-least-once delivery mechanism, can redeliver an event after a
  crash mid-relay.

## Alternatives Considered

- **Publish to the queue directly after commit, no outbox.** Rejected: the crash-between-commit-
  and-publish gap is exactly the failure mode this decision exists to close, and it is unacceptable
  for events tied to money movement or compliance state (pay runs, exits, compensation changes).
- **Two-phase commit across the database and the message broker.** Rejected: adds distributed-
  transaction complexity and broker-specific 2PC support requirements for a problem the outbox
  pattern solves with a single additional table and a lightweight relay, using infrastructure
  (Postgres, Celery/Redis) already in the stack (ADR-0014).
