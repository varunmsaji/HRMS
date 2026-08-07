# Document 23 — Non-Functional Requirements & Compliance

**Version:** 2.0 — migrated from Document 10 v1.0 ("Non-Functional Requirements, Security &
Compliance"). Security-specific requirements (§3 and §3.5 of the original) moved to
**Document 14 — Security Architecture**. This document keeps performance, availability, usability/
accessibility, privacy/regulatory compliance, and support SLA content, all of which is
**stack-independent and unchanged in substance** by the FastAPI migration.

---

## 1. Performance & Scalability

| NFR | Requirement |
|---|---|
| NFR-P1 | API p95 latency < 500 ms for reads, < 800 ms for writes (excluding long-running jobs) |
| NFR-P2 | Page interactive (LCP) < 2.5 s on a 4G connection for the web app |
| NFR-P3 | Mobile app cold start < 3 s; punch action completes < 2 s on 3G |
| NFR-P4 | Support 3,000 concurrent users; 200 sustained req/s; 2,000 req/s burst during the 9–10 AM punch window |
| NFR-P5 | Payroll: 5,000 employees computed in ≤ 10 minutes; 500 in ≤ 3 minutes |
| NFR-P6 | Attendance recompute for 5,000 employee-days in ≤ 2 minutes |
| NFR-P7 | Report export of 100k rows completes in ≤ 5 minutes (async) |
| NFR-P8 | Punch ingestion: 10,000 punches/minute per tenant with < 200 ms ack |
| NFR-P9 | Database growth to 2 TB without architectural change; partitioning and archival in place from day 1 |
| NFR-P10 | Horizontal scale: API and workers stateless, autoscaled on CPU and queue depth |
| NFR-P11 | No N+1 queries on any list endpoint — enforced by a query-count assertion in integration tests (Document 08 §15, Document 15 §2) |

**Load-test scenarios (must be automated and run before each release):**
1. Morning punch storm: 50,000 punches in 15 minutes
2. Month-end: 20 concurrent payroll runs across tenants
3. Salary day: 30,000 employees opening payslips within 2 hours
4. Report storm: 200 concurrent report generations
5. Sustained: 200 req/s for 30 minutes with a mixed workload

---

## 2. Availability & Reliability

| NFR | Requirement |
|---|---|
| NFR-A1 | 99.9% monthly uptime (≈43 min downtime/month) for the core application |
| NFR-A2 | 99.95% for the punch-ingestion service — lost punches are lost wages |
| NFR-A3 | **Zero planned downtime during month-end (25th–5th)** — the payroll blackout window |
| NFR-A4 | RPO ≤ 5 minutes (point-in-time recovery); RTO ≤ 2 hours |
| NFR-A5 | Multi-AZ deployment; database failover automatic and tested quarterly |
| NFR-A6 | Cross-region backup replication; annual full DR drill with documented results |
| NFR-A7 | Zero-downtime deployments (blue-green or rolling with health checks and automatic rollback) |
| NFR-A8 | Graceful degradation: if AI, SMS, calendar or accounting integrations fail, core HR functions continue |
| NFR-A9 | Every background job (Celery task, Document 11 §2) is idempotent and resumable; no task may corrupt data on retry |
| NFR-A10 | Backups tested by **actual restore** monthly — an untested backup is not a backup |

**Deployment freeze calendar:** no production deployments on the 1st, 25th–31st of any month, or on
the day before/after a statutory filing due date, without a documented exception (Document 16 §2).

---

## 3. Usability & Accessibility — Unchanged

| NFR | Requirement |
|---|---|
| NFR-U1 | WCAG 2.1 Level AA for all employee-facing web screens; Level A minimum for admin screens |
| NFR-U2 | Keyboard navigable; visible focus indicators; logical tab order |
| NFR-U3 | Screen-reader labels on all interactive elements; ARIA landmarks |
| NFR-U4 | Colour contrast ≥4.5:1; never colour alone to convey status (attendance calendars must use icons/patterns as well as colour) |
| NFR-U5 | Mobile: touch targets ≥44×44 pt; font scaling honoured up to 200% |
| NFR-U6 | Error messages state what went wrong **and what to do next**, in plain language |
| NFR-U7 | Destructive actions require confirmation naming the specific object ("Delete pay run for March 2026?") |
| NFR-U8 | No data loss on navigation: unsaved-change warnings, form draft persistence |
| NFR-U9 | Multi-language: English, Hindi, Malayalam, Tamil (Phase 1 scope for ESS; strings externalised for all) |
| NFR-U10 | Low-literacy support: icon-led punch flow, voice prompt option (Phase 3) for field/blue-collar staff |

These are entirely frontend (Next.js/React Native, Document 24) concerns, unaffected by the backend
language.

---

## 4. Privacy & Data Protection (DPDP Act 2023, India) — Unchanged

| Obligation | Implementation |
|---|---|
| **Roles** | The customer company is the **Data Fiduciary**; the platform is a **Data Processor**. This must be stated in the DPA and understood by anyone doing support — we do not decide purposes for employee data. |
| Notice & consent | Employee-facing privacy notice per tenant; consent records for optional processing (biometrics, WhatsApp, AI screening, location tracking) with timestamp, version and withdrawal capability |
| Purpose limitation | Each data category mapped to a declared purpose; no secondary use without a new basis |
| Data minimisation | Collect only what a stated feature requires; challenge every "nice to have" field |
| Accuracy | Employee-initiated correction workflow (Document 17) |
| Storage limitation | Retention policy engine (Document 08 §11 `file.retention_until`) with per-category periods |
| Right to access | Self-service export of all data held about an employee, machine-readable |
| Right to correction & erasure | Workflow with legal-hold override (payroll records cannot be erased before statutory retention expires — this exception must be explained to the employee, not silently applied) |
| Grievance redressal | Named Grievance Officer per tenant, contact surfaced in the app, tracked SLA |
| Cross-border transfer | Default: all data in India (ap-south-1). Any sub-processor outside India documented and assessed — including LLM API providers used by Document 12; Document 21 §5 P5/P6 already require data-minimisation before any external call |
| Children's data | Not applicable to employees, but applies to dependants' records — restrict and justify |
| Breach notification | Per Document 14 §5 |

**Statutory retention (India) — these override deletion requests:**
| Record | Retention |
|---|---|
| Payroll and wage registers | 8 years |
| PF records | 7 years after exit |
| ESI records | 5 years |
| Income tax / TDS records | 8 years |
| Attendance/muster roll | 3 years (Shops & Establishments; state variance) |
| Contract labour records | 3 years |
| POSH complaint records | As directed by the Act and the Internal Committee |
| Recruitment records (unsuccessful candidates) | 6–12 months with consent; then delete |

---

## 5. Compliance Framework (India) — Unchanged

| Statute | Impact on the product |
|---|---|
| **Payment of Wages Act** | Wage period ≤1 month; payment deadlines; permitted deductions only; wage register format |
| **Minimum Wages Act** | State- and skill-category-wise minimum wage validation at payroll (Document 17) |
| **EPF & MP Act** | PF contribution, UAN, ECR filing, wage ceiling handling |
| **ESI Act** | ESI contribution, IP number, wage ceiling, contribution periods |
| **Payment of Gratuity Act** | 5-year eligibility, 15/26 formula, ceiling, nomination (Form F) |
| **Payment of Bonus Act** | Eligibility ceiling, min 8.33% / max 20%, Form C register |
| **Maternity Benefit Act** | 26 weeks, job protection, crèche provision flag, no dismissal during the period |
| **Factories Act** | Working hours, OT at 2×, weekly off, leave with wages, registers |
| **Shops & Establishments Acts** | State-specific hours, leave, holidays, registers — the biggest source of state variance |
| **Contract Labour (R&A) Act** | Contractor registration, licence, principal-employer register |
| **POSH Act 2013** | Internal Committee, complaint confidentiality, annual report |
| **Income Tax Act** | TDS computation, Form 16, Form 24Q, Form 12BB declarations |
| **Professional Tax** | State-specific slabs and filing frequency |
| **Labour Welfare Fund** | State-specific contributions and periodicity |
| **Rights of Persons with Disabilities Act** | Accessibility, non-discrimination, reservation reporting for applicable establishments |
| **The four Labour Codes** | Passed but implementation is staged; the platform's effective-dated statutory design allows a data-driven transition. Monitor and do not hardcode current rules. |

> ⚠ **Compliance disclaimer for the project:** every statutory rate, slab, threshold and format
> encoded in the system is **indicative and subject to change by government notification**. The
> client/business owner is responsible for engaging a qualified compliance consultant to verify all
> payroll and statutory logic before go-live (Document 02 dependency D5) and for keeping the
> statutory master current thereafter. The engineering implements a **configurable, effective-dated
> rules engine**; it does not warrant legal compliance.

---

## 6. Support & SLA (customer-facing) — Unchanged Structure, Re-Baseline Owner Noted

| Plan | First response | Resolution target (S1/S2/S3) | Channels |
|---|---|---|---|
| Starter | 24 h | 3 d / 5 d / best effort | Email, in-app |
| Growth | 8 h | 8 h / 2 d / 5 d | + chat |
| Enterprise | 2 h | 4 h / 1 d / 3 d | + phone, named CSM |

**Payroll-critical escalation:** during the 25th–5th window, any payroll-blocking issue is treated
as S1 regardless of plan.

**Solo-developer note:** these SLA numbers were written for a support-staffed operation. Whether they
are honestly achievable by a single developer once paying customers exist is a business decision for
Document 25/Document 26, not an engineering one — this document states the target the *system* must
be capable of meeting (fast detection, clear runbooks, Document 16 §9); whether a human is available
to act on it within these windows is a staffing decision, flagged explicitly rather than silently
assumed.

---

## 7. NFR Acceptance & Verification

| NFR area | Verified by | Gate |
|---|---|---|
| Performance | Automated load tests (k6) in CI-nightly and pre-release | Targets in §1 met |
| Security | See Document 14 §6 and Document 15 §6 | Zero critical/high open |
| Availability | Chaos testing (kill a task, fail over the DB) in staging quarterly | Recovery within RTO |
| Backup/DR | Monthly restore test, annual full DR drill (Document 16 §7) | Documented success |
| Accessibility | axe-core in CI + manual screen-reader audit of the top 20 screens | Zero critical violations |
| Compliance | Compliance consultant sign-off on payroll outputs; legal review of the DPA and privacy notice | Written sign-off |
| Data isolation | Automated cross-tenant leakage suite on every build (Document 15 §6) | 100% pass |

**No go-live without:** external pentest report with critical/high items remediated, compliance
consultant sign-off on payroll, a successful restore test, and a completed DPA.
