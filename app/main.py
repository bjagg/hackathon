"""FastAPI application for the Portable Learner Memory Platform."""

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.entitlements import ENTITLEMENTS
from app.tree import build_tree, query_subtree, list_paths, load_index_markdown
from app.models import (
    AuditEntry,
    ContextBundle,
    ContextRequest,
    DocumentType,
    DocumentView,
    GrantRequest,
    Section,
    SectionCreate,
    SectionUpdate,
)
from app.policy import policy_engine
from app.router import build_context_bundle
from app.store import (
    create_section,
    delete_section,
    get_audit_log,
    get_document,
    get_section,
    list_sections,
    update_section,
)

# Pipeline imports
from app.connectors.schema import NormalizedInteraction
from app.connectors.canvas_adapter import CanvasAdapter
from app.connectors.slack_adapter import SlackAdapter
from app.daily_logger import daily_logger
from app.entitlement_service import entitlement_service, EntitlementUpdate
from app.langchain_pipeline import memory_pipeline

app = FastAPI(
    title="Portable Learner Memory Platform",
    version="0.4.0",
    description=(
        "Education-first, user-governed portable memory API with entitlement-based access, "
        "interaction ingestion, LLM-governed memory admission, and vector retrieval."
    ),
)


# --- Entitlements catalog ---


@app.get("/entitlements")
def list_entitlements_endpoint():
    """List all available entitlements with their access scopes."""
    return {
        name: {
            "description": e.description,
            "allowed_documents": [d.value for d in e.allowed_documents],
            "allowed_kinds": [k.value for k in e.allowed_kinds] if e.allowed_kinds else "all",
            "max_classification": e.max_classification,
        }
        for name, e in ENTITLEMENTS.items()
    }


@app.get("/entitlements/{name}")
def get_entitlement_endpoint(name: str):
    if name not in ENTITLEMENTS:
        raise HTTPException(status_code=404, detail=f"Entitlement '{name}' not found")
    e = ENTITLEMENTS[name]
    return {
        "name": name,
        "description": e.description,
        "allowed_documents": [d.value for d in e.allowed_documents],
        "allowed_kinds": [k.value for k in e.allowed_kinds] if e.allowed_kinds else "all",
        "max_classification": e.max_classification,
    }


# --- Document views ---


@app.get("/docs/{subject}/{doc_type}", response_model=DocumentView)
def read_document_endpoint(subject: str, doc_type: DocumentType):
    return get_document(subject, doc_type, actor="api")


@app.get("/docs/{subject}/{doc_type}/markdown")
def read_document_markdown_endpoint(subject: str, doc_type: DocumentType):
    doc = get_document(subject, doc_type, actor="api")
    return {"document": doc_type.value, "markdown": doc.rendered_markdown}


# --- Section CRUD ---


@app.post("/sections/{subject}", response_model=Section, status_code=201)
def create_section_endpoint(subject: str, data: SectionCreate):
    return create_section(subject, data, actor="api")


@app.get("/sections/{subject}/{doc_type}/{section_id}", response_model=Section)
def read_section_endpoint(subject: str, doc_type: DocumentType, section_id: str):
    item = get_section(subject, doc_type, section_id, actor="api")
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return item


@app.get("/sections/{subject}", response_model=list[Section])
def list_sections_endpoint(
    subject: str,
    document: DocumentType | None = Query(default=None),
    kind: str | None = Query(default=None),
):
    return list_sections(subject, doc_type=document, kind=kind)


@app.patch("/sections/{subject}/{doc_type}/{section_id}", response_model=Section)
def update_section_endpoint(
    subject: str, doc_type: DocumentType, section_id: str, updates: SectionUpdate,
):
    item = update_section(subject, doc_type, section_id, updates, actor="api")
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return item


@app.delete("/sections/{subject}/{doc_type}/{section_id}")
def delete_section_endpoint(
    subject: str, doc_type: DocumentType, section_id: str,
    hard: bool = Query(default=False),
):
    ok = delete_section(subject, doc_type, section_id, hard=hard, actor="api")
    if not ok:
        raise HTTPException(status_code=404, detail="Section not found")
    return {"status": "deleted", "section_id": section_id}


# --- Context retrieval ---


@app.post("/context", response_model=ContextBundle)
def retrieve_context_endpoint(request: ContextRequest):
    return build_context_bundle(request)


# --- Grants ---


