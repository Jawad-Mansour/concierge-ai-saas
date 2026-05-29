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

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from app import classifier as classifier_module  # noqa: E402
from app import deps as deps_module  # noqa: E402
from app import version  # noqa: E402
from app.deps import require_service_credential  # noqa: E402
from app.schemas import (  # noqa: E402
    IntentClass,
    PredictRequest,
    PredictResponse,
    UnauthenticatedResponse,
)


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
def _otel_capture() -> Iterator[tuple[TracerProvider, InMemorySpanExporter]]:
    """Per-test tracer provider + in-memory exporter.

    Shared by `make_app` (which instruments the app it builds) and
    `span_exporter` (which reads the captured spans), so a request's server span
    lands in the exporter the test asserts on. Both the instrumentation and the
    classifier tracer use this provider EXPLICITLY: OTel's global
    set_tracer_provider() is set-once per process, so relying on it makes span
    capture order-dependent — only the first test in a session would see spans.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Refresh the tracer cached in classifier.py. Vestigial today (classify()
    # enriches the server span via get_current_span), but kept in sync defensively.
    classifier_module._tracer = provider.get_tracer("modelserver.classifier")
    yield provider, exporter
    exporter.clear()


@pytest.fixture
def span_exporter(
    _otel_capture: tuple[TracerProvider, InMemorySpanExporter],
) -> InMemorySpanExporter:
    return _otel_capture[1]


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
def make_app(
    boot_credential: str,
    model_hash: str,
    _otel_capture: tuple[TracerProvider, InMemorySpanExporter],
) -> Callable[..., FastAPI]:
    """Build a FastAPI app with a stubbed backend and the auth dependency active.

    The app is instrumented (like production main.py) so `classify()` can enrich
    the active FastAPI server span via trace.get_current_span(); without it there
    is no recording span and the EvaluationSpan attrs would go nowhere (T026).
    """
    provider = _otel_capture[0]

    def _factory(
        backend: Any,
        *,
        unknown_threshold: float = 0.25,
        timeout_s: float = 0.200,
    ) -> FastAPI:
        app = FastAPI()
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
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
                {
                    **e,
                    "ctx": {
                        k: str(v) if isinstance(v, Exception) else v
                        for k, v in e["ctx"].items()
                    },
                }
                if "ctx" in e else e
                for e in exc.errors()
            ]
            return JSONResponse(status_code=422, content={"detail": errors})

        return app

    return _factory
