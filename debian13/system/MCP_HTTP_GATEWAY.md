# Debian 13 — opt-in read-only MCP HTTP gateway

**Status:** local implementation and CI tests only. This does **not** publish
a remote MCP service, install a ChatGPT plugin, connect a real agent or provide
an autonomous worker. The original source registry is not proof of inference.

## Why this is separate

`mcp_server.py` already provides seven read-only tools over stdio.
`mcp_http_gateway.py` exposes the same tool contract on a **stateless,
loopback-only HTTP POST /mcp** transport (legacy MCP protocol 2025-11-25).
It does not add shell/root operations, task creation/dispatch, file writes,
GitHub operations, payments or arbitrary URLs.

The gateway has a separate strong Bearer secret, validates Host and Origin,
rejects redirects via the existing backend MCP proxy, rejects unsupported
methods, caps incoming requests at 64 KiB, and accepts only JSON-RPC requests
for the existing MCP methods.

**This transport implements 2025-11-25, not the newer 2026-07-28 request
metadata revision.** Modern clients must negotiate compatible transport or
this gateway needs to be upgraded after a real client compatibility test.

## Run locally (Python, no external service)

### Simplest option: one-command opt-in

From the repository root:

```sh
DEBIAN13_ENABLE_MCP_HTTP=1 bash debian13/start-local.sh
```

This launches the existing API, GUI and the separate private MCP gateway.
The launcher automatically creates a **different** 48-byte random Bearer
credential for MCP in the state directory (default
`~/.local/state/debian13/mcp-gateway-token`, mode 0600). It reuses this
credential after restarting the app and terminates the gateway when the
launcher stops. The gateway is *disabled by default*, and neither the
secret nor local API token is printed in the console.

To configure a client on **the same trusted host**, retrieve the gateway
token from the private file into the client's secret store. Never paste
that token into issues or commit it. Read the token only as the host
operator; do not expose this local port on GitHub Codespaces.

To select a different local port, set
`DEBIAN13_MCP_GATEWAY_PORT` to an unused port between 1024 and 65535.
The gateway's port must differ from the GUI and API ports. This option
does not configure a TLS reverse proxy, OAuth or ChatGPT remote access.

### Verify actual local MCP and backend (no model or paid API)

With `DEBIAN13_ENABLE_MCP_HTTP=1` and the console running, in another
terminal run:

```sh
python3 debian13/system/mcp_preflight.py
```

The self-test reads the private MCP gateway token from the state directory,
then runs real authenticated `initialize`, `tools/list` and read-only
`tools/call` against the existing API. It outputs JSON suitable for
diagnostics, with truthful flags such as:

- `localMcpStatus: verified`: **this machine only**;
- `originalAgentExecutionVerified`: taken from the original agent registry
  report, not from the presence of an agent profile;
- `workersReportedByBackend`: a counter reported by Work; not proof of
  execution;
- `chatgptExternalConnection: not_tested`: connecting ChatGPT requires
  separate account permissions, tunnel credentials and an external test;
- `publicMcpEndpoint: not_deployed_by_this_check`: this test never publishes
  a port or configures an external account.

When the gateway is off, its token is wrong, the backend is unavailable, or
new unknown/mutating tools appear, the test fails with `BLOCKED`, exits
nonzero and does not disclose credentials or private task descriptions.
The check makes **no LLM inference calls and consumes no API credits**.

### Manual option: two terminals

Start the existing app in terminal A:

```sh
bash debian13/start-local.sh
```

In a separate terminal B (use the same operator token file created by
`start-local.sh`, without committing or printing secrets):

```sh
export DEBIAN13_SYSTEM_API_URL="http://127.0.0.1:8765"
export DEBIAN13_API_TOKEN="$(cat "$HOME/.local/state/debian13/operator-token")"
export DEBIAN13_MCP_GATEWAY_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
python3 debian13/system/mcp_http_gateway.py
```

If you set `DEBIAN13_STATE_DIR` or `DEBIAN13_API_PORT`, adjust the file
path/port accordingly. The gateway listens on **127.0.0.1:8766** only.
Keep the `DEBIAN13_MCP_GATEWAY_TOKEN` in the client/host secret store; losing
it after restarting the shell invalidates old client credentials. In
production use a persistent managed secret. Gateway and API tokens must differ.

