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

FACE_PROFILE_DECIDED: Final = NotificationType("FACE_PROFILE_DECIDED", "ATTENDANCE")

# Approval workflows: "waiting for you" goes to the reviewer of the current stage, "decided" goes
# to the employee the request is about.
LEAVE_APPROVAL_REQUESTED: Final = NotificationType("LEAVE_APPROVAL_REQUESTED", "LEAVE", "HIGH")
LEAVE_DECIDED: Final = NotificationType("LEAVE_DECIDED", "LEAVE")
REGULARIZATION_APPROVAL_REQUESTED: Final = NotificationType(
    "REGULARIZATION_APPROVAL_REQUESTED", "ATTENDANCE", "HIGH"
)
REGULARIZATION_DECIDED: Final = NotificationType("REGULARIZATION_DECIDED", "ATTENDANCE")
OVERTIME_APPROVAL_REQUESTED: Final = NotificationType(
    "OVERTIME_APPROVAL_REQUESTED", "OVERTIME", "HIGH"
)
OVERTIME_DECIDED: Final = NotificationType("OVERTIME_DECIDED", "OVERTIME")

SHIFT_SWAP_REQUESTED: Final = NotificationType("SHIFT_SWAP_REQUESTED", "ATTENDANCE", "HIGH")
SHIFT_SWAP_DECIDED: Final = NotificationType("SHIFT_SWAP_DECIDED", "ATTENDANCE")

PAYSLIP_AVAILABLE: Final = NotificationType("PAYSLIP_AVAILABLE", "PAYROLL")

ONBOARDING_SUBMITTED: Final = NotificationType("ONBOARDING_SUBMITTED", "ONBOARDING", "HIGH")

#: Registered types. A new type is one constant above plus one entry here.
REGISTRY: Final[dict[str, NotificationType]] = {
    t.code: t
    for t in (
        FACE_ENROLLMENT_REQUESTED,
        FACE_PROFILE_DECIDED,
        LEAVE_APPROVAL_REQUESTED,
        LEAVE_DECIDED,
        REGULARIZATION_APPROVAL_REQUESTED,
        REGULARIZATION_DECIDED,
        OVERTIME_APPROVAL_REQUESTED,
        OVERTIME_DECIDED,
        SHIFT_SWAP_REQUESTED,
        SHIFT_SWAP_DECIDED,
        PAYSLIP_AVAILABLE,
        ONBOARDING_SUBMITTED,
    )
}

# Paths of the destinations the first notification types point at.
FACE_SETUP_PATH: Final = "/app/attendance/face-setup"
ATTENDANCE_PATH: Final = "/app/attendance"
SHIFT_SWAPS_PATH: Final = "/app/rosters/schedule"
MY_PAYSLIPS_PATH: Final = "/app/me/payslips"
ONBOARDING_PATH: Final = "/app/onboarding"
