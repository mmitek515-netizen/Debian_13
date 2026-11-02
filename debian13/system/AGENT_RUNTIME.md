# Debian 13 — background agents and privilege policy

## Current state
The four API profiles (Alex, Aria, Astyria, Aurelius) are **not** background workers.
The existing `debian13-system` Compose service uses `restart: unless-stopped`,
which restarts the API process, not four autonomous agents. Do not label a
profile as running without a verified worker heartbeat.

## Background runtime prerequisites
1. Configure a real model endpoint, model name, and credentials via protected
   environment variables / Codespaces secrets. Never commit keys.
2. Implement a persistent task queue with per-agent leases, heartbeats,
   idempotency keys, retry budgets, and explicit cancellation.
3. Implement separate workers with scoped project permissions, durable task
   logs, and a read-only status endpoint.
4. Add integration tests proving task execution, restart recovery, cancellation,
   and accurate online/offline state.
5. Only after tests pass, enable restart policies and monitor worker health.

## Privileges
Never run model-generated commands as unrestricted root on the Codespaces host.
Keep the existing container non-root (UID 10001), with dropped capabilities,
read-only root filesystem and no-new-privileges. Provide a dedicated writable
project workspace. Allow administrative operations only through an audited,
explicitly approved executor with a narrow command allowlist and bounded
timeouts. Do not mount the Docker socket or host root filesystem into agent
containers. Human approval is required for destructive operations, secrets,
privilege changes, and production deployments.

## Existing service start (API only)
From the repository root, after reviewing the compose file:

```sh
export DEBIAN13_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose -f debian13/system/compose.yaml build
docker compose -f debian13/system/compose.yaml up -d
docker compose -f debian13/system/compose.yaml ps
```

Keep the port private. This starts the API service only; it does **not** start
autonomous AI workers. A Codespace can be suspended or stopped by GitHub, so
`restart: unless-stopped` does not guarantee continuous 24/7 operation.
