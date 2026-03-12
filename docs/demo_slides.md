# Portable Learner Memory Platform — Demo

---

## The Problem

Every time a student switches learning tools, they start from zero.

- Mastery data locked in one LMS
- Preferences lost between tutoring sessions
- No continuity across school transfers
- Students have no control over their own learning data
- Tools get raw data dumps instead of governed, contextual memory

---

## Our Solution: Portable Learner Memory

A **user-governed, portable memory system** that travels with the learner.

**Key principles:**
- Learner owns their data
- Markdown files are the source of truth (human-readable, portable)
- Minimum-necessary access via entitlements
- Every read and write is audited
- An AI steward decides what's worth remembering

---

## Architecture Overview

```
Source Systems → Connectors → Daily Logs → LLM Steward → Semantic Memory
                                                              ↓
                                              Vector Index ← Markdown Files
                                                              ↓
                                  Query → Governance Filter → Approved Context
```

**Two storage layers:**
1. **Markdown files** — canonical, human-readable, versioned
2. **SQLite vector DB** — derived index for semantic search

---

## Six Semantic Documents

Each learner carries six Markdown documents:

| Document | Purpose |
|----------|---------|
| **AGENTS.md** | Policies, constraints, data handling rules |
| **SOUL.md** | Core learning identity and values |
| **IDENTITY.md** | Current school, grade, focus areas |
| **USER.md** | Preferences, accessibility needs |
| **TOOLS.md** | Authorized integrations and configs |
| **MEMORY.md** | Mastery, error patterns, inferences |

Plus **INDEX.md** — a derived domain tree with rollup statistics.

---

## Interaction → Memory Flow

1. **Canvas** submits a grade event → Connector normalizes it
2. Event appended to `daily/2026-03-12.md`
3. **LLM Steward** evaluates: "Should this become durable memory?"
   - Follows ethics guidelines (minimal storage, privacy first)
   - Returns structured decision with reasoning
4. If admitted → routed to correct semantic memory file
5. Embedding index updated for future retrieval

**Example steward decision:**
```json
{
  "store": true,
  "summary": "Score of 92 on Chapter 5 quiz",
  "memory_type": "semantic",
  "confidence": 0.9,
  "reason": "Academic performance data is valuable for mastery tracking"
}
```

---

## Governance & Entitlements

### 9 named entitlements with least-privilege scoping:

| Entitlement | Documents | Use Case |
|-------------|-----------|----------|
| `transcript` | IDENTITY + MEMORY | Academic records |
| `tutoring_session` | USER + MEMORY | 1-hour tutoring |
| `assessment` | USER + AGENTS | Testing (no mastery data!) |
| `parent_review` | ALL | Guardian inspection right |
| `school_transfer` | 4 documents | Cross-district transfer |

### Sharing scopes for each memory file:
- **Private** — only the learner
- **Project** — class/course members
- **Team** — school/district
- **Global** — all authorized users

---

## Demo Walkthrough

### 1. Ingest interactions from Canvas + Slack
```
POST /ingest/raw  {"source": "canvas", "events": [...]}
POST /ingest/raw  {"source": "slack", "events": [...]}
```

### 2. View daily log
```
GET /daily/student_maya/2026-03-12
```

### 3. Trigger compaction
```
POST /compact/student_maya/2026-03-12
```

### 4. Query with governance
```
POST /query?query=math mastery&user_id=maya&reader_id=tutor
```
→ Returns only what the tutor's entitlement allows

### 5. Manage entitlements via UI
```
GET /ui  → Web interface for granting/revoking access
```

---

## What Makes This Different

| Traditional | Our Approach |
|-------------|-------------|
| Data locked in vendor silos | Portable Markdown files |
| All-or-nothing data sharing | Entitlement-scoped access |
| No student agency | Learner-governed |
| Raw event dumps | AI-curated semantic memory |
| No audit trail | Every access logged |
| Binary access control | Time-bound, purpose-specific grants |

---

## Technical Stack

- **Python 3.12 + FastAPI** — API layer
- **Pydantic v2** — Data validation
- **python-frontmatter** — Markdown + YAML storage
- **SQLite + numpy** — Vector similarity search
- **Mock LLM steward** — Rule-based (swappable for Ollama/cloud)
- **44+ tests** passing

---

## Next Steps

- Real LLM integration (Ollama / Claude API)
- Semantic embeddings (sentence-transformers)
- Cross-institution federation protocol
- Mobile-friendly UI
- FERPA/COPPA compliance audit
- Student-facing memory dashboard
