"""LangChain orchestration plane — wires together the full memory pipeline.

Pipeline steps:
1. Interaction ingestion (connectors → normalized schema)
2. Daily log write
3. LLM steward evaluation (memory admission)
4. Memory routing
5. Markdown write (semantic memory)
6. Embedding index update
7. Governed retrieval
8. Response generation

Each step logs its actions for transparency.
"""

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.connectors.schema import NormalizedInteraction
from app.daily_logger import daily_logger
from app.embedding_indexer import embedding_indexer
from app.entitlement_service import entitlement_service
from app.llm_steward import MemoryAdmissionDecision, memory_steward
from app.memory_compactor import CompactionResult, memory_compactor
from app.memory_router import memory_router
from app.retriever import GovernedRetriever, RetrievalRequest, RetrievalResult, governed_retriever

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))

logger = logging.getLogger("memory_pipeline")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(handler)


class PipelineStep(BaseModel):
    """Record of a single pipeline step execution."""
    step_name: str
    status: str = "success"
    detail: str = ""
    duration_ms: float = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IngestResult(BaseModel):
    interaction_id: str
    logged_to: str
    steward_decision: MemoryAdmissionDecision | None = None
    memory_written_to: str | None = None
    steps: list[PipelineStep] = Field(default_factory=list)


class QueryResult(BaseModel):
    query: str
    retrieval: RetrievalResult | None = None
    answer: str = ""
    steps: list[PipelineStep] = Field(default_factory=list)


