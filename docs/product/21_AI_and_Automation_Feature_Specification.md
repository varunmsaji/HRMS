# Document 21 — AI & Automation Feature Specification

*(Renumbered and updated from Document 08 for the Python/FastAPI backend architecture — see Document 00 for the full document map.)*

---

## 1. Governing Principles

These constraints exist because HR is a domain where an AI mistake has legal and human
consequences, and because "AI-powered" claims are easy to make and hard to keep.

| # | Principle |
|---|---|
| P1 | **No AI output is ever an automatic decision about a person.** AI recommends; a human decides. This applies absolutely to hiring, performance, promotion, PIP and termination. |
| P2 | **Every AI feature has a manual fallback.** If the AI service is down, the ATS, payroll and attendance still work fully. No AI is on a critical path. |
| P3 | **Explainability is mandatory.** A score without reasons is unusable and legally indefensible. Every score ships with the factors that produced it. |
| P4 | **No protected attributes in features.** Gender, age, religion, caste, marital status, pregnancy, disability, region and name-derived proxies are excluded from all scoring models, and the exclusion is tested. |
| P5 | **Data minimisation.** Send the least data necessary to an external LLM. Redact PII before external calls. Salary data never leaves the platform to a third-party model. |
| P6 | **Tenant data isolation.** No tenant's data trains a model used by another tenant without explicit contractual consent. Default: no training on customer data at all. |
| P7 | **Confidence thresholds.** Below the threshold, the system says "not confident" rather than guessing. Silence beats a wrong answer. |
| P8 | **Auditability.** Every AI invocation logs the model, version, prompt/feature-vector reference, output, confidence and the human decision that followed. |

---

## 2. Feature-by-Feature Specification

### 2.1 Resume Parsing (Phase 1) — *the highest-value AI feature; build it first*

