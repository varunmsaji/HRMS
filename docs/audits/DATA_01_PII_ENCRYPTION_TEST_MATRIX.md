# DATA-01 — PII Encryption Test Matrix

| Field | Value |
|---|---|
| Status | **Implemented and passing** — 59 new tests across `tests/unit/core/test_crypto_field.py`, `test_crypto_keys.py`, `test_pii_crypto_service.py`, `test_audit_redact.py`, `tests/unit/modules/employee/test_employee_bank_service.py` (additions), `tests/integration/modules/employee/test_employee_banking.py` (additions), `tests/integration/modules/onboarding/test_onboarding_activation.py` (additions), and `tests/integration/test_pii_encryption_backfill.py`. Full backend suite: 1362 passed, 1 pre-existing unrelated failure. Not automated in this batch: a true concurrent-write-vs-backfill race test (plan §21/test matrix §4's own "not a strict requirement to automate" allowance) and historical audit-log remediation tests (§6 below — the remediation itself was not run, gated on sign-off per implementation plan §8.7). |
| Companion documents | `DATA_01_PII_DATA_FLOW_INVENTORY.md`, `DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` |

This matrix specifies what the DATA-01 implementation batch must test, mapped directly to the
design in the implementation plan and the four storage locations in the inventory, plus the
mandatory audit-log protection work (plan §7/§8) and the onboarding-lifecycle decision (plan §9).
Existing test conventions in this repository are followed throughout: real Redis/Postgres
integration tests (no mocked database, matching `tests/integration/`'s existing posture), raw-JSON
response assertions for masked/omitted fields (matching every RESTRICTED-field precedent —
Compensation, Statutory, Banking), and `pytest-asyncio` with the existing `client`/`seeded_db`
fixture shapes.

---

## 1. Encryption primitives (`hrms/core/crypto/`)

New unit test file, e.g. `tests/unit/core/test_crypto.py`:

| Test | Asserts |
|---|---|
| `test_plaintext_never_persisted` | Encrypting a known plaintext value never produces a string equal to (or containing, as a substring) the original plaintext |
| `test_randomized_encryption_produces_different_ciphertext_each_time` | Encrypting the same plaintext twice (same key) produces two different ciphertext strings (nonce uniqueness, plan §2.3) — this is also the direct proof that no equality-based lookup is possible without a separate blind index (plan §3) |
| `test_decrypt_returns_the_original_value` | `decrypt_field(encrypt_field(x)) == x` for a representative set of values: a real-shaped PAN (`"ABCDE1234F"`), a real-shaped Aadhaar (`"123456789012"`), a real-shaped bank account number (`"1234567890"`), an empty string, a very long string, and a string containing the `:` delimiter character itself (format-injection guard) |
| `test_tampered_ciphertext_fails_authentication` | Flipping one byte in the ciphertext portion of an encrypted value raises a decryption error (GCM's authentication-tag check) rather than returning corrupted plaintext |
| `test_tampered_nonce_fails_authentication` | Same, for the nonce segment |
| `test_malformed_ciphertext_string_fails_safely` | A string that doesn't match the `v1:<int>:<base64>:<base64>` shape at all (e.g. plain garbage, or a legacy plaintext value that doesn't start with `v1:`) is either (a) treated as plaintext needing migration (the backfill's own classification logic, tested separately in §4) or (b) raises a clear, named exception — never crashes with an unhandled `IndexError`/`binascii.Error` that could leak a stack trace containing adjacent request data |
| `test_none_passes_through_unchanged` | `encrypt_field(None)` and `decrypt_field(None)` both return `None` — matches every field's existing `nullable=True` behavior |
| `test_key_version_is_recorded_and_used_on_decrypt` | Encrypting under key version N produces a ciphertext string carrying `N`; decrypting looks up/uses version N specifically, not always "the current key" (proves rotation-safety, plan §2.2/§10) |
| `test_aad_is_required_not_optional` | Calling `encrypt_field`/`decrypt_field` without an `aad` argument fails at the call signature level (a required keyword argument, plan §2.4) — not merely "works without AAD" |
| `test_decrypt_fails_when_aad_does_not_match_encryption_aad` | Encrypting under `aad="employee_bank:account_number_enc:{id_a}"` then decrypting the resulting ciphertext under a different AAD (e.g. `{id_b}`) raises an authentication error — direct proof of AAD binding (plan §2.4) |
| `test_ciphertext_copied_to_a_different_row_fails_to_decrypt` | The concrete scenario plan §2.4 describes: take a real ciphertext value produced for row A's AAD, place it (simulating a copy/tamper) where row B would be decrypted, and confirm decrypting it under row B's own AAD raises rather than returning row A's plaintext under row B's identity — this is the single most important AAD test in this file |
| `test_same_row_same_field_produces_stable_aad_across_calls` | Encrypting the same row's field twice (e.g. a revision) computes an identical AAD string both times, derived only from stable identifiers (the row's own id) — proves AAD construction has no accidental nondeterminism (e.g. a timestamp) that would make the row's own later decrypt fail |

### Key management (DEK cache and `encryption_keys` registry, plan §2.1/§2.2)

| Test | Asserts |
|---|---|
| `test_missing_kms_key_configuration_fails_closed` | With no KMS key identifier configured, an encrypt/decrypt attempt raises rather than silently falling back to an unencrypted no-op |
| `test_invalid_kms_key_reference_fails_closed` | A configured key ARN/alias that KMS rejects (e.g. wrong region, doesn't exist) surfaces as a clear error on first use, not a delayed or swallowed failure |
| `test_kms_unavailable_on_write_fails_closed` | Simulated KMS outage during a DEK-cache-miss encrypt call → the write is rejected, not silently persisted as plaintext (plan §5.5) — this is the single most important test in this file |
| `test_kms_unavailable_on_read_degrades_the_one_field_only` | Simulated KMS outage during a DEK-cache-miss decrypt call, in the context of a full `GET` response containing other, non-encrypted fields → the response for the encrypted field surfaces a distinct, named error; sibling non-encrypted fields on the same resource are unaffected (plan §5.5) |
| `test_dek_is_resolved_from_kms_at_most_once_per_process_per_key_version` | Encrypting/decrypting several records in sequence, all under the current key version, results in exactly one `kms:Decrypt`/`GenerateDataKey` call, not one per record — direct proof of the DEK cache (plan §2.1), and of the "no per-field KMS call" claim the corrected architecture depends on |
| `test_dek_cache_expires_after_its_ttl_and_is_re_resolved` | After the configured cache TTL elapses, the next operation triggers a fresh registry lookup (and, if the wrapped bytes for that version aren't already known, a fresh `kms:Decrypt`) rather than using a stale entry indefinitely (plan §2.1) |
| `test_no_active_encryption_key_row_fails_closed` | With the `encryption_keys` table present but zero `ACTIVE` rows, an encrypt attempt raises a clear error rather than silently picking an arbitrary/`RETIRED` row (plan §2.2) |
| `test_more_than_one_active_encryption_key_row_is_treated_as_a_fault` | Two `ACTIVE` rows existing simultaneously (a hypothetical data-integrity violation of the "exactly one ACTIVE row" invariant) is detected and rejected rather than silently resolved by picking one (plan §2.2) |
| `test_unknown_key_version_in_ciphertext_fails_closed` | A `key_version` parsed from a ciphertext string with no matching `encryption_keys` row raises a distinct error, never falls back to "use the current key instead" (plan §2.2) |
| `test_key_rotation_old_version_still_decrypts` | A value encrypted under key version 1 still decrypts correctly after rotation creates key version 2 and marks it `ACTIVE` (plan §10.2) |
| `test_key_rotation_flips_exactly_one_row_atomically` | Rotation's insert-new-ACTIVE + retire-old-ACTIVE happens within one transaction — a simulated failure between the two steps leaves the registry in its pre-rotation state (still one `ACTIVE` row, the old one), never in a zero-`ACTIVE` or two-`ACTIVE` state (plan §2.2/§10.2) |
| `test_new_writes_after_rotation_use_the_new_key_version` | Immediately after rotation, a new encrypt call's resulting ciphertext carries the new `key_version`, not the retired one (plan §10.2 item 5) |

---

## 2. Settings / boot guard

New tests in (or alongside) `tests/unit/core/test_settings.py` — same pattern
`PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s SEC-01 guard tests already established for JWT secrets:

| Test | Asserts |
|---|---|
| `test_development_allows_the_local_dev_key` | `environment="development"` boots with the dev-mode local key path (plan §5.4) |
| `test_staging_rejects_missing_kms_configuration` | `environment="staging"` with no KMS key configured fails `Settings()` construction |
| `test_production_rejects_missing_kms_configuration` | Same, for `production` |
| `test_staging_rejects_the_dev_mode_local_key` | `environment="staging"` with the known dev-mode key/flag still set is rejected — mirrors SEC-01's "known default explicitly rejected outside development" requirement exactly |
| `test_production_rejects_the_dev_mode_local_key` | Same, for `production` |
| `test_staging_accepts_a_real_kms_key_reference` | A syntactically valid (test double) KMS key ARN/alias is accepted |
| `test_production_accepts_a_real_kms_key_reference` | Same, for `production` |
| `test_staging_rejects_boot_with_zero_active_encryption_keys` | `environment="staging"` with a real KMS key configured but no `ACTIVE` row in `encryption_keys` fails boot (plan §10.3) |
| `test_production_rejects_boot_with_zero_active_encryption_keys` | Same, for `production` |
| `test_error_message_never_echoes_the_key_reference` | Error text names the field/environment only, matching SEC-01's own convention (no ARN, no key material, in any raised message) |

---

## 3. API-level behavior (per storage location)

### 3a. `employee.pan_number_enc` / `.aadhaar_number_enc` (once a write path exists)

Since no write path exists today (inventory §2), these tests are written **against whatever E-02
slice adds the write path**, using the same encryption primitives — listed here so the
implementer of that future slice does not have to re-derive the requirement:

| Test | Asserts |
|---|---|
| `test_pan_is_encrypted_at_rest` | After a create/update call, querying the raw DB column directly (bypassing the ORM's `EncryptedOnWrite` type, e.g. via a raw `SELECT`) returns a `v1:`-prefixed ciphertext, never the submitted plaintext |
| `test_pan_round_trips_correctly_through_the_api` | Submitted plaintext PAN is returned unchanged (decrypted) on a subsequent authorized read |
| `test_pan_absent_without_the_governing_permission` | Matches the existing RESTRICTED-field convention: omitted (not `null`) from the raw JSON response when the caller lacks the permission gating it |
| `test_plain_orm_load_of_employee_never_decrypts_pan_or_aadhaar` | Loading an `Employee` row via a plain `session.get()`/incidental query (not through `EmployeeService`'s permission-checked read path) returns the raw `v1:`-prefixed ciphertext string on the attribute, never plaintext — direct proof the `EncryptedOnWrite` type has no read-side auto-decrypt hook (plan §2.5) |

### 3b. `employee_bank.account_number_enc` (live today)

New tests, likely extending `tests/integration/modules/employee/test_employee_banking.py`:

| Test | Asserts |
|---|---|
| `test_bank_account_number_is_encrypted_at_rest` | Direct raw-SQL read of `employee_bank.account_number_enc` after a `POST .../bank` returns ciphertext (`v1:` prefix), never the submitted plaintext — this is the core proof-of-encryption test for the one field with a live, shipped write path |
| `test_bank_account_number_round_trips_through_the_api` | `POST` then `GET` returns the identical plaintext value the caller submitted |
| `test_bank_read_still_omits_the_field_without_view_banking_permission` | Regression: the existing `test_account_number_absent_without_view_banking_permission` behavior (raw-JSON, field absent) must be unaffected by the encryption change |
| `test_self_scoped_employee_still_sees_only_their_own_decrypted_value` | Regression against PD-1's resolved `SELF`-scope wiring (inventory §3 item 8) — encryption must not break, or accidentally widen, the existing data-scope binding |
| `test_revision_history_rows_all_decrypt_correctly` | An employee with multiple effective-dated bank rows (a revision) — every historical row, not just the current one, decrypts correctly on a full-history read, each under its own row-specific AAD (plan §2.4) |
| `test_two_bank_rows_for_different_employees_cannot_decrypt_each_others_ciphertext` | Swapping the raw `account_number_enc` ciphertext between two different `EmployeeBank` rows and attempting to read either afterward raises an authentication error rather than returning the wrong employee's account number (plan §2.4's AAD guarantee, applied end-to-end through the real service/repository path, not just the crypto-primitive unit test in §1) |
| `test_plain_orm_load_of_bank_row_never_decrypts_account_number` | Loading an `EmployeeBank` row outside `EmployeeBankService`'s permission-checked read methods returns ciphertext on the attribute (plan §2.5) |
| `test_bank_audit_log_row_never_contains_the_plaintext_account_number` | After a `POST .../bank`, the resulting `audit_log` row's `before_json`/`after_json` contains the masked form (`"******7890"`-shaped) of `account_number_enc`, never the plaintext or the raw ciphertext — proves the mandatory redaction in implementation plan §7 is wired into `bank_to_audit_dict()` |

### 3c. `onboarding_case.bank_info` (live, unauthenticated write — the most important location)

New tests, likely extending `tests/integration/modules/onboarding/test_onboarding_public.py` and
`test_onboarding_review.py`:

| Test | Asserts |
|---|---|
| `test_onboarding_bank_info_is_encrypted_at_rest` | Direct raw-SQL read of `onboarding_case.bank_info ->> 'account_number_enc'` after a public wizard `PATCH` submission returns ciphertext, never plaintext — the single highest-priority test in this entire matrix, per the inventory's own finding that this location is the most easily overlooked |
| `test_candidate_read_back_shows_the_original_plaintext` | The candidate's own "my submission so far" endpoint decrypts and returns the value they submitted, unchanged |
| `test_hr_review_read_back_shows_the_original_plaintext` | Same, for the HR-facing case-detail endpoint |
| `test_activation_correctly_decrypts_before_constructing_bank_create` | After `activate_case`, the resulting `employee_bank.account_number_enc` row (itself encrypted per §3b, under its own AAD) decrypts to the **same** value the candidate originally submitted — proves the decrypt-then-re-encrypt handoff at activation (plan §6.9 Phase B, §15 item 6) doesn't corrupt or double-encrypt the value |
| `test_onboarding_case_account_number_key_is_removed_after_successful_activation` | With the default (clearing) design enabled (implementation plan §9.1): after `activate_case` commits, re-reading `onboarding_case.bank_info` shows the `account_number_enc` key absent entirely — not `null`, not a stale ciphertext — while sibling non-sensitive keys (`bank_name`, `branch_name`, `payment_mode`, `ifsc`, `account_holder_name`) are unchanged |
| `test_onboarding_cleanup_is_atomic_with_the_employee_bank_insert` | Simulate a failure between the `employee_bank` insert and the `bank_info` key removal (plan §9.1's atomicity requirement) — either both persist (on success) or neither does (on rollback); never a state where `employee_bank` exists but `bank_info` still holds a stale copy because the two writes weren't in the same transaction |
| `test_onboarding_cleanup_is_idempotent_on_retry` | Re-running activation's cleanup step against a case whose `account_number_enc` key is already absent (e.g. a retried activation after a prior partial failure) is a no-op, not an error (plan §9.1) |
| `test_onboarding_retention_alternative_keeps_the_value_encrypted` | With the retention alternative enabled instead (implementation plan §9.2) — a configuration this test exercises explicitly, not the default — `bank_info`'s `account_number_enc` key remains present after activation, and is still `v1:`-prefixed ciphertext, never plaintext |

---

## 4. Migration / backfill

New test file, e.g. `tests/integration/test_pii_encryption_backfill.py`, against a real (test)
database — matching this repository's existing convention of testing migrations/backfills against
real Postgres, not a mock:

| Test | Asserts |
|---|---|
| `test_backfill_on_an_empty_database` | Runs cleanly, discovery query (plan §6.1) reports zero rows, no error |
| `test_backfill_encrypts_a_single_plaintext_row` | One `employee_bank` row with a plaintext `account_number_enc`, seeded directly via raw SQL (bypassing the ORM's `EncryptedOnWrite` type, simulating pre-migration data) → after the backfill runs, the same row's raw column value is ciphertext, carries the current `key_version`, decrypts to the original value under its own AAD, and re-runs of the discovery query no longer count it as plaintext |
| `test_backfill_computes_the_correct_row_specific_aad` | The ciphertext the backfill produces for a given row decrypts successfully only under that row's own AAD (`table:column:record_id`, plan §2.4) — not under a different row's AAD, even one from the same table |
| `test_backfill_resolves_the_dek_once_per_run_not_per_row` | Backfilling a multi-row batch results in a bounded, small number of `kms:Decrypt`/`GenerateDataKey` calls (at most one per distinct key version touched), not one per row (plan §6.3's "DEK cache, not per-row KMS call" claim) |
| `test_backfill_on_a_larger_dataset` | A batch-sized-plus-one row count (e.g. 501 rows against a 500-row batch size, plan §6.3) — every row is migrated, none skipped, none double-processed |
| `test_backfill_skips_null_values` | Rows with `account_number_enc IS NULL` are left as `NULL`, not encrypted into `"v1:...(null)"` or similar |
| `test_backfill_is_a_no_op_on_already_encrypted_rows` | A row already holding a `v1:`-prefixed value is left untouched (byte-for-byte identical ciphertext before and after a backfill run) — direct proof of idempotency (plan §6.4) |
| `test_backfill_handles_partial_failure_and_resumes` | Simulate a KMS failure partway through a batch (e.g. the 3rd of 10 rows in a batch) → rows 1-2 are committed as encrypted; re-running the backfill completes rows 3-10 without re-processing 1-2 |
| `test_backfill_verification_matches_pre_migration_snapshot` | The snapshot-comparison step (plan §6.6) correctly flags a mismatch if a row's decrypted value does not match its recorded pre-migration plaintext (inject a deliberately wrong "expected" value in the test to prove the check is real, not a tautology) |
| `test_backfill_covers_all_four_locations` | A single test seeding plaintext rows in `employee.pan_number_enc`, `employee.aadhaar_number_enc`, `employee_bank.account_number_enc`, **and** `onboarding_case.bank_info` in the same run confirms all four are picked up — guards specifically against the "backfill only remembers the bank table" failure mode the inventory's §4 finding warns about |
| `test_concurrent_backfill_and_live_write_do_not_conflict` | A live `POST .../bank` write happening concurrently with a backfill pass touching a *different* row completes normally (`FOR UPDATE SKIP LOCKED`, plan §6.3) — not a strict requirement to automate as a true concurrency test, but at minimum a single-threaded simulation proving the `SKIP LOCKED` query shape behaves as expected |

---

## 5. Audit-log redaction (mandatory, implementation plan §7)

New unit test file, e.g. `tests/unit/core/test_audit_redaction.py`, plus integration coverage
folded into the existing banking tests (§3b above):

| Test | Asserts |
|---|---|
| `test_mask_account_number_shows_only_last_four_digits` | `mask_account_number("1234567890") == "******7890"` — matches the documented product format (inventory §8) exactly |
| `test_mask_pan_shows_first_five_and_last_one` | `mask_pan("ABCDE1234F") == "ABCDE****F"` — matches the documented format exactly |
| `test_mask_aadhaar_shows_last_four_only` | `mask_aadhaar("123456789012") == "XXXX XXXX 9012"`-shaped output — matches the documented format exactly |
| `test_mask_sensitive_only_touches_registered_fields` | `mask_sensitive()` applied to a dict with both sensitive and non-sensitive keys leaves every non-registered key (e.g. `bank_name`, `ifsc`, `is_primary`) byte-for-byte unchanged |
| `test_mask_sensitive_handles_a_null_sensitive_value` | A registered sensitive field whose value is `None` passes through as `None`, not an error from the mask function attempting to slice a `None` |
| `test_bank_to_audit_dict_never_contains_the_plaintext_account_number` | `bank_to_audit_dict(bank)` for a `BankRead` carrying a real-shaped account number returns a dict whose `account_number_enc` value is the masked form, never the plaintext and never the raw ciphertext blob |
| `test_pan_aadhaar_are_pre_registered_in_the_mask_registry` | `SENSITIVE_FIELD_MASKS` already contains `pan_number_enc`/`aadhaar_number_enc` entries even though no write path exists yet (plan §7.3) — so a future `employee_to_audit_dict()` cannot forget to redact them |
| `test_audit_masking_happens_before_the_record_call_not_after` | `AuditService.record()` is called (or its equivalent seam) with an already-masked payload — verified by asserting on the call arguments, not only on the persisted row, so a hypothetical future refactor that redacts too late is caught even if it happens to still pass the persisted-row assertion |

---

## 6. Historical audit-log remediation (implementation plan §8)

New test file, e.g. `tests/integration/test_pii_audit_log_remediation.py`, against a real (test)
database seeded with pre-existing, deliberately plaintext `audit_log` rows (simulating rows written
before this batch's redaction shipped):

| Test | Asserts |
|---|---|
| `test_detection_finds_plaintext_bank_audit_rows` | The detection query (plan §8.1) correctly identifies seeded `audit_log` rows whose `before_json`/`after_json` holds a non-`v1:`-prefixed `account_number_enc` value, and correctly excludes rows that are already masked or already ciphertext-shaped |
| `test_remediation_redacts_a_well_formed_historical_row` | A seeded row whose JSON matches the expected `BankRead`-derived shape is rewritten in place (`jsonb_set`) to the masked form, with every other field on the row (`action`, `occurred_at`, `actor_user_id`, `entity_id`) byte-for-byte unchanged |
| `test_remediation_flags_a_malformed_historical_row_for_manual_review_instead_of_rewriting_it` | A seeded row whose JSON does **not** match the expected shape (e.g. missing keys, a differently-structured legacy payload) is **not** auto-rewritten — it is reported in the "needs manual review" bucket (plan §8.4 Option C), proving the remediation does not assume uniform structure across every historical row |
| `test_remediation_is_idempotent` | Re-running remediation against an already-remediated row is a no-op (the detection query no longer selects it) |
| `test_remediation_never_touches_a_row_that_is_already_ciphertext_shaped` | A seeded row that (hypothetically) already holds a `v1:`-prefixed value in its audit JSON is left untouched — remediation targets plaintext specifically, not "every bank audit row" |
| `test_remediation_verification_confirms_zero_remaining_plaintext_rows_in_scope` | After remediation runs, re-running the detection query (plan §8.5) against the rows it processed returns zero for the "well-formed and still plaintext" bucket |
| `test_remediation_does_not_run_without_explicit_configuration` | The remediation script/task refuses to run against a target database without an explicit, named confirmation flag/argument — guards against it ever being invoked accidentally as part of an unrelated migration or deploy step, consistent with plan §8.7's sign-off-gated posture |

---

## 7. Search (explicit non-requirement, tested as a negative)

| Test | Asserts |
|---|---|
| `test_no_route_accepts_a_pan_aadhaar_or_account_number_query_parameter` | A structural/contract test over the router's declared query parameters for every Employee/Banking `GET` route — confirms the current "no lookup exists" state (inventory §6) doesn't silently regress if someone adds a filter parameter without realizing it would need to operate on ciphertext |
| `test_no_plaintext_search_leakage_via_error_messages` | Submitting a malformed/oversized value to a field that will become encrypted does not echo the submitted value back in a `422` validation error message in a way that would differ from today's behavior (guards against a validator that logs or echoes the raw value while ostensibly just checking length/format) |

If a blind index is ever built (implementation plan §3's documented-but-not-implemented design):

| Test (future, not this batch) | Asserts |
|---|---|
| `test_blind_index_finds_the_correct_record_by_normalized_value` | An HMAC blind-index lookup for a known value returns the correct row |
| `test_blind_index_normalizes_before_hashing` | Two differently-cased/whitespace-padded submissions of the same PAN produce the same blind-index value and both find the same record |
| `test_blind_index_key_is_separate_from_the_encryption_key` | Rotating the blind-index key does not require re-encrypting the ciphertext column, and vice versa (proves key separation, plan §3) |

---

## 8. Logging

| Test | Asserts |
|---|---|
| `test_backfill_log_lines_contain_no_sensitive_values` | Capture the backfill job's log output (structlog, matching this codebase's existing convention) across a run touching real-shaped plaintext values → assert none of the submitted values, and none of the row-specific AAD strings' underlying plaintext, appear anywhere in the captured log text, only counts/ids/table names/key versions (plan §6.5) |
| `test_kms_failure_error_response_contains_no_sensitive_value` | The `503`-shaped (or equivalent) error response surfaced on a KMS outage (§1's key-management tests) never includes the plaintext value that failed to decrypt/encrypt, nor the raw ciphertext, in its message body |
| `test_no_sensitive_value_in_an_unhandled_exception_path` | A forced, unexpected exception during an encrypt/decrypt call does not surface the plaintext in whatever the generic exception handler currently does with it (cross-check against `OBS-01`'s existing "`_ = exc`" behavior — this test should still pass today, and continue to pass, precisely because today's handler already discards the exception object; it exists here to catch a regression if `OBS-01` is fixed in a way that starts logging exception details without first stripping sensitive locals) |
| `test_audit_log_redaction_is_mandatory_not_conditional` | `AuditLog.before_json`/`after_json` never contain the plaintext account number after any bank write in this batch — unlike the first draft of this plan, this is no longer a "which of two options was chosen" test (implementation plan §7 made redaction mandatory); §6 above separately covers the historical-row remediation decision for rows that predate this batch |

---

## 9. Regression

Full existing suite, explicitly re-run and confirmed unaffected beyond "the stored value is now
ciphertext" (per `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own regression-verification style):

| Area | Existing test file(s) | Expected result |
|---|---|---|
| Employee creation/update | `tests/unit/modules/employee/test_employee_service.py`, `tests/integration/modules/employee/test_employee.py` | Pass unchanged — neither currently touches PAN/Aadhaar (inventory §2) |
| Employee banking creation/read | `tests/unit/modules/employee/test_employee_bank_service.py`, `tests/integration/modules/employee/test_employee_banking.py` | Pass, with the synthetic `"1234567890"` value now round-tripping through real encryption instead of being stored verbatim |
| Onboarding public wizard | `tests/integration/modules/onboarding/test_onboarding_public.py` | Pass, same reasoning |
| Onboarding review | `tests/integration/modules/onboarding/test_onboarding_review.py` | Pass |
| Onboarding documents (PAN/Aadhaar scanned uploads) | `tests/integration/modules/onboarding/test_onboarding_documents.py` | Pass, unaffected — these test the S3-stored document image, not a plaintext number field (inventory §2 item 8) |
| Employee assignment/compensation/statutory (fixtures referencing `pan_number_enc`/`aadhaar_number_enc: None`) | `tests/unit/modules/employee/test_employee_assignment_service.py`, `test_employee_compensation_service.py`, `test_employee_statutory_service.py`, `test_employment_service.py` | Pass unchanged — these fixtures set both to `None`, and `None` continues to pass through the new `EncryptedOnWrite` type as `None` (plan §4, null-handling row) |
| Full backend suite + mypy + ruff | (as established by `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own convention) | Zero new failures attributable to this batch; any pre-existing unrelated failure (e.g. the RBAC permission-set assertion already documented as pre-existing in that report) reconfirmed as still pre-existing, not newly caused |

---

## Summary

This matrix is written to be executable as-is once the implementation batch exists — every test
name is specific enough to serve as a checklist item, and every row cites the exact inventory/plan
section it verifies. No test in this matrix has been run; this document is planning only.
