FROM python:3.12.16-alpine3.24@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7 AS base

RUN apk add --no-cache libstdc++

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN addgroup -S -g 999 itam && adduser -S -D -u 999 -G itam -h /home/itam itam

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-build

COPY . .
RUN uv sync --frozen --no-dev --no-build

ENV PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.production

RUN mkdir -p /app/staticfiles && chown -R itam:itam /app

USER itam

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]

# Only the opt-in backup worker receives database tools and repository credentials.
FROM base AS backup-runner
USER root
RUN apk add --no-cache restic openssh-client-default postgresql16-client
USER itam
RUN pg_dump --version && pg_restore --version && restic version

# CI-only target: exercise the existing PostgreSQL/Redis/SFTP suite on this libc.
FROM backup-runner AS runtime-tests
USER root
RUN uv sync --frozen --group dev --no-build
USER itam

FROM base AS production
