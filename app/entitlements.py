"""Entitlement definitions — named access profiles with least-privilege scoping.

Each entitlement declares exactly which documents and section kinds are needed
for a specific use case. Grants bind an entitlement to a requester + subject + duration.

The entitlement is the "what and why". The grant is the "who, for whom, and how long".
"""

from dataclasses import dataclass, field

from app.models import DocumentType, SectionKind


@dataclass
class Entitlement:
    name: str
    description: str
    # Which documents can be accessed
    allowed_documents: list[DocumentType]
    # Within those documents, which section kinds (empty = all kinds in allowed docs)
    allowed_kinds: list[SectionKind] = field(default_factory=list)
    # Maximum classification level this entitlement can see
    max_classification: str = "restricted"


# ─── Predefined entitlements ───────────────────────────────────────────

ENTITLEMENTS: dict[str, Entitlement] = {}


def _register(e: Entitlement):
    ENTITLEMENTS[e.name] = e


# --- Academic records ---

_register(Entitlement(
    name="transcript",
    description=(
        "Academic transcript generation. Access to identity facts, mastery records, "
        "and goals. No access to behavioral inferences, preferences, accessibility, "
        "or interaction logs."
    ),
    allowed_documents=[DocumentType.identity, DocumentType.memory],
    allowed_kinds=[
        SectionKind.fact,
        SectionKind.mastery,
        SectionKind.goal,
    ],
))

_register(Entitlement(
    name="school_transfer",
    description=(
        "Transfer to a new school or district. Includes identity, mastery, goals, "
        "accessibility accommodations, and institutional constraints. Excludes behavioral "
        "inferences, interaction logs, communication preferences, and tool configs."
    ),
    allowed_documents=[
        DocumentType.identity, DocumentType.memory, DocumentType.user, DocumentType.agents,
    ],
    allowed_kinds=[
        SectionKind.fact,
        SectionKind.mastery,
        SectionKind.goal,
        SectionKind.accessibility,
        SectionKind.constraint,
        SectionKind.policy,
        SectionKind.relationship,
    ],
))


# --- Tutoring & instruction ---

_register(Entitlement(
    name="tutoring_session",
    description=(
        "Single tutoring session. Access to preferences, communication style, "
        "mastery, error patterns, and engagement inferences. No access to raw identity "
        "facts, institutional policies, or tool configurations."
    ),
    allowed_documents=[DocumentType.user, DocumentType.memory],
    allowed_kinds=[
        SectionKind.preference,
        SectionKind.accessibility,
        SectionKind.mastery,
        SectionKind.error_pattern,
        SectionKind.inference,
        SectionKind.goal,
    ],
))

_register(Entitlement(
    name="adaptive_practice",
    description=(
        "Adaptive practice engine. Broader than tutoring — includes interaction events "
        "and engagement patterns to drive real-time difficulty adjustment. Also includes "
        "session interaction protocol from AGENTS. No access to identity details or "
        "tool configurations."
    ),
    allowed_documents=[DocumentType.user, DocumentType.memory, DocumentType.agents],
    allowed_kinds=[
        SectionKind.preference,
        SectionKind.accessibility,
        SectionKind.mastery,
        SectionKind.error_pattern,
        SectionKind.inference,
        SectionKind.interaction_event,
        SectionKind.policy,
    ],
))


# --- Assessment ---

_register(Entitlement(
    name="assessment",
    description=(
        "Formal assessment administration. Access to accessibility accommodations "
        "and constraints only. No access to mastery, preferences, or behavioral data — "
        "the assessment must measure without prior bias."
    ),
    allowed_documents=[DocumentType.user, DocumentType.agents],
    allowed_kinds=[
        SectionKind.accessibility,
        SectionKind.constraint,
        SectionKind.policy,
    ],
))


# --- Reporting ---

_register(Entitlement(
    name="progress_report",
    description=(
        "Generate a progress report for parent or guardian. Includes identity, goals, "
        "mastery, error patterns, and interaction event summaries. Excludes internal "
        "inferences, tool configs, and institutional policies."
    ),
    allowed_documents=[DocumentType.identity, DocumentType.memory],
    allowed_kinds=[
        SectionKind.fact,
        SectionKind.goal,
        SectionKind.mastery,
        SectionKind.error_pattern,
        SectionKind.interaction_event,
        SectionKind.relationship,
    ],
))

_register(Entitlement(
    name="parent_review",
    description=(
        "Full parent/guardian review of all stored learner data. Broadest access "
        "entitlement — parents can see everything about their child including "
        "inferences, policies, and tool configs. This is an inspection right."
    ),
    allowed_documents=list(DocumentType),
    allowed_kinds=[],  # empty = all kinds
))


# --- Integration ---

_register(Entitlement(
    name="sis_sync",
    description=(
        "SIS integration sync. Access to identity facts and mastery records only. "
        "Strictly limited — SIS should not receive behavioral data, preferences, "
        "or inferences."
    ),
    allowed_documents=[DocumentType.identity, DocumentType.memory],
    allowed_kinds=[
        SectionKind.fact,
        SectionKind.mastery,
    ],
))

_register(Entitlement(
    name="tool_onboarding",
    description=(
        "Onboarding a new learning tool. Access to AGENTS policies and constraints, "
        "USER accessibility requirements, and TOOLS integration specs. No access to "
        "actual learning data in MEMORY, IDENTITY details, or SOUL."
    ),
    allowed_documents=[DocumentType.agents, DocumentType.user, DocumentType.tools],
    allowed_kinds=[
        SectionKind.policy,
        SectionKind.constraint,
        SectionKind.accessibility,
        SectionKind.tool_config,
        SectionKind.integration,
    ],
))
