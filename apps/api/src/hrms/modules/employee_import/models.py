"""ORM models owned by the employee_import module."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class EmployeeImportBatch(Base, TimestampMixin):
    __tablename__ = "employee_import_batch"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company.id"))
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    original_filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(Text)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmployeeImportRowError(Base):
    __tablename__ = "employee_import_row_error"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee_import_batch.id", ondelete="CASCADE")
    )
    company_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company.id"))
    row_number: Mapped[int] = mapped_column(Integer)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error_code: Mapped[str] = mapped_column(String(60))
    error_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
