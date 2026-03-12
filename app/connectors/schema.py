"""Normalized interaction schema for cross-system event ingestion.

Every source system adapter converts its native events into this common
format before they enter the memory pipeline.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NormalizedInteraction(BaseModel):
    """Common schema for interactions from any source system."""

    interaction_id: str = Field(default_factory=lambda: f"int_{uuid4().hex[:12]}")
    source_system: str          # "canvas", "slack", "classroom", etc.
    event_type: str             # "submission", "message", "grade", etc.
    actor: str                  # who performed the action
    timestamp: datetime = Field(default_factory=_utcnow)

    # Flexible payload from the source system
    payload: dict = Field(default_factory=dict)

    # Optional object reference
    object_id: Optional[str] = None
    object_type: Optional[str] = None

    # Governance metadata
    sensitivity: str = "normal"   # normal, sensitive, restricted
    provenance: str = "system"    # how this was captured

    # Routing hints
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

    def summary_line(self) -> str:
        """One-line summary for daily log entries."""
        obj = f" on {self.object_type}:{self.object_id}" if self.object_id else ""
        return f"[{self.source_system}] {self.actor} → {self.event_type}{obj}"
