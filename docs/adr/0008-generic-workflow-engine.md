# ADR-0008: Workflow Engine as a Generic Shared Service, Not Per-Module Approvals

**Status:** Accepted

## Context

At least eight distinct flows need multi-step approval: leave application, attendance
regularisation, manpower requisition, offer approval, resignation/exit, salary revision, expense
claim, profile change request (Doc 07 §3). If each module implements its own approval logic, the
platform ends up with eight subtly different state machines, eight different escalation
mechanisms, and eight places to fix the same class of bug (e.g. a stuck approval never
timing out). Configuration over code (Doc 03 principle 3) applies directly here: approval chains
are tenant data, and a `workflow_definition` model that only leave understands is not
configuration, it's a hidden code fork.

## Decision

Build **one generic workflow/approval engine** (Doc 07): `workflow_definition` →
`workflow_version` → `workflow_node` → `approval_request` → `approval_step` → `approval_action`,
with configurable node types, approver-resolution rules, a condition expression language, and
shared SLA/reminder/escalation logic. Every approval-driven flow in the product — present and
future — is an *instance* of this engine, configured differently per tenant and per flow, not a
bespoke implementation.

## Consequences

- **Positive:** SLA handling, escalation, delegation, and the approval inbox UI are built once and
  work identically everywhere, including for modules that don't exist yet (Phase 2 expense claims
  reuse the same engine per Doc 07 §3.7 — no new approval logic required).
- **Positive:** a tenant can reconfigure their leave approval chain without a code change or a
  deploy — directly serving the "configuration over code" principle and the workflow-builder UI
  (Doc 12 S5).
- **Negative:** the engine itself is nontrivial (Doc 12 estimates 79 person-days) and is a Sprint 5
  dependency that several later modules (attendance regularisation, recruitment offers, exit) sit
  behind — a bug in the shared engine has a wide blast radius across modules.
- **Negative:** debugging "why didn't my leave get approved" now involves understanding a generic
  engine's state rather than a leave-specific if/else chain — mitigated by the approval inbox and
  audit trail being first-class engine features, not per-module afterthoughts.

## Alternatives Considered

- **Per-module approval logic (e.g. `leave_approval`, `exit_approval` as separate implementations).**
  Rejected: guarantees eight inconsistent implementations of the same underlying problem, and every
  new approval-driven feature (a near-certainty in an HRMS roadmap) requires its own new approval
  subsystem instead of a new configuration.
- **A third-party workflow/BPM engine.** Rejected: adds an external dependency and integration
  surface for a domain (HR approvals) whose actual complexity — sequential/parallel approvers,
  SLA escalation, delegation — is well within what an in-house engine handles, without the
  operational and licensing overhead of a general-purpose BPM product.
