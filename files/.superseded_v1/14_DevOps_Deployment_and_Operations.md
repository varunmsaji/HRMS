# Document 14 — DevOps, Deployment & Operations Runbook

---

## 1. Infrastructure (AWS ap-south-1, Mumbai)

```
Route 53 ──▶ CloudFront (static + CDN) ──▶ S3 (web build)
         └─▶ WAF ──▶ ALB ──▶ ECS Fargate services
                              ├── api            (2–10 tasks, autoscaled)
                              ├── ingestion      (2–6 tasks, separate target group)
                              ├── worker         (2–8 tasks, scaled on queue depth)
                              ├── scheduler      (1 task, leader-elected)
                              └── ai-service     (1–4 tasks)
                                        │
        ┌───────────────────────────────┼────────────────────────────────┐
        ▼                               ▼                                ▼
  RDS PostgreSQL 16              ElastiCache Redis              S3 buckets
  Multi-AZ primary               cluster mode, 2 nodes          documents / payslips
  + 1 read replica               (cache + queue + sessions)     resumes / exports / backups
        │                                                        SSE-KMS, versioned
        ▼
  Automated backups (35 d) + PITR + cross-region snapshot copy

Supporting: Secrets Manager · Parameter Store · KMS · CloudWatch · OpenSearch (logs + search)
            SES · SNS · EventBridge (schedules) · ECR (images)
```

### 1.1 Sizing (Phase 1 launch → 12 months)

| Component | Launch | 12 months (500 tenants / 150k employees) |
|---|---|---|
| API tasks | 2 × (1 vCPU, 2 GB) | 6 × (2 vCPU, 4 GB) |
| Worker tasks | 2 × (2 vCPU, 4 GB) | 6 × (2 vCPU, 8 GB) |
| Ingestion tasks | 2 × (0.5 vCPU, 1 GB) | 4 × (1 vCPU, 2 GB) |
| AI service | 1 × (2 vCPU, 4 GB) | 3 × (2 vCPU, 8 GB) |
| RDS | db.r6g.large, 200 GB gp3 | db.r6g.2xlarge, 1.5 TB gp3, 1–2 read replicas |
| Redis | cache.t4g.medium | cache.r6g.large ×2 |
| Estimated monthly cost | ~$900–1,200 | ~$4,500–6,500 |

Costs exclude AI provider charges, SMS/WhatsApp and support tooling. Review quarterly; the largest
growth driver is RDS storage and IOPS from `punch` and `audit_log`.

---

## 2. Environments

| Env | Infra | Data | Deploy trigger | Access |
|---|---|---|---|---|
| Local | Docker Compose | Seeded | Manual | Developers |
| Dev | Single small ECS cluster | Seeded synthetic | Auto on merge to `develop` | Team |
| QA | Production-shaped, smaller | Anonymised realistic | Auto on merge to `develop` | Team + QA |
| Staging/UAT | Production mirror | Anonymised client data | Manual promotion from QA | Client, QA, PM |
| Production | Full HA | Real | Manual approval after staging sign-off | Ops (break-glass only) |

Every environment is defined in Terraform. Environment differences are variables, not separate
configurations — otherwise "works in staging" stops meaning anything.

---

## 3. CI/CD Pipeline

```
Push / PR
  ├─ Lint + format + type check
  ├─ Unit tests (parallel shards) + coverage gate
  ├─ Build (Docker, multi-stage, non-root, minimal base)
  ├─ SAST (Semgrep) + dependency scan (Snyk) + secret scan
  ├─ Integration tests (Testcontainers: real Postgres + Redis)
  ├─ Security suites: cross-tenant isolation, permission matrix, data scope, field masking
  ├─ Contract tests against OpenAPI
  └─ Image push to ECR (tagged with commit SHA)

Merge to develop
  ├─ Deploy to Dev, then QA
  ├─ Run DB migrations (online-safe)
  ├─ E2E suite (Playwright) against QA
  ├─ Accessibility scan
  └─ Notify team

Promote to Staging (manual)
  ├─ Deploy, migrate, smoke test
  ├─ Load test (light)
  └─ UAT available

Promote to Production (manual, two approvers)
  ├─ Pre-deploy checklist (§4)
  ├─ Blue-green deploy with health checks
  ├─ Migrations run before the new version takes traffic
  ├─ Smoke tests against production
  ├─ Gradual traffic shift, automatic rollback on error-rate spike
  └─ Post-deploy verification + release notes
```

