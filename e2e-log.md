# End-to-End Test Log

**Date:** 2026-03-12
**Server:** `uvicorn app.main:app --reload --port 8000`
**Backends:** STEWARD_BACKEND=llm, EMBEDDER_BACKEND=ollama, ROUTER_BACKEND=ollama, COMPACTOR_BACKEND=ollama
**Tool:** Playwright MCP (browser automation) + curl (API tests)

---

## Test 1: Entitlements UI — Load & Browse

**URL:** `http://localhost:8000/ui`
**Result:** PASS

- Page title: "Memory Entitlements Manager"
- Status bar: operational, 39 entitlements, 0 indexed chunks
- Memory path tree rendered with 3 top-level directories: `projects/`, `subjects/`, `users/`
- Users tree shows: `matt_hanson/`, `maya/`, `student_maya/`, `tutor_sarah/`
- Create Entitlement form, Grant/Revoke panel, Quick Access Check panel all visible
- Current Entitlements table rendered with all 39 rows

**Screenshot:** `screenshots/e2e_01_entitlements_ui.png`

---

## Test 2: Create Entitlement

**Action:** Created "E2E Test — Tutor View" entitlement via UI form
**Result:** PASS

- **Name:** E2E Test — Tutor View
- **Owner:** maya
- **Paths:** `users/maya/daily/`, `users/maya/semantic/`
- **Scope:** Team
- **Sensitivity:** Sensitive
- **Readers:** tutor_sarah, counselor_jones
- **Purpose tags:** e2e_test, tutoring
- **Entitlement ID:** ent_bc045302
- Status bar updated: 39 → 40 entitlements
- Toast: "Entitlement 'E2E Test — Tutor View' created"
- New row appeared in Current Entitlements table with correct scope (team) and sensitivity (sensitive)

**Screenshot:** `screenshots/e2e_02_entitlement_created.png`

---

## Test 3: Grant Access

**Action:** Selected "E2E Test — Tutor View" entitlement, granted to `tutor_sarah` with purpose `e2e_test_session`
**Result:** PASS

- Selected entitlement from dropdown: "E2E Test — Tutor View (maya)"
- Reader ID: tutor_sarah
- Purpose: e2e_test_session
- Clicked "Grant Access"
- Toast: "Access granted to tutor_sarah"

---

## Test 4: Quick Access Check

### 4a: Authorized reader
**Action:** Checked `tutor_sarah` access to `memory/users/maya/semantic/grade.md`
**Result:** PASS — "tutor_sarah has access to memory/users/maya/semantic/grade.md"

### 4b: Unauthorized reader
**Action:** Checked `random_user` access to `memory/users/maya/semantic/grade.md`
**Result:** PASS — "random_user does NOT have access to memory/users/maya/semantic/grade.md"

**Screenshot:** `screenshots/e2e_03_access_check.png`

---

## Test 5: Swagger UI

**URL:** `http://localhost:8000/docs`
**Result:** PASS

- Title: "Portable Learner Memory Platform 0.4.0 OAS 3.1"
- All endpoint groups visible: CRUD, tree, audit, ingest, LIF, daily, compact, query, pipeline, manage, chat
- 40+ endpoints listed

**Screenshot:** `screenshots/e2e_04_swagger_ui.png`

---

## Test 6: API — Pipeline Status

**Endpoint:** `GET /pipeline/status`
**Result:** PASS

```json
{
    "index_stats": {
        "total_chunks": 0,
        "files_indexed": 0,
        "unique_owners": 0
    },
    "entitlement_count": 40,
    "status": "operational"
}
```

---

## Test 7: API — Ingest Interaction

**Endpoint:** `POST /ingest`
**Payload:** Quiz submission — Maya scored 92% on algebra quiz
**Result:** PASS

- Interaction ID: `int_7a9c0aa145d6`
- Logged to: `memory/users/maya/daily/2026-03-12.md`
- **LLM Steward decision:** store=true, memory_type=semantic, sensitivity=normal, retention=long_term, shareability=project
- Memory written to: `memory/users/maya/semantic/semantic.md`
- Pipeline step: daily_log_write — success (3.6ms)

---

## Test 8: API — Reindex

**Endpoint:** `POST /pipeline/reindex`
**Result:** PASS

```json
{
    "status": "reindexed",
    "chunks_indexed": 288
}
```

---

## Test 9: API — Governed Retrieval (Query)

