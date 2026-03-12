"""Governance tests — entitlements, sharing, and access control."""

import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.embedding_indexer import EmbeddingIndexer, HashEmbedder
from app.entitlement_service import EntitlementService
from app.memory_router import MemoryRouter
from app.sharing import SharingMetadata, SharingScope, check_access

client = TestClient(app)

TEST_ROOT = Path("memory_test_gov")


@pytest.fixture(autouse=True)
def clean_state():
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    yield
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)


# --- Sharing scope tests ---


class TestSharingAccess:
    def test_owner_always_has_access(self):
        sharing = SharingMetadata(owner="maya", scope=SharingScope.private)
        assert check_access(sharing, "maya") is True

    def test_private_blocks_others(self):
        sharing = SharingMetadata(owner="maya", scope=SharingScope.private)
        assert check_access(sharing, "tutor_sarah") is False

    def test_global_allows_everyone(self):
        sharing = SharingMetadata(owner="maya", scope=SharingScope.global_)
        assert check_access(sharing, "anyone") is True

    def test_explicit_reader_allowed(self):
        sharing = SharingMetadata(
            owner="maya",
            scope=SharingScope.private,
            allowed_readers=["tutor_sarah"],
        )
        assert check_access(sharing, "tutor_sarah") is True
        assert check_access(sharing, "random_user") is False

    def test_project_scope_checks_membership(self):
        sharing = SharingMetadata(
            owner="maya",
            scope=SharingScope.project,
            project_id="MATH101",
        )
        # Project member
        assert check_access(sharing, "tutor_sarah", reader_projects=["MATH101"]) is True
        # Not a member
        assert check_access(sharing, "tutor_sarah", reader_projects=["ENG201"]) is False


# --- Entitlement service tests ---


class TestEntitlementService:
    def test_create_and_get(self):
        svc = EntitlementService(root=TEST_ROOT)
        ent = svc.create(
            memory_path="memory/users/maya/semantic/general.md",
            owner="maya",
            scope="private",
        )
        assert ent.entitlement_id.startswith("ent_")
        retrieved = svc.get(ent.entitlement_id)
        assert retrieved is not None
        assert retrieved.owner == "maya"

    def test_grant_and_revoke_reader(self):
        svc = EntitlementService(root=TEST_ROOT)
        ent = svc.create(
            memory_path="memory/users/maya/semantic/general.md",
            owner="maya",
        )
        # Grant
        svc.grant_reader(ent.entitlement_id, "tutor_sarah", purpose="tutoring")
        ent = svc.get(ent.entitlement_id)
        assert "tutor_sarah" in ent.allowed_readers

        # Revoke
        svc.revoke_reader(ent.entitlement_id, "tutor_sarah")
        ent = svc.get(ent.entitlement_id)
        assert "tutor_sarah" not in ent.allowed_readers

    def test_check_access(self):
        svc = EntitlementService(root=TEST_ROOT)
        svc.create(
            memory_path="memory/users/maya/semantic/general.md",
            owner="maya",
            allowed_readers=["tutor_sarah"],
        )
        assert svc.check_access("memory/users/maya/semantic/general.md", "maya") is True
        assert svc.check_access("memory/users/maya/semantic/general.md", "tutor_sarah") is True
        assert svc.check_access("memory/users/maya/semantic/general.md", "random") is False

    def test_list_for_owner(self):
        svc = EntitlementService(root=TEST_ROOT)
        svc.create(memory_path="path1", owner="maya")
        svc.create(memory_path="path2", owner="maya")
        svc.create(memory_path="path3", owner="other")
        assert len(svc.list_for_owner("maya")) == 2

    def test_sensitivity_filtering_in_entitlement_changes(self):
        """Changes in entitlements should affect retrieval."""
        svc = EntitlementService(root=TEST_ROOT)
        ent = svc.create(
            memory_path="path1",
            owner="maya",
            scope="private",
        )
        # Initially no access for tutor
        assert svc.check_access("path1", "tutor_sarah") is False

        # Grant access
        svc.grant_reader(ent.entitlement_id, "tutor_sarah")
        assert svc.check_access("path1", "tutor_sarah") is True

        # Revoke access
        svc.revoke_reader(ent.entitlement_id, "tutor_sarah")
        assert svc.check_access("path1", "tutor_sarah") is False


# --- Entitlement management API tests ---


class TestEntitlementAPI:
    def test_create_entitlement_via_api(self):
        resp = client.post("/manage/entitlements", json={
            "memory_path": "memory/users/maya/semantic/general.md",
            "owner": "maya",
            "scope": "private",
            "sensitivity": "normal",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner"] == "maya"
        assert data["entitlement_id"].startswith("ent_")

    def test_list_entitlements_via_api(self):
        client.post("/manage/entitlements", json={
            "memory_path": "path1", "owner": "maya",
        })
        resp = client.get("/manage/entitlements")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_check_access_via_api(self):
        client.post("/manage/entitlements", json={
            "memory_path": "test/path.md",
            "owner": "maya",
            "allowed_readers": ["tutor_sarah"],
        })
        resp = client.get("/manage/check-access?memory_path=test/path.md&reader_id=tutor_sarah")
        assert resp.status_code == 200
        assert resp.json()["has_access"] is True

        resp = client.get("/manage/check-access?memory_path=test/path.md&reader_id=stranger")
        assert resp.json()["has_access"] is False


# --- Embedding indexer with governance ---


class TestEmbeddingGovernance:
    def test_sensitive_content_filtered(self):
        """Sensitive content should be filtered unless permitted."""
        indexer = EmbeddingIndexer(
            db_path=TEST_ROOT / "test_vectors.db",
            embedder=HashEmbedder(),
        )

        # Create a test markdown file with sensitive content
        import frontmatter
        test_file = TEST_ROOT / "sensitive_test.md"
        post = frontmatter.Post(
            content="# Secret\n\nThis is sensitive data about the student.",
        )
        post.metadata = {
            "sharing": {
                "owner": "maya",
                "scope": "private",
                "sensitivity": "sensitive",
                "allowed_readers": [],
            }
        }
        test_file.write_text(frontmatter.dumps(post))

        # Index it
        indexer.index_file(test_file)

        # Search with normal sensitivity max — should filter it out
        results = indexer.search(
            "sensitive data",
            sensitivity_max="normal",
        )
        assert len(results) == 0

        # Search with sensitive max — should find it
        results = indexer.search(
            "sensitive data",
            sensitivity_max="sensitive",
        )
        assert len(results) > 0

    def test_private_memory_not_visible_to_others(self):
        """Private memory should not be visible to other users."""
        indexer = EmbeddingIndexer(
            db_path=TEST_ROOT / "test_vectors2.db",
            embedder=HashEmbedder(),
        )

        import frontmatter
        test_file = TEST_ROOT / "private_test.md"
        post = frontmatter.Post(content="# My Private Notes\n\nPersonal study strategy.")
        post.metadata = {
            "sharing": {
                "owner": "maya",
                "scope": "private",
                "sensitivity": "normal",
                "allowed_readers": [],
            }
        }
        test_file.write_text(frontmatter.dumps(post))
        indexer.index_file(test_file)

        # Owner can see it
        results = indexer.search("study strategy", reader_id="maya")
        assert len(results) > 0

        # Others cannot
        results = indexer.search("study strategy", reader_id="stranger")
        assert len(results) == 0
