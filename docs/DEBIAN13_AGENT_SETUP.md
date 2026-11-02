# New Debian 13 system: isolated development setup

This branch prepares an optional Debian 13 Codespaces profile for the new independent system in `debian13/`. The repository name is historical. Do not import the legacy application into the new system.

## Launch
In GitHub Codespaces, select New with options, branch `setup/debian13-agent-environment`, and `.devcontainer/debian13/devcontainer.json`. The editor opens `debian13/`; dependency installation uses only a lockfile in that directory. Preview port 3000 is private. No application is started automatically.

## Workstreams
1. Debian 13 packaging, boot and system architecture.
2. Responsive GUI and accessibility.
3. MCP, Codex, GPT Actions integration with least-privilege credentials.
4. CI, diagnostics and integration tests.

Use distinct issues and branches per workstream and review passing CI before integration. Profiles and assigned issues do not prove running workers. Keep secrets in configured secret stores.

## Verification boundaries
The workflow checks Debian release 13, configuration syntax, independent workspace path and private preview configuration. It does not build the devcontainer image, boot an OS, start agents or prove external MCP connectivity. The image and features still need an actual Codespaces build.

## Continuous execution
Codespaces alone does not provide permanent 24/7 agent work. Continuous execution requires a configured authenticated runner/orchestrator, available agent APIs, quotas and spending limits. Work in this chat continues during an active session; scheduled checks are separate.
