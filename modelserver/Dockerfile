# Owner: Charbel

# ── deps stage ───────────────────────────────────────────────
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV VIRTUAL_ENV=/opt/venv
RUN uv venv $VIRTUAL_ENV

WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --python $VIRTUAL_ENV/bin/python --no-cache \
    fastapi "uvicorn[standard]" hvac \
    onnxruntime "scikit-learn" numpy joblib

# ── runtime ──────────────────────────────────────────────────
FROM python:3.12-slim

COPY --from=deps /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/app

WORKDIR /app
COPY app/ ./app/

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
