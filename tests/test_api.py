"""API tests for the Portable Learner Memory Platform (v3 — semantic documents + entitlements)."""

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


def _create_section(**overrides):
    payload = {
        "document": "USER",
        "heading": "Learning Style Preference",
        "kind": "preference",
        "domain_path": "general",
        "declared_by": "user",
        "provenance": "explicit_statement",
        "confidence": 1.0,
        "classification": "private",
        "content": "Prefers worked examples before formal proofs.",
    }
    payload.update(overrides)
    return client.post(f"/sections/{TEST_SUBJECT}", json=payload)


# --- Section CRUD ---


class TestCreateSection:
    def test_create_section(self):
        resp = _create_section()
        assert resp.status_code == 201
        data = resp.json()
        assert data["document"] == "USER"
        assert data["kind"] == "preference"
        assert data["content"] == "Prefers worked examples before formal proofs."
        assert data["version"] == 1
        assert data["status"] == "active"
        assert data["id"].startswith("sec_")

    def test_create_inference(self):
        resp = _create_section(
            document="MEMORY",
            heading="Multi-step Word Problem Difficulty",
            kind="inference",
            domain_path="math/word_problems",
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
        resp = _create_section(confidence=1.5)
        assert resp.status_code == 422

    def test_markdown_file_created(self):
        _create_section()
        path = MEMORY_ROOT / "subjects" / TEST_SUBJECT / "USER.md"
        assert path.exists()
        content = path.read_text()
        assert "Prefers worked examples" in content
        assert "preference" in content


class TestReadSection:
    def test_read_existing(self):
        sec_id = _create_section().json()["id"]
        resp = client.get(f"/sections/{TEST_SUBJECT}/USER/{sec_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == sec_id

    def test_read_not_found(self):
        resp = client.get(f"/sections/{TEST_SUBJECT}/USER/sec_nonexist")
        assert resp.status_code == 404


class TestListSections:
    def test_list_all(self):
        _create_section(content="Section 1")
        _create_section(content="Section 2", heading="Second Preference")
        resp = client.get(f"/sections/{TEST_SUBJECT}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_filter_by_document(self):
        _create_section(document="USER", content="pref")
        _create_section(
            document="MEMORY", heading="Algebra Mastery", kind="mastery",
            domain_path="math/algebra", content="Algebra mastery score.",
        )
        resp = client.get(f"/sections/{TEST_SUBJECT}?document=MEMORY")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["document"] == "MEMORY"

    def test_filter_by_kind(self):
        _create_section(kind="preference", content="pref")
        _create_section(
            document="MEMORY", heading="Algebra Mastery", kind="mastery",
            domain_path="math/algebra", content="mastery item",
        )
        resp = client.get(f"/sections/{TEST_SUBJECT}?kind=mastery")
        items = resp.json()
        assert len(items) == 1
        assert items[0]["kind"] == "mastery"


class TestUpdateSection:
    def test_update_content(self):
        sec_id = _create_section().json()["id"]
        resp = client.patch(
            f"/sections/{TEST_SUBJECT}/USER/{sec_id}",
            json={"content": "Updated preference.", "correction_reason": "User corrected"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "Updated preference."
        assert data["version"] == 2

    def test_update_not_found(self):
        resp = client.patch(
            f"/sections/{TEST_SUBJECT}/USER/sec_nonexist",
            json={"content": "nope"},
        )
        assert resp.status_code == 404


class TestDeleteSection:
    def test_soft_delete(self):
        sec_id = _create_section().json()["id"]
        resp = client.delete(f"/sections/{TEST_SUBJECT}/USER/{sec_id}")
        assert resp.status_code == 200

        # Should not appear in list (soft-deleted)
        resp = client.get(f"/sections/{TEST_SUBJECT}")
        assert len(resp.json()) == 0

    def test_hard_delete(self):
        sec_id = _create_section().json()["id"]
        resp = client.delete(f"/sections/{TEST_SUBJECT}/USER/{sec_id}?hard=true")
        assert resp.status_code == 200

        # Section should be gone from the document
        resp = client.get(f"/sections/{TEST_SUBJECT}/USER/{sec_id}")
        assert resp.status_code == 404

    def test_delete_not_found(self):
        resp = client.delete(f"/sections/{TEST_SUBJECT}/USER/sec_nonexist")
        assert resp.status_code == 404


# --- Document views ---


class TestDocumentViews:
    def test_read_document(self):
        _create_section()
        resp = client.get(f"/docs/{TEST_SUBJECT}/USER")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document"] == "USER"
        assert len(data["sections"]) == 1
        assert "rendered_markdown" in data

    def test_read_document_markdown(self):
        _create_section()
        resp = client.get(f"/docs/{TEST_SUBJECT}/USER/markdown")
        assert resp.status_code == 200
        data = resp.json()
        assert "# USER" in data["markdown"]
        assert "Prefers worked examples" in data["markdown"]


# --- Fact vs inference separation ---


class TestFactInferenceSeparation:
    def test_facts_and_inferences_separate(self):
        _create_section(
            document="IDENTITY", heading="Birth Year", kind="fact",
            content="Born 2015.",
        )
        _create_section(
            document="MEMORY", heading="Visual Learning Inference", kind="inference",
            domain_path="general/learning_style",
            declared_by="system", provenance="derived",
            confidence=0.6, content="May prefer visual learning.",
        )
        facts = client.get(f"/sections/{TEST_SUBJECT}?kind=fact").json()
        inferences = client.get(f"/sections/{TEST_SUBJECT}?kind=inference").json()
        assert len(facts) == 1
        assert facts[0]["declared_by"] == "user"
        assert len(inferences) == 1
        assert inferences[0]["declared_by"] == "system"
        assert inferences[0]["confidence"] == 0.6


# --- Entitlements catalog ---


class TestEntitlements:
    def test_list_entitlements(self):
        resp = client.get("/entitlements")
        assert resp.status_code == 200
        data = resp.json()
        assert "transcript" in data
        assert "tutoring_session" in data
        assert "parent_review" in data

    def test_get_entitlement(self):
        resp = client.get("/entitlements/transcript")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "transcript"
        assert "IDENTITY" in data["allowed_documents"]
        assert "MEMORY" in data["allowed_documents"]

    def test_entitlement_not_found(self):
        resp = client.get("/entitlements/nonexistent")
        assert resp.status_code == 404


# --- Context retrieval with entitlements ---


class TestContextRetrieval:
    def _seed_sections(self):
        """Create test sections across multiple documents."""
        _create_section(
            document="MEMORY", heading="Algebra Mastery", kind="mastery",
            domain_path="math/algebra", content="Rational expressions: 0.55",
        )
        _create_section(
            document="USER", heading="Visual Preference", kind="preference",
            content="Prefers visual aids and worked examples.",
        )
        _create_section(
            document="USER", heading="Screen Reader Need", kind="accessibility",
            content="Needs screen reader with high contrast mode.",
        )
        _create_section(
            document="IDENTITY", heading="Current Grade", kind="fact",
            content="9th grade at Lincoln High School.",
        )

    def test_retrieval_without_grant_returns_empty(self):
        self._seed_sections()
        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
        })
        assert resp.status_code == 200
        bundle = resp.json()
        assert len(bundle["items"]) == 0
        # All documents should be redacted when no grant exists
        assert len(bundle["redacted_documents"]) > 0

    def test_retrieval_with_grant(self):
        self._seed_sections()
        # Create grant for tutoring_session entitlement
        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
            "duration_hours": 1.0,
        })
        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
        })
        bundle = resp.json()
        # tutoring_session: USER+MEMORY, preference/accessibility/mastery/error_pattern/inference/goal
        # Should get: mastery (MEMORY), preference (USER), accessibility (USER)
        # Should NOT get: fact (IDENTITY) — neither doc nor kind match
        assert len(bundle["items"]) == 3
        assert bundle["bundle_id"].startswith("ctx_")
        kinds = {item["kind"] for item in bundle["items"]}
        assert "mastery" in kinds
        assert "preference" in kinds
        assert "accessibility" in kinds
        assert "fact" not in kinds

    def test_transcript_entitlement_scoping(self):
        """Transcript only gets IDENTITY+MEMORY, only fact/mastery/goal kinds."""
        self._seed_sections()
        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "sis_app",
            "entitlement": "transcript",
            "duration_hours": 24.0,
        })
        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "requester": "sis_app",
            "entitlement": "transcript",
        })
        bundle = resp.json()
        # Should get: mastery (MEMORY), fact (IDENTITY)
        # Should NOT get: preference (USER — wrong doc), accessibility (wrong doc+kind)
        assert len(bundle["items"]) == 2
        kinds = {item["kind"] for item in bundle["items"]}
        assert kinds == {"mastery", "fact"}
        # USER, SOUL, TOOLS, AGENTS should be redacted
        assert "USER" in bundle["redacted_documents"]

    def test_assessment_entitlement_excludes_mastery(self):
        """Assessment only gets accessibility/constraint/policy — no mastery to avoid bias."""
        self._seed_sections()
        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "exam_platform",
            "entitlement": "assessment",
            "duration_hours": 2.0,
        })
        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "requester": "exam_platform",
            "entitlement": "assessment",
        })
        bundle = resp.json()
        # assessment: USER+AGENTS, accessibility/constraint/policy
        # Should get: accessibility (USER)
        # Should NOT get: preference (wrong kind), mastery (wrong doc+kind), fact (wrong doc)
        assert len(bundle["items"]) == 1
        assert bundle["items"][0]["kind"] == "accessibility"
        redacted_kinds = bundle["redacted_kinds"]
        assert "mastery" in redacted_kinds

    def test_parent_review_gets_everything(self):
        """Parent review entitlement sees all documents and all kinds."""
        self._seed_sections()
        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "parent_maria",
            "entitlement": "parent_review",
            "duration_hours": 720.0,
        })
        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "requester": "parent_maria",
            "entitlement": "parent_review",
        })
        bundle = resp.json()
        # parent_review: ALL docs, ALL kinds
        assert len(bundle["items"]) == 4
        assert len(bundle["redacted_documents"]) == 0