Both startup modes use only a loopback listener. Neither asks the
server to download an Ollama model or consume a paid API request.

### Basic authenticated HTTP test

Use a local MCP client that sends `POST /mcp`, an `Authorization: Bearer`
header containing the gateway token, JSON content and an Accept header with
both `application/json` and `text/event-stream`. First initialize:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"local-probe","version":"1"}}}
```

Then send the `notifications/initialized` notification (returns HTTP 202),
`tools/list`, and read-only `tools/call` (one HTTP POST per message).
Use `MCP-Protocol-Version: 2025-11-25` after initialization. The gateway
does **not** implement standalone GET SSE streams: GET /mcp returns 405.
No browser CORS access is enabled by default.

Run regression tests:

```sh
python3 -m unittest discover -s debian13/system/tests -p 'test_*.py' -v
```

## Optional service on a real Debian 13 host (systemd user manager)

To keep **the API, GUI and local MCP gateway** running across process failures
while the Debian machine and user manager are online, use a **non-root**
systemd user service. This is not an AI worker or a subscription bypass.

From the checked-out project directory, as your **regular Debian user**:

```sh
python3 debian13/install-user-service.py --check
python3 debian13/install-user-service.py --install
systemctl --user daemon-reload
systemctl --user enable --now debian13-console.service
systemctl --user status debian13-console.service
python3 debian13/system/mcp_preflight.py
```

The installer refuses root, never invokes `systemctl` or `loginctl`
itself, writes the user unit privately (0600), and requires explicit
`--force` to replace an existing unit with different content.
`--check` never writes files. The unit enables local MCP
(`DEBIAN13_ENABLE_MCP_HTTP=1`), runs the existing launcher as the
current user, restarts on failures and **does not expose ports or
configure any external TLS tunnel**. Tokens are stored separately by
the launcher, not embedded in the unit.

To stop and disable it:

```sh
systemctl --user disable --now debian13-console.service
```

**24/7 limitation:** a user service normally runs only while that user's
systemd manager is alive. Operation after logout requires an administrator
to *separately authorize and configure* `loginctl enable-linger USER`.
A powered-off or suspended computer, resource exhaustion, Codespaces
suspension, and GitHub limits still stop the service. No claim of
autonomous AI work follows merely from an active unit.

The generated unit stores an absolute project path; if the project moves
after installation, stop the service and regenerate the unit with
`--install --force` only after reviewing the change. Keep the
repository directory and its token files private.

## Before any ChatGPT or external access

1. Confirm that the current ChatGPT plan and custom-plugin permissions
   support this connection. A ChatGPT Plus subscription alone does not make
   this loopback endpoint reachable or provide OpenAI API credits.
2. Prefer **Secure MCP Tunnel** for a private server when supported.
   Otherwise use an operator-controlled TLS reverse proxy **with a reviewed
   identity layer** (OAuth/OIDC if required by the client), per-user scopes,
   request limits and short-lived credentials. A static gateway Bearer token
   alone is **not** sufficient for public exposure.
3. If using a reverse proxy, it must connect only to 127.0.0.1:8766,
   rewrite `Host` to `127.0.0.1:8766`, preserve the intended Origin,
   and block access to the backend API and any other local ports.
4. If a client sends an Origin header, explicitly allow only that trusted
   exact **HTTPS origin** using
   `DEBIAN13_MCP_ALLOWED_ORIGINS=https://trusted.example`.
   Never set a wildcard. By default all supplied Origin values are rejected;
   requests without Origin still require the gateway Bearer token.
5. Complete live client negotiation, tool discovery, authorization, and
   negative-security tests; only then consider marking the service
   connected in the GUI. Confirm whether the client requires the newer
   MCP 2026-07-28 transport or additional OAuth features.
6. Obtain operator approval before deploying any network entry point;
   do not make a Codespaces port public or merge this PR automatically.

The gateway cannot make your original four AI workers run in the
background. It only exposes truthful read-only status and queued Work tasks
which are stored but not executed by an autonomous worker.
