# ADR-001: FastAPI as Core Backend

**Status:** Accepted  
**Date:** 2026-08-03  
**Detailed ADR:** [0013-fastapi-python-backend.md](0013-fastapi-python-backend.md)

## Context

The platform originally targeted NestJS/Node.js. Delivery is a single Python-fluent developer building AI-heavy HR features. A two-language backend (Node + Python AI) added complexity without benefit.

## Decision

Use **Python 3.12+** and **FastAPI** as the sole backend for:

- REST API (`entrypoints/api.py`)
- Device ingestion (`entrypoints/ingestion.py`)
- Background workers (Celery)
- AI/ML modules (`modules/ai/`)

## Consequences

- **Positive:** One language, one test stack, shared SQLAlchemy models for AI and core HR.
- **Positive:** FastAPI `Depends()` maps cleanly to guards, tenancy, RBAC.
- **Negative:** Must enforce module structure via `import-linter` (NestJS no longer "forces" modules).
- **Negative:** Async SQLAlchemy session discipline required (no lazy-load surprises).

## Alternatives rejected

- NestJS (superseded)
- Django REST (async less foundational)
- Separate AI microservice for Phase 1 (unnecessary boundary)
