# Document 09 — Integration Specification

---

## 1. Integration Principles

| # | Principle |
|---|---|
| I1 | Every integration is **optional and degradable**. If it fails, the core HR operation still completes. |
| I2 | All integrations go through an **adapter interface** per category (attendance device, messaging, accounting, calendar, storage), so a provider swap is a configuration change plus one adapter class — not a refactor. |
| I3 | Credentials are stored encrypted per tenant in a secrets store, never in the database in plain text, never in code. |
| I4 | Every outbound call is logged (endpoint, status, latency, correlation id) with request/response bodies **redacted of PII**. |
| I5 | Retries use exponential backoff with jitter and a circuit breaker; a persistently failing integration is marked degraded and the tenant admin is alerted. |
| I6 | Inbound webhooks verify signatures and are idempotent. |
| I7 | Every integration has a **connection test** button in the UI that performs a real round-trip and reports a specific, actionable error. |

---

## 2. Biometric & Access-Control Devices (Phase 1 — critical path)

### 2.1 Reality check
This is the integration most likely to consume more time than estimated. Devices in the Indian SME
market are heterogeneous, poorly documented, often behind NAT on customer LANs, and frequently
running old firmware. Budget **3× your first estimate**, and get physical access to at least two
real devices before Sprint 1.

### 2.2 Supported patterns

| Pattern | How | Devices |
|---|---|---|
| **Push (ADMS/HTTP)** | Device posts punches to our URL at intervals | ZKTeco, eSSL (most common in India) — **preferred** |
| **Pull (SDK/TCP)** | Our poller connects to the device on the LAN | Requires an on-prem agent when the device has no public IP |
| **Cloud API** | Vendor's cloud holds the data; we call their API | Matrix, Realtime, some ESSL cloud offerings |
| **File-based** | Device/software exports CSV/Excel; we import | Fallback for legacy or exotic devices |
| **On-prem agent** | A small service we ship, installed at the customer site, bridges LAN devices to our cloud | Necessary for pull-mode devices behind NAT |

### 2.3 The on-prem agent (build this — it unblocks the long tail)
A lightweight service (Go or Node, single binary, Windows service + Linux daemon) that:
- Discovers and connects to configured devices on the LAN
- Polls punches on a schedule; buffers locally (SQLite) when the internet is down
- Pushes to `/ingest/v1/punches` with device HMAC auth and idempotency keys
- Reports device health, firmware and enrolled-user counts
- Receives commands: sync employees, set time, delete user, restart
- Auto-updates itself; logs locally for support

### 2.4 Data contract
```json
POST /ingest/v1/punches
{ "device_serial": "ZK5820394",
  "punches": [
    { "employee_code": "ACM0042", "biometric_id": "142",
      "timestamp": "2026-08-03T09:12:11+05:30",
      "direction": "IN", "verify_mode": "FINGERPRINT",
      "work_code": null, "device_punch_id": "88213" } ] }
```
Idempotency key = `sha256(device_serial + biometric_id + timestamp)`.

### 2.5 Employee ↔ device mapping
- `employee_device_mapping (employee_id, device_id, biometric_id, enrolled_at, status)`
- Enrolment happens on the device; we sync the mapping. Unmapped biometric ids produce an
  "unknown enrolment" exception queue for HR to resolve — **never silently discard punches**.

### 2.6 Failure handling
| Failure | Behaviour |
|---|---|
| Device offline > 2 h | Alert HR admin + IT contact; show on the attendance dashboard |
| Clock drift > 5 min | Flag punches; auto-issue a time-sync command; alert |
| Duplicate punch | Idempotency key rejects silently, counted in metrics |
| Unknown employee code | Exception queue, retained 90 days for reconciliation |
| Agent version outdated | Warn; block if below the minimum supported version |

### 2.7 Face recognition
- Prefer **device-side matching** (privacy: templates stay on the device; performance: no image upload)
- If server-side: store **templates, not images**, encrypted; liveness detection required;
  explicit employee consent captured and revocable; deletion on exit
- Biometric data is sensitive personal data under DPDP — document the lawful basis, retention and
  deletion, and be prepared to justify it. Offer a non-biometric alternative for employees who refuse.

