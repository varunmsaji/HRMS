"""Multipart (form-field) variant of the punch location, for the face-punch endpoint."""

from datetime import datetime

from pydantic import ValidationError as PydanticValidationError

from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.geofence import CLIENT_LOCATION_ERRORS
from hrms.modules.attendance.schemas import PunchLocation


def parse_form_location(
    *,
    latitude: float | None,
    longitude: float | None,
    accuracy_m: float | None,
    captured_at: datetime | None,
    error: str | None,
) -> PunchLocation | None:
    """All four position fields or none. `error` (the app could not get a fix) excludes them."""
    if error is not None and error not in CLIENT_LOCATION_ERRORS:
        raise ValidationError(f"location_error must be one of {CLIENT_LOCATION_ERRORS}")
    given = [v is not None for v in (latitude, longitude, accuracy_m, captured_at)]
    if not any(given):
        return None
    if error is not None:
        raise ValidationError("send either a location or location_error, not both")
    if not all(given):
        raise ValidationError(
            "location_latitude, location_longitude, location_accuracy_m and "
            "location_captured_at must be sent together"
        )
    try:
        return PunchLocation(
            latitude=latitude,  # type: ignore[arg-type]
            longitude=longitude,  # type: ignore[arg-type]
            accuracy_m=accuracy_m,  # type: ignore[arg-type]
            captured_at=captured_at,  # type: ignore[arg-type]
        )
    except PydanticValidationError as exc:
        raise ValidationError("The reported location is not valid") from exc
