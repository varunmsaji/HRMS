"""Geofence decision rules for self-service punches — pure functions, no I/O.

Everything the server decides about a device-reported location lives here so the rules are
deterministic and unit-testable without a database. The service layer (`geofence_service`) only
gathers trusted inputs (policy version, applicable workplaces, the server clock) and persists the
outcome.

**What this proves and what it does not.** A latitude/longitude/accuracy triple is *reported by
the device*. A rooted or developer-mode phone, a mock-location app or an emulator can report any
position, and the server has no independent view of where the handset physically is. A geofence
acceptance therefore means "the device claimed a position inside an approved workplace, with a
fresh timestamp and acceptable stated accuracy" — never proof of physical presence. The checks
below reduce honest-mistake and casual-misuse risk; they are not anti-spoofing. Corroboration
(face verification, IP/device signals, HR review of the recorded attempts) is a separate layer.

Decision order (first failing rule wins, so the outcome is deterministic):

1. malformed location (non-finite / out-of-range numbers, naive timestamp) -> LOCATION_INVALID
2. capture time more than FUTURE_SKEW_SECONDS ahead of the server clock    -> LOCATION_INVALID
3. capture older than the policy's max_age_seconds                          -> LOCATION_STALE
4. reported horizontal accuracy worse than the policy's max_accuracy_m -> LOCATION_TOO_INACCURATE
5. no applicable workplace with usable coordinates -> NO_APPLICABLE_WORKPLACE
6. distance to the nearest applicable workplace centre <= radius            -> INSIDE
7. otherwise                                                                -> OUTSIDE_GEOFENCE
   (sub-case OUTSIDE_GEOFENCE_UNCERTAIN when distance - accuracy <= radius: the reported point is
   outside but the device's own error circle reaches the fence, so the app should tell the
   employee to improve the fix and retry. The punch is still refused.)

The radius is never widened to compensate for poor accuracy, and a client can neither supply nor
loosen the accuracy/age thresholds: they come from the published policy version.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

#: Mean Earth radius (IUGG), metres. Haversine on a sphere is within ~0.5% of WGS84 geodesic
#: distance — ample for fences of tens to thousands of metres, and cheap and dependency-free.
EARTH_RADIUS_M = 6_371_008.8

#: A device clock that is slightly fast must not turn a fresh fix into "invalid". Anything beyond
#: this is treated as a bad or manipulated timestamp.
FUTURE_SKEW_SECONDS = 30

GEOFENCE_MODES = ("DISABLED", "OPTIONAL", "REQUIRED")

#: Bounds enforced both by the API schema and by DB CHECK constraints.
ACCURACY_LIMIT_MIN_M = 5
ACCURACY_LIMIT_MAX_M = 500
MAX_AGE_MIN_SECONDS = 5
MAX_AGE_MAX_SECONDS = 300

# Outcomes ------------------------------------------------------------------------------------
INSIDE = "INSIDE"
OUTSIDE_GEOFENCE = "OUTSIDE_GEOFENCE"
OUTSIDE_GEOFENCE_UNCERTAIN = "OUTSIDE_GEOFENCE_UNCERTAIN"
LOCATION_TOO_INACCURATE = "LOCATION_TOO_INACCURATE"
LOCATION_STALE = "LOCATION_STALE"
LOCATION_INVALID = "LOCATION_INVALID"
LOCATION_REQUIRED = "LOCATION_REQUIRED"
LOCATION_UNAVAILABLE_CLIENT = "LOCATION_UNAVAILABLE_CLIENT"
NO_APPLICABLE_WORKPLACE = "NO_APPLICABLE_WORKPLACE"
#: OPTIONAL mode with no location supplied — recorded, never blocks.
NOT_PROVIDED = "NOT_PROVIDED"

CLIENT_LOCATION_ERRORS = (
    "PERMISSION_DENIED",
    "PERMISSION_DENIED_FOREVER",
    "SERVICES_DISABLED",
    "TIMEOUT",
    "UNAVAILABLE",
)


@dataclass(frozen=True)
class ReportedLocation:
    latitude: float
    longitude: float
    accuracy_m: float
    captured_at: datetime


@dataclass(frozen=True)
class Workplace:
    """A workplace geofence resolved from trusted server-side data (a `Branch` row)."""

    branch_id: UUID
    name: str
    latitude: float
    longitude: float
    radius_m: float


@dataclass(frozen=True)
class GeofencePolicy:
    mode: str
    max_accuracy_m: int
    max_age_seconds: int


@dataclass(frozen=True)
class GeofenceDecision:
    outcome: str
    #: True when the punch may proceed. Under OPTIONAL a non-INSIDE outcome is still recorded but
    #: never blocks (see `decide`).
    allowed: bool
    enforced: bool
    branch_id: UUID | None = None
    distance_m: float | None = None
    radius_m: float | None = None
    accuracy_m: float | None = None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points given in decimal degrees."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def validate_location(location: ReportedLocation) -> bool:
    """True when every number is finite and in range and the timestamp is timezone-aware."""
    values = (location.latitude, location.longitude, location.accuracy_m)
    if not all(math.isfinite(v) for v in values):
        return False
    if not -90.0 <= location.latitude <= 90.0:
        return False
    if not -180.0 <= location.longitude <= 180.0:
        return False
    if location.accuracy_m < 0:
        return False
    return location.captured_at.tzinfo is not None


def _round_m(value: float) -> float:
    # Compare on centimetres so the boundary is stable against float noise from the trig.
    return round(value, 2)


def nearest_workplace(
    latitude: float, longitude: float, workplaces: Sequence[Workplace]
) -> tuple[Workplace, float] | None:
    """The workplace the point is closest to (by margin inside/outside its own radius), with the
    distance to its centre. Deterministic: ties on margin break on the smaller branch id."""
    best: tuple[float, str, Workplace, float] | None = None
    for workplace in workplaces:
        distance = _round_m(
            haversine_m(latitude, longitude, workplace.latitude, workplace.longitude)
        )
        key = (distance - workplace.radius_m, str(workplace.branch_id))
        if best is None or key < (best[0], best[1]):
            best = (key[0], key[1], workplace, distance)
    if best is None:
        return None
    return best[2], best[3]


def decide(
    *,
    policy: GeofencePolicy,
    location: ReportedLocation | None,
    client_error: str | None,
    workplaces: Sequence[Workplace],
    now: datetime,
) -> GeofenceDecision:
    """The single decision function. `now` is the server clock (UTC)."""
    if policy.mode == "DISABLED":
        # Existing behaviour is untouched: nothing is evaluated, recorded or returned.
        return GeofenceDecision(outcome=NOT_PROVIDED, allowed=True, enforced=False)

    enforced = policy.mode == "REQUIRED"

    def result(outcome: str, **extra: object) -> GeofenceDecision:
        allowed = outcome == INSIDE or not enforced
        return GeofenceDecision(outcome=outcome, allowed=allowed, enforced=enforced, **extra)  # type: ignore[arg-type]

    if location is None:
        if client_error is not None:
            return result(LOCATION_UNAVAILABLE_CLIENT)
        return result(NOT_PROVIDED if not enforced else LOCATION_REQUIRED)

    accuracy = float(location.accuracy_m) if math.isfinite(location.accuracy_m) else None
    if not validate_location(location):
        return result(LOCATION_INVALID)

    age = now - location.captured_at.astimezone(UTC)
    if age < -timedelta(seconds=FUTURE_SKEW_SECONDS):
        return result(LOCATION_INVALID, accuracy_m=accuracy)
    if age > timedelta(seconds=policy.max_age_seconds):
        return result(LOCATION_STALE, accuracy_m=accuracy)
    if location.accuracy_m > policy.max_accuracy_m:
        return result(LOCATION_TOO_INACCURATE, accuracy_m=accuracy)

    nearest = nearest_workplace(location.latitude, location.longitude, workplaces)
    if nearest is None:
        return result(NO_APPLICABLE_WORKPLACE, accuracy_m=accuracy)
    workplace, distance = nearest

    common: dict[str, object] = {
        "branch_id": workplace.branch_id,
        "distance_m": distance,
        "radius_m": workplace.radius_m,
        "accuracy_m": accuracy,
    }
    if distance <= workplace.radius_m:
        return result(INSIDE, **common)
    if distance - location.accuracy_m <= workplace.radius_m:
        return result(OUTSIDE_GEOFENCE_UNCERTAIN, **common)
    return result(OUTSIDE_GEOFENCE, **common)


def round_coordinate(value: float, places: int = 4) -> Decimal:
    """Retained-coordinate precision: 4 decimal places is ~11 m, enough to review a dispute but
    deliberately coarser than the raw fix."""
    return Decimal(str(round(value, places)))


def utcnow() -> datetime:
    return datetime.now(UTC)
