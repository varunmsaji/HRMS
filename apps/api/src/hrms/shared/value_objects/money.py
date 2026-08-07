from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Money:
    """Money value object — minor units, never float (ADR-0006)."""

    amount_minor: int
    currency: str

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("currency_mismatch")
        return Money(self.amount_minor + other.amount_minor, self.currency)
