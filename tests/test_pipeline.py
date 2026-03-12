"""Pipeline tests — ingestion, daily logging, compaction, and retrieval."""

import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.connectors.schema import NormalizedInteraction
from app.connectors.canvas_adapter import CanvasAdapter, sample_canvas_events
from app.connectors.slack_adapter import SlackAdapter, sample_slack_events
from app.daily_logger import DailyLogger
from app.embedding_indexer import EmbeddingIndexer, HashEmbedder
from app.llm_steward import MockSteward
from app.memory_compactor import MemoryCompactor
from app.memory_router import MemoryRouter

client = TestClient(app)

TEST_ROOT = Path("memory_test_pipeline")
TEST_USER = "student_maya"


@pytest.fixture(autouse=True)
def clean_state():
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    yield
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)


# --- Connector tests ---


class TestCanvasAdapter:
    def test_normalize_submission(self):
        events = sample_canvas_events()
        interaction = CanvasAdapter.normalize(events[0])
        assert interaction.source_system == "canvas"
        assert interaction.event_type == "submission"
        assert interaction.actor == "maya.johnson"
        assert interaction.user_id == "student_maya"

    def test_normalize_grade_is_sensitive(self):
        events = sample_canvas_events()
        interaction = CanvasAdapter.normalize(events[1])
        assert interaction.sensitivity == "sensitive"
        assert interaction.event_type == "grade"

    def test_all_sample_events_normalize(self):
        for event in sample_canvas_events():
            interaction = CanvasAdapter.normalize(event)
            assert interaction.interaction_id.startswith("int_")


class TestSlackAdapter:
    def test_normalize_message(self):
        events = sample_slack_events()
        interaction = SlackAdapter.normalize(events[0])
        assert interaction.source_system == "slack"
        assert interaction.event_type == "message"

    def test_dm_is_sensitive(self):
        events = sample_slack_events()
        interaction = SlackAdapter.normalize(events[2])  # DM
        assert interaction.sensitivity == "sensitive"

    def test_project_channel_detection(self):
        events = sample_slack_events()
        interaction = SlackAdapter.normalize(events[0])
        assert interaction.project_id == "math-study-group"


# --- Daily logging tests ---


class TestDailyLogger:
    def test_append_creates_file(self):
        router = MemoryRouter(root=TEST_ROOT)
        logger = DailyLogger(router=router)
        interaction = NormalizedInteraction(
            source_system="test",
            event_type="test_event",
            actor="tester",
            user_id=TEST_USER,
        )
        path = logger.append(TEST_USER, interaction)
        assert path.exists()

    def test_append_multiple_entries(self):
        router = MemoryRouter(root=TEST_ROOT)
        logger = DailyLogger(router=router)
        today = date.today()
        for i in range(3):
            interaction = NormalizedInteraction(
                source_system="test",
                event_type=f"event_{i}",
                actor="tester",
                user_id=TEST_USER,
            )
            logger.append(TEST_USER, interaction, log_date=today)

        entries = logger.read_log(TEST_USER, today)
        assert len(entries) == 3

    def test_read_log_markdown(self):
        router = MemoryRouter(root=TEST_ROOT)
        logger = DailyLogger(router=router)
        interaction = NormalizedInteraction(
            source_system="canvas",
            event_type="submission",
            actor="maya",
            user_id=TEST_USER,
        )
        logger.append(TEST_USER, interaction)
        md = logger.read_log_markdown(TEST_USER, date.today())
        assert md is not None
        assert "Daily Log" in md

    def test_list_log_dates(self):
        router = MemoryRouter(root=TEST_ROOT)
        logger = DailyLogger(router=router)
        interaction = NormalizedInteraction(
            source_system="test",
            event_type="test",
            actor="tester",
            user_id=TEST_USER,
        )
        logger.append(TEST_USER, interaction, log_date=date(2026, 3, 10))
        logger.append(TEST_USER, interaction, log_date=date(2026, 3, 11))
        dates = logger.list_log_dates(TEST_USER)
        assert len(dates) == 2


# --- Memory routing tests ---


class TestMemoryRouter:
    def test_daily_log_path(self):
        router = MemoryRouter(root=TEST_ROOT)
        path = router.daily_log_path("maya", date(2026, 3, 12))
        assert "users/maya/daily/2026-03-12.md" in str(path)

    def test_semantic_memory_path(self):
        router = MemoryRouter(root=TEST_ROOT)
        path = router.semantic_memory_path("maya", "math/algebra")
        assert "users/maya/semantic/math_algebra.md" in str(path)

    def test_routing_selects_correct_file(self):
        """Routing should select correct Markdown file based on type and scope."""
        router = MemoryRouter(root=TEST_ROOT)

        private_path = router.resolve_write_path("maya", "semantic", "private")
        assert "users/maya/semantic" in str(private_path)

        project_path = router.resolve_write_path("maya", "semantic", "project", project_id="MATH101")
        assert "projects/MATH101" in str(project_path)

        policy_path = router.resolve_write_path("maya", "policy", "team")
        assert "policies" in str(policy_path)

    def test_resolve_read_paths(self):
        router = MemoryRouter(root=TEST_ROOT)
        # Create some files
        sem_dir = TEST_ROOT / "users" / "maya" / "semantic"
        sem_dir.mkdir(parents=True, exist_ok=True)
        (sem_dir / "general.md").write_text("test")
        (sem_dir / "math.md").write_text("test")

        paths = router.resolve_read_paths("maya")
        assert len(paths) >= 2


