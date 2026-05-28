# Owner: Jana
"""FastAPI app entrypoint.

Boot sequence (data-model.md "Boot-time state transitions"):
  1. parse + validate model_card.md
  2. compute artifact SHA-256, compare to card
  3. instantiate InferenceBackend, load artifact
  4. fetch service credential from Vault
  5. init OTel
  6. (warm-up handled implicitly by the first inbound request)
The listener does NOT open until 1–5 return successfully.
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    _OTEL_AVAILABLE = True
except (ModuleNotFoundError, ImportError):
    _OTEL_AVAILABLE = False

from . import classifier, model_loader, telemetry
from .deps import fetch_vault_credential, require_service_credential
from .schemas import PredictRequest, PredictResponse, UnauthenticatedResponse

INFERENCE_TIMEOUT_MS = float(os.environ.get("INFERENCE_TIMEOUT_MS", "200"))


def create_app() -> FastAPI:
    loaded = model_loader.load()
    fetch_vault_credential()
    telemetry.init(service_name="modelserver")

    app = FastAPI(title="Concierge modelserver")
    if _OTEL_AVAILABLE:
        FastAPIInstrumentor.instrument_app(app)

    app.state.backend = loaded.backend
    app.state.unknown_threshold = loaded.unknown_threshold
    app.state.inference_timeout_s = INFERENCE_TIMEOUT_MS / 1000.0

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model_hash": loaded.model_hash_short}

    @app.post(
        "/predict",
        response_model=PredictResponse,
        responses={
            401: {"model": UnauthenticatedResponse},
        },
        dependencies=[Depends(require_service_credential)],
    )
    async def predict(request: Request, body: PredictRequest) -> PredictResponse:
        return await classifier.classify(
            backend=request.app.state.backend,
            message=body.message,
            tenant_id=body.tenant_id,
            unknown_threshold=request.app.state.unknown_threshold,
            timeout_s=request.app.state.inference_timeout_s,
        )

    @app.exception_handler(HTTPException)
    async def _401_opaque(_: Request, exc: HTTPException) -> JSONResponse:
        # Principle V / FR-004 — every 401 carries the same byte-identical body.
        if exc.status_code == 401:
            return JSONResponse(
                status_code=401,
                content=UnauthenticatedResponse().model_dump(),
            )
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


app = create_app()
