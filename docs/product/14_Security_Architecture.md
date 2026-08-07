# Document 14 — Security Architecture

**Version:** 2.0 — split from Document 10 v1.0 ("Non-Functional Requirements, Security &
Compliance") §3 ("Security Requirements") and §3.5 ("Incident Response"), elevated to its own
document. Performance, availability, usability/accessibility, and regulatory/compliance content
(DPDP, labour law) moved to **Document 23 — Non-Functional Requirements & Compliance**. RBAC/
permission design is **Document 19**; authentication mechanics are **Document 10** (Authentication
Architecture — note the document renumbering means "Document 10" now refers to Authentication
Architecture, not this NFR-derived content, per Document 00's map). **Almost none of the substance
here changed** — security requirements are close to stack-independent; what changed is which
Python-specific library or mechanism satisfies each requirement.

---

## 1. Data Protection

| Control | Requirement | Implementation note (Python-specific where relevant) |
|---|---|---|
| Encryption in transit | TLS 1.2+ everywhere; HSTS with preload; no plaintext internal hops | Unchanged — ALB/CloudFront termination, service mesh internal TLS where applicable |
| Encryption at rest | AES-256 for database, S3/MinIO, backups and snapshots via KMS | Unchanged |
| Column-level encryption | PAN, Aadhaar, bank account, biometric templates, MFA secrets — encrypted with a separate key, decrypted only on authorised access | `cryptography` (Fernet or AES-GCM via `cryptography.hazmat`) wrapping a SQLAlchemy `TypeDecorator` so encryption/decryption happens transparently at the model boundary — was: a Prisma middleware or explicit field-level encryption helper in the NestJS service layer; the SQLAlchemy `TypeDecorator` pattern is the direct equivalent |
| Key management | AWS KMS with annual rotation; keys never in code or environment variables | Unchanged; the application fetches data keys via `boto3`/`aioboto3` (async), not the Node AWS SDK |
| Data masking | Non-production environments use irreversibly anonymised data (Document 03 §8) | Unchanged |
| PII in logs | Automatic redaction middleware; log review in the security checklist | ASGI middleware / a `structlog` processor that redacts known-sensitive field names before a log line is emitted (Document 13 §3) |
| Secure deletion | Crypto-shredding for tenant deletion; documented certificate of deletion | Unchanged |

---

## 2. Application Security

| Control | Requirement | Implementation note |
|---|---|---|
| OWASP Top 10 | Addressed and verified by automated scanning plus annual manual pentest | Unchanged as a requirement |
| Authentication | Argon2id password hashing; MFA; secure session handling | Document 10 (Authentication Architecture) — `argon2-cffi`, `pyotp` |
| Authorization | Deny-by-default; automated permission matrix tests | Document 19; FastAPI `Depends(require_permission(...))` (Document 07 §4) |
| Input validation | Schema validation on every endpoint; reject unknown fields | Pydantic v2 with `extra="forbid"` (Document 09 §6) — this is arguably **stronger** than the previous `class-validator`/zod setup because it's the same validation layer FastAPI uses to generate the OpenAPI schema, so the documented contract and the enforced contract cannot drift apart |
| Output encoding | Context-aware encoding; CSP header with no `unsafe-inline` | Unchanged — enforced at the frontend (Next.js) and via response headers middleware |
| SQL injection | Parameterised queries only; raw SQL reviewed and linted | SQLAlchemy Core/ORM parameterises by default; any raw SQL (payroll aggregation, Document 08 §1) is written with bound parameters and reviewed; `ruff`'s `S608` rule (Bandit-derived) flags string-built SQL |
| File upload | Type allow-list, magic-byte verification, size caps, ClamAV scan, served from a separate origin via presigned URLs | Unchanged; `python-magic` for magic-byte checks, ClamAV invoked from a Celery task (`reports_exports` or a dedicated `security` queue) rather than inline |
| CSRF | SameSite=Strict cookies + token for state-changing form posts | Unchanged |
| Rate limiting | Per Document 09 §1.9 | Redis-backed sliding window (Document 09 §1.9) |
| Dependency scanning | Automated on every build; critical CVEs block the release | `pip-audit` / `Safety` + Dependabot for Python dependencies (was: Dependabot/Snyk for npm) |
| Secret scanning | Pre-commit hooks + CI; a leaked secret triggers immediate rotation | `detect-secrets` or `gitleaks` in `pre-commit` (Document 05 §3) and CI |
| SAST / DAST | SAST on every PR; DAST weekly against staging | Semgrep (language-agnostic, works the same for Python); OWASP ZAP unchanged for DAST |
| Container security | Minimal base images, non-root user, image scanning, no secrets in layers | `python:3.12-slim` multi-stage build, non-root `USER`, image scanning in CI (Document 13 §2) |

---

## 3. Infrastructure Security — Unchanged

- Private subnets for database and application; no public database endpoint
- Bastion-less access (SSM Session Manager); no long-lived SSH keys
- WAF with managed rule sets plus custom rules for the auth and ingestion endpoints
- DDoS protection (CloudFront + Shield)
- Least-privilege IAM roles; no wildcard policies; access reviewed quarterly
- All infrastructure changes via Terraform in version control; no console changes in production
- Centralised logging with tamper-evident storage; log retention 1 year hot, 7 years archived

The application database role has no `UPDATE`/`DELETE` grant on `audit_log` or
`sensitive_access_log` (Document 07 §9) — a defence-in-depth control specific to this rewrite's
audit implementation, stated here because it is a genuine infrastructure/database-permission
control, not just an application-layer one.

---

## 4. Operational Security

| Control | Requirement |
|---|---|
| Production access | Break-glass only: time-boxed, approved, fully logged, reviewed post-hoc |
| Direct DB write access | **Prohibited** in production. Data fixes go through reviewed, audited scripts |
| Impersonation | Per Document 10 §7: reason, time limit, banner, audit, forbidden actions |
| Solo-developer note | With one developer, "break-glass" access and "the developer's normal access" are the same person — the control that still matters is that *production write access is not the default working mode even for the developer*: routine work happens through the CI/CD pipeline and reviewed scripts, not ad hoc production shell/DB access, and every exception is logged the same way it would be for a larger team (Document 26 §Bus Factor Risk explains why this discipline matters more, not less, without a second person to notice an unlogged shortcut) |
| Background checks | For any staff (contractor or hire) with production data access, if/when the team grows (Document 25) |
| Security training | Annual review of this document and the OWASP Top 10 against the current codebase — a solo-developer equivalent of "mandatory annual training" |
| Vendor assessment | Every sub-processor (LLM providers, SMS/WhatsApp providers, S3, etc.) assessed and listed publicly |

---

## 5. Incident Response

1. **Detect** — alerting on anomalous access, failed-auth spikes, data-export volume, error rates (Document 16 §6)
2. **Triage** — severity classification (S1 data breach → S4 cosmetic) with defined response times (Document 16 §6)
3. **Contain** — documented runbooks: revoke tokens, disable accounts, isolate services (Document 16 §9)
4. **Notify** — DPDP Act requires notification to the Data Protection Board and affected data
   principals; customer contractual notification typically 24–72 h. Templates prepared in advance
   (Document 23 §4).
5. **Remediate & review** — blameless post-mortem within 5 working days, published to affected customers

**Breach notification readiness is a launch requirement, not a post-launch task.** Have the
template, the contact list and the decision tree ready before the first customer's data is loaded.

**Solo-developer note:** an incident response plan written for a team ("page the on-call engineer",
"escalate to the tech lead") does not survive contact with a team of one. The runbooks in
Document 16 §9 are written assuming the developer is both detector and responder, with explicit
guidance on when to pause active feature work entirely to handle an S1 — a decision a team can make
implicitly (someone else keeps working) but a solo developer must make explicitly and in advance,
not while the incident is happening.

---

## 6. Security Testing — Cross-Reference

The four blocking security test suites (cross-tenant isolation, permission matrix, data scope, field
masking) that must pass on every CI build are specified in full in Document 15 §6 — this document
states the requirement; Document 15 owns the test implementation and coverage detail, consistent
with the split between "what must be true" (this document, Document 02's business rules) and "how we
verify it's true" (Document 15).
