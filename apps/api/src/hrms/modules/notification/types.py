"""Central catalogue of notification types.

Adding a notification is a code change here (one `NotificationType` row + a call to
`NotificationService.create_notification` from the owning module) and never a schema change: the
table stores `type` as text and the per-type defaults live in this registry.

`action_url` is an app-relative path. The web and the mobile app both resolve the same path, so a
notification is one record that works on either client; the destination screen always re-reads the
canonical server state - a notification only says where to go.
"""

from dataclasses import dataclass
from typing import Final

#: Substrings that must never appear in a metadata key (biometrics and scoring are not
#: notification material, ever). Checked recursively, case-insensitively.
FORBIDDEN_METADATA_KEY_PARTS: Final = (
    "embedding",
    "template",
    "liveness",
    "score",
    "photo",
    "image",
    "descriptor",
    "biometric",
    "face_token",
    "faceset",
    "landmark",
    "password",
    "secret",
    "token",
)
MAX_METADATA_BYTES: Final = 2048

PRIORITIES: Final = ("LOW", "NORMAL", "HIGH")
CATEGORIES: Final = (
    "ATTENDANCE",
    "LEAVE",
    "OVERTIME",
    "ONBOARDING",
    "PAYROLL",
    "ANNOUNCEMENT",
    "SYSTEM",
)


@dataclass(frozen=True)
class NotificationType:
    code: str
    category: str
    priority: str = "NORMAL"


FACE_ENROLLMENT_REQUESTED: Final = NotificationType(
    "FACE_ENROLLMENT_REQUESTED", "ATTENDANCE", "HIGH"
)

#: Registered types. Future modules register theirs here (LEAVE_REQUEST_SUBMITTED, ...).
REGISTRY: Final[dict[str, NotificationType]] = {
    FACE_ENROLLMENT_REQUESTED.code: FACE_ENROLLMENT_REQUESTED,
}

# Paths of the destinations the first notification types point at.
FACE_SETUP_PATH: Final = "/app/attendance/face-setup"
