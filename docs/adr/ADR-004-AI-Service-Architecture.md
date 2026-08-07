# ADR-004: AI Service Architecture

**Status:** Accepted  
**Date:** 2026-08-03  
**Related:** [0009-ai-non-blocking.md](0009-ai-non-blocking.md), `files/12_AI_Architecture.md`

## Context

AI features (resume parsing, matching, assistant, anomaly detection) were originally sketched as a separate Python/FastAPI service called from NestJS. Backend is now unified Python.

## Decision

**In-process AI modules** under `src/hrms/modules/ai/`:

| Capability | Approach |
|------------|----------|
| LLM (parse, assistant) | Hosted APIs — OpenAI, Claude, Gemini |
| Embeddings | Sentence Transformers + pgvector |
| Classical ML | scikit-learn, XGBoost in Celery workers |
| OCR / resume | Python OCR libraries in workers |
| Long runs | Celery tasks — API returns 202 + job_id (non-blocking) |

Share SQLAlchemy session, tenancy, and audit with core HR modules.

## Consequences

- **Positive:** No cross-language debugging; one deployment artifact.
- **Positive:** AI can read HR data through proper service boundaries.
- **Negative:** Worker CPU/memory must account for ML workloads.
- **Negative:** Future split to dedicated AI service requires explicit migration (documented exit path).

## Alternatives rejected

- Separate AI microservice for Phase 1
- Client-side inference
- Training custom LLMs in Phase 1
