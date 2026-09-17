"""Shared parsing primitives.

Dutch decimal commas appear in both prices and nutrition values (CLAUDE.md
section 1), and dots do double duty as thousands separators. One function owns
that ambiguity so three parsers cannot disagree about it.
"""

from __future__ import annotations

import re

_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")


def parse_decimal(text: str | None) -> float | None:
    """Parse a Dutch or English decimal. Returns None rather than raising.

    "1,02"  -> 1.02   (comma decimal)
    "1.200" -> 1200.0 (dot as thousands separator)
    "1.02"  -> 1.02   (dot decimal - only 2 trailing digits, so not thousands)
    "1.234,56" -> 1234.56
    """
    if text is None:
        return None
    t = str(text).strip().replace(" ", "").replace(" ", "")
    t = t.replace("€", "").replace("EUR", "").strip()
    if not t:
        return None

    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif _THOUSANDS.match(t):
        t = t.replace(".", "")

    try:
        return float(t)
    except ValueError:
        return None


def normalise(text: str | None) -> str:
    """Lowercase, collapse whitespace, normalise the unicode odds and ends."""
    if text is None:
        return ""
    t = str(text)
    t = t.replace("&lt;", "<").replace("&gt;", ">")
    t = t.replace(" ", " ").replace("×", "x").replace("−", "-")
    t = t.replace("±", "+/-")
    return re.sub(r"\s+", " ", t).strip().lower()
