"""Daily interaction logging — appends normalized interactions to Markdown daily logs.

Each user gets a daily log at: memory/users/{user_id}/daily/YYYY-MM-DD.md

Logs use YAML front matter for metadata and append interaction entries as
Markdown sections.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import frontmatter

from app.connectors.schema import NormalizedInteraction
from app.memory_router import memory_router


class DailyLogger:
    """Appends interactions to per-user daily Markdown log files."""

    def __init__(self, router=None):
        self.router = router or memory_router

    def append(
        self,
        user_id: str,
        interaction: NormalizedInteraction,
        log_date: date | None = None,
    ) -> Path:
        """Append an interaction entry to the user's daily log.

        Creates the file if it doesn't exist, appends if it does.
        Returns the path to the log file.
        """
        d = log_date or interaction.timestamp.date()
        path = self.router.daily_log_path(user_id, d)

        if path.exists():
            post = frontmatter.load(str(path))
            entries = post.metadata.get("entries", [])
        else:
            post = frontmatter.Post(content="")
            post.metadata = {
                "user_id": user_id,
                "date": d.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "entry_count": 0,
                "entries": [],
            }
            entries = []

        # Add the interaction as a structured entry
        entry = {
            "interaction_id": interaction.interaction_id,
            "timestamp": interaction.timestamp.isoformat(),
            "source": interaction.source_system,
            "event_type": interaction.event_type,
            "actor": interaction.actor,
            "sensitivity": interaction.sensitivity,
            "provenance": interaction.provenance,
            "summary": interaction.summary_line(),
            "payload": interaction.payload,
        }
        entries.append(entry)
        post.metadata["entries"] = entries
        post.metadata["entry_count"] = len(entries)
        post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Rebuild the markdown content
        post.content = self._render_log(user_id, d, entries)
        path.write_text(frontmatter.dumps(post))
        return path

    def append_batch(
        self, user_id: str, interactions: list[NormalizedInteraction]
    ) -> list[Path]:
        """Append multiple interactions, grouping by date."""
        paths = set()
        for interaction in interactions:
            p = self.append(user_id, interaction)
            paths.add(p)
        return list(paths)

    def read_log(self, user_id: str, log_date: date) -> list[dict]:
        """Read entries from a daily log file."""
        path = self.router.daily_log_path(user_id, log_date)
        if not path.exists():
            return []
        post = frontmatter.load(str(path))
        return post.metadata.get("entries", [])

    def read_log_markdown(self, user_id: str, log_date: date) -> str | None:
        """Read the rendered markdown from a daily log."""
        path = self.router.daily_log_path(user_id, log_date)
        if not path.exists():
            return None
        post = frontmatter.load(str(path))
        return post.content

    def list_log_dates(self, user_id: str) -> list[date]:
        """List all dates that have daily logs for a user."""
        daily_dir = self.router.root / "users" / user_id / "daily"
        if not daily_dir.exists():
            return []
        dates = []
        for p in sorted(daily_dir.glob("*.md")):
            try:
                dates.append(date.fromisoformat(p.stem))
            except ValueError:
                continue
        return dates

    def _render_log(self, user_id: str, log_date: date, entries: list[dict]) -> str:
        """Render daily log entries as human-readable Markdown."""
        lines = [
            f"# Daily Log — {user_id}",
            f"**Date**: {log_date.isoformat()}",
            f"**Entries**: {len(entries)}",
            "",
            "---",
            "",
        ]
        for i, entry in enumerate(entries, 1):
            ts = entry.get("timestamp", "")
            if "T" in ts:
                time_part = ts.split("T")[1][:8]
            else:
                time_part = ts
            lines.append(f"### {i}. {entry.get('summary', 'Unknown event')}")
            lines.append("")
            lines.append(f"- **Time**: {time_part}")
            lines.append(f"- **Source**: {entry.get('source', '?')}")
            lines.append(f"- **Type**: {entry.get('event_type', '?')}")
            lines.append(f"- **Actor**: {entry.get('actor', '?')}")
            if entry.get("sensitivity") != "normal":
                lines.append(f"- **Sensitivity**: {entry.get('sensitivity')}")
            lines.append(f"- **Provenance**: {entry.get('provenance', '?')}")
            lines.append("")

        return "\n".join(lines)


daily_logger = DailyLogger()
