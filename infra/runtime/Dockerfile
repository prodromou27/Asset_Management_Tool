# Build only the privilege-drop helper; retain Go symbols for vulnerability analysis.
FROM golang:1.27.3-alpine3.24@sha256:fa3d596898d9f126af7c01d14ee7597bab3f39cccf392ef36b69fe77cd681f18 AS gosu
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOSUMDB=sum.golang.org GOPROXY=https://proxy.golang.org
# Upstream gosu 1.20 commit; Go's checksum database authenticates module downloads.
RUN go install -trimpath github.com/tianon/gosu@29b939aa5bd4dc588af765b8248f6e39150d2565 \
    && cp /go/pkg/mod/github.com/tianon/gosu@*/LICENSE /go/bin/gosu.LICENSE \
    && /go/bin/gosu --version \
    && /go/bin/gosu nobody true

FROM postgres:16.15-alpine3.24@sha256:aa6cb33cf4c19c765cefcf48d96176258800870a9a1e930ad126200f9d825139 AS postgres
ENV GOSU_VERSION=1.20
COPY --from=gosu /go/bin/gosu /usr/local/bin/gosu
COPY --from=gosu /go/bin/gosu.LICENSE /usr/local/share/licenses/gosu/LICENSE
RUN gosu --version && test "$(gosu postgres id -u)" = "70"

# Preserve the official Redis 7 binaries and entrypoint, replacing only their OS.
FROM redis:7.4.12-alpine3.21@sha256:c5d34a98396a4775e223c74e929162c35c5a2182901ba26b50ade939941ce14b AS redis-source
FROM alpine:3.24.4@sha256:93b41ef40b1677fce8fcc64ff4af09daddfacf5040afde618bc46c1e2d1cc7d4 AS redis
RUN apk add --no-cache tzdata libgcc libstdc++ libssl3 libcrypto3 setpriv \
    && ln -s /bin/setpriv /usr/bin/setpriv \
    && addgroup -S -g 1000 redis \
    && adduser -S -G redis -u 999 redis \
    && mkdir /data && chown redis:redis /data
COPY --from=redis-source /usr/local/bin/redis-* /usr/local/bin/
COPY --from=redis-source /usr/local/bin/docker-entrypoint.sh /usr/local/bin/
RUN redis-server --version | grep 'v=7.4.12 ' \
    && redis-cli --version \
    && test "$(/usr/bin/setpriv --reuid redis --regid redis --clear-groups id -u)" = "999"
VOLUME /data
WORKDIR /data
ENTRYPOINT ["docker-entrypoint.sh"]
EXPOSE 6379
CMD ["redis-server"]
