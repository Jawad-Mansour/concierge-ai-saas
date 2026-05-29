# Owner: Ali
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class EmbeddingProviderError(ValueError):
    code = "embedding_provider_error"


class EmbeddingConfigurationError(EmbeddingProviderError):
    code = "embedding_configuration_error"


class EmbeddingRequestError(EmbeddingProviderError):
    code = "embedding_request_error"


class EmbeddingProvider(Protocol):
    def embed_text(self, text: str, *, tenant_id: str | None = None) -> list[float]:
        """Return one embedding vector for the supplied text."""


class EmbeddingCostTracker(Protocol):
    def record_embedding_call(
        self,
        *,
        tenant_id: str | None,
        provider: str,
        model: str,
        input_count: int,
    ) -> None:
        """Record one hosted embedding request for tenant cost attribution."""


class HashingEmbeddingProvider:
    """Deterministic local embedding fallback for tests and offline demos."""

    def __init__(self, *, dimensions: int = 64) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed_text(self, text: str, *, tenant_id: str | None = None) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = sum(value * value for value in vector) ** 0.5
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class VoyageEmbeddingProvider:
    """Hosted embedding provider recommended by Anthropic for semantic retrieval."""

    API_URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 20,
        post_json=None,
        cost_tracker: EmbeddingCostTracker | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("VOYAGE_API_KEY")
        self.model = model or os.getenv("EMBEDDINGS_MODEL", "voyage-3.5")
        self.timeout_seconds = timeout_seconds
        self.post_json = post_json or self._post_json
        self.cost_tracker = cost_tracker
        if not self.api_key:
            raise EmbeddingConfigurationError("VOYAGE_API_KEY is not configured")

    def embed_text(self, text: str, *, tenant_id: str | None = None) -> list[float]:
        response = self.post_json(
            self.API_URL,
            {"model": self.model, "input": [text]},
            {
                "authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            self.timeout_seconds,
        )
        if self.cost_tracker is not None:
            self.cost_tracker.record_embedding_call(
                tenant_id=tenant_id,
                provider="voyage",
                model=self.model,
                input_count=1,
            )
        try:
            embedding = response["data"][0]["embedding"]
            return [float(value) for value in embedding]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise EmbeddingRequestError("invalid embedding provider response") from exc

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
            raise EmbeddingRequestError("embedding provider request failed") from exc
