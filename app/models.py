"""Pydantic models for the Portable Learner Memory Platform."""

from datetime import datetime, date, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Document types ---

class DocumentType(str, Enum):
    agents = "AGENTS"
    soul = "SOUL"
    identity = "IDENTITY"
    user = "USER"
    tools = "TOOLS"
    memory = "MEMORY"


DOCUMENT_DESCRIPTIONS = {
    DocumentType.agents: "Rules of engagement, security protocols, data handling policies, institutional constraints",
    DocumentType.soul: "Core learning identity, values, beliefs about learning — rarely changes",
    DocumentType.identity: "Current role, school, grade, focus areas — evolves over time",
    DocumentType.user: "Preferences, accessibility needs, communication style — personalization core",
    DocumentType.tools: "Authorized tools, integrations, environment-specific configurations",
    DocumentType.memory: "Curated long-term memory — mastery, error patterns, interaction insights, distilled events",
}


# --- Section within a document ---

class SectionKind(str, Enum):
    policy = "policy"
    constraint = "constraint"
    value = "value"
    belief = "belief"
    trait = "trait"
    fact = "fact"
    preference = "preference"
    accessibility = "accessibility"
    goal = "goal"
    mastery = "mastery"
    error_pattern = "error_pattern"
    inference = "inference"
    interaction_event = "interaction_event"
    relationship = "relationship"
    tool_config = "tool_config"
    integration = "integration"


class DeclaredBy(str, Enum):
    user = "user"
    system = "system"
    guardian = "guardian"
    institution = "institution"
    tutor = "tutor"


class Classification(str, Enum):
    public = "public"
    private = "private"
    restricted = "restricted"


class SectionStatus(str, Enum):
    active = "active"
    candidate = "candidate"
    reviewable = "reviewable"
    deprecated = "deprecated"
    deleted = "deleted"


class SectionCreate(BaseModel):
    document: DocumentType
    heading: str
    kind: SectionKind
    declared_by: DeclaredBy = DeclaredBy.user
    provenance: str = "explicit_statement"
    source_ref: Optional[str] = None
    evidence_refs: Optional[list[str]] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    classification: Classification = Classification.private
    content: str


class SectionUpdate(BaseModel):
    heading: Optional[str] = None
    content: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: Optional[SectionStatus] = None
    classification: Optional[Classification] = None
    correction_reason: Optional[str] = None


class Section(BaseModel):
    id: str = Field(default_factory=lambda: f"sec_{uuid4().hex[:8]}")
    document: DocumentType
    heading: str
    kind: SectionKind
    declared_by: DeclaredBy
    provenance: str
    source_ref: Optional[str] = None
    evidence_refs: Optional[list[str]] = None
    confidence: float
    classification: Classification
    status: SectionStatus = SectionStatus.active
    version: int = 1
    content: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --- Full document view ---

class DocumentView(BaseModel):
    document: DocumentType
    description: str
    subject: str
    sections: list[Section]
    rendered_markdown: str



# --- Context retrieval (entitlement-based) ---

class ContextRequest(BaseModel):
    subject: str
    requester: str
    entitlement: str


class ContextItem(BaseModel):
    document: DocumentType
    heading: str
    kind: SectionKind
    content: str
    source: str
    confidence: float


class ContextBundle(BaseModel):
    bundle_id: str = Field(default_factory=lambda: f"ctx_{uuid4().hex[:8]}")
    subject: str
    entitlement: str
    requester: str
    grant_id: str
    allowed_until: Optional[datetime] = None
    items: list[ContextItem]
    redacted_documents: list[str] = []
    redacted_kinds: list[str] = []


# --- Grant models ---

class GrantRequest(BaseModel):
    subject: str
    requester: str
    entitlement: str
    duration_hours: float = 1.0
    institution: Optional[str] = None
    justification: Optional[str] = None


# --- Audit models ---

class AuditAction(str, Enum):
    read = "read"
    create = "create"
    update = "update"
    delete = "delete"
    context_retrieval = "context_retrieval"


class AuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"aud_{uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=utcnow)
    action: AuditAction
    actor: str
    subject: str
    document: Optional[DocumentType] = None
    section_id: Optional[str] = None
    bundle_id: Optional[str] = None
    detail: Optional[str] = None
