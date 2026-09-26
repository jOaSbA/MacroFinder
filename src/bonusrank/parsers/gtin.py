"""Barcodes (GTIN/EAN). Milestone 35.

AH states the GTIN on its product detail call. Jumbo doesn't state it
anywhere in the listing, but its image filenames carry it, next to upload
timestamps. Aldi's feed has only internal article numbers.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"(?<!\d)\d{8,14}(?!\d)")
# Upload times in milliseconds: 13 digits, 2017 to 2033.
_MS_MIN, _MS_MAX = 1_480_000_000_000, 2_000_000_000_000


def gs1_valid(code: str) -> bool:
    """GS1 mod-10 check digit, for GTIN-8/12/13/14."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalise_gtin(raw: str | None) -> str | None:
    """A valid GTIN as 13 digits where it fits (GTIN-14 padding and GTIN-12 are
    widened or stripped), EAN-8 as is. None if it isn't a valid code."""
    if raw is None:
        return None
    code = raw.strip()
    if not gs1_valid(code):
        return None
    if len(code) == 14 and code.startswith("0"):
        code = code[1:]
    elif len(code) == 12:
        code = "0" + code
    return code


def _is_timestamp(token: str) -> bool:
    return len(token) == 13 and _MS_MIN <= int(token) < _MS_MAX


def _is_date(token: str) -> bool:
    """The DDMMYYYY upload date that starts many filenames. One in ten dates
    passes the check digit by chance, so they're ruled out by shape."""
    if len(token) != 8:
        return False
    day, month, year = int(token[:2]), int(token[2:4]), int(token[4:])
    return 1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2099


def jumbo_image_gtin(url: str | None) -> str | None:
    """The barcode in a Jumbo product image filename, or None.

    Filenames mix a date, upload timestamps, an internal id and the GTIN.
    Only tokens with a valid check digit that aren't timestamps count, and if
    two different codes remain there is no telling which is the product.
    """
    if not url or "/Products/" not in url:
        return None
    name = url.rsplit("/", 1)[-1]
    found = {normalise_gtin(t) for t in _TOKEN.findall(name) if not _is_timestamp(t) and not _is_date(t)}
    found.discard(None)
    return found.pop() if len(found) == 1 else None
