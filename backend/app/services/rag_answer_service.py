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
    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        tenant_id: str | None = None,
    ) -> str:
        """Generate a grounded answer from retrieved RAG context."""


class RagAnswerCostTracker(Protocol):
    def record_llm_call(
        self,
        *,
        tenant_id: str | None,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        """Record one billable RAG answer synthesis call."""


class ExtractiveRagAnswerGenerator:
    """Local fallback when hosted LLM answer synthesis is not configured."""

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        tenant_id: str | None = None,
    ) -> str:
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
        cost_tracker: RagAnswerCostTracker | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        self.timeout_seconds = timeout_seconds
        self.post_json = post_json or self._post_json
        self.cost_tracker = cost_tracker
        if not self.api_key:
            raise RagAnswerConfigurationError("ANTHROPIC_API_KEY is not configured")

    def generate(
        self,
        *,
        question: str,
        contexts: list[str],
        tenant_id: str | None = None,
    ) -> str:
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
        self._record_cost(tenant_id=tenant_id, response=response)
        try:
            return str(response["content"][0]["text"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RagAnswerRequestError("invalid Anthropic RAG answer response") from exc

    def _record_cost(self, *, tenant_id: str | None, response: dict) -> None:
        if self.cost_tracker is None:
            return
        usage = response.get("usage") or {}
        self.cost_tracker.record_llm_call(
            tenant_id=tenant_id,
            provider="anthropic",
            model=self.model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

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
