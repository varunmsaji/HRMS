# ADR-0007: Separate Ingestion Service for Biometric Punches

**Status:** Accepted

## Context

Attendance punches are 10-100x the write volume of any other event in the system (Doc 03 §5):
5,000 employees × 4 punches/day ≈ 20k writes/day for a single tenant, which becomes ~10M/day at
500 tenants. Biometric devices in the field do not retry indefinitely — a punch lost because the
Core API happened to be mid-deploy is a lost wage record, and attendance/payroll disputes are
exactly the kind of support burden this product is trying to design away (Doc 03 §5, §8).

## Decision

A dedicated **Device Ingestion service**, deployed and scaled independently from the Core API,
sits in front of the biometric push path:

```
Biometric device ──HTTP push──▶ Ingestion Service ──▶ Redis Stream ──▶ Punch Writer
                                     │                                     │
                                 validate device key                  batch insert into
                                 dedupe (device+emp+ts)               punch (partitioned by month)
                                 buffer if DB slow                         │
                                                                           ▼
                                                              Attendance Day Recompute Job
                                                              (debounced per employee per date)
```

It must accept punches even while the Core API is deploying. The `punch` table is partitioned by
month; recompute is debounced so multiple punches for the same employee/date within 60 seconds
trigger one recompute, not several.

## Consequences

- **Positive:** a Core API deploy, incident, or scale-up never causes a lost punch — the ingestion
  service has its own deploy lifecycle and its own scaling profile (Doc 14 §1: separate ECS target
  group).
- **Positive:** the high-volume write path (punches) is isolated from interactive request latency
  budgets (Doc 03 §10: punch ingestion ack < 200ms vs. dashboard load < 1.5s) — it can be tuned and
  scaled independently without touching the Core API's resource profile.
- **Negative:** one more service to deploy, monitor and reason about, with its own on-call runbook
  (Doc 14 §9, runbook 2/3) — accepted because the alternative (punches routed through the same
  process as everything else) has already been identified as a scaling bottleneck at the sizing
  Doc 03 §5 lays out.
- **Negative:** the dedupe/buffer logic (device+employee+timestamp) must be correct and tested
  independently, since a bug here either drops real punches or double-counts attendance.

## Alternatives Considered

- **Route biometric punches through the Core API like any other write.** Rejected: couples the
  highest-volume, most failure-intolerant write path to the deploy cadence and resource profile of
  every other module, which is exactly the risk this ADR exists to remove.
- **Serverless (Lambda) ingestion.** Rejected in Doc 03 §2.3 generally for CPU-bursty workloads;
  while punches themselves are lightweight, keeping the whole attendance path on one runtime model
  (ECS Fargate, per Doc 14 §1) simplifies operations.
