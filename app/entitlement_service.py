"""Entitlement management service — CRUD for memory access controls.

Entitlements are stored in Markdown front matter and can be managed
through the API/UI. This service provides the backend for entitlement
management independent of the existing policy engine.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))


class MemoryEntitlement(BaseModel):
    """An access entitlement for a specific memory or memory path."""
    entitlement_id: str = Field(default_factory=lambda: f"ent_{uuid4().hex[:8]}")
    name: str = ""                          # human-friendly name, e.g. "Transcript — Term Grades"
    memory_paths: list[str] = Field(default_factory=list)  # files and/or directories
    # Legacy single-path field kept for backwards compatibility
    memory_path: str = ""
    owner: str
    scope: str = "private"  # private, project, team, global
    sensitivity: str = "normal"
    allowed_readers: list[str] = Field(default_factory=list)
    purpose_tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def effective_paths(self) -> list[str]:
        """Return the authoritative path list (prefers memory_paths, falls back to memory_path)."""
        if self.memory_paths:
            return self.memory_paths
        if self.memory_path:
            return [self.memory_path]
        return []

    def allows(self, reader_id: str) -> bool:
        if reader_id == self.owner:
            return True
        if self.scope == "global":
            return True
        if reader_id in self.allowed_readers:
            return True
        return False

    def covers_path(self, path: str) -> bool:
        """Check if this entitlement covers a given memory path (exact or directory prefix)."""
        for ep in self.effective_paths():
            if path == ep:
                return True
            # Directory-style match: entitlement on "memory/users/maya/" covers files inside
            if ep.endswith("/") and path.startswith(ep):
                return True
            # Also match if the entitlement path is a prefix directory even without trailing slash
            if not ep.endswith(".md") and path.startswith(ep + "/"):
                return True
        return False


class EntitlementUpdate(BaseModel):
    name: Optional[str] = None
    memory_paths: Optional[list[str]] = None
    scope: Optional[str] = None
    sensitivity: Optional[str] = None
    allowed_readers: Optional[list[str]] = None
    purpose_tags: Optional[list[str]] = None


class EntitlementService:
    """Manages memory entitlements with JSON file persistence."""

    def __init__(self, root: Path | None = None):
        self.root = root or MEMORY_ROOT
        self._index_path = self.root / "entitlements_index.json"
        self._entitlements: dict[str, MemoryEntitlement] = {}
        self._load()

    def _load(self):
        if self._index_path.exists():
            data = json.loads(self._index_path.read_text())
            for item in data:
                ent = MemoryEntitlement.model_validate(item)
                self._entitlements[ent.entitlement_id] = ent

    def _save(self):
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.model_dump(mode="json") for e in self._entitlements.values()]
        self._index_path.write_text(json.dumps(data, indent=2, default=str))

    def create(
        self,
        memory_path: str = "",
        owner: str = "",
        scope: str = "private",
        sensitivity: str = "normal",
        allowed_readers: list[str] | None = None,
        purpose_tags: list[str] | None = None,
        name: str = "",
        memory_paths: list[str] | None = None,
    ) -> MemoryEntitlement:
        ent = MemoryEntitlement(
            name=name,
            memory_paths=memory_paths or [],
            memory_path=memory_path,
            owner=owner,
            scope=scope,
            sensitivity=sensitivity,
            allowed_readers=allowed_readers or [],
            purpose_tags=purpose_tags or [],
        )
        self._entitlements[ent.entitlement_id] = ent
        self._save()
        return ent

    def get(self, entitlement_id: str) -> MemoryEntitlement | None:
        return self._entitlements.get(entitlement_id)

    def get_by_path(self, memory_path: str) -> list[MemoryEntitlement]:
        return [e for e in self._entitlements.values() if e.covers_path(memory_path)]

    def list_for_owner(self, owner: str) -> list[MemoryEntitlement]:
        return [e for e in self._entitlements.values() if e.owner == owner]

    def list_for_reader(self, reader_id: str) -> list[MemoryEntitlement]:
        return [e for e in self._entitlements.values() if e.allows(reader_id)]

    def update(self, entitlement_id: str, updates: EntitlementUpdate) -> MemoryEntitlement | None:
        ent = self._entitlements.get(entitlement_id)
        if not ent:
            return None
        update_data = updates.model_dump(exclude_none=True)
        for field, value in update_data.items():
            setattr(ent, field, value)
        ent.updated_at = datetime.now(timezone.utc)
        self._save()
        return ent

    def revoke_reader(self, entitlement_id: str, reader_id: str) -> bool:
        ent = self._entitlements.get(entitlement_id)
        if not ent:
            return False
        if reader_id in ent.allowed_readers:
            ent.allowed_readers.remove(reader_id)
            ent.updated_at = datetime.now(timezone.utc)
            self._save()
            return True
        return False

    def grant_reader(self, entitlement_id: str, reader_id: str, purpose: str = "") -> bool:
        ent = self._entitlements.get(entitlement_id)
        if not ent:
            return False
        if reader_id not in ent.allowed_readers:
            ent.allowed_readers.append(reader_id)
            if purpose and purpose not in ent.purpose_tags:
                ent.purpose_tags.append(purpose)
            ent.updated_at = datetime.now(timezone.utc)
            self._save()
            return True
        return False

    def delete(self, entitlement_id: str) -> bool:
        if entitlement_id in self._entitlements:
            del self._entitlements[entitlement_id]
            self._save()
            return True
        return False

    def check_access(self, memory_path: str, reader_id: str) -> bool:
        """Check if a reader has access to a memory path."""
        entitlements = self.get_by_path(memory_path)
        if not entitlements:
            return False
        return any(e.allows(reader_id) for e in entitlements)

    def list_all(self) -> list[MemoryEntitlement]:
        return list(self._entitlements.values())

    def clear(self):
        self._entitlements.clear()
        self._save()

    def scan_memory_paths(self) -> list[dict]:
        """Scan the memory root and return available files and directories.

        Returns a flat list of entries, each with:
          - path: relative path from memory root
          - type: "file" or "directory"
          - label: human-friendly display name
        """
        entries = []
        if not self.root.exists():
            return entries

        for item in sorted(self.root.rglob("*")):
            rel = str(item.relative_to(self.root))
            # Skip hidden files, __pycache__, .db, .json
            if any(part.startswith(".") or part == "__pycache__" for part in item.parts):
                continue
            if item.suffix in (".db", ".json", ".pyc"):
                continue

            if item.is_dir():
                entries.append({
                    "path": f"memory/{rel}/",
                    "type": "directory",
                    "label": f"{rel}/",
                })
            elif item.suffix == ".md":
                entries.append({
                    "path": f"memory/{rel}",
                    "type": "file",
                    "label": rel,
                })
        return entries


entitlement_service = EntitlementService()
