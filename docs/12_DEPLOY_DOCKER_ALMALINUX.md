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
| ITAM worker (daily) and api ("Check now") | Approved TLS endpoints only (Task 017) | The approved port, usually TCP 443 | Read the presented certificate (TLS handshake only) |
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

## 9. Simple installation (HTTP first, HTTPS later)

Owner decision (2026-11-04, ASM-51): the first install runs on **plain HTTP, port 80**, reached by the server IP; an administrator adds a certificate later with one command. HTTP sends passwords unencrypted, so use it only on a trusted internal network. `ITAM_ENV=production` refuses HTTP; go-live still needs the ADR-011 gates (backups Task 019, SMTP Task 018, load test Task 022) and DEC-04/DEC-11.

**Install** (as a user with sudo, on AlmaLinux 10.x):

~~~bash
sudo dnf -y install git
sudo git clone -b DEV https://github.com/prodromou27/Asset_Management_Tool.git /opt/itam
cd /opt/itam
sudo bash scripts/install.sh
~~~

`install.sh` installs Docker from Docker's official repository if missing (signing key fingerprint checked), writes `.env` with generated secrets (mode 600, never printed), builds, migrates, starts, opens HTTP in firewalld, checks health and offers to create the first administrator. Open `http://<server-ip>/`. SELinux and firewalld stay enabled. Keep a safe copy of `/opt/itam/.env`.

**Update:** `cd /opt/itam && sudo git pull && sudo bash scripts/install.sh`

**Enable HTTPS later:**

~~~bash
sudo bash scripts/enable_https.sh /path/fullchain.pem /path/privkey.pem itam.example.local
# or a temporary self-signed certificate:
sudo bash scripts/enable_https.sh --self-signed [hostname]
~~~

It checks that the key matches the certificate and that it has not expired, stores them in `/etc/itam/tls`, switches `.env` to HTTPS (previous copy kept as `.env.before-https`), opens HTTPS in firewalld and restarts. Port 80 then redirects to HTTPS. The hostname needs a DNS record pointing to the server.

**Everyday commands** (in `/opt/itam`): `sudo bash scripts/compose.sh prod ps`, `… logs --tail=100 api`, `sudo bash scripts/bootstrap_admin.sh prod <username> "<Full Name>" [email]`. Never run `down --volumes`: it deletes the database.

**Access by another name:** add it to `ITAM_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `.env`, then run `install.sh` again.
