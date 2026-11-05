#!/bin/sh
set -eu
# Bind-mount ownership varies by operator host; install strict local copies.
install -d -o backup -g backup -m 700 /home/backup/.ssh
install -o backup -g backup -m 600 /run/fixture-keys/authorized_keys /home/backup/.ssh/authorized_keys
install -o root -g root -m 600 /run/fixture-keys/host_key /etc/ssh/fixture_host_key
exec /usr/sbin/sshd -D -e
