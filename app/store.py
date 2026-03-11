"""Markdown-based canonical memory store.

Each learner has six semantic documents (AGENTS, SOUL, IDENTITY, USER, TOOLS, MEMORY).
Each document is a single Markdown file with YAML front matter containing sections.
The filesystem is the source of truth per the PRD.
"""

import json
import os
from pathlib import Path

import frontmatter

from app.models import (
    AuditAction,
    AuditEntry,
    DocumentType,
    DocumentView,
    DOCUMENT_DESCRIPTIONS,
    Section,
    SectionCreate,
    SectionStatus,
    SectionUpdate,
    utcnow,
)

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))


def _subject_dir(subject: str) -> Path:
    d = MEMORY_ROOT / "subjects" / subject
    d.mkdir(parents=True, exist_ok=True)
    return d


def _doc_path(subject: str, doc_type: DocumentType) -> Path:
    return _subject_dir(subject) / f"{doc_type.value}.md"


# --- Markdown rendering ---

def _render_document(doc_type: DocumentType, subject: str, sections: list[Section]) -> str:
    """Render a document as human-readable Markdown."""
    lines = [f"# {doc_type.value}", ""]
    lines.append(f"> {DOCUMENT_DESCRIPTIONS[doc_type]}")
    lines.append(f"> Subject: {subject}")
    lines.append("")

    active = [s for s in sections if s.status != SectionStatus.deleted]
    for section in active:
        lines.append(f"## {section.heading}")
        lines.append("")
        # Metadata line
        meta_parts = [f"kind: {section.kind.value}"]
        if section.declared_by:
            meta_parts.append(f"by: {section.declared_by.value}")
        if section.confidence < 1.0:
            meta_parts.append(f"confidence: {section.confidence}")
        if section.status != SectionStatus.active:
            meta_parts.append(f"status: {section.status.value}")
        meta_parts.append(f"v{section.version}")
        lines.append(f"*{' | '.join(meta_parts)}*")
        lines.append("")
        lines.append(section.content)
        lines.append("")

    return "\n".join(lines)


def _save_document(subject: str, doc_type: DocumentType, sections: list[Section]):
    """Save sections to a document's Markdown file."""
    sections_data = [s.model_dump(mode="json") for s in sections]
    post = frontmatter.Post(
        content=_render_document(doc_type, subject, sections),
        subject=subject,
        document=doc_type.value,
        updated_at=utcnow().isoformat(),
        sections=sections_data,
    )
    path = _doc_path(subject, doc_type)
    path.write_text(frontmatter.dumps(post))


def _load_sections(subject: str, doc_type: DocumentType) -> list[Section]:
    """Load sections from a document file."""
    path = _doc_path(subject, doc_type)
    if not path.exists():
        return []
    post = frontmatter.load(str(path))
    sections_data = post.metadata.get("sections", [])
    return [Section.model_validate(s) for s in sections_data]


# --- Audit log ---

_audit_log: list[AuditEntry] = []


def record_audit(
    action: AuditAction,
    actor: str,
    subject: str,
    document: DocumentType | None = None,
    section_id: str | None = None,
    bundle_id: str | None = None,
    detail: str | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        action=action,
        actor=actor,
        subject=subject,
        document=document,
        section_id=section_id,
        bundle_id=bundle_id,
        detail=detail,
    )
    _audit_log.append(entry)
    return entry


def get_audit_log(subject: str | None = None) -> list[AuditEntry]:
    if subject:
        return [e for e in _audit_log if e.subject == subject]
    return list(_audit_log)


def clear_audit_log():
    _audit_log.clear()


# --- CRUD operations ---


def create_section(subject: str, data: SectionCreate, actor: str = "system") -> Section:
    section = Section(
        document=data.document,
        heading=data.heading,
        kind=data.kind,
        declared_by=data.declared_by,
        provenance=data.provenance,
        source_ref=data.source_ref,
        evidence_refs=data.evidence_refs,
        confidence=data.confidence,
        classification=data.classification,
        content=data.content,
    )
    sections = _load_sections(subject, data.document)
    sections.append(section)
    _save_document(subject, data.document, sections)

    record_audit(
        AuditAction.create, actor, subject,
        document=data.document, section_id=section.id,
    )
    return section


def get_document(subject: str, doc_type: DocumentType, actor: str = "system") -> DocumentView:
    sections = _load_sections(subject, doc_type)
    active = [s for s in sections if s.status != SectionStatus.deleted]
    record_audit(AuditAction.read, actor, subject, document=doc_type)
    return DocumentView(
        document=doc_type,
        description=DOCUMENT_DESCRIPTIONS[doc_type],
        subject=subject,
        sections=active,
        rendered_markdown=_render_document(doc_type, subject, active),
    )


def get_section(subject: str, doc_type: DocumentType, section_id: str, actor: str = "system") -> Section | None:
    sections = _load_sections(subject, doc_type)
    for s in sections:
        if s.id == section_id:
            record_audit(
                AuditAction.read, actor, subject,
                document=doc_type, section_id=section_id,
            )
            return s
    return None


def update_section(
    subject: str,
    doc_type: DocumentType,
    section_id: str,
    updates: SectionUpdate,
    actor: str = "system",
) -> Section | None:
    sections = _load_sections(subject, doc_type)
    target = None
    for s in sections:
        if s.id == section_id:
            target = s
            break
    if target is None:
        return None

    update_data = updates.model_dump(exclude_none=True)
    update_data.pop("correction_reason", None)
    for field, value in update_data.items():
        setattr(target, field, value)
    target.version += 1
    target.updated_at = utcnow()

    _save_document(subject, doc_type, sections)

    detail = f"updated: {list(update_data.keys())}"
    if updates.correction_reason:
        detail += f" reason: {updates.correction_reason}"
    record_audit(
        AuditAction.update, actor, subject,
        document=doc_type, section_id=section_id, detail=detail,
    )
    return target


def delete_section(
    subject: str, doc_type: DocumentType, section_id: str,
    hard: bool = False, actor: str = "system",
) -> bool:
    sections = _load_sections(subject, doc_type)
    target = None
    for s in sections:
        if s.id == section_id:
            target = s
            break
    if target is None:
        return False

    if hard:
        sections.remove(target)
    else:
        target.status = SectionStatus.deleted
        target.updated_at = utcnow()

    _save_document(subject, doc_type, sections)
    record_audit(
        AuditAction.delete, actor, subject,
        document=doc_type, section_id=section_id,
        detail="hard" if hard else "soft",
    )
    return True


def list_sections(
    subject: str,
    doc_type: DocumentType | None = None,
    kind: str | None = None,
    status: str | None = None,
) -> list[Section]:
    doc_types = [doc_type] if doc_type else list(DocumentType)
    results = []
    for dt in doc_types:
        sections = _load_sections(subject, dt)
        for s in sections:
            if kind and s.kind.value != kind:
                continue
            if status and s.status.value != status:
                continue
            if s.status == SectionStatus.deleted:
                continue
            results.append(s)
    return results