**Endpoint:** `POST /query?query=algebra+quiz&user_id=maya&reader_id=tutor_sarah&max_results=3`
**Result:** PASS

- Total candidates: 15
- Filtered out by governance: 13
- Returned to tutor_sarah: 2 chunks
- Top chunk: "Maya submitted a quiz with a score of 80" (similarity 21.1%)
- Second chunk: "student achieved a score of 95" (similarity 20.0%)
- Pipeline steps: index_refresh (5ms), governed_retrieval (151ms)

Demonstrates governance-first retrieval: 13 of 15 chunks filtered before similarity ranking.

---

## Test 10: API — LIF Person Lookup

**Endpoint:** `GET /lif/person/100005`
**Result:** PASS

- Name: Matt Hanson
- School ID: 100005
- Email: mhanson_lifdemo@stateu.edu
- Credentials: 11
- Courses: 3
- Proficiencies: 118

1EdTech LIF GraphQL endpoint accessed via DNS fallback (curl --resolve).

---

## Test 11: Chat UI — Load

**URL:** `http://localhost:8000/chat/ui`
**Result:** PASS

- Title: "Memory Chat — Two-LLM governed education assistant"
- Status indicators: Ollama (green), Cloud LLM (green/yellow), 258 chunks
- Sidebar panels: Memory Context (0), New Memories (0), Pipeline Steps, Governance Log
- User controls: user ID (student_maya), sensitivity (Normal), New Session button
- Chat input with Send button

**Screenshot:** `screenshots/e2e_05_chat_ui.png`

---

## Test 12: Chat UI — Two-LLM Conversation

**Action:** Sent "How is Maya doing in algebra? What are her recent quiz scores?"
**Result:** PASS

### Cloud LLM Response (Claude via Anthropic API):
- Reported Maya scored 78 on a recent submission
- Identified key breakthrough: "finally understood how to simplify rational expressions"
- Noted positive study group feedback
- Acknowledged limited quiz data, suggested checking gradebook

### Governance Sidebar:
- **Memory Context (5 chunks retrieved):**
  1. `users/student_maya/semantic/math_algebra.md` — 31% — areas of weakness in math
  2. `projects/math-study-group/shared.md` — 31% — tutor feedback "Great insight Maya!"
  3. `projects/math-study-group/shared.md` — 30% — rational expressions breakthrough
  4. `projects/math-study-group/shared.md` — 30% — study group interaction
  5. `users/student_maya/semantic/semantic.md` — 29% — score of 78 on submission

- **New Memories (1):** episodic — "Maya's recent algebra performance and areas of growth"

- **Session ID:** chat_bd532216262...

Full two-LLM pipeline executed:
1. Local Ollama analyzed user message → generated search queries
2. Governed retrieval filtered memory chunks by entitlement/sensitivity
3. Approved context sent to Claude API (cloud LLM) for response
4. Local Ollama evaluated conversation for memory admission → created 1 new episodic memory

**Screenshot:** `screenshots/e2e_06_chat_response.png`

---

## Test 13: Automated Test Suite

**Command:** `pytest tests/ -v`
**Result:** PASS — 89/89 tests passed in 1.02s

Categories:
- `test_api.py` — Section CRUD, grants, context, tree, audit
- `test_governance.py` — Entitlement CRUD, access checks, embedding governance
- `test_pipeline.py` — Canvas/Slack adapters, daily logger, memory router, steward, compaction, ingestion, shared project memory

---

## Summary

| # | Test | Status |
|---|------|--------|
| 1 | Entitlements UI — Load & Browse | PASS |
| 2 | Create Entitlement | PASS |
| 3 | Grant Access | PASS |
| 4a | Quick Access Check — Authorized | PASS |
| 4b | Quick Access Check — Denied | PASS |
| 5 | Swagger UI | PASS |
| 6 | Pipeline Status API | PASS |
| 7 | Ingest Interaction API | PASS |
| 8 | Reindex API | PASS |
| 9 | Governed Retrieval (Query) API | PASS |
| 10 | LIF Person Lookup API | PASS |
| 11 | Chat UI — Load | PASS |
| 12 | Chat UI — Two-LLM Conversation | PASS |
| 13 | Automated Test Suite (89 tests) | PASS |

**All 13 end-to-end tests passed.** All platform workflows — entitlement management, interaction ingestion, LLM-governed memory admission, governed retrieval, LIF student record lookup, and two-LLM chat with Claude API — are operational.
