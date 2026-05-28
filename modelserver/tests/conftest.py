# Owner: Jana
"""Shared test fixtures.

Every test installs:
  - a stubbed `InferenceBackend` (no real artifact required),
  - a known boot credential via env-var so `deps.require_service_credential`
    can be exercised end-to-end,
  - a known `version.MODEL_HASH` so PredictResponse passes 12-hex validation,
  - an in-memory OTel span exporter so US3 tests can assert attributes.
"""

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

os.environ.setdefault("MODELSERVER_SERVICE_CREDENTIAL", "test-token")
os.environ.setdefault("INFERENCE_TIMEOUT_MS", "200")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from app import classifier as classifier_module  # noqa: E402
from app import deps as deps_module  # noqa: E402
from app import version  # noqa: E402
from app.deps import require_service_credential  # noqa: E402
from app.schemas import IntentClass, PredictRequest, PredictResponse, UnauthenticatedResponse  # noqa: E402


class StubBackend:
    """Returns canned `(class, confidence)` tuples keyed by message text."""

    def __init__(self, table: dict[str, tuple[IntentClass, float]]):
        self._table = table
        self.last_message: str | None = None

    def predict(self, message: str) -> tuple[IntentClass, float]:
        self.last_message = message
        if message in self._table:
            return self._table[message]
        return ("UNKNOWN", 0.5)


@pytest.fixture
def span_exporter() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    # Refresh the tracer cached in classifier.py
    classifier_module._tracer = trace.get_tracer("modelserver.classifier")
    yield exporter
    exporter.clear()


@pytest.fixture
def boot_credential() -> Iterator[str]:
    token = "test-token"
    deps_module._BOOT_CREDENTIAL = token
    yield token


@pytest.fixture
def model_hash() -> Iterator[str]:
    version.set_model_hash("abcdef012345")
    yield "abcdef012345"


@pytest.fixture
def make_app(boot_credential: str, model_hash: str) -> Callable[..., FastAPI]:
    """Build a FastAPI app with a stubbed backend and the auth dependency active."""
    def _factory(
        backend: Any,
        *,
        unknown_threshold: float = 0.25,
        timeout_s: float = 0.200,
    ) -> FastAPI:
        app = FastAPI()
        app.state.backend = backend
        app.state.unknown_threshold = unknown_threshold
        app.state.inference_timeout_s = timeout_s

        @app.post(
            "/predict",
            response_model=PredictResponse,
            dependencies=[Depends(require_service_credential)],
        )
        async def predict(request: Request, body: PredictRequest) -> PredictResponse:
            return await classifier_module.classify(
                backend=request.app.state.backend,
                message=body.message,
                tenant_id=body.tenant_id,
                unknown_threshold=request.app.state.unknown_threshold,
                timeout_s=request.app.state.inference_timeout_s,
            )

        @app.exception_handler(HTTPException)
        async def _401(_: Request, exc: HTTPException) -> JSONResponse:
            if exc.status_code == 401:
                return JSONResponse(status_code=401, content=UnauthenticatedResponse().model_dump())
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        @app.exception_handler(RequestValidationError)
        async def _422(_: Request, exc: RequestValidationError) -> JSONResponse:
            errors = [
                {**e, "ctx": {k: str(v) if isinstance(v, Exception) else v for k, v in e["ctx"].items()}}
                if "ctx" in e else e
                for e in exc.errors()
            ]
            return JSONResponse(status_code=422, content={"detail": errors})

        return app

    return _factory