@app.post("/grants")
def create_grant_endpoint(request: GrantRequest):
    try:
        grant = policy_engine.create_grant(
            subject=request.subject,
            requester=request.requester,
            entitlement=request.entitlement,
            duration_hours=request.duration_hours,
            institution=request.institution,
            justification=request.justification,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return grant.to_dict()


@app.get("/grants")
def list_grants_endpoint(
    subject: str | None = Query(default=None),
    requester: str | None = Query(default=None),
):
    return [g.to_dict() for g in policy_engine.list_grants(subject, requester)]


@app.delete("/grants/{grant_id}")
def revoke_grant_endpoint(grant_id: str):
    ok = policy_engine.revoke_grant(grant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Grant not found")
    return {"status": "revoked", "grant_id": grant_id}


# --- Domain tree index (INDEX.md) ---


@app.get("/tree/{subject}")
def tree_endpoint(subject: str, depth: int = Query(default=-1)):
    """Full domain tree with rollup stats. Rebuilds and persists INDEX.md."""
    root = build_tree(subject)
    return root.to_dict(depth=depth)


@app.get("/tree/{subject}/markdown")
def tree_markdown_endpoint(subject: str):
    """Read INDEX.md as rendered markdown."""
    build_tree(subject)
    md = load_index_markdown(subject)
    if md is None:
        raise HTTPException(status_code=404, detail="No index found")
    return {"document": "INDEX", "markdown": md}


@app.get("/tree/{subject}/ascii")
def tree_ascii_endpoint(subject: str):
    """ASCII rendering of the domain tree."""
    root = build_tree(subject)
    lines = [f"{root.name}  (total={root.total_sections})"]
    children = sorted(root.children.values(), key=lambda c: c.name)
    for i, child in enumerate(children):
        lines.append(child.to_ascii("", i == len(children) - 1))
    return {"tree": "\n".join(lines)}


@app.get("/tree/{subject}/paths")
def tree_paths_endpoint(subject: str):
    """List all domain paths that contain sections."""
    return {"paths": list_paths(subject)}


@app.get("/tree/{subject}/at/{path:path}")
def tree_subtree_endpoint(subject: str, path: str, depth: int = Query(default=-1)):
    """Query a specific subtree by domain path."""
    node = query_subtree(subject, path)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Path '{path}' not found in tree")
    return node.to_dict(depth=depth)


@app.post("/tree/{subject}/rebuild")
def tree_rebuild_endpoint(subject: str):
    """Force rebuild INDEX.md from canonical documents."""
    root = build_tree(subject)
    return {"status": "rebuilt", "total_sections": root.total_sections}


# --- Audit ---


@app.get("/audit", response_model=list[AuditEntry])
def audit_endpoint(subject: str | None = Query(default=None)):
    return get_audit_log(subject)


# ═══════════════════════════════════════════════════════════════════════
# Day 2 — Ingestion, Pipeline, Governance, and UI endpoints
# ═══════════════════════════════════════════════════════════════════════


# --- Interaction ingestion ---


@app.post("/ingest")
def ingest_endpoint(interaction: NormalizedInteraction):
    """Ingest a single normalized interaction through the full pipeline."""
    result = memory_pipeline.ingest(interaction)
    return result.model_dump(mode="json")


@app.post("/ingest/batch")
def ingest_batch_endpoint(interactions: list[NormalizedInteraction]):
    """Ingest multiple interactions."""
    results = memory_pipeline.ingest_batch(interactions)
    return [r.model_dump(mode="json") for r in results]


class RawEventIngest(BaseModel):
    source: str  # "canvas" or "slack"
    events: list[dict]


@app.post("/ingest/raw")
def ingest_raw_endpoint(payload: RawEventIngest):
    """Ingest raw events from a source system. Adapter normalizes them."""
    adapters = {"canvas": CanvasAdapter, "slack": SlackAdapter}
    adapter_cls = adapters.get(payload.source)
    if not adapter_cls:
        raise HTTPException(status_code=400, detail=f"Unknown source: {payload.source}")

    interactions = [adapter_cls.normalize(event) for event in payload.events]
    results = memory_pipeline.ingest_batch(interactions)
    return {
        "source": payload.source,
        "events_received": len(payload.events),
        "results": [r.model_dump(mode="json") for r in results],
    }


# --- Daily logs ---


@app.get("/daily/{user_id}/{log_date}")
def read_daily_log_endpoint(user_id: str, log_date: str):
    """Read a user's daily interaction log."""
    try:
        d = date.fromisoformat(log_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")
    entries = daily_logger.read_log(user_id, d)
    markdown = daily_logger.read_log_markdown(user_id, d)
    return {"user_id": user_id, "date": log_date, "entries": entries, "markdown": markdown}


@app.get("/daily/{user_id}")
def list_daily_logs_endpoint(user_id: str):
    """List all daily log dates for a user."""
    dates = daily_logger.list_log_dates(user_id)
    return {"user_id": user_id, "dates": [d.isoformat() for d in dates]}


# --- Compaction ---


@app.post("/compact/{user_id}/{compact_date}")
def compact_endpoint(user_id: str, compact_date: str):
    """Trigger compaction of a daily log into semantic memories."""
    try:
        d = date.fromisoformat(compact_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    result = memory_pipeline.compact(user_id, d)
    return result.model_dump(mode="json")


@app.post("/compact/{user_id}")
def compact_recent_endpoint(user_id: str, days: int = Query(default=7)):
    """Compact all recent uncompacted daily logs."""
    from app.memory_compactor import memory_compactor
    results = memory_compactor.compact_recent(user_id, days)
    return [r.model_dump(mode="json") for r in results]


# --- Governed retrieval ---


@app.post("/query")
def query_endpoint(
    query: str,
    user_id: str,
    reader_id: str | None = Query(default=None),
    max_sensitivity: str = Query(default="normal"),
    top_k: int = Query(default=5),
):
    """Governed memory retrieval with entitlement filtering."""
    result = memory_pipeline.query(
        question=query,
        user_id=user_id,
        reader_id=reader_id,
        max_sensitivity=max_sensitivity,
        top_k=top_k,
    )
    return result.model_dump(mode="json")


# --- Pipeline status ---


@app.get("/pipeline/status")
def pipeline_status_endpoint():
    """Get pipeline health and statistics."""
    return memory_pipeline.get_status()


@app.post("/pipeline/reindex")
def reindex_endpoint():
    """Reindex all memory files."""
    total = memory_pipeline.reindex_all()
    return {"status": "reindexed", "chunks_indexed": total}


# --- Entitlement management (for UI) ---


class EntitlementCreateRequest(BaseModel):
    memory_path: str
    owner: str
    scope: str = "private"
    sensitivity: str = "normal"
    allowed_readers: list[str] = []
    purpose_tags: list[str] = []


class GrantReaderRequest(BaseModel):
    reader_id: str
    purpose: str = ""


class RevokeReaderRequest(BaseModel):
    reader_id: str


@app.get("/manage/entitlements")
def list_managed_entitlements(owner: str | None = Query(default=None)):
    """List all managed entitlements."""
    if owner:
        items = entitlement_service.list_for_owner(owner)
    else:
        items = entitlement_service.list_all()
    return [e.model_dump(mode="json") for e in items]


@app.post("/manage/entitlements")
def create_managed_entitlement(req: EntitlementCreateRequest):
    ent = entitlement_service.create(
        memory_path=req.memory_path,
        owner=req.owner,
        scope=req.scope,
        sensitivity=req.sensitivity,
        allowed_readers=req.allowed_readers,
        purpose_tags=req.purpose_tags,
    )
    return ent.model_dump(mode="json")


@app.get("/manage/entitlements/{entitlement_id}")
def get_managed_entitlement(entitlement_id: str):
    ent = entitlement_service.get(entitlement_id)
    if not ent:
        raise HTTPException(status_code=404, detail="Entitlement not found")
    return ent.model_dump(mode="json")


@app.put("/manage/entitlements/{entitlement_id}")
def update_managed_entitlement(entitlement_id: str, updates: EntitlementUpdate):
    ent = entitlement_service.update(entitlement_id, updates)
    if not ent:
        raise HTTPException(status_code=404, detail="Entitlement not found")
    return ent.model_dump(mode="json")


@app.delete("/manage/entitlements/{entitlement_id}")
def delete_managed_entitlement(entitlement_id: str):
    ok = entitlement_service.delete(entitlement_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Entitlement not found")
    return {"status": "deleted", "entitlement_id": entitlement_id}


@app.post("/manage/entitlements/{entitlement_id}/grant")
def grant_reader_endpoint(entitlement_id: str, req: GrantReaderRequest):
    ok = entitlement_service.grant_reader(entitlement_id, req.reader_id, req.purpose)
    if not ok:
        raise HTTPException(status_code=404, detail="Entitlement not found or reader already granted")
    return {"status": "granted", "reader_id": req.reader_id}


@app.post("/manage/entitlements/{entitlement_id}/revoke")
def revoke_reader_endpoint(entitlement_id: str, req: RevokeReaderRequest):
    ok = entitlement_service.revoke_reader(entitlement_id, req.reader_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Entitlement not found or reader not found")
    return {"status": "revoked", "reader_id": req.reader_id}


@app.get("/manage/check-access")
def check_access_endpoint(
    memory_path: str = Query(...),
    reader_id: str = Query(...),
):
    has_access = entitlement_service.check_access(memory_path, reader_id)
    return {"memory_path": memory_path, "reader_id": reader_id, "has_access": has_access}


# --- UI ---


@app.get("/ui")
def ui_endpoint():
    """Serve the entitlements management UI."""
    ui_path = Path(__file__).parent.parent / "ui" / "entitlements.html"
    return FileResponse(ui_path, media_type="text/html")
