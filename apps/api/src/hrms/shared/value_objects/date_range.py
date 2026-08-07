from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date | None = None

    def contains(self, value: date) -> bool:
        if value < self.start:
            return False
        if self.end is not None and value > self.end:
            return False
        return True
