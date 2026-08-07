# ADR-0009: AI Features Are Strictly Non-Blocking; Every AI Path Has a Manual Fallback

**Status:** Accepted

## Context

Phase 1 AI features (resume parsing, candidate matching, an HR assistant) use a hosted LLM API
plus classical ML for scoring (Doc 03 A8, Doc 08). Hosted LLM APIs have their own latency, rate
limits, outages and cost profiles that this platform does not control. HR operations — hiring,
onboarding, payroll — cannot be allowed to stall because a third-party AI provider is degraded or
over quota; "the AI is down" must never be an answer to "why can't I hire this candidate."

## Decision

Every AI-touched workflow has a manual path that fully replaces it. Resume parsing failing or
queuing means the recruiter enters candidate details by hand and the ATS remains completely
usable (Doc 03 §8). No AI call sits on the critical path of any core HR operation — AI output is
always advisory, prefetched, or asynchronous, never a blocking dependency of leave, attendance,
payroll, or any statutory process.

## Consequences

- **Positive:** an AI provider outage or quota exhaustion (Doc 14 §9, runbook 9) degrades a nice-
  to-have, not a core operation — it never appears as an S1 incident (Doc 14 §6.2's severity table
  has no AI-path entry among the S1 triggers).
- **Positive:** this also protects cost — noisy-neighbour controls (Doc 03 §3.3) and per-tenant AI
  spend limits can throttle or pause AI features for a tenant without breaking their ability to use
  the product.
- **Negative:** every AI feature requires building and maintaining the non-AI fallback path
  alongside it — effectively double implementation for anything AI touches (manual candidate entry
  form *and* resume parsing, manual leave-policy Q&A *and* the assistant).
- **Negative:** product experience is inconsistent when AI degrades gracefully to manual — this is
  accepted as the correct trade-off (reliability over polish) for a system where the "manual" path
  is what HR teams already do today without any AI at all.

## Alternatives Considered

- **Make AI parsing a required step in the recruitment pipeline.** Rejected: makes the entire ATS
  hostage to a third-party API's uptime, which directly contradicts Doc 03 §8's resilience
  principle ("no external dependency may block a core HR operation").
- **In-house model hosting instead of a hosted LLM API, to control uptime directly.** Rejected for
  Phase 1 (Doc 03 A8): no model training or self-hosted inference in Phase 1; revisit only if
  hosted-API cost or reliability becomes a proven, measured problem at scale.
