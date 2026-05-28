# Owner: Jana
"""Shared test fixtures.

The full app boot path runs Vault fetch and OTel init. We bypass Vault via the
env-override and re-init OTel against an in-memory exporter so US6's span
tests have a real backing exporter to assert against.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

os.environ.setdefault("GUARDRAILS_SERVICE_CREDENTIAL", "test-token")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from app import deps as deps_module  # noqa: E402
from app import validators as validators_module  # noqa: E402
from app.deps import require_service_credential  # noqa: E402
from app.schemas import (  # noqa: E402
    EvaluationRequestInput,
    EvaluationRequestOutput,
    UnauthenticatedResponse,
)


@pytest.fixture
def span_exporter() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    validators_module._tracer = trace.get_tracer("guardrails.validators")
    yield exporter
    exporter.clear()


@pytest.fixture
def boot_credential() -> Iterator[str]:
    token = "test-token"
    deps_module._BOOT_CREDENTIAL = token
    yield token


@pytest.fixture
def app(boot_credential: str) -> FastAPI:
    fastapi_app = FastAPI()

    @fastapi_app.post(
        "/check/input",
        dependencies=[Depends(require_service_credential)],
    )
    async def check_input(req: EvaluationRequestInput) -> Any:
        return (
            await validators_module.evaluate(
                endpoint="input",
                content=req.message,
                tenant_id=req.tenant_id,
                tenant_config=req.tenant_config,
            )
        ).model_dump()

    @fastapi_app.post(
        "/check/output",
        dependencies=[Depends(require_service_credential)],
    )
    async def check_output(req: EvaluationRequestOutput) -> Any:
        return (
            await validators_module.evaluate(
                endpoint="output",
                content=req.llm_response,
                tenant_id=req.tenant_id,
                tenant_config=req.tenant_config,
            )
        ).model_dump()

    @fastapi_app.exception_handler(HTTPException)
    async def _401(_: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 401:
            return JSONResponse(
                status_code=401, content=UnauthenticatedResponse().model_dump()
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @fastapi_app.exception_handler(RequestValidationError)
    async def _422(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {**e, "ctx": {k: str(v) if isinstance(v, Exception) else v for k, v in e["ctx"].items()}}
            if "ctx" in e else e
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    return fastapi_app
