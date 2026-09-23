# DATA-01 — PII Encryption Implementation Plan

| Field | Value |
|---|---|
| Status | **IMPLEMENTATION BATCH 1 COMPLETE — READY FOR REVIEW** (encryption infra, both live write paths, mandatory audit redaction, and the backfill are implemented and tested; historical audit-log remediation and the onboarding post-activation cleanup are explicitly gated on product/compliance sign-off, per §8/§9, and were not executed) |
| Baseline commit | `c3b8cec9c1d24dbd4892f92a649b9c4c98e3533f` (branch `main`) |
| Source finding | `DATA-01`, `docs/audits/PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md` §2 |
| Prior art this plan builds on, not duplicates | `docs/architecture/HRMS_SYSTEM_DESIGN_BASELINE.md` Decision **D-2** / Risk **H-2**; `docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §14/§15 **PD-4** and §15 **PD-3** (masking) |
| Companion document | `DATA_01_PII_DATA_FLOW_INVENTORY.md` — every factual claim about where PII lives cites it |
| Companion document | `DATA_01_PII_ENCRYPTION_TEST_MATRIX.md` |
| Architecture review outcome | An architecture review of the first draft of this plan returned **NO-GO — RESOLVE THESE ITEMS BEFORE IMPLEMENTATION**, citing six internal-consistency blockers (§0 below). This revision resolves all six. |

This plan does not reopen the question of *whether* to encrypt — `HRMS_SYSTEM_DESIGN_BASELINE.md`
Decision D-2 already recommended "column-level encryption (SQLAlchemy `TypeDecorator` + KMS)" and
the production audit's DATA-01 finding independently arrives at the same direction (envelope
encryption, KMS-managed key, decrypt only in narrow service paths, mask reads, backfill, complete
before the first real tenant). This plan makes that direction concrete, internally consistent, and
implementation-ready.

---

## 0. What changed in this revision (architecture-review blockers → resolution)

The first draft of this plan was internally inconsistent — it described itself as "envelope
encryption" while its actual recommended design (old §2.2 "Design A") was direct per-field KMS
`Encrypt`/`Decrypt`, which is **not** envelope encryption. That single inconsistency cascaded into
five more gaps. All six are resolved in this revision:

| # | Blocker | Resolution |
|---|---|---|
| 1 | **Design A/B inconsistency** — the plan recommended direct KMS `Encrypt`/`Decrypt` per field ("Design A") while calling itself envelope encryption | §2.1 — adopts true envelope encryption: KMS wraps a per-environment application DEK; AES-256-GCM runs locally against the DEK. KMS is never called per field operation. |
| 2 | **No encryption-key registry was defined** — the ciphertext format referenced a `key_version` with nowhere for it to resolve to | §2.2 — defines the `encryption_keys` registry explicitly: fields, current-key selection, old-key lookup, rotation, recovery. |
| 3 | **No AAD** — GCM was specified without Additional Authenticated Data, so a ciphertext value copied into a different row would still decrypt successfully | §2.4 — AAD is now mandatory, binds every ciphertext to `table:column:record_id`, specified per field. |
| 4 | **Encryption boundary violation** — old §2.4 recommended a `TypeDecorator` whose `process_result_value` transparently decrypts on every ORM load, which is exactly the "automatic plaintext materialization on read" this design must avoid | §2.5 — the boundary is corrected: encrypt-on-write may use a `TypeDecorator` (write-only direction), but decryption is never automatic; it is always an explicit call inside an authorized service method. |
| 5 | **Audit-log redaction was optional** — old §7 listed fixing `bank_to_audit_dict()` as a "recommended, not must-have" fast-follow | §7 — audit-log redaction is now a mandatory DATA-01 requirement with a reusable, typed mechanism, not a one-off fix to one function. |
| 6 | **No historical-data decision** — old plan said nothing about the plaintext already sitting in `audit_log` rows, or about `onboarding_case.bank_info` never being cleared after activation | §8 (historical audit remediation) and §9 (onboarding lifecycle) — both now carry explicit, evaluated decisions with a stated default and a named production sign-off gate. |

---

## 0a. Implementation record (this batch)

This section records what the implementation batch actually shipped, against this plan, including
one material technical correction discovered during implementation and two items deliberately left
un-executed pending sign-off.

**One technical correction to §2.5/§2.6's literal mechanism** (the security properties are
unchanged; only the SQLAlchemy mechanism that satisfies them changed): §2.5 described the write
side as a SQLAlchemy `TypeDecorator` (`EncryptedOnWrite`) whose `process_bind_param` would compute
AAD from the row's own primary key at flush time. This is not implementable as literally described,
for two independent, structural reasons discovered during implementation:

1. **AAD needs row context `TypeDecorator.process_bind_param(value, dialect)` does not have.** A
   column-level `TypeDecorator` genuinely has no access to the owning instance (its `id`) at bind
   time — there is no SQLAlchemy hook that supplies it.
2. **DEK resolution is inherently async** (KMS calls via `aioboto3`), and SQLAlchemy's synchronous
   ORM hooks (`process_bind_param`, `before_insert`/`before_update` mapper events) cannot `await`
   them.

**Resolution shipped**: encryption is applied via **explicit, async service-layer calls** —
`PiiCryptoService.encrypt_column`/`decrypt_column`/`encrypt_jsonb_key`/`decrypt_jsonb_key`
(`hrms/core/crypto/service.py`) — at every write and read site, for every field, uniformly. This is
what the plan already specified for `onboarding_case.bank_info` (a JSONB key never had a
`TypeDecorator` option); the three real columns (`Employee.pan_number_enc`/`.aadhaar_number_enc`,
`EmployeeBank.account_number_enc`) now use the identical explicit-call pattern instead of a
column-type hook. The columns themselves remain plain `String` at the SQLAlchemy level — no column
type change, no migration needed for them (§4 Option A is unaffected). Every security property §2.5
required is preserved and, if anything, made more literally true: there is no `TypeDecorator` at
all, so there is no code path that could theoretically decrypt on read — every decrypt is a visible,
grep-able call to `PiiCryptoService`, always inside a permission-checked service method
(`EmployeeBankService._decrypt_bank`, `OnboardingCaseService._decrypt_bank_info`,
`OnboardingActivationService._decrypt_bank_info`).

**Implemented in full**:

- §2.1-§2.4 (envelope encryption, `encryption_keys` registry, ciphertext format, mandatory AAD) —
  `hrms/core/crypto/{kms,keys,registry,field,aad,models,service,errors}.py`.
- §2.2's registry table — migration `20260927090000_encryption_key_registry.py`.
- §2.5's boundary (corrected mechanism, see above) — wired into `EmployeeBankService` (live write
  path) and `OnboardingCaseService`/`OnboardingActivationService` (live write path + the
  decrypt-then-re-encrypt handoff at activation).
- §5.4's development-mode local key — `Settings.dev_encryption_key`, `DekCache`'s dev short-circuit.
- §7's mandatory audit-log redaction — `hrms/core/audit/redact.py`, wired into
  `bank_to_audit_dict()`.
- §6's backfill, all four locations, batched/idempotent/`FOR UPDATE SKIP LOCKED`/per-row verified —
  `hrms/core/crypto/backfill.py`.
- §10's application-level DEK rotation and initial provisioning — `hrms/core/crypto/provisioning.py`
  (operator-invoked, never automatic).
- §10.3's boot guard — the KMS-configuration half in `Settings._guard_non_development_config`; the
  `encryption_keys`-has-an-ACTIVE-row half in `app.py`'s `lifespan()` (runs only outside
  `development`; confirmed to never fire during this repository's test suite, since `ASGITransport`
  never triggers FastAPI's lifespan).
- PAN/Aadhaar (`employee.pan_number_enc`/`.aadhaar_number_enc`) — the encryption/decryption
  machinery is fully wired and tested against these two columns directly (no service-layer write
  path exists yet to call it from, inventory §2 — unchanged by this batch, out of scope per E-02).

**Deliberately not executed, per this batch's own gating instructions**:

- **§8 historical audit-log remediation** — strategy fully documented; **not run**. No sign-off was
  recorded authorizing it, and this batch's own scope required stopping rather than deciding this
  unilaterally. `audit_log` rows written before this batch (if any real ones exist — none in this
  repository's own test/dev data) remain plaintext until that sign-off is obtained and the
  remediation is separately executed.
- **§9.1 onboarding post-activation cleanup** — **not enabled**. No sign-off was recorded. This
  batch ships §9.2's retention alternative as the *de facto* current behavior:
  `onboarding_case.bank_info`'s `account_number_enc` key is encrypted (§2) but is **not** cleared
  after activation — the same "never clear" behavior the original inventory finding described,
  except now the retained copy is encrypted rather than plaintext.

See the implementation batch's own final report (delivered in-conversation) for the full file list,
test results, and database verification evidence.

---

## 1. What this plan is building toward

Four storage locations need encryption at rest (inventory §1, §10):

1. `employee.pan_number_enc` — dormant, no write path exists yet.
2. `employee.aadhaar_number_enc` — dormant, no write path exists yet.
3. `employee_bank.account_number_enc` — live, has a shipped write path.
4. `onboarding_case.bank_info` (JSONB, `account_number_enc` key within it) — live, written by an
   unauthenticated caller, copied into #3 at activation without ever being cleared (resolved: §9).

Plus, newly in scope per the architecture review (§7, §8):

5. `audit_log.before_json` / `.after_json` — currently receives an unredacted `BankRead.model_dump()`
   for every bank write (inventory §3 item 13), and already contains plaintext account numbers from
   every bank write made to date.

No lookup, sort, filter, join, or uniqueness constraint exists on any of the four field-level
locations today (inventory §6). No export path exists (inventory §7). This materially simplifies
the design: **this plan does not recommend building a blind index/HMAC** (see §3).

---

## 2. Encryption architecture

### 2.1 Envelope encryption: KMS-wrapped, environment-scoped application DEK

**Corrected design** (resolves blocker 1, §0). Values are encrypted in the application process,
before the ORM ever sees them, and decrypted only inside the narrow service methods that genuinely
need the plaintext (§2.5). The database, its backups, and anyone with raw SQL access never see
plaintext or a key that could unwrap it on its own.

The envelope has two layers, with one instance of each active per environment:

- **KEK (key-encrypting key)** — one **AWS KMS customer-managed key (CMK) per environment**
  (`hrms-pii-encryption-staging`, `hrms-pii-encryption-production`, §5.2). Never leaves KMS. Its
  only job is to wrap and unwrap DEKs.
- **DEK (data-encrypting key)** — one **active application DEK per environment per key version**,
  established via a single KMS `GenerateDataKey` call at key-creation/rotation time (§2.2, §10),
  used to perform **AES-256-GCM locally** against every PAN/Aadhaar/bank-account value, for as many
  records as exist, until the next rotation.

**Why "one DEK per environment," not one DEK per record.** The first draft of this plan floated a
per-record DEK as its rejected "Design B" alternative and dismissed it as unnecessary complexity —
but a *per-record* DEK still requires a KMS network call (to generate or unwrap that record's own
DEK) on every single field operation, which is exactly the cost problem direct KMS `Encrypt`/
`Decrypt` ("Design A") had. That defeats the actual purpose of envelope encryption, which is to
make the expensive, rate-limited KMS call rare (once per key version, amortized across every record
encrypted under that version) while keeping the fast, unlimited, purely-local AES-GCM operation on
the hot path. A DEK shared across all records in an environment for a given key version — combined
with mandatory per-record AAD (§2.4) so records cannot be confused with one another despite sharing
a key — is the standard shape of envelope encryption (the same pattern S3-SSE, EBS encryption, and
every major KMS-integrated system uses: a small number of long-lived DEKs, not one per object).

**Mechanics:**

- **`GenerateDataKey`** establishes a DEK: KMS returns both a plaintext DEK (used immediately, kept
  only in memory) and a `CiphertextBlob` (the same DEK, wrapped by the CMK). Called once per new key
  version (creation or rotation, §10), never per field operation.
- **KMS-wrapped DEK persisted** in the encryption-key registry (§2.2) — the `CiphertextBlob`, not
  the plaintext.
- **AES-256-GCM** performs the actual field encryption/decryption, entirely in the application
  process, using the plaintext DEK already resolved into memory. Authenticated encryption —
  confidentiality **and** tamper-detection in one primitive (a bit-flipped ciphertext, or a
  mismatched AAD, fails to decrypt rather than silently producing corrupted plaintext). Available
  today via the `cryptography` package (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`),
  already present in this repository's dependency lock (`uv.lock`, version 50.0.0) as a transitive
  dependency of `python-jose[cryptography]` — no new supply-chain surface, though it should be
  promoted to a direct `pyproject.toml` dependency rather than relied on transitively (a
  `python-jose` upgrade or swap — separately tracked as `DEP-01` — could otherwise silently drop
  it).
