"""Context buffer value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextItem:
    """One piece of meeting context.

    Deliberately generic. Today the buffer holds transcript segments; tomorrow
    it may hold chat messages, detected slide changes, or model output. Callers
    filter by ``kind`` rather than the buffer growing a type per source.
    """

    kind: str
    content: str
    speaker: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "content": self.content,
            "speaker": self.speaker,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class ContextQuery:
    """Filter for reading back from the buffer."""

    limit: int | None = None
    kind: str | None = None
    since: datetime | None = None

    def matches(self, item: ContextItem) -> bool:
        if self.kind is not None and item.kind != self.kind:
            return False
        return not (self.since is not None and item.created_at < self.since)
