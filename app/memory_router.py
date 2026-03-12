"""Memory routing — determines which Markdown files to read from and write to.

Routes based on user_id, memory_type, sharing scope, and project context.
The filesystem layout:

    memory/
        users/{user_id}/daily/YYYY-MM-DD.md
        users/{user_id}/semantic/{topic}.md
        projects/{project_id}/shared.md
        shared/team.md
        shared/global.md
        policies/{scope}.md
"""

import os
from datetime import date
from pathlib import Path

from app.connectors.schema import NormalizedInteraction

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))


class MemoryRouter:
    """Routes memory reads and writes to the correct Markdown files."""

    def __init__(self, root: Path | None = None):
        self.root = root or MEMORY_ROOT

    # --- Write routing ---

    def daily_log_path(self, user_id: str, log_date: date | None = None) -> Path:
        """Path for a user's daily interaction log."""
        d = log_date or date.today()
        path = self.root / "users" / user_id / "daily" / f"{d.isoformat()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def semantic_memory_path(self, user_id: str, topic: str = "general") -> Path:
        """Path for a user's semantic memory file."""
        safe_topic = topic.replace("/", "_").replace(" ", "_").lower()
        path = self.root / "users" / user_id / "semantic" / f"{safe_topic}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def project_memory_path(self, project_id: str) -> Path:
        """Path for shared project memory."""
        path = self.root / "projects" / project_id / "shared.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def shared_memory_path(self, scope: str = "team") -> Path:
        """Path for team/global shared memory."""
        path = self.root / "shared" / f"{scope}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def policy_path(self, scope: str = "default") -> Path:
        """Path for policy documents."""
        path = self.root / "policies" / f"{scope}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_write_path(
        self,
        user_id: str,
        memory_type: str = "semantic",
        scope: str = "private",
        project_id: str | None = None,
        topic: str = "general",
    ) -> Path:
        """Determine which file should receive a new memory."""
        if memory_type == "policy":
            return self.policy_path(scope)
        if scope == "project" and project_id:
            return self.project_memory_path(project_id)
        if scope in ("team", "global"):
            return self.shared_memory_path(scope)
        # Default: private semantic memory
        return self.semantic_memory_path(user_id, topic)

    # --- Read routing ---

    def resolve_read_paths(
        self,
        user_id: str,
        project_ids: list[str] | None = None,
        include_shared: bool = True,
        include_policies: bool = True,
    ) -> list[Path]:
        """Determine which files to read for context retrieval.

        Returns paths in priority order: user's own files first, then project,
        then shared, then policies.
        """
        paths = []

        # User's semantic memories
        user_semantic = self.root / "users" / user_id / "semantic"
        if user_semantic.exists():
            paths.extend(sorted(user_semantic.glob("*.md")))

        # Project memories
        if project_ids:
            for pid in project_ids:
                p = self.root / "projects" / pid / "shared.md"
                if p.exists():
                    paths.append(p)

        # Shared memories
        if include_shared:
            shared_dir = self.root / "shared"
            if shared_dir.exists():
                paths.extend(sorted(shared_dir.glob("*.md")))

        # Policy documents
        if include_policies:
            policy_dir = self.root / "policies"
            if policy_dir.exists():
                paths.extend(sorted(policy_dir.glob("*.md")))

        return paths

    def resolve_daily_logs(
        self, user_id: str, days: int = 7
    ) -> list[Path]:
        """Get recent daily log paths for a user."""
        daily_dir = self.root / "users" / user_id / "daily"
        if not daily_dir.exists():
            return []
        logs = sorted(daily_dir.glob("*.md"), reverse=True)
        return logs[:days]

    # --- Routing from interaction ---

    def route_interaction(self, interaction: NormalizedInteraction) -> Path:
        """Route an interaction to the appropriate daily log."""
        user_id = interaction.user_id or "unknown"
        log_date = interaction.timestamp.date()
        return self.daily_log_path(user_id, log_date)


memory_router = MemoryRouter()
