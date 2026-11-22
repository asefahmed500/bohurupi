# Bohurupi API — Python 3.12 + uv, CPU speech stack included.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# System deps for soundfile (libsndfile) + ctranslate2 runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
# NOTE: the 'fx' extra (pedalboard + audioseal + torch) is intentionally not
# installed — it adds ~2 GB. Without it, Voice Studio effects and audioseal
# watermarking degrade gracefully (metadata mark only). Add --extra fx here
# for the full watermark/effects profile.
RUN uv sync --frozen --no-install-project --extra audio

COPY app ./app
COPY alembic.ini ./
COPY db/migrations ./db/migrations
RUN uv sync --frozen --extra audio

FROM python:3.12-slim-bookworm

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m bohurupi

WORKDIR /app
COPY --from=builder /app /app
# /data/storage must exist with the right owner BEFORE the first named-volume
# mount, or Docker creates it root-owned and the non-root user cannot write.
RUN mkdir -p /data/storage && chown -R bohurupi:bohurupi /app /data/storage

USER bohurupi
EXPOSE 8000

# Apply migrations, then serve
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
