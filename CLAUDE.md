# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Portable Learner Memory Platform — an education-first, user-governed portable memory API. Learners carry context across learning tools via six semantic Markdown documents with entitlement-based access control.

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
```

## Architecture

**Storage model**: Markdown files with YAML front matter (python-frontmatter). Filesystem is source of truth. Each subject gets a directory under `memory/subjects/{subject}/` containing 6 document files + INDEX.md.

**Six semantic documents**: AGENTS.md (policies/constraints), SOUL.md (learning identity/values), IDENTITY.md (current role/school/grade), USER.md (preferences/accessibility), TOOLS.md (integrations/configs), MEMORY.md (mastery/errors/inferences/events).

**INDEX.md**: Derived, rebuildable domain tree index. Auto-rebuilt on every CRUD mutation via `store._rebuild_index()`. Contains YAML front matter (machine-readable tree) + rendered markdown (ASCII tree, rollup tables, mastery bars). Never edit directly.

**Key modules**:
- `app/models.py` — Pydantic v2 models. `Section` is the atomic unit with `domain_path` for tree placement.
- `app/store.py` — CRUD over Markdown files. Calls `_rebuild_index()` after every write.
- `app/tree.py` — Builds hierarchical `TreeNode` from sections, computes rollup stats, renders/persists INDEX.md.
- `app/entitlements.py` — 9 named access profiles with document + kind scoping (least privilege).
- `app/policy.py` — `Grant` binds entitlement + requester + subject + duration. `PolicyEngine` resolves access.
- `app/router.py` — Builds `ContextBundle` filtered by grant, reports redacted documents/kinds.

**Access control flow**: Requester gets a time-bound `Grant` for a named entitlement → context retrieval filters sections by allowed documents AND allowed kinds → response shows what was included and what was redacted.

**Domain tree**: Sections have `domain_path` (e.g., `math/algebra/rational_expressions`). Tree nodes aggregate stats (mastery_avg, confidence_avg, error counts) bottom-up via `_rollup()`.

## Conventions

- Python 3.12+, FastAPI, Pydantic v2
- No database — Markdown files are canonical storage
- `memory/subjects/` is gitignored (runtime data)
- Tests use `httpx.AsyncClient` with FastAPI's `TestClient`
- Section IDs are `sec_{uuid_hex[:8]}`, grants are `grant_{uuid_hex[:8]}`
