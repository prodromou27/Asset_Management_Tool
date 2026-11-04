# 12 | Deployment Runbook: AlmaLinux + Docker

Target: **single AlmaLinux OS 10.2 VM/server** (latest stable verified on 2 November 2026), Docker Engine + Docker Compose v2. No deployment has happened yet. This file is an implementation contract and operating runbook for the code agent. Before installing the host, reconfirm that 10.2 remains the latest stable general-availability release.

## 0. Preflight (operator must fill)

| Item | Required check |
|---|---|
| OS | Install/record AlmaLinux OS 10.2 GA, architecture (prefer x86_64 if infrastructure supports it), kernel, repos and fully patched state; recheck latest stable GA at deployment |
| Resources | Start sizing proposal: 8 vCPU, 24–32 GB RAM, SSD and separate capacity-monitored persistent volumes; adjust after load test |
| Disk | Reserve space for PostgreSQL, observations, attachments, export staging, logs and local backup cache; calculate growth |
| Connectivity | Internal HTTPS FQDN, DNS, trusted TLS cert, NTP, outbound routes to LibreNMS, Endpoint Central, Microsoft APIs, SMTP and approved lifecycle sources |
| Security | SELinux enforcing, firewalld, host updates, SSH hardening, backup network path, least-privilege operator access |
| Secrets | Approved secret storage/master key/rotation/backup process |
| Host state | Existing Docker/Podman installations, firewall rules, data volumes and other workloads checked for conflicts |

The OS release decision is **AlmaLinux OS 10.2 stable**, rather than 10.3 Beta or AlmaLinux Kitten. This release selection was current on 2 November 2026, so the operator must verify the current GA before installation and approve any updated version. Do not silently force an existing host upgrade or install an unverified container runtime. Use current Docker Engine installation instructions for the compatible RHEL 10/CentOS family, and prove the chosen Docker CE repository, required packages, SELinux and firewalld behavior on a fresh **AlmaLinux 10.2 staging host** first.

## 1. Docker prerequisite

Reference: https://docs.docker.com/engine/install/rhel/ and https://docs.docker.com/compose/install/linux/.
After operator approval and repo compatibility validation, expected package family is docker-ce, docker-ce-cli, containerd.io, docker-buildx-plugin, docker-compose-plugin.
The validated installation normally uses DNF and systemd; verify with:

~~~bash
cat /etc/os-release
uname -m
getenforce
firewall-cmd --state
docker version
docker compose version
sudo systemctl status docker
~~~

The above are **preflight checks**; do not assume Docker is already installed. Docker documents RHEL 10 installation, but states that derivative distributions are not tested or verified as supported platforms. Hence AlmaLinux 10.2 + Docker Engine **must pass compatibility testing** before production. Verify package/dependency availability, repository compatibility and GPG fingerprint before installing. Never disable SELinux or firewalld to 'make Docker work'. Membership in the docker group is effectively root-equivalent: reserve it for approved administrators.

## 2. Runtime containers (production)

| Service | Exposed | Persistent data | Health |
|---|---|---|---|
| nginx-proxy | 443/TCP externally; optional 80 for redirect/ACME if approved | TLS certificate/trust config | HTTPS readiness |
| web-static | internal | immutable frontend image | HTTP 200 |
| api (Django/ASGI or WSGI) | internal only | object storage adapter/optional media | GET /health/ready |
| worker (Celery) | internal only | none except shared secure artifacts interface | worker heartbeat |
| scheduler (Celery Beat) | internal only | scheduler DB | heartbeat |
| postgres | **not** exposed to host/network | named Docker volume or carefully managed labeled data mount | pg_isready |
| redis | **not** exposed | named volume only if queue durability policy requires it | ping |
| backup runner | internal/on-demand with restricted credential | write-only backup staging, off-host destination | last verified backup metric |

No Docker socket mount into web/API/worker. Pin image versions, nonroot user, minimal capabilities, read-only root filesystems where feasible, no privileged containers, resource/memory limits and stop grace periods. Compose production overrides must set restart and health checks. Use separate internal frontend/backend networks as necessary; do not publish database or Redis ports.

## 3. Filesystem and SELinux

Prefer named Docker volumes for PostgreSQL. For necessary bind mounts, confirm labeling and ownership according to current Docker Compose + SELinux behavior; do not blindly assume a :Z suffix works in every Compose service mount configuration. Keep SELinux Enforcing. Separate logs/data/backups, use file permissions and least-privilege service UIDs, avoid chmod 777.

## 4. Network matrix

