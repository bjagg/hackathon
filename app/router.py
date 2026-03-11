"""Context router — returns entitlement-scoped, least-privilege context bundles."""

from app.models import (
    AuditAction,
    ContextBundle,
    ContextItem,
    ContextRequest,
    DocumentType,
    SectionKind,
    SectionStatus,
)
from app.policy import policy_engine
from app.store import list_sections, record_audit


# All known document types and section kinds for computing redactions
ALL_DOCUMENTS = set(DocumentType)
ALL_KINDS = set(SectionKind)


def build_context_bundle(request: ContextRequest) -> ContextBundle:
    """Build a context bundle scoped by entitlement grant."""

    grant = policy_engine.resolve_access(
        subject=request.subject,
        requester=request.requester,
        entitlement=request.entitlement,
    )

    if grant is None:
        record_audit(
            AuditAction.context_retrieval,
            actor=request.requester,
            subject=request.subject,
            detail=f"DENIED: no valid grant for entitlement={request.entitlement}",
        )
        return ContextBundle(
            subject=request.subject,
            entitlement=request.entitlement,
            requester=request.requester,
            grant_id="none",
            items=[],
            redacted_documents=[d.value for d in ALL_DOCUMENTS],
            redacted_kinds=[],
        )

    ent = grant.entitlement
    allowed_docs = set(ent.allowed_documents)
    allowed_kinds = set(ent.allowed_kinds) if ent.allowed_kinds else ALL_KINDS

    # Compute what was excluded
    redacted_docs = [d.value for d in ALL_DOCUMENTS - allowed_docs]
    redacted_kinds = []
    if ent.allowed_kinds:
        redacted_kinds = [k.value for k in ALL_KINDS - allowed_kinds]

    # Fetch only sections that pass both document and kind filters
    items: list[ContextItem] = []
    for doc_type in allowed_docs:
        sections = list_sections(subject=request.subject, doc_type=doc_type)
        for sec in sections:
            if sec.status != SectionStatus.active:
                continue
            if sec.kind not in allowed_kinds:
                continue
            items.append(
                ContextItem(
                    document=sec.document,
                    heading=sec.heading,
                    kind=sec.kind,
                    content=sec.content,
                    source=f"{sec.document.value}.md#{sec.id}",
                    confidence=sec.confidence,
                )
            )

    items.sort(key=lambda i: i.confidence, reverse=True)

    bundle = ContextBundle(
        subject=request.subject,
        entitlement=request.entitlement,
        requester=request.requester,
        grant_id=grant.id,
        allowed_until=grant.expires_at,
        items=items,
        redacted_documents=redacted_docs,
        redacted_kinds=redacted_kinds,
    )

    record_audit(
        AuditAction.context_retrieval,
        actor=request.requester,
        subject=request.subject,
        bundle_id=bundle.bundle_id,
        detail=(
            f"entitlement={request.entitlement} grant={grant.id} "
            f"items={len(items)} redacted_docs={redacted_docs}"
        ),
    )

    return bundle
