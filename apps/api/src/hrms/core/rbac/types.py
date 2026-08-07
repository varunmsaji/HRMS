from dataclasses import dataclass
from enum import StrEnum


class DataScopeLevel(StrEnum):
    COMPANY = "COMPANY"
    TEAM = "TEAM"
    SELF = "SELF"


@dataclass(frozen=True, slots=True)
class DataScope:
    level: DataScopeLevel = DataScopeLevel.COMPANY