| Source | Destination | Port/protocol | Function |
|---|---|---|---|
| User browser | ITAM proxy | TCP 443 | App/API |
| ITAM worker | LibreNMS | TCP 443 or approved custom HTTPS | Read-only inventory API |
| ITAM worker | Endpoint Central on-prem | HTTPS, documented example TCP 8383; verify actual | Inventory API |
| ITAM worker | Graph/Defender endpoints | TCP 443 | Inventory, security and license facts |
| ITAM worker | Approved vendor lifecycle sites | TCP 443 | Support milestones |
| ITAM worker | SMTP relay | TCP 587 STARTTLS or approved alternative | Notifications |
| ITAM to DNS | Approved resolvers | UDP/TCP 53 | Only approved DNS checks |
| api/worker | postgres | TCP 5432, internal Compose network only | DB |
| api/worker | Redis | TCP 6379, internal Compose network only | Queue |
| host | time/NTP | approved NTP | Accurate timestamps |

Firewall must allow only necessary flows and obey segmentation. No inbound Internet exposure is required unless separately authorized.

## 5. Required configuration

Provide .env.example with **non-secret** keys only, and typed validation at startup. Production secrets are injected from protected secret files or approved secret manager; never stored in repo, compose command line, image, admin API plaintext or logs.

| Setting family | Representative keys (names may be finalized by code) |
|---|---|
| App | ITAM_ENV, ITAM_PUBLIC_URL, ITAM_ALLOWED_HOSTS, ITAM_TIMEZONE, ITAM_LOG_LEVEL |
| DB | POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT; credentials by secret reference |
| Redis | REDIS_URL, separate auth secret if used |
| Django | DJANGO_SECRET_KEY, OIDC settings, CSRF trusted origins, secure cookie/TLS settings |
| Email | SMTP_HOST, SMTP_PORT, SMTP_SECURITY, SMTP_FROM; secret reference for username/password |
| Storage | STORAGE_DRIVER, STORAGE_BUCKET_OR_PATH; separate credentials secret |
| Backup | BACKUP_TARGET, BACKUP_SCHEDULE, BACKUP_RETENTION, BACKUP_ENCRYPTION_KEY_REF |
| Integrations | LIBRENMS_BASE_URL, ENDPOINT_CENTRAL_BASE_URL; tokens stored securely, tenant settings in admin DB |

App refuses to start production with DEBUG enabled, default secrets, untrusted TLS settings or absent required signing key. Settings UI tests nonsecret connections; never returns credential material.

## 6. Deployment sequence

1. Obtain host/network/backup approvals and confirm preflight and OS compatibility.
2. Install and pin Docker Engine/Compose through approved official repository.
3. Provision volumes, backup destination, TLS cert, DNS and secret references.
4. Build/pull pinned signed images; run container/image vulnerability checks.
5. Validate compose with **docker compose config**, inspect published ports, mounts, users and resources.
6. Start PostgreSQL/Redis; verify health; run schema migrations **once** as controlled job.
7. Start API/workers/scheduler/frontend/proxy; wait for health/ready.
8. Bootstrap **named** admin via protected one-off management command, enable MFA/SSO; no default password.
9. Configure sites, integration tokens, SMTP, backup schedule and notifications through admin UI/secret store.
10. Run sample read-only LibreNMS/Endpoint Central/Microsoft sync and verify reconciliation.
11. Run successful backup **and restore into isolated staging** before declaring production ready.
12. Document installed image digests, revision, API versions, admin owners and service endpoints.

Later approved updates follow build → staging migration/restore → backup snapshot → controlled deployment → smoke checks. Do not use blind 'latest' tags or uncontrolled compose down --volumes.

## 7. Commands the agent should implement and document

~~~bash
docker compose -f compose.yaml -f compose.prod.yaml config
docker compose -f compose.yaml -f compose.prod.yaml up -d
docker compose -f compose.yaml -f compose.prod.yaml ps
docker compose -f compose.yaml -f compose.prod.yaml logs --tail=100 api
docker compose -f compose.yaml -f compose.prod.yaml exec api python manage.py check --deploy
~~~

One-off migration and bootstrap commands must be provided in scripts/ with guarded and documented arguments. Never execute placeholder deployment commands on a real host without credentials/approval and a completed staging dry-run.

## 8. Rollback

Application rollback is to previously tested pinned images **only if database schema remains compatible**. For incompatible migrations, use planned recovery to a separate environment and a reviewed data migration/rollback path; do not assume container image rollback undoes a schema change. Preserve last verified backup and audit logs.

## 9. Staging installation (no FQDN or trusted certificate yet)

