"""Daily log compaction — converts daily interaction logs into durable semantic memories.

The compaction process:
1. Reads daily logs for a given user + date
2. Evaluates each interaction via the LLM steward
3. Groups related admitted interactions
4. Writes summarized semantic memories to the appropriate files
5. Marks the daily log as compacted
"""

import os
from datetime import date, datetime, timezone
from pathlib import Path

import frontmatter
from pydantic import BaseModel, Field

from app.connectors.schema import NormalizedInteraction
from app.daily_logger import daily_logger
from app.embedding_indexer import embedding_indexer
from app.llm_steward import MemoryAdmissionDecision, memory_steward
from app.memory_router import memory_router

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))


class CompactedMemory(BaseModel):
    """A compacted memory produced from daily log interactions."""
    summary: str
    memory_type: str
    sensitivity: str
    retention_class: str
    shareability: str
    confidence: float
    source_interactions: list[str] = Field(default_factory=list)  # interaction IDs
    source_date: str
    written_to: str = ""


class CompactionResult(BaseModel):
    user_id: str
    date: str
    interactions_evaluated: int
    memories_stored: int
    memories_skipped: int
    compacted_memories: list[CompactedMemory] = Field(default_factory=list)


class MemoryCompactor:
    """Compacts daily logs into durable semantic memories."""

    def __init__(self, steward=None, router=None, logger=None, indexer=None):
        self.steward = steward or memory_steward
        self.router = router or memory_router
        self.logger = logger or daily_logger
        self.indexer = indexer or embedding_indexer

    def compact(self, user_id: str, compact_date: date) -> CompactionResult:
        """Compact a day's interactions into semantic memories.

        Returns a CompactionResult describing what was stored and what was skipped.
        """
        # 1. Read daily log entries
        entries = self.logger.read_log(user_id, compact_date)
        if not entries:
            return CompactionResult(
                user_id=user_id,
                date=compact_date.isoformat(),
                interactions_evaluated=0,
                memories_stored=0,
                memories_skipped=0,
            )

        # 2. Reconstruct NormalizedInteractions from log entries
        interactions = []
        for entry in entries:
            interaction = NormalizedInteraction(
                interaction_id=entry["interaction_id"],
                source_system=entry["source"],
                event_type=entry["event_type"],
                actor=entry["actor"],
                timestamp=datetime.fromisoformat(entry["timestamp"]),
                sensitivity=entry.get("sensitivity", "normal"),
                provenance=entry.get("provenance", "daily_log"),
                user_id=user_id,
                payload=entry.get("payload", {}),
            )
            interactions.append(interaction)

        # 3. Evaluate with the memory steward
        decisions = self.steward.evaluate(interactions)

        # 4. Process decisions
        stored = []
        skipped = 0
        for decision in decisions:
            if decision.store:
                memory = CompactedMemory(
                    summary=decision.summary,
                    memory_type=decision.memory_type,
                    sensitivity=decision.sensitivity,
                    retention_class=decision.retention_class,
                    shareability=decision.shareability,
                    confidence=decision.confidence,
                    source_interactions=[decision.interaction_id],
                    source_date=compact_date.isoformat(),
                )

                # 5. Write to appropriate semantic memory file
                path = self.router.resolve_write_path(
                    user_id=user_id,
                    memory_type=decision.memory_type,
                    scope=decision.shareability,
                    topic=decision.memory_type,
                )
                self._append_memory(path, user_id, memory)
                memory.written_to = str(path)
                stored.append(memory)

                # 6. Update embedding index
                self.indexer.index_file(path)
            else:
                skipped += 1

        # 7. Mark the daily log as compacted
        self._mark_compacted(user_id, compact_date, len(stored))

        return CompactionResult(
            user_id=user_id,
            date=compact_date.isoformat(),
            interactions_evaluated=len(interactions),
            memories_stored=len(stored),
            memories_skipped=skipped,
            compacted_memories=stored,
        )

    def compact_recent(self, user_id: str, days: int = 7) -> list[CompactionResult]:
        """Compact all uncompacted daily logs from the last N days."""
        results = []
        for log_date in self.logger.list_log_dates(user_id):
            # Check if already compacted
            log_path = self.router.daily_log_path(user_id, log_date)
            if log_path.exists():
                post = frontmatter.load(str(log_path))
                if post.metadata.get("compacted"):
                    continue
            result = self.compact(user_id, log_date)
            results.append(result)
        return results

    def _append_memory(self, path: Path, user_id: str, memory: CompactedMemory):
        """Append a compacted memory to a semantic memory file."""
        now = datetime.now(timezone.utc)

        if path.exists():
            post = frontmatter.load(str(path))
            memories = post.metadata.get("memories", [])
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            post = frontmatter.Post(content="")
            post.metadata = {
                "user_id": user_id,
                "memory_type": memory.memory_type,
                "created_at": now.isoformat(),
                "sharing": {
                    "owner": user_id,
                    "scope": memory.shareability,
                    "sensitivity": memory.sensitivity,
                    "allowed_readers": [],
                },
                "memories": [],
            }
            memories = []

        # Add new memory entry
        entry = memory.model_dump()
        entry["compacted_at"] = now.isoformat()
        memories.append(entry)
        post.metadata["memories"] = memories
        post.metadata["updated_at"] = now.isoformat()
        post.metadata["memory_count"] = len(memories)

        # Render markdown content
        post.content = self._render_semantic_file(user_id, memory.memory_type, memories)
        path.write_text(frontmatter.dumps(post))

    def _render_semantic_file(self, user_id: str, memory_type: str, memories: list[dict]) -> str:
        """Render semantic memory file as human-readable Markdown."""
        lines = [
            f"# {memory_type.title()} Memory — {user_id}",
            "",
            f"**Entries**: {len(memories)}",
            "",
            "---",
            "",
        ]
        for i, m in enumerate(memories, 1):
            lines.append(f"## {i}. {m['summary'][:80]}")
            lines.append("")
            lines.append(f"- **Type**: {m.get('memory_type', '?')}")
            lines.append(f"- **Confidence**: {m.get('confidence', '?')}")
            lines.append(f"- **Retention**: {m.get('retention_class', '?')}")
            lines.append(f"- **Sensitivity**: {m.get('sensitivity', '?')}")
            lines.append(f"- **Source date**: {m.get('source_date', '?')}")
            refs = m.get("source_interactions", [])
            if refs:
                lines.append(f"- **Source interactions**: {', '.join(refs)}")
            lines.append("")
        return "\n".join(lines)

    def _mark_compacted(self, user_id: str, compact_date: date, memories_stored: int):
        """Mark a daily log as compacted."""
        path = self.router.daily_log_path(user_id, compact_date)
        if not path.exists():
            return
        post = frontmatter.load(str(path))
        post.metadata["compacted"] = True
        post.metadata["compacted_at"] = datetime.now(timezone.utc).isoformat()
        post.metadata["memories_stored"] = memories_stored
        path.write_text(frontmatter.dumps(post))


memory_compactor = MemoryCompactor()