---

## 3. Messaging Channels

### 3.1 Email
- Provider: AWS SES (primary) + SendGrid (failover)
- Per-tenant sending domain with SPF, DKIM and DMARC for white-label
- Bounce and complaint webhooks → suppression list → notify HR of invalid addresses
- Transactional only; bulk announcements are rate-shaped to protect domain reputation
- Attachments (payslips) are password-protected PDFs; large attachments become secure links instead

### 3.2 SMS
- Provider: MSG91 / Twilio / Kaleyra (India: DLT registration is mandatory)
- **DLT compliance:** sender IDs, entity registration and template registration with the Indian
  telecom DLT platform must be completed by the client before go-live — this takes 1–3 weeks and is
  a common launch blocker. Flag it in the project plan as a client dependency with a hard lead time.
- Use cases: OTP, interview reminders, critical alerts to employees without the app

### 3.3 WhatsApp Business API
- Provider: Meta BSP (Gupshup / Interakt / Twilio)
- Template messages require Meta pre-approval (24–48 h per template); build the template library early
- Opt-in consent per employee, recorded with timestamp and source; unsubscribe honoured immediately
- 24-hour session window rules apply for free-form replies
- **Highest-value channel in the Indian SME market** — payslip notifications, leave approvals and
  attendance reminders on WhatsApp drive adoption far better than email
- Two-way: a simple WhatsApp bot for "leave balance", "apply leave", "payslip" (Phase 2)

### 3.4 Push
- FCM (Android + web) and APNs (iOS) via a single abstraction
- Token lifecycle management: register on login, refresh, invalidate on logout/uninstall
- Silent pushes for dashboard invalidation; visible pushes for user-facing events
- Deep links into the correct app screen (approval → the approval detail screen)

---

## 4. Calendar Integration

| Provider | Method |
|---|---|
| Google Calendar | OAuth 2.0, Calendar API, per-user consent |
| Microsoft 365 | Microsoft Graph, OAuth 2.0 |
| Generic | ICS file attachments (works everywhere, no auth) |

**Use cases:** interview scheduling with panel availability lookup (free/busy), meeting-link
generation (Meet/Teams), leave shown on the team calendar, holiday calendar subscription, review
meeting scheduling.

**Design note:** always attach an ICS file *in addition to* the API-created event. OAuth consent
lapses, tokens expire, and users change accounts — the ICS fallback means scheduling never silently
fails.

---

## 5. Accounting & ERP

### 5.1 Tally (Phase 2 — the SME default in India)
- Output: Tally XML journal voucher for the payroll JV
- Import method: Tally's HTTP XML gateway on the customer LAN (needs the on-prem agent), or a manual
  XML file import by the accountant
- Mapping UI: salary component → ledger name, cost centre → Tally cost centre
- Provide a reconciliation report: our totals vs what was posted

### 5.2 Zoho Books / QuickBooks / Xero (Phase 2/3)
- REST APIs with OAuth 2.0; create journal entries directly; store the external reference id
- Handle their rate limits and idempotency requirements

### 5.3 SAP / Oracle / Microsoft Dynamics (Phase 3, enterprise)
- Typically file-based (IDoc, flat file to SFTP) or middleware-mediated
- Scope per deal; do not attempt a generic connector

### 5.4 Generic outputs (Phase 1 — ship these first)
- Journal voucher CSV/Excel with configurable columns
- Bank payment files: NEFT/RTGS/IMPS formats for HDFC, ICICI, SBI, Axis, Kotak + generic CSV
- These cover 90% of customers without any API integration, and they work on day one

---

## 6. Job Boards (Phase 2)

| Board | Capability |
|---|---|
| LinkedIn | Job posting via Talent Solutions (requires a partner agreement — commercial lead time) |
| Naukri | Posting + resume database access (paid API, contract required) |
| Indeed | XML feed for organic posting (simplest — start here) |
| Company careers page | Native, always available (Phase 1) |

**Phase 1 approach:** a well-built careers page + a shareable link + email inbox parsing covers most
SME needs. Board integrations are commercially gated and should not sit on the MVP critical path.

