# Synthetic CI/development SFTP destination only; never used by production Compose.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/sh backup \
    && passwd -d backup && mkdir -p /run/sshd /repository \
    && chown backup:backup /repository
COPY sshd_config /etc/ssh/sshd_config
CMD ["/usr/sbin/sshd", "-D", "-e"]
