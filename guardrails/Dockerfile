# Owner: Charbel

# ── deps stage ───────────────────────────────────────────────
FROM python:3.12-slim AS deps

# nemoguardrails -> annoy requires g++ to build from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential g++ && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV VIRTUAL_ENV=/opt/venv
RUN uv venv $VIRTUAL_ENV

WORKDIR /app
COPY pyproject.toml ./
# NOTE: nemoguardrails may pull torch/transformers transitively.
# If the image exceeds expected size, Jana should audit with:
#   docker run --rm <image> pip show torch
RUN uv pip install --python $VIRTUAL_ENV/bin/python --no-cache \
    fastapi "uvicorn[standard]" hvac nemoguardrails

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
