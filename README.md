# Purr — independent Gateway and Core

Purr is a shared, multi-tenant AI provider for natural conversation and Sophia-approved product guidance. Gateway owns evolving authentication and public contracts; Core remains independent of HTTP frameworks.

## Architecture

- `purrfect.gateway` — FastAPI v1 API, pluggable `ClientVerifier` boundary, trusted session credentials, JSON/SSE.
- `purrfect.core` — framework-independent product guidance, conversation and streaming.
- `purrfect.infrastructure.scheduler` — tenant-fair, cancelable per-process inference admission.
- `purrfect.infrastructure.cache` — revision-aware tenant-scoped retrieval evidence caching.
- `purrfect.infrastructure.sessions` — memory/SQLite state; tenant-isolated.
- `purrfect.ollama` — native incremental inference.
- `purrfect.sophira*` — approved knowledge.

The project does not bundle WordPress, the Assistant UI, Docker, or a production identity provider.

## Local development — PowerShell, Python 3.14+

```powershell
python -m pip install -e ".[dev]"
python -m pytest
$env:PURR_CLIENTS_JSON = '[{"token":"local-development-token-12345","tenant_id":"dev","products":["demo"]}]'
$env:PURR_SESSION_SIGNING_KEY = "local-only-replace-with-32-plus-random-bytes"
python -m purrfect
```

### Application credential lifecycle (development implementation)

The Gateway authenticates an Assistant backend (tenant application identity) using a replaceable `ClientVerifier`. The bundled `CredentialRegistry` is static configuration **for development**, not an issuer or external identity provider. Configured secrets are hashed in memory and compared using constant-time digests.

The server-side `PURR_CLIENTS_JSON` configuration supports `token`, `tenant_id`, `products`, and optional `not_before`, `expires_at` (Unix seconds) and `disabled`. Multiple distinct credentials can be active for the same tenant to allow overlap during rotation:

```json
[
  {"token":"old-private-key-at-least-16","tenant_id":"hotel","products":["booking"]},
  {"token":"new-private-key-at-least-16","tenant_id":"hotel","products":["booking"]}
]
```

Deploy a configuration with both keys; migrate the caller; then deploy a configuration with the old key `disabled` or removed. This needs a process reload/restart: **there is no online management endpoint or immediate centralized revocation**. `not_before` and `expires_at` are verified for every request, but the list of credentials remains a static snapshot. Do not place any application secret in a browser, public repository, URL, or telemetry.

The Gateway can instead receive an external OAuth/OIDC verifier or other client-identity provider adapter via `create_app(core, verifier, tickets)`. That adapter must independently validate issuer, audience, signature, expiry, tenant binding and product grants as applicable. **No concrete external verifier is implemented or chosen yet.** Core only sees normalized tenant grants.

### Session credentials and signing key rollover

The Assistant backend authenticates with its application credential and calls `POST /v1/sessions`. The Gateway returns `session_id`, `session_token` and `expires_at`; chat calls then require the tenant credential and `X-Purr-Session` header. Client-supplied `session_id` must match the signed ticket if present. This ticket establishes *anonymous session possession*, not verified end-user identity.

```powershell
$headers = @{ Authorization = "Bearer local-development-token-12345" }
$session = Invoke-RestMethod http://127.0.0.1:8765/v1/sessions -Method Post -Headers $headers
$headers["X-Purr-Session"] = $session.session_token
$body = @{ message = "Hi!" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/v1/chat -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

Use `PURR_SESSION_SIGNING_KEY` for **new tickets**. Optional `PURR_SESSION_PREVIOUS_KEYS` is a JSON array of earlier signing keys still accepted for verification. Key-rollover sequence: deploy new primary with old key listed as previous; let Assistant clients obtain new tickets; after old tickets expire, remove the previous key. Removing a previous key rejects its outstanding tickets immediately at that process. Maximum three previous keys; all signing keys require at least 32 UTF-8 bytes. Protect signing keys in your secrets manager and configure the same keys on all participating Gateway instances. The Gateway does not have per-ticket revocation or refresh yet.

## API

- `GET /v1/health` — authenticated.
- `POST /v1/sessions` — authenticated session issuance.
- `POST /v1/chat` — authenticated chat, signed session ticket required.
- `POST /v1/chat/stream` — authenticated POST SSE with `delta`, `done`, and terminal `error` events.

Product packages are tenant namespaced in Sophia as `tenant_id/product_id` (for example `dev/demo`). Only approved knowledge is used.

## Environment

- `PURR_CLIENTS_JSON`: required static development client credential list.
- `PURR_SESSION_SIGNING_KEY`: required new-ticket signing key.
- `PURR_SESSION_PREVIOUS_KEYS`: JSON list of accepted old keys; default `[]`.
- `PURR_SESSION_TTL`: ticket lifetime, default 86400 seconds.
- `PURR_MODEL_BACKEND`: deterministic or ollama.
- `PURR_OLLAMA_MODEL`, `PURR_OLLAMA_URL`, `PURR_SOPHIA_DB`, `PURR_SESSION_DB`, `PURR_HISTORY_LIMIT`, `PURR_INFERENCE_CONCURRENCY`, `PURR_QUEUE_LIMIT`, `PURR_TENANT_QUEUE_LIMIT`, `PURR_QUEUE_TIMEOUT`, `PURR_RETRIEVAL_CACHE_SIZE`, `PURR_HOST`, `PURR_PORT`.

## Remaining production gaps

This remains a **development foundation**. Identity verification is replaceable but a real external identity source is not connected. Client grants and revocation changes require process reload. Anonymous visitors remain the Assistant backend's responsibility; Gateway possession tickets alone cannot authenticate a human. No per-session revocation, streaming replay, multi-worker coordinated session locking, shared distributed queue, global rate limiting, or retention cleanup. SQLite is single-host state and inference efficiency is unbenchmarked. Keep a single API process until coordinated deployment is validated.
