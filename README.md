# GPTHub Hack 2026

An AI assistant platform that combines a customized **OpenWebUI** frontend with a dedicated **GPTHub API** backend.  
OpenWebUI provides the user experience, while GPTHub API handles model routing, feature orchestration, and integration logic.

## Why this project is portfolio-ready

- End-to-end product architecture: UI, API, persistence, vector storage, and model providers.
- Real feature surface (not a toy demo): auto model routing, chat memory, media workflows, and workspace automation.
- Production-style deployment with Docker Compose and health checks.
- OpenAI-compatible API layer for easier integration with external tools.

## Repository structure

- `apps/gpthub-api` — FastAPI backend with routing logic and product features.
- `apps/openwebui` — local OpenWebUI fork customized for GPTHub integration.
- `config/` — shared defaults, including auto-model presets.
- `docker-compose.yml` — main multi-service stack definition.
- `docker-compose.override.yml` — local development port mapping.
- `docs/` — internal implementation notes and feature specifications.

## Core architecture

The platform runs as a service monolith with supporting infrastructure:

1. **OpenWebUI** receives user input and renders chat experiences.
2. **GPTHub API** applies routing policies, feature settings, and business logic.
3. **PostgreSQL** stores operational data for both GPTHub and OpenWebUI.
4. **Qdrant** powers vector-backed memory retrieval.
5. **LLM providers** (MWS GPT and OpenAI-compatible endpoints) execute model calls.

## Feature snapshot

- **Auto/Autoselect routing** with task-type-aware model selection.
- **Chat memory** with retrieval for long-running conversations.
- **OpenAI-compatible endpoints** for chat, embeddings, image generation, and audio transcription.
- **Media gallery** and related chat ingestion flows.
- **Workspaces + file tree operations** for coding-style task execution.
- **Runtime feature settings** for controlled behavior toggles.

## Quick start

### 1. Prerequisites

- Docker + Docker Compose
- A valid model provider key (for non-stub mode)

### 2. Prepare environment

```bash
cp .env.example .env
```

Open `.env` and verify at least these values:

| Variable | Required | Description |
| --- | --- | --- |
| `OPENWEBUI_EXTERNAL_PORT` | Yes | External port for OpenWebUI (default: `3000`) |
| `BACKEND_EXTERNAL_PORT` | Yes | External port for GPTHub API (default: `8000`) |
| `MWS_STUB_MODE` | Yes | `true` for local stub behavior, `false` for real provider calls |
| `MWS_GPT_API_KEY` | Required when `MWS_STUB_MODE=false` | API key for MWS GPT |
| `E2B_API_KEY` | Required for autopilot scenarios | Enables E2B-backed execution features |
| `OPENWEBUI_ADMIN_EMAIL` / `OPENWEBUI_ADMIN_PASSWORD` | Yes | Initial OpenWebUI admin credentials |

### 3. Build and run

```bash
docker compose up -d --build
```

### 4. Check service status

```bash
docker compose ps
```

### 5. Open the platform

- OpenWebUI: `http://localhost:${OPENWEBUI_EXTERNAL_PORT:-3000}`
- GPTHub API root: `http://localhost:${BACKEND_EXTERNAL_PORT:-8000}/`
- GPTHub API docs: `http://localhost:${BACKEND_EXTERNAL_PORT:-8000}/docs`

## Operational checks

Quick API availability probe:

```bash
curl http://localhost:${BACKEND_EXTERNAL_PORT:-8000}/
```

Expected response:

```json
{"status":"ok","service":"GPTHub API","mode":"stub-ready"}
```

If internal API auth is enabled in your environment, send the bearer token in requests to `/api/v1/*` and `/v1/*` routes.

## Configuration notes

### GPTHub and OpenWebUI databases

- `GPTHUB_POSTGRES_*` variables configure GPTHub API storage.
- `OPENWEBUI_POSTGRES_*` variables configure OpenWebUI storage.

### OpenWebUI ↔ GPTHub API integration

- `OPENWEBUI_GPTHUB_API_URL` points OpenWebUI to GPTHub API inside the Compose network.
- `OPENWEBUI_GPTHUB_AUTO_BOOTSTRAP_OPENAI=true` auto-registers GPTHub as an OpenAI-compatible provider.
- `OPENWEBUI_OPENAI_API_BASE_URL` / `OPENWEBUI_OPENAI_API_KEY` can be used for an additional direct provider.

### Auto-model defaults

`config/auto-model-defaults.json` defines baseline auto-routing defaults such as classifier model and task-type model mapping.  
After changing defaults, rebuild services to apply updates reliably.

## Request flow (high level)

1. User sends a message in OpenWebUI.
2. OpenWebUI forwards the request to GPTHub API.
3. GPTHub API selects routing strategy and target model.
4. The selected upstream provider processes the request.
5. The final response is returned to the chat interface.

## Useful commands

```bash
# Follow logs
docker compose logs -f

# Restart a single service
docker compose restart backend

# Stop stack
docker compose down
```
