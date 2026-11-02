# 10 | SMTP Service and Notification Engine

Outgoing SMTP is mandatory for V1. The application sends EOL/EOS, domain/certificate expiry, data-quality and operational alerts. Sending must run asynchronously; email server failure must not cause asset writes to fail.

## Configurable settings

| Field | Required behavior |
|---|---|
| SMTP enabled | Global enabled/disabled control; when disabled preserve queued messages with defined expiry policy |
| Host/port | Approved FQDN/IP, port 587 STARTTLS preferred; 465 implicit TLS or approved internal relay according to policy |
| Transport | STARTTLS mandatory for credentialed submission; implicit TLS option; never silently downgrade TLS |
| Authentication | Username/password or documented OAuth-capable transport where available; credentials only in secret store |
| From | Verified sender address, display name, Reply-To, optional support contact |
| CA trust | Validate server certificate and hostname; custom internal CA only through approved mounted trust bundle |
| Connection | Timeout, connection pool limit, throttling, retry policy, duplicate suppression |
| Recipient policy | Per event type/group/site/owner, escalation recipients and optional daily digest |
| Templates | Subject + sanitized plaintext and HTML bodies; preview and test-send |
| Audit | Message ID, template version, recipient count, status, attempts, last error, queued/sent timestamps; never log email bodies with secrets |

Admin UI: Administration → SMTP & Notifications. Buttons: Test connection (does not send), Send test email (to current authorized admin), Save, Disable, View delivery queue. Show redacted credential and successful test timestamp. Require admin permission to change configuration. Test send must not email arbitrary unauthorised addresses.

## Events and schedules

| Trigger | Default policy |
|---|---|
| Hardware/OS/firmware verified EOL thresholds | 365, 180, 90, 30, 7 days; no unverified auto-alert claiming EOS |
| TLS certificate expiry | 90, 60, 30, 14, 7 days and expired |
| Domain renewal | 90, 60, 30, 14, 7 days when verified; Unknown prompts data-quality review |
| Daily digest | One per recipient/site policy with consolidated findings |
| Integration failures | Admin alert on repeated failures or prolonged stale sync |
| Backup failures | Administrator alert on last-good-backup age, failed upload or failed verification |
| Unknown/duplicate device findings | Optional summary, never one message per network scan observation |

Dedup key = event type + target ID + milestone date + threshold + recipient policy version. Re-announcement only on meaningful source change or expiration of a suppressed alert. Queue outbound messages in database outbox, use Celery worker with exponential backoff/jitter, bounded retries, dead-letter visible to admin. Rendering must escape user-controlled values and not embed secret content.

## SMTP connection examples (configuration templates, not real credentials)

Internal authenticated relay:

~~~text
Host: smtp.internal.example
Port: 587
Security: STARTTLS required
Authentication: enabled
Username/password: stored as secret references
From: itam-alerts@example.invalid
~~~

Approved anonymous on-prem relay: credentialless only if protected by source IP/TLS and reviewed by administrators; no automatic fallback to unauthenticated external port 25.

## Implementation tests

Use Mailpit or equivalent capture service only in dev/test, not a public production relay. Test accepted, auth fail, TLS/CA fail, timeout, 4xx retry, 5xx terminal failure, bounced recipient, disabled notifications, digest dedup, time-zone display and injection-safe templates.

## Production gate

Admin saves and tests approved SMTP configuration; one test email reaches a nominated recipient; one queued EOL event is delivered once; a simulated outage shows a retry and visible operational alert.
