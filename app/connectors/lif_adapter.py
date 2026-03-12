"""LIF (Learning Information Fabric) GraphQL adapter.

Connects to a 1EdTech LIF endpoint to fetch learner records and normalize
them into NormalizedInteraction format for ingestion into the memory platform.
"""

import os
from datetime import datetime, timezone

import httpx

from app.connectors.schema import NormalizedInteraction

# DNS workaround — the demo endpoint may not resolve on all networks
LIF_ENDPOINT = os.environ.get(
    "LIF_ENDPOINT",
    "https://graphql-org1.demo.lif.unicon.net/graphql",
)
LIF_API_KEY = os.environ.get(
    "LIF_API_KEY",
    "r6ywESPUaVbnjc14YIJALvoalfcAFkfClVDB2BOU1O4",
)
LIF_RESOLVE_IP = os.environ.get("LIF_RESOLVE_IP", "18.204.188.227")

PERSON_QUERY = """
query GetPerson($filter: PersonInput!) {
  person(filter: $filter) {
    Name { firstName lastName }
    Identifier { identifier identifierType }
    Contact { Email { emailAddress } }
    CredentialAward {
      identifier awardIssueDate credentialAwardee name
      awardStatus creditsEarned
    }
    CourseLearningExperience {
      identifier startDate endDate name
      RefCourse { identifier name }
    }
    Proficiency { name description }
    Interactions {
      interactionId channel interactionType summary
      interactionStart interactionEnd sentiment
    }
  }
}
"""


class LIFClient:
    """Client for querying the LIF GraphQL endpoint."""

    def __init__(
        self,
        endpoint: str = LIF_ENDPOINT,
        api_key: str = LIF_API_KEY,
        resolve_ip: str | None = LIF_RESOLVE_IP,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.resolve_ip = resolve_ip

    def _make_transport(self) -> httpx.HTTPTransport | None:
        """Create transport with DNS override if needed."""
        if self.resolve_ip:
            from urllib.parse import urlparse
            parsed = urlparse(self.endpoint)
            host = parsed.hostname
            port = 443 if parsed.scheme == "https" else 80
            return httpx.HTTPTransport(
                verify=True,
                # httpx doesn't support --resolve directly, so we use
                # a custom transport isn't straightforward. We'll handle
                # this in the request instead.
            )
        return None

    def fetch_person(self, school_id: str) -> dict | None:
        """Fetch a person record by SCHOOL_ASSIGNED_NUMBER."""
        import json as _json

        variables = {
            "filter": {
                "Identifier": [{
                    "identifier": school_id,
                    "identifierType": "SCHOOL_ASSIGNED_NUMBER",
                }]
            }
        }
        # Collapse multi-line query to single line for subprocess compatibility
        query = " ".join(PERSON_QUERY.split())
        body = _json.dumps({"query": query, "variables": variables})

        # Try direct httpx first
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(self.endpoint, content=body, headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self.api_key,
                })
                resp.raise_for_status()
                persons = resp.json().get("data", {}).get("person", [])
                return persons[0] if persons else None
        except Exception:
            pass

        # Fallback: use curl with --resolve for DNS override
        if self.resolve_ip:
            import subprocess
            from urllib.parse import urlparse
            parsed = urlparse(self.endpoint)
            resolve = f"{parsed.hostname}:443:{self.resolve_ip}"
            try:
                result = subprocess.run(
                    [
                        "curl", "-s", "--max-time", "15",
                        "--resolve", resolve,
                        "-X", "POST", self.endpoint,
                        "-H", "Content-Type: application/json",
                        "-H", f"X-API-Key: {self.api_key}",
                        "-d", body,
                    ],
                    capture_output=True, text=True, timeout=20,
                )
                if result.returncode == 0 and result.stdout:
                    data = _json.loads(result.stdout)
                    persons = data.get("data", {}).get("person", [])
                    return persons[0] if persons else None
            except Exception:
                pass

        return None


