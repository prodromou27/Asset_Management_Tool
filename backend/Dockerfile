FROM python:3.12.16-alpine3.24@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7 AS sqlite-build
RUN apk add --no-cache alpine-sdk
WORKDIR /build/sqlite
ADD --checksum=sha256:926ef8d3eab93fbf6e06011901273eec076b25594a4e1cdadd50c987f4f6d64e https://www.sqlite.org/2026/sqlite-autoconf-3540100.tar.gz ./sqlite-autoconf-3540100.tar.gz
COPY runtime/sqlite/APKBUILD ./APKBUILD
ENV REPODEST=/packages
RUN abuild-keygen -a -n -i
RUN --network=none abuild -F -d \
    && mkdir /out \
    && find /packages -name 'sqlite-libs-3.54.1-r0.apk' -exec cp '{}' /out/ \; \
    && test -f /out/sqlite-libs-3.54.1-r0.apk

FROM golang:1.27.3-alpine3.24@sha256:fa3d596898d9f126af7c01d14ee7597bab3f39cccf392ef36b69fe77cd681f18 AS restic-build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2 GOSUMDB=sum.golang.org GOPROXY=https://proxy.golang.org
RUN go mod download -json github.com/restic/restic@v0.18.1
RUN cd /go/pkg/mod/github.com/restic/restic@v0.18.1 && go mod download && go mod verify
RUN --network=none GOPROXY=off go install -p 2 -trimpath -ldflags '-X main.version=0.18.1' github.com/restic/restic/cmd/restic@v0.18.1 \
    && cp /go/pkg/mod/github.com/restic/restic@v0.18.1/LICENSE /go/bin/restic.LICENSE \
    && go version -m /go/bin/restic > /go/bin/restic-buildinfo.txt

FROM python:3.12.16-alpine3.24@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7 AS base

RUN apk add --no-cache libstdc++
COPY --from=sqlite-build /out/sqlite-libs-3.54.1-r0.apk /tmp/sqlite-libs.apk
RUN --network=none apk add --no-network --allow-untrusted /tmp/sqlite-libs.apk \
    && rm /tmp/sqlite-libs.apk
COPY runtime/sqlite/source.json /usr/local/share/itam/sqlite-source.json
COPY runtime/sqlite/APKBUILD /usr/local/share/itam/sqlite-APKBUILD

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN addgroup -S -g 10001 itam && adduser -S -D -u 10001 -G itam -h /home/itam itam

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
RUN apk add --no-cache openssh-client-default postgresql16-client
COPY --from=restic-build /go/bin/restic /usr/local/bin/restic
COPY --from=restic-build /go/bin/restic.LICENSE /usr/local/share/licenses/restic/LICENSE
COPY --from=restic-build /go/bin/restic-buildinfo.txt /usr/local/share/itam/restic-buildinfo.txt
USER itam
RUN --network=none pg_dump --version && pg_restore --version && restic version

# CI-only target: exercise the existing PostgreSQL/Redis/SFTP suite on this libc.
FROM backup-runner AS runtime-tests
USER root
RUN uv sync --frozen --group dev --no-build
USER itam

FROM base AS production
