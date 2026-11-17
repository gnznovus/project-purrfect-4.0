# Purr — independent Gateway and Core

Purr is a shared multi-tenant AI provider for Sophia-grounded product guidance. Gateway owns external authentication and API contracts; Core owns conversational behavior; infrastructure handles inference and state.

## Foundation

- **Gateway:** FastAPI + pluggable client verification, expiring tenant-bound session tickets, JSON and SSE endpoints.
- **Core:** framework-independent conversation, approved Sophia retrieval and inference.
- **State:** in-memory/SQLite for local development; optional Redis shared session history and cross-worker serialization.
- **Inference:** tenant-fair **per-process** queue/scheduler with Ollama adapter.
- **Retrieval:** revision-aware per-process evidence cache.

WordPress/Purr Assistant, container infrastructure, and product-specific UI are not bundled.

## Local development (PowerShell, Python 3.14+)

```powershell
python -m pip install -e ".[dev]"
python -m pytest
$env:PURR_CLIENTS_JSON = '[{"token":"local-development-token-12345","tenant_id":"dev","products":["demo"]}]'
$env:PURR_SESSION_SIGNING_KEY = "local-only-replace-with-32-plus-random-bytes"
python -m purrfect
```

Create an authenticated session before either chat endpoint:

```powershell
$headers = @{ Authorization = "Bearer local-development-token-12345" }
$session = Invoke-RestMethod http://127.0.0.1:8765/v1/sessions -Method Post -Headers $headers
$headers["X-Purr-Session"] = $session.session_token
$body = @{ message = "Hi!" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/v1/chat -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

The Gateway also supports POST `/v1/chat/stream` with SSE events `delta`, `done`, and `error`. Native Ollama chunks are passed through without waiting for a complete answer.

## Redis shared session coordination (optional)

Install `python -m pip install -e ".[redis]"` when not using the development extras. Set `PURR_REDIS_URL` to enable shared sessions instead of SQLite; startup fails if Redis cannot be reached (no silent fallback).

```powershell
$env:PURR_REDIS_URL = "redis://127.0.0.1:6379/0"
$env:PURR_REDIS_NAMESPACE = "purr"
$env:PURR_SESSION_IDLE_TTL = "604800"
$env:PURR_SESSION_LEASE_SECONDS = "30"
$env:PURR_SESSION_WAIT_SECONDS = "5"
python -m purrfect
```

When enabled, all instances must share the same Redis instance, namespace, and session ticket signing keys. Redis stores a bounded per-tenant/per-session history, expires inactive sessions after `PURR_SESSION_IDLE_TTL` seconds, and serializes requests on a session across workers. A renewable per-session lease lets only its current owner write the final turn: an expired or superseded lease **cannot commit** stale answers. If a session is busy beyond `PURR_SESSION_WAIT_SECONDS`, Purr returns HTTP 503 (stream clients receive a terminal `error` event after headers). Broken Redis access fails the request instead of falling back to isolated state.

**Important limitations:** This is a single-Redis-primary lease model and not distributed consensus across asynchronous Redis failovers. It does not guarantee exactly-once replies or inference cancellation at a remote model. The inference scheduler is **still per-process**; do not run multiple inference-capable Gateway workers against one constrained model until global inference admission is added. Multi-worker load tests, Redis failover recovery, credential and visitor identity integration, request idempotency, and production secret management remain required.

The Redis integration tests run against a dedicated Redis test service in GitHub CI. For local integration tests, run a disposable Redis instance, set `PURR_TEST_REDIS_URL` to its isolated database, and run `python -m pytest`. Tests flush that test database.

## Other configuration

- `PURR_CLIENTS_JSON` — trusted static development client credentials with optional expiry/disable controls.
- `PURR_SESSION_SIGNING_KEY`, `PURR_SESSION_PREVIOUS_KEYS`, `PURR_SESSION_TTL` — signing key and rollover settings.
- `PURR_SESSION_DB` — SQLite path when Redis is disabled; blank for bounded memory only.
- `PURR_MODEL_BACKEND` — deterministic or ollama.
- `PURR_OLLAMA_URL`, `PURR_OLLAMA_MODEL`, `PURR_SOPHIA_DB`.
- `PURR_INFERENCE_CONCURRENCY`, `PURR_QUEUE_LIMIT`, `PURR_TENANT_QUEUE_LIMIT`, `PURR_QUEUE_TIMEOUT`, `PURR_RETRIEVAL_CACHE_SIZE`.
- `PURR_HISTORY_LIMIT`, `PURR_HOST`, `PURR_PORT`.

The production authentication provider is not chosen. Client credentials authenticate the Assistant backend, but anonymous visitor identity and binding to its session ticket remain the Assistant backend's responsibility. There is no per-ticket revocation or centralized client-credential management. Redis does not make this a production-ready multi-node AI service on its own.
