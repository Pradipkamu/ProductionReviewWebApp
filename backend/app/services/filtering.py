from __future__ import annotations

from enum import Enum
from typing import Iterable, TypeVar

TEnum = TypeVar("TEnum", bound=Enum)


def csv_strings(value: str | None) -> list[str]:
    if value is None:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in str(value).split(","):
        item = raw.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def csv_ints(value: str | int | None) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, int):
        return [value]
    out: list[int] = []
    seen: set[int] = set()
    for raw in str(value).split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            item = int(raw)
        except ValueError:
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def csv_enums(value: str | None, enum_type: type[TEnum]) -> list[TEnum]:
    out: list[TEnum] = []
    seen: set[TEnum] = set()
    for raw in csv_strings(value):
        try:
            item = enum_type(raw)
        except ValueError:
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def any_filter(*values: object) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return True
        elif isinstance(value, Iterable):
            if any(True for _ in value):
                return True
        else:
            return True
    return False
