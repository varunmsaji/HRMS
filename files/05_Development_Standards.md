# Document 05 — Development Standards

**Version:** 2.0 — new document. Consolidates and expands the original Document 10 v1.0 §7
("Maintainability & Code Quality") into a standalone standard, since a solo-developer, AI-assisted
project needs its coding conventions to be explicit and mechanically enforced — there is no second
engineer's code review to catch drift by osmosis (Document 01 §2, Document 26 §Bus Factor Risk).

---

## 1. Why This Document Exists for a Team of One

A multi-engineer team enforces consistency partly through code review and partly through shared
tacit knowledge. Neither exists reliably here: code review is occasional at best (Document 25), and
an AI coding assistant generating the 40th endpoint has no memory of a convention that was only ever
discussed in a Slack message that doesn't exist. Every convention that matters is therefore written
down here and, wherever mechanically possible, **enforced by a CI gate**, not left as a guideline.
The rule of thumb: if a standard cannot be checked by a tool, ask whether it can be redesigned so
that it can be.

---

## 2. Language & Style

| Rule | Enforcement |
|---|---|
| Python 3.12+, type hints on every function signature (parameters and return type) | `mypy --strict` on `core/`, `shared/`, and every module; CI gate |
| Formatting and lint rules per `Ruff` default + project ruleset in `pyproject.toml` | `ruff check` + `ruff format --check`; CI gate; `pre-commit` runs both locally before a commit is even possible |
| `snake_case` for functions, variables, modules; `PascalCase` for classes; `SCREAMING_SNAKE_CASE` for constants and enum members | Ruff naming rules (`N` ruleset) |
| No bare `except:`; catch specific exceptions; re-raise with context (`raise X from e`) when wrapping | Ruff `BLE`/`TRY` rulesets |
| No mutable default arguments | Ruff `B006` |
| Docstrings only where the *why* is non-obvious (a hidden constraint, a workaround, a subtle invariant) — not on every function restating its signature in prose | Code review discipline; not mechanically enforced, but flagged in the PR checklist (§7) |
| Prefer composition and explicit dependency passing (constructor injection via FastAPI `Depends`) over inheritance hierarchies or global singletons | Architecture review; see Document 07 §2 |

---

## 3. Project & Dependency Management

- `uv` is the only dependency manager. `pyproject.toml` + `uv.lock` are committed; no `requirements.txt`, no unpinned installs.
- Dependencies are added with a one-line justification in the PR description — an unused or
  redundant dependency is exactly the kind of thing that accumulates unnoticed without a second
  reviewer, and it is a supply-chain risk surface (Document 14 §2).
- Dependency updates run through Dependabot (or Renovate) with automated PRs; security-relevant
  updates (flagged by `pip-audit`/`Safety` in CI) are not deferred past the current sprint.

---

## 4. Testing Standard (full strategy in Document 15)

| Rule | Target |
|---|---|
| Unit test coverage | ≥80% overall; **≥95% for payroll calculation, leave accrual, attendance resolution, and RBAC/tenancy code** (`core/rbac`, `core/tenancy`) — unchanged from the original NFR-M1, this bar does not move for a smaller team; if anything it matters more, because there is no second reviewer to catch a regression the tests miss |
| Every `service.py`, `router.py`, and `repository.py` has a corresponding test file | Enforced by a CI check (Document 06 §4), not just convention |
| A PR that touches payroll, RBAC, or tenancy code and does not add/modify a test in the same PR | Blocked — this is a hard CI gate, no override |
| Flaky tests | Quarantined within 24 hours, fixed within a week, or deleted. A test suite that gets ignored is worse than no suite (unchanged from the original QA doctrine, now Document 15 §9) |

---

## 5. Module Boundary Discipline

Full detail in Document 07 §3. The mechanical summary: `import-linter` contracts in
`.importlinter` define which packages may import which, and a violation fails CI exactly the way a
failing test does — there is no "we'll fix it next sprint" for a boundary violation, because
boundary erosion compounds silently and a solo project cannot afford to discover it at module #18.

