# Case Study: Maya's Portable Learner Memory

## A walkthrough of the Portable Learner Memory Platform

> *Meet Maya Johnson, a high school student in MATH101. Her learning data lives across Canvas LMS, Slack study groups, and tutoring sessions. The Portable Learner Memory Platform gives Maya ownership of her learning history — and a fiduciary AI that decides what to remember, who can see it, and how to use it.*

---

## 1. Ingestion: Canvas Events Flow In

Maya completes a homework assignment, receives a grade, and takes a quiz — all in Canvas LMS. The platform receives these as raw webhook events.

**API Call:**
```bash
POST /ingest/raw
{
  "source": "canvas",
  "events": [
    {
      "event_type": "submission_created",
      "user_id": "student_maya",
      "user_login": "maya.johnson",
      "course_id": "MATH101",
      "created_at": "2026-03-12T10:30:00Z",
      "body": {
        "assignment_id": "hw_rational_expressions",
        "score": 78,
        "body": "Completed rational expressions worksheet. Showed work for all
                 problems but made sign errors in problems 3 and 7."
      }
    },
    {
      "event_type": "grade_change",
      "user_id": "student_maya",
      "course_id": "MATH101",
      "created_at": "2026-03-12T14:00:00Z",
      "body": { "assignment_id": "quiz_chapter5", "score": 92, "grade": "A-" }
    },
    {
      "event_type": "quiz_submitted",
      "user_id": "student_maya",
      "course_id": "MATH101",
      "created_at": "2026-03-12T15:45:00Z",
      "body": { "assignment_id": "quiz_geometry_basics", "score": 95 }
    }
  ]
}
```

**What happens under the hood:**

```
Canvas webhook
  → CanvasAdapter normalizes event format
    → DailyLogger writes to memory/users/student_maya/daily/2026-03-12.md
      → LLM Steward evaluates each event for memory admission
        → MemoryRouter decides which semantic file to write to
          → EmbeddingIndexer updates the vector DB
```

### Steward Decisions

The local LLM (Ollama llama3.2) evaluates each event independently, acting as a fiduciary for Maya:

| Event | Store? | Confidence | Sensitivity | Reasoning |
|-------|--------|------------|-------------|-----------|
| Homework (score: 78) | Yes | 0.85 | normal | "Academic performance data is valuable for tracking mastery progression." |
| Grade change (score: 92) | Yes | 0.85 | **sensitive** | Grade changes marked sensitive — only shared with explicit entitlement. |
| Quiz (score: 95) | Yes | 0.90 | normal | "Quiz results directly measure understanding and inform mastery tracking." |

Note the differentiated decisions: the grade change event is automatically classified as **sensitive** while the quiz submission is **normal**. The steward applies the ethics prompt's guideline: *"Grade data and assessment results require careful handling."*

### Where Data Lands

Each admitted memory is routed to the appropriate semantic file:

```
memory/users/student_maya/
├── daily/
│   └── 2026-03-12.md          ← Raw interaction log (all 3 events)
└── semantic/
    ├── submission_created.md   ← Homework score (78)
    ├── grade_change.md         ← Chapter 5 quiz grade (92, A-)
    └── quiz_results.md         ← Geometry quiz score (95)
```

When Ollama routing is enabled, the LLM classifies memories by topic rather than event type — so a math grade might be routed to `math_algebra.md` instead of `grade_change.md`.

---

## 2. The Six Semantic Documents

Maya's subject-level profile is organized into six canonical Markdown documents:

| Document | Contents |
|----------|----------|
| **IDENTITY.md** | Current role, school, grade level, enrollment info |
| **SOUL.md** | Learning values, motivations, what drives Maya |
| **MEMORY.md** | Mastery data, error patterns, inferences, key events |
| **AGENTS.md** | Policies and constraints (e.g., accommodations, IEP) |
| **USER.md** | Preferences, accessibility needs, tool configurations |
| **TOOLS.md** | Integration configs, connected platforms |

These documents use YAML front matter + Markdown sections. Each section has a `domain_path` for hierarchical organization (e.g., `math/algebra/quadratics`) and a `kind` tag (mastery, error, inference, event).

```
memory/subjects/learner_maya_2026/
├── AGENTS.md
├── IDENTITY.md
├── INDEX.md        ← Auto-generated tree with rollup stats
├── MEMORY.md
├── SOUL.md
├── TOOLS.md
└── USER.md
```

---

## 3. Entitlements: Who Sees What

