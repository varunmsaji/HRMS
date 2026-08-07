# Document 16 — Deployment Strategy

**Version:** 2.0 — split from Document 14 v1.0 ("DevOps, Deployment & Operations Runbook").
Infrastructure topology, CI/CD pipeline design, and observability tooling are in
**Document 13 — DevOps Architecture**. This document covers environments, the deployment
checklist/runbook, release cadence, backup/DR, and tenant operations — process content that is
almost entirely unchanged by the backend language migration, adapted where the solo-developer
delivery model (Document 01 §2, Document 25) genuinely changes what's realistic.

---

## 1. Environments — Unchanged

| Env | Infra | Data | Deploy trigger | Access |
|---|---|---|---|---|
| Local | Docker Compose (Document 13 §5) | Seeded | Manual | Developer |
| Dev | Single small ECS cluster | Seeded synthetic | Auto on merge to `develop` | Developer + any contractors |
| QA | Production-shaped, smaller | Anonymised realistic | Auto on merge to `develop` | Developer |
| Staging/UAT | Production mirror | Anonymised client data | Manual promotion from QA | Client, developer |
| Production | Full HA | Real | Manual approval after staging sign-off | Developer (break-glass only) |

Every environment is defined in Terraform (Document 13 §4). Environment differences are variables,
not separate configurations.

---

## 2. Deployment Checklist

### Pre-deploy
- [ ] All CI gates green, including the four security suites (Document 15 §6)
- [ ] Release notes written; breaking changes flagged
- [ ] Alembic migrations reviewed for lock behaviour and reversibility (Document 08 §14)
- [ ] Feature flags configured (new features default off)
- [ ] Staging verified (self-review checklist, Document 13 §2, plus client review for major releases)
- [ ] **Not within the payroll blackout window** (25th–5th) unless it is a hotfix
- [ ] Rollback plan documented for this specific release
- [ ] Developer available for the deploy window (there is no separate on-call to hand off to)

### During
- [ ] Migrations applied and verified
- [ ] Health checks passing on new tasks
- [ ] Error rate, latency and queue depth monitored during the traffic shift
- [ ] Smoke tests: login, punch, apply leave, view payslip, run a report

### Post-deploy
- [ ] Monitor for 30 minutes (errors, latency, queue depth, DB connections)
- [ ] Verify Celery workers are processing (Flower dashboard, Document 11 §5)
- [ ] Verify notification delivery
- [ ] Update the status page if customer-visible
- [ ] Close the release ticket with the deployed SHA recorded

### Rollback triggers (any one → roll back immediately, investigate afterwards)
- Error rate > 2× baseline for 5 minutes
- p95 latency > 3× baseline
- Any payroll computation failure
- Any authentication or authorization failure spike
- Any report of cross-tenant data visibility

---

## 3. Scheduled Jobs — See Document 11 §4

The full scheduled-job catalogue moved to Document 11 §4 (Background Job Architecture) since it is
now Celery Beat configuration, not a standalone operations table — keeping job *definitions* next to
the job *system* avoids the two drifting apart.

---

## 4. Monitoring & Alerting

### 4.1 Dashboards
1. **Platform health** — request rate, error rate, p50/p95/p99 latency, task count, DB connections, replica lag
2. **Queue health** — depth per queue, processing rate, failure rate, DLQ size, oldest message age (Document 11 §5)
3. **Business** — punches ingested/hour, active payroll runs, notifications sent/failed, logins, approvals pending
4. **Per-tenant** — usage, error rate, storage, AI spend, notification spend
5. **Cost** — daily AWS spend by service, AI provider spend, messaging spend

### 4.2 Key Alerts

| Alert | Threshold | Severity |
|---|---|---|
| API 5xx rate | > 1% for 5 min | S2 |
| p95 latency | > 2 s for 10 min | S3 |
| DB CPU | > 80% for 10 min | S2 |
| DB connections | > 80% of max | S2 |
| Replica lag | > 30 s | S3 |
| Queue depth | > 10,000 or growing 15 min | S2 |
| DLQ | Any message | S2 |
| Payroll run failure | Any | **S1** |
| Punch ingestion stopped | No punches for 15 min in business hours | **S1** |
| Cross-tenant access detected | Any | **S1** |
| Auth failure spike | > 5× baseline | S2 |
| Device offline | > 2 h | S3 (tenant alert) |
| Scheduled job did not run | Missed window | S2 |
| Certificate expiry | < 21 days | S3 |
| Disk/storage | > 80% | S3 |
| Daily cost anomaly | > 150% of the 7-day average | S3 |

### 4.3 On-Call — Re-Baselined for a Solo Developer

The original on-call rotation (primary engineer → tech lead → engineering manager) does not exist.
What replaces it:

- **The developer is the entire on-call rotation.** During the payroll window (25th–5th), this means
  actively protecting availability for incident response — not scheduling other high-focus work
  (a new module build, a large refactor) that would make a 30-minute S1 response commitment
  unrealistic (Document 23 §6 payroll-critical escalation).
- **Every alert links to a runbook** (§9) — this matters *more* without a second person to improvise
  a response from first principles under pressure.
- **A dead-man's-switch alert** (a periodic external ping that must be acknowledged) is recommended
  so that a genuinely incapacitated developer (illness, connectivity loss) is itself detected rather
  than silently leaving customers unsupported during a payroll-critical window — this is new relative
  to v1.0, which didn't need it because a team provides this redundancy implicitly.