class MemoryPipeline:
    """Orchestrates the full memory pipeline.

    This is the main entry point for the system. It coordinates:
    - Ingestion: raw events → normalized → daily log → steward → memory
    - Retrieval: query → governance filter → vector search → response
    - Compaction: daily logs → semantic memories
    """

    def __init__(self):
        self.router = memory_router
        self.logger = daily_logger
        self.steward = memory_steward
        self.compactor = memory_compactor
        self.indexer = embedding_indexer
        self.retriever = governed_retriever
        self.ent_service = entitlement_service

    # --- Ingestion pipeline ---

    def ingest(
        self,
        interaction: NormalizedInteraction,
        auto_evaluate: bool = True,
    ) -> IngestResult:
        """Full ingestion pipeline for a single interaction.

        1. Write to daily log
        2. (Optional) Evaluate with LLM steward
        3. If admitted, write to semantic memory + update index
        """
        steps = []
        user_id = interaction.user_id or "unknown"

        # Step 1: Daily log
        t0 = datetime.now(timezone.utc)
        log_path = self.logger.append(user_id, interaction)
        steps.append(PipelineStep(
            step_name="daily_log_write",
            detail=f"Logged to {log_path}",
            duration_ms=_elapsed_ms(t0),
        ))
        logger.info(f"[ingest] Logged {interaction.interaction_id} to {log_path}")

        result = IngestResult(
            interaction_id=interaction.interaction_id,
            logged_to=str(log_path),
            steps=steps,
        )

        # Step 2: Steward evaluation
        if auto_evaluate:
            t0 = datetime.now(timezone.utc)
            decisions = self.steward.evaluate([interaction])
            decision = decisions[0] if decisions else None
            steps.append(PipelineStep(
                step_name="steward_evaluation",
                detail=f"store={decision.store if decision else 'N/A'}, "
                       f"reason={decision.reason_for_decision[:100] if decision else 'N/A'}",
                duration_ms=_elapsed_ms(t0),
            ))
            result.steward_decision = decision
            logger.info(
                f"[ingest] Steward decision for {interaction.interaction_id}: "
                f"store={decision.store if decision else 'N/A'}"
            )

            # Step 3: Write to semantic memory if admitted
            if decision and decision.store:
                t0 = datetime.now(timezone.utc)
                write_path = self.router.resolve_write_path(
                    user_id=user_id,
                    memory_type=decision.memory_type,
                    scope=decision.shareability,
                    project_id=interaction.project_id,
                    topic=decision.memory_type,
                    memory_content=decision.summary,
                )
                self.compactor._append_memory(
                    write_path,
                    user_id,
                    _decision_to_compacted(decision, interaction),
                )
                result.memory_written_to = str(write_path)
                steps.append(PipelineStep(
                    step_name="memory_write",
                    detail=f"Written to {write_path}",
                    duration_ms=_elapsed_ms(t0),
                ))
                logger.info(f"[ingest] Memory written to {write_path}")

                # Step 4: Update embedding index
                t0 = datetime.now(timezone.utc)
                chunks = self.indexer.index_file(write_path)
                steps.append(PipelineStep(
                    step_name="embedding_index_update",
                    detail=f"Indexed {chunks} chunks from {write_path}",
                    duration_ms=_elapsed_ms(t0),
                ))

        return result

    def ingest_batch(
        self,
        interactions: list[NormalizedInteraction],
        auto_evaluate: bool = True,
    ) -> list[IngestResult]:
        """Ingest multiple interactions."""
        results = []
        for interaction in interactions:
            result = self.ingest(interaction, auto_evaluate=auto_evaluate)
            results.append(result)
        return results

    # --- Retrieval pipeline ---

    def query(
        self,
        question: str,
        user_id: str,
        reader_id: str | None = None,
        project_ids: list[str] | None = None,
        max_sensitivity: str = "normal",
        top_k: int = 5,
    ) -> QueryResult:
        """Full retrieval pipeline.

        1. Index any unindexed files
        2. Apply governance filters
        3. Vector search
        4. Return approved context
        """
        steps = []

        # Step 1: Ensure index is up to date
        t0 = datetime.now(timezone.utc)
        user_dir = self.router.root / "users" / user_id
        chunks_indexed = 0
        if user_dir.exists():
            chunks_indexed = self.indexer.index_directory(user_dir)
        steps.append(PipelineStep(
            step_name="index_refresh",
            detail=f"Indexed {chunks_indexed} new chunks",
            duration_ms=_elapsed_ms(t0),
        ))

        # Step 2+3: Governed retrieval
        t0 = datetime.now(timezone.utc)
        request = RetrievalRequest(
            query=question,
            user_id=user_id,
            reader_id=reader_id or user_id,
            project_ids=project_ids or [],
            max_sensitivity=max_sensitivity,
            top_k=top_k,
        )
        retrieval = self.retriever.retrieve(request)
        steps.append(PipelineStep(
            step_name="governed_retrieval",
            detail=f"Found {len(retrieval.chunks)} chunks "
                   f"(filtered {retrieval.filtered_out} by governance)",
            duration_ms=_elapsed_ms(t0),
        ))
        logger.info(
            f"[query] Retrieved {len(retrieval.chunks)} chunks for '{question[:50]}' "
            f"(filtered {retrieval.filtered_out})"
        )

        # Step 4: Build answer from context
        if retrieval.chunks:
            context_summary = " | ".join(
                f"[{c.sensitivity}] {c.text[:100]}" for c in retrieval.chunks[:3]
            )
            answer = f"Found {len(retrieval.chunks)} relevant memories. Top context: {context_summary}"
        else:
            answer = "No relevant memories found matching your query and access level."

        return QueryResult(
            query=question,
            retrieval=retrieval,
            answer=answer,
            steps=steps,
        )

    # --- Compaction pipeline ---

    def compact(self, user_id: str, compact_date: date | None = None) -> CompactionResult:
        """Run compaction for a user's daily log."""
        d = compact_date or date.today()
        logger.info(f"[compact] Starting compaction for {user_id} on {d}")
        result = self.compactor.compact(user_id, d)
        logger.info(
            f"[compact] Compacted {result.interactions_evaluated} interactions → "
            f"{result.memories_stored} memories"
        )
        return result

    # --- Admin ---

    def get_status(self) -> dict:
        """Get pipeline status and statistics."""
        return {
            "index_stats": self.indexer.get_stats(),
            "entitlement_count": len(self.ent_service.list_all()),
            "status": "operational",
        }

    def reindex_all(self) -> int:
        """Reindex all memory files."""
        return self.indexer.index_directory(self.router.root)


def _elapsed_ms(start: datetime) -> float:
    return (datetime.now(timezone.utc) - start).total_seconds() * 1000


def _decision_to_compacted(decision: MemoryAdmissionDecision, interaction: NormalizedInteraction):
    """Convert a steward decision into a CompactedMemory for writing."""
    from app.memory_compactor import CompactedMemory
    return CompactedMemory(
        summary=decision.summary,
        memory_type=decision.memory_type,
        sensitivity=decision.sensitivity,
        retention_class=decision.retention_class,
        shareability=decision.shareability,
        confidence=decision.confidence,
        source_interactions=[decision.interaction_id],
        source_date=interaction.timestamp.date().isoformat(),
    )


# Module-level singleton
memory_pipeline = MemoryPipeline()
