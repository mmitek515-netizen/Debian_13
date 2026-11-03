# Ollama for the standalone Debian 13 prototype

Ollama is optional. The default Compose stack remains unchanged.
The additional `compose.ollama.yaml` runs Ollama as a private service on the
Docker Compose network. The Debian 13 API talks to Ollama's native `/api/tags`
and streaming `/api/chat` endpoints. It does not grant root to agents or expose
Ollama on a public host port.

## Start

From the repository root:

```sh
bash debian13/start-ai-session.sh
```

The script checks for at least 2 GiB available RAM and disk before Compose can
download the model. The default is the text-only `qwen3:0.6b` Q4_K_M model
(about 523 MB; Apache-2.0). `OLLAMA_LLM_LIBRARY=cpu` explicitly forces CPU
inference; no GPU device is passed to the container.
Override it with `OLLAMA_MODEL` if the host has more resources. In Codespaces,
open port 3000 with **Private** visibility; port 11434 is bound to host loopback
only and must not be forwarded publicly.

The script creates a local operator token outside the repository. To verify the
private model service from inside its container:

```sh
curl -f http://127.0.0.1:11434/api/tags
```

The UI/API status probes `/api/tags`; configured base URL and model name remain
server-side. Conversations use `/api/chat` token streaming and persist in the
private SQLite workspace. Selecting an original agent never substitutes an
Ollama persona: without that agent's real chat API, the request fails as
`agent_disconnected` and the attempt is recorded without message content.
The API and UI start independently of the model download so a failed pull does
not leave the app hung. If the one-shot model initializer fails, inspect its
container logs and retry:

```sh
docker compose -f debian13/system/compose.yaml \
  -f debian13/system/compose.ollama.yaml run --rm ollama-model-init
```

## Vision

The default `qwen3:0.6b` is text-only, **not** a vision model. Vision remains
disabled until an operator explicitly selects and downloads a vision model.
For example:

```sh
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull qwen3-vl:8b
```

Set `OLLAMA_VISION_MODEL=qwen3-vl:8b` before starting Compose to download the
vision model. This does not yet connect the UI's image-upload path to native
Ollama vision requests.

## Security and availability

- Ollama is reachable inside Compose as `ollama:11434` and from host loopback
  as `127.0.0.1:11434`; it is not bound to a public host interface.
- The internal HTTP URL is accepted only with
  `DEBIAN13_ALLOW_INTERNAL_OLLAMA=1` and the exact `ollama:11434` hostname.
- The Debian 13 API still requires a separate secret `DEBIAN13_API_TOKEN`.
- This setup does not create autonomous background agents or a bootable OS.
- GitHub-hosted Actions runners are temporary and generally unsuitable for
  persistent inference; deploy on a persistent host for 24/7 use.
- Review and pin the Ollama container image to a tested digest before
  production deployment.

## Optional Llama 3.2 Vision 11B

The official Ollama tag is `llama3.2-vision:11b` (approximately 7.8 GB model download).
It accepts image and text input, and returns text. Ollama recommends at least
8 GB VRAM for GPU inference; check actual host resources before downloading.

```sh
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull llama3.2-vision:11b
```

To select it as the optional configured vision model:

```sh
export OLLAMA_VISION_MODEL=llama3.2-vision:11b
docker compose -f compose.yaml -f compose.ollama.yaml up -d --build
```

**Important:** selecting a vision-capable model does not yet enable image uploads
through the Debian 13 application. The GUI explicitly reports this limitation;
no unsupported image request is silently sent.
