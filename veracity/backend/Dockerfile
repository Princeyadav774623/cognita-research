# syntax=docker/dockerfile:1

# Two stages so the build toolchain does not ship. psycopg2 needs gcc and
# libpq-dev to compile; the runtime needs neither, and leaving them in adds
# ~200 MB and a compiler to anything that gets a shell in the container.
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

# ffmpeg is not optional: every ingest decodes through it, and without it the
# service starts happily and fails on the first upload.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MEDIA_ROOT=/var/lib/veracity/media \
    HF_HOME=/opt/models

# Downloaded at build time rather than on the first request. fastembed fetches
# ~130 MB on first use; leaving that to runtime means the first upload after
# every deploy pays for it, and a container with no outbound access at runtime
# never works at all.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

# Non-root. The process only ever writes to MEDIA_ROOT, so nothing else needs
# to be writable by it.
RUN useradd --system --create-home --uid 10001 veracity \
    && mkdir -p /var/lib/veracity/media \
    && chown -R veracity:veracity /var/lib/veracity /opt/models

WORKDIR /app
COPY --chown=veracity:veracity . .
USER veracity

EXPOSE 8080

# Checks the database and tenant isolation, not just that the process is
# listening — a service that answers while its policies are inert is not healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8080/health | grep -q '"status": *"ok"' || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