# --- Grant management ---


class TestGrants:
    def test_create_and_list_grants(self):
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
            "duration_hours": 1.0,
        })
        assert resp.status_code == 200
        grant = resp.json()
        assert grant["id"].startswith("grant_")
        assert grant["entitlement"] == "tutoring_session"
        assert grant["valid"] is True

        grants = client.get(f"/grants?subject={TEST_SUBJECT}").json()
        assert len(grants) == 1

    def test_revoke_grant(self):
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
        })
        grant_id = resp.json()["id"]

        resp = client.delete(f"/grants/{grant_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

        # Grant should now be revoked
        grants = client.get(f"/grants?subject={TEST_SUBJECT}").json()
        assert grants[0]["revoked"] is True

    def test_revoked_grant_blocks_context(self):
        _create_section(
            document="MEMORY", heading="Algebra Mastery", kind="mastery",
            domain_path="math/algebra", content="Algebra: 0.8",
        )
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
        })
        grant_id = resp.json()["id"]
        client.delete(f"/grants/{grant_id}")

        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
        })
        bundle = resp.json()
        assert len(bundle["items"]) == 0

    def test_unknown_entitlement_rejected(self):
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "nonexistent_entitlement",
        })
        assert resp.status_code == 400


# --- Audit trail ---


class TestAudit:
    def test_crud_operations_audited(self):
        sec_id = _create_section().json()["id"]
        client.get(f"/sections/{TEST_SUBJECT}/USER/{sec_id}")
        client.patch(
            f"/sections/{TEST_SUBJECT}/USER/{sec_id}",
            json={"content": "updated"},
        )
        client.delete(f"/sections/{TEST_SUBJECT}/USER/{sec_id}")

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
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
        })
        entries = client.get(f"/audit?subject={TEST_SUBJECT}").json()
        assert any(e["action"] == "context_retrieval" for e in entries)


