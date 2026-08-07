from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user_id: UUID
    company_id: UUID
    session_id: UUID
    employee_id: UUID | None = None
