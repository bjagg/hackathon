"""Chat orchestrator — two-LLM architecture for governed education chat.

Flow:
1. Local Ollama: analyze user message, plan memory retrieval
2. GovernedRetriever: fetch approved memory chunks
3. Cloud LLM (Claude/OpenAI): generate response with approved context
4. Local Ollama: evaluate conversation turn for memory admission
5. If admitted: write through existing memory pipeline
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from uuid import uuid4

from pydantic import BaseModel, Field

from app.cloud_llm import CloudLLMClient, get_cloud_client
from app.connectors.schema import NormalizedInteraction
from app.embedding_indexer import embedding_indexer
from app.langchain_pipeline import PipelineStep, _elapsed_ms, _decision_to_compacted
from app.llm_steward import MemoryAdmissionDecision, memory_steward
from app.memory_compactor import memory_compactor
from app.memory_router import memory_router
from app.retriever import (
    ContextChunk,
    GovernedRetriever,
    RetrievalRequest,
    governed_retriever,
)

logger = logging.getLogger("chat_orchestrator")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(handler)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text() if path.exists() else ""


# --- Models ---


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatSession(BaseModel):
    session_id: str
    user_id: str
    history: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatRequest(BaseModel):
    message: str
    user_id: str
    session_id: str | None = None
    max_sensitivity: str = "normal"


class ChatResponse(BaseModel):
    session_id: str
    message: str
    context_used: list[ContextChunk] = Field(default_factory=list)
    memories_created: list[dict] = Field(default_factory=list)
    steps: list[PipelineStep] = Field(default_factory=list)
    governance_log: dict = Field(default_factory=dict)


# --- Context Planner (Local Ollama) ---


class ContextPlanner:
    """Uses local Ollama to analyze messages and plan retrieval."""

    def __init__(self):
        self.prompt = _load_prompt("chat_context_prompt.md")
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            try:
                from langchain_ollama import ChatOllama
                self._llm = ChatOllama(model="llama3.2", temperature=0.1)
            except Exception:
                return None
        return self._llm

    def plan(self, message: str, history: list[ChatMessage]) -> dict:
        """Analyze message and return retrieval plan."""
        llm = self._get_llm()
        if llm is None:
            return self._fallback_plan(message)

        history_text = "\n".join(
            f"{m.role}: {m.content[:200]}" for m in history[-4:]
        ) if history else "(no history)"

        prompt = (
            f"{self.prompt}\n\n"
            f"## Conversation history:\n{history_text}\n\n"
            f"## Current user message:\n{message}\n\n"
            "Return ONLY the JSON object."
        )

        try:
            response = llm.invoke(prompt)
            text = response.content if hasattr(response, 'content') else str(response)
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(text[json_start:json_end])
        except Exception as e:
            logger.warning(f"Context planner LLM failed: {e}")

        return self._fallback_plan(message)

    def _fallback_plan(self, message: str) -> dict:
        """Keyword-based fallback when Ollama is unavailable."""
        words = message.lower().split()
        academic_keywords = {
            "grade", "score", "quiz", "test", "assignment", "homework",
            "progress", "mastery", "struggle", "help", "understand",
            "math", "science", "reading", "writing", "history",
        }
        has_academic = any(w in academic_keywords for w in words)
        # Use the message itself as the search query
        queries = [message[:200]] if has_academic else []
        return {
            "search_queries": queries,
            "max_sensitivity": "normal",
            "needs_context": has_academic,
            "reasoning": "Keyword-based fallback (Ollama unavailable)",
        }


# --- Admission Evaluator (Local Ollama) ---


class AdmissionEvaluator:
    """Uses local Ollama to evaluate if a chat turn should become memory."""

    def __init__(self):
        self.prompt = _load_prompt("chat_admission_prompt.md")
        self.ethics_prompt = _load_prompt("ethics_prompt.md")
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            try:
                from langchain_ollama import ChatOllama
                self._llm = ChatOllama(model="llama3.2", temperature=0.1)
            except Exception:
                return None
        return self._llm

    def evaluate(self, user_message: str, assistant_response: str, user_id: str) -> dict | None:
        """Evaluate a conversation turn for memory admission."""
        llm = self._get_llm()
        if llm is None:
            return self._fallback_evaluate(user_message)

        prompt = (
            f"{self.prompt}\n\n"
            f"## Ethics Guidelines\n{self.ethics_prompt}\n\n"
            f"## Conversation turn:\n"
            f"User: {user_message[:500]}\n"
            f"Assistant: {assistant_response[:500]}\n\n"
            "Return ONLY the JSON object."
        )

        try:
            response = llm.invoke(prompt)
            text = response.content if hasattr(response, 'content') else str(response)
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(text[json_start:json_end])
                if result.get("store"):
                    return result
        except Exception as e:
            logger.warning(f"Admission evaluator LLM failed: {e}")

        return self._fallback_evaluate(user_message)

    def _fallback_evaluate(self, user_message: str) -> dict | None:
        """Heuristic fallback for chat admission."""
        learning_keywords = [
            "understood", "learned", "struggling", "figured out",
            "breakthrough", "confused", "finally", "goal",
        ]
        has_signal = any(kw in user_message.lower() for kw in learning_keywords)
        if has_signal:
            return {
                "store": True,
                "summary": f"Chat insight: {user_message[:200]}",
                "memory_type": "episodic",
                "sensitivity": "normal",
                "reason": "Learning-relevant signal detected in chat",
            }
        return None


# --- Chat Orchestrator ---


class ChatOrchestrator:
    """Coordinates the two-LLM chat flow."""

    def __init__(self):
        self.sessions: dict[str, ChatSession] = {}
        self.context_planner = ContextPlanner()
        self.admission_evaluator = AdmissionEvaluator()
        self.retriever = governed_retriever
        self.cloud_client: CloudLLMClient = get_cloud_client()
        self.system_prompt = _load_prompt("chat_system_prompt.md")
        self.max_history = int(os.environ.get("CHAT_MAX_HISTORY", "20"))

    def _get_or_create_session(self, request: ChatRequest) -> ChatSession:
        if request.session_id and request.session_id in self.sessions:
            session = self.sessions[request.session_id]
            session.last_active = datetime.now(timezone.utc)
            return session

        session_id = request.session_id or f"chat_{uuid4().hex[:12]}"
        session = ChatSession(session_id=session_id, user_id=request.user_id)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)

    def end_session(self, session_id: str) -> bool:
        return self.sessions.pop(session_id, None) is not None

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Full two-LLM chat flow."""
        steps = []
        governance_log = {}

        session = self._get_or_create_session(request)

        # Step 1: Context planning (local Ollama)
        t0 = datetime.now(timezone.utc)
        plan = self.context_planner.plan(request.message, session.history)
        steps.append(PipelineStep(
            step_name="context_planning",
            detail=f"needs_context={plan.get('needs_context')}, "
                   f"queries={plan.get('search_queries', [])}",
            duration_ms=_elapsed_ms(t0),
        ))
        governance_log["context_plan"] = plan
        logger.info(f"[chat] Context plan: {plan}")

        # Step 2: Governed retrieval
        approved_chunks: list[ContextChunk] = []
        if plan.get("needs_context") and plan.get("search_queries"):
            t0 = datetime.now(timezone.utc)

            # Ensure index is fresh
            user_dir = memory_router.root / "users" / request.user_id
            if user_dir.exists():
                embedding_indexer.index_directory(user_dir)

            for query in plan["search_queries"][:3]:
                retrieval = self.retriever.retrieve(RetrievalRequest(
                    query=query,
                    user_id=request.user_id,
                    reader_id=request.user_id,
                    max_sensitivity=plan.get("max_sensitivity", request.max_sensitivity),
                    top_k=5,
                ))
                # Deduplicate by chunk_id
                seen = {c.chunk_id for c in approved_chunks}
                for chunk in retrieval.chunks:
                    if chunk.chunk_id not in seen:
                        approved_chunks.append(chunk)
                        seen.add(chunk.chunk_id)

            steps.append(PipelineStep(
                step_name="governed_retrieval",
                detail=f"Retrieved {len(approved_chunks)} approved chunks",
                duration_ms=_elapsed_ms(t0),
            ))
            governance_log["chunks_retrieved"] = len(approved_chunks)
            logger.info(f"[chat] Retrieved {len(approved_chunks)} memory chunks")

        # Step 3: Build cloud LLM prompt
        system = self.system_prompt
        if approved_chunks:
            context_text = "\n\n".join(
                f"[Memory: {c.path}]\n{c.text}" for c in approved_chunks[:8]
            )
            system += f"\n\n## Learner Memory Context\n\n{context_text}"

        # Build message history for cloud LLM
        messages = []
        for msg in session.history[-(self.max_history):]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": request.message})

        # Step 4: Cloud LLM generation
        t0 = datetime.now(timezone.utc)
        try:
            cloud_response = self.cloud_client.generate(system, messages)
        except Exception as e:
            logger.error(f"[chat] Cloud LLM error: {e}")
            cloud_response = f"I'm having trouble connecting to the AI service. Error: {str(e)[:200]}"
        steps.append(PipelineStep(
            step_name="cloud_llm_generation",
            detail=f"Generated {len(cloud_response)} chars",
            duration_ms=_elapsed_ms(t0),
        ))

        # Update session history
        session.history.append(ChatMessage(role="user", content=request.message))
        session.history.append(ChatMessage(role="assistant", content=cloud_response))

        # Trim history
        if len(session.history) > self.max_history * 2:
            session.history = session.history[-(self.max_history * 2):]

        # Step 5: Post-response memory admission (local Ollama)
        memories_created = []
        t0 = datetime.now(timezone.utc)
        admission = self.admission_evaluator.evaluate(
            request.message, cloud_response, request.user_id,
        )
        if admission and admission.get("store"):
            try:
                # Create a NormalizedInteraction for the pipeline
                interaction = NormalizedInteraction(
                    source_system="chat",
                    event_type="conversation",
                    actor=request.user_id,
                    user_id=request.user_id,
                    payload={
                        "user_message": request.message[:500],
                        "assistant_response": cloud_response[:500],
                    },
                    sensitivity=admission.get("sensitivity", "normal"),
                    provenance="chat_session",
                )

                decision = MemoryAdmissionDecision(
                    interaction_id=interaction.interaction_id,
                    store=True,
                    summary=admission.get("summary", ""),
                    memory_type=admission.get("memory_type", "episodic"),
                    sensitivity=admission.get("sensitivity", "normal"),
                    retention_class="short_term",
                    shareability="private",
                    confidence=0.7,
                    reason_for_decision=admission.get("reason", "Chat admission"),
                )

                write_path = memory_router.resolve_write_path(
                    user_id=request.user_id,
                    memory_type=decision.memory_type,
                    scope=decision.shareability,
                    topic=decision.memory_type,
                    memory_content=decision.summary,
                )
                memory_compactor._append_memory(
                    write_path,
                    request.user_id,
                    _decision_to_compacted(decision, interaction),
                )
                embedding_indexer.index_file(write_path)

                memories_created.append({
                    "summary": decision.summary,
                    "type": decision.memory_type,
                    "written_to": str(write_path),
                })
                logger.info(f"[chat] New memory created: {decision.summary[:100]}")
            except Exception as e:
                logger.error(f"[chat] Memory write failed: {e}")

        steps.append(PipelineStep(
            step_name="memory_admission",
            detail=f"store={bool(admission and admission.get('store'))}, "
                   f"memories_created={len(memories_created)}",
            duration_ms=_elapsed_ms(t0),
        ))
        governance_log["admission"] = admission

        return ChatResponse(
            session_id=session.session_id,
            message=cloud_response,
            context_used=approved_chunks,
            memories_created=memories_created,
            steps=steps,
            governance_log=governance_log,
        )

    def chat_stream(self, request: ChatRequest) -> Generator[dict, None, None]:
        """Streaming variant — yields token chunks then final metadata."""
        steps = []
        governance_log = {}

        session = self._get_or_create_session(request)

        # Steps 1-2: Context planning + retrieval (same as blocking)
        t0 = datetime.now(timezone.utc)
        plan = self.context_planner.plan(request.message, session.history)
        steps.append(PipelineStep(
            step_name="context_planning",
            detail=f"needs_context={plan.get('needs_context')}",
            duration_ms=_elapsed_ms(t0),
        ))
        governance_log["context_plan"] = plan

        approved_chunks: list[ContextChunk] = []
        if plan.get("needs_context") and plan.get("search_queries"):
            t0 = datetime.now(timezone.utc)
            user_dir = memory_router.root / "users" / request.user_id
            if user_dir.exists():
                embedding_indexer.index_directory(user_dir)

            for query in plan["search_queries"][:3]:
                retrieval = self.retriever.retrieve(RetrievalRequest(
                    query=query,
                    user_id=request.user_id,
                    reader_id=request.user_id,
                    max_sensitivity=plan.get("max_sensitivity", request.max_sensitivity),
                    top_k=5,
                ))
                seen = {c.chunk_id for c in approved_chunks}
                for chunk in retrieval.chunks:
                    if chunk.chunk_id not in seen:
                        approved_chunks.append(chunk)
                        seen.add(chunk.chunk_id)

        # Yield context metadata before streaming
        yield {
            "type": "context",
            "chunks": [c.model_dump(mode="json") for c in approved_chunks],
            "plan": plan,
        }

        # Step 3: Build cloud LLM prompt
        system = self.system_prompt
        if approved_chunks:
            context_text = "\n\n".join(
                f"[Memory: {c.path}]\n{c.text}" for c in approved_chunks[:8]
            )
            system += f"\n\n## Learner Memory Context\n\n{context_text}"

        messages = []
        for msg in session.history[-(self.max_history):]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": request.message})

        # Step 4: Stream cloud LLM response
        full_response = ""
        try:
            for token in self.cloud_client.generate_stream(system, messages):
                full_response += token
                yield {"type": "token", "content": token}
        except Exception as e:
            full_response = f"Error: {e}"
            yield {"type": "token", "content": full_response}

        # Update session
        session.history.append(ChatMessage(role="user", content=request.message))
        session.history.append(ChatMessage(role="assistant", content=full_response))

        # Step 5: Admission (async-ish, yield result at end)
        admission = self.admission_evaluator.evaluate(
            request.message, full_response, request.user_id,
        )
        memories_created = []
        if admission and admission.get("store"):
            try:
                interaction = NormalizedInteraction(
                    source_system="chat",
                    event_type="conversation",
                    actor=request.user_id,
                    user_id=request.user_id,
                    payload={"user_message": request.message[:500]},
                    sensitivity=admission.get("sensitivity", "normal"),
                    provenance="chat_session",
                )
                decision = MemoryAdmissionDecision(
                    interaction_id=interaction.interaction_id,
                    store=True,
                    summary=admission.get("summary", ""),
                    memory_type=admission.get("memory_type", "episodic"),
                    sensitivity=admission.get("sensitivity", "normal"),
                    retention_class="short_term",
                    shareability="private",
                    confidence=0.7,
                    reason_for_decision=admission.get("reason", "Chat admission"),
                )
                write_path = memory_router.resolve_write_path(
                    user_id=request.user_id,
                    memory_type=decision.memory_type,
                    scope=decision.shareability,
                    topic=decision.memory_type,
                    memory_content=decision.summary,
                )
                memory_compactor._append_memory(
                    write_path,
                    request.user_id,
                    _decision_to_compacted(decision, interaction),
                )
                embedding_indexer.index_file(write_path)
                memories_created.append({
                    "summary": decision.summary,
                    "type": decision.memory_type,
                })
            except Exception:
                pass

        # Final metadata
        yield {
            "type": "done",
            "session_id": session.session_id,
            "memories_created": memories_created,
            "governance_log": governance_log,
        }


# Module-level singleton
chat_orchestrator = ChatOrchestrator()
