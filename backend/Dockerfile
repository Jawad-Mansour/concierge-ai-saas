# Owner: Charbel

# ── deps stage ───────────────────────────────────────────────
FROM python:3.12-slim AS deps

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
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --python $VIRTUAL_ENV/bin/python

# ── runtime ──────────────────────────────────────────────────
FROM python:3.12-slim

COPY --from=deps /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/app

WORKDIR /app
COPY backend/app/ ./app/
COPY backend/alembic.ini ./
COPY backend/alembic/ ./alembic/
COPY infra/postgres/migrations /infra/postgres/migrations
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
