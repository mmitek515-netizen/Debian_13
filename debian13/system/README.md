# Debian 13 System — first runnable stage

This is a new, standalone Debian 13 system prototype. It does not depend on the
legacy Bastilla OS 2 application or modify its API. The first stage provides an
authenticated local API and runtime diagnostics, a constrained command
terminal, four selectable agent profiles, and an optional real OpenAI-compatible
chat provider.

## What is and is not running

- The four names in `GET /v1/profiles` are role profiles, not four background
  AI processes. A profile handles a chat only when the configured provider
  returns a real response.
- Without a configured model URL, key, and model name, `/v1/chat` returns
  `503 provider_not_configured`; it never fabricates a reply.
- A successful provider request confirms that one chat request reached the
  configured endpoint. It does not mean four autonomous agents are running.
- The container and host-service tests do not boot a Debian installer or ISO.
  No bootable image is part of this first stage.

## Stage 1: run in an isolated Debian 13 container

Requirements: Docker Engine with Compose v2. The image is based on a pinned
Debian 13 image digest and installs only Debian packages. The Trixie package
archive is not snapshot-pinned, so package updates can change subsequent builds;
this is a repeatable setup recipe, not a bit-for-bit reproducible image build.
Review and update the base digest and package versions as part of release
maintenance.

From this directory:

```sh
export DEBIAN13_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d
```

The service is published only on `127.0.0.1:8080`. Its container runs as UID
10001 with a read-only root filesystem, no Linux capabilities, no-new-privileges,
resource limits, and a dedicated named workspace volume. The terminal does not
invoke a shell and only accepts a small allowlist of commands with workspace-
confined file paths. It has a per-IP request limit and bounds execution time and
output. Keep the port private; the bearer token is required for all API routes
except liveness.

### Codespaces Debian 13 readiness

From the repository root, run these commands in one Codespaces terminal. They
keep the generated token in the shell environment and container; do not print it
or forward the port publicly:

```sh
export DEBIAN13_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
unset MODEL_CHAT_URL MODEL_API_KEY MODEL_NAME
docker compose -f debian13/system/compose.yaml build
docker compose -f debian13/system/compose.yaml up -d
python3 debian13/system/readiness.py
```

The checker verifies the host's `/etc/os-release` is Debian `VERSION_ID=13`,
health, rejection of anonymous diagnostics with HTTP 401, authenticated
diagnostics, and whether provider settings are present. It never prints
credentials. A missing provider blocks readiness; configured settings are not
proof that the provider is reachable or that inference works. The checker never
sends a model prompt. Use `docker compose -f debian13/system/compose.yaml down`
to stop the service.

### Verify the PR #97 adapter against the running service

The API gateway owns `debian13/system_service_adapter.py`; this branch does not
copy or modify that shared file. The smoke is pinned to the reviewed PR #97
revision `4e5138fda32fe3513c3929b0c433ab42b3ea3fb0` and verifies the adapter
file's SHA-256 before importing it. With that source available, run its actual
implementation against the running `/v1` service:

```sh
git show 4e5138fda32fe3513c3929b0c433ab42b3ea3fb0:debian13/system_service_adapter.py > /tmp/system_service_adapter.py
DEBIAN13_SYSTEM_API_URL=http://127.0.0.1:8080 \
DEBIAN13_API_TOKEN="$DEBIAN13_API_TOKEN" \
python3 debian13/system/adapter_integration_smoke.py \
  --adapter /tmp/system_service_adapter.py
```

This smoke calls the real service's authenticated `/v1/profiles` through
`SystemServiceAdapter`, verifies that an invalid token is treated as
unavailable, and checks fail-closed chat only when no provider is configured.
When a provider is configured it skips chat to avoid an unapproved request.
The adapter integration does not itself prove a real model is reachable or
perform real inference.

## API compatibility boundary

This service exposes `/v1/profiles`, `/v1/diagnostics`, `/v1/terminal`, and
`/v1/chat`, and requires a bearer token except for `/healthz`. Alex's separate
Debian 13 demo contract in PR #97 uses `/api/v1/status`, `/api/v1/agents`, and
session/task routes on a loopback-only listener. Its server-side
`SystemServiceAdapter` can call this service's authenticated `/v1/profiles` and
`/v1/chat`; that narrow adapter does not make the service API compatible with
the browser-facing `/api/v1` contract or provide `/v1` diagnostics, sessions,
or streaming. Keep the token server-side and do not expose either listener
publicly. This service's terminal and model chat remain separate; model output
is not executed.

