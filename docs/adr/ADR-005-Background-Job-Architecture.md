# ADR-005: Background Job Architecture

**Status:** Accepted  
**Date:** 2026-08-03  
**Detailed ADR:** [0014-celery-redis-job-queue.md](0014-celery-redis-job-queue.md)

## Context

HRMS needs scheduled jobs (accrual, outbox sweep), long payroll pipelines, notification fan-out, and AI batch processing. Previous stack used BullMQ (Node). Backend is Python.

## Decision

Use **Celery** with **Redis** as broker and result backend:

- Workers: `entrypoints/worker.py`
- Scheduler: Celery Beat via `entrypoints/beat.py`
- Tasks: `modules/<name>/tasks.py`
- Monitoring: Flower + OpenTelemetry + Grafana
- Outbox relay: beat-scheduled sweep (ADR-0012)

## Consequences

- **Positive:** Canvas chains/chords for payroll pipeline.
- **Positive:** Mature ops tooling for solo developer.
- **Positive:** OTel trace propagation API → worker → DB.
- **Negative:** More moving parts than ARQ/RQ.
- **Negative:** Workers are sync processes wrapping async via careful session handling.

## Alternatives rejected

- BullMQ (Node — stack removed)
- ARQ / RQ (insufficient workflow orchestration)
- Dramatiq (less mature monitoring/ecosystem for this workload mix)
