# Debian 13 integrations — MCP, GPT Actions, Codex

This is an **independent Debian 13 prototype**, not Bastilla OS 2. These
integrations provide real files, API surfaces, and an opt-in GitHub workflow;
none is evidence that a remote account, agent worker, model, or 24/7 server
is connected. The Settings screen calls `GET /api/v1/integrations` via
the local UI proxy and displays **connected: false** until verified.

## 1. Model Context Protocol (MCP) — read-only stdio

`mcp_server.py` is a dependency-free MCP server speaking JSON-RPC over
newline-delimited standard input/output (protocol version 2025-11-25).
It advertises three read-only tools:

- `debian13_profiles`: GET `/v1/profiles`
- `debian13_diagnostics`: GET `/v1/diagnostics`
- `debian13_integrations`: GET `/v1/integrations`

It never offers a shell, file writes, root access, repository modification or
arbitrary HTTP requests. The API token remains in process environment. The
API must already be running, and MCP requires explicit client setup.

**Local Python example (from `debian13/system`):**

```sh
export DEBIAN13_SYSTEM_API_URL=http://127.0.0.1:8080
# DEBIAN13_API_TOKEN is already configured in the calling environment.
python3 mcp_server.py
```

Send a JSON-RPC request on its standard input, one JSON object per line:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"local-test","version":"1"}}}
```

Then send a `notifications/initialized` notification and `tools/list`.
A configured MCP client can launch the same executable via stdio; use
secure environment variable settings in the client, never a token in an MCP
tool argument or GitHub Issue.

**Inside Docker Compose** (uses the token from the existing API container):

```sh
docker compose -f compose.yaml exec -T debian13-system \
  python3 /opt/debian13/system/mcp_server.py
```

The stdio server remains available for local clients. An optional
**loopback-only** HTTP wrapper is now provided in `mcp_http_gateway.py`
with documented setup and exact security constraints in
[`MCP_HTTP_GATEWAY.md`](MCP_HTTP_GATEWAY.md). This wrapper is **not** a
publicly deployed HTTPS server, OAuth identity provider or active ChatGPT
connection; it does not execute tasks or reach GitHub automatically.
It implements stateless Streamable HTTP with 2025-11-25 compatibility;
the 2026-07-28 protocol and client compatibility must be tested separately.

## 2. GPT Actions — authenticated API

Import `gpt-actions.openapi.json` into the GPT Actions editor. First,
**replace** `https://debian13.example.com` in `servers.url` with an
operator-controlled **HTTPS** domain routing to the real API. The existing
Docker Compose binds to `127.0.0.1:8080` intentionally and is **not**
publicly accessible; do not publish it to the internet without authenticating
reverse proxy, TLS, traffic controls and an explicit security review.

Configure API-key authentication as **Bearer** using a dedicated secret
(matching `DEBIAN13_API_TOKEN` in this single-operator prototype). Never put
the secret in the JSON schema, a README or a client-side JavaScript file.
The schema exposes only real endpoints:

- GET `/v1/profiles`
- GET `/v1/diagnostics`
- GET `/v1/integrations`
- GET `/api/v1/tasks` — persisted Work queue, including `workersRunning`;
  **queued means recorded, not executed**
- GET `/api/v1/original-agents` — state of the source task registry and
  explicit `workerVerified` / `originalAgentExecutionVerified` indicators;
  **a profile or registry entry is not proof of an autonomous agent**
- POST `/v1/chat` (text only, requires reachable model provider)

The POST operation is marked consequential and may require confirmation.
The two new GET operations are read-only; the schema does not offer task
dispatch, writes, root, shell or purchase actions.
GPT Actions are **not yet connected to a specific GPT**; import, HTTPS
deployment, account permissions and real request tests remain outstanding.
Until an operator configures a compatible client and confirms an HTTPS test
request, the integration MUST display `connected=false`. Never expose the
localhost port, reverse-proxy admin endpoints or bearer tokens publicly.
The task list contains private operator descriptions; use a dedicated
read-only credential/proxy with access controls before any external client.
Do not use `/v1/terminal` as a GPT Action.

## 3. Codex — manual GitHub issue-to-PR execution

The workflow `.github/workflows/debian13-codex-issue.yml` is installed on
the default branch. From the GitHub Actions tab select
**Debian 13 Codex — implement reviewed issue**, click **Run workflow**, and
enter issue number `3`, `4`, or `5`.

The repository owner must configure the GitHub secret **OPENAI_API_KEY** in
Actions secrets. A ChatGPT subscription alone is not an API secret or
guaranteed API credit; the API is billed independently. Never commit API keys.

The workflow:
1. Loads an issue and checks out `migration/debian13-codespaces`.
2. Runs official `openai/codex-action@v1` with `:workspace` permissions and
   `drop-sudo`, limiting the published patch to `debian13/`.
3. Runs Python + Node tests **in a separate job without an API secret or
   repository write token**.
4. If tests pass, creates a new reviewable PR targeting
   `migration/debian13-codespaces`; **never merges** automatically.

GitHub Actions runners are short-lived. Codex is not a background daemon
and no PR is produced until you dispatch a run with valid credentials.
Keep branch protections and require human review before merging.

## 4. Integration tests

```sh
python3 -m unittest discover -s debian13/system/tests -v
node --test debian13/ui/dev_server.test.mjs
docker compose -f debian13/system/compose.yaml config
```

If tests have not been run on the modified commit, status must remain
**unverified**. The UI's older chat/session/task endpoints use a different
backend contract and are **not** made functional by these integrations alone.

Related Issues: #3 (Codex), #4 (MCP), #5 (GPT Actions); see also #2.
