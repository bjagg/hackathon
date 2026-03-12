"""Governed retrieval pipeline — applies entitlement filters before semantic search.

Retrieval order:
1. Embed the query
2. Apply governance filters (entitlements, sensitivity, scope)
3. Perform vector similarity search
4. Return only approved context chunks
"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from app.embedding_indexer import EmbeddingIndexer, SearchResult, embedding_indexer
from app.entitlement_service import EntitlementService, entitlement_service


class RetrievalRequest(BaseModel):
    query: str
    user_id: str
    reader_id: str | None = None       # who is requesting (defaults to user_id)
    project_ids: list[str] = Field(default_factory=list)
    max_sensitivity: str = "normal"     # normal, sensitive, restricted
    top_k: int = 10


class ContextChunk(BaseModel):
    chunk_id: str
    text: str
    path: str
    similarity: float
    sensitivity: str
    scope: str
    owner_id: str


class RetrievalResult(BaseModel):
    retrieval_id: str = Field(default_factory=lambda: f"ret_{uuid4().hex[:8]}")
    query: str
    reader_id: str
    chunks: list[ContextChunk]
    total_candidates: int
    filtered_out: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GovernedRetriever:
    """Retrieval pipeline with governance-first filtering."""

    def __init__(
        self,
        indexer: EmbeddingIndexer | None = None,
        ent_service: EntitlementService | None = None,
    ):
        self.indexer = indexer or embedding_indexer
        self.ent_service = ent_service or entitlement_service

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Execute a governed retrieval.

        1. Apply governance filters at the DB level
        2. Compute similarity on filtered results
        3. Post-filter by entitlements
        4. Return approved chunks
        """
        reader = request.reader_id or request.user_id

        # Step 1+2: Search with governance filters applied in the query
        candidates = self.indexer.search(
            query=request.query,
            top_k=request.top_k * 3,  # Over-fetch to account for filtering
            sensitivity_max=request.max_sensitivity,
            reader_id=reader,
        )
        total_candidates = len(candidates)

        # Step 3: Post-filter by entitlement service
        approved = []
        for result in candidates:
            if self._check_access(result, reader, request.project_ids):
                approved.append(
                    ContextChunk(
                        chunk_id=result.chunk_id,
                        text=result.text,
                        path=result.path,
                        similarity=result.similarity,
                        sensitivity=result.sensitivity,
                        scope=result.scope,
                        owner_id=result.owner_id,
                    )
                )

        # Trim to requested top_k
        approved = approved[: request.top_k]
        filtered_out = total_candidates - len(approved)

        return RetrievalResult(
            query=request.query,
            reader_id=reader,
            chunks=approved,
            total_candidates=total_candidates,
            filtered_out=filtered_out,
        )

    def _check_access(
        self,
        result: SearchResult,
        reader_id: str,
        project_ids: list[str],
    ) -> bool:
        """Check if reader has access to this chunk."""
        # Owner always has access
        if result.owner_id == reader_id:
            return True

        # Global scope is readable by all
        if result.scope == "global":
            return True

        # Check entitlement service
        if self.ent_service.check_access(result.path, reader_id):
            return True

        # Check explicit entitlements in vector metadata
        if reader_id in result.entitlements:
            return True

        # Project scope: check membership
        if result.scope == "project":
            # In a real system, check project membership
            # For demo, check if any project_ids match the path
            for pid in project_ids:
                if pid in result.path:
                    return True

        return False


governed_retriever = GovernedRetriever()
