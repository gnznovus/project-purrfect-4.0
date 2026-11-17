# Purr — independent Gateway and Core

Purr is a shared, multi-tenant AI provider for natural conversation and Sophia-approved product guidance. The Gateway owns evolving external contracts; Core stays independent of web-framework logic.

## Architecture

- `purrfect.gateway` — FastAPI v1 contracts, verified app credentials, tenant-scoped session tickets, JSON and SSE.
- `purrfect.core` — framework-independent conversation, retrieval, and response streaming.
- `purrfect.infrastructure.scheduler` — tenant-fair cancelable, in-process inference scheduling.
- `purrfect.infrastructure.cache` — bounded, revision-aware, tenant-isolated evidence cache.
- `purrfect.infrastructure.sessions` — interchangeable memory and SQLite conversation stores.
- `purrfect.ollama` — native incremental inference stream.
- `purrfect.sophira*` — approved revisioned knowledge.

No WordPress plugin, Purr Assistant, Docker, Redis, or microservice networking is bundled.

## Local development — PowerShell, Python 3.14+

```powershell
python -m pip install -e ".[dev]"
python -m pytest
$env:PURR_CLIENTS_JSON = '[{"token":"local-development-token-12345","tenant_id":"dev","products":["demo"]}]'
$env:PURR_SESSION_SIGNING_KEY = "local-only-replace-with-32-plus-random-bytes"
python -m purrfect
```

### Gateway-issued conversation sessions

The Assistant backend authenticates with its server-side credential, then issues a session ticket for a visitor. This is an opaque-to-clients, HMAC-signed bearer credential, not a decision to adopt JWT or any particular identity provider.

1. **Create**: `POST /v1/sessions` with tenant client Bearer token (no body). Returns `session_id`, `session_token`, `expires_at` (Unix seconds).
2. **Chat**: `POST /v1/chat` or `POST /v1/chat/stream` with tenant Bearer token AND `X-Purr-Session: <session_token>`.
3. Gateway verifies signature, expiry and tenant match; Core receives only the resulting session ID and verified tenant context. An optional JSON `session_id` must match the ticket, otherwise 403.
4. Store session credentials securely in the Assistant backend's visitor session store. Never put the tenant application key or its session ticket in public URLs, logs, analytics, or public browser JavaScript.
5. On expiry, the Assistant backend creates a **new session**. The old history remains in SQLite until retention cleanup (not implemented); automatic transfer/resume of expired tickets is intentionally not permitted.

```powershell
$headers = @{ Authorization = "Bearer local-development-token-12345" }
$session = Invoke-RestMethod http://127.0.0.1:8765/v1/sessions -Method Post -Headers $headers
$headers["X-Purr-Session"] = $session.session_token
$body = @{ message = "Hi!" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/v1/chat -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

The stream endpoint uses POST SSE; it emits `delta`, `done`, or terminal `error` events. The Ollama adapter yields real incremental model chunks. The session ticket is verified **before** streaming headers are sent.

### Security boundary

These tickets prove **possession of an issued anonymous session**, not verified end-user identity. A trusted tenant backend can mint multiple visitor sessions, but must keep the correct ticket bound to each visitor and must implement visitor authentication/session security itself. Anyone obtaining both the tenant credential and session ticket can replay the session until expiry. Stolen tickets are not individually revocable in this prototype; rotating `PURR_SESSION_SIGNING_KEY` invalidates all previously issued tickets. Production plans still require user identity integration, secure credential storage and rotation, rate limits, and revocation.

## Sophia product knowledge

Publish approved packages as `tenant_id/product_id` (for example `dev/demo`) using the existing Sophia operator CLI. Set `PURR_SOPHIA_DB` to its SQLite path. The gateway enforces product grants and Core always scopes retrieval to the verified tenant.

## Environment

- `PURR_CLIENTS_JSON`: required trusted client Bearer credentials.
- `PURR_SESSION_SIGNING_KEY`: required signing key (at least 32 bytes; use a cryptographically random secret).
- `PURR_SESSION_TTL`: ticket lifetime in seconds (60–604800; default 86400).
- `PURR_MODEL_BACKEND`: deterministic (default) or ollama.
- `PURR_OLLAMA_MODEL`, `PURR_OLLAMA_URL`, `PURR_SOPHIA_DB`.
- `PURR_SESSION_DB`: SQLite history path (default `./purr-sessions.db`; blank for memory).
- `PURR_HISTORY_LIMIT`: turns retained per session, default 6.
- `PURR_INFERENCE_CONCURRENCY`, `PURR_QUEUE_LIMIT`, `PURR_TENANT_QUEUE_LIMIT`, `PURR_QUEUE_TIMEOUT`, `PURR_RETRIEVAL_CACHE_SIZE`, `PURR_HOST`, `PURR_PORT`.

## Production gaps

This is still a **development foundation**, not a production-ready identity system. Real visitor identity or external user-token verification is not implemented; session ownership is possession-based only. Session credentials are portable across processes sharing the same signing key, but in-process locks and schedulers are not distributed; SQLite storage does not coordinate cross-host concurrency. There is no ticket revocation list, ticket refresh/rebinding, global quota, configurable per-user identity assertion, credential rotation API, durable idempotency, or stream replay. Session rows require retention controls. Keep a single API process until these are addressed.
