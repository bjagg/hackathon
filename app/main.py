"""FastAPI application for the Portable Learner Memory Platform."""

from fastapi import FastAPI, HTTPException, Query

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

app = FastAPI(
    title="Portable Learner Memory Platform",
    version="0.3.0",
    description="Education-first, user-governed portable memory API with entitlement-based access.",
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
    # Ensure it's up to date
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