- If a second developer or contractor is engaged (Document 25), the rotation and escalation path
  from v1.0 (primary → someone else) is reinstated.

---

## 5. Release Cadence & Versioning

| Type | Cadence | Content |
|---|---|---|
| Hotfix | As needed | S1/S2 defects only; minimal change; expedited but still gated |
| Patch | As completed | Bug fixes, small improvements — cadence follows the block-based schedule in Document 25, not a fixed weekly cycle |
| Minor | Per completed build block (Document 25) | New features behind flags |
| Major | Per phase completion | Significant capabilities; customer communication in advance |

Semantic versioning for the API and mobile app, unchanged. Mobile supports the current plus the
previous two minor versions; below that, a forced upgrade (Document 09 §7).

**Payroll blackout:** no deployments 25th–5th except hotfixes. Communicate the blackout calendar to
customers — it is a trust signal, not an inconvenience.

---

## 6. Backup & Disaster Recovery — Unchanged

| Asset | Backup | Retention | Restore test |
|---|---|---|---|
| PostgreSQL | Automated daily + PITR (5-min granularity) | 35 days; monthly snapshot 12 months | **Monthly, automated** |
| S3/MinIO documents | Versioning + cross-region replication (S3; MinIO is local-only, not backed up beyond dev convenience) | Per retention policy | Quarterly |
| Redis | Not backed up (cache); Celery broker state reconstructible from the outbox (Document 07 §7) and `job_log` | — | — |
| Secrets | Versioned in Secrets Manager | 90 days | Semi-annual |
| Infrastructure | Terraform state (versioned, locked) | Indefinite | Annual full rebuild drill |

**RPO 5 minutes, RTO 2 hours.**

### DR Procedure (summary)
1. Declare the incident; notify stakeholders; update the status page
2. Assess: region outage vs data corruption vs application failure
3. **Region outage:** promote the cross-region snapshot, apply Terraform in the DR region, update DNS
4. **Data corruption:** identify the corruption time; restore PITR to just before it; replay from the
   outbox where possible; reconcile
5. Verify: data integrity checks, smoke tests, a sample payroll recomputation comparison
6. Resume traffic; monitor closely for 24 hours
7. Post-mortem within 5 working days

**Annual DR drill is mandatory** and its results are documented.

---

## 7. Tenant Operations — Unchanged

### 7.1 Onboarding a new tenant
1. Create the company record (self-serve or by Super Admin)
2. Seed industry template (leave types, shifts, salary structure, workflows, letters, designations)
3. Assign the subscription plan and entitlements
4. Create the first Company Admin user and send an invitation
5. Guided setup checklist in-app: entity → branch → department → designation → grade → holiday
   calendar → leave policy → salary structure → employees
6. Optional: assisted onboarding with data import and a configuration review call

**Target:** a self-serve SME is operational in under 2 hours; an assisted mid-market tenant in
under 5 working days.

### 7.2 Tenant suspension / termination
- Suspension (non-payment): read-only access, no new transactions, **payroll and payslip access
  preserved** — never hold an employee's salary record hostage to a billing dispute
- Termination: 30-day export window, full data export provided, then deletion per the DPA with a
  certificate of deletion issued

### 7.3 Support Tooling — Build This
- Tenant lookup with health summary
- Read-only data inspector (with sensitive fields masked and every access logged)
- Job history and retry per tenant (now: Celery task history via Flower plus `job_log`, Document 11 §5)
- Notification delivery log
- Integration status and connection test
- Audit log search
- Impersonation with the controls in Document 10 §7

Without support tooling, every customer issue becomes hand-run production queries — slow,
error-prone, and a compliance problem, and with no second person to build this tooling later "when
there's time," it should be built early rather than deferred (Document 25).

---

## 8. Incident Response Runbooks (index)

Each has a dedicated page with detection, diagnosis, mitigation, verification and communication
steps:

1. Payroll run failed or produced wrong figures
2. Punch ingestion stopped
3. Biometric device fleet offline for a tenant
4. Cross-tenant data exposure suspected
5. Authentication outage
6. Database failover
7. Celery queue backlog / worker stall
8. Notification provider outage
9. AI provider outage or quota exhaustion
10. Deployment gone bad / rollback
11. Data corruption discovered
12. DDoS or abuse
13. Security vulnerability disclosed
14. Statutory rate change requiring an urgent update

**Runbook 1 (payroll) is the most important** and should be written first, rehearsed, and include
the exact steps to (a) prevent payment on incorrect figures, (b) communicate with the affected
tenant, and (c) correct via arrears rather than by editing history.

---

## 9. Documentation to Maintain

| Doc | Owner | Update trigger |
|---|---|---|
| ADRs | Developer | Every significant decision (Document 05 §6) |
| OpenAPI spec | Auto-generated | Auto-generated, CI-validated (Document 09 §8) |
| Runbooks | Developer | Every incident (add or refine one) |
| Onboarding guide for a future second developer/contractor | Developer | Quarterly, or before engaging any contractor |
| Deployment guide | Developer | On pipeline change |
| Statutory rules reference (what is implemented, with sources) | Developer + Compliance consultant | Every notification |
| User help centre | Developer (or a technical-writing contractor, Document 25) | Every feature release |
| Release notes | Developer | Every release |
| Data flow and processing register (DPDP) | Developer | Every new data use |

**Target, unchanged:** a new contributor is productive within 5 working days using documentation
alone. Test this the same way v1.0 proposed — watch where a new reader gets stuck, and fix that
specific gap (Document 01 §4, Document 05 §6).
