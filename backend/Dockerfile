# Multi-stage build for Askit RAG.
# Builder installs deps via uv; runtime copies the venv + app source only.
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Build deps for sentence-transformers / numpy wheels.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Install prod deps only (no dev group) into a venv at /app/.venv.
RUN uv sync --frozen --no-dev

# --- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# /models holds the on-device reranker cache (mount a volume here so the
# sentence-transformers download survives container restarts). Embeddings are
# via the Fireworks API now, so no large local embedding cache.
ENV PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/models/huggingface \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY scripts ./scripts

VOLUME ["/models"]
EXPOSE 8000

# Liveness probe — pure stdlib, no curl in slim.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
