"""Cloud LLM clients — Anthropic (Claude) and OpenAI.

Provides the intelligence layer for chat while the local Ollama
handles governance and memory admission.
"""

import os
from typing import Protocol, Generator


class CloudLLMClient(Protocol):
    """Protocol for cloud LLM backends."""

    def generate(self, system: str, messages: list[dict]) -> str: ...
    def generate_stream(self, system: str, messages: list[dict]) -> Generator[str, None, None]: ...


class AnthropicClient:
    """Claude API client."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def generate(self, system: str, messages: list[dict]) -> str:
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    def generate_stream(self, system: str, messages: list[dict]) -> Generator[str, None, None]:
        client = self._get_client()
        with client.messages.stream(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text


class OpenAIClient:
    """OpenAI API client."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def generate(self, system: str, messages: list[dict]) -> str:
        client = self._get_client()
        msgs = [{"role": "system", "content": system}] + messages
        response = client.chat.completions.create(
            model=self.model,
            messages=msgs,
        )
        return response.choices[0].message.content

    def generate_stream(self, system: str, messages: list[dict]) -> Generator[str, None, None]:
        client = self._get_client()
        msgs = [{"role": "system", "content": system}] + messages
        stream = client.chat.completions.create(
            model=self.model,
            messages=msgs,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class MockCloudClient:
    """Mock client for testing without API keys."""

    def generate(self, system: str, messages: list[dict]) -> str:
        last_msg = messages[-1]["content"] if messages else ""
        return (
            f"[Mock cloud LLM — no API key configured]\n\n"
            f"I received your message and {len(messages)} conversation turns. "
            f"To enable real responses, set ANTHROPIC_API_KEY or OPENAI_API_KEY.\n\n"
            f"Your question: {last_msg[:200]}"
        )

    def generate_stream(self, system: str, messages: list[dict]) -> Generator[str, None, None]:
        yield self.generate(system, messages)


def get_cloud_client(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> CloudLLMClient:
    """Get the appropriate cloud LLM client.

    Auto-detects provider from environment if not specified.
    Falls back to mock if no API keys found.
    """
    provider = provider or os.environ.get("CLOUD_LLM_PROVIDER", "auto")

    if provider == "anthropic":
        return AnthropicClient(api_key=api_key, model=model or "claude-sonnet-4-20250514")
    if provider == "openai":
        return OpenAIClient(api_key=api_key, model=model or "gpt-4o")

    # Auto-detect from environment
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient(model=model or "claude-sonnet-4-20250514")
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai  # noqa: F401
            return OpenAIClient(model=model or "gpt-4o")
        except ImportError:
            pass

    return MockCloudClient()
