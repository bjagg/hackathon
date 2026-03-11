"""Policy engine for entitlement-based, least-privilege access control.

Grants bind an entitlement to a requester + subject + duration.
The entitlement defines what data is accessible. The grant defines who, for whom, and how long.
"""

from datetime import timedelta
from uuid import uuid4

from app.entitlements import ENTITLEMENTS, Entitlement
from app.models import DocumentType, SectionKind, utcnow


class Grant:
    def __init__(
        self,
        subject: str,
        requester: str,
        entitlement: str,
        duration_hours: float,
        institution: str | None = None,
        justification: str | None = None,
    ):
        if entitlement not in ENTITLEMENTS:
            raise ValueError(f"Unknown entitlement: {entitlement}")

        self.id = f"grant_{uuid4().hex[:8]}"
        self.subject = subject
        self.requester = requester
        self.entitlement_name = entitlement
        self.entitlement = ENTITLEMENTS[entitlement]
        self.duration_hours = duration_hours
        self.institution = institution
        self.justification = justification
        self.created_at = utcnow()
        self.revoked = False
        self.expires_at = self.created_at + timedelta(hours=duration_hours)

    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if utcnow() > self.expires_at:
            return False
        return True

    def allows(self, doc_type: DocumentType, kind: SectionKind) -> bool:
        if not self.is_valid():
            return False
        if doc_type not in self.entitlement.allowed_documents:
            return False
        if self.entitlement.allowed_kinds and kind not in self.entitlement.allowed_kinds:
            return False
        return True

    def time_remaining(self) -> str:
        if not self.is_valid():
            return "expired"
        remaining = self.expires_at - utcnow()
        hours = remaining.total_seconds() / 3600
        if hours >= 1:
            return f"{hours:.1f}h"
        minutes = remaining.total_seconds() / 60
        return f"{minutes:.0f}m"

    def to_dict(self) -> dict:
        ent = self.entitlement
        return {
            "id": self.id,
            "subject": self.subject,
            "requester": self.requester,
            "entitlement": self.entitlement_name,
            "entitlement_description": ent.description,
            "allowed_documents": [d.value for d in ent.allowed_documents],
            "allowed_kinds": [k.value for k in ent.allowed_kinds] if ent.allowed_kinds else "all",
            "duration_hours": self.duration_hours,
            "institution": self.institution,
            "justification": self.justification,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "time_remaining": self.time_remaining(),
            "revoked": self.revoked,
            "valid": self.is_valid(),
        }


class PolicyEngine:
    def __init__(self):
        self._grants: list[Grant] = []

    def create_grant(
        self,
        subject: str,
        requester: str,
        entitlement: str,
        duration_hours: float = 1.0,
        institution: str | None = None,
        justification: str | None = None,
    ) -> Grant:
        grant = Grant(
            subject=subject,
            requester=requester,
            entitlement=entitlement,
            duration_hours=duration_hours,
            institution=institution,
            justification=justification,
        )
        self._grants.append(grant)
        return grant

    def resolve_access(
        self,
        subject: str,
        requester: str,
        entitlement: str,
    ) -> Grant | None:
        """Find the best valid grant for this requester + entitlement."""
        for grant in self._grants:
            if (
                grant.subject == subject
                and grant.requester == requester
                and grant.entitlement_name == entitlement
                and grant.is_valid()
            ):
                return grant
        return None

    def check_section_access(
        self,
        subject: str,
        requester: str,
        entitlement: str,
        doc_type: DocumentType,
        kind: SectionKind,
    ) -> bool:
        grant = self.resolve_access(subject, requester, entitlement)
        if grant is None:
            return False
        return grant.allows(doc_type, kind)

    def revoke_grant(self, grant_id: str) -> bool:
        for grant in self._grants:
            if grant.id == grant_id:
                grant.revoked = True
                return True
        return False

    def list_grants(self, subject: str | None = None, requester: str | None = None) -> list[Grant]:
        results = self._grants
        if subject:
            results = [g for g in results if g.subject == subject]
        if requester:
            results = [g for g in results if g.requester == requester]
        return results

    def clear(self):
        self._grants.clear()


policy_engine = PolicyEngine()
