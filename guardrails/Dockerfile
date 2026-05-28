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
COPY config/ ./config/

# Principle II — compute the rails-config content hash at build time and pin it
# into app/version.py. The boot path recomputes from disk and refuses to start
# on mismatch (see app/main.py). The < 500 MB image budget is enforced by the
# CI image-size job; this Dockerfile copies neither training tools nor torch.
RUN python -c "import hashlib, pathlib, sys; \
    configs = sorted(pathlib.Path('config').glob('*.yaml')); \
    h = hashlib.sha256(); \
    [h.update(p.name.encode()) or h.update(b':') or h.update(p.read_bytes()) or h.update(b'\\n') for p in configs]; \
    digest = h.hexdigest(); \
    pathlib.Path('app/version.py').write_text(\
        '# Generated at image build — do not edit\\n' \
        'RAILS_CONFIG_HASH = ' + repr(digest) + '\\n' \
        'RAILS_VERSION = ' + repr(digest[:12]) + '\\n')"

EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]
