# Owner: Charbel

# ── deps stage ───────────────────────────────────────────────
FROM python:3.12-slim AS deps

# nemoguardrails -> annoy requires g++ to build from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential g++ && rm -rf /var/lib/apt/lists/*

# Install uv via pip — avoids ghcr.io which is blocked on some networks
RUN pip install uv==0.5.4 --no-cache-dir

ENV VIRTUAL_ENV=/opt/venv \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN uv venv $VIRTUAL_ENV

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --python $VIRTUAL_ENV/bin/python

# ── runtime ──────────────────────────────────────────────────
FROM python:3.12-slim

COPY --from=deps /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/app

WORKDIR /app
COPY app/ ./app/

EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
