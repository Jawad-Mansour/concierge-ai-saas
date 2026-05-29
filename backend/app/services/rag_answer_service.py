# Owner: Ali
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class RagAnswerError(ValueError):
    code = "rag_answer_error"


class RagAnswerConfigurationError(RagAnswerError):
    code = "rag_answer_configuration_error"


class RagAnswerRequestError(RagAnswerError):
    code = "rag_answer_request_error"


class RagAnswerGenerator(Protocol):
    def generate(self, *, question: str, contexts: list[str]) -> str:
        """Generate a grounded answer from retrieved RAG context."""


class ExtractiveRagAnswerGenerator:
    """Local fallback when hosted LLM answer synthesis is not configured."""

    def generate(self, *, question: str, contexts: list[str]) -> str:
        return contexts[0] if contexts else "I do not have enough tenant context to answer that."


class AnthropicRagAnswerGenerator:
    """LLM answer synthesis over retrieved tenant-scoped chunks."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 20,
        post_json=None,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        self.timeout_seconds = timeout_seconds
        self.post_json = post_json or self._post_json
        if not self.api_key:
            raise RagAnswerConfigurationError("ANTHROPIC_API_KEY is not configured")

    def generate(self, *, question: str, contexts: list[str]) -> str:
        if not contexts:
            return "I do not have enough tenant context to answer that."
        response = self.post_json(
            self.API_URL,
            {
                "model": self.model,
                "max_tokens": 350,
                "temperature": 0,
                "system": (
                    "Answer only from the provided tenant context. "
                    "If the context is insufficient, say you do not have enough information."
                ),
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": question,
                                "contexts": contexts,
                            },
                            sort_keys=True,
                        ),
                    }
                ],
            },
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            self.timeout_seconds,
        )
        try:
            return str(response["content"][0]["text"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RagAnswerRequestError("invalid Anthropic RAG answer response") from exc

    def _post_json(
        self,
        url: str,
        payload: dict,
        headers: dict,
        timeout_seconds: int,
    ) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RagAnswerRequestError("Anthropic RAG answer request failed") from exc
