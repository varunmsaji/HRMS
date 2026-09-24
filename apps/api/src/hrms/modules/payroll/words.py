"""Amounts in words for payslips, Indian numbering (thousand, lakh, crore)."""

_ONES = (
    "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen "
    "Fifteen Sixteen Seventeen Eighteen Nineteen"
).split()
_TENS = "Zero Ten Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def number_in_words(n: int) -> str:
    """A non-negative whole number in words: 1,23,45,678 → "One Crore Twenty Three Lakh Forty
    Five Thousand Six Hundred Seventy Eight"."""
    if n == 0:
        return "Zero"
    parts = []
    crores, n = divmod(n, 10_000_000)
    lakhs, n = divmod(n, 100_000)
    thousands, n = divmod(n, 1_000)
    if crores:
        parts.append(f"{number_in_words(crores)} Crore")
    if lakhs:
        parts.append(f"{_below_hundred(lakhs)} Lakh")
    if thousands:
        parts.append(f"{_below_hundred(thousands)} Thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def rupees_in_words(minor: int) -> str:
    """Paise → "Rupees Fifty Six Thousand Two Hundred and Fifty Paise Only"."""
    negative = minor < 0
    rupees, paise = divmod(abs(minor), 100)
    text = f"Rupees {number_in_words(rupees)}"
    if paise:
        text += f" and {number_in_words(paise)} Paise"
    return ("Minus " if negative else "") + text + " Only"
