"""Shared (de)serialization mixin for HowlWriter's domain dataclasses."""

from __future__ import annotations

import dataclasses
import enum
import json
from datetime import date, datetime
from typing import Any, TypeVar

T = TypeVar("T", bound="DataClassSerializationMixin")


def _encode(value: Any) -> Any:
    if isinstance(value, DataClassSerializationMixin):
        return value.to_dict()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


class DataClassSerializationMixin:
    """Adds to_dict/to_json/from_dict to a dataclass without hiding its fields.

    Nested dataclasses, enums, dates, lists, and dicts are encoded recursively.
    from_dict does a plain field-name match; it does not attempt to resolve
    nested dataclass types automatically, since each domain object rebuilds
    its own nested fields explicitly where needed.
    """

    def to_dict(self) -> dict:
        if not dataclasses.is_dataclass(self):
            raise TypeError(f"{type(self).__name__} must be a dataclass")
        return {f.name: _encode(getattr(self, f.name)) for f in dataclasses.fields(self)}

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls: type[T], data: dict) -> T:
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in field_names})
