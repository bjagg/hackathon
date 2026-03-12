"""Slack adapter — normalizes Slack messages/events."""

from datetime import datetime, timezone

from app.connectors.schema import NormalizedInteraction


class SlackAdapter:
    """Converts Slack events into NormalizedInteraction format."""

    SOURCE = "slack"

    @staticmethod
    def normalize(raw_event: dict) -> NormalizedInteraction:
        """Convert a Slack event payload to normalized interaction.

        Slack events typically include: type, user, channel, ts, text, etc.
        """
        event_type_map = {
            "message": "message",
            "reaction_added": "reaction",
            "file_shared": "file_share",
            "channel_join": "channel_join",
        }

        slack_type = raw_event.get("type", "message")
        normalized_type = event_type_map.get(slack_type, slack_type)

        actor = raw_event.get("user", "unknown")
        user_id = raw_event.get("user_id", actor)

        # Parse Slack timestamp
        ts = raw_event.get("ts")
        timestamp = (
            datetime.fromtimestamp(float(ts), tz=timezone.utc)
            if ts
            else datetime.now(timezone.utc)
        )

        # Determine sensitivity — DMs and certain channels are sensitive
        channel = raw_event.get("channel", "")
        sensitivity = "normal"
        if raw_event.get("channel_type") == "im":
            sensitivity = "sensitive"
        if raw_event.get("is_private", False):
            sensitivity = "sensitive"

        # Build payload
        text = raw_event.get("text", "")
        payload = {
            "channel": channel,
            "channel_type": raw_event.get("channel_type", "channel"),
            "text_preview": text[:500] if text else "",
            "thread_ts": raw_event.get("thread_ts"),
            "has_attachments": bool(raw_event.get("files")),
        }

        # Derive project from channel name if it follows conventions
        project_id = None
        if channel.startswith("proj-") or channel.startswith("project-"):
            project_id = channel.split("-", 1)[1] if "-" in channel else None

        return NormalizedInteraction(
            source_system=SlackAdapter.SOURCE,
            event_type=normalized_type,
            actor=actor,
            timestamp=timestamp,
            payload=payload,
            object_id=raw_event.get("client_msg_id"),
            object_type="message",
            sensitivity=sensitivity,
            provenance="slack_events_api",
            user_id=user_id,
            project_id=project_id,
        )


def sample_slack_events() -> list[dict]:
    """Return sample Slack events for testing."""
    return [
        {
            "type": "message",
            "user": "maya.johnson",
            "user_id": "student_maya",
            "channel": "proj-math-study-group",
            "channel_type": "channel",
            "ts": "1741776000.000100",
            "text": "I finally understood how to simplify rational expressions! The key is factoring the numerator and denominator first.",
        },
        {
            "type": "message",
            "user": "tutor_sarah",
            "user_id": "tutor_sarah",
            "channel": "proj-math-study-group",
            "channel_type": "channel",
            "ts": "1741776300.000200",
            "text": "Great insight Maya! That's exactly right. Try applying the same approach to the complex fractions in tonight's homework.",
        },
        {
            "type": "message",
            "user": "maya.johnson",
            "user_id": "student_maya",
            "channel": "dm-maya-tutor",
            "channel_type": "im",
            "is_private": True,
            "ts": "1741777200.000300",
            "text": "I'm still struggling with the word problems though. Can we go over those in our next session?",
        },
    ]
