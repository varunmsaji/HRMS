# DATA-01 — PII Data-Flow Inventory

| Field | Value |
|---|---|
| Status | Planning only — no code, schema, or data changed |
| Baseline commit | `c3b8cec9c1d24dbd4892f92a649b9c4c98e3533f` (branch `main`) |
| Source finding | `DATA-01`, `docs/audits/PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md` §2 |
| Method | Full-repository grep + read (models, schemas, services, repositories, routers, migrations, tests, frontend), no code executed except read-only `grep`/`git` |

This document answers one question precisely, for every sensitive field named in DATA-01: **where
does the value live today, and every place it currently moves through.** The implementation plan
(`DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md`) is built entirely on what this document
establishes — nothing here is inferred from the `_enc` naming convention; every claim below was
verified against actual source.

---

## 1. The four storage locations

Confirmed by grepping every migration, every model, and every JSONB-holding table in the
repository — **these four are the only places PAN/Aadhaar/bank-account values are ever
persisted**:

| # | Table.column | Type | Nullable | Index/constraint | Write path exists today? |
|---|---|---|---|---|---|
| 1 | `employee.pan_number_enc` | `TEXT` | yes | none | **No** — dormant |
| 2 | `employee.aadhaar_number_enc` | `TEXT` | yes | none | **No** — dormant |
| 3 | `employee_bank.account_number_enc` | `TEXT` | yes | none | **Yes** — live |
| 4 | `onboarding_case.bank_info` | `JSONB` (untyped dict, holds a copy of the same account number + IFSC etc. pre-activation) | not null, default `{}` | none | **Yes** — live, written by an unauthenticated caller |

Adjacent columns worth naming (not named in DATA-01, carry a lighter version of the same gap,
flagged here rather than silently folded in):

- `employee.uan_number` (`VARCHAR(20)`) — EPF Universal Account Number. No `_enc` suffix (no false
  promise), also dormant (no write path, see §3).
- `employee_bank.ifsc` (`VARCHAR(15)`) — a public bank-branch code, not itself an
  account-identifying secret. Travels alongside `account_number_enc` everywhere in this inventory
  but does not independently need encryption — noted for completeness only.
- `employee_statutory.pf_number` / `.esi_ip_number` (`VARCHAR`) — same "real government-adjacent
  identifier, no encryption" gap as PAN/Aadhaar, no `_enc` suffix and not named in the audit. Out
  of DATA-01's scope; recommend a follow-up finding rather than silently expanding this batch.
- `onboarding_case.statutory_info` (`JSONB`) — the pre-activation staging copy of the statutory
  fields above, same shape as `bank_info`. Same "out of DATA-01 scope, follow-up finding" note.

**Migration history**: `alembic/versions/20260813180000_employee_foundation.py` (adds
`pan_number_enc`/`aadhaar_number_enc`/`uan_number` to `employee`, additive `ADD COLUMN IF NOT
EXISTS`, confirmed zero rows existed at the time it was written);
`alembic/versions/20260815140000_employee_bank.py` (creates `employee_bank`, including
`account_number_enc`/`ifsc`, foundational `CREATE TABLE`); `alembic/versions/
20260905090000_onboarding_o1.py` (creates `onboarding_case` including `bank_info JSONB`). No
migration has ever touched these columns since. No direct SQL access outside these three
migrations and the ORM was found anywhere in `apps/api` or `scripts/sql/`.

---

## 2. `employee.pan_number_enc` / `employee.aadhaar_number_enc` — fully dormant

Verified across every layer:

1. **SQLAlchemy model** (`hrms/modules/employee/models.py:61-62`) — plain `String`/`TEXT`
   columns, no `TypeDecorator`, no encryption. Own docstring (line 26-28) states outright: "exist
   as columns... but have no write path in this slice."