---

## 6. Documentation Discipline

| Artefact | When it's required | Where |
|---|---|---|
| ADR | Every architecturally significant decision — a new dependency that shapes module structure, a change to the tenancy model, a new external integration pattern, anything a future reader would ask "why was it done this way?" about | `/docs/adr/`, one file per decision, using the format in `/docs/adr/README.md` |
| OpenAPI spec | Always current — it is generated automatically from FastAPI route definitions and Pydantic schemas, never hand-maintained | Served at `/v1/openapi.json`, CI-validated against a snapshot so an accidental breaking change is caught (Document 09 §8) |
| Module `README.md` (optional but recommended for the five most complex modules: payroll, attendance, workflow, ai, integration) | When a module's internal logic is non-obvious enough that Document 07's generic module shape doesn't explain *this module's* specific quirks | `modules/<name>/README.md` |
| This document set (`files/`) | Updated whenever a decision documented here changes | Change control process in Document 26 |

**The standard this project holds itself to:** a new contributor — a future second developer, a
contractor brought in for a security review, or the original developer returning after months away
— should be productive using the documentation set alone. This is tested the same way the original
Document 14 v1.0 proposed testing it for a new engineer joining a team: watch where the reader gets
stuck, and fix that specific gap, rather than assuming the documentation is complete because it is
long.

---

## 7. Pull Request / Change Checklist

Even solo, changes of any real size go through a PR (not a direct push to `main`) so that CI gates
run and there is a reviewable diff — this is cheap insurance and the closest available substitute
for a second reviewer:

- [ ] `ruff check` / `ruff format --check` / `mypy` clean
- [ ] `import-linter` clean (no module boundary violation)
- [ ] Tests added/updated for the change; coverage gate met
- [ ] If payroll, RBAC, or tenancy code changed: the relevant golden-dataset or security suite ran and passed (Document 15 §3, §6)
- [ ] If a new dependency was added: one-line justification in the PR description
- [ ] If an architecturally significant decision was made: an ADR was added
- [ ] If a new endpoint was added: it has an explicit permission dependency (Document 19) — an
      endpoint with no declared permission requirement **fails the build**, per Document 09 §6
- [ ] No secrets, credentials, or real customer data in the diff (pre-commit secret scan should
      already have caught this, but the checklist is the second layer)

---

## 8. AI-Assisted Development Guardrails

Specific to this project's delivery model (Document 01 §2, Document 25):

| Rule | Why |
|---|---|
| AI-generated code for payroll calculation, statutory compliance logic, or RBAC/tenancy enforcement is **never merged without the developer manually tracing through the logic against the golden dataset or a hand-worked example** | These are the modules where a plausible-looking but subtly wrong implementation causes legal and financial harm (Document 02 §7, Document 15 §3). "The tests pass" is necessary but not sufficient — the developer must understand *why* the logic is correct, not just that a test asserts it is. |
| AI-generated code follows the same module shape, naming conventions, and boundary rules as everything else (Document 06) — an assistant is briefed with this document set, not asked to invent its own structure | Consistency is what makes a 20-module, AI-assisted codebase navigable by one human. A structurally novel 21st module is a liability even if it works. |
| Every AI-assisted change still goes through the PR checklist above — AI assistance does not create an exception to any gate | The gates exist because there is no second reviewer; that reason does not go away because a machine wrote the diff. |
| Prompts, code-generation sessions, or design conversations that produced a non-obvious architectural decision get captured as an ADR, not left implicit in chat history | Chat history is not documentation and is not searchable by a future contributor. |

---

## 9. Naming & Terminology

Product/domain terminology (User vs Employee vs Candidate, etc.) is defined once in Document 02
§11 — do not redefine it here. Code-level naming conventions specific to the folder structure
(module names, class naming, permission codes, event naming) are defined in Document 06 §5 and
Document 07 — do not duplicate them here either. This document governs *how you write code*;
Document 06 governs *where it goes*; Document 02 governs *what the domain words mean*.
