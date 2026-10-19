# Purr pairing backend — first API slice

This is an independent FastAPI boundary for trusted, durable registration of
WordPress Purr Assistant installations. It does **not** replace the lab's
existing local chat API yet. No production authentication or TLS proxy is
configured by this source branch.

## Run locally (Python 3.14)

From the Purrfect repo on branch `feat/standalone-assistant-identity`:

```powershell
python -m pip install -e ".[dev]"
$env:PURR_PAIRING_DB_PATH = ".\purr-pairing.sqlite"
python -m uvicorn purrfect.pairing_api:app --host 127.0.0.1 --port 8766
```

Use an HTTPS reverse proxy with restrictive network access before exposing
the pairing service beyond loopback. Never forward it to the public Internet
without TLS, abuse protections, and operational hardening.

## Issue an operator-controlled pairing code

In a second terminal with the same `PURR_PAIRING_DB_PATH`:

```powershell
python -m purrfect.pairing_admin issue-code
```

The code is a 256-bit randomly generated, one-use invitation, expires after
10 minutes, and is stored only as a hash. Treat it as a sensitive secret.

## HTTP contract

POST `/v1/assistants/pair` with JSON:

```json
{
  "code": "operator-issued-one-time-code",
  "assistant_id": "YOUR-UUIDV7",
  "site_id": "SEPARATE-SITE-UUIDV7",
  "site_url": "https://your-wordpress.example"
}
```

On success (HTTP 201), the server returns an `assistant_id`, `site_id`,
`status=paired`, and a **one-time credential**. The credential is stored on
Purr only as a SHA-256 digest. The WordPress plugin will later store the
one-time returned credential in server-side protected options, not browser JS.

GET `/v1/assistants/me` with headers:

```text
X-Purr-Assistant-ID: YOUR-UUIDV7
Authorization: Bearer YOUR-ONE-TIME-CREDENTIAL
```

The server derives tenant identity from the verified credential, not an
arbitrary site ID supplied by the caller. Duplicate Assistant or Site UUIDs
are rejected. A revoked Assistant is denied.

Trusted operator revocation:

```powershell
python -m purrfect.pairing_admin revoke --assistant-id YOUR-UUIDV7
```

## Acceptance boundaries

- The plugin currently generates an Assistant UUIDv7 but **not yet** a Site
  UUIDv7 or credentials. Its Pair button remains disabled.
- No WordPress pairing client wiring is implemented yet.
- The existing `/v1/chat` and `/v1/knowledge/sync` are still lab-oriented,
  **not** protected by this new registry. Do not expose them to the Internet.
- Pending work: pairing controls in WordPress, HTTPS reverse proxy, certificate
  verification, secret rotation/recovery, rate limiting, clone detection,
  authenticated multi-tenant chat/knowledge access, and full end-to-end tests.

Run targeted tests with:

```powershell
python -m pytest tests/test_pairing.py -q
```
