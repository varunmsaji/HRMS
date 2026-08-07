# Document 10 — Non-Functional Requirements, Security & Compliance

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
| NFR-P11 | No N+1 queries on any list endpoint — enforced by a query-count assertion in integration tests |

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
| NFR-A9 | Every background job is idempotent and resumable; no job may corrupt data on retry |
| NFR-A10 | Backups tested by **actual restore** monthly — an untested backup is not a backup |

**Deployment freeze calendar:** no production deployments on the 1st, 25th–31st of any month, or on
the day before/after a statutory filing due date, without a documented exception approved by the
engineering lead.

---

## 3. Security Requirements

### 3.1 Data Protection
| Control | Requirement |
|---|---|
| Encryption in transit | TLS 1.2+ everywhere; HSTS with preload; no plaintext internal hops |
| Encryption at rest | AES-256 for database, S3, backups and snapshots via KMS |
| Column-level encryption | PAN, Aadhaar, bank account, biometric templates, MFA secrets — encrypted with a separate key, decrypted only on authorised access |
| Key management | AWS KMS with annual rotation; keys never in code or environment variables |
| Data masking | Non-production environments use irreversibly anonymised data (§ Doc 03 §9) |
| PII in logs | Automatic redaction middleware; log review in the security checklist |
| Secure deletion | Crypto-shredding for tenant deletion; documented certificate of deletion |

### 3.2 Application Security
| Control | Requirement |
|---|---|
| OWASP Top 10 | Addressed and verified by automated scanning plus annual manual pentest |
| Authentication | Argon2id password hashing; MFA; secure session handling per SRS §1 |
| Authorization | Per Doc 06; deny-by-default; automated permission matrix tests |
| Input validation | Schema validation on every endpoint; reject unknown fields |
| Output encoding | Context-aware encoding; CSP header with no `unsafe-inline` |
| SQL injection | Parameterised queries only; raw SQL reviewed and linted |
| File upload | Type allow-list, magic-byte verification, size caps, ClamAV scan, served from a separate origin via presigned URLs |
| CSRF | SameSite=Strict cookies + token for state-changing form posts |
| Rate limiting | Per Doc 05 §1.9 |
| Dependency scanning | Automated (Dependabot/Snyk) on every build; critical CVEs block the release |
| Secret scanning | Pre-commit hooks + CI; a leaked secret triggers immediate rotation |
| SAST / DAST | SAST on every PR; DAST weekly against staging |
| Container security | Minimal base images, non-root user, image scanning, no secrets in layers |

### 3.3 Infrastructure Security
- Private subnets for database and application; no public database endpoint
- Bastion-less access (SSM Session Manager); no long-lived SSH keys
- WAF with managed rule sets plus custom rules for the auth and ingestion endpoints
- DDoS protection (CloudFront + Shield)
- Least-privilege IAM roles; no wildcard policies; access reviewed quarterly
- All infrastructure changes via Terraform in version control; no console changes in production
- Centralised logging with tamper-evident storage; log retention 1 year hot, 7 years archived

### 3.4 Operational Security
| Control | Requirement |
|---|---|
| Production access | Break-glass only: time-boxed, approved, fully logged, reviewed post-hoc |
| Direct DB write access | **Prohibited** in production. Data fixes go through reviewed, audited scripts |
| Impersonation | Per FR-AUTH-011: reason, time limit, banner, audit, forbidden actions |
| Onboarding/offboarding of staff | Access provisioned by role; revoked within 4 hours of departure |
| Background checks | For staff with production data access |
| Security training | Annual, mandatory, with a secure-coding module for engineers |
| Vendor assessment | Every sub-processor assessed and listed publicly |

### 3.5 Incident Response
1. **Detect** — alerting on anomalous access, failed-auth spikes, data-export volume, error rates
2. **Triage** — severity classification (S1 data breach → S4 cosmetic) with defined response times
3. **Contain** — documented runbooks: revoke tokens, disable accounts, isolate services
4. **Notify** — DPDP Act requires notification to the Data Protection Board and affected data
   principals; customer contractual notification typically 24–72 h. Templates prepared in advance.
5. **Remediate & review** — blameless post-mortem within 5 working days, published to affected customers

**Breach notification readiness is a launch requirement, not a post-launch task.** Have the
template, the contact list and the decision tree ready before the first customer's data is loaded.

---

## 4. Privacy & Data Protection (DPDP Act 2023, India)

| Obligation | Implementation |
|---|---|
| **Roles** | The customer company is the **Data Fiduciary**; the platform is a **Data Processor**. This must be stated in the DPA and understood by the support team — we do not decide purposes for employee data. |
| Notice & consent | Employee-facing privacy notice per tenant; consent records for optional processing (biometrics, WhatsApp, AI screening, location tracking) with timestamp, version and withdrawal capability |
| Purpose limitation | Each data category mapped to a declared purpose; no secondary use without a new basis |
| Data minimisation | Collect only what a stated feature requires; challenge every "nice to have" field |
| Accuracy | Employee-initiated correction workflow (FR-EMP-009) |
| Storage limitation | Retention policy engine (FR-AUD-006) with per-category periods |
| Right to access | Self-service export of all data held about an employee, machine-readable |
| Right to correction & erasure | Workflow with legal-hold override (payroll records cannot be erased before statutory retention expires — this exception must be explained to the employee, not silently applied) |
| Grievance redressal | Named Grievance Officer per tenant, contact surfaced in the app, tracked SLA |
| Cross-border transfer | Default: all data in India (ap-south-1). Any sub-processor outside India documented and assessed |
| Children's data | Not applicable to employees, but applies to dependants' records — restrict and justify |
| Breach notification | Per §3.5 |

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