- **Plaintext DEK held only in application process memory** — never persisted to disk, never
  logged, never sent anywhere except the one KMS `GenerateDataKey`/`Decrypt` round trip that
  produced it.
- **Lazy DEK loading** — nothing calls KMS at process boot. The first encrypt/decrypt operation
  that needs a given `key_version` triggers exactly one `kms:Decrypt` call against that version's
  `wrapped_dek` (§2.2); the result is cached in-process.
- **Bounded cache lifetime** — each resolved plaintext DEK is cached in-process for a fixed TTL
  (proposed: 60 minutes), not indefinitely. This bounds (a) how long a rotated-out DEK stays
  resident in a process's memory after `encryption_keys` marks it `RETIRED`, and (b) how stale a
  long-running process's view of "which version is current" can become without a restart. A cache
  miss after TTL expiry re-resolves from the registry (a local-DB read, cheap) and only calls KMS
  again if that specific version's wrapped bytes aren't already cached — rotation does not require
  re-fetching every version from KMS repeatedly.
- **Old DEKs are retained, forever, for decrypting historical ciphertext** — `encryption_keys` rows
  are never deleted (§2.2). A record encrypted under key version 3 keeps decrypting correctly under
  version 3's DEK indefinitely, regardless of how many later rotations have happened.
- **New writes use the current DEK only** — the registry's single `ACTIVE` row (§2.2) is what every
  new encrypt operation resolves to; existing rows are never silently re-encrypted as a side effect
  of a write elsewhere.
- **Application-level DEK rotation creates a new key version** — §10 has the full rotation
  procedure; it does not require decrypting the whole database.

**Why this satisfies the production audit's envelope-encryption requirement.** KMS never sees a
plaintext PAN, Aadhaar, or bank-account value — its blast radius is limited to "can unwrap this
environment's DEK(s)," never "has decrypted this specific employee's bank account." KMS's own
CloudTrail log now records one `Decrypt` call per DEK-cache-miss (at most a handful per process per
TTL window), not one call per field read — cheaper, and the textbook definition of envelope
encryption: a data-encrypting key protected by a key-encrypting key, with the KEK never directly
touching application data. This is also what makes §2.1's threat model (§11) hold: an attacker who
obtains a database dump gets ciphertext and a `key_version` integer only; unwrapping still requires
a live, IAM-scoped `kms:Decrypt` call the dump alone cannot make.

### 2.2 Encryption-key registry — `encryption_keys` (resolves blocker 2)

**Not created in this batch** — this is the planned schema, to be implemented as an Alembic
migration in the implementation batch, following this repository's existing conventions
(`Base`/`TimestampMixin`, UUID primary keys per `core/db/base.py`, `employee_bank`'s own shape as
the nearest precedent).

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` (PK) | Matches this repository's PK convention everywhere else. |
| `key_version` | `Integer`, unique, indexed | The integer embedded in every ciphertext string's `<key_version>` segment (§2.3). Monotonically increasing, assigned at row creation. |
| `kms_key_arn` | `String` | The KMS CMK ARN/alias that wrapped this row's DEK. Recorded per row (not assumed globally constant) so a future CMK replacement is representable without breaking old rows. |
| `wrapped_dek` | `Text` | Base64 of the KMS `GenerateDataKey` `CiphertextBlob`. Never the plaintext DEK. |
| `status` | `String` (`ACTIVE` \| `RETIRED`) | Exactly one `ACTIVE` row must exist at a time (enforced at the application/rotation-service level within one transaction that flips the old row to `RETIRED` and inserts the new `ACTIVE` row together — the same "no boolean-flag race" discipline this codebase already applies to effective-dated rows elsewhere, e.g. `employee_bank`'s GiST exclusion constraint for overlapping ranges; a DB-level partial unique index on `status = 'ACTIVE'` is a defense-in-depth option to add at implementation time, not a substitute for the transactional invariant). |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | Via `TimestampMixin`, this codebase's standard. |
| `activated_at` | `DateTime(timezone=True)`, nullable | When this version became `ACTIVE`. |
| `retired_at` | `DateTime(timezone=True)`, nullable | When this version stopped being `ACTIVE`. `NULL` while `ACTIVE`. |
| `created_by` | `String`, nullable | Free-text identifier of what triggered this version (`"initial-provisioning"`, `"scheduled-rotation"`, `"incident-response"`) — an audit breadcrumb for key history, not a `User` FK (rotation is an operational/CI action, not necessarily tied to a logged-in user). |

No `environment` column — this repository deploys a separate database per environment (dev/
staging/production, per `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own `ENVIRONMENT=` convention),
so `encryption_keys` is already environment-scoped by which database it lives in; adding a column
for it would be redundant, not defense-in-depth.

**How the current key is selected.** Query `encryption_keys WHERE status = 'ACTIVE'` — exactly one
row is expected; more than zero or more than one is a data-integrity fault the boot guard (§10)
should refuse to start against, not silently pick the first/last row of.

**How old keys are found.** `encryption_keys WHERE status = 'RETIRED'` (or, to resolve one specific
historical ciphertext, `WHERE key_version = <N>` — the exact lookup the decrypt path performs,
below). Rows are never deleted.

