"""The app's values as plain JSON data, for the recorded fixtures."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from enum import Enum
from typing import Any


def plain(value: Any) -> Any:
    """`value` - dataclasses, named tuples, enums, times, mappings and
    sequences of them - as JSON's dicts, lists and primitives; a mapping's
    keys as text, in order. A time is ISO 8601, UTC's offset as `Z`."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {
            str(key): plain(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