# --- LLM Steward tests ---


class TestMockSteward:
    def test_grade_event_stored(self):
        steward = MockSteward()
        interaction = NormalizedInteraction(
            source_system="canvas",
            event_type="grade",
            actor="maya",
            user_id="maya",
            payload={"score": 92},
        )
        decisions = steward.evaluate([interaction])
        assert len(decisions) == 1
        assert decisions[0].store is True
        assert "92" in decisions[0].summary

    def test_routine_message_not_stored(self):
        steward = MockSteward()
        interaction = NormalizedInteraction(
            source_system="slack",
            event_type="message",
            actor="maya",
            user_id="maya",
            payload={"text_preview": "ok see you later"},
        )
        decisions = steward.evaluate([interaction])
        assert decisions[0].store is False
        assert decisions[0].retention_class == "ephemeral"

    def test_learning_insight_stored(self):
        steward = MockSteward()
        interaction = NormalizedInteraction(
            source_system="slack",
            event_type="message",
            actor="maya",
            user_id="maya",
            payload={"text_preview": "I finally understood rational expressions!", "channel_type": "channel"},
        )
        decisions = steward.evaluate([interaction])
        assert decisions[0].store is True
        assert decisions[0].memory_type == "episodic"


# --- Compaction tests ---


class TestCompaction:
    def test_daily_logs_compact_into_semantic_memory(self):
        """Daily logs should compact into semantic memory."""
        router = MemoryRouter(root=TEST_ROOT)
        logger = DailyLogger(router=router)
        indexer = EmbeddingIndexer(
            db_path=TEST_ROOT / "test_vectors.db",
            embedder=HashEmbedder(),
        )
        steward = MockSteward()
        compactor = MemoryCompactor(
            steward=steward, router=router, logger=logger, indexer=indexer,
        )

        # Create daily log entries
        today = date.today()
        interactions = [
            NormalizedInteraction(
                source_system="canvas",
                event_type="grade",
                actor="maya",
                user_id="maya",
                payload={"score": 85},
            ),
            NormalizedInteraction(
                source_system="slack",
                event_type="message",
                actor="maya",
                user_id="maya",
                payload={"text_preview": "I finally understood the concept!"},
            ),
            NormalizedInteraction(
                source_system="slack",
                event_type="message",
                actor="maya",
                user_id="maya",
                payload={"text_preview": "ok bye"},
            ),
        ]
        for i in interactions:
            logger.append("maya", i, log_date=today)

        # Compact
        result = compactor.compact("maya", today)
        assert result.interactions_evaluated == 3
        assert result.memories_stored >= 2  # grade + learning insight
        assert result.memories_skipped >= 1  # "ok bye"

        # Verify semantic memory file exists
        semantic_dir = TEST_ROOT / "users" / "maya" / "semantic"
        assert semantic_dir.exists()
        semantic_files = list(semantic_dir.glob("*.md"))
        assert len(semantic_files) > 0


# --- API pipeline tests ---


class TestPipelineAPI:
    def test_ingest_single_interaction(self):
        resp = client.post("/ingest", json={
            "source_system": "canvas",
            "event_type": "grade",
            "actor": "maya",
            "user_id": "student_maya",
            "payload": {"score": 88},
            "provenance": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["interaction_id"].startswith("int_")
        assert "logged_to" in data

    def test_ingest_raw_canvas_events(self):
        resp = client.post("/ingest/raw", json={
            "source": "canvas",
            "events": sample_canvas_events(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["events_received"] == 3
        assert len(data["results"]) == 3

    def test_ingest_raw_slack_events(self):
        resp = client.post("/ingest/raw", json={
            "source": "slack",
            "events": sample_slack_events(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["events_received"] == 3

    def test_unknown_source_rejected(self):
        resp = client.post("/ingest/raw", json={
            "source": "unknown_system",
            "events": [{}],
        })
        assert resp.status_code == 400

    def test_pipeline_status(self):
        resp = client.get("/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "operational"
        assert "index_stats" in data


# --- Shared project memory ---


class TestSharedProjectMemory:
    def test_shared_project_memory_visible_to_members(self):
        """Shared project memory should be visible to project members."""
        router = MemoryRouter(root=TEST_ROOT)

        import frontmatter
        project_dir = TEST_ROOT / "projects" / "MATH101"
        project_dir.mkdir(parents=True, exist_ok=True)
        shared_file = project_dir / "shared.md"
        post = frontmatter.Post(content="# Project Notes\n\nShared study notes for algebra.")
        post.metadata = {
            "sharing": {
                "owner": "teacher_jones",
                "scope": "project",
                "sensitivity": "normal",
                "allowed_readers": [],
                "project_id": "MATH101",
            }
        }
        shared_file.write_text(frontmatter.dumps(post))

        indexer = EmbeddingIndexer(
            db_path=TEST_ROOT / "test_vectors_shared.db",
            embedder=HashEmbedder(),
        )
        indexer.index_file(shared_file)

        # Search — project scope should be findable
        results = indexer.search("algebra study notes")
        assert len(results) > 0
        assert results[0].scope == "project"