**Migration safety:** every migration is reviewed for lock behaviour. Long-running or locking
migrations run in a maintenance window outside the payroll blackout. Expand-contract pattern for
all schema changes; never a destructive change in a single release.

---

## 4. Deployment Checklist

### Pre-deploy
- [ ] All CI gates green, including the four security suites
- [ ] Release notes written; breaking changes flagged
- [ ] Migrations reviewed for lock behaviour and reversibility
- [ ] Feature flags configured (new features default off)
- [ ] Staging verified by QA and, for major releases, by the client
- [ ] **Not within the payroll blackout window** (25th–5th) unless it is a hotfix
- [ ] Rollback plan documented for this specific release
- [ ] On-call engineer identified and available

### During
- [ ] Migrations applied and verified
- [ ] Health checks passing on new tasks
- [ ] Error rate, latency and queue depth monitored during the traffic shift
- [ ] Smoke tests: login, punch, apply leave, view payslip, run a report

### Post-deploy
- [ ] Monitor for 30 minutes (errors, latency, queue depth, DB connections)
- [ ] Verify background jobs are processing
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

## 5. Scheduled Jobs

| Job | Schedule | Notes |
|---|---|---|
| Attendance day resolution | Every 15 min + event-triggered | Debounced per employee/date |
| Absent marking for the previous day | 02:00 company-local | After the punch-sync grace window |
| Leave accrual | Monthly, configurable day, 01:00 | Idempotent |
| Comp-off expiry | Daily 01:30 | |
| Leave year-end processing | On the FY boundary, manual confirm | Preview required |
| Future-dated changes activation | Daily 00:15 | Assignments, compensation, statutory |
| Probation/confirmation reminders | Daily 08:00 | T-30, T-15, T-0 |
| Document expiry alerts | Daily 08:00 | 30/15/7 days |
| Birthday/anniversary greetings | Daily 08:00 company-local | Opt-out honoured |
| Roster generation | Weekly | N weeks ahead |
| Access revocation for exits | Daily 23:55 | Per last working day |
| Notification retry sweep | Every 5 min | |
| Stuck workflow detection | Hourly | Flags requests idle > 7 days |
| Device heartbeat check | Every 30 min | Alert if silent > 2 h |
| Scheduled report delivery | Per user configuration | |
| Dashboard metric aggregation | Hourly | |
| Data retention enforcement | Weekly | |
| Audit log archival to S3 | Monthly | Partitions older than 12 months |
| Punch partition maintenance | Monthly | Create next, archive old |
| Backup restore verification | Monthly | Automated restore to a scratch instance |
| Statutory due-date reminders | Daily | Compliance calendar |

**All jobs:** idempotent, resumable, logged to `job_log`, monitored for both failure **and
non-execution** (a job that silently stops running is the more dangerous failure — alert on
"expected run did not occur").

---

## 6. Monitoring & Alerting

### 6.1 Dashboards
1. **Platform health** — request rate, error rate, p50/p95/p99 latency, task count, DB connections, replica lag
2. **Queue health** — depth per queue, processing rate, failure rate, DLQ size, oldest message age
3. **Business** — punches ingested/hour, active payroll runs, notifications sent/failed, logins, approvals pending
4. **Per-tenant** — usage, error rate, storage, AI spend, notification spend
5. **Cost** — daily AWS spend by service, AI provider spend, messaging spend

### 6.2 Key Alerts

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

### 6.3 On-Call
- Business hours: primary engineer rotation
- Payroll window (25th–5th): dedicated on-call with a 30-minute response commitment
- Escalation: primary → tech lead → engineering manager
- Runbook per alert, linked from the alert itself. An alert without a runbook link is an incomplete alert.

---

## 7. Backup & Disaster Recovery

| Asset | Backup | Retention | Restore test |
|---|---|---|---|
| PostgreSQL | Automated daily + PITR (5-min granularity) | 35 days; monthly snapshot 12 months | **Monthly, automated** |
| S3 documents | Versioning + cross-region replication | Per retention policy | Quarterly |
| Redis | Not backed up (cache); queue state reconstructible from the outbox | — | — |
| Secrets | Versioned in Secrets Manager | 90 days | Semi-annual |
| Infrastructure | Terraform state (versioned, locked) | Indefinite | Annual full rebuild drill |