---

## 7. Background Verification (Phase 2)

Vendors: AuthBridge, IDfy, SpringVerify (India).
Flow: initiate check → webhook status updates → store the report → gate onboarding on the outcome.
Data handling: candidate consent is mandatory and must be recorded; reports contain highly sensitive
data and are `RESTRICTED` classification with access logging.

---

## 8. Payment Gateway (for platform subscription billing)

Razorpay (India primary) / Stripe (international).
Flows: subscription creation, recurring mandate (eNACH/UPI Autopay), invoice, webhook for
payment success/failure, dunning, refunds.
**Not** used for salary disbursement — salaries go through the customer's own bank via advice files.
Do not build salary disbursement; it is a regulated activity and a different business.

---

## 9. Cloud Storage & Document Signing

| Need | Provider |
|---|---|
| Primary document storage | AWS S3 with SSE-KMS, versioning, lifecycle to Glacier |
| Customer's own storage (optional) | Google Drive / OneDrive / Dropbox connectors for document export |
| E-signature | DocuSign / Zoho Sign / Digio (India, Aadhaar eSign) for offers, appointment letters, policy acknowledgement |

**Aadhaar eSign note:** legally recognised in India and cheap, but requires an ESP relationship and
careful consent handling. Evaluate against DocuSign on cost per envelope at expected volume.

---

## 10. Identity Providers (Phase 2)

SAML 2.0 and OIDC for Google Workspace, Microsoft Entra ID, Okta.
Per-tenant configuration: entity id, ACS URL, certificate, attribute mapping, JIT provisioning
rules, default role assignment.
SCIM 2.0 for automated user provisioning/deprovisioning (enterprise requirement — Phase 3).

---

## 11. Integration Registry & Monitoring

Every tenant integration is a row in `integration_config`:
`id, company_id, integration_type, provider, config JSONB (non-secret), secret_ref, status
(ACTIVE/DEGRADED/DISABLED), last_success_at, last_error_at, last_error_message, health_score`

**Integration health dashboard** (per tenant, and aggregated for platform ops):
- Status per integration with last successful sync
- Error rate over 24 h / 7 d
- Volume processed
- A "Test connection" action
- Alerting: 3 consecutive failures → tenant admin email + ops alert

**Ops view:** an integration failing across many tenants simultaneously indicates a provider
outage, not a customer problem — the dashboard must make that distinction obvious, or support
will field 50 identical tickets.

---

## 12. Integration Effort Estimates

| Integration | Effort (dev-days) | Risk | Phase |
|---|---:|---|---|
| Biometric push (ZKTeco/eSSL) | 15 | **High** — hardware access, firmware variance | 1 |
| On-prem agent | 20 | High | 1 |
| GPS/mobile attendance | 8 | Medium | 1 |
| Email (SES) | 4 | Low | 1 |
| SMS (MSG91) | 5 | Medium — DLT registration lead time | 1 |
| Push (FCM/APNs) | 6 | Low | 1 |
| WhatsApp Business API | 12 | Medium — template approval lead time | 1/2 |
| Bank payment files (5 banks) | 10 | Medium — format variance | 1 |
| Statutory file formats (ECR/ESI/24Q) | 15 | **High** — format precision, rejection risk | 1 |
| Google/Outlook Calendar | 10 | Medium | 1/2 |
| Tally | 12 | Medium — on-prem, XML quirks | 2 |
| Zoho Books | 6 | Low | 2 |
| Face recognition | 15 | High — accuracy, privacy, consent | 2 |
| Job boards (per board) | 8–15 | Medium — commercial gating | 2 |
| Background verification | 8 | Low | 2 |
| E-signature | 8 | Low | 2 |
| SSO (SAML + OIDC) | 15 | Medium | 2 |
| Payment gateway | 10 | Low | 1 (for billing) |

**Total Phase 1 integration effort ≈ 110 dev-days.** This is roughly 20% of the Phase 1 build and is
consistently underestimated. Treat biometric and statutory file generation as the two highest-risk
items in the entire project after payroll computation itself.