class LIFAdapter:
    """Converts LIF person records into NormalizedInteraction format."""

    SOURCE = "lif"

    @staticmethod
    def normalize_person(person: dict, user_id: str | None = None) -> list[NormalizedInteraction]:
        """Convert a full LIF person record into a list of interactions.

        Each credential, course, proficiency, etc. becomes a separate interaction
        so the steward can evaluate them independently.
        """
        interactions = []

        # Determine user identity
        names = person.get("Name", [])
        full_name = ""
        if names:
            full_name = f"{names[0].get('firstName', '')} {names[0].get('lastName', '')}".strip()

        ids = person.get("Identifier", [])
        school_id = None
        for ident in ids:
            if ident.get("identifierType") == "SCHOOL_ASSIGNED_NUMBER":
                school_id = ident.get("identifier")
                break
        actor = user_id or school_id or "unknown"

        # --- Credential Awards ---
        for cred in person.get("CredentialAward", []):
            ts = _parse_ts(cred.get("awardIssueDate"))
            interactions.append(NormalizedInteraction(
                source_system="lif",
                event_type="credential_award",
                actor=actor,
                user_id=actor,
                timestamp=ts,
                payload={
                    "credential_id": cred.get("identifier"),
                    "name": cred.get("name"),
                    "awardee": cred.get("credentialAwardee") or full_name,
                    "award_date": cred.get("awardIssueDate"),
                    "status": cred.get("awardStatus"),
                    "credits_earned": cred.get("creditsEarned"),
                },
                sensitivity="normal",
                provenance="lif_graphql",
                project_id=None,
            ))

        # --- Course Learning Experiences ---
        for course in person.get("CourseLearningExperience", []):
            ref = course.get("RefCourse") or {}
            course_name = ref.get("name") or course.get("name") or "unnamed course"
            ts = _parse_ts(course.get("startDate"))
            interactions.append(NormalizedInteraction(
                source_system="lif",
                event_type="course_enrollment",
                actor=actor,
                user_id=actor,
                timestamp=ts,
                payload={
                    "course_id": ref.get("identifier") or course.get("identifier"),
                    "course_name": course_name,
                    "start_date": course.get("startDate"),
                    "end_date": course.get("endDate"),
                },
                sensitivity="normal",
                provenance="lif_graphql",
            ))

        # --- Proficiencies ---
        for prof in person.get("Proficiency", []):
            interactions.append(NormalizedInteraction(
                source_system="lif",
                event_type="proficiency",
                actor=actor,
                user_id=actor,
                payload={
                    "skill_name": prof.get("name"),
                    "description": prof.get("description"),
                },
                sensitivity="normal",
                provenance="lif_graphql",
            ))

        # --- Interactions (if any from LIF) ---
        for ixn in person.get("Interactions", []) or []:
            ts = _parse_ts(ixn.get("interactionStart"))
            interactions.append(NormalizedInteraction(
                source_system="lif",
                event_type="interaction",
                actor=actor,
                user_id=actor,
                timestamp=ts,
                payload={
                    "interaction_id": ixn.get("interactionId"),
                    "channel": ixn.get("channel"),
                    "interaction_type": ixn.get("interactionType"),
                    "summary": ixn.get("summary"),
                    "sentiment": ixn.get("sentiment"),
                },
                sensitivity="normal",
                provenance="lif_graphql",
            ))

        return interactions

    @staticmethod
    def normalize_identity(person: dict, user_id: str | None = None) -> dict:
        """Extract identity information for the IDENTITY.md document."""
        names = person.get("Name", [])
        ids = person.get("Identifier", [])
        contacts = person.get("Contact", [])

        school_id = None
        for ident in ids:
            if ident.get("identifierType") == "SCHOOL_ASSIGNED_NUMBER":
                school_id = ident.get("identifier")

        emails = []
        for contact in contacts:
            for email in contact.get("Email", []):
                emails.extend(email.get("emailAddress", []))

        return {
            "first_name": names[0].get("firstName") if names else None,
            "last_name": names[0].get("lastName") if names else None,
            "school_id": school_id,
            "email": emails[0] if emails else None,
            "identifiers": [
                {"type": i["identifierType"], "value": i["identifier"]}
                for i in ids
            ],
        }


def _parse_ts(ts_str: str | None) -> datetime:
    """Parse a LIF timestamp, falling back to now."""
    if ts_str:
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


# Module-level convenience
lif_client = LIFClient()
