"""Canvas LMS adapter — normalizes Canvas webhook/API events."""

from datetime import datetime, timezone

from app.connectors.schema import NormalizedInteraction


class CanvasAdapter:
    """Converts Canvas LMS events into NormalizedInteraction format."""

    SOURCE = "canvas"

    @staticmethod
    def normalize(raw_event: dict) -> NormalizedInteraction:
        """Convert a Canvas event payload to normalized interaction.

        Canvas events typically include: event_type, user_id, assignment_id,
        submission data, grades, timestamps, etc.
        """
        event_type_map = {
            "submission_created": "submission",
            "submission_updated": "submission_update",
            "grade_change": "grade",
            "assignment_created": "assignment",
            "quiz_submitted": "quiz_submission",
            "discussion_entry_created": "discussion_post",
        }

        canvas_type = raw_event.get("event_type", "unknown")
        normalized_type = event_type_map.get(canvas_type, canvas_type)

        # Extract user from Canvas event structure
        user_id = raw_event.get("user_id") or raw_event.get("body", {}).get("user_id")
        actor = raw_event.get("user_login", f"canvas_user_{user_id}")

        # Parse Canvas timestamp
        ts_str = raw_event.get("created_at")
        timestamp = (
            datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts_str
            else datetime.now(timezone.utc)
        )

        # Determine sensitivity based on event type
        sensitivity = "normal"
        if canvas_type in ("grade_change",):
            sensitivity = "sensitive"

        # Build payload with relevant Canvas fields
        body = raw_event.get("body", {})
        payload = {
            "canvas_event_type": canvas_type,
            "course_id": raw_event.get("course_id"),
            "assignment_id": body.get("assignment_id") or raw_event.get("assignment_id"),
        }
        # Extract score/grade from body or top-level
        for key in ("score", "grade", "submission_type", "assignment"):
            val = body.get(key) or raw_event.get(key)
            if val is not None:
                payload[key] = val
        if "body" in body:
            payload["content_preview"] = body["body"][:500]

        return NormalizedInteraction(
            source_system=CanvasAdapter.SOURCE,
            event_type=normalized_type,
            actor=actor,
            timestamp=timestamp,
            payload=payload,
            object_id=raw_event.get("body", {}).get("assignment_id"),
            object_type="assignment" if "assignment_id" in raw_event.get("body", {}) else None,
            sensitivity=sensitivity,
            provenance="canvas_webhook",
            user_id=str(user_id) if user_id else None,
            project_id=str(raw_event.get("course_id")) if raw_event.get("course_id") else None,
        )


# Convenience for demo data generation
def sample_canvas_events() -> list[dict]:
    """Return sample Canvas events for testing."""
    return [
        {
            "event_type": "submission_created",
            "user_id": "student_maya",
            "user_login": "maya.johnson",
            "course_id": "MATH101",
            "created_at": "2026-03-12T10:30:00Z",
            "body": {
                "assignment_id": "hw_rational_expressions",
                "user_id": "student_maya",
                "submission_type": "online_text_entry",
                "score": 78,
                "body": "Completed rational expressions worksheet. Showed work for all problems but made sign errors in problems 3 and 7.",
            },
        },
        {
            "event_type": "grade_change",
            "user_id": "student_maya",
            "user_login": "maya.johnson",
            "course_id": "MATH101",
            "created_at": "2026-03-12T14:00:00Z",
            "body": {
                "assignment_id": "quiz_chapter5",
                "user_id": "student_maya",
                "score": 92,
                "grade": "A-",
            },
        },
        {
            "event_type": "quiz_submitted",
            "user_id": "student_maya",
            "user_login": "maya.johnson",
            "course_id": "MATH101",
            "created_at": "2026-03-12T15:45:00Z",
            "body": {
                "assignment_id": "quiz_geometry_basics",
                "user_id": "student_maya",
                "submission_type": "online_quiz",
                "score": 95,
            },
        },
    ]