Maya's data is governed by entitlements — named access profiles that scope what data a reader can access.

### Creating an Entitlement

Maya's parent and tutor need access to her math progress. Using the entitlements UI (`/ui`), we create:

**"Maya Math Progress"** entitlement:
- **Owner:** maya
- **Paths:** `subjects/learner_maya_2026/MEMORY.md`, `users/maya/semantic/` (directory)
- **Scope:** Project
- **Readers:** tutor_sarah, parent_maria
- **Sensitivity:** Normal

The collapsible tree picker lets us select individual files or entire directories:

```
▼ 📁 users/
  ▼ 📁 maya/
    ▼ 📁 semantic/         ← ☑ Selected (entire directory)
      📄 episodic.md
      📄 grade.md
      📄 semantic.md
```

### Access Check

The Quick Access Check verifies entitlements in real time:

```
✓ tutor_sarah has access to memory/users/maya/semantic/grade.md
✗ random_user does NOT have access to memory/users/maya/semantic/grade.md
```

### Grant & Revoke Flow

When Maya's math coach needs temporary access:

1. **Grant:** Select "Maya Math Progress" → Reader: `coach_james` → Grant Access
   - Readers updated: `tutor_sarah, parent_maria, coach_james`
2. **Verify:** Quick Access Check confirms `coach_james` can read `grade_score.md`
3. **Revoke:** Select entitlement → Reader: `coach_james` → Revoke Access
   - Readers revert: `tutor_sarah, parent_maria`
4. **Verify:** Access check confirms `coach_james` is now denied

---

## 4. Governed Retrieval: Privacy Before Search

When anyone queries Maya's memory, governance filters apply **before** vector similarity search — not after.

```
Query: "maya math scores"
  → Embed query (Ollama 3072-dim or hash-based)
    → Pre-filter: sensitivity ≤ reader's clearance level
      → Pre-filter: scope allows this reader
        → Vector similarity search on filtered set
          → Post-filter: entitlement service check per chunk
            → Return approved chunks only
```

**Example retrieval for tutor_sarah:**

| Chunk | File | Similarity | Access |
|-------|------|------------|--------|
| "Score of 78 on submission" | semantic.md | 37% | Approved (entitlement match) |
| "Quiz completed with score 95" | semantic.md | 35% | Approved |
| "Score of 92 on grade change" | grade_change.md | 33% | **Filtered** (sensitive, tutor has normal clearance) |

The grade change (score 92) was marked **sensitive** by the steward. Even though the vector similarity matches, it's filtered out because the tutor's entitlement only grants **normal** sensitivity access.

---

## 5. Two-LLM Chat: The Fiduciary Architecture

The chat system (`/chat/ui`) implements a privacy-preserving two-LLM architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    User Message                          │
│         "How am I doing in math?"                       │
└────────────────────┬────────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │   Local Ollama      │  Step 1: Context Planning
          │   (llama3.2)        │  "What memory to retrieve?"
          │                     │
          │  Queries:           │
          │  - "math scores"    │
          │  - "recent grades"  │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │  GovernedRetriever  │  Step 2: Governed Retrieval
          │                     │  Entitlements + sensitivity
          │  6 chunks approved  │  filters applied
          │  0 chunks filtered  │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │   Cloud LLM         │  Step 3: Generate Response
          │   (Claude API)      │  Sees ONLY pre-approved
          │                     │  memory text — no metadata,
          │                     │  no governance info leaked
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │   Local Ollama      │  Step 4: Memory Admission
          │   (llama3.2)        │  "Should this conversation
          │                     │   become memory?"
          │  Decision: store    │
          │  → "Identify areas  │
          │    of weakness"     │
          └─────────────────────┘