| Aspect | Detail |
|---|---|
| **Input** | PDF, DOCX, DOC, TXT, RTF, image (with OCR); up to 10 MB |
| **Output** | Structured JSON: name, emails, phones, location, total experience (months), current company, current designation, skills[], education[], experience[], certifications, notice period, expected CTC, LinkedIn/GitHub URLs |
| **Approach** | Hybrid: layout-aware text extraction (pdfplumber/Tika) → rule-based extraction for high-confidence fields (email, phone, dates) → LLM extraction for narrative fields (skills, responsibilities) with a strict JSON schema → validation and normalisation |
| **Normalisation** | Skills mapped to a canonical taxonomy (e.g. "ReactJS", "React.js", "React" → `REACT`); designations to a standard ladder; institutions to a master list |
| **Confidence** | Per field, 0–1. Fields below 0.7 are highlighted for human review in the UI |
| **Accuracy target** | ≥90% for email/phone/name; ≥85% for experience and education; ≥75% for skills, measured on a labelled test set of 500 real resumes across the 8 industries |
| **Fallback** | Manual entry form pre-filled with whatever was extracted; parsing never blocks candidate creation |
| **Cost control** | Cache by resume SHA-256; re-parse only on request. Batch processing off-peak for bulk uploads |
| **Privacy** | Redact nothing on input (the resume is the candidate's own submission), but do not send resumes to any provider that trains on inputs; use a zero-retention API tier |

**Failure modes to handle explicitly:** two-column layouts, tables, scanned images, non-English
resumes, resumes with photos, ATS-hostile design-heavy CVs, and multi-page PDFs where the header
repeats. Test set must include all of these.

### 2.2 Candidate–Job Matching (Phase 1)

| Aspect | Detail |
|---|---|
| **Input** | Parsed candidate profile + job opening requirements |
| **Output** | Match score 0–100 + factor breakdown + a short natural-language rationale |
| **Scoring factors** | Must-have skills matched (weight 35), good-to-have skills (10), experience range fit (20), education fit (10), domain/industry relevance (10), location/relocation fit (5), notice period fit (5), CTC expectation vs band (5) — weights configurable per opening |
| **Approach** | Deterministic weighted scoring on structured fields + embedding similarity between the candidate's experience text and the JD for the "domain relevance" factor. **Not** a black-box end-to-end model — the client must be able to explain a rejection |
| **Explainability** | Always returns e.g. `{"matched": ["Java","Spring","5y exp"], "missing": ["Kubernetes"], "concerns": ["90-day notice vs 30 required"]}` |
| **Bias controls** | Name, gender, age, photo, marital status, address (beyond city for location fit) and college tier are **not** inputs. Regular bias audits comparing score distributions across inferred demographic groups on a held-out set |
| **Human control** | The score sorts a list. It never auto-rejects. Recruiters can override and their overrides are tracked as feedback |
| **Guardrail** | If a recruiter rejects >80% of high-scoring candidates for an opening, flag the model as miscalibrated for that role and prompt to re-weight |

### 2.3 HR Assistant Chatbot (Phase 1 basic, Phase 2 full)

| Aspect | Detail |
|---|---|
| **Purpose** | Answer employee questions: "How much leave do I have?", "When is my payslip out?", "What's the maternity policy?", "Who is my HR contact?" |
| **Architecture** | Intent classification → two paths: (a) **structured queries** answered by calling internal APIs with the employee's own permissions; (b) **policy questions** answered by RAG over the tenant's policy documents |
| **Critical constraint** | The assistant executes queries **as the asking employee**, through the same permission layer. It can never surface another employee's data. This is enforced by passing the user's auth context to the tool layer, not by prompting. |
| **Grounding** | Policy answers cite the source document and section. If no relevant document is found, it says so and offers to raise a ticket — it does not improvise policy |
| **Prohibited topics** | The assistant does not give legal advice, tax advice, medical advice, or opinions on grievances/POSH matters. These route to a human immediately |
| **Escalation** | "I'm not sure" → offer to create a helpdesk ticket with the conversation attached |
| **Phase 1 scope** | Structured queries only (leave balance, payslip, holidays, my manager, my shift, apply-leave shortcut) — no free-form policy RAG until the document corpus and evaluation harness exist |
| **Measurement** | Deflection rate (queries resolved without a ticket), satisfaction rating, escalation rate, and a monthly manual review of 100 sampled conversations |

### 2.4 Interview Assistant (Phase 2)

- Generates role-specific interview question sets from the JD and the candidate's profile
- Suggests probing follow-ups based on gaps between the JD and the resume
- Optional: transcribes and summarises interview recordings **with explicit consent from all
  participants**, producing a structured summary against the scorecard competencies
- **Never** produces a hire/no-hire recommendation. The panel decides. The tool organises evidence.
- Recording consent, retention period and deletion are configurable and default to conservative

### 2.5 Payroll Validation AI (Phase 2)

This is a **safety net, not a calculator**. The payroll engine is deterministic; this feature
catches human input errors before money moves.

| Check | Method |
|---|---|
| Net-pay outlier vs employee history | Statistical (z-score vs the employee's own last 6 months) |
| Component outlier vs peer group | Compare against the same grade/designation cohort |
| Missing employee in the run | Set difference against active headcount |
| Sudden LOP spike | Threshold + comparison to attendance data |
| Statutory anomaly | Rule-based: PF/ESI applicability changed without a documented reason |
| Duplicate bank account across employees | Exact match — a classic fraud indicator |
| Round-number salary inputs (₹50,000 exactly, repeatedly) | Heuristic flag for manual input errors |
| Reactivated exited employee receiving salary | Rule |

Output: a ranked exception list attached to the pay run, each with an explanation and a link to the
record. It integrates with the mandatory variance gate (FR-PAY-014). **No AI adjusts a number.**

### 2.6 Attendance Anomaly Detection (Phase 2)

| Anomaly | Signal |
|---|---|
| Buddy punching | Same device/IP punching for multiple employees; punch pairs consistently within seconds |
| Impossible travel | Two geo-punches whose distance/time implies unrealistic speed |
| Location spoofing | Mock-location flag, GPS accuracy anomalies, identical coordinates to 6 decimals repeatedly |
| Systematic late arrival | Trend detection vs the individual and team baseline |
| Punch-in-only pattern | Repeated missing check-outs |
| Overtime abuse | OT concentrated on specific days/employees beyond the department norm |
| Ghost employee | Perfect attendance with no other system activity, no leave ever, no device variation |

**Handling:** anomalies produce a *review queue for HR*, never an automatic deduction or
disciplinary action. Employees have the right to see and contest a flag raised against them —
build the contest flow, because this is where trust is won or lost.

### 2.7 Attrition Prediction (Phase 2/3)

| Aspect | Detail |
|---|---|
| **Output** | Risk band (Low / Medium / High) per employee + top contributing factors |
| **Features** | Tenure, time since last promotion, time since last increment, increment % vs peer median, compa-ratio, manager change count, team attrition rate, leave pattern change, attendance pattern change, engagement survey score, performance rating trend, span of control, commute distance band, internal application activity |
| **Excluded features** | Age, gender, marital status, pregnancy status, religion, caste, health data, salary in absolute terms (use compa-ratio instead) |
| **Model** | Gradient-boosted trees (XGBoost) with SHAP values for per-employee explanation. Trained per tenant once ≥ 200 exit events exist; before that, show a rules-based risk indicator instead of a fake model |
| **Access control** | Visible only to HR Manager and above, **never to the reporting manager by default**, and never to the employee. This is deliberately restrictive — an employee labelled "high flight risk" in a manager's view will be treated differently, which is both unfair and self-fulfilling |
| **Ethical guardrail** | The output must never be used in compensation, promotion or termination decisions. Displayed with that statement on-screen. Usage is audited |
| **Value framing** | The product's job is to prompt a retention *conversation*, not to rank people for pre-emptive action |

### 2.8 Performance Insights (Phase 2)

- Summarises a year of check-in notes, feedback and goal progress into a draft review narrative
  that the **manager must edit and own** before submission
- Detects rating bias patterns per manager (leniency/severity/central-tendency) for calibration
- Flags goals with no update in 60 days
- Suggests development areas by comparing the competency profile to the role's requirement
- **Never** generates a rating. The manager rates.

### 2.9 Smart Reports / Natural Language Query (Phase 3)

- "Show me attrition in the Kochi branch for the last 6 months by department"
- Architecture: NL → structured query DSL (not raw SQL) → validated against the report schema →
  executed through the standard reporting layer with the user's permissions and data scope
- **Never** generate raw SQL from user text and execute it. The DSL boundary is the security control
- Ambiguous queries ask a clarifying question rather than guessing
- Results always show the interpreted query so the user can verify the question was understood

### 2.10 Workforce Planning (Phase 3)

- Headcount forecasting from historical growth, attrition rates and the hiring pipeline
- Scenario simulation: cost impact of an X% increment, a hiring freeze, or a location shift
- Skill-gap projection against planned initiatives
- Presented as *scenarios with assumptions stated*, never as a single confident number

---

## 3. AI Service Architecture (Summary)

The AI service is a standalone FastAPI application, exposing endpoints such as `/parse/resume`,
`/match/candidate`, `/assist/query`, `/detect/anomaly`, `/predict/attrition` and `/summarise/*`,
called by the core API over HTTP and/or via the shared Celery/Redis job queue for anything that
exceeds a synchronous timeout. It sits in front of external LLM provider APIs (zero-retention tier)
and local models (embeddings, classifiers, XGBoost scorers), with a pgvector store for RAG over
tenant policy documents.

With the core API now also on Python/FastAPI, the AI service is no longer an outlier next to a
Node.js core — it is a peer service in the same language, and can share the core's SQLAlchemy
models, database session handling and common libraries directly where useful, rather than
duplicating them across a language boundary. It still deploys and scales independently, since its
workload profile (LLM latency, batch scoring, GPU/CPU-bound inference) differs materially from the
core API's request/response profile.

Full architectural detail — the request flow, the model registry, quota metering, prompt
versioning and review process, timeout and job-queue boundaries, and deployment topology — lives in
**Document 12 — AI Architecture** and is not repeated here.

---

## 4. Cost Model & Controls

AI cost is the main threat to PEPM unit economics. Controls:

| Control | Implementation |
|---|---|
| Per-plan quotas | Resume parses/month, assistant messages/month, summaries/month |
| Caching | Resume hash, JD hash, embedding cache, policy-answer cache |
| Model tiering | Small/cheap model for classification and extraction; large model only for generation and reasoning |
| Batching | Bulk resume parsing and anomaly detection run off-peak in batches |
| Token limits | Hard caps on input and output tokens per call; truncate with a strategy, never silently |
| Degradation | On quota exhaustion, features degrade to rule-based fallbacks with a clear message, never a broken screen |
| Monitoring | Per-tenant per-feature cost dashboard, daily; alert on anomalous spend |

**Budget guidance:** target AI cost ≤ 8% of PEPM revenue. Model the per-tenant monthly AI cost
before enabling any feature by default on a plan.

---

## 5. Evaluation & Quality Assurance for AI Features

Every AI feature ships with an evaluation harness before it ships to customers.

| Feature | Eval method | Gate to ship |
|---|---|---|
| Resume parsing | Labelled set of 500 resumes; per-field precision/recall | ≥ targets in §2.1 |
| Candidate matching | Recruiter agreement study: do recruiters rank the same top-10? | ≥70% overlap on top-10 |
| HR assistant | 300 curated Q&A pairs; correctness + refusal-appropriateness | ≥90% correct, 0% harmful |
| Anomaly detection | Precision on a labelled incident set | ≥60% precision (false positives waste HR time) |
| Attrition | AUC on a held-out period; calibration curve | AUC ≥0.70, calibrated |
| Any LLM feature | Red-team suite: prompt injection, data exfiltration attempts, PII leakage, cross-tenant probing | 0 successful attacks |

**Prompt injection is a live risk here**: resumes, expense receipts, helpdesk tickets and policy
documents are all attacker-controllable text that reaches an LLM. Treat all such content as
untrusted data, never as instructions; use structured extraction with schema validation; never let
model output directly trigger a privileged action without human confirmation.

---

## 6. Regulatory & Ethical Compliance

| Requirement | Implementation |
|---|---|
| DPDP Act (India) — notice & purpose | AI processing disclosed in the privacy notice; purpose stated per feature |
| Employee right to explanation | Every AI-influenced decision surface shows the factors; employees may request the rationale |
| No automated decision-making on individuals | Enforced by design (P1); documented for enterprise procurement questionnaires |
| Candidate consent | Explicit consent for AI screening captured at application; opt-out routes to full manual review |
| Bias auditing | Quarterly audit of score distributions across inferred groups; results documented and remediated |
| Model documentation | A model card per feature: purpose, data, limitations, evaluation, known failure modes |
| Human oversight | Named role accountable for each AI feature's outputs at the tenant level |
| Right to erasure | AI caches, embeddings and vector entries are included in deletion requests |

**Note on EU AI Act:** if the product is ever sold into the EU, HR-related AI (recruitment,
performance, promotion) is classified as **high-risk**, triggering substantial obligations
(risk management, data governance, logging, transparency, human oversight, conformity assessment).
The design principles above are deliberately aligned with those requirements so that EU entry is a
compliance exercise rather than a rebuild. Flag this to the client before any EU commitment.

---

## 7. Phased Delivery of AI

| Phase | Features | Rationale |
|---|---|---|
| **Phase 1** | Resume parsing, candidate matching, basic HR assistant (structured queries only) | Highest ROI, lowest risk, immediately demonstrable |
| **Phase 2** | Payroll validation, attendance anomaly, interview assistant, performance summarisation, full assistant with policy RAG | Requires real data volume and a stable base product |
| **Phase 3** | Attrition prediction, workforce planning, NL reporting | Requires ≥12 months of tenant history to be credible |

**Do not** promise Phase 2/3 AI features in Phase 1 sales material. An attrition model trained on
three months of data from one customer is not a product; it is a liability.