**RPO 5 minutes, RTO 2 hours.**

### DR Procedure (summary — full runbook maintained separately)
1. Declare the incident; notify stakeholders; update the status page
2. Assess: region outage vs data corruption vs application failure
3. **Region outage:** promote the cross-region snapshot, apply Terraform in the DR region, update DNS
4. **Data corruption:** identify the corruption time; restore PITR to just before it; replay from the
   outbox where possible; reconcile
5. Verify: data integrity checks, smoke tests, a sample payroll recomputation comparison
6. Resume traffic; monitor closely for 24 hours
7. Post-mortem within 5 working days

**Annual DR drill is mandatory** and its results are documented. An untested DR plan is a document,
not a capability.

---

## 8. Tenant Operations

### 8.1 Onboarding a new tenant
1. Create the company record (self-serve or by Super Admin)
2. Seed industry template (leave types, shifts, salary structure, workflows, letters, designations)
3. Assign the subscription plan and entitlements
4. Create the first Company Admin user and send an invitation
5. Guided setup checklist in-app: entity → branch → department → designation → grade → holiday
   calendar → leave policy → salary structure → employees
6. Optional: assisted onboarding with data import and a configuration review call

**Target:** a self-serve SME is operational in under 2 hours; an assisted mid-market tenant in
under 5 working days.

### 8.2 Tenant suspension / termination
- Suspension (non-payment): read-only access, no new transactions, **payroll and payslip access
  preserved** — never hold an employee's salary record hostage to a billing dispute
- Termination: 30-day export window, full data export provided, then deletion per the DPA with a
  certificate of deletion issued

### 8.3 Support Tooling (build this — it is not optional)
- Tenant lookup with health summary
- Read-only data inspector (with sensitive fields masked and every access logged)
- Job history and retry per tenant
- Notification delivery log
- Integration status and connection test
- Audit log search
- Impersonation with the controls in FR-AUTH-011

Without support tooling, every customer issue becomes an engineer running production queries by
hand — which is slow, error-prone and a compliance problem.

---

## 9. Incident Response Runbooks (index)

Each has a dedicated page with detection, diagnosis, mitigation, verification and communication steps:

1. Payroll run failed or produced wrong figures
2. Punch ingestion stopped
3. Biometric device fleet offline for a tenant
4. Cross-tenant data exposure suspected
5. Authentication outage
6. Database failover
7. Queue backlog / worker stall
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

## 10. Release Cadence & Versioning

| Type | Cadence | Content |
|---|---|---|
| Hotfix | As needed | S1/S2 defects only; minimal change; expedited but still gated |
| Patch | Weekly (Tuesday) | Bug fixes, small improvements |
| Minor | Bi-weekly (end of sprint) | New features behind flags |
| Major | Quarterly | Significant capabilities; customer communication in advance |

Semantic versioning for the API and mobile app. Mobile supports the current plus the previous two
minor versions; below that, a forced upgrade.

**Payroll blackout:** no deployments 25th–5th except hotfixes approved by the engineering manager.
Communicate the blackout calendar to customers — they will appreciate that their payroll week is
protected, and it becomes a trust signal rather than an inconvenience.

---

## 11. Documentation to Maintain

| Doc | Owner | Update trigger |
|---|---|---|
| ADRs | Tech Lead | Every significant decision |
| OpenAPI spec | Backend | Auto-generated, CI-validated |
| Runbooks | DevOps | Every incident (add or refine one) |
| Onboarding guide for new engineers | Tech Lead | Quarterly |
| Deployment guide | DevOps | On pipeline change |
| Statutory rules reference (what is implemented, with sources) | BA + Compliance | Every notification |
| User help centre | Technical Writer | Every feature release |
| Release notes | PM | Every release |
| Data flow and processing register (DPDP) | PM + Legal | Every new data use |

**Target:** a new engineer is productive within 5 working days using documentation alone, without
needing a senior engineer to explain the system. Test this with each new joiner and fix the gaps
they hit — those gaps are the real documentation backlog.
