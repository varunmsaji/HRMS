# Document 12 — AI Architecture

**Version:** 2.0 — new document, split out from Document 08 v1.0 ("AI & Automation Specification")
§3 ("AI Service Architecture"). The feature-by-feature specification (governing principles,
resume parsing, matching, chatbot, anomaly detection, attrition, evaluation methodology, regulatory
compliance) is unchanged and lives in **Document 21**. This document is the architecture — how the
AI/ML surface is built, deployed, and integrated with the rest of the system — updated for the fact
that AI was **already** Python/FastAPI before this migration, and is now simply the same language
and process family as everything else, which changes the architecture more than it changes any
individual feature's design.

---

## 1. What Actually Changed

Before this migration, the AI service was a genuinely separate deployable: a different language
(Python) from the NestJS core, talking to it over HTTP or a queue, with its own database access (if
any) mediated through an API rather than shared models. After this migration, the AI functionality
is, by default, **an internal module (`modules/ai/`) inside the Core API and Worker processes**
(Document 03 §1.1) — it can:

- Share the **same SQLAlchemy models** as the rest of the system (e.g. read `candidate` and
  `job_opening` directly via `RecruitmentRepository`, rather than receiving a serialised payload over
  an HTTP call).
- Share the **same auth/tenancy context** (Document 07 §5) — an AI-assisted query executes with the
  requesting user's actual permissions and data scope, which directly strengthens the governing
  principle in Document 21 §1 P5 ("the assistant executes queries as the asking employee, through
  the same permission layer") — this is now enforced by the same `Depends(require_permission(...))`
  machinery every other endpoint uses, not a separately-implemented equivalent.
- Share the **same Celery infrastructure** (Document 11) for batch work — resume parsing, anomaly
  detection batches, and attrition scoring runs are Celery tasks on the dedicated `ai` queue, not a
  separate job system.

**What is preserved from the original design, deliberately:** the AI surface keeps an **explicit
extraction seam** — its own router prefix (`/ai/*` internally, mapped to the feature-specific paths
in Document 09 §3.6/§3.8, e.g. `/candidates/parse-resume`), its own `service.py` public interface,
and no other module importing its internals (Document 06 §3.1's boundary rule applies to `ai/` like
any other module). If GPU workloads, LLM-call latency isolation, or independent scaling needs ever
justify it, `modules/ai/` can be extracted into a fifth deployable (its own `entrypoints/ai.py`
ASGI app) with the same low-friction move used for any other module extraction candidate
(Document 03 §1.1) — the seam exists from day one even though the extraction may never be needed.

---

## 2. Architecture

```
Core API / Worker process
  └── modules/ai/
        ├── router.py          # /candidates/parse-resume, /applications/{id}/match-score, etc.
        ├── service.py           # AiService — the public interface (candidate matching, resume
        │                          parsing, assistant query handling, anomaly/attrition scoring)
        ├── llm_gateway.py         # Thin, provider-agnostic wrapper over OpenAI/Claude/Gemini SDKs
        ├── models_local/           # Local models: Sentence Transformers embeddings, XGBoost
        │                            scorers, classifiers — loaded once at process startup
        ├── model_registry.py        # Tracks model name, version, deployment date, eval scores
        ├── prompts/                  # Versioned prompt templates, reviewed like code (Document 05 §6)
        └── tasks.py                    # Celery tasks: batch resume parsing, anomaly detection
                                          # batches, attrition scoring runs — queue="ai" (Document 11 §1)
                                    │
                    ┌───────────────┴────────────────┐
                    ▼                                ▼
              LLM Provider APIs                 Local models
              OpenAI / Claude / Gemini           (Sentence Transformers, scikit-learn, XGBoost, OCR)
              (zero-retention tier)
                    │
             pgvector (in the primary PostgreSQL 16 instance, Document 04 §1) for RAG over
             tenant policy documents and for embedding-similarity matching (Document 21 §2.2)
```

**Synchronous vs. asynchronous split, unchanged from v1.0:** synchronous AI endpoints (e.g. a quick
assistant query) have a hard 10-second timeout; anything longer goes through the Celery `ai` queue
and the long-running-operation pattern (Document 09 §5). All calls carry `company_id` and are
quota-metered per tenant plan (§4).

---

## 3. Why `pgvector` in the Primary Database, Not a Separate Vector DB

A dedicated vector database (Pinecone, Weaviate, Qdrant) was considered and rejected for Phase 1:
`pgvector` runs inside the same PostgreSQL 16 instance already required for everything else
(Document 04 §1), which means one fewer stateful service for a solo-operated system to run, patch,
back up, and reason about — the same "reduced complexity" principle that drove the backend language
decision (Document 01 §2) applies here. Embeddings for RAG (tenant policy documents, Document 21
§2.3) and for candidate-JD domain-relevance scoring (Document 21 §2.2) are stored in the same
transactional database as the records they relate to, queried with the same SQLAlchemy session, and
backed up by the same RDS backup policy (Document 13 §5) — no separate backup/DR story for vector
data. If embedding volume or query latency ever genuinely outgrows `pgvector`, that's a well-scoped,
evidence-driven extraction later, not a default assumption now.

---

## 4. Model Registry & Prompt Versioning — Unchanged in Design

A model registry tracks model name, version, deployment date and evaluation scores; every inference
logs the version used, so a regression can be traced to a deployment (Document 21 §5). Prompt
templates are versioned in the repository (`modules/ai/prompts/`) and reviewed like code — a prompt
change is a behaviour change and goes through the same PR checklist as any other change
(Document 05 §7), with the evaluation harness (Document 21 §5) re-run before a prompt change ships.

---

## 5. Cost Controls — Implementation

The cost model itself (per-plan quotas, caching, model tiering, degradation) is unchanged and fully
specified in Document 21 §4. The Python-specific implementation:

- **Quota enforcement** is a `Depends` on AI endpoints, reading a per-tenant counter in Redis
  (`ai_quota:{company_id}:{feature}:{period}`), incremented atomically on each call — the same
  Redis-backed counting pattern used for rate limiting (Document 09 §1.9), reused rather than
  reinvented.
- **Caching** (resume hash, JD hash, embedding cache, policy-answer cache) uses Redis for
  short-lived caches and a `content_hash` column on the relevant table (e.g. `candidate.resume_text`
  hash) for durable dedup, so a re-upload of an identical resume doesn't re-trigger a paid LLM call.
- **Batching** (bulk resume parsing, anomaly detection) runs as Celery `group` tasks on the `ai`
  queue, schedulable off-peak via Celery Beat (Document 11 §4) exactly like any other batch job.
- **Per-tenant, per-feature cost dashboard**: cost-per-call is logged alongside every AI invocation
  (model, token counts, provider cost estimate) into a dedicated `ai_usage_log` table, aggregated
  daily into the cost dashboard (Document 13 §6).

---

## 6. Sharing Code Between AI and the Rest of the Backend — What's Actually Shared, and What Isn't

This is the concrete payoff of the single-language decision (Document 01 §2), stated precisely so it
doesn't get oversold:

**Shared:**
- SQLAlchemy models and repositories for reading domain data the AI features need (candidate, job
  opening, employee, attendance, leave, payslip history for attrition features).
- The auth/tenancy/permission dependency chain (Document 07 §2) — an AI endpoint is just another
  FastAPI router with the same `Depends(require_permission(...))` pattern.
- The Celery infrastructure, task design rules, and monitoring (Document 11).
- The Pydantic validation/serialisation patterns, error handling hierarchy (Document 07 §8), and
  testing conventions (Document 15).

**Not shared, and shouldn't be:** the LLM gateway, prompt templates, local model loading, and
embedding logic are AI-domain-specific and stay entirely inside `modules/ai/` — nothing about the
language migration makes it a good idea to, say, let the `payroll` module import an LLM client
directly. The module boundary rules (Document 06 §3.1, Document 07 §3) apply to `ai/` exactly as to
every other module: other modules interact with AI functionality only through `ai.service`'s public
interface (e.g. `payroll` never calls `ai` — there's no AI-in-payroll feature currently designed —
while `recruitment` calls `ai.service.match_candidate(...)` for scoring, and `helpdesk`/`assistant`
flows call `ai.service.answer_query(...)`).

---

## 7. Non-Blocking Guarantee — Implementation Note

Document 21 §1 P2 ("every AI feature has a manual fallback... no AI is on a critical path") is
enforced architecturally, not just as a design principle, by the deployment isolation in §1: even
though `modules/ai/` runs inside the same process as the rest of the Core API by default, its
Celery tasks run on a **dedicated `ai` queue** with its own worker pool (Document 11 §1) — a stalled
LLM provider or a backlog of resume-parsing jobs cannot starve the `payroll` or `attendance` queues,
because they are different Celery queues consumed by different worker processes. If AI request
volume or LLM latency ever threatened the Core API's own request-handling capacity (a risk only if
AI were called synchronously from a hot path, which Document 09 §5's long-running-operation pattern
specifically avoids for anything AI-related beyond the 10-second synchronous ceiling), the
extraction seam in §1 is the escape hatch.