## 5. Compliance Framework (India)

| Statute | Impact on the product |
|---|---|
| **Payment of Wages Act** | Wage period ≤1 month; payment deadlines; permitted deductions only; wage register format |
| **Minimum Wages Act** | State- and skill-category-wise minimum wage validation at payroll (FR-PAY-015) |
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
> client is responsible for engaging a qualified compliance consultant to verify all payroll and
> statutory logic before go-live (BRD dependency D5) and for keeping the statutory master current
> thereafter. The engineering team implements a **configurable, effective-dated rules engine**;
> it does not warrant legal compliance. This must be stated explicitly in the contract.

---

## 6. Usability & Accessibility

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

---

## 7. Maintainability & Code Quality

| NFR | Requirement |
|---|---|
| NFR-M1 | Unit test coverage ≥ 80% overall; **≥ 95% for payroll calculation, leave accrual, attendance resolution and RBAC** |
| NFR-M2 | Every PR requires review by one engineer other than the author; payroll and security changes require two |
| NFR-M3 | Linting, formatting, type checking and tests enforced in CI; no bypass |
| NFR-M4 | Module boundary rules enforced by dependency-cruiser in CI (Doc 03 §4) |
| NFR-M5 | All configuration via environment variables/parameter store; nothing environment-specific in code |
| NFR-M6 | Database migrations reviewed, forward-only, online-safe |
| NFR-M7 | ADRs recorded for every significant decision |
| NFR-M8 | API documented via OpenAPI, generated from code, CI-validated |
| NFR-M9 | Structured JSON logging with correlation ids propagated across API → queue → worker |
| NFR-M10 | Feature flags for every risky feature, with a documented kill-switch procedure |
| NFR-M11 | Technical debt logged as tickets with an owner; ≥15% of each sprint reserved for debt and defects |

---

## 8. Observability

| Layer | What we monitor |
|---|---|
| **Infrastructure** | CPU, memory, disk, connections, replica lag, queue depth |
| **Application** | Request rate, error rate, latency percentiles per endpoint, saturation |
| **Business** | Payroll runs completed/failed, punches ingested, notifications delivered/failed, logins, approval SLA breaches, integration health |
| **Per-tenant** | Usage, error rate, cost — so we can tell "the platform is fine, this one tenant is broken" |

**Alerting tiers:**
| Severity | Example | Response |
|---|---|---|
| S1 | Data breach, payroll data corruption, total outage | Immediate page, 15-min response, all-hands |
| S2 | Payroll run failure, punch ingestion down, auth failures spiking | Page, 30-min response |
| S3 | Integration degraded, elevated error rate, queue backlog | Business-hours, 4-h response |
| S4 | Cosmetic, single-tenant non-blocking | Next sprint |

**Golden signals dashboard** on a wall/Slack channel: request rate, error rate, p95 latency, queue
depth, active payroll runs, punch ingestion rate. If the team cannot see these at a glance, incidents
will be discovered by customers instead.

---

## 9. Support & SLA (customer-facing)

| Plan | First response | Resolution target (S1/S2/S3) | Channels |
|---|---|---|---|
| Starter | 24 h | 3 d / 5 d / best effort | Email, in-app |
| Growth | 8 h | 8 h / 2 d / 5 d | + chat |
| Enterprise | 2 h | 4 h / 1 d / 3 d | + phone, named CSM |

**Payroll-critical escalation:** during the 25th–5th window, any payroll-blocking issue is treated
as S1 regardless of plan. This should be stated in the SLA — it is what customers actually care
about and it is a genuine differentiator.

---

## 10. NFR Acceptance & Verification

| NFR area | Verified by | Gate |
|---|---|---|
| Performance | Automated load tests (k6/Gatling) in CI-nightly and pre-release | Targets in §1 met |
| Security | SAST/DAST/dependency scan per build; external pentest before go-live and annually | Zero critical/high open |
| Availability | Chaos testing (kill a pod, fail over the DB) in staging quarterly | Recovery within RTO |
| Backup/DR | Monthly restore test, annual full DR drill | Documented success |
| Accessibility | axe-core in CI + manual screen-reader audit of the top 20 screens | Zero critical violations |
| Compliance | Compliance consultant sign-off on payroll outputs; legal review of the DPA and privacy notice | Written sign-off |
| Data isolation | Automated cross-tenant leakage suite on every build | 100% pass |

**No go-live without:** external pentest report with critical/high items remediated, compliance
consultant sign-off on payroll, a successful restore test, and a completed DPA.
