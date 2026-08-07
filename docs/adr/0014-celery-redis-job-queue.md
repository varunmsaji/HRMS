# ADR-0014: Celery + Redis as the Official Background Job System, Replacing BullMQ

**Status:** Accepted

## Context

BullMQ (Node.js/Redis) was the background-job system under the original NestJS-based design.
ADR-0013 replaces the backend language with Python, which means BullMQ — a Node-specific library —
cannot come along. Python has four realistic replacement candidates: Celery, Dramatiq, ARQ, and RQ.

This system's background workload is more demanding than "send an email later": it includes the
checkpointed, multi-step, CPU-bursty payroll pipeline (Doc 03 §5 — create, snapshot, compute in
parallel batches, validate, variance-check, human-review gate, finalise, produce outputs), a
notification fan-out across email/SMS/WhatsApp/push/in-app (Doc 20 §9), a large scheduled-job
catalogue (Doc 11 §4), and AI batch processing (Doc 12). It also has to be operable by one person
with no team to watch dashboards in shifts.

## Decision

**Celery + Redis** (Redis as both broker and result backend) is the official background job system.
Full comparison table in Doc 04 §3; summary of the deciding factors:

1. **Canvas primitives** (`chain`, `group`, `chord`) map directly onto the payroll pipeline's
   checkpointed multi-step structure and its parallel-batch compute step (Doc 11 §3) — this is not
   available in equivalent form in ARQ or RQ, and is materially more expressive in Celery than in
   Dramatiq.
2. **Flower**, Celery's monitoring dashboard, gives a solo operator task history, worker status,
   queue depth and retry visibility with no custom tooling required (Doc 11 §5) — none of the
   alternatives have an equivalent.
3. **First-class OpenTelemetry instrumentation** (`opentelemetry-instrumentation-celery`) traces a
   task's execution as a span linked to its originating API request, giving the same
   API→queue→worker→DB tracing story the original BullMQ-based design relied on for payroll
   debugging (Doc 03 §1.3) — this was a deciding factor specifically because it preserves a
   debugging capability the team already depended on.
4. **`celery beat`** gives mature, database-backed periodic-task scheduling for the large scheduled-
   job catalogue (Doc 11 §4), which would need a bolted-on scheduler (e.g. APScheduler) under ARQ or
   Dramatiq.

## Consequences

- **Positive:** the payroll pipeline, notification fan-out, and scheduled-job catalogue all map onto
  native Celery constructs rather than requiring custom orchestration code.
- **Positive:** monitoring and tracing visibility is materially better for a solo operator than any
  of the lighter alternatives would provide out of the box.
- **Negative:** Celery is **not `asyncio`-native**. Every task body is a synchronous wrapper
  (`asyncio.run(...)`) around an async implementation function (Doc 11 §2) — a small, consistent
  pattern, but a real seam that ARQ (built on `asyncio` throughout) would not have required.
- **Negative:** higher operational surface area than ARQ or Dramatiq — more configuration (broker,
  result backend, beat scheduler, Flower), more moving parts for one person to operate. Accepted
  because the monitoring/tracing/canvas benefits outweigh this for the specific workload (payroll,
  not simple fire-and-forget jobs).
- **Mitigation for the added complexity:** this is a per-queue decision, not all-or-nothing (Doc 04
  §3). If evidence shows Celery's overhead isn't earning its keep for a specific simple queue (e.g.
  fire-and-forget notification sends), that queue can move to a lighter mechanism without disturbing
  the payroll/workflow queues that need Celery's full feature set.
- **Broker choice — Redis over RabbitMQ:** Redis was already a required dependency (cache, sessions,
  rate limiting — Doc 03 §6), so using it as the Celery broker avoids running an additional stateful
  service. RabbitMQ's stronger delivery guarantees are compensated for by the outbox pattern
  (ADR-0012, unchanged) and the idempotent task design rule (Doc 11 §2 rule 2) rather than needed
  from the broker itself.

## Alternatives Considered

- **ARQ.** Best technical fit for a purely `asyncio`-native, simple-job workload — but this system's
  workload is not simple, and ARQ has no equivalent to Celery's canvas primitives or Flower.
  Reconsidered and rejected specifically because the payroll pipeline would need custom
  chain/fan-out/checkpoint orchestration code that Celery provides natively.
- **Dramatiq.** A reasonable middle ground; rejected primarily for its thinner monitoring story
  relative to Flower and less expressive workflow composition than Celery's canvas.
- **RQ.** Not competitive for this workload — minimal workflow support, community-maintained
  scheduler add-on rather than a first-class one.

## Related

- Depends on: ADR-0013 (Python/FastAPI backend)
- See: Document 04 §3 (full comparison table), Document 11 (queue topology, task design rules,
  scheduled job catalogue), Document 03 §5 (payroll pipeline as a Celery canvas)
