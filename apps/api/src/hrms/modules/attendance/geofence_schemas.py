"""Request/response models for the geofence administration surface."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GeofenceWorkplaceRead(BaseModel):
    """A branch viewed as a workplace geofence. Coordinates are edited through the branch screen
    (`PATCH /branches/{id}`); this is the attendance-side view with usage counts."""

    branch_id: UUID
    name: str
    code: str | None
    is_active: bool
    latitude: float | None
    longitude: float | None
    radius_m: int | None
    #: True when the branch has coordinates and a radius, i.e. can act as a geofence.
    configured: bool
    assigned_employee_count: int
    authorized_employee_count: int


class GeofencePolicyMeRead(BaseModel):
    """The caller's own location requirement, so the app knows whether to capture a fix before a
    punch. Informational: the server re-evaluates every punch and a client cannot loosen it."""

    mode: str
    max_accuracy_m: int
    max_age_seconds: int


class WorkplaceAuthorizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    branch_id: UUID


class WorkplaceAuthorizationRead(BaseModel):
    id: UUID
    employee_id: UUID
    branch_id: UUID
    created_by_user_id: UUID | None
    created_at: str


class GeofenceAttemptRead(BaseModel):
    id: UUID
    employee_id: UUID
    punch_id: UUID | None
    direction: str
    source: str
    mode: str
    outcome: str
    accepted: bool
    branch_id: UUID | None
    distance_m: Decimal | None
    radius_m: Decimal | None
    accuracy_m: Decimal | None
    #: Rounded to 4 decimal places (~11 m) at write time; null when no fix was reported.
    latitude: Decimal | None
    longitude: Decimal | None
    captured_at: str | None
    client_error: str | None
    created_at: str


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def attempt_to_read(row: Any) -> GeofenceAttemptRead:
    return GeofenceAttemptRead(
        id=row.id,
        employee_id=row.employee_id,
        punch_id=row.punch_id,
        direction=row.direction,
        source=row.source,
        mode=row.mode,
        outcome=row.outcome,
        accepted=row.accepted,
        branch_id=row.branch_id,
        distance_m=row.distance_m,
        radius_m=row.radius_m,
        accuracy_m=row.accuracy_m,
        latitude=row.latitude,
        longitude=row.longitude,
        captured_at=_ts(row.captured_at),
        client_error=row.client_error,
        created_at=_ts(row.created_at) or "",
    )


def authorization_to_read(row: Any) -> WorkplaceAuthorizationRead:
    return WorkplaceAuthorizationRead(
        id=row.id,
        employee_id=row.employee_id,
        branch_id=row.branch_id,
        created_by_user_id=row.created_by_user_id,
        created_at=_ts(row.created_at) or "",
    )
