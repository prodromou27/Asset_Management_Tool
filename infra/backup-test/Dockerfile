# Synthetic CI/development SFTP destination only; never used by production Compose.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/sh itamfixture \
    && passwd -d itamfixture && mkdir -p /run/sshd /repository \
    && chown itamfixture:itamfixture /repository
COPY sshd_config /etc/ssh/sshd_config
COPY start.sh /usr/local/bin/start-fixture
CMD ["sh", "/usr/local/bin/start-fixture"]