**How ciphertext `key_version` maps to key material.** Every ciphertext string carries its
`key_version` in plaintext (§2.3 — this is standard practice; the version number is metadata, not a
secret). Decrypting a value means: parse `key_version` from the string → look up (cache-first, §2.1)
the matching `encryption_keys` row by that exact `key_version` → if not cached, `kms:Decrypt` its
`wrapped_dek` to obtain the plaintext DEK → AES-256-GCM-decrypt the value using that DEK and the
AAD recomputed for that row (§2.4). A `key_version` with no matching registry row is a hard failure
(fails closed, never treated as "use the current key instead" — that would silently produce garbage
or, worse, appear to succeed against the wrong key in a hypothetical future AEAD variant that
doesn't authenticate the key itself).

**How rotation works.** See §10 in full; summarized here: generate a new DEK via `GenerateDataKey`,
insert a new `ACTIVE` `encryption_keys` row for it (new `key_version`), atomically flip the
previously-`ACTIVE` row to `RETIRED` in the same transaction, invalidate the in-process DEK cache's
"current version" pointer (not the cached DEK bytes themselves — old versions stay cached and valid
until their own TTL expires). New writes immediately begin using the new version; existing
ciphertext is untouched and keeps decrypting under its own recorded version.

**How old records remain decryptable.** Because `encryption_keys` rows are never deleted and every
ciphertext string is permanently associated with the `key_version` that encrypted it, a record
encrypted five rotations ago decrypts exactly the same way today as the day it was written — the
lookup above resolves any historical version identically to the current one.

**How a new application process obtains the required DEK.** No special "warm the cache at boot"
step is required or recommended (a KMS call at every process boot, across every worker/pod, would
itself reintroduce needless KMS traffic). The first request that needs to encrypt or decrypt a
DATA-01 field triggers the lazy-load path above for whichever `key_version` it needs — normally just
the current `ACTIVE` version, resolved once per process per TTL window (§2.1).

### 2.3 Ciphertext format

Every encrypted column/JSONB-key value is replaced by a single opaque string with this exact
structure:

```text
v1:<key_version>:<base64(nonce)>:<base64(ciphertext_and_tag)>
```

- `v1` — a literal format-version tag, distinct from `key_version`. Lets a future change to the
  envelope scheme (a different AEAD construction, a different registry shape) be introduced without
  an ambiguous migration — code can `match` on the leading segment and dispatch to the right decrypt
  path, forever, even mid-migration.
- `<key_version>` — the integer identifying the exact `encryption_keys` row that encrypted this
  value (§2.2). Stored in plaintext alongside the ciphertext (standard practice — the version number
  is metadata, not a secret) so a rotation does not require re-encrypting every existing row before
  old rows become unreadable.
- `nonce` — 12 bytes, generated fresh per encryption via a cryptographically secure random source
  (`os.urandom(12)`, AES-GCM's standard nonce size). **Never reused** for a given key — GCM's
  security guarantee depends entirely on nonce uniqueness per key; this is why encryption must be
  randomized (a fresh nonce every call), not deterministic, ruling out any lookup-by-ciphertext-
  equality shortcut (consistent with §3's conclusion that no such lookup is needed).
- `ciphertext_and_tag` — AES-GCM's output already appends the 16-byte authentication tag to the
  ciphertext; no separate tag field is needed in the format.

**AAD is not embedded in this string** — see §2.4 for why, and how a malformed or tampered value
fails.

**Malformed ciphertext fails safely.** A string that does not match this exact shape (wrong number
of `:`-delimited segments, non-base64 segments, an unrecognized version tag) is rejected by the
decrypt helper with a distinct, named exception before any cryptographic operation is attempted —
never an unhandled `IndexError`/`binascii.Error` that could surface a stack trace containing
adjacent request context. During the one-time backfill (§6), a value that is *not* `v1:`-shaped is
the expected, correctly-handled case (it means "still plaintext, needs migrating," §6.2) — this is
a classification, not an error path, in that specific context only.

**Future format versions are possible.** The `v1` prefix reserves the ability to introduce `v2`
later (e.g. a different AEAD, a different registry key shape) without an ambiguous migration:
decrypt logic dispatches on the leading segment, so `v1` and `v2` values can coexist in the same
column indefinitely, exactly as `v1`-and-plaintext coexist during today's planned backfill.

Chosen over a structured (e.g. JSON) representation because every value that needs this format is a
single opaque string being written into either a `TEXT` column or a specific JSONB key whose type is
already `str | None` in the corresponding Pydantic schema — a colon-delimited string requires no
schema/column-type change anywhere (§4 depends on this).

### 2.4 AAD — mandatory, binds ciphertext to its storage identity (resolves blocker 3)

**GCM's Additional Authenticated Data (AAD) is mandatory for every encrypt/decrypt call in this
design — no field may be encrypted without it.** AAD is authenticated (tamper-evident) but not
encrypted; it is supplied by the caller at both encryption and decryption time and is **never
itself stored** — GCM verifies the caller-supplied AAD at decrypt time matches what was supplied at
encrypt time, as part of the same authentication-tag check that already catches ciphertext
tampering. This is why AAD must be **deterministically re-derivable from the row being decrypted**,
not read back from anywhere: the whole point is that the code path decrypting a row always knows,
independently of the ciphertext itself, which row it is decrypting for, and GCM refuses to proceed
if that context doesn't match what was true at encryption time.

**Convention, following this repository's existing `table.column` naming style used throughout the
inventory and this plan:**

```text
<table>:<column>:<record_id>
```

For a JSONB key (only `onboarding_case.bank_info`, §2.5), the column segment identifies the specific
key within the blob, since the table/column pair alone is not precise enough (other, non-sensitive
keys share the same JSONB column):

```text
<table>:<column>.<jsonb_key>:<record_id>
```

Specified per field, all four DATA-01 locations:

| Field | AAD |
|---|---|
| `employee.pan_number_enc` | `employee:pan_number_enc:{employee.id}` |
| `employee.aadhaar_number_enc` | `employee:aadhaar_number_enc:{employee.id}` |
| `employee_bank.account_number_enc` | `employee_bank:account_number_enc:{employee_bank.id}` |
| `onboarding_case.bank_info` (`account_number_enc` key) | `onboarding_case:bank_info.account_number_enc:{onboarding_case.id}` |

`{record_id}` is the row's own primary-key UUID, rendered as its canonical string form (matching
how every other identifier already round-trips through this codebase's JSON responses) — never a
business identifier that could change (e.g. `employee_code`), since AAD must be stable for the
lifetime of the ciphertext.

**What happens if ciphertext is copied to another row.** Say an attacker (or a bug — a copy-paste
in a data-migration script, a restored backup partially merged into live data, a replication
anomaly) writes `employee_bank` row B's `account_number_enc` ciphertext into row A's
`account_number_enc` column. Row A's own id differs from row B's id, so decrypting row A recomputes
AAD as `employee_bank:account_number_enc:{A.id}` — which does not match the AAD
(`employee_bank:account_number_enc:{B.id}`) that was supplied when that ciphertext was originally
encrypted. **GCM's authentication-tag check fails, and the decrypt operation raises an error rather
than returning row B's plaintext value under row A's identity.** This is the specific property AAD
adds beyond what the format's own tamper-detection already provided (§2.3): without AAD, a
byte-for-byte valid ciphertext blob decrypts successfully under any key version that produced it,
*regardless of which row it currently sits in* — a real risk given none of these columns has a
uniqueness constraint (inventory §6) and nothing else in the schema would notice a copied value.
AAD closes that gap structurally, at the cryptographic layer, rather than relying on an application-
level check to catch it.

### 2.5 The encryption boundary (resolves blocker 4)

**Adopted model, from the architecture review, verbatim:**

```text
Write:  plaintext → encryption helper encrypts it → database receives ciphertext.
Read:   database returns ciphertext → authorized service explicitly calls decrypt →
        plaintext exists only inside the narrow service operation that requires it.
```

**The first draft of this plan violated this on the read side.** Its proposed `EncryptedString`
`SQLAlchemy` `TypeDecorator` implemented both `process_bind_param` (encrypt on write — fine) *and*
`process_result_value` (decrypt on read) — meaning **every ORM load of a row containing that column
would transparently decrypt it**, including any incidental load that has nothing to do with the
narrow, permission-checked service path the plan itself specifies elsewhere (§8, §12 item 4). That
is precisely the "automatic plaintext materialization on read" the architecture review's model
forbids, and it would have silently defeated the entire "decrypt only where genuinely needed"
property this plan claims throughout.

**Corrected shape:**

```text
hrms/core/crypto/
  __init__.py
  kms.py        — KmsKeyService: thin aioboto3 "kms" client wrapper
                   (GenerateDataKey / Decrypt on wrapped DEKs only — never called with field
                   plaintext, §2.1)
  keys.py       — DekCache: lazy-loads and TTL-caches plaintext DEKs by key_version (§2.1/§2.2),
                   backed by the encryption_keys registry
  field.py      — encrypt_field(plaintext: str, *, aad: str) -> str /
                   decrypt_field(ciphertext: str, *, aad: str) -> str — the one place AES-256-GCM,
                   the ciphertext format (§2.3), and AAD (§2.4) are actually applied. AAD is a
                   required keyword argument, not optional — there is no call form that skips it.
  types.py      — EncryptedOnWrite: a SQLAlchemy TypeDecorator implementing ONLY
                   process_bind_param (calls encrypt_field, computing AAD from the instance's own
                   primary key at flush time). process_result_value is NOT overridden — it returns
                   the raw ciphertext string unchanged, exactly as SQLAlchemy would for a plain
                   String column. Used for the three real columns
                   (employee.pan_number_enc, employee.aadhaar_number_enc,
                   employee_bank.account_number_enc).
```

**Decryption is never automatic, for any field, in any code path.** The only way to obtain plaintext
is an explicit call to `decrypt_field(...)` (or, for the three `TypeDecorator`-backed columns, a
service-layer helper that wraps it — e.g. `EmployeeBankService.decrypt_account_number(bank_row)`),
made **after** the calling code has already run the relevant permission check
(`EMPLOYEE.VIEW_BANKING`, etc.) — matching this plan's existing §12 item 4 requirement, now actually
satisfied by the type's own implementation rather than only stated as a rule engineers must
remember to follow elsewhere. A raw `session.get(EmployeeBank, id)` (or any other ORM load — a
background job, an admin console query, a future report) returns ciphertext in that attribute, full
stop, with no risk of an incidental plaintext leak through a code path that never intended to
decrypt anything.

`onboarding_case.bank_info` (JSONB) was never a `TypeDecorator` candidate in the first place
(inventory §4 item 2 — a JSONB dict has no per-key ORM hook) and continues to need explicit
`encrypt_field`/`decrypt_field` calls at the two service-layer boundaries named in §2.6/§7 — this
was already consistent with the corrected boundary model even in the first draft; only the three
real columns' `TypeDecorator` needed correcting.

**A `TypeDecorator` is used at all only for the write direction**, per the architecture review's own
allowance ("if a `TypeDecorator` is used at all, it must not cause automatic plaintext
materialization on read") — `EncryptedOnWrite` satisfies that literally: it decorates the bind
(write) side only.

### 2.6 Why encrypt-on-write still benefits from a `TypeDecorator`, decrypt still doesn't

A `TypeDecorator`'s write-side hook (`process_bind_param`) runs at flush time, when SQLAlchemy
already knows the target row's primary key (for an `INSERT`, the ORM-generated UUID is assigned
before flush in this codebase's convention — every model here sets `id=uuid4()` explicitly at
construction, not via a DB-generated default) — so AAD (§2.4) can be computed correctly at that
point without any extra plumbing, and every write path automatically encrypts without an engineer
having to remember to call `encrypt_field` manually (eliminates an entire class of "forgot to
encrypt this one write path" bug — the original, still-valid motivation for using a `TypeDecorator`
at all). The read side has no equivalent safety argument in its favor: an automatic decrypt on every
load is not "one fewer thing to remember," it is the exact behavior that removes the ability to
guarantee decryption only happens behind a permission check — so it is deliberately not implemented,
per §2.5.

---

## 3. Search requirements — explicit conclusion

**No deterministic lookup, sort, filter, join, or uniqueness requirement exists today for any of
the three DATA-01 fields** (inventory §6, verified by grepping every repository query-construction
site and every migration's index/constraint list). Consequently:

- **A blind index/HMAC is not recommended for this batch.** Building one would be pure speculative
  infrastructure against a requirement nothing in this codebase currently has — directly against
  this plan's own instruction not to introduce unneeded searchable encryption.
- **The one condition that would change this conclusion**: if a future requirement emerges to (a)
  detect duplicate PAN/Aadhaar numbers across employees within a tenant (a real-world HR concern —
  the same government ID should not belong to two active employee records), or (b) let payroll/HR
  search "find the employee with bank account ending in 7890." If and when that requirement is
  confirmed, the addition is additive and does not require touching the encryption design above:
  a separate `pan_number_hmac` (etc.) column, computed as `HMAC-SHA256(normalized_value,
  blind_index_key)` — a **key genuinely separate from the KMS-wrapped DEK** (compromising the
  blind-index key only enables equality-testing, never decryption; compromising the DEK should not
  also hand over the ability to test guesses against the blind index) — normalized (uppercase,
  whitespace-stripped) before hashing so `"ABCDE1234F"` and `"abcde1234f"` collide as intended,
  indexed with a standard B-tree index, and rotated by re-computing the HMAC column under a new key
  in a background job identical in shape to the re-encryption backfill this plan already specifies
  (§6). **Not implemented now** — this paragraph exists so the future implementer does not have to
  re-derive the design if the requirement does appear.

---

## 4. Data model strategy

**Recommended: Option A — reuse existing columns**, for all three field-level DATA-01 columns, plus
the new `encryption_keys` registry table (§2.2), plus one JSONB-key exception noted below.

| | Option A: reuse existing columns | Option B: new encrypted columns alongside | Option C: structured encrypted-value storage (e.g. a separate `pii_vault` table keyed by a reference id) |
|---|---|---|---|
| Migration safety | No `ALTER TABLE ADD COLUMN` needed at all for `pan_number_enc`/`aadhaar_number_enc`/`account_number_enc` (they're already `TEXT`, and the encrypted format is itself a string — §2.3 was deliberately designed to fit inside the existing column type) | Requires 3 new columns, then a cutover, then dropping the old ones later — three migrations instead of zero for the columns that already fit | Requires a wholly new table + FK + join on every read; a structural change to `BankRead`/`EmployeeRead` construction |
| Rollback | Trivial — nothing changed at the schema level, only what the application writes into the column | A failed cutover leaves two columns in an ambiguous state | A failed migration leaves an orphaned table and broken joins |
| Compatibility | The column's declared SQLAlchemy type is already `String`/`TEXT`; swapping the Python-side type to `EncryptedOnWrite` (still ultimately a `String` at the DB level) requires no `ALTER COLUMN TYPE` | New columns can coexist during a dual-write phase, at the cost of every read path needing "check new column, fall back to old" logic during the transition | Correctly isolates PII into one access-controlled table (a genuine security-architecture benefit at larger scale) but is disproportionate engineering for three fields on two tables |
| Indexing | No existing index to preserve or break — confirmed none exists (inventory §6) | Same | Would need its own index strategy independent of the owning table |
| Data length | AES-256-GCM ciphertext is plaintext length + 28 bytes (12-byte nonce + 16-byte tag) + the `v1:N:` prefix overhead (~10 bytes) + base64's ~33% expansion on the binary parts — for a ~10-18 character bank account number or a 10-character PAN, the encrypted form is comfortably under 100 characters. The columns are already unbounded `TEXT` — no length ceiling to hit | Same, but on a new column | Same |
| Null handling | `None` stays `None` — `process_bind_param` special-cases `None` as a no-op, exactly matching every field's current `nullable=True` behavior | Same | Same, plus a "no vault row exists yet" state to handle |
| Legacy records | None exist for `pan_number_enc`/`aadhaar_number_enc` (dormant, confirmed zero writers). `employee_bank.account_number_enc` and `onboarding_case.bank_info` **may** already hold real-shaped plaintext values if any real tenant has been onboarded since E-08 shipped — the backfill (§6) is required precisely because Option A does not distinguish "old plaintext row" from "new ciphertext row" except by the `v1:` format prefix itself, which **is** the distinguishing signal the backfill script uses | Same distinction available via "is the new column populated yet" instead of a format-prefix check — marginally simpler to reason about, at the cost of the migration overhead above | Same |
| Deployment sequencing | Single deploy: ship `hrms/core/crypto/` + the `encryption_keys` registry + `EncryptedOnWrite`, then run the backfill (§6) as a separate, monitored step — no coordination between two column names required | Requires coordinating "write to both columns" deploy, then "read from new column" deploy, then "drop old column" deploy — three sequenced releases for a gain Option A gets in one | Same multi-release sequencing, plus the new table's own migration |

**The one necessary exception: `onboarding_case.bank_info`.** This is not a column-type swap
question at all (inventory §4) — it is a JSONB dict where exactly one key (`account_number_enc`,
matching `BankInfoSection`'s field name) needs field-level encryption applied/removed at the
service-layer boundaries named in §2.5/§7, and, per §9, an explicit post-activation clearing step.
"Option A vs B vs C" doesn't cleanly apply to a JSONB blob; treat this as its own, small,
explicitly-named implementation item rather than folding it silently into the column-level
`TypeDecorator` work.

**Recommendation: Option A for the three columns, a new `encryption_keys` table (§2.2, unavoidable —
envelope encryption has nowhere else to record wrapped DEKs), plus the explicit JSONB-key treatment
for `onboarding_case.bank_info`.** Reasoning: this repository's own architectural invariants already
favor minimal-diff, additive changes (`HRMS_SYSTEM_DESIGN_BASELINE.md` §20's own invariants:
"additive only... no data to transform or lose" is the pattern every migration in this codebase
already follows), the fields in question are small opaque strings with no indexing/length pressure,
and Option B/C's main advantage (a clean "old vs. new" distinction) is available for free under
Option A anyway, via the ciphertext format's own `v1:` prefix (§2.3), which is precisely what lets
the backfill (§6) run safely without a parallel-column scheme.

---

## 5. Key management

### 5.1 What already exists in this repository

- **No KMS integration exists today** (confirmed: zero references to `kms` anywhere in
  `apps/api/src`).
- **AWS is the established, already-adopted cloud provider** — not an assumption this plan is
  introducing. `env/.env.production.example`/`.env.staging.example`/`.env.dev.example` all document
  AWS Secrets Manager for JWT/database secrets (per `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own
  SEC-01 remediation, which this plan's `ENVIRONMENT=`/secret-injection convention directly
  extends), `aioboto3` is already a pinned dependency used for S3/MinIO document storage
  (`core/storage.py`), and `Settings` already carries `aws_region`/`aws_access_key_id`/
  `aws_secret_access_key`/`s3_endpoint_url` fields. **AWS KMS is the natural, lowest-new-risk
  choice** — it reuses the exact same IAM/credential/region configuration surface the application
  already depends on for S3, rather than introducing a second cloud vendor's SDK and credential
  model.
- **Local development** already runs against MinIO (an S3-compatible server) via
  `s3_endpoint_url=http://localhost:9000` for document storage — there is **no equivalent
  KMS-compatible local emulator** in the existing docker-compose setup. This is decided explicitly
  below (§5.4), not silently assumed.

### 5.2 Proposed master-key structure

- **One customer-managed KMS key (CMK) per environment** (`hrms-pii-encryption-staging`,
  `hrms-pii-encryption-production`) — not shared with any other purpose (not the same key
  protecting, say, S3 bucket encryption, if that is ever enabled) so this key's access policy and
  audit trail stay scoped exactly to PII field encryption and nothing else. Wraps that environment's
  application DEK(s) only (§2.1) — never called against field plaintext directly.
- **Not per-tenant.** This system is not currently multi-key-per-tenant anywhere (the JWT signing
  secrets, the database credentials, and every other secret are environment-wide, per
  `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own SEC-01 model) — introducing per-tenant KMS keys
  would be a materially larger architecture change than DATA-01's own scope, and nothing in the
  audit or this codebase's existing tenancy model calls for it. If a specific enterprise customer's
  contract someday requires a dedicated key (a real, if currently hypothetical, possibility for a
  B2B HR SaaS), that is an additive change on top of this design (a per-tenant DEK, wrapped by the
  same environment CMK, is a natural extension of the registry shape in §2.2), not a redesign.
- **IAM policy shape**: the application's own IAM role/ECS task role gets `kms:GenerateDataKey` (used
  only when establishing a new DEK — initial provisioning or rotation, §10) and `kms:Decrypt` (used
  whenever an existing `wrapped_dek` needs to be resolved into a plaintext DEK, §2.1/§2.2) on this
  one key's ARN only — explicitly **not** `kms:*`, not `kms:CreateKey`/`kms:ScheduleKeyDeletion`/
  `kms:PutKeyPolicy`/`kms:DisableKey` (key administration and deletion protection are a separate,
  human/CI-pipeline-only IAM principal, never the running application — this separation is also the
  main defense against accidental key deletion, §12).

### 5.3 Rotation and versioning

See §10 for the full rotation procedure (KMS CMK automatic rotation and application-level DEK
rotation are two distinct, independently-operating mechanisms — both specified there in detail per
the architecture review's own required outline).

### 5.4 Local development

**Recommendation: a development-only encryption implementation, not a call to real AWS KMS from a
laptop.** Concretely: `Settings` gains an `environment`-gated switch (mirroring the existing
`is_development` pattern already used throughout `Settings`) — in `development`, the DEK cache
(§2.1) is seeded from a **local, fixed, clearly-fake key** (e.g. a `Settings.dev_encryption_key`
field with an obvious placeholder default, the same posture as `jwt_access_secret`'s development
default before `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s SEC-01 guard) rather than resolving
anything through a real `encryption_keys` row or a real KMS call. This:

- keeps local `docker-compose up` fully offline-capable, matching every other local-dev dependency
  in this repository (Postgres/Redis/MinIO all run locally; nothing today requires reaching a real
  AWS endpoint to run tests);
- is safe specifically because — per SEC-01's own guard, which this plan reuses rather than
  reinvents — a development-only key/mode must be **structurally incapable of running in
  `staging`/`production`** (§10's boot-guard requirement: the same "reject the known default outside
  development" validator pattern SEC-01 already established for JWT secrets applies verbatim here);
- **staging and production both call real AWS KMS and use a real `encryption_keys` registry** — no
  "staging uses a simpler scheme" carve-out, since staging is explicitly described elsewhere in this
  repository (`env/.env.staging.example`'s own header comment) as "a production mirror... where
  pilot customers and the client sign off before go-live" — the encryption path is exactly the kind
  of thing that must be proven in staging, not first exercised in production.

### 5.5 Failure behavior when KMS is unavailable

- **Write path**: if KMS is unreachable when a DEK needs to be freshly resolved (a cache miss — the
  common write path, once a DEK is cached, needs no KMS call at all), the write must **fail closed**
  — return an error to the caller rather than silently persisting plaintext (the one behavior this
  plan must never allow) or silently skipping encryption.
- **Read path**: if KMS is unreachable during a DEK cache miss on read, the specific field read
  fails (surfaces as an error on that one field/response), but this must **not** take down the
  entire employee-profile or bank-details response if other, non-encrypted fields on the same
  resource are still requested — i.e. a KMS outage degrades to "banking details temporarily
  unavailable," not "the whole employee record 500s." (Concretely: the decrypt call in the service
  layer should be wrapped so a KMS failure raises a distinct, named exception the router layer maps
  to a `503`-shaped response for just that resource, not an unhandled 500 — the exact code shape
  lands in the implementation batch, not this planning document.) Note the DEK cache (§2.1) means
  this failure mode is rarer in practice than "every read calls KMS" would suggest — it only occurs
  on a cache miss, not on every request.
- **This is a new, DATA-01-specific failure policy — not a re-statement of `SEC-11`.** `SEC-11`
  (rate-limiter Redis-outage behavior, tracked separately per
  `PRODUCTION_HARDENING_BATCH_1_REPORT.md`) is an unrelated dependency (Redis, not KMS) protecting an
  unrelated concern (request throttling, not data confidentiality) — this plan does not touch or
  reference `SEC-11`'s own remediation.

### 5.6 Backup and disaster-recovery implications of the key strategy

Covered in full in §12/§13; the load-bearing requirement this key-management design must satisfy is
stated once, here, because it drives every other decision above: **a PostgreSQL backup, snapshot, or
restored copy must not, by itself, grant the ability to read PII in plaintext** — only when paired
with the ability to call `kms:Decrypt` against the specific KMS key (a distinct AWS IAM/KMS-policy
control, not a database credential) does the backup become readable. This is precisely what §2.1's
envelope design + a KMS CMK never stored anywhere in the database or its backups (§2.3's format only
ever stores a `key_version` integer, never key material, wrapped or otherwise) achieves.

---

## 6. Existing-data migration / backfill strategy

### 6.1 Discovery

Before writing any backfill code, the implementing batch's first step must run a **read-only** query
against each of the four locations to establish the actual current row count and whether any already
hold real (non-synthetic) data:

```sql
SELECT count(*) FILTER (WHERE pan_number_enc IS NOT NULL) AS pan_rows,
       count(*) FILTER (WHERE aadhaar_number_enc IS NOT NULL) AS aadhaar_rows
FROM employee;

SELECT count(*) FILTER (WHERE account_number_enc IS NOT NULL) AS bank_rows
FROM employee_bank;

SELECT count(*) FILTER (WHERE bank_info -> 'account_number_enc' IS NOT NULL) AS onboarding_bank_rows
FROM onboarding_case;
```

Per inventory §2, the first two are expected to return `0` in every real environment (no write path
has ever existed) — if either is nonzero in a real (non-dev, non-seed) database, that is itself a
finding to report before proceeding, not something to silently backfill over.

### 6.2 A value is either already encrypted or plaintext — distinguished by the format prefix

Because §2.3's ciphertext format always begins with a literal `v1:` (a string that a real bank
account number or PAN would essentially never collide with — those are exactly 10 or 9-18
alphanumeric characters respectively, never containing a colon), the backfill can classify every
existing non-null value with a single, cheap check: does it match `^v1:\d+:`? If yes, already
migrated (idempotent — see §6.7); if no, plaintext requiring encryption. **This is the mechanism
that makes the backfill safe to interrupt and re-run without a separate "migration status" column or
table** — the data itself carries its own migration state.

### 6.3 Batching, transaction boundaries, retry

- Process each of the three live tables (`employee`, `employee_bank`, `onboarding_case`)
  independently, in batches of a few hundred rows ordered by primary key (`id`), each batch in its
  own transaction: `SELECT ... WHERE <format-check indicates plaintext> ORDER BY id LIMIT 500 FOR
  UPDATE SKIP LOCKED`, encrypt each row's relevant column(s) in the application process — computing
  each row's own AAD (§2.4) from its own primary key, using whichever DEK is currently cached/
  resolved (§2.1; a DEK cache miss during the backfill's first batch is expected and calls KMS
  exactly once for the run, not once per row) — then `UPDATE` each row and `COMMIT` the batch.
- `FOR UPDATE SKIP LOCKED` specifically so the backfill job can run **concurrently with normal
  application traffic** without blocking a live write to a row it hasn't reached yet, and without the
  backfill and a live request racing to update the same row (whichever gets the row lock first wins;
  the other's `SKIP LOCKED` clause simply defers that row to the next batch pass).
- On any error mid-batch (a KMS transient failure, a serialization conflict), roll back that one
  batch's transaction and retry it with backoff — already-committed prior batches are untouched, so a
  retry never double-encrypts a row (§6.7).

### 6.4 Idempotency

Guaranteed structurally, not by a separate "already processed" bookkeeping table: re-running the
entire backfill script against a fully-migrated table is a no-op, because every row's format-prefix
check (§6.2) already says "not plaintext" — the `WHERE` clause in §6.3's batch query naturally
selects zero rows. This is what makes the backfill safely resumable after a partial failure, process
restart, or deliberate pause, with no separate progress-tracking mechanism to build, test, or get
wrong.

### 6.5 Progress tracking and resumability

Because idempotency (§6.4) is structural, "progress" is simply "how many plaintext-format rows
remain," directly observable at any time by re-running the discovery query (§6.1) — no bespoke
progress table is needed. The batch job should `structlog`-log (matching this codebase's existing
observability convention) a per-batch summary (`rows_processed`, `table`, `key_version`, elapsed
time) — **the row's own field value, and its AAD string (which embeds the row's own id but never
the plaintext), must never appear in this log line beyond counts and identifiers** (§8/§11).

### 6.6 Verification

After a backfill pass reports zero remaining plaintext rows (§6.1's discovery query returning zero
for the plaintext-pattern check), verify **decryption**, not just "the format looks right": for every
migrated row (or a statistically meaningful sample on a very large table — not expected to be
necessary at this system's actual scale, inventory §2.2), decrypt the new ciphertext value (using its
recorded `key_version` and recomputed AAD, §2.2/§2.4) and compare it against a **pre-migration
snapshot of the plaintext** taken during discovery (§6.1) — not against the ciphertext round-tripping
through the same encrypt/decrypt code (that would only prove the code is internally consistent, not
that it faithfully preserved the original value). This snapshot must itself be handled carefully:
held only in-memory or in a short-lived, access-restricted temporary location for the duration of the
verification pass, never written to a permanent log or file, and discarded immediately after the
comparison completes.

### 6.7 Partial failure

Because each batch commits independently (§6.3) and idempotency is structural (§6.4), "partial
failure" simply means the discovery query (§6.1) still reports some plaintext rows after a run —
re-running the backfill picks up exactly where it left off. No special partial-failure handling code
is required beyond ordinary retry-with-backoff on the batch loop itself.

### 6.8 When plaintext can safely be removed — and the two different meanings of "remove" here

**This plan does not propose deleting plaintext before ciphertext is verified — and for the three
real columns, "removing plaintext" does not mean deleting a row at all:**

- For `employee.pan_number_enc`/`.aadhaar_number_enc`/`employee_bank.account_number_enc`: the
  backfill **overwrites the same column in place** (§4's Option A) — there is no separate "plaintext
  copy" left lying around once the `UPDATE` in §6.3 commits and is verified (§6.6). The only way
  plaintext could still exist afterward is in a database backup taken *before* the backfill ran —
  addressed by §13, not by this section (encrypting live rows does not retroactively encrypt an old
  backup; only DR-procedure controls, and eventual backup-retention expiry, address that). **This
  specific "never null out a real column's ciphertext" rule is unrelated to, and does not conflict
  with, §9's separate decision to clear the `account_number_enc` *key* out of the
  `onboarding_case.bank_info` JSONB dict after activation** — that is a distinct, deliberate
  data-lifecycle decision about a different table, made explicitly in §9, not an accidental
  contradiction of this paragraph.
- For `onboarding_case.bank_info`: this location needs its *own* backfill pass (same batching/
  idempotency shape, applied to the one JSONB key inside `bank_info`, per §4's noted exception), run
  as its own explicit step, not assumed to be covered by the `employee_bank` pass — and, per §9, is
  the one location where the sensitive key is *later* deliberately cleared after activation, as a
  separate, subsequent step from the backfill itself.

### 6.9 Zero-downtime feasibility and staged sequence

**Zero-downtime is achievable**, because Option A (§4) means the column's SQL type never changes
(still `TEXT`/`JSONB`) — only what the *application* writes into it changes. The staged sequence:

| Phase | What happens | Downtime? |
|---|---|---|
| **A — Preparation** | Ship `hrms/core/crypto/` (§2.5), the `encryption_keys` migration (§2.2, empty table), the `EncryptedOnWrite` `TypeDecorator`, the KMS IAM policy (§5.2) provisioned in staging and production, the dev-mode local key path (§5.4), and the SEC-01-style boot guard that refuses to start in `staging`/`production` without a real KMS key and at least one `ACTIVE` `encryption_keys` row (§10 gate list). **No column yet uses the new type** — this phase is pure new-code-path-exists, old-path-still-runs. | None |
| **A′ — Initial key provisioning** | Run the one-time initial-provisioning procedure (§10): create the CMK (if not already created), call `GenerateDataKey` once, insert the first `encryption_keys` row (`key_version = 1`, `status = 'ACTIVE'`). A prerequisite for Phase B, not a separate deploy. | None |
| **B — Encrypt-only writes, controlled decrypt reads** | Wire `EncryptedOnWrite` onto the three real columns and the explicit encrypt/decrypt calls onto `onboarding_case.bank_info`'s one key. From this deploy forward, **every new write is encrypted**; every authorized read path explicitly decrypts whichever format it finds (the `v1:` prefix check, §6.2, lives inside the decrypt helper, so an old plaintext row and a newly-encrypted row are both handled correctly, with no separate code path needed per row). This is the one deploy that must ship before the backfill runs. | None — reads and writes both keep working throughout |
| **C — Backfill** | Run the batched backfill (§6.1-§6.7) against all four locations. Safe to run at any time after Phase B ships, concurrently with live traffic, and safe to pause/resume. | None |
| **D — Verification** | §6.6's snapshot-comparison pass, plus re-running discovery (§6.1) to confirm zero remaining plaintext-format rows across all four locations. | None |
| **E — Audit-log redaction wired** | §7's redaction mechanism ships (may ship alongside Phase B — it does not depend on the backfill — called out as its own phase so it is not silently skipped). | None |
| **F — Onboarding cleanup enabled** | §9's post-activation clearing of `onboarding_case.bank_info` begins taking effect for newly-activated cases. Requires the product/compliance sign-off named in §9 before enabling in production. | None |
| **G — Historical audit remediation (conditional)** | Only if approved per §8's sign-off gate — a separate, explicitly scheduled, backed-up, monitored run against `audit_log`. Not part of the standard rollout sequence. | None (application); the remediation job itself is the risk surface, mitigated per §8 |
| **H — Enforcement** | The boot guard from Phase A is what makes this permanent — a future deploy cannot silently regress to plaintext writes, because there is no code path left that writes anything *but* through `EncryptedOnWrite`/the explicit encrypt call. | None |

No phase requires taking the API offline. The only sequencing rule that matters: **Phase B must be
fully deployed before Phase C (the backfill) starts** — running the backfill against a deployment
that doesn't yet know how to decrypt the `v1:` format would immediately break every read of a
just-migrated row.

---

## 7. Audit-log protection — mandatory, reusable redaction (resolves blocker 5)

**This is now a mandatory DATA-01 requirement**, not a recommended fast-follow. The current pattern
— `bank_to_audit_dict()` = `bank.model_dump(mode="json")`, passed whole to `AuditService.record()`
(inventory §3 item 13) — puts the full plaintext account number into every `BANK_REVISED` audit row,
permanently, in an architecturally-immutable table (`HRMS_SYSTEM_DESIGN_BASELINE.md` §20 invariant
#8). Shipping field-level encryption (§2) without fixing this would leave the exact same secret
sitting in plaintext one table over — DATA-01 is not complete without this.

### 7.1 Reusable mechanism

A single, named redaction helper in `hrms/core/audit/` (alongside `AuditLog`/`AuditService`, the
only layer both `employee` and `onboarding` already depend on for audit recording):

```text
hrms/core/audit/
  redact.py  — mask_sensitive(payload: dict[str, Any], *, sensitive_fields: dict[str, MaskFn])
               -> dict[str, Any]
             — SENSITIVE_FIELD_MASKS: dict[str, MaskFn], a registry (not a hardcoded list inside
               one function) mapping field name -> masking function, so a future sensitive field
               (statutory pf_number/esi_ip_number, if that follow-up is ever scoped — inventory §5)
               registers itself here rather than requiring a new bespoke redaction function.
```

- `mask_account_number(value: str) -> str` — last-four-digit convention already documented as this
  system's product intent (inventory §8: `"Bank account: ******7890"`), applied to the **plaintext**
  value before it is encrypted (on write) or immediately after it is decrypted for audit purposes
  (on a path that needs the "before" state) — the masked string, never the full plaintext and never
  the ciphertext blob, is what reaches `AuditService.record()`.
- `mask_pan(value: str) -> str` — `"ABCDE****F"` (first 5 + last 1 shown, matching the documented
  format exactly).
- `mask_aadhaar(value: str) -> str` — `"XXXX XXXX 1234"` (last 4 digits only, matching the documented
  format exactly).
- Registry keys match the field names already used throughout this codebase (`account_number_enc`,
  `pan_number_enc`, `aadhaar_number_enc`) — applied by field name, not by table, so the same registry
  covers `employee`, `employee_bank`, and (when/if it ever gets its own audit call) `onboarding_case`
  without duplicating the mapping.

`bank_to_audit_dict()` (`employee/schemas.py:581-582`) is changed to call `mask_sensitive(bank.
model_dump(mode="json"), sensitive_fields=SENSITIVE_FIELD_MASKS)` instead of returning the raw dump
— a small, mechanical change once `mask_sensitive` exists, and the model every future `*_to_audit_dict()`
function (an eventual `employee_to_audit_dict()` for PAN/Aadhaar once E-02 ships a write path,
per inventory §2's own noted forward-looking risk) should follow from day one rather than
re-introducing the same gap this section closes.

### 7.2 Where masking happens — never after the fact

Masking must happen **before** the dict reaches `AuditService.record()`, in the same request that
performs the write — never as a later, separate "scrub the audit table" pass for *new* rows (that
class of fix is §8's territory, and only for pre-existing rows). This keeps the audit table's own
immutability invariant intact: nothing is ever written and then edited; the masked form is simply
what gets written in the first place, from this point forward.

### 7.3 Ensuring future PAN/Aadhaar encryption work doesn't regress this

Because `SENSITIVE_FIELD_MASKS` is a named, imported registry (not inline logic duplicated per
`*_to_audit_dict()` function), the moment E-02 (PAN/Aadhaar write path, still unbuilt — inventory §2)
ships and needs its own `employee_to_audit_dict()`, the masking requirement is already visible at
the call site (`mask_sensitive(..., sensitive_fields=SENSITIVE_FIELD_MASKS)` is the obvious, minimal-
effort correct call, not an opt-in a future engineer has to remember to add) — and `pan_number_enc`/
`aadhaar_number_enc` are already registered in `SENSITIVE_FIELD_MASKS` from this batch, even before
E-02 exists, specifically so that future slice cannot forget to redact them.

---

## 8. Historical audit-log remediation (resolves blocker 6, part 1)

`audit_log` rows written before this batch ships already contain plaintext bank-account numbers
(every `BANK_REVISED` row since E-08 shipped, inventory §3 item 13). §7 stops new rows from
containing plaintext; this section addresses the rows that already do. **This must be an explicit
production decision, not silently resolved by this document** — the analysis below evaluates the
three options the task names and states a default recommendation, but execution requires a named
sign-off (§14 gate).

### 8.1 Detection

Reuse the same format-prefix distinguishing trick as the field-level backfill (§6.2): a JSONB
sub-query against `audit_log.before_json`/`after_json` for `entity_type = 'EmployeeBank'` (or
wherever `bank_to_audit_dict()`'s payload landed) where the `account_number_enc` key's value does
**not** match `^v1:\d+:` — i.e. still plaintext-shaped. PAN/Aadhaar have no write path yet (inventory
§2), so no historical audit rows exist for those fields — this remediation is scoped to bank-account
audit rows only, unless discovery (§6.1-style, run against `audit_log` specifically) finds otherwise
in a real environment.

### 8.2 Affected rows

Determined at execution time by the detection query above, per environment — not estimated here,
since it depends on real production `audit_log` volume this planning pass has no access to. The
detection query itself is the first step of the remediation run, and its row count is the first line
of the remediation's own closeout report.

### 8.3 Backup considerations

Because this remediation **mutates** rows in a table whose own architectural invariant is
immutability (`HRMS_SYSTEM_DESIGN_BASELINE.md` §20 #8), it is itself a deliberate, approved exception
to that invariant — requiring a documented change-control record, not just an ordinary deploy. Before
running: take a full, access-restricted export/snapshot of the affected `audit_log` rows (not the
whole database — scoped to what's being changed) and retain it only under the organization's existing
sensitive-data retention/access policy, for exactly as long as legally/operationally required to prove
the remediation was correctly applied — never as an ordinary "restore point" (restoring it would
reintroduce the exact plaintext this remediation exists to remove).

### 8.4 Remediation strategy — evaluated

- **Option A — redact existing plaintext values in audit rows.** Run a small, idempotent, one-time
  job: for each row the detection query (§8.1) flags, `jsonb_set()` the sensitive key(s) inside
  `before_json`/`after_json` to the masked form (§7.1's same `mask_account_number`, applied once,
  historically, to the value already in the row — not re-derived from a live encrypted value, since
  the point is to remove the plaintext that's already there) — never deletes the row, never touches
  any other field on it (`action`, `occurred_at`, `actor_user_id`, etc. all untouched).
- **Option B — keep historical rows unchanged, formally accept as residual exposure.** Requires a
  written risk acceptance (who signed off, when, why) — legitimate if, e.g., the affected row count
  is verified zero (no real tenant ever triggered a bank write before this batch) or if a compliance
  review determines the historical exposure is already covered by an existing incident-response/
  access-control posture.
- **Option C — a separate, controlled remediation mechanism**, for any row whose JSON structure
  doesn't match what Option A's `jsonb_set()` assumes (e.g. a `before_json`/`after_json` from a
  pre-`BankRead`-shape version of the payload, or a malformed/partial dump from an old bug) — such
  rows are **not** blindly rewritten (per this task's own instruction: "do not assume that every
  historical audit JSON structure can be safely rewritten"). They are instead flagged by the
  detection query as "does not match expected shape" and routed to manual review rather than
  automated `jsonb_set()`, with the manual-review outcome (redact by hand, or explicitly accept)
  recorded the same way Option B's sign-off is.

**Default recommendation: Option A for every row whose JSON matches the expected `BankRead`-derived
shape exactly; Option C (manual review, not automated rewriting) for any row that doesn't; Option B
only as an explicit, signed-off fallback if remediation is deferred.** This favors eliminating
plaintext where it is technically safe to do so (matching the task's own stated default) without
assuming uniform structure across every historical row.

### 8.5 Verification

After remediation runs, re-run the detection query (§8.1) and confirm zero plaintext-shaped values
remain among the rows processed; separately confirm the "does not match expected shape" bucket (if
non-empty) has a recorded manual-review disposition for every row in it, not just the ones that were
auto-redacted.

### 8.6 Rollback limitations

**This remediation does not have an ordinary rollback.** Because its entire purpose is to
irreversibly destroy plaintext that should never have persisted, "rolling back" the redaction would
mean restoring the plaintext — the opposite of what compliance requires. The only recovery path is
the pre-remediation backup named in §8.3, and that backup itself must be treated as a sensitive,
time-limited artifact, not a routine restore point. This is disclosed explicitly here, per this
plan's own instruction not to understate rollback limitations: **once §8.4's redaction runs and is
verified, the original plaintext audit values are gone, by design, and that is irreversible outside
of the narrowly-scoped, access-controlled backup.**

### 8.7 Sign-off gate

Per this task's explicit instruction ("do not silently make the product decision"), executing §8.4
against a real staging or production `audit_log` table requires named sign-off from a
product/compliance owner before it runs — listed as its own item in §14's production safety gates
and §15's implementation checklist. This document specifies the strategy; it does not authorize
running it.

---

## 9. `onboarding_case.bank_info` lifecycle after activation (resolves blocker 6, part 2)

Per inventory §4 item 5: after `OnboardingService.activate_case()` successfully constructs a
`BankCreate` from `case.bank_info` and persists it into `employee_bank` (§3 of the inventory), the
application **never reads `onboarding_case.bank_info` again** — confirmed by inventory §4's own
end-to-end trace, and unaffected by anything else in this plan. Leaving the sensitive key there
forever means the same plaintext-shaped-then-encrypted value keeps existing in two independent
storage locations indefinitely, for a value the second location has no further legitimate use for.

### 9.1 Preferred design

**After successful activation, and only after the `employee_bank` insert is confirmed persisted,
clear the `account_number_enc` key out of `onboarding_case.bank_info`** (the other, non-sensitive
keys in the same JSONB dict — `bank_name`, `branch_name`, `payment_mode`, `account_holder_name`,
`ifsc` — are not part of DATA-01's scope, inventory §1, and are left untouched; only the one sensitive
key is removed).

**Atomicity**: this clearing step must happen in the **same database transaction** as the
`employee_bank` insert performed by `EmployeeBankService.create_bank()` during activation — not a
separate, subsequent, un-transacted write. Two independent writes would create a window where a
crash between them leaves `employee_bank` populated but `onboarding_case.bank_info` still holding
its (by then redundant) encrypted copy — not incorrect, but not the guarantee this design intends
either. A single transaction means either both happen or neither does; a retried activation attempt
after a rollback re-runs both steps from the same source data.

**Idempotency**: clearing a key that is already absent (a retried activation, or a case activated
under a version of the code before this step existed) is a no-op, not an error — `dict.pop(key,
None)`-shaped semantics, matching this plan's general preference for structural idempotency over
bookkeeping (§6.4's same principle applied here).

### 9.2 The retention alternative — an explicit decision point, not silently decided here

Per this task's own instruction ("do not silently make the product decision"): if a product or
compliance owner determines the onboarding case record should retain a historical copy of the bank
information submitted (e.g. for dispute resolution — "what did the candidate actually type into the
wizard" — a real, if currently unconfirmed, business need this plan cannot rule out), the alternative
is:

- **Do not clear the key.** Instead, ensure it remains **encrypted** (§2, exactly as it already will
  be from Phase B of §6.9 onward) — the current, unresolved gap this plan closes either way is "the
  value sits there in plaintext forever," not "the value sits there at all." Under this alternative,
  the ciphertext simply persists in `onboarding_case.bank_info` alongside its independent, separately-
  encrypted copy in `employee_bank`, with no further application code needed beyond what §2/§6
  already ship.
- This alternative changes nothing about §2's encryption design, §6's backfill, or §7's audit
  redaction — it only changes whether §9.1's clearing step is enabled.

### 9.3 Default recommendation and the decision point

**Default recommendation: clear (§9.1).** Rationale: inventory §4's own conclusion is that this
location, once encryption ships, becomes a second, purely-redundant at-rest copy of a secret with a
single legitimate consumer (activation) that has already run by the time any clearing would occur —
minimizing the number of places a secret persists is a defensible default absent a stated business
reason to keep it. **This is a default, not a unilateral decision** — enabling §9.1 in production
(Phase F, §6.9) requires the same named product/compliance sign-off gate as §8.7, listed in §14/§15,
specifically because "should we retain this data" is a product/compliance question this planning
document is not positioned to answer on its own, per this task's explicit instruction.

---

## 10. Key rotation

### 10.1 KMS CMK rotation

Enable **AWS KMS's built-in automatic annual rotation** for the CMK (§5.2), per the environment's
selected production policy, from day one — a single IAM/console setting, not an engineering task. AWS
KMS keeps prior key material available for decrypting data encrypted under earlier rotations of the
same CMK automatically — this layer requires **no application change and no re-encryption** when it
fires; it is transparent to the `wrapped_dek` values stored in `encryption_keys` (a `wrapped_dek`
remains a valid `kms:Decrypt` target across a CMK's own internal rotation, by KMS's own design).

### 10.2 Application DEK rotation

A distinct, application-level procedure — creating a new `key_version` in the registry, not a KMS
setting:

1. Generate a new DEK via `kms:GenerateDataKey` against the environment's CMK.
2. The DEK arrives already wrapped by KMS (`CiphertextBlob`) — no separate wrap step.
3. Insert a new `encryption_keys` row: next `key_version`, this `wrapped_dek`, `status = 'ACTIVE'`.
4. In the same transaction, flip the previously-`ACTIVE` row to `status = 'RETIRED'`,
   `retired_at = now()`.
5. New writes use the new DEK immediately (the next cache resolution of "the current version" picks
   up the new row; §2.1's TTL bounds how long any in-flight process keeps using the old version as
   "current" for new writes — acceptable, since old-version writes are still valid ciphertext, just
   under a version that will itself be retired soon).
6. **Existing records continue using their recorded key version** — no row's `key_version` changes as
   a side effect of rotation; decrypting an old row still resolves and uses the old (now `RETIRED`,
   but never deleted) DEK exactly as before.
7. **Old DEKs remain available for decryption** — `RETIRED` rows are permanent, per §2.2; rotation
   never requires "the entire database" to be decrypted, migrated, or become briefly unreadable.
8. **Optional background re-encryption** can migrate old records to the new key version later,
   identical in shape and safety properties to §6's backfill (batched, `SKIP LOCKED`, idempotent via
   the same `key_version`-comparison logic, resumable) — genuinely optional, not required for
   correctness, since old records remain fully decryptable under their original version indefinitely.
   Recommended only if there's a concrete reason to reduce the number of live `RETIRED` versions
   (e.g. a compliance-driven "re-encrypt everything under the newest key within N days of rotation"
   policy) — not a default requirement of this plan.

### 10.3 Boot guard

`staging`/`production` must refuse to start without: a real (non-development) KMS CMK configured,
and at least one `ACTIVE` row in `encryption_keys` — reusing the exact `model_validator`-based
guard pattern `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s SEC-01 already established for JWT secrets,
not inventing a new one.

---

## 11. Security threat model

| Threat | Protection this design provides | Residual risk | Mitigation |
|---|---|---|---|
| Database dump compromise | Ciphertext + a `key_version` integer only; plaintext requires a separate, live, IAM-scoped `kms:Decrypt` call the dump alone cannot make | An attacker who also compromises the application's IAM credentials/role gets both | IAM scoping (§5.2) as tight as possible; credential compromise is a broader incident-response concern this plan cannot solve alone |
| Database write/tampering (an attacker or bug with direct SQL write access modifies a ciphertext value or overwrites it with different valid-looking ciphertext) | GCM's authentication tag detects any bit-level tampering of the ciphertext or nonce (§2.3); AAD (§2.4) additionally detects a *structurally valid* ciphertext moved to the wrong row | A tampered/substituted value that also somehow reused the exact same AAD-bound row would not be caught by AAD alone — but doing so requires already controlling the specific row's own id, which is a database-write-access scenario the threat already assumes | Row-level write access controls (application RBAC, DB-user least privilege) — not a DATA-01 control, named because AAD's guarantee is scoped precisely to "wrong row," not "any write" |
| Ciphertext substitution (copying a valid ciphertext from one row into another) | **Directly prevented by AAD (§2.4)** — decrypting under the receiving row's own recomputed AAD fails authentication, since it differs from the AAD used at the original encryption | None within this design's scope | N/A — this is the specific gap AAD closes |
| Backup compromise | Same as database dump compromise (§13) | Same | Same, plus the DR-runbook discipline named in §13 |
| SQL read access (e.g. a support engineer with a read replica) | Sees ciphertext only | Same as above | Same |
| Application log leakage | No plaintext value is ever passed to a log call under this design (§5.5's failure-path logging explicitly excludes the value; §6.5's backfill logging is counts-only; §7's audit masking ensures the masked, not the plaintext, form is what any audit-adjacent log would ever show) | A future engineer adds a debug `log.info(f"bank: {value}")` — a code-review/lint concern, not something the encryption design alone prevents | Recommend (not must-have for DATA-01): a `ruff`/custom lint rule or code-review checklist item flagging any log call referencing these field names by name — a process control, out of this plan's own scope to implement |
| Audit-log leakage | §7's mandatory redaction ensures every *new* audit row carries a masked value only | **Historical rows written before §7 ships remain plaintext until §8's remediation runs and is verified** — an explicit, named residual risk, not hidden | §8's remediation procedure, gated on production sign-off (§8.7) |
| Unauthorized API access | Unchanged from today's RBAC gating (§14) — DATA-01 does not widen or narrow who can call the existing routes | If RBAC itself has a gap (none found for these specific routes in this inventory), encryption does not compensate for it | Out of scope — RBAC changes are explicitly excluded from this batch |
| Insider access (an engineer with production DB access but no KMS grant) | Cannot decrypt | An engineer with **both** DB and KMS access can | Least-privilege IAM discipline (§5.2) — organizational control, not a code control |
| Compromised application server | **Encryption does not solve this.** A compromised app server holds the running process's own IAM credentials and its already-cached plaintext DEK(s) (§2.1), and can call KMS `Decrypt`/`GenerateDataKey` exactly as the legitimate application does — this is a fundamental limitation of application-level encryption with a live decrypt path, not a gap specific to this design. **Explicitly documented, as required**: this design does not protect against a fully compromised application server that can legitimately request decryption. | Full server compromise defeats essentially any at-rest control; this is named explicitly per this task's own instruction not to claim otherwise | Out of scope for DATA-01 — belongs to broader infrastructure-hardening (`OPS-04` container hardening, least-privilege task IAM roles, network segmentation) |
| Stolen environment configuration (e.g. leaked `.env`) | The KMS key identifier alone (which is what `Settings` would hold) grants nothing without the IAM role's own credentials also being compromised — unlike the JWT-secret case (`SEC-01`), the "secret" here is not a value `Settings` holds directly, it's an AWS-side permission grant | If the leaked config includes real AWS access keys (as opposed to an ECS task role, the recommended production posture per `env/.env.production.example`'s own stated convention), those keys likely also carry the KMS grant | Reinforces `env/.env.production.example`'s existing "never static keys in production — the ECS task role provides access" convention — already established, not new to this plan |
| KMS compromise | Out of this application's control — a KMS-service-level compromise (vs. an IAM-credential leak) is an AWS-platform-level incident, not something a customer application can mitigate directly | Total | AWS's own KMS security model / incident response; genuinely outside this plan's scope |
| Loss of the KMS CMK (service-side failure, not deletion) | Out of this application's control | Total, for every `wrapped_dek` under that CMK — see §13 | AWS's own KMS availability SLA/incident response |
| Accidental KMS key deletion | KMS enforces a mandatory 7-30 day waiting period before a scheduled deletion actually takes effect, during which it is cancelable; IAM scoping (§5.2) already excludes `kms:ScheduleKeyDeletion`/`kms:DisableKey` from the application's own role | A human with key-administration access schedules deletion and it is not caught within the waiting window | §13's explicit recommendation: maximum (30-day) waiting period in production, a separate administrative IAM principal for key administration, and a recommended CloudTrail alert on `ScheduleKeyDeletion` against this key |
| Onboarding-token compromise | Out of this design's scope — a stolen, valid onboarding token lets its holder read/submit `bank_info` exactly as the legitimate candidate could, through the same authenticated (by token) API; encryption protects the value at rest, not from a legitimate-looking holder of a valid credential reading it through the normal API path | Real, but structurally the same limitation as "compromised application server" one row above — an authentication/token-lifecycle control, not an at-rest control | Out of scope for DATA-01; a candidate for a separate onboarding-security follow-up (token expiry/single-use enforcement, if not already covered elsewhere) |
| Key-rotation failure (a rotation that leaves some rows undecryptable) | §10's design (KMS-native rotation keeps prior key material available automatically; application-level rotation retains every prior `key_version` row indefinitely, §2.2) is specifically built to avoid this | A bug in an *optional* background re-encryption pass (§10.2 item 8) could leave a batch half-migrated | Same batching/idempotency/verification discipline as §6 — a re-encryption pass is the same job, run again under a new key; and it is optional, so a stalled pass never makes any row undecryptable (old rows stay valid under their original version regardless) |
| Developer/staging database copies | Ciphertext only, same as any other backup (§13) | A staging environment that is *also* granted the production KMS key's decrypt permission defeats the isolation | Staging must use its **own** KMS key and its **own** `encryption_keys` rows (§5.2 — "one CMK per environment") — never the production key — an explicit provisioning rule, not implicit |

**Explicitly not claimed**: this design does not protect against a fully compromised application
server, a compromised KMS-capable IAM principal, or a platform-level KMS compromise — each is named
above rather than glossed over.

---

## 12. Production safety gates

1. **No plaintext value remains in any of the four field-level locations** (inventory §1) — verified
   by the discovery query (§6.1) returning zero plaintext-format rows across
   `employee.pan_number_enc`, `employee.aadhaar_number_enc`, `employee_bank.account_number_enc`,
   **and** `onboarding_case.bank_info`'s `account_number_enc` key (the second location is easy to
   forget — named explicitly as its own gate item, not folded into "the bank table").
2. **The DEK is external to the database in wrapped form, and the KEK never leaves KMS** — satisfied
   structurally by §2.1/§2.2: no plaintext key material of any kind is ever stored in Postgres, only
   `key_version` integers (in ciphertext strings) and `wrapped_dek` blobs (in `encryption_keys`,
   themselves useless without a live `kms:Decrypt` against the CMK).
3. **All four write paths encrypt, with correct AAD** — `EmployeeService` (PAN/Aadhaar, once E-02
   ships), `EmployeeBankService.create_bank`, the onboarding wizard's `bank_info` `PATCH` handler, and
   `activate_case`'s `BankCreate` construction — verified by the test matrix's write-path and AAD
   tests.
4. **The audit-log redaction mechanism is live and covers every current write path** (§7) — verified
   by the test matrix's audit tests; this gate cannot be silently skipped, unlike the prior draft's
   optional framing.
5. **The historical audit-log remediation decision (§8) has been explicitly made and, if approved,
   executed and verified** — not left ambiguous; either "executed, §8.5 verification passed" or "Option
   B formally accepted, signed off" must be true before this gate is considered satisfied.
6. **The onboarding-lifecycle decision (§9) has been explicitly made** — either "clearing (§9.1) is
   enabled and its own regression tests pass" or "retention (§9.2) is the approved product decision,
   and the retained value is confirmed encrypted" — not left as the prior draft's silent "never clear"
   default.
7. **All read paths use controlled decryption** — decryption happens only inside
   `EmployeeBankService`/`EmployeeService`/`OnboardingService` methods that have already run the
   relevant permission check (§7 of this plan's implementation sequencing, below), never inside a
   Pydantic schema, a list-serialization loop (§13's performance section), or an automatic
   `TypeDecorator` read hook (§2.5 — now structurally impossible, not just a convention to follow).
8. **Logs contain no sensitive values** — verified by the test matrix's logging tests and the backfill
   job's counts-only logging convention (§6.5).
9. **Migration/backfill verified** — §6.6's snapshot-comparison pass completed and its results (row
   counts, zero-plaintext-remaining confirmation) recorded in the closeout report; the plaintext
   snapshot itself discarded per §6.6's own handling rule.
10. **Restore procedure tested** — a DR-drill restore explicitly confirms the ciphertext/KMS-access
    separation described in §13, in at least one non-production environment, before this gate is
    considered satisfied.
11. **Key rotation tested** — at minimum, confirm KMS-native automatic CMK rotation is enabled
    (§10.1); a full application-level DEK rotation rehearsal (§10.2) is recommended before first
    production use but may be deferred to the first real rotation event if time-boxed explicitly in
    the closeout report.
12. **Tests pass** — the full matrix in `DATA_01_PII_ENCRYPTION_TEST_MATRIX.md`, plus the existing
    regression suite (employee creation/update, banking creation/read, onboarding wizard submit/
    read-back/activation) with zero behavioral regressions beyond "the stored value is now
    ciphertext."
13. **No production secret committed** — no real KMS key ARN, AWS credential, or real-shaped PII value
    appears in `env/.env.*.example`, source, tests, or this planning documentation (verified: this
    plan and its companions contain none).
14. **Staging validation completed** — the full Phase A-H sequence (§6.9) exercised in staging against
    staging's own KMS key and its own `encryption_keys` rows before production Phase B ships, matching
    `env/.env.staging.example`'s own stated role as the pre-production sign-off environment.

---

## 13. Backups, disaster recovery, and production recovery

### 13.1 What a backup contains, and what it does not

A PostgreSQL logical dump (`pg_dump`), a snapshot, or a staging/developer copy of the database all
contain: every ciphertext value, every `key_version` reference, and the full `encryption_keys` table
— including every `wrapped_dek` ever issued, active or retired. This is the direct, intended
consequence of envelope, application-level encryption (as opposed to, say, relying solely on
encryption-at-rest for the whole disk/volume, which protects against physical media theft but does
**not** protect against someone with ordinary read access to a backup file or a restored copy —
exactly the gap DATA-01 exists to close). **What a Postgres-only backup does not contain, under any
circumstance, is the KMS CMK itself** — the one piece of material that turns a `wrapped_dek` back
into a usable plaintext DEK.

### 13.2 What must exist in AWS KMS for a restore to be usable

The same CMK (same key ARN/alias, same AWS account and region) that wrapped the `wrapped_dek` values
present in the restored `encryption_keys` table must still exist, be enabled, and be reachable.
Without it, every `wrapped_dek` in the restored table is permanently opaque ciphertext with nothing
that can unwrap it — this is true regardless of how complete or correct the PostgreSQL restore
itself is.

### 13.3 IAM permissions required for a restored application

The restored application's compute identity (ECS task role or equivalent, per
`env/.env.production.example`'s existing convention) needs `kms:Decrypt` on the specific CMK ARN to
resolve any `wrapped_dek` back into a usable plaintext DEK (§2.1/§2.2), and `kms:GenerateDataKey`
only if the restore is also expected to be able to mint new key versions (i.e. it is being brought
back up as a live, writable environment, not a read-only forensic copy) — the same least-privilege
scoping as §5.2, not a separate policy invented for recovery.

### 13.4 How a restored application obtains wrapped DEKs and decrypts old ciphertext

No special "recovery mode" code path is required or recommended — this is itself a resilience
property worth stating explicitly. A restored application reads the `encryption_keys` table (now
present via the ordinary Postgres restore) for whichever `key_version` a given ciphertext string
references, resolves the matching row's `wrapped_dek` via `kms:Decrypt` (lazily, on first need,
exactly as in normal operation, §2.1), and decrypts using AES-256-GCM with the row's own recomputed
AAD (§2.4) — the identical code path used every day, not a bespoke recovery procedure that could
itself be undertested.

### 13.5 What happens if the KMS key is unavailable during a restore

If unavailability is transient (regional throttling, a temporary outage) — per §5.5's existing
failure-mode design, decrypt calls fail closed for the specific field/request involved, not for the
whole restore; a DR runbook should treat "cannot reach KMS" as an explicit go/no-go checklist item
before declaring a restore complete for any environment where reading PII is required, rather than
silently proceeding with an environment that can restore rows but not read them.

### 13.6 Protection against, and consequence of, accidental or permanent KMS key deletion

AWS KMS enforces a mandatory waiting period (configurable, 7-30 days) before a scheduled CMK deletion
actually takes effect, during which it can be canceled by anyone with the key-administration IAM
grant. Recommended for production: the maximum 30-day window, an IAM/SCP-level restriction limiting
`kms:ScheduleKeyDeletion`/`kms:DisableKey` to a small, separate administrative principal (never the
application's own role, §5.2), and a recommended (not must-have for DATA-01) CloudTrail alert on any
`ScheduleKeyDeletion` event against this specific key.

**Explicitly documented, as required**: deletion or permanent loss of the KMS CMK makes every
`wrapped_dek` ever issued under it — and therefore every ciphertext value ever encrypted, across
every retained key version, including fully historical ones — **permanently unrecoverable**. There is
no application-level, database-level, or backup-level recovery from CMK loss; a PostgreSQL backup
containing a complete, correct `encryption_keys` table is worthless for recovering plaintext once its
CMK is gone. This is the single largest availability risk this design introduces, and is the direct,
accepted tradeoff of the property that makes a database-only compromise safe in the first place (§13.1)
— the same external dependency that keeps an attacker with only the database out is exactly what
keeps a legitimate operator out if it is lost. The 30-day deletion window and IAM separation above are
the mitigations; there is no cryptographic recovery path beyond them.

### 13.7 Restore-testing implication

A disaster-recovery drill that restores the database into a fresh environment must separately verify
that environment either (a) has its own correctly-scoped KMS access (a production DR restore, where
decrypting is the whole point), or (b) deliberately does **not** (a staging/test restore of production
data, where the ciphertext staying opaque is the desired safety property) — this distinction should be
a named checklist item in the existing DR-drill process referenced by
`PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md`'s own "Backup & recovery: Undefined" finding (a
separate, already-flagged gap this plan does not attempt to close, but whose eventual remediation
must account for this KMS-access distinction).

---

## 14. Performance analysis

| Operation | Impact | Where decryption should NOT occur |
|---|---|---|
| Employee creation | None today (PAN/Aadhaar have no write path yet, inventory §2) — becomes "one AES-GCM encrypt call, using the already-cached DEK" whenever E-02 ships a write path; a KMS call only on a DEK cache miss, not per record | N/A |
| Employee update | Same | N/A |
| Employee listing (`GET /employees`) | **None** — `EmployeeRead` never includes `pan_number_enc`/`aadhaar_number_enc` (inventory §2 item 3), so a list response never triggers a decrypt call regardless of how many rows it returns. This is exactly the property that keeps list-endpoint performance (already a separate, tracked concern — `API-01`, pagination) unaffected by DATA-01 | List endpoints — confirmed no decrypt call is ever needed there, and none should be added |
| Employee detail (`GET /employees/{id}`) | None (same reason) | Same |
| Bank creation (`POST .../bank`) | One local AES-GCM encrypt call added to an already-low-frequency write (an effective-dated revision, not a hot path); no KMS network call unless the current DEK isn't already cached in this process | N/A |
| Bank read (`GET .../bank`, `GET .../bank/{id}`) | One local AES-GCM decrypt call per row returned, using the cached DEK for that row's `key_version`; a KMS call only on a cache miss for that specific version, at most once per process per TTL window (§2.1) — not once per row. At this system's actual bank-details access pattern (a single employee's own record, or one HR reviewer looking at one profile at a time — never a bulk list, inventory §3 items 6/11) this is negligible even before accounting for the cache | N/A — this is the one path that legitimately needs it |
| Employee CSV import | None — confirmed zero references to these fields anywhere in `employee_import` (inventory §2 item 6, §3 item 9) | N/A |
| Export | None — no export path exists (inventory §7) | N/A |
| Reports | None — no reporting functionality exists in this codebase today | N/A |
| Onboarding wizard read-back (candidate + HR) | One `encrypt_field` call on `PATCH` submit, one `decrypt_field` call on each of the two read-back responses (inventory §4 items 3-4) — same cached-DEK, local-AES-GCM cost profile as bank read/write above | N/A |
| Onboarding activation | One `decrypt_field` + one `encrypt_field` call (decrypt the JSONB copy, re-encrypt into the real `employee_bank` column), plus (per §9.1) one JSONB-key removal in the same transaction — a one-time, per-employee event, not a hot path | N/A |
| Backfill job | Bounded by AES-GCM throughput and the row count discovered in §6.1 (not KMS rate limits — a single DEK is resolved once at the start of the run and reused for every row, §6.3), at this system's actual data volume (inventory's own framing: hundreds-to-low-thousands of employees per tenant) expected to complete in seconds to low minutes per environment | N/A |

**Overarching principle**: decryption should occur **only** at the single-record detail/edit boundary
where a caller has already passed the permission check for that specific RESTRICTED field — never
inside a list-serialization loop, never inside a search/filter query (none exists to worry about,
§3), and never eagerly on employee/case load "just in case" a caller might ask for the sensitive
sub-resource. §2.5's corrected encryption boundary now makes this structurally true for the three
real columns (no ORM load ever decrypts implicitly), not just a convention for `onboarding_case.
bank_info`'s already-explicit calls. This keeps plaintext lifetime in application memory to the
shortest span the current code already implies: one request, one field, one decrypt call, discarded
the moment the response is serialized.

---

## 15. Implementation sequencing

### Must-have for DATA-01

1. `hrms/core/crypto/` package: `KmsKeyService` (aioboto3 `kms` client wrapper — `GenerateDataKey`/
   `Decrypt` on wrapped DEKs only), `DekCache` (lazy-load + TTL-bound in-memory DEK cache, §2.1),
   `encrypt_field`/`decrypt_field` functions (ciphertext format §2.3, mandatory AAD parameter §2.4),
   `EncryptedOnWrite` `TypeDecorator` (write-only, §2.5).
2. `encryption_keys` Alembic migration (§2.2) — new table, no data migration.
3. `hrms/core/audit/redact.py`: `mask_sensitive()` + `SENSITIVE_FIELD_MASKS` registry (§7.1).
4. `Settings` additions: a KMS key identifier/ARN setting (environment-driven, same
   `env/.env.*.example` documentation convention `PRODUCTION_HARDENING_BATCH_1_REPORT.md`
   established for `CORS_ALLOWED_ORIGINS`/`TRUSTED_PROXY_HOSTS`), a development-mode local-key
   setting (§5.4), and a `model_validator` boot guard refusing `staging`/`production` startup without
   a real KMS key **and** at least one `ACTIVE` `encryption_keys` row (§10.3) — reusing the exact
   validation pattern SEC-01 already established, not inventing a new one.
5. Wire `EncryptedOnWrite` onto `Employee.pan_number_enc`, `Employee.aadhaar_number_enc`,
   `EmployeeBank.account_number_enc` in `hrms/modules/employee/models.py`.
6. Explicit `encrypt_field`/`decrypt_field` calls, with correctly-constructed AAD per §2.4, at the two
   `onboarding_case.bank_info` boundaries (`onboarding/service.py`'s wizard-`PATCH` write path and the
   `activate_case` read-then-construct-`BankCreate` path) and the two read-back response-construction
   sites (`onboarding/schemas.py:328`, `:437`) — decrypt only immediately before handing the value to
   the response schema, per the narrow-service-path principle.
7. Update `BankRead`/whatever future `EmployeeRead` PAN/Aadhaar fields look like, to decrypt via an
   explicit service-layer call only, never inside a Pydantic validator and never via an automatic
   `TypeDecorator` read hook (§2.5) — decryption happens in `EmployeeBankService`, after the
   permission check has already run, not in the schema.
8. Wire `mask_sensitive()` into `bank_to_audit_dict()` (§7.1) — must ship no later than the same
   deploy that starts writing bank audit rows under the new code, so no new plaintext audit row is
   ever created after this batch begins.
9. Wire §9.1's post-activation clearing of `onboarding_case.bank_info`'s `account_number_enc` key,
   gated on the sign-off named in §9.3 before enabling in a real environment.
10. A standalone backfill script/Celery task (§6), runnable independently of a request cycle, covering
    all four field-level locations.
11. A separate, independently-scheduled historical audit-log remediation script (§8), gated on the
    sign-off named in §8.7 before running against a real environment.
12. No Alembic migration is required for the three real columns' *types* (Option A, §4) — but a
    migration **is** required for `encryption_keys` (item 2 above), and a migration or reviewable
    script is required to run the discovery queries (§6.1) as a repeatable, reviewable artifact.
13. Tests — full matrix, `DATA_01_PII_ENCRYPTION_TEST_MATRIX.md`.

### Recommended, closely related, but not strictly DATA-01

- **Resolving PD-3** (partial masking at the API layer, inventory §8) — see §16 below; kept separate.
- **PAN/Aadhaar write path** (E-02, still unbuilt) — out of scope entirely; this plan only ensures the
  columns and the audit-masking registry are ready for whenever that slice ships, per H-2's own
  stated ordering.

### Explicitly out of scope (per this task's own scope lock)

`API-01` (pagination), `SEC-03`–`SEC-10`, `SEC-11`, account lockout, Docker/CI, attendance/timezone
logic, RBAC changes beyond what item 7 above already requires (a service-layer decrypt call, not a
permission-model change), refresh-token storage, password reset, invite authentication, email
verification, `DEP-01` (python-jose migration — noted only because it is `cryptography`'s current
transitive source, §2.1).

### Deployment order (maps directly to §6.9's phases)

Prep (A) → initial key provisioning (A′) → ship (B) → backfill (C) → verify (D) → audit redaction (E)
→ onboarding cleanup, gated (F) → historical audit remediation, gated and conditional (G) →
enforcement (H).

### Rollback strategy

Because Option A never changes a column's SQL type, rollback at any point before the backfill (Phase
C) completes is a plain code rollback (redeploy the prior version) — the column still holds whatever
it held before (plaintext, if Phase B/C hadn't reached that row yet). **After** the backfill has
encrypted a row, rolling back the *application code* to a pre-encryption version would make that row
unreadable by the old code (it would see `v1:...` and treat it as a garbled plaintext value) — so once
Phase C begins in a given environment, the corresponding code deploy (Phase B) is a one-way door for
that environment's data, exactly as any real encryption rollout is. §8's historical audit remediation
and §9's onboarding-cleanup are separately, explicitly **not** one-way in the same sense before their
own sign-off gates fire — both are disclosed as irreversible-after-execution in their own sections
(§8.6, and §9.1's atomicity discussion), which is the more precise statement than a blanket "rollback
strategy" line could give them.

---

## 16. API masking behavior (ties to inventory §8 / PD-3) — kept separate from DATA-01

Per this task's explicit instruction: **DATA-01 does not require changing the current authorization
model.** API-level partial masking (PD-3, inventory §8) remains a separate, P1-recommended-before-
production item, and is **not** silently implemented as part of this batch.

Default posture, **regardless of whether PD-3 is formally resolved separately**: no change to who can
see a full value versus who cannot — that remains governed entirely by the existing
`EMPLOYEE.VIEW_BANKING`/`EMPLOYEE.UPDATE_SENSITIVE` permission checks (inventory §3 items 6-8), which
this plan does not alter. What DATA-01 changes is *only* that the value the authorized caller receives
was decrypted through a narrow, explicit service-layer call rather than read directly off the ORM
object.

- **Employee (self-service)**: today, sees their own bank details in full (SELF-scoped
  `.VIEW_BANKING`, inventory §3 item 8) — unchanged by DATA-01 unless PD-3 is separately resolved to
  introduce masking for this specific viewer tier.
- **HR admin**: sees full values (`COMPANY`-scoped `.VIEW_BANKING`) — unchanged.
- **Authorized manager**: no manager-shaped role is granted `.VIEW_BANKING` by default today
  (inventory §3 item 7, `Decision F` cited in the banking plan's own threat model) — unchanged.
- **Payroll/admin roles**: no Payroll module exists yet in this codebase; not applicable today.
- **System administrators** (anyone with direct DB/backup access): per §5.6/§13, must **not** be able
  to read the value without also holding KMS `kms:Decrypt` permission on the specific key — this is
  the entire point of the design, and the one place DATA-01 changes access for a previously-
  unrestricted class of viewer (a database or backup copy is no longer sufficient on its own).
- **Auditing full-value access**: no new audit event is proposed for *reading* a decrypted value in
  this batch (a "PII_ACCESSED" audit event is a real, defensible idea, but is new infrastructure
  beyond "encrypt the column" — flagged as a **recommended, not must-have**, item, consistent with
  this plan's instruction not to expand scope past DATA-01's core). KMS's own CloudTrail log already
  records every `Decrypt` API call (principal, key, timestamp) under the DEK-cache model (§2.1) — a
  real, if coarser-grained (per-cache-miss, not per-employee-record), access trail exists "for free"
  the moment KMS is wired up, without building anything new — coarser than the first draft's claim
  (which assumed one CloudTrail entry per field read, true only under the rejected direct-KMS-call
  design), so this is named explicitly as a corrected, weaker claim than the original draft made.
- **Recommendation**: resolving PD-3 in the same implementation batch remains sensible (the natural
  implementation point for "decrypt only inside a narrow, authorized path" is exactly where a masked
  vs. full view decision would also be made) but is not required, and must not be silently bundled in
  without a separate, explicit approval to change API/authorization behavior.

---

## 17. Risks and decisions carried into the closeout report

- **PD-3** (partial masking) remains open — this plan recommends resolving it alongside DATA-01 but
  does not decide it; either answer (whole-resource gating continues, or partial masking is built) is
  compatible with everything in this plan.
- **§8's historical audit-log remediation** — strategy fully specified, execution gated on named
  production sign-off; not decided unilaterally by this document.
- **§9's onboarding-lifecycle decision** — default (clear) recommended, alternative (retain,
  encrypted) fully specified; enabling either in production gated on named sign-off; not decided
  unilaterally by this document.
- **The blind-index/HMAC design in §3** is fully specified but explicitly not built — a future
  requirement, not a current one.
- **Per-tenant KMS keys** (§5.2) — not recommended now, but named as a plausible future enterprise
  requirement so it is not rediscovered from zero if asked for later.
- **Optional background re-encryption after rotation** (§10.2 item 8) — named as available but not
  required; a future operator can decide whether to run it based on real rotation cadence and
  compliance needs, not predetermined here.

---

## 18. Final implementation checklist

- [ ] PAN encryption (`Employee.pan_number_enc` wired to `EncryptedOnWrite`; explicit decrypt at
      service boundary once E-02 ships a write path)
- [ ] Aadhaar encryption (`Employee.aadhaar_number_enc`, same shape)
- [ ] Employee bank account encryption (`EmployeeBank.account_number_enc`)
- [ ] Onboarding bank information encryption (`onboarding_case.bank_info`'s `account_number_enc` key,
      explicit `encrypt_field`/`decrypt_field` at both service-layer boundaries)
- [ ] KMS CMK configuration (one per environment, IAM-scoped per §5.2, automatic annual rotation
      enabled)
- [ ] DEK generation (`GenerateDataKey`, §2.1/§10.2)
- [ ] Wrapped-DEK registry (`encryption_keys` table, §2.2, migration shipped)
- [ ] Key versioning (`key_version` in every ciphertext string; resolves to a specific `encryption_keys`
      row; old versions retained indefinitely)
- [ ] AES-256-GCM (local encrypt/decrypt against the cached plaintext DEK; no per-field KMS calls)
- [ ] AAD (mandatory on every encrypt/decrypt call; `table:column:record_id` convention, §2.4;
      ciphertext-substitution test passes, §11)
- [ ] Encrypt-on-write (`EncryptedOnWrite` `TypeDecorator`, write-side only, §2.5)
- [ ] Explicit decrypt-at-service-boundary (no automatic read-side decryption anywhere; verified by
      the test matrix's boundary tests)
- [ ] Audit-log redaction (`mask_sensitive()` + `SENSITIVE_FIELD_MASKS` wired into
      `bank_to_audit_dict()` and every future `*_to_audit_dict()`, §7)
- [ ] Historical audit-log remediation (strategy executed per the approved option in §8.4, or Option B
      formally signed off; §8.5 verification passed)
- [ ] Onboarding cleanup after activation (§9.1 enabled per the approved decision in §9.3, atomic with
      the `employee_bank` insert; or §9.2's retention alternative approved and confirmed encrypted)
- [ ] Idempotent backfill (§6, all four field-level locations covered, verified via §6.6)
- [ ] Verification (§6.6 snapshot-comparison pass; §8.5 historical-remediation verification if §8
      executed)
- [ ] Key rotation (KMS CMK automatic rotation confirmed enabled; application-level DEK rotation
      procedure rehearsed at least once, §10)
- [ ] Backup/recovery (DR-drill restore tested against a non-production environment confirming the
      ciphertext/KMS-access separation, §13.7)
- [ ] Tests (full `DATA_01_PII_ENCRYPTION_TEST_MATRIX.md` passing, plus full regression suite)
- [ ] Staging validation (full Phase A-H sequence exercised in staging before production Phase B
      ships, §6.9/§12 gate 14)
- [ ] Production safety gates (all 14 gates in §12 satisfied and recorded in the closeout report)

---

## Final position

This plan was implementation-ready and internally consistent, and §0a records that the
implementation batch has now executed it: every design decision above is grounded in a specific,
cited piece of this repository's actual code, schema, or prior architectural decision, the six
blockers the architecture review raised against the first draft (§0) are each resolved with a
concrete, specific design, and §15's sequence has been executed against real code, with one
technical correction (§0a) and two items deliberately left un-executed pending the named
product/compliance sign-offs (§8, §9.3).

**DATA-01 is not yet CLOSED.** What is done: encryption infrastructure, both live write paths
(`employee_bank`, `onboarding_case.bank_info`), the backfill (implemented and tested; not yet run
against a real production dataset since none exists in this repository), mandatory audit-log
redaction, and the production safety gates in §12 that don't depend on the two open sign-offs. What
remains open: §8's historical audit-log remediation decision, §9.3's onboarding-retention decision,
a staging rehearsal of the full Phase A-H sequence (§6.9) against a real KMS CMK (this batch only
exercised `environment=development`'s local-key path plus registry/rotation logic against a fake
KMS — no real AWS KMS account was available in this environment), and a rehearsed application-level
key rotation in a real (non-development) environment.