Optional real model access uses an OpenAI-compatible chat-completions endpoint.
Set these variables before starting Compose; the URL must be HTTPS, except that
HTTP loopback endpoints are allowed for local development:

```sh
export MODEL_CHAT_URL="https://provider.example/v1/chat/completions"
export MODEL_API_KEY="use-a-deployment-secret"
export MODEL_NAME="provider-model-id"
docker compose -f compose.yaml up -d --force-recreate
```

Do not put real keys in shell history, tracked files, or a public image. Chat
requests have a timeout; provider redirects, arbitrary client-supplied URLs,
and fallback/mock replies are not used.

Check the service and authenticated API:

```sh
curl --fail http://127.0.0.1:8080/healthz
curl --fail -H "Authorization: ******" \
  http://127.0.0.1:8080/v1/profiles
curl --fail -H "Authorization: ******" \
  -H 'Content-Type: application/json' \
  -d '{"command":"ls"}' http://127.0.0.1:8080/v1/terminal
curl --fail -H "Authorization: ******" \
  http://127.0.0.1:8080/v1/diagnostics
```

Stop the service with `docker compose -f compose.yaml down`. The named workspace
volume persists; remove it only when intentionally discarding user files:
`docker compose -f compose.yaml down -v`.

## Stage 1 alternative: install as a host systemd service

On Debian 13 with Python 3 and systemd:

```sh
sudo ./install.sh
sudo systemctl status debian13-system.service
sudo journalctl -u debian13-system.service
```

The installer creates a system account, a root-managed environment file, and a
workspace writable only by that account. The service binds to loopback and has
systemd filesystem/kernel hardening. Retrieve the generated local bearer token
only when needed using the command printed by the installer. To configure an
AI provider, edit `/etc/debian13/system.env` as root and restart the service.

## Tests and evidence

The focused tests use Python's standard library and a local fake provider; no
external account, payment, model, or network service is required:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile server.py
python3 smoke_test.py
systemd-analyze verify systemd/debian13-system.service
docker compose -f compose.yaml config
docker compose -f compose.yaml build
```

For the isolated HTTP smoke test, build `debian13-system:local` first; the test
starts a temporary container with a random API token, loopback-only ephemeral
port, read-only root filesystem, dropped capabilities, and resource limits. It
checks unauthenticated/invalid-token rejection, profiles, non-root terminal
execution, authenticated runtime diagnostics, configured container isolation via
Docker inspect, denied writes to the root filesystem, an unconfigured chat
provider, and the 429 rate-limit response, then removes the container. It reports
the image ID and checked container settings; it does not boot an OS image or
provide continuous host monitoring.

The repository CI runs Python compilation and unit tests, shell syntax,
systemd, Compose, and image-build checks alongside the existing application
checks. Run `smoke_test.py` locally after the image build for the isolated
container HTTP checks.

The provider test confirms the selected profile and real HTTP request/response
flow against a test server; it is not evidence that a production AI account is
configured. A passing container/package test is not a Debian OS boot. A
bootable ISO, installer run, VM boot log, package release, and actual production
provider integration remain separate acceptance work.

## API contract

Every endpoint except `GET /healthz` requires
`Authorization: ****** Chat and terminal work remain
separate; model output is never executed as a command.

| Route | Request / response |
| --- | --- |
| `GET /healthz` | Liveness only: `{"status":"ok"}` |
| `GET /v1/profiles` | Profile IDs/roles, all with `active:false`, and provider configuration status |
| `GET /v1/diagnostics` | Authenticated, read-only process UID/GID, workspace writability, provider configuration, Python version, and Linux security fields when `/proc/self/status` is available; no credentials or boot claim |
| `POST /v1/terminal` | `{"command":"ls"}`; direct allowlisted argv execution and bounded output |
| `POST /v1/chat` | `{"profile":"aria","message":"..."}`; real provider response or explicit error |

Error responses use `{"error":{"code":"...","message":"...","requestId":"..."}}`.
