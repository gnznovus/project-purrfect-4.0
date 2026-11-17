# Purr — Gateway / Core boundary

Purr is a multi-tenant, independently callable AI provider for natural conversation and Sophia-approved product guidance. The API Gateway evolves with consumers, while Purr Core remains independent of FastAPI, Pydantic, and transport protocols.

## Architecture

- `purrfect.gateway` — public FastAPI v1 API, schemas, credential authentication, tenant grants, error mapping.
- `purrfect.core` — framework-independent conversation and product RAG, verified tenant context, tenant-isolated sessions.
- `purrfect.infrastructure.scheduler` — bounded, cancellation-aware, per-tenant round-robin model scheduling (single process).
- `purrfect.infrastructure.cache` — bounded, checksum/revision-aware, tenant-isolated retrieval result cache (single process).
- `purrfect.infrastructure.runtime` — composition root and runtime selection.
- `purrfect.ollama` — optional inference adapter.
- `purrfect.sophira*` — trusted local Sophia knowledge package and SQLite storage.

No WordPress, Purr Assistant, Docker, Redis, or microservice networking is included. Logical components initially share a single Python process.

## Local development (Python 3.14+)

```powershell
python -m pip install -e ".[dev]"
python -m pytest
$env:PURR_CLIENTS_JSON = '[{"token":"local-development-token-12345","tenant_id":"dev","products":["demo"]}]'
python -m purrfect
```

`PURR_CLIENTS_JSON` is mandatory, even locally. Tokens are trusted server-side credentials; do **not** embed them in public browser JavaScript. An Assistant client should call Purr through its own server-side proxy. Use a real secret in deployed environments, configure TLS, and do not expose this prototype directly to the internet.

```powershell
$headers = @{ Authorization = "Bearer local-development-token-12345" }
$body = @{ session_id = "demo"; message = "Hi!" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/v1/chat -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

## Product RAG

Sophia packages must be namespaced by tenant. For tenant `dev` and public product `demo`, the approved package's `product_id` must be **`dev/demo`**. Only credentials granting `demo` may query it.

```json
{"session_id":"demo","message":"How do I install?","product_id":"demo","product_version":"1.0.0"}
```

To publish a checksum-validated package, use the existing trusted operator CLI:

```powershell
python -m purrfect.sophira_admin approved-package.json --database ./sophia.db --approved
$env:PURR_SOPHIA_DB = "./sophia.db"
```

Knowledge approval via `--approved` is an operator assertion, not an authenticated approval workflow. The public API has no knowledge publication route.

## Scheduling and caching

Only requests that actually invoke a model enter the inference scheduler. Deterministic greetings and knowledge-gap responses bypass it. The scheduler limits simultaneous inferences, total pending requests, and waiting requests per tenant. Waiting jobs are selected in tenant round-robin order. Queue saturation returns 429; waiting timeout returns 503. Cancellation releases queue permits. All scheduling is **in-process**, not distributed or durable.

Retrieval results are cached with tenant, product, package version, approved package digest (including revision), and normalized query as a key. Revising Sophia knowledge changes the digest and causes a fresh retrieval. Cached values are approved evidence only, never user-specific sessions or generated output. The bounded cache uses in-process LRU eviction. The Sophia catalog is still consulted on each product question to detect revisions.

Environment settings:
- `PURR_CLIENTS_JSON` — trusted local client credentials and product grants.
- `PURR_MODEL_BACKEND` — `deterministic` (default) or `ollama`.
- `PURR_OLLAMA_MODEL`, `PURR_OLLAMA_URL`, `PURR_SOPHIA_DB`.
- `PURR_HOST`, `PURR_PORT`.
- `PURR_INFERENCE_CONCURRENCY` (default 1), `PURR_QUEUE_LIMIT` (default 4).
- `PURR_TENANT_QUEUE_LIMIT` (default 2), `PURR_QUEUE_TIMEOUT` (default 5 seconds).
- `PURR_RETRIEVAL_CACHE_SIZE` (default 512 entries).

## Public API

- `GET /v1/health` (authenticated).
- `POST /v1/chat` (authenticated): `session_id`, `message`, optional paired `product_id` / `product_version`. Response: `session_id`, `status`, `message`, `sources`.
- `GET /docs` — generated API documentation.

## Known limitations

This is an architectural POC, not a production-ready multi-tenant service. Tenant grants come from static trusted credentials, not an identity provider. Sessions, inference queues, and caches are in-memory and per-process; no durable queue, cross-process fairness, credential revocation, streaming, or user-based rate limits yet. Retrieval is lexical, not semantic. Inference backend resilience and latency are unbenchmarked. Tenant namespacing must also be enforced by the external Sophia publisher. Start with one process; do not scale API workers without a shared state and scheduling design.
