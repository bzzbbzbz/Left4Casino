"""Money storage codec for arbitrary-size integer point balances.

SQLite persists money as canonical base-10 TEXT. Application code uses Python ``int``.
"""

from __future__ import annotations

from typing import Any


# [START SPEC:TASK-016:money-codec]
# REQ: Persist all money fields as SQLite TEXT while exposing Python int in code.
# Source: TASK-016 Big Integer Money Storage exact design.
# CRITICAL: No REAL, no scale factor; canonical signed decimal strings only.
def encode_money(value: int | str | None, *, default: int | None = 0) -> str | None:
    """Encode a Python int-like money value for SQLite TEXT storage."""
    if value is None:
        if default is None:
            return None
        value = default
    if isinstance(value, bool):
        raise TypeError("Boolean values are not valid money amounts")
    return str(int(value))


def decode_money(value: Any, *, default: int = 0) -> int:
    """Decode a SQLite money cell (TEXT/legacy INTEGER/NULL) into Python int."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise TypeError("Boolean values are not valid money amounts")
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        value = value.decode()
    text = str(value).strip()
    if text == "":
        return default
    return int(text)


def normalize_money_dict(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Return a copy of ``row`` with selected money fields decoded to int."""
    normalized = dict(row)
    for field in fields:
        if field in normalized:
            normalized[field] = decode_money(normalized[field])
    return normalized


# [END SPEC:TASK-016]