# --- Domain tree index ---


class TestDomainTree:
    def _seed_tree(self):
        _create_section(
            document="MEMORY", heading="Algebra Mastery", kind="mastery",
            domain_path="math/algebra", confidence=0.75,
            content="Algebra mastery assessment.",
        )
        _create_section(
            document="MEMORY", heading="Geometry Mastery", kind="mastery",
            domain_path="math/geometry", confidence=0.90,
            content="Geometry mastery assessment.",
        )
        _create_section(
            document="MEMORY", heading="Sign Error Pattern", kind="error_pattern",
            domain_path="math/algebra", confidence=0.85,
            content="Frequently drops negative signs.",
        )

    def test_tree_endpoint(self):
        self._seed_tree()
        resp = client.get(f"/tree/{TEST_SUBJECT}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == TEST_SUBJECT
        assert data["total_sections"] == 3
        assert "math" in data["children"]

    def test_tree_ascii(self):
        self._seed_tree()
        resp = client.get(f"/tree/{TEST_SUBJECT}/ascii")
        assert resp.status_code == 200
        tree_text = resp.json()["tree"]
        assert "math" in tree_text
        assert "algebra" in tree_text
        assert "geometry" in tree_text

    def test_tree_paths(self):
        self._seed_tree()
        resp = client.get(f"/tree/{TEST_SUBJECT}/paths")
        assert resp.status_code == 200
        paths = resp.json()["paths"]
        assert "math/algebra" in paths
        assert "math/geometry" in paths

    def test_tree_subtree(self):
        self._seed_tree()
        resp = client.get(f"/tree/{TEST_SUBJECT}/at/math/algebra")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "algebra"
        assert data["total_sections"] == 2  # mastery + error_pattern

    def test_tree_subtree_not_found(self):
        self._seed_tree()
        resp = client.get(f"/tree/{TEST_SUBJECT}/at/science/biology")
        assert resp.status_code == 404

    def test_tree_markdown(self):
        self._seed_tree()
        resp = client.get(f"/tree/{TEST_SUBJECT}/markdown")
        assert resp.status_code == 200
        md = resp.json()["markdown"]
        assert "# INDEX" in md
        assert "Domain Tree" in md

    def test_tree_rebuild(self):
        self._seed_tree()
        resp = client.post(f"/tree/{TEST_SUBJECT}/rebuild")
        assert resp.status_code == 200
        assert resp.json()["total_sections"] == 3

    def test_index_md_created_on_disk(self):
        self._seed_tree()
        path = MEMORY_ROOT / "subjects" / TEST_SUBJECT / "INDEX.md"
        assert path.exists()
        content = path.read_text()
        assert "INDEX" in content

    def test_tree_rollup_stats(self):
        self._seed_tree()
        resp = client.get(f"/tree/{TEST_SUBJECT}")
        data = resp.json()
        # Root should have mastery_avg from the two mastery sections
        assert "mastery_avg" in data
        assert data["error_pattern_count"] == 1
        # Math subtree
        math_node = data["children"]["math"]
        assert math_node["total_sections"] == 3


# --- MVP acceptance criteria (updated for v3) ---


class TestMVPAcceptanceCriteria:
    def test_scoped_session_retrieval(self):
        """A learner authorizes a tutoring tool — it gets only what the entitlement allows."""
        _create_section(
            document="MEMORY", heading="Rational Expressions", kind="mastery",
            domain_path="math/algebra", content="Rational expressions: 0.55",
        )
        _create_section(
            document="USER", heading="Worked Examples Preference", kind="preference",
            content="Worked examples first.",
        )
        _create_section(
            document="USER", heading="Screen Reader", kind="accessibility",
            content="Needs screen reader.",
        )
        _create_section(
            document="IDENTITY", heading="School", kind="fact",
            content="Lincoln High School.",
        )

        client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "app_fantasy_academy",
            "entitlement": "tutoring_session",
            "duration_hours": 1.0,
        })

        resp = client.post("/context", json={
            "subject": TEST_SUBJECT,
            "requester": "app_fantasy_academy",
            "entitlement": "tutoring_session",
        })
        bundle = resp.json()
        # tutoring_session: USER+MEMORY, preference/accessibility/mastery/error_pattern/inference/goal
        # Should get mastery, preference, accessibility (3 items)
        # Should NOT get fact from IDENTITY
        kinds = {item["kind"] for item in bundle["items"]}
        assert "mastery" in kinds
        assert "preference" in kinds
        assert "accessibility" in kinds
        assert "fact" not in kinds

    def test_all_reads_writes_audited(self):
        """Every read and write is logged in the audit trail."""
        sec_id = _create_section().json()["id"]
        client.get(f"/sections/{TEST_SUBJECT}/USER/{sec_id}")

        entries = client.get(f"/audit?subject={TEST_SUBJECT}").json()
        assert len(entries) >= 2

    def test_revocation_recorded(self):
        """A parent can revoke a grant."""
        resp = client.post("/grants", json={
            "subject": TEST_SUBJECT,
            "requester": "app_tutor",
            "entitlement": "tutoring_session",
        })
        grant_id = resp.json()["id"]
        resp = client.delete(f"/grants/{grant_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    def test_inspect_correct_version_inference(self):
        """A user can inspect, correct, and version a stored inference."""
        resp = _create_section(
            document="MEMORY", heading="Visual Learning Guess", kind="inference",
            domain_path="general/learning_style",
            declared_by="system", confidence=0.6,
            content="May prefer visual learning.",
        )
        sec_id = resp.json()["id"]
        assert resp.json()["version"] == 1

        resp = client.patch(
            f"/sections/{TEST_SUBJECT}/MEMORY/{sec_id}",
            json={
                "content": "Confirmed: prefers visual learning.",
                "confidence": 1.0,
                "correction_reason": "Parent confirmed preference",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 2
        assert resp.json()["content"] == "Confirmed: prefers visual learning."
