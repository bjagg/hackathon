"""Local LLM memory steward — decides what interactions become durable memory.

Acts as a fiduciary memory steward using the ethics prompt to guide decisions.
Supports pluggable backends: mock (always works), Ollama, or LangChain LLM.
"""

import json
import os
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from app.connectors.schema import NormalizedInteraction

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class MemoryAdmissionDecision(BaseModel):
    """Structured output from the memory steward."""
    interaction_id: str
    store: bool
    summary: str = ""
    memory_type: str = "semantic"        # episodic, semantic, policy
    sensitivity: str = "normal"          # normal, sensitive, restricted
    retention_class: str = "long_term"   # permanent, long_term, short_term, ephemeral
    shareability: str = "private"        # private, project, team, global
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason_for_decision: str = ""


class StewardBackend(Protocol):
    """Protocol for memory steward backends."""
    def evaluate(self, interactions: list[NormalizedInteraction]) -> list[MemoryAdmissionDecision]: ...


def _load_prompt(name: str) -> str:
    """Load a prompt file from the prompts directory."""
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text()
    return ""


class MockSteward:
    """Rule-based mock steward — works without any LLM dependency.

    Uses heuristics to make reasonable admission decisions for demo purposes.
    """

    def evaluate(self, interactions: list[NormalizedInteraction]) -> list[MemoryAdmissionDecision]:
        decisions = []
        for interaction in interactions:
            decision = self._evaluate_one(interaction)
            decisions.append(decision)
        return decisions

    def _evaluate_one(self, interaction: NormalizedInteraction) -> MemoryAdmissionDecision:
        # Heuristic rules based on event type and content
        event = interaction.event_type
        payload = interaction.payload

        # Grade/score events → always store as semantic memory
        if event in ("grade", "submission") and payload.get("score") is not None:
            score = payload.get("score", 0)
            return MemoryAdmissionDecision(
                interaction_id=interaction.interaction_id,
                store=True,
                summary=f"Score of {score} on {payload.get('canvas_event_type', event)} "
                        f"({interaction.source_system})",
                memory_type="semantic",
                sensitivity="sensitive" if interaction.sensitivity == "sensitive" else "normal",
                retention_class="long_term",
                shareability="private",
                confidence=0.85,
                reason_for_decision=f"Academic performance data (score={score}) is valuable "
                                    "for tracking mastery progression.",
            )

        # Quiz submissions → store with high confidence
        if event == "quiz_submission":
            score = payload.get("score")
            return MemoryAdmissionDecision(
                interaction_id=interaction.interaction_id,
                store=True,
                summary=f"Quiz completed with score {score}" if score else "Quiz submitted",
                memory_type="semantic",
                sensitivity="normal",
                retention_class="long_term",
                shareability="private",
                confidence=0.9,
                reason_for_decision="Quiz results directly measure understanding and inform mastery tracking.",
            )

        # Messages with learning insights → store as episodic
        if event == "message":
            text = payload.get("text_preview", "")
            learning_keywords = [
                "understood", "learned", "figured out", "struggling",
                "breakthrough", "finally", "key is", "insight",
                "confused", "help with", "makes sense",
            ]
            has_learning_signal = any(kw in text.lower() for kw in learning_keywords)

            if has_learning_signal:
                # Check if this is a private/sensitive message
                channel_type = payload.get("channel_type", "channel")
                sensitivity = "sensitive" if channel_type == "im" else "normal"

                return MemoryAdmissionDecision(
                    interaction_id=interaction.interaction_id,
                    store=True,
                    summary=f"Learning insight from {interaction.source_system}: {text[:150]}",
                    memory_type="episodic",
                    sensitivity=sensitivity,
                    retention_class="short_term",
                    shareability="private" if sensitivity == "sensitive" else "project",
                    confidence=0.7,
                    reason_for_decision="Message contains learning-relevant signal that may "
                                        "inform future tutoring or mastery assessment.",
                )

            # Routine messages → don't store
            return MemoryAdmissionDecision(
                interaction_id=interaction.interaction_id,
                store=False,
                summary="",
                memory_type="episodic",
                sensitivity=interaction.sensitivity,
                retention_class="ephemeral",
                shareability="private",
                confidence=0.8,
                reason_for_decision="Routine message without clear learning signal. "
                                    "Minimal storage principle: do not store.",
            )

        # Default: store with low confidence
        return MemoryAdmissionDecision(
            interaction_id=interaction.interaction_id,
            store=True,
            summary=interaction.summary_line(),
            memory_type="episodic",
            sensitivity=interaction.sensitivity,
            retention_class="short_term",
            shareability="private",
            confidence=0.5,
            reason_for_decision=f"Unrecognized event type '{event}'. Storing with low confidence "
                                "for review.",
        )


class LLMSteward:
    """LLM-backed steward using Ollama for real inference.

    Falls back to MockSteward if the LLM is unavailable.
    """

    def __init__(self, model_name: str = "llama3.2"):
        self.model_name = model_name
        self.system_prompt = _load_prompt("steward_prompt.md")
        self.ethics_prompt = _load_prompt("ethics_prompt.md")
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            try:
                from langchain_ollama import ChatOllama
                self._llm = ChatOllama(model=self.model_name, temperature=0.1)
            except Exception:
                return None
        return self._llm

    def evaluate(self, interactions: list[NormalizedInteraction]) -> list[MemoryAdmissionDecision]:
        llm = self._get_llm()
        if llm is None:
            return MockSteward().evaluate(interactions)

        # Build rich interaction descriptions
        interactions_text = "\n".join(
            f"- ID: {i.interaction_id}\n"
            f"  Source: {i.source_system}\n"
            f"  Event type: {i.event_type}\n"
            f"  Actor: {i.actor}\n"
            f"  User: {i.user_id}\n"
            f"  Sensitivity: {i.sensitivity}\n"
            f"  Payload: {json.dumps(i.payload)[:500]}"
            for i in interactions
        )

        prompt = (
            f"{self.system_prompt}\n\n"
            f"## Ethics Guidelines\n{self.ethics_prompt}\n\n"
            f"## Interactions to evaluate:\n{interactions_text}\n\n"
            "IMPORTANT: Grades, scores, quiz results, and submissions with scores "
            "are academically significant and SHOULD be stored as semantic memories "
            "with long_term retention.\n\n"
            "Return ONLY a JSON array with one object per interaction. No other text."
        )

        try:
            response = llm.invoke(prompt)
            text = response.content if hasattr(response, 'content') else str(response)
            json_start = text.find("[")
            json_end = text.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                decisions_data = json.loads(text[json_start:json_end])
                return [MemoryAdmissionDecision.model_validate(d) for d in decisions_data]
        except Exception:
            pass

        return MockSteward().evaluate(interactions)


def get_steward(backend: str = "auto") -> StewardBackend:
    """Get the appropriate steward backend.

    Args:
        backend: "mock", "llm", or "auto" (try LLM, fall back to mock)
    """
    if backend == "mock":
        return MockSteward()
    if backend == "llm":
        return LLMSteward()
    # Auto: check if Ollama is available
    if backend == "auto":
        try:
            import subprocess
            result = subprocess.run(
                ["ollama", "list"], capture_output=True, timeout=3
            )
            if result.returncode == 0:
                return LLMSteward()
        except Exception:
            pass
    return MockSteward()


# Module-level default
memory_steward = get_steward(os.environ.get("STEWARD_BACKEND", "mock"))