Purpose: evaluate the application and perform the AlmaLinux 10.2 + Docker compatibility check from sections 0–1 on a **staging** host. It is not a production deployment: the ADR-011 gates (verified backup/restore, SMTP), Task 022 and the open decisions still apply. Data on this host is disposable; integrations stay off (`ITAM_ALLOW_LIVE_INTEGRATIONS=false`) and no live source is configured.

Until DNS and the internal CA are ready, the host is reached by IP over HTTPS with a **temporary self-signed certificate** (90 days). Browsers will warn; compare the SHA-256 fingerprint printed by the certificate script before accepting it. HSTS is ignored for IP addresses and for certificates with errors, so this does not lock browsers out later.

The stack runs with the production settings and hardening of `compose.prod.yaml`; only `ITAM_ENV=staging` differs. Scripts live in `scripts/staging/`; each one refuses to overwrite existing secrets, certificates or `.env`.

| Step | Command (run from the repository root on the host) | Changes the host? |
|---|---|---|
| 1. Get the code | `git clone -b DEV <repo> /opt/itam` (deploy key with read-only access), or copy a `git archive` of the reviewed commit | Yes |
| 2. Preflight | `scripts/staging/preflight.sh` — OS, SELinux enforcing, firewalld, NTP, updates, resources, conflicting runtimes, port 443, reachability of Docker's repository and Docker Hub | No |
| 3. Docker | `sudo scripts/staging/install_docker.sh` prints the plan; `sudo scripts/staging/install_docker.sh --yes` installs from Docker's RHEL repository after checking the GPG fingerprint, enables the service and writes `/root/itam-docker-install-*.txt`. It stops if Podman/runc are installed or the repository does not resolve on 10.2 — record that as a compatibility result instead of forcing it | Yes |
| 4. Certificate | `sudo scripts/staging/make_selfsigned_cert.sh <ip> [short-name]` → `/etc/itam/tls/{fullchain,privkey}.pem`, root-owned, key mode 600, labelled `container_file_t` | Yes |
| 5. Configuration | `scripts/staging/make_env.sh <ip> [short-name]` → `.env` (mode 600) with generated PostgreSQL password, Django secret key and import encryption key; nothing is printed. Store a protected copy outside the host | Yes |
| 6. Deploy | `sudo ITAM_CONFIRM_STAGING=yes scripts/staging/deploy.sh` — labels the two bind mounts, validates Compose and refuses any published port other than `nginx-proxy:443`, builds, starts PostgreSQL/Redis, migrates once, starts the rest and waits for health, runs `check --deploy --fail-level WARNING`, smoke-tests through the proxy and writes `.deploy/staging-*.txt` | Yes |
| 7. Firewall | `sudo firewall-cmd --permanent --add-service=https && sudo firewall-cmd --reload` (443/tcp only; nothing else is published) | Yes |
| 8. First admin | `sudo scripts/bootstrap_admin.sh prod <username> "<Display Name>" [email]` — the password is prompted, never passed as an argument. MFA/SSO is not implemented yet (ASM-03, DEC-04/DEC-11), so use a long unique password and keep the host off public networks | Yes |
| 9. Verify from a workstation | Browse to `https://<ip>/`, accept the certificate after comparing the fingerprint, sign in. From another machine confirm only 443 answers (Docker-published ports can bypass firewalld zone rules, so test reachability rather than trusting the rule list) | No |

Day-2 commands use the same wrapper: `sudo scripts/compose.sh prod ps`, `… logs --tail=100 api`, `… restart nginx-proxy`. Update: `git pull`, then step 6 again. Do not run `down --volumes`; it deletes the database.

Replacing the temporary certificate when the FQDN and internal CA are ready:

1. Put the CA-issued `fullchain.pem` (server certificate followed by intermediates) and `privkey.pem` in `/etc/itam/tls/` (or a new directory and update `ITAM_TLS_CERT_DIR`), mode 600 for the key, then `sudo chcon -R -t container_file_t /etc/itam/tls`.
2. Put the FQDN **first** in `ITAM_ALLOWED_HOSTS` and add `https://<fqdn>` to `CSRF_TRUSTED_ORIGINS`; set `ITAM_PUBLIC_URL`. The api container healthcheck uses the first allowed host.
3. Re-run step 6 (or `sudo scripts/compose.sh prod up -d` followed by `… restart nginx-proxy`).

Known limits of this staging install: no backups (Task 019), no SMTP (Task 018), no load test (Task 022), images built on the host and not yet scanned or signed (section 6 step 4), and the Docker-on-AlmaLinux compatibility record still needs review before production.
