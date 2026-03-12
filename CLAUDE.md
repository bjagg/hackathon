# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Portable Learner Memory Platform — an education-first, user-governed portable memory API. Learners carry context across learning tools via six semantic Markdown documents with entitlement-based access control, interaction ingestion, LLM-governed memory admission, and vector retrieval.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Run single test
pytest tests/test_api.py::test_name -v

# Run demo client (server must be running)
python client_demo.py

# Entitlements UI (server must be running)
# Open http://localhost:8000/ui
```

## Architecture

### Storage model
Markdown files with YAML front matter (python-frontmatter). Filesystem is source of truth. Two storage layouts:
- `memory/subjects/{subject}/` — 6 semantic documents + INDEX.md (Day 1 section-based store)
- `memory/users/{user_id}/daily/` and `memory/users/{user_id}/semantic/` — interaction logs + compacted memories (Day 2 pipeline)

SQLite vector DB (`memory/vectors.db`) is a derived index for semantic search, rebuildable from Markdown.

### Six semantic documents
AGENTS.md (policies/constraints), SOUL.md (learning identity/values), IDENTITY.md (current role/school/grade), USER.md (preferences/accessibility), TOOLS.md (integrations/configs), MEMORY.md (mastery/errors/inferences/events).

### Key modules — Day 1 (Section store)
- `app/models.py` — Pydantic v2 models. `Section` is the atomic unit with `domain_path` for tree placement.
- `app/store.py` — CRUD over Markdown files. Calls `_rebuild_index()` after every write.
- `app/tree.py` — Builds hierarchical `TreeNode` from sections, computes rollup stats, renders INDEX.md.
- `app/entitlements.py` — 9 named access profiles with document + kind scoping.
- `app/policy.py` — `Grant` binds entitlement + requester + subject + duration.
- `app/router.py` — Builds `ContextBundle` filtered by grant.

### Key modules — Day 2 (Pipeline)
- `app/connectors/` — Normalize events from source systems (Canvas LMS, Slack).
- `app/daily_logger.py` — Append interactions to daily Markdown logs.
- `app/llm_steward.py` — LLM memory admission with mock + real backends. Ethics prompt in `prompts/`.
- `app/memory_router.py` — Route reads/writes to correct Markdown files by type/scope.
- `app/memory_compactor.py` — Compact daily logs into semantic memories.
- `app/embedding_indexer.py` — SQLite vector DB with hash-based or sentence-transformer embeddings.
- `app/retriever.py` — Governance-first retrieval (filter before search).
- `app/entitlement_service.py` — Per-file entitlement CRUD with JSON persistence.
- `app/sharing.py` — Sharing scopes (private/project/team/global).
- `app/langchain_pipeline.py` — Orchestrates ingest → log → steward → route → write → index → retrieve.

### Access control (two layers)
1. **Entitlements** (Day 1): Named profiles scoping document types + section kinds, bound via time-limited grants.
2. **Sharing scopes** (Day 2): Per-file access (private/project/team/global) with explicit reader lists, stored in frontmatter.

Retrieval always applies governance filters BEFORE vector similarity search.

## Conventions

- Python 3.12+, FastAPI, Pydantic v2, numpy
- Markdown files are canonical storage; vector DB is derived
- `memory/subjects/` and `memory/users/` are gitignored (runtime data)
- Tests use `fastapi.testclient.TestClient` (synchronous)
- IDs: `sec_{hex[:8]}`, `grant_{hex[:8]}`, `int_{hex[:12]}`, `ent_{hex[:8]}`
- LLM steward defaults to mock (rule-based); set `STEWARD_BACKEND=llm` for Ollama
- Embedder defaults to hash-based; install `sentence-transformers` for real semantics
