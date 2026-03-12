"""SQLite vector database with embeddings for governed memory retrieval.

Stores embeddings for memory chunks alongside governance metadata.
Uses plain SQLite with cosine similarity computed in Python — no extensions needed.

For production, swap in sqlite-vec or a dedicated vector DB.
"""

import hashlib
import json
import os
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

import frontmatter
import numpy as np
from pydantic import BaseModel, Field

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))
DB_PATH = MEMORY_ROOT / "vectors.db"
EMBEDDING_DIM = 384  # matches all-MiniLM-L6-v2


class SearchResult(BaseModel):
    chunk_id: str
    path: str
    text: str
    owner_id: str
    scope: str
    sensitivity: str
    similarity: float
    entitlements: list[str] = Field(default_factory=list)


class Embedder(Protocol):
    """Protocol for embedding backends."""
    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashEmbedder:
    """Deterministic hash-based embedder — works without any ML dependencies.

    Produces consistent embeddings based on text content. Not semantically
    meaningful, but sufficient for testing the full pipeline.
    """

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        embeddings = []
        for text in texts:
            # Use SHA-256 hash expanded to target dimension
            h = hashlib.sha256(text.lower().encode()).digest()
            # Expand hash to fill dimension
            expanded = h * ((self.dim * 4 // len(h)) + 1)
            values = struct.unpack(f"{self.dim}f", expanded[: self.dim * 4])
            vec = np.array(values, dtype=np.float32)
            # Normalize to unit vector
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec)
        return np.array(embeddings)


class SentenceTransformerEmbedder:
    """Real semantic embeddings using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, normalize_embeddings=True)


def get_embedder(backend: str = "auto") -> Embedder:
    """Get the best available embedder."""
    if backend == "hash":
        return HashEmbedder()
    if backend == "sentence_transformer":
        return SentenceTransformerEmbedder()
    # Auto-detect
    try:
        return SentenceTransformerEmbedder()
    except (ImportError, Exception):
        return HashEmbedder()


class EmbeddingIndexer:
    """SQLite-backed vector index with governance metadata."""

    def __init__(self, db_path: Path | None = None, embedder: Embedder | None = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or get_embedder(os.environ.get("EMBEDDER_BACKEND", "hash"))
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    chunk_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    text TEXT NOT NULL,
                    owner_id TEXT DEFAULT 'unknown',
                    scope TEXT DEFAULT 'private',
                    sensitivity TEXT DEFAULT 'normal',
                    entitlements TEXT DEFAULT '[]',
                    embedding BLOB,
                    file_hash TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_owner ON memory_embeddings(owner_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_scope ON memory_embeddings(scope)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_path ON memory_embeddings(path)
            """)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def index_file(self, path: Path) -> int:
        """Index a Markdown file, splitting into chunks and storing embeddings.

        Returns the number of chunks indexed.
        """
        if not path.exists():
            return 0

        content = path.read_text()
        file_hash = hashlib.md5(content.encode()).hexdigest()

        # Check if file has changed
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT file_hash FROM memory_embeddings WHERE path = ? LIMIT 1",
                (str(path),)
            ).fetchone()
            if existing and existing[0] == file_hash:
                return 0  # No changes

        # Parse frontmatter for governance metadata
        post = frontmatter.load(str(path))
        sharing = post.metadata.get("sharing", {})
        owner_id = sharing.get("owner") or post.metadata.get("user_id", "unknown")
        scope = sharing.get("scope") or post.metadata.get("scope", "private")
        sensitivity = sharing.get("sensitivity") or post.metadata.get("sensitivity", "normal")
        entitlements = json.dumps(sharing.get("allowed_readers", []))

        # Split content into chunks
        chunks = self._split_into_chunks(post.content, str(path))

        if not chunks:
            return 0

        # Generate embeddings
        texts = [c["text"] for c in chunks]
        embeddings = self.embedder.embed(texts)
        now = datetime.now(timezone.utc).isoformat()

        with self._conn() as conn:
            # Remove old chunks for this file
            conn.execute("DELETE FROM memory_embeddings WHERE path = ?", (str(path),))

            for chunk, embedding in zip(chunks, embeddings):
                conn.execute(
                    """INSERT INTO memory_embeddings
                    (chunk_id, path, text, owner_id, scope, sensitivity,
                     entitlements, embedding, file_hash, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk["id"],
                        str(path),
                        chunk["text"],
                        owner_id,
                        scope,
                        sensitivity,
                        entitlements,
                        embedding.tobytes(),
                        file_hash,
                        now,
                        now,
                    ),
                )
        return len(chunks)

    def index_directory(self, directory: Path) -> int:
        """Recursively index all Markdown files in a directory."""
        total = 0
        for md_file in directory.rglob("*.md"):
            total += self.index_file(md_file)
        return total

    def search(
        self,
        query: str,
        top_k: int = 10,
        owner_filter: str | None = None,
        scope_filter: str | None = None,
        sensitivity_max: str | None = None,
        reader_id: str | None = None,
    ) -> list[SearchResult]:
        """Search for similar chunks with governance filtering.

        Governance filters are applied BEFORE similarity search.
        """
        # Embed the query
        query_vec = self.embedder.embed([query])[0]

        # Build SQL filter
        conditions = []
        params = []

        if owner_filter:
            conditions.append("owner_id = ?")
            params.append(owner_filter)

        if scope_filter:
            conditions.append("scope = ?")
            params.append(scope_filter)

        if sensitivity_max:
            sensitivity_order = {"normal": 0, "sensitive": 1, "restricted": 2}
            max_level = sensitivity_order.get(sensitivity_max, 2)
            allowed = [k for k, v in sensitivity_order.items() if v <= max_level]
            placeholders = ",".join("?" * len(allowed))
            conditions.append(f"sensitivity IN ({placeholders})")
            params.extend(allowed)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT chunk_id, path, text, owner_id, scope, sensitivity, entitlements, embedding FROM memory_embeddings WHERE {where}"

        results = []
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        for row in rows:
            chunk_id, path, text, owner_id, scope, sensitivity, entitlements_json, emb_bytes = row

            # Apply reader-based access check
            ent_list = json.loads(entitlements_json) if entitlements_json else []
            if reader_id and reader_id != owner_id:
                if scope == "private" and reader_id not in ent_list:
                    continue

            # Compute cosine similarity
            stored_vec = np.frombuffer(emb_bytes, dtype=np.float32)
            similarity = float(np.dot(query_vec, stored_vec))

            results.append(SearchResult(
                chunk_id=chunk_id,
                path=path,
                text=text,
                owner_id=owner_id,
                scope=scope,
                sensitivity=sensitivity,
                similarity=similarity,
                entitlements=ent_list,
            ))

        # Sort by similarity descending
        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:top_k]

    def get_stats(self) -> dict:
        """Get index statistics."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
            files = conn.execute("SELECT COUNT(DISTINCT path) FROM memory_embeddings").fetchone()[0]
            owners = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM memory_embeddings").fetchone()[0]
        return {"total_chunks": total, "files_indexed": files, "unique_owners": owners}

    def clear(self):
        """Clear the entire index."""
        with self._conn() as conn:
            conn.execute("DELETE FROM memory_embeddings")

    def _split_into_chunks(self, content: str, path: str) -> list[dict]:
        """Split markdown content into meaningful chunks."""
        chunks = []
        current_heading = ""
        current_text = []

        for line in content.split("\n"):
            if line.startswith("#"):
                # Save previous chunk
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text and len(text) > 20:
                        chunk_id = hashlib.md5(f"{path}:{current_heading}:{text[:100]}".encode()).hexdigest()[:12]
                        chunks.append({"id": f"chunk_{chunk_id}", "text": text, "heading": current_heading})
                current_heading = line.lstrip("#").strip()
                current_text = [line]
            else:
                current_text.append(line)

        # Don't forget the last chunk
        if current_text:
            text = "\n".join(current_text).strip()
            if text and len(text) > 20:
                chunk_id = hashlib.md5(f"{path}:{current_heading}:{text[:100]}".encode()).hexdigest()[:12]
                chunks.append({"id": f"chunk_{chunk_id}", "text": text, "heading": current_heading})

        return chunks


embedding_indexer = EmbeddingIndexer()