2. **Pydantic request schemas** (`hrms/modules/employee/schemas.py:48-80`) — `EmployeeCreate` and
   `EmployeeUpdate` both explicitly omit these fields; the module's own file-header docstring
   (lines 8-11) names the omission and why (`EMPLOYEE.UPDATE_SENSITIVE` is out of the E-01 slice's
   scope).
3. **Pydantic response schema** (`schemas.py:93-114`, `EmployeeRead`) — does not include either
   field. `employee_to_read()` (line 123) does not read them off the ORM instance.
4. **Create path / Update path** — no code path in `EmployeeService` ever assigns either column
   (confirmed: zero occurrences of `pan_number_enc`/`aadhaar_number_enc` in `service.py` or
   `repository.py`).
5. **Read path (admin or self-service)** — none; not present in any response schema anywhere in
   the module.
6. **Import path** — `employee_import` module's `EmployeeImportService`/CSV parsing has zero
   references to either field (confirmed by grep across the whole module).
7. **Export path** — no export functionality of any kind exists in the API (see §7).
8. **Onboarding** (the one other place a new employee's data enters the system) — the public
   wizard's `PersonalInfoSection` (`onboarding/schemas.py:180-194`) is an explicit subset of
   `EmployeeCreate` and likewise excludes both fields. The only PAN/Aadhaar-adjacent thing the
   onboarding wizard collects is a scanned **document upload** under `document_type in {"PAN",
   "AADHAAR", ...}` (`onboarding/schemas.py:91`) — an image/PDF stored in S3/MinIO via
   `DocumentStorageService`, never the plaintext number itself. Document-upload security
   (buffering, content-type spoofing) is tracked separately as `SEC-03`/`SEC-04`, out of scope
   here.
9. **Background jobs** — none reference either field (confirmed across `employee_import/tasks.py`,
   the only Celery task touching Employee-adjacent data).
10. **Audit logging** — `employee_to_audit_dict()` (`schemas.py:149`) dumps `EmployeeRead`, which
    (per #3) never carries either field — so no audit-log exposure exists either.
11. **Test fixtures** — every unit test fixture across `tests/unit/modules/employee/*.py` sets
    both to `None` explicitly (e.g. `test_employee_service.py:35-36`), and
    `tests/integration/modules/employee/test_employee.py:92-95` has a standing regression
    assertion (`assert "pan_number_enc" not in data`) that both fields never appear in the create
    response. No test seeds a real-looking value for either field anywhere in the repository.
12. **Frontend** — zero references in `apps/web/src` (confirmed by grep) — no UI reads or writes
    either field.

**Conclusion**: these two columns carry **zero current production-data risk** — nothing writes to
them, nothing reads them back, and no test or seed script has ever populated them with a
real-shaped value. The risk is entirely forward-looking: the moment a future slice (E-02's
originally-scoped PAN/Aadhaar write path, per `HRMS_SYSTEM_DESIGN_BASELINE.md` H-2/D-2) adds a
write path, it will write into an unencrypted column unless DATA-01 lands first. This matches
`HRMS_SYSTEM_DESIGN_BASELINE.md`'s own stated priority: land the mechanism **before** that slice
ships, not after.

---

## 3. `employee_bank.account_number_enc` (+ `ifsc`, `account_holder_name`) — live, in production shape

This is the **higher-urgency** of the two DATA-01 storage locations — unlike PAN/Aadhaar, this one
already has a complete, shipped, callable read/write path.

1. **SQLAlchemy model** — `hrms/modules/employee/models.py:241-283` (`EmployeeBank`). Plain
   `String`/`TEXT` columns. The class docstring (lines 255-258) explicitly documents the gap as a
   known, accepted, tracked decision — not a silent oversight — citing
   `HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2 Option 2 and
   `docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §14/§22 PD-4 directly.
2. **Pydantic request schema** — `BankCreate` (`employee/schemas.py:520-534`), `extra="forbid"`.
   `account_number_enc` accepted as a **plaintext string at the API boundary** (the field name
   promises encryption at rest; the schema does not perform any).
3. **Pydantic response schema** — `BankRead` (`schemas.py:537-553`) returns
   `account_number_enc`/`ifsc`/`account_holder_name` **unmasked, in full**, to any caller who
   passes the permission check below. No partial-masking exists anywhere in this codebase today
   (see §8).
4. **Create path** — `POST /v1/employees/{employee_id}/bank`
   (`employee/router.py:716`, gated on `EMPLOYEE.UPDATE_SENSITIVE`) →
   `EmployeeBankService.create_bank` (`employee/service.py`, around line 2047) → INSERT of the
   plaintext value into `account_number_enc`.
5. **Update path** — none (insert-only, effective-dated revision API — a "revision" is a new
   `POST`, per module convention; no `PATCH`/`DELETE` exists for any Employee sub-resource).
6. **Read path** — `GET /v1/employees/{employee_id}/bank` and `GET
   /v1/employees/{employee_id}/bank/{bank_id}` (`router.py:668`, `693`), both gated on
   `EMPLOYEE.VIEW_BANKING`.
7. **Admin path** — same two `GET` routes; a `COMPANY`-wide HR admin holding `.VIEW_BANKING` sees
   every employee's account number in full, unmasked.
8. **Employee self-service path** — `EMPLOYEE.VIEW_BANKING` is the **one** RESTRICTED Employee
   sub-resource permission in this module that is `SELF`-scope-bound (`employee/permissions.py:71`,
   confirmed live in `router.py` via `require_permission(EMPLOYEE_VIEW_BANKING)` resolving a real
   `DataScope`, unlike Compensation/Statutory which stay `COMPANY`-only) — so an employee viewing
   their own profile can retrieve their own account number in full through the same unmasked
   `BankRead` schema.
9. **Import path** — `employee_import` (bulk CSV) has **zero** references to any banking field
   (confirmed by grep across the whole module) — bulk import cannot currently create or modify a
   bank row at all.
10. **Export path** — none exists (see §7).
11. **Search/filter path** — none. Confirmed by grep: `account_number_enc` never appears in any
    `WHERE`, `ORDER BY`, or repository filter anywhere in `employee/repository.py`. No index or
    unique constraint on the column (§1 table; the migration only adds `(company_id)` and
    `(employee_id)` indexes, not on the sensitive columns themselves).
12. **Background-job usage** — none.
13. **Audit-log usage** — **confirmed plaintext exposure**: `bank_to_audit_dict()`
    (`employee/schemas.py:581-582`) is `bank.model_dump(mode="json")` — the **entire** `BankRead`,
    account number included — passed as `before`/`after` to `AuditService.record(...)` at
    `employee/service.py:2066-2074` (`action="BANK_REVISED"`). Every bank write creates a permanent
    `audit_log` row containing the full plaintext account number. No API route currently exposes
    `audit_log` contents (confirmed: no router references `AuditLog`), so this is a
    database/backup-level exposure, not an API-level one today — but it is a second at-rest
    location for the same secret, and it is never overwritten or redacted (audit rows are
    immutable by the architecture's own invariant #8, `HRMS_SYSTEM_DESIGN_BASELINE.md` §20).
    **Implemented**: `bank_to_audit_dict()` now calls `mask_sensitive()`
    (`hrms/core/audit/redact.py`, implementation plan §7) before the dict ever reaches
    `AuditService.record()` — every `BANK_REVISED` audit row written from this point forward
    carries the masked, last-four-digit form only (`"******7890"`), never plaintext or raw
    ciphertext, verified by `test_bank_audit_log_row_never_contains_the_plaintext_account_number`
    (`tests/integration/modules/employee/test_employee_banking.py`). **Historical rows written
    before this change remain plaintext** — the implementation plan's §8 remediation strategy is
    fully specified but was not executed in this batch (no product/compliance sign-off recorded);
    this is an explicit, open item, not an oversight.
14. **Test fixtures** — `tests/unit/modules/employee/test_employee_bank_service.py` and
    `tests/integration/modules/employee/test_employee_banking.py` both use an
    **obviously-synthetic** value, `"1234567890"`, consistently — no real-shaped test data.
15. **Existing migration history** — one foundational migration (§1); never altered since.
16. **Direct SQL access** — none found outside the ORM and the one migration.
17. **Frontend exposure** — `apps/web/src/components/employee/banking-panel.tsx` renders the value
    through `maskAccountNumber()` (`apps/web/src/lib/employee/validate-bank.ts:53-60`, masks all
    but the last 4 digits with `•`). **This masking is client-side only.** The API response the
    browser receives already contains the full plaintext value — `maskAccountNumber` only changes
    what is *rendered*, not what crosses the network. Anyone reading the network response body
    directly (browser devtools, a proxy, a script calling the API without the web app, a browser
    extension) sees the real account number regardless of this component's behavior. This is the
    single most concrete, demonstrable exposure this inventory found.

**Conclusion**: this is the storage location DATA-01 should treat as most urgent — it already has
real production-shaped read/write paths, a live self-service consumer, a plaintext copy inside
every audit row it creates, and a frontend that assumes masking is a solved problem when it is not.

---

## 4. `onboarding_case.bank_info` — the second, easy-to-miss live plaintext copy

**This is the most important finding in this inventory.** Encrypting `employee_bank.
account_number_enc` alone does **not** close DATA-01 — the exact same value passes through, and is
persisted in, a second, completely independent plaintext location first, written by an
**unauthenticated** caller.

The flow, traced end to end:

1. **Public, token-authenticated (not user-authenticated) wizard** — a candidate submits
   `BankInfoSection` (`onboarding/schemas.py:222-233`, a subset of `BankCreate` — same
   `account_number_enc`/`ifsc`/`account_holder_name`/`bank_name`/`branch_name` fields, plaintext at
   the API boundary) via a `PATCH` route gated only by possession of an emailed onboarding token,
   not a `User` session. This is the **earliest** point sensitive bank data enters the system for a
   new hire, predating the `Employee`/`EmployeeBank` rows' own existence.
2. **Storage** — `OnboardingCase.bank_info` (`onboarding/models.py:75`), an **untyped `JSONB`
   dict** (`mapped_column(JSONB, default=dict)`) — by design (module docstring, lines 12-16):
   validated only against the matching Pydantic subset at the API boundary, never given ORM-level
   field structure. This means a column-level SQLAlchemy `TypeDecorator` (the natural fix for
   `employee_bank.account_number_enc`) **cannot** transparently reach inside this JSONB blob — the
   encryption/decryption has to happen at the service layer, on the specific key(s) inside the
   dict, before/after it round-trips through this column.
3. **Read-back #1 (candidate-facing)** — the candidate's own "my submission so far" response model
   (`onboarding/schemas.py:289`, `bank_info: dict[str, object]`, populated directly from
   `case.bank_info` at line 328) returns the **raw, unmasked dict** — including the plaintext
   account number the candidate just typed in, echoed straight back with no transformation.
4. **Read-back #2 (HR-facing)** — the HR case-detail response model (`schemas.py:423`, same shape,
   populated at line 437 from the identical `case.bank_info`) returns the same raw dict to any HR
   user with case-review access — again, fully unmasked.
5. **Activation (O7)** — `OnboardingService.activate_case()` (`onboarding/service.py:864-1020`), at
   line 958-962, does `if case.bank_info: ... BankCreate(effective_from=case.proposed_joining_date,
   **case.bank_info)` — unpacking the plaintext JSONB dict directly into the real `BankCreate`
   schema, which then flows into `EmployeeBankService.create_bank` and lands in
   `employee_bank.account_number_enc` (§3) for the first time. **The `onboarding_case.bank_info`
   row is never cleared or redacted after this copy happens** — the value now exists permanently
   in *two* places, not one, for every employee who was ever onboarded through this wizard, and
   the application never reads `bank_info` again after this point (confirmed: no later code path
   references `case.bank_info`). **Partially implemented**: both copies are now encrypted at rest
   (`onboarding_case.bank_info`'s `account_number_enc` key and `employee_bank.account_number_enc`
   are independently encrypted, under different AAD, per implementation plan §2/§9 — verified by
   `test_activate_decrypts_bank_info_and_reencrypts_for_employee_bank`), so this is no longer a
   plaintext duplication. The plan's §9.1 default (clearing the key after activation) was
   **not enabled** in this batch — no product/compliance sign-off was recorded, and per this
   batch's own instructions that decision was not made unilaterally — so the two-copy duplication
   itself still exists, just encrypted (plan §9.2's retention alternative is the current, de facto
   behavior).
6. **Import/export** — no import or export path touches `onboarding_case` at all.
7. **Search/filter** — none; `bank_info` is never queried by its contents anywhere (confirmed by
   grep — it is only ever read whole, never filtered).
8. **Audit logging** — no `AuditService.record()` call in the onboarding activation path passes
   `bank_info` or the constructed `BankCreate` as its payload (confirmed by reading the activation
   method in full) — this specific location does **not** duplicate into the audit log the way §3's
   does; the *subsequent* `employee_bank` write still does (§3 item 13, since activation calls the
   same `create_bank` service method).
9. **Frontend exposure** — the onboarding wizard's own frontend (`apps/web/src/lib/onboarding/
   types.ts`, `apps/web/src/lib/onboarding/public-wizard.ts`) necessarily has the plaintext value
   in-memory to submit it in the first place; not a new exposure beyond what item 3 above already
   describes for the read-back.
10. **Test fixtures** — `tests/integration/modules/onboarding/test_onboarding_public.py:155` and
    similar use synthetic values (`"State Bank"`, `"SBIN0001234"`) consistently.

**Conclusion**: any implementation that encrypts only `employee_bank.account_number_enc` and
leaves `onboarding_case.bank_info` untouched has fixed roughly half the actual exposure — the
implementation plan treats this as a first-class, equally-weighted target, not an afterthought.

---

## 5. Adjacent PII already flowing through the same onboarding mechanism (context only, not DATA-01 scope)

`onboarding_case.statutory_info` (JSONB) carries the same shape of gap for `pf_number`/
`esi_ip_number` as `bank_info` does for banking — same untyped-JSONB storage, same
read-back-unmasked pattern, same activation-time copy into `employee_statutory`. **Not named in
DATA-01**, not touched by this plan; flagged here so a future PII-encryption follow-up (were one
ever scoped for statutory identifiers) does not have to re-derive this from scratch. No action
taken.

---

## 6. Search, sort, filter, uniqueness — direct answer

**None of the three DATA-01-named fields (`pan_number_enc`, `aadhaar_number_enc`,
`account_number_enc`) are ever the target of a `WHERE`, `ORDER BY`, `JOIN`, or uniqueness
constraint anywhere in this codebase**, confirmed by:

- grepping `employee/repository.py` (the only place `Employee`/`EmployeeBank` queries are built) —
  zero matches for any of the three column names in a query-construction context;
- the migrations (§1) — no index or `UNIQUE` constraint defined on any of the three columns, only
  the standard `company_id`/`employee_id` tenant-scoping indexes;
- the API's list/filter surface (`GET /employees`, `GET /employees/{id}/bank`) — neither accepts a
  query parameter referencing any of these three fields (confirmed against `router.py`'s `Query(...)`
  declarations).

**This directly answers the deterministic-lookup question the implementation plan needs**: there
is no current requirement for exact lookup, partial lookup, sorting, or duplicate detection on any
of these three fields. A blind index/HMAC is **not required today** and the implementation plan
does not propose building one — see the plan's Search Requirements section for the explicit
reasoning and the one narrow condition under which that conclusion would need to be revisited.

---

## 7. Import/export — direct answer

**No export functionality of any kind exists anywhere in this API.** Confirmed by repository-wide
search for `csv.writer`, `StreamingResponse`, `xlsx`/`openpyxl`, and any route returning
`media_type="text/csv"` other than one: `GET /v1/employee-imports/template`
(`employee_import/router.py:43-47`), which serves a **blank CSV template for uploading**, not an
export of any employee data. There is therefore no current export path that could leak these
fields — this significantly simplifies the corresponding section of the implementation plan (no
export-masking work is required *today*; the plan still specifies the rule that must hold if
export functionality is ever added later).

**Import** (`employee_import`, bulk CSV) has zero references to PAN, Aadhaar, or bank fields
anywhere in its schema, service, repository, or Celery task — it cannot currently create or modify
any of the three fields. Only the onboarding wizard (§4) and the direct Banking API (§3) can.

---

## 8. Masking — current state vs. documented product intent

Three independent product documents (`docs/product/19_RBAC_and_Permission_Matrix.md` §6,
`docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md` §2G, `docs/design/screens/
01_Employee_List_Directory.md`) all specify the **same** intended partial-masking format:

```text
PAN:          ABCDE****F
Aadhaar:      XXXX XXXX 1234
Bank account: ******7890
```

**None of this is implemented at the API layer.** The existing, shipped precedent for every
RESTRICTED field in this codebase (Compensation, Statutory, and now Banking) is **binary
whole-sub-resource gating only**: a caller either has the permission and receives the full
unmasked value, or lacks it and the field is *omitted* (never `null`) from the response. This is a
documented, deliberate, already-resolved decision — `docs/modules/employee/
33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §15 **PD-3**, still open, recommends *not* building
partial masking because no document names which permission tier should see the masked view versus
the full view. The frontend's `maskAccountNumber()` (§3 item 17) is the only place in the entire
system that renders the documented masked format — and it does so after already receiving the full
plaintext value over the network.

The implementation plan treats API-level masking as **closely related to, but separable from,**
DATA-01's core encryption-at-rest work, and explicitly recommends resolving PD-3 as part of the
same batch — since the natural implementation point for "decrypt only inside a narrow,
authorized path" is exactly where a masked vs. full view decision would also be made.

---

## 9. Logging — grep results

Searched `structlog`/`logging`/`print` call sites across the whole API for any of the three field
names or the literal string `account_number`: **zero matches** outside the files already named in
this inventory (models/schemas/service/test files, where the field name appears as an identifier,
not a logged value). `core/observability/logging.py` configures `structlog` but (per
`PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own finding, `OBS-02`) no request-path code currently
calls `get_logger()` at all — so there is currently no request logging pipeline that could leak
these fields even if it wanted to. The one confirmed at-rest plaintext exposure via a logging-
adjacent mechanism is the audit log (§3 item 13), not `structlog` output. `core/errors/handlers.py`'s
generic exception handler (`_ = exc`) does not serialize or log the exception body at all today
(a separate, already-tracked gap, `OBS-01`) — so an unhandled exception during a bank write cannot
currently leak the value through an error response either, though this is incidental (a side effect
of `OBS-01`, not a DATA-01 control) and should not be relied upon once `OBS-01` is fixed.

---

## 10. Summary table

| Location | Live today? | Encryption today? | Masking today? | Audit-log copy? | Search/index? |
|---|---|---|---|---|---|
| `employee.pan_number_enc` | No (dormant) | No | N/A (never exposed) | No | No |
| `employee.aadhaar_number_enc` | No (dormant) | No | N/A (never exposed) | No | No |
| `employee_bank.account_number_enc` | **Yes** | No | Client-side only (cosmetic) | **Yes, plaintext** | No |
| `onboarding_case.bank_info` | **Yes**, unauthenticated write | No | No (raw dict both read-backs) | No (but feeds #3, which does) | No |

This inventory is the factual basis for every recommendation in
`DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md`.
