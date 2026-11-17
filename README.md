# Purr — independent Gateway and Core

Purr is a shared, multi-tenant AI provider for natural conversation and Sophia-approved product guidance. The Gateway owns evolving external contracts; Purr Core stays independent of web-framework logic.

## Architecture

- `purrfect.gateway` — FastAPI v1 contracts, static trusted client credentials, product grants, JSON and SSE responses.
- `purrfect.core` — framework-independent conversation, retrieval, and response streaming.
- `purrfect.infrastructure.scheduler` — per-tenant fair, cancelable, in-process inference scheduling.
- `purrfect.infrastructure.cache` — bounded, revision-aware, tenant-isolated retrieval evidence cache.
- `purrfect.infrastructure.sessions` — interchangeable in-memory and SQLite session stores.
- `purrfect.ollama` — complete-response and native chunk streaming inference adapter.
- `purrfect.sophira*` — approved, revisioned local knowledge catalog.

No WordPress plugin, Purr Assistant, Docker, Redis, or microservice networking is bundled here.

## Run locally (Python 3.14+; PowerShell)

```powershell
python -m pip install -e ".[dev]"
python -m pytest
$env:PURR_CLIENTS_JSON = '[{"token":"local-development-token-12345","tenant_id":"dev","products":["demo"]}]'
python -m purrfect
```

By default `PURR_SESSION_DB=./purr-sessions.db` stores conversation turns in SQLite across restarts. Set `PURR_SESSION_DB` to the empty string to use bounded ephemeral sessions. Every history lookup is tenant-scoped, and only successfully completed answers are persisted. Neither mechanism identifies end users: the Gateway still relies on trusted application credentials and a client-supplied session ID. **Session ownership/visitor identity must be established before production exposure.**

Never place the client Bearer secret in browser-side code. Use an Assistant backend. Set up a TLS reverse proxy before any remote deployment.

## API

- `GET /v1/health` — authenticated status
- `POST /v1/chat` — authenticated JSON response
- `POST /v1/chat/stream` — authenticated server-sent events (SSE) over POST: `delta` events with `{"text":"..."}`; terminal `done` includes session ID, status and approved sources. Post-header errors use an `error` event containing status and safe message rather than changing HTTP status.

Both chat endpoints accept `session_id`, `message`, and optionally paired `product_id`/`product_version`. The stream is consumed by a server-side HTTP client or browser fetch implementation (native EventSource is GET-only). Unlike polling, the Ollama adapter emits real incremental model chunks.

Example PowerShell test:

```powershell
$headers = @{ Authorization = "Bearer local-development-token-12345" }
$body = @{ session_id = "demo"; message = "Hi!" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/v1/chat -Method Post -Headers $headers -ContentType "application/json" -Body $body
curl.exe -N -X POST http://127.0.0.1:8765/v1/chat/stream -H "Authorization: Bearer local-development-token-12345" -H "Content-Type: application/json" -d '{"session_id":"demo","message":"Hi!"}'
```

Product knowledge must be namespaced in Sophia as `tenant_id/product_id` (for example `dev/demo`) and approved via the existing trusted CLI. Set `PURR_SOPHIA_DB` to the database path.

## Runtime settings

- `PURR_CLIENTS_JSON` — required static trusted client credentials.
- `PURR_MODEL_BACKEND` — `deterministic` or `ollama` (default deterministic).
- `PURR_OLLAMA_MODEL`, `PURR_OLLAMA_URL`, `PURR_SOPHIA_DB`.
- `PURR_SESSION_DB` — SQLite history database (default `./purr-sessions.db`; blank = memory only).
- `PURR_HISTORY_LIMIT` — stored turns per session, default 6.
- `PURR_INFERENCE_CONCURRENCY` — active model calls, default 1.
- `PURR_QUEUE_LIMIT`, `PURR_TENANT_QUEUE_LIMIT`, `PURR_QUEUE_TIMEOUT`.
- `PURR_RETRIEVAL_CACHE_SIZE`, `PURR_HOST`, `PURR_PORT`.

## Known limitations

This is a development foundation, **not a production-ready multi-tenant service**. In-process session locks do not synchronize across workers/hosts, SQLite does not provide distributed session coordination, and client-provided session IDs are not verified as owned by an individual visitor. There is no persistent inference queue, cross-worker fairness, tenant-issued end-user identity, durable idempotency, credential rotation, user-level quotas, or streaming resume/replay. Stream cancellation should release local inference permits but cannot guarantee remote runtime immediately stops work. Core retrieval remains lexical, and real inference latency remains to be benchmarked. Keep a single API process until coordinated state and identity safeguards are built.
