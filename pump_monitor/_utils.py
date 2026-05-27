from __future__ import annotations

from typing import Any


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    return None


def str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
