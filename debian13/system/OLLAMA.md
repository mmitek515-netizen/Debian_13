# Ollama for the standalone Debian 13 prototype

Ollama is optional. The default Compose stack remains unchanged.
The additional `compose.ollama.yaml` runs Ollama as a private service on the
Docker Compose network and connects the existing Debian 13 API to its
OpenAI-compatible `/v1/chat/completions` endpoint. It does not grant root to
agents or expose Ollama on a public host port.

## Start

From `debian13/system`:

```sh
export DEBIAN13_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose -f compose.yaml -f compose.ollama.yaml up -d --build
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull qwen3:14b
docker compose -f compose.yaml -f compose.ollama.yaml ps
curl -fsS http://127.0.0.1:8080/healthz
```

Pulling models downloads multiple gigabytes and requires sufficient RAM and
disk. CPU-only inference on a 14B model can be slow. A 20 GB memory limit is
configured for Ollama, but the host must actually provide that memory.
Choose a smaller model on constrained hosts.

## Vision

`qwen3:14b` is a text model, **not** a vision model. For image analysis:

```sh
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull qwen3-vl:8b
```

Set `OLLAMA_MODEL=qwen3-vl:8b` before starting Compose to use the vision
model as the backend. Note: the current `/v1/chat` API only accepts text
messages; image uploads and vision-aware chat payloads require a separate
implementation and tests. Merely pulling Qwen3-VL does not enable vision in UI.

## Security and availability

- Ollama is reachable only inside the Compose network as `ollama:11434`.
- The internal HTTP URL is accepted only with
  `DEBIAN13_ALLOW_INTERNAL_OLLAMA=1` and the exact `ollama:11434` hostname.
- The dummy `MODEL_API_KEY` is only for local Ollama compatibility; the
  Debian 13 API still requires a separate secret `DEBIAN13_API_TOKEN`.
- This setup does not create autonomous background agents or a bootable OS.
- GitHub-hosted Actions runners are temporary and generally unsuitable for
  persistent local 14B inference; deploy on a persistent host for 24/7 use.
- Review and pin the Ollama container image to a tested digest before
  production deployment.

## Llama 3.2 Vision 11B

The official Ollama tag is `llama3.2-vision:11b` (approximately 7.8 GB model download).
It accepts image and text input, and returns text. Ollama recommends at least
8 GB VRAM for GPU inference; check actual host resources before downloading.

```sh
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull llama3.2-vision:11b
```

To select it for the current text-chat API, start Compose with:

```sh
export OLLAMA_MODEL=llama3.2-vision:11b
docker compose -f compose.yaml -f compose.ollama.yaml up -d --build
```

**Important:** selecting a vision-capable model does not yet enable image uploads
through the Debian 13 application. That needs multimodal request support in
`server.py` and the UI. For multimodal prompts, Ollama's native `/api/chat`
accepts an `images` array in a user message.