```

### Key privacy boundary

The cloud LLM **never sees**:
- Governance metadata (sensitivity levels, entitlement info)
- Filtered-out chunks (the ones the reader shouldn't see)
- The steward's admission decisions

It receives only the pre-approved text content, formatted as learner memory context.

### Conversation Example

**Maya asks:** *"How am I doing in math? What are my recent quiz scores?"*

**Context Planning (Ollama):**
```json
{
  "search_queries": ["math scores", "recent math grades"],
  "max_sensitivity": "normal",
  "needs_context": true,
  "reasoning": "The question requires recent scores, so context is needed
                to retrieve the learner's math grades."
}
```

**Memory Context Retrieved:** 6 chunks from `grade.md`, `episodic.md`, `semantic.md` with scores 78, 92, 95.

**Cloud LLM Response:** *(with Anthropic API key configured)*
Uses the memory context to give Maya a specific, data-grounded answer about her progress.

**Post-Response Admission (Ollama):**
The steward evaluates whether the conversation turn itself should become memory. A routine question about scores: probably not stored. But if Maya says *"I finally understood how to factor quadratic equations"* — that's a learning insight, and the steward admits it.

**Maya says:** *"I finally understood how to factor quadratic equations after working through the practice problems. The key is recognizing the pattern."*

**Steward decision:** Store as episodic memory.
```json
{
  "store": true,
  "summary": "Recognizing pattern key to factoring quadratic equations",
  "memory_type": "episodic",
  "sensitivity": "normal"
}
```

This insight is now part of Maya's portable memory — available to any future learning tool that has the right entitlement.

---

## 6. The Sidebar: Transparency by Design

The chat UI includes a governance transparency sidebar showing exactly what happened:

| Panel | Shows |
|-------|-------|
| **Memory Context** | Which chunks were retrieved, from which files, with similarity scores |
| **New Memories** | Any memories the steward admitted from the conversation |
| **Pipeline Steps** | Timing for each step (context planning, retrieval, generation, admission) |
| **Governance Log** | The steward's full reasoning — search queries chosen, admission decisions |

This isn't just debugging — it's an accountability feature. Maya (or her guardian) can see exactly what data was used, what was filtered, and what was stored.

---

## 7. Data Portability: It's Just Markdown

Every piece of Maya's learning memory is stored as Markdown with YAML front matter:

```yaml
---
created_at: '2026-03-12T18:04:41.427433+00:00'
memories:
- summary: 'Score of 92 on quiz_chapter5 (canvas)'
  memory_type: semantic
  confidence: 0.85
  retention_class: long_term
  sensitivity: sensitive
  shareability: private
  source_date: '2026-03-12'
  source_interactions: ['int_3c0dc36c3c67']
---

## 1. Score of 92 on quiz_chapter5 (canvas)

- **Type**: semantic
- **Confidence**: 0.85
- **Retention**: long_term
```

The SQLite vector DB is a **derived index** — rebuildable from the Markdown files at any time with `POST /pipeline/reindex`. Maya can take her `memory/` directory to any compatible system.

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    Source Systems                             │
│        Canvas LMS    │    Slack    │    (future: more)       │
└──────────┬───────────┴─────┬──────┴─────────────────────────┘
           │                 │
    ┌──────▼─────────────────▼──────┐
    │     Connector Adapters         │  Normalize to common schema
    │  (canvas_adapter, slack_adapter)│
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │      Daily Logger               │  Append to daily Markdown log
    │  memory/users/{id}/daily/*.md   │
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │     LLM Memory Steward          │  Fiduciary admission decision
    │  (Ollama llama3.2 or mock)      │  store? type? sensitivity?
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │      Memory Router              │  Route to correct semantic file
    │  (LLM topic classification)     │  by type, topic, scope
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │    Semantic Memory Files        │  Canonical Markdown storage
    │  memory/users/{id}/semantic/    │  YAML front matter + sections
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │    Embedding Indexer            │  Vector DB (SQLite)
    │  (Ollama 3072-dim or hash)      │  Derived, rebuildable
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │   Governed Retriever            │  Entitlement + sensitivity
    │   (filter BEFORE search)        │  filtering pre-search
    └──────────────┬─────────────────┘
                   │
    ┌──────────────▼─────────────────┐
    │      Chat Orchestrator          │  Two-LLM architecture
    │  Local Ollama → Cloud Claude    │  Privacy boundary enforced
    └─────────────────────────────────┘
```

---

## Key Design Principles

1. **Learner ownership.** Maya owns her memory. It's Markdown files she can read, move, or delete.

2. **Fiduciary stewardship.** The LLM steward acts in Maya's interest — storing minimum necessary data, never surveilling.

3. **Governance before search.** Entitlements filter data *before* vector similarity, not after. You can't find what you're not allowed to see.

4. **Privacy boundary.** The cloud LLM sees only pre-approved text. Governance metadata stays local.

5. **Transparency.** Every decision is logged, auditable, and visible in the UI. The steward explains its reasoning.

6. **Portability.** Markdown is the source of truth. The vector DB is derived. Take the files anywhere.

---

*Built at the 1EdTech Hackathon, March 2026.*
*Platform: FastAPI + Ollama (llama3.2) + Claude API + SQLite vector DB.*
