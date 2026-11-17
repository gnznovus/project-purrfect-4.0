# Purr — standalone AI provider

Purr is an independent Python API for natural conversation and approved product guidance from Sophia. This repository contains **no WordPress plugin, Purr Assistant UI, or Docker deployment**.

## Run locally

Python 3.14+ required.

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m purrfect
```

The default provider binds `127.0.0.1:8765` and runs in deterministic mode without an LLM. For an Ollama-backed POC, set `PURR_MODEL_BACKEND=ollama` and install `llama3.2:3b` in your local Ollama server. Configure `PURR_OLLAMA_MODEL`, `PURR_OLLAMA_URL`, and `PURR_SOPHIA_DB` as needed. No automatic model download is performed.

```bash
curl -H "Content-Type: application/json" -d '{"session_id":"demo","message":"Hi!"}' http://127.0.0.1:8765/v1/chat
```

For product guidance, include both `product_id` and `product_version`. Purr reads only trusted, approved knowledge in the Sophia database; it will not invent an answer when no relevant evidence exists.

```json
{"session_id":"demo","message":"How do I install it?","product_id":"my-product","product_version":"1.0.0"}
```

Sophia knowledge is published via the trusted local operator command:

```bash
python -m purrfect.sophira_admin approved-package.json --database ./sophia.db --approved
```

Set `PURR_SOPHIA_DB=./sophia.db` before starting Purr. `--approved` is an operator assertion, not an authenticated approval workflow.

## API
- `GET /v1/health`
- `POST /v1/chat`: JSON with `session_id`, `message` and optional product identity; returns `message`, `status`, `sources`, `session_id`

Environment: `PURR_HOST`, `PURR_PORT`, `PURR_API_TOKEN`, `PURR_MODEL_BACKEND`, `PURR_OLLAMA_URL`, `PURR_OLLAMA_MODEL`, `PURR_SOPHIA_DB`.

Outside loopback, `PURR_API_TOKEN` is mandatory. **Do not expose this POC directly to the internet**: TLS, tenant/product entitlements, hardened authentication, request budgets, and operational safeguards are still pending.

Product-source isolation, conversation and inference interfaces are independent of any frontend client.
