"""API tests for the Portable Learner Memory Platform."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.policy import policy_engine
from app.store import MEMORY_ROOT, clear_audit_log

client = TestClient(app)

TEST_SUBJECT = "learner_test_001"


@pytest.fixture(autouse=True)
def clean_state():
    """Reset filesystem and in-memory state between tests."""
    subject_dir = MEMORY_ROOT / "subjects" / TEST_SUBJECT
    if subject_dir.exists():
        shutil.rmtree(subject_dir)
    clear_audit_log()
    policy_engine.clear()
    yield
    if subject_dir.exists():
        shutil.rmtree(subject_dir)


def _create_memory(**overrides):
    payload = {
        "subject": TEST_SUBJECT,
        "kind": "preference",
        "domain": "math",
        "category": "learning_preferences",
        "declared_by": "user",
        "provenance": "explicit_user_statement",
        "confidence": 1.0,
        "classification": "private",
        "content": "Prefers worked examples before formal proofs.",
    }
    payload.update(overrides)
    return client.post("/memories", json=payload)


# --- Memory CRUD ---


class TestCreateMemory:
    def test_create_memory(self):
        resp = _create_memory()
        assert resp.status_code == 201
        data = resp.json()
        assert data["subject"] == TEST_SUBJECT
        assert data["kind"] == "preference"
        assert data["content"] == "Prefers worked examples before formal proofs."
        assert data["version"] == 1
        assert data["status"] == "active"
        assert data["id"].startswith("mem_")

    def test_create_inference(self):
        resp = _create_memory(
            kind="inference",
            category="error_patterns",
            declared_by="system",
            provenance="derived_from_quiz_history",
            evidence_refs=["quiz_882", "quiz_901"],
            confidence=0.72,
            content="Struggles with multi-step word problems.",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["kind"] == "inference"
        assert data["declared_by"] == "system"
        assert data["evidence_refs"] == ["quiz_882", "quiz_901"]
        assert data["confidence"] == 0.72

    def test_create_validates_confidence_range(self):
        resp = _create_memory(confidence=1.5)
        assert resp.status_code == 422

    def test_markdown_file_created(self):
        resp = _create_memory()
        mem_id = resp.json()["id"]
        path = MEMORY_ROOT / "subjects" / TEST_SUBJECT / f"{mem_id}.md"
        assert path.exists()
        content = path.read_text()
        assert "Prefers worked examples" in content
        assert "preference" in content


class TestReadMemory:
    def test_read_existing(self):
        mem_id = _create_memory().json()["id"]
        resp = client.get(f"/memories/{TEST_SUBJECT}/{mem_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == mem_id

    def test_read_not_found(self):
        resp = client.get(f"/memories/{TEST_SUBJECT}/mem_nonexistent")
        assert resp.status_code == 404


class TestListMemories:
    def test_list_all(self):
        _create_memory(content="Memory 1")
        _create_memory(content="Memory 2")
        resp = client.get(f"/memories/{TEST_SUBJECT}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_filter_by_category(self):
        _create_memory(category="learning_preferences", content="pref")
        _create_memory(category="mastery", content="mastery item", kind="mastery")
        resp = client.get(f"/memories/{TEST_SUBJECT}?category=mastery")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["category"] == "mastery"

    def test_filter_by_domain(self):
        _create_memory(domain="math", content="math pref")
        _create_memory(domain="reading", content="reading pref")
        resp = client.get(f"/memories/{TEST_SUBJECT}?domain=reading")
        items = resp.json()
        assert len(items) == 1
        assert items[0]["domain"] == "reading"


class TestUpdateMemory:
    def test_update_content(self):
        mem_id = _create_memory().json()["id"]
        resp = client.patch(
            f"/memories/{TEST_SUBJECT}/{mem_id}",
            json={"content": "Updated preference.", "correction_reason": "User corrected"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "Updated preference."
        assert data["version"] == 2

    def test_update_not_found(self):
        resp = client.patch(
            f"/memories/{TEST_SUBJECT}/mem_nonexistent",
            json={"content": "nope"},
        )
        assert resp.status_code == 404


class TestDeleteMemory:
    def test_soft_delete(self):
        mem_id = _create_memory().json()["id"]
        resp = client.delete(f"/memories/{TEST_SUBJECT}/{mem_id}")
        assert resp.status_code == 200

        # Should not appear in list (soft-deleted)
        resp = client.get(f"/memories/{TEST_SUBJECT}")
        assert len(resp.json()) == 0

        # But file still exists
        path = MEMORY_ROOT / "subjects" / TEST_SUBJECT / f"{mem_id}.md"
        assert path.exists()

    def test_hard_delete(self):
        mem_id = _create_memory().json()["id"]
        resp = client.delete(f"/memories/{TEST_SUBJECT}/{mem_id}?hard=true")
        assert resp.status_code == 200

        path = MEMORY_ROOT / "subjects" / TEST_SUBJECT / f"{mem_id}.md"
        assert not path.exists()

    def test_delete_not_found(self):
        resp = client.delete(f"/memories/{TEST_SUBJECT}/mem_nonexistent")
        assert resp.status_code == 404


# --- Fact vs Inference separation (FR2) ---


class TestFactInferenceSeparation:
    def test_facts_and_inferences_separate(self):
        _create_memory(kind="fact", category="facts", content="Born 2015.")
        _create_memory(
            kind="inference",
            category="inferences",
            declared_by="system",
            provenance="derived",
            confidence=0.6,
            content="May prefer visual learning.",
        )
        facts = client.get(f"/memories/{TEST_SUBJECT}?category=facts").json()
        inferences = client.get(f"/memories/{TEST_SUBJECT}?category=inferences").json()
        assert len(facts) == 1
        assert facts[0]["declared_by"] == "user"
        assert len(inferences) == 1
        assert inferences[0]["declared_by"] == "system"
        assert inferences[0]["confidence"] == 0.6


# --- Context retrieval with policy ---


class TestContextRetrieval:
    def test_retrieval_without_grant_returns_empty(self):
        _create_memory(category="mastery", kind="mastery", content="Algebra: 0.8")
        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "role": "math_tutor",
            "purpose": "algebra_tutoring",
            "duration": "session",
            "requested_categories": ["mastery"],
        })
        assert resp.status_code == 200
        bundle = resp.json()
        assert len(bundle["items"]) == 0
        assert "mastery" in bundle["redactions_applied"]

    def test_retrieval_with_grant(self):
        _create_memory(category="mastery", kind="mastery", content="Algebra: 0.8")
        _create_memory(category="learning_preferences", content="Likes visual aids")

        # Create a grant
        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "category_scope": ["mastery", "learning_preferences"],
            "purpose": "algebra_tutoring",
            "duration": "session",
        })

        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "role": "math_tutor",
            "purpose": "algebra_tutoring",
            "duration": "session",
            "requested_categories": ["mastery", "learning_preferences"],
        })
        bundle = resp.json()
        assert len(bundle["items"]) == 2
        assert len(bundle["redactions_applied"]) == 0
        assert bundle["bundle_id"].startswith("ctx_")

    def test_partial_grant_redacts_ungranted(self):
        _create_memory(category="mastery", kind="mastery", content="Algebra: 0.8")
        _create_memory(category="learning_preferences", content="Likes visual aids")

        # Grant only mastery, not learning_preferences
        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "category_scope": ["mastery"],
            "purpose": "algebra_tutoring",
        })

        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "role": "math_tutor",
            "purpose": "algebra_tutoring",
            "requested_categories": ["mastery", "learning_preferences"],
        })
        bundle = resp.json()
        assert len(bundle["items"]) == 1
        assert bundle["items"][0]["content"] == "Algebra: 0.8"
        assert "learning_preferences" in bundle["redactions_applied"]


# --- Grant management ---


class TestGrants:
    def test_create_and_list_grants(self):
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "category_scope": ["mastery"],
            "purpose": "tutoring",
        })
        assert resp.status_code == 200
        grant = resp.json()
        assert grant["id"].startswith("grant_")

        grants = client.get(f"/grants?subject={TEST_SUBJECT}").json()
        assert len(grants) == 1

    def test_revoke_grant(self):
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "category_scope": ["mastery"],
            "purpose": "tutoring",
        })
        grant_id = resp.json()["id"]

        resp = client.delete(f"/grants/{grant_id}")
        assert resp.status_code == 200

        # Grant should now be revoked
        grants = client.get(f"/grants?subject={TEST_SUBJECT}").json()
        assert grants[0]["revoked"] is True

    def test_revoked_grant_blocks_access(self):
        _create_memory(category="mastery", kind="mastery", content="Algebra: 0.8")

        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "category_scope": ["mastery"],
            "purpose": "tutoring",
        })
        grant_id = resp.json()["id"]
        client.delete(f"/grants/{grant_id}")

        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "role": "tutor",
            "purpose": "tutoring",
            "requested_categories": ["mastery"],
        })
        bundle = resp.json()
        assert len(bundle["items"]) == 0
        assert "mastery" in bundle["redactions_applied"]


# --- Audit trail ---


class TestAudit:
    def test_crud_operations_audited(self):
        mem_id = _create_memory().json()["id"]
        client.get(f"/memories/{TEST_SUBJECT}/{mem_id}")
        client.patch(
            f"/memories/{TEST_SUBJECT}/{mem_id}",
            json={"content": "updated"},
        )
        client.delete(f"/memories/{TEST_SUBJECT}/{mem_id}")

        resp = client.get(f"/audit?subject={TEST_SUBJECT}")
        assert resp.status_code == 200
        entries = resp.json()
        actions = [e["action"] for e in entries]
        assert "create" in actions
        assert "read" in actions
        assert "update" in actions
        assert "delete" in actions

    def test_context_retrieval_audited(self):
        client.post("/context", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "role": "tutor",
            "purpose": "tutoring",
            "requested_categories": ["mastery"],
        })
        entries = client.get(f"/audit?subject={TEST_SUBJECT}").json()
        assert any(e["action"] == "context_retrieval" for e in entries)


# --- MVP acceptance criteria ---


class TestMVPAcceptanceCriteria:
    """Tests mapping to the PRD's MVP acceptance criteria."""

    def test_scoped_session_retrieval(self):
        """A learner can authorize a new math tool to retrieve only math mastery
        and learning preferences for one session."""
        _create_memory(category="mastery", kind="mastery", domain="math", content="Rational expressions: 0.55")
        _create_memory(category="learning_preferences", domain="math", content="Worked examples first")
        _create_memory(category="accessibility", kind="accessibility", content="Needs screen reader")

        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "actor": "app_fantasy_academy",
            "category_scope": ["mastery", "learning_preferences"],
            "purpose": "algebra_tutoring",
            "duration": "session",
        })

        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "actor": "app_fantasy_academy",
            "role": "math_tutor",
            "purpose": "algebra_tutoring",
            "duration": "session",
            "requested_categories": ["mastery", "learning_preferences", "accessibility"],
        })
        bundle = resp.json()
        # Should get mastery and preferences, NOT accessibility
        assert len(bundle["items"]) == 2
        assert "accessibility" in bundle["redactions_applied"]

    def test_all_reads_writes_audited(self):
        """Every read and write is logged and visible in an audit view."""
        mem_id = _create_memory().json()["id"]
        client.get(f"/memories/{TEST_SUBJECT}/{mem_id}")

        entries = client.get(f"/audit?subject={TEST_SUBJECT}").json()
        assert len(entries) >= 2

    def test_revocation_recorded(self):
        """A parent can revoke a grant and the system records the event."""
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "actor": "app_tutor",
            "category_scope": ["mastery"],
            "purpose": "tutoring",
        })
        grant_id = resp.json()["id"]
        resp = client.delete(f"/grants/{grant_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    def test_inspect_correct_version_inference(self):
        """A user can inspect, correct, and version a stored inference."""
        resp = _create_memory(
            kind="inference",
            category="inferences",
            declared_by="system",
            confidence=0.6,
            content="May prefer visual learning.",
        )
        mem_id = resp.json()["id"]
        assert resp.json()["version"] == 1

        # Correct it
        resp = client.patch(
            f"/memories/{TEST_SUBJECT}/{mem_id}",
            json={
                "content": "Confirmed: prefers visual learning.",
                "confidence": 1.0,
                "correction_reason": "Parent confirmed preference",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 2
        assert resp.json()["content"] == "Confirmed: prefers visual learning."
