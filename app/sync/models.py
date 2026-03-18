from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CanonicalFieldChange:
    node_id: UUID
    field: str
    old_value: Any
    new_value: Any
    changed_by: str
    changed_at: datetime
    event_id: str
    schema_version: str = "1.0"


@dataclass(frozen=True)
class PartialUpdate:
    external_id: str
    source: str
    fields: dict[str, Any]
