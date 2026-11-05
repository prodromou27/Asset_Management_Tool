#!/bin/sh
set -eu
# Bind-mount ownership varies by operator host; install strict local copies.
install -d -o itamfixture -g itamfixture -m 700 /home/itamfixture/.ssh
install -o itamfixture -g itamfixture -m 600 /run/fixture-keys/authorized_keys /home/itamfixture/.ssh/authorized_keys
install -o root -g root -m 600 /run/fixture-keys/host_key /etc/ssh/fixture_host_key
exec /usr/sbin/sshd -D -e
