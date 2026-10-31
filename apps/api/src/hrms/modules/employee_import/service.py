"""Business logic for employee_import.

`EmployeeImportService.create_batch` runs synchronously inside the upload request (parses and
validates the CSV shape, stores the file, inserts the batch row, enqueues the Celery task).
`process_batch` runs inside the Celery task (`tasks.py`) against its own session — it is the
actual row-by-row pipeline, driving `employee.service`'s existing `EmployeeService`/
`EmploymentService`/`EmployeeAssignmentService`/`EmployeeCompensationService` per row rather than
reimplementing employee-creation logic, so an imported employee is validated identically to one
created through the interactive API.
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.base import AppError, ValidationError
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.storage import DocumentStorageService
from hrms.modules.employee.schemas import (
    AssignmentCreate,
    CompensationCreate,
    EmployeeCreate,
    EmploymentCreate,
)
from hrms.modules.employee.service import (
    EmployeeAssignmentService,
    EmployeeCompensationService,
    EmployeeService,
    EmploymentService,
)
from hrms.modules.employee_import.exceptions import (
    ImportBatchNotFoundError,
    ImportFileEmptyError,
    ImportFileTooLargeError,
    ImportFileUnreadableError,
    ImportHeaderInvalidError,
    ImportQueueUnavailableError,
    ImportRowLimitExceededError,
)
from hrms.modules.employee_import.repository import EmployeeImportRepository
from hrms.modules.employee_import.schemas import (
    ALL_COLUMNS,
    MAX_IMPORT_FILE_SIZE_BYTES,
    MAX_IMPORT_ROWS,
    REQUIRED_COLUMNS,
    EmployeeImportBatchRead,
    EmployeeImportRow,
    EmployeeImportRowErrorRead,
    batch_to_read,
    row_error_to_read,
)
from hrms.modules.organisation.service import OrganisationService

_logger = get_logger(__name__)

#: How often (in rows) the batch's progress counters are flushed to the DB mid-run, so
#: `GET /employee-imports/{id}` shows live progress on a large file instead of only at the end.
_PROGRESS_FLUSH_INTERVAL = 25


def _index_by_code_or_name(
    items: Sequence[Any], *, code_attr: str = "code", name_attr: str = "name"
) -> dict[str, UUID]:
    """Builds a lowercase code/name -> id lookup from one of `OrganisationService`'s `list_*`
    results. Tries `code_attr` first (`setdefault` on the name so a code match always wins a
    collision), falls back to `name_attr` — matches this plan's "code first, case-insensitive
    name otherwise" resolution rule for every org-structure reference column. `getattr(...,
    None)` defaults make this safe for `LegalEntityRead`, which has no `code` field at all."""
    index: dict[str, UUID] = {}
    for item in items:
        item_id: UUID = item.id
        code = getattr(item, code_attr, None)
        if code:
            index[str(code).strip().lower()] = item_id
        name = getattr(item, name_attr, None)
        if name:
            index.setdefault(str(name).strip().lower(), item_id)
    return index


def _lookup(index: dict[str, UUID], value: str, *, field_name: str) -> UUID:
    resolved = index.get(value.strip().lower())
    if resolved is None:
        raise ValidationError(
            f"{field_name} '{value}' does not match any {field_name} in this company"
        )
    return resolved


def _sanitize_raw_row(row: dict[str, str | None]) -> dict[str, str]:
    """`csv.DictReader` can produce a `None` key (`restkey`, extra columns on a malformed data
    row) or `None` values (`restval`, a short row) — neither is valid JSONB. The header is
    already validated exact-match at upload time, so this only guards a malformed *data* row,
    not the common case."""
    return {str(k): (v if v is not None else "") for k, v in row.items() if k is not None}


@dataclass
class _ResolvedReferences:
    legal_entity_id: UUID
    branch_id: UUID
    department_id: UUID
    designation_id: UUID
    grade_id: UUID | None
    reporting_manager_id: UUID | None


class EmployeeImportService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeImportRepository()
        self._storage = DocumentStorageService(self._settings)

    # ------------------------------------------------------------------
    # Upload (synchronous — runs inside the HTTP request)
    # ------------------------------------------------------------------

    async def create_batch(
        self,
        company_id: UUID,
        *,
        filename: str,
        file_bytes: bytes,
        actor_user_id: UUID | None,
    ) -> EmployeeImportBatchRead:
        # SEC-03 — checked before parsing, same posture as onboarding's
        # `OnboardingDocumentTooLargeError`; `MAX_IMPORT_ROWS` only catches an oversized file
        # *after* it has already been decoded and split into rows.
        if len(file_bytes) > MAX_IMPORT_FILE_SIZE_BYTES:
            raise ImportFileTooLargeError(MAX_IMPORT_FILE_SIZE_BYTES)
        rows = self._parse_and_validate_shape(file_bytes)

        now = datetime.now(UTC)
        batch_id = uuid4()
        # SEC-04 — the object-key filename component is always this fixed literal, never the
        # client-supplied `filename` (path-traversal/unsafe-key risk); `batch_id` already makes
        # the key unique, and the format is always CSV (`_parse_and_validate_shape` above already
        # requires it). The client-supplied `filename` is retained only as display metadata
        # (`original_filename` below), same split as onboarding documents.
        s3_key = f"employee-imports/{company_id}/{batch_id}/import.csv"
        # Storage write happens before the DB row so a storage failure never leaves a batch row
        # pointing at a nonexistent object.
        await self._storage.put_object(key=s3_key, body=file_bytes, content_type="text/csv")

        batch = await self._repo.insert_batch(
            self._session,
            data={
                "id": batch_id,
                "company_id": company_id,
                "status": "PENDING",
                "original_filename": filename,
                "s3_key": s3_key,
                "total_rows": len(rows),
                "processed_rows": 0,
                "success_count": 0,
                "error_count": 0,
                "created_by": actor_user_id,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            },
        )
        # Explicit commit before enqueueing: the Celery task opens its own session/connection
        # and can start running before this request's own `get_session` dependency commits at
        # the end of the request — without this, the task could query a batch row that isn't
        # visible yet on its connection. The commit clears the transaction-local RLS variable, so it
        # is restored for the `FAILED` update below should the publish fail.
        await self._commit_and_restore_rls(company_id)

        from hrms.modules.employee_import.tasks import process_batch

        actor_user_id_arg = str(actor_user_id) if actor_user_id is not None else None
        try:
            process_batch.delay(str(company_id), str(batch_id), actor_user_id_arg)
        except Exception as exc:  # noqa: BLE001 — any broker/publish failure, see below
            # The batch row is already committed. Without this, an unreachable broker left it
            # PENDING forever with no message behind it (and the caller saw a bare 500). Close it
            # as FAILED so no operator mistakes it for queued work, say so in the log, and tell the
            # client nothing was imported so it can upload again.
            now = datetime.now(UTC)
            await self._repo.update_batch_progress(
                self._session,
                company_id=company_id,
                batch_id=batch_id,
                values={"status": "FAILED", "completed_at": now},
                now=now,
            )
            await self._session.commit()
            safe_log(
                _logger.error,
                "employee_import.batch.enqueue_failed",
                company_id=str(company_id),
                batch_id=str(batch_id),
                **safe_error(exc),
            )
            raise ImportQueueUnavailableError() from exc

        return batch_to_read(batch)

    def _parse_and_validate_shape(self, file_bytes: bytes) -> list[dict[str, str]]:
        try:
            text_content = file_bytes.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text_content))
            header = reader.fieldnames or []
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ImportFileUnreadableError() from exc
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        unexpected = [c for c in header if c not in ALL_COLUMNS]
        if missing or unexpected:
            raise ImportHeaderInvalidError(missing=missing, unexpected=unexpected)

        try:
            rows = [_sanitize_raw_row(row) for row in reader]
        except csv.Error as exc:
            raise ImportFileUnreadableError() from exc
        if not rows:
            raise ImportFileEmptyError()
        if len(rows) > MAX_IMPORT_ROWS:
            raise ImportRowLimitExceededError(row_count=len(rows), limit=MAX_IMPORT_ROWS)
        return rows

    def get_template(self) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(ALL_COLUMNS))
        writer.writeheader()
        writer.writerow(
            {
                "employee_code": "",
                "first_name": "Priya",
                "middle_name": "",
                "last_name": "Sharma",
                "date_of_birth": "1995-06-12",
                "gender": "FEMALE",
                "blood_group": "",
                "marital_status": "",
                "nationality": "Indian",
                "personal_email": "priya.sharma@example.com",
                "personal_mobile": "9876543210",
                "legal_entity": "Acme Manufacturing Pvt Ltd",
                "branch": "HO-BLR",
                "department": "Engineering",
                "designation": "Software Engineer",
                "grade": "",
                "reporting_manager": "",
                "work_location_type": "OFFICE",
                "joining_date": "2026-09-15",
                "annual_ctc_minor": "120000000",
                "currency": "INR",
            }
        )
        return buffer.getvalue()

    async def get_reference_data(self, company_id: UUID) -> dict[str, list[dict[str, str]]]:
        organisation = OrganisationService(self._session, self._settings)
        return {
            "legal_entities": [
                {"name": e.name} for e in await organisation.list_legal_entities(company_id)
            ],
            "branches": [
                {"code": b.code or "", "name": b.name}
                for b in await organisation.list_branches(company_id)
            ],
            "departments": [
                {"code": d.code or "", "name": d.name}
                for d in await organisation.list_departments(company_id)
            ],
            "designations": [
                {"code": d.code or "", "name": d.title}
                for d in await organisation.list_designations(company_id)
            ],
            "grades": [
                {"code": g.code, "name": g.name} for g in await organisation.list_grades(company_id)
            ],
        }

    # ------------------------------------------------------------------
    # Status / errors (read paths)
    # ------------------------------------------------------------------

    async def get_batch(self, company_id: UUID, batch_id: UUID) -> EmployeeImportBatchRead:
        batch = await self._repo.get_batch(self._session, company_id=company_id, batch_id=batch_id)
        if batch is None:
            raise ImportBatchNotFoundError()
        return batch_to_read(batch)

    async def list_row_errors(
        self, company_id: UUID, batch_id: UUID
    ) -> list[EmployeeImportRowErrorRead]:
        await self.get_batch(company_id, batch_id)  # 404s a nonexistent/cross-tenant batch first
        errors = await self._repo.list_row_errors(
            self._session, company_id=company_id, batch_id=batch_id
        )
        return [row_error_to_read(error) for error in errors]

    # ------------------------------------------------------------------
    # Processing pipeline (runs inside the Celery task's own session)
    # ------------------------------------------------------------------

    async def process_batch(
        self, company_id: UUID, batch_id: UUID, actor_user_id: UUID | None
    ) -> None:
        batch = await self._repo.get_batch(self._session, company_id=company_id, batch_id=batch_id)
        ids = {"company_id": str(company_id), "batch_id": str(batch_id)}
        if batch is None:
            # A message for a batch that no longer exists (e.g. deleted test data in a stale
            # queue). Nothing to do, but no longer silent.
            safe_log(_logger.warning, "employee_import.batch.skipped", reason="missing", **ids)
            return

        # Idempotency guard: only a PENDING batch is processed, claimed atomically. The pipeline
        # is create-only, so running a batch a second time (a redelivered or duplicated message,
        # a manual re-enqueue) would create duplicate employees for rows without a colliding
        # `employee_code`. A normally pending batch is processed exactly as before. This does
        # NOT decide whether an *old* PENDING batch should still run — see decision D-B in
        # `docs/audits/LOGGING_ERROR_HANDLING_AUTONOMOUS_EXECUTION_REPORT.md`.
        now = datetime.now(UTC)
        if not await self._repo.claim_pending_batch(
            self._session, company_id=company_id, batch_id=batch_id, now=now
        ):
            safe_log(
                _logger.warning,
                "employee_import.batch.skipped",
                reason="not_pending",
                status=batch.status,
                **ids,
            )
            return
        await self._commit_and_restore_rls(company_id)
        started = datetime.now(UTC)

        try:
            file_bytes = await self._storage.get_object(key=batch.s3_key)
        except Exception as exc:  # noqa: BLE001 — must catch every storage failure, not just botocore's
            # Storage unavailable (MinIO down, bad credentials, missing bucket, ...): leave the
            # batch in a terminal FAILED state rather than stuck at PROCESSING forever with no
            # operator-visible outcome. Re-raised so the Celery task itself still records/logs
            # the failure (Document 11 §1) — this only closes out the DB-visible batch status.
            await self._repo.update_batch_progress(
                self._session,
                company_id=company_id,
                batch_id=batch_id,
                values={"status": "FAILED", "completed_at": datetime.now(UTC)},
                now=datetime.now(UTC),
            )
            await self._session.commit()
            # Compact: the Celery failure record that follows carries the traceback.
            safe_log(
                _logger.error, "employee_import.batch.storage_failed", **ids, **safe_error(exc)
            )
            raise

        rows = [
            _sanitize_raw_row(row)
            for row in csv.DictReader(io.StringIO(file_bytes.decode("utf-8-sig")))
        ]

        organisation = OrganisationService(self._session, self._settings)
        legal_entities = _index_by_code_or_name(await organisation.list_legal_entities(company_id))
        branches = _index_by_code_or_name(await organisation.list_branches(company_id))
        departments = _index_by_code_or_name(await organisation.list_departments(company_id))
        designations = _index_by_code_or_name(
            await organisation.list_designations(company_id), name_attr="title"
        )
        grades = _index_by_code_or_name(await organisation.list_grades(company_id))

        employee_service = EmployeeService(self._session, self._settings)
        employment_service = EmploymentService(self._session, self._settings)
        assignment_service = EmployeeAssignmentService(self._session, self._settings)
        compensation_service = EmployeeCompensationService(self._session, self._settings)

        success_count = 0
        error_count = 0
        for index, raw_row in enumerate(rows):
            row_number = index + 2  # +1 for 1-indexing, +1 for the header row
            try:
                async with self._session.begin_nested():
                    parsed = EmployeeImportRow.model_validate(raw_row)
                    resolved = await self._resolve_row(
                        parsed,
                        company_id=company_id,
                        legal_entities=legal_entities,
                        branches=branches,
                        departments=departments,
                        designations=designations,
                        grades=grades,
                        employee_service=employee_service,
                    )
                    await self._create_employee_row(
                        parsed,
                        resolved,
                        company_id=company_id,
                        actor_user_id=actor_user_id,
                        employee_service=employee_service,
                        employment_service=employment_service,
                        assignment_service=assignment_service,
                        compensation_service=compensation_service,
                    )
                success_count += 1
            except Exception as exc:  # noqa: BLE001 — one bad row must never abort the batch
                error_count += 1
                await self._record_row_error(company_id, batch_id, row_number, raw_row, exc)

            if (index + 1) % _PROGRESS_FLUSH_INTERVAL == 0:
                await self._flush_progress(
                    company_id, batch_id, index + 1, success_count, error_count
                )

        final_status = (
            "COMPLETED"
            if error_count == 0
            else "FAILED"
            if success_count == 0
            else "COMPLETED_WITH_ERRORS"
        )
        completed_now = datetime.now(UTC)
        await self._repo.update_batch_progress(
            self._session,
            company_id=company_id,
            batch_id=batch_id,
            values={
                "status": final_status,
                "processed_rows": len(rows),
                "success_count": success_count,
                "error_count": error_count,
                "completed_at": completed_now,
            },
            now=completed_now,
        )
        await self._session.commit()
        safe_log(
            _logger.warning if error_count else _logger.info,
            "employee_import.batch.finished",
            status=final_status,
            processed_rows=len(rows),
            success_count=success_count,
            error_count=error_count,
            duration_ms=round((completed_now - started).total_seconds() * 1000, 1),
            **ids,
        )

    async def _resolve_row(
        self,
        parsed: EmployeeImportRow,
        *,
        company_id: UUID,
        legal_entities: dict[str, UUID],
        branches: dict[str, UUID],
        departments: dict[str, UUID],
        designations: dict[str, UUID],
        grades: dict[str, UUID],
        employee_service: EmployeeService,
    ) -> _ResolvedReferences:
        reporting_manager_id: UUID | None = None
        if parsed.reporting_manager is not None:
            manager = await employee_service.find_employee_by_code_or_email(
                company_id, parsed.reporting_manager
            )
            if manager is None:
                raise ValidationError(
                    f"reporting_manager '{parsed.reporting_manager}' does not match any"
                    " employee_code or personal_email in this company"
                )
            reporting_manager_id = manager.id

        return _ResolvedReferences(
            legal_entity_id=_lookup(legal_entities, parsed.legal_entity, field_name="legal_entity"),
            branch_id=_lookup(branches, parsed.branch, field_name="branch"),
            department_id=_lookup(departments, parsed.department, field_name="department"),
            designation_id=_lookup(designations, parsed.designation, field_name="designation"),
            grade_id=_lookup(grades, parsed.grade, field_name="grade") if parsed.grade else None,
            reporting_manager_id=reporting_manager_id,
        )

    async def _create_employee_row(
        self,
        parsed: EmployeeImportRow,
        resolved: _ResolvedReferences,
        *,
        company_id: UUID,
        actor_user_id: UUID | None,
        employee_service: EmployeeService,
        employment_service: EmploymentService,
        assignment_service: EmployeeAssignmentService,
        compensation_service: EmployeeCompensationService,
    ) -> None:
        employee = await employee_service.create_employee(
            company_id,
            EmployeeCreate(
                first_name=parsed.first_name,
                middle_name=parsed.middle_name,
                last_name=parsed.last_name,
                date_of_birth=parsed.date_of_birth,
                gender=parsed.gender,
                blood_group=parsed.blood_group,
                marital_status=parsed.marital_status,
                nationality=parsed.nationality,
                personal_email=parsed.personal_email,
                personal_mobile=parsed.personal_mobile,
            ),
            actor_user_id=actor_user_id,
            employee_code_override=parsed.employee_code,
        )

        # `scope=None`/`caller_employee_id=None` on every call below: the same "internal
        # caller, unscoped" convention `EmployeeAssignmentService._assert_employee_visible`'s
        # own docstring describes for callers other than the interactive routes — a freshly
        # bulk-created employee has no meaningful visibility restriction to apply against the
        # importing admin, who already holds `EMPLOYEE.BULK_IMPORT` at the router level.
        await employment_service.create_employment(
            company_id,
            employee.id,
            EmploymentCreate(
                legal_entity_id=resolved.legal_entity_id, joining_date=parsed.joining_date
            ),
            actor_user_id=actor_user_id,
            scope=None,
            caller_employee_id=None,
        )

        await assignment_service.create_assignment(
            company_id,
            employee.id,
            AssignmentCreate(
                effective_from=parsed.joining_date,
                change_type="INITIAL",
                branch_id=resolved.branch_id,
                department_id=resolved.department_id,
                designation_id=resolved.designation_id,
                grade_id=resolved.grade_id,
                reporting_manager_id=resolved.reporting_manager_id,
                work_location_type=parsed.work_location_type,
            ),
            expected_version=None,
            actor_user_id=actor_user_id,
            scope=None,
            caller_employee_id=None,
        )

        await compensation_service.create_compensation(
            company_id,
            employee.id,
            CompensationCreate(
                effective_from=parsed.joining_date,
                annual_ctc_minor=parsed.annual_ctc_minor,
                currency=parsed.currency,
                revision_type="JOINING",
                revision_reason="Bulk import",
            ),
            expected_version=None,
            actor_user_id=actor_user_id,
            scope=None,
            caller_employee_id=None,
        )

    async def _record_row_error(
        self,
        company_id: UUID,
        batch_id: UUID,
        row_number: int,
        raw_row: dict[str, str],
        exc: Exception,
    ) -> None:
        if isinstance(exc, PydanticValidationError):
            code = "VALIDATION_ERROR"
            message = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        elif isinstance(exc, AppError):
            code = exc.code
            message = exc.message
        else:
            code = "IMPORT_ROW_FAILED"
            message = str(exc)

        await self._repo.insert_row_error(
            self._session,
            data={
                "id": uuid4(),
                "batch_id": batch_id,
                "company_id": company_id,
                "row_number": row_number,
                "raw_row": raw_row,
                "error_code": code,
                "error_message": message,
                "created_at": datetime.now(UTC),
            },
        )

    async def _flush_progress(
        self, company_id: UUID, batch_id: UUID, processed: int, success: int, errors: int
    ) -> None:
        await self._repo.update_batch_progress(
            self._session,
            company_id=company_id,
            batch_id=batch_id,
            values={"processed_rows": processed, "success_count": success, "error_count": errors},
            now=datetime.now(UTC),
        )
        await self._commit_and_restore_rls(company_id)

    async def _commit_and_restore_rls(self, company_id: UUID) -> None:
        """`set_rls_company_id` sets the `app.company_id` GUC with `is_local=true`
        (`core/db/session.py`) — scoped to the current transaction only, per Postgres's own
        `set_config` semantics. `process_batch` commits mid-run (progress flushes, the
        `PROCESSING` status write) so the RLS predicate on every tenant table's policy would
        silently see an empty/unset `app.company_id` on the next query after any of those
        commits, without this: `session_scope` only applies it once, at the very start of the
        task, and never anticipated a caller committing more than once inside its lifetime."""
        await self._session.commit()
        await set_rls_company_id(self._session, str(company_id))
