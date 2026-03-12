# Architecture — Portable Learner Memory Platform

## System Diagram

```
Source Systems                    Memory Pipeline                     Storage Layer
┌──────────────┐                                                    ┌──────────────────────────┐
│  Canvas LMS  │──┐                                                 │  Markdown Files          │
└──────────────┘  │   ┌─────────────┐   ┌──────────────┐           │  (Source of Truth)        │
                  ├──▶│  Connector  │──▶│  Daily Log   │──────────▶│                          │
┌──────────────┐  │   │  Adapters   │   │  Writer      │           │  users/{id}/daily/       │
│    Slack     │──┘   └─────────────┘   └──────┬───────┘           │  users/{id}/semantic/    │
└──────────────┘         normalize              │                   │  projects/{id}/          │
                                                │                   │  shared/                 │
                                                ▼                   │  policies/               │
                                       ┌──────────────┐            │                          │
                                       │  LLM Memory  │            │  subjects/{id}/          │
                                       │  Steward     │            │    AGENTS.md             │
                                       │  (fiduciary) │            │    SOUL.md               │
                                       └──────┬───────┘            │    IDENTITY.md           │
                                               │ admit/reject      │    USER.md               │
                                               ▼                   │    TOOLS.md              │
                                       ┌──────────────┐            │    MEMORY.md             │
                                       │   Memory     │            │    INDEX.md              │
                                       │   Router     │───────────▶│                          │
                                       └──────────────┘            └──────────┬───────────────┘
                                                                              │
                                                                              │ index
                                                                              ▼
Retrieval Path                                                     ┌──────────────────────────┐
                                                                   │  SQLite Vector DB        │
┌──────────────┐    ┌──────────────┐   ┌──────────────┐           │                          │
│   Query      │───▶│  Governance  │──▶│   Vector     │◀──────────│  chunk_id, path, text,   │
│              │    │  Filter      │   │   Search     │           │  owner_id, scope,        │
└──────────────┘    └──────────────┘   └──────┬───────┘           │  sensitivity, embedding  │
                     entitlements,             │                   └──────────────────────────┘
                     sensitivity,              ▼
                     scope checks     ┌──────────────┐
                                      │  Approved    │
                                      │  Context     │
                                      └──────────────┘
```

## Component Inventory

| Component | File | Purpose |
|-----------|------|---------|
| **Connectors** | `app/connectors/` | Normalize events from Canvas, Slack, etc. |
| **Daily Logger** | `app/daily_logger.py` | Append interactions to daily Markdown logs |
| **LLM Steward** | `app/llm_steward.py` | Fiduciary memory admission decisions |
| **Memory Router** | `app/memory_router.py` | Route reads/writes to correct Markdown files |
| **Memory Compactor** | `app/memory_compactor.py` | Compact daily logs into semantic memories |
| **Embedding Indexer** | `app/embedding_indexer.py` | SQLite vector DB for similarity search |
| **Retriever** | `app/retriever.py` | Governance-first retrieval pipeline |
| **Entitlement Service** | `app/entitlement_service.py` | CRUD for memory access controls |
| **Sharing** | `app/sharing.py` | Scope-based access (private/project/team/global) |
| **Pipeline** | `app/langchain_pipeline.py` | Orchestrates the full ingest→store→retrieve flow |
| **Semantic Store** | `app/store.py` | Section CRUD over 6 semantic Markdown documents |
| **Policy Engine** | `app/policy.py` | Time-bound grants for entitlement-based access |
| **Domain Tree** | `app/tree.py` | Hierarchical domain index with rollup stats |
| **Entitlements Catalog** | `app/entitlements.py` | 9 named access profiles (transcript, tutoring, etc.) |
| **API** | `app/main.py` | FastAPI endpoints for everything |
| **UI** | `ui/entitlements.html` | Web UI for entitlement management |

## Key Design Decisions

### Markdown as canonical store
All memory lives in Markdown files with YAML front matter. The vector database is a derived index — it can be rebuilt at any time from the Markdown files. This ensures human readability, version control compatibility, and portability.

### Governance before search
Retrieval always applies governance filters (entitlements, sensitivity, scope) BEFORE performing vector similarity search. This guarantees that unauthorized content never reaches the LLM, even as a candidate.

### Fiduciary memory steward
The LLM that decides what to store acts as a fiduciary — it serves the learner's interests, not the institution's. It follows explicit ethics guidelines and provides reasoning for every decision.

### Dual access control layers
1. **Entitlements** (from Day 1): Named access profiles scoping which document types and section kinds are accessible
2. **Sharing scopes** (Day 2): Per-file access controls (private/project/team/global) with explicit reader lists

### Pluggable backends
- **Embeddings**: Hash-based (testing) → sentence-transformers (local) → API-based (production)
- **LLM Steward**: Rule-based mock (testing) → Ollama (local) → cloud LLM (production)
