# Purr — Gateway / Core boundary

Purr is a multi-tenant, independently callable AI provider for natural conversation and Sophia-approved product guidance. The API Gateway evolves with consumers, while Purr Core remains independent of FastAPI, Pydantic, and transport protocols.

## Architecture

- `purrfect.gateway` — public FastAPI v1 API, request schemas, credential authentication, tenant grants, bounded per-process admission.
- `purrfect.core` — framework-independent conversation and product RAG, verified tenant context, tenant-isolated sessions.
- `purrfect.infrastructure` — composition root and runtime selection.
- `purrfect.ollama` — optional inference adapter.
- `purrfect.sophira*` — trusted local Sophia knowledge package and SQLite storage.

No WordPress, Purr Assistant, Docker, Redis, or microservice networking is included. These are separate logical layers in one Python process. Runtime distribution and shared scheduling are future tasks.

## Local development (Python 3.14+)

```powershell
python -m pip install -e ".[dev]"
python -m pytest
$env:PURR_CLIENTS_JSON = '[{"token":"local-development-token-12345","tenant_id":"dev","products":["demo"]}]'
python -m purrfect
```

`PURR_CLIENTS_JSON` is mandatory, even locally. Tokens are trusted server-side credentials; do **not** embed them in public browser JavaScript. A WordPress client must call Purr through its own server-side proxy. Use a real secret in deployed environments, configure TLS, and do not expose this prototype directly to the internet.

```powershell
$headers = @{ Authorization = "Bearer local-development-token-12345" }
$body = @{ session_id = "demo"; message = "Hi!" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/v1/chat -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

## Product RAG

Product knowledge is namespace-scoped to each tenant in Sophia. For tenant `dev` and public product `demo`, the approved package's `product_id` must be **`dev/demo`**. Only credentials granting `demo` may query it.

```json
{"session_id":"demo","message":"How do I install?","product_id":"demo","product_version":"1.0.0"}
```

To publish a checksum-validated package, use the existing trusted operator CLI:

```powershell
python -m purrfect.sophira_admin approved-package.json --database ./sophia.db --approved
$env:PURR_SOPHIA_DB = "./sophia.db"
```

Knowledge approval via `--approved` is an operator assertion, not an authenticated approval workflow. The public API has no knowledge publication route.

## Public API

- `GET /v1/health` (authenticated)
- `POST /v1/chat` (authenticated): `session_id`, `message`, optional paired `product_id` / `product_version`. Response: `session_id`, `status`, `message`, `sources`.
- `GET /docs` — generated API documentation.

Environment: `PURR_CLIENTS_JSON`, `PURR_MODEL_BACKEND` (deterministic or ollama), `PURR_OLLAMA_MODEL`, `PURR_OLLAMA_URL`, `PURR_SOPHIA_DB`, `PURR_HOST`, `PURR_PORT`, `PURR_INFERENCE_CONCURRENCY`, `PURR_QUEUE_LIMIT`.

## Known limitations

This is a boundary POC, not a production-ready multi-tenant service. Tenant grants come from static trusted credentials, not an identity provider. Sessions and inference admission are in-memory and per-process; no durable queue, cross-process fairness, revocation, per-tenant rate limits, or streaming yet. Core retrieval is lexical, not semantic. Inference backend resilience and latency are unbenchmarked. Tenant namespacing must also be enforced by the external Sophia publisher. Start with one gateway process.
