FROM postgres:16.15-trixie@sha256:f9a7b9ebf6f56201f949db745e47bc423c0f0f8294bafe991cc10bf74b029657 AS pgtools

FROM python:3.12.16-slim-trixie@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN groupadd --system itam && useradd --system --gid itam --create-home itam

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.production

RUN mkdir -p /app/staticfiles && chown -R itam:itam /app

USER itam

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]

# Only the opt-in backup worker receives database tools and repository credentials.
FROM base AS backup-runner
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    restic openssh-client libpq5 liblz4-1 libzstd1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=pgtools /usr/lib/postgresql/16/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=pgtools /usr/lib/postgresql/16/bin/pg_restore /usr/local/bin/pg_restore
USER itam
RUN pg_dump --version && pg_restore --version && restic version

FROM base AS production
