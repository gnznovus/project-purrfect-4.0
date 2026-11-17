# Railway staging — Purr Gateway and Operations API

This is a **controlled infrastructure staging deployment**, not a public beta or production authorization system. The existing Windows `purrfect` development CLI does not run in Railway.

## Architecture and scope

- **Railway Gateway**: Python 3.14 / FastAPI, deterministic inference, authenticated tenant APIs. Public Railway-generated HTTPS domain may be enabled for controlled tests. Health check `GET /healthz` is unauthenticated, reports only `{"status":"ok"}`; existing `/v1/health` and all session/chat routes remain protected.
- **Railway Operations**: separate service from the same repo/image, private networking **only** for now. Its APIs still use an operator Bearer token with no username/password sessions. **Do not create a public Railway domain for Operations**, and do not expose it from the Plesk dashboard until real hosted authentication or a restricted same-origin API proxy is implemented.
- **Plesk React dashboard**: a future milestone. The existing bundled Console HTML/JS remains available for local development. This PR does not silently expose it or replace it with React.
- **Storage**: one Railway volume `/data` attached to Operations for SQLite history. Gateway can use in-memory sessions for the first staging test. Redis and external Ollama are deferred.

Railway documents one persistent volume per Free project, so the plan deliberately uses **one volume attached to Operations only**. Gateway sessions will not survive a Gateway restart in this first deployment; signed session tickets are still verified, but conversational history is not durable. If persistence is required for both, move to Redis/external DB or a plan supporting more volumes.

## 1. Create Railway services

1. Link this GitHub repository to a Railway project.
2. Add **two services**, both using the repository root and Dockerfile:
   - `Purr Gateway`: config-as-code path `/deploy/railway.gateway.json`
   - `Purr Operations`: config-as-code path `/deploy/railway.operations.json`
3. Create a persistent **volume on Operations**, mount at `/data`; ensure the mount is writable by the container's UID **10001** (adjust deployment UID/volume permissions if needed).
4. Set `PORT=8080` for **both services**. Config files choose separate start commands; each container listens on `0.0.0.0:$PORT`.
5. Enable a Railway public HTTPS domain on **Gateway only**. Keep Operations reachable solely via Railway private networking.

The Railway config files are explicit because their startup commands differ. Do not use the Windows `purrfect start` supervisor in containers.

## 2. Set Railway variables (separately per service)

Use Railway's **Variables** tab; do not upload or copy your local `.env`. Generate fresh cryptographic secrets in a trusted environment and store only in the Railway service variables.

Gateway:

```dotenv
PURR_ENV=production
PORT=8080
PURR_MODEL_BACKEND=deterministic
PURR_SESSION_DB=
PURR_CLIENTS_JSON=[{"token":"<unique-random-32+-character-token>","tenant_id":"staging","products":["demo"]}]
PURR_SESSION_SIGNING_KEY=<independent-random-64-character-secret>
PURR_METRICS_TOKEN=<independent-random-64-character-secret>
```

Operations (private):

```dotenv
PURR_ENV=production
PORT=8080
PURR_OPERATIONS_DEV_AUTO_AUTH=0
PURR_OPERATIONS_TOKEN=<independent-random-64-character-operator-secret>
PURR_OPERATIONS_GATEWAY_TOKEN=<same-token-as-gateway-client>
PURR_OPERATIONS_METRICS_TOKEN=<same-secret-as-gateway-metrics-token>
PURR_OPERATIONS_GATEWAY_URL=http://<gateway-private-railway-domain>:8080
PURR_OPERATIONS_DB=/data/purr-operations.db
PURR_OPERATIONS_MODEL_LABEL=Staging deterministic backend
```

Use the **actual Railway Gateway private hostname**, not the example placeholder. Internal Railway service networking supports a private HTTP origin. Do not insert `https://` if the chosen private origin is plain HTTP. The Operations service uses server-side credentials; they must **never** be embedded in React assets or browser JavaScript.

Credentials must match as shown. Never commit actual values to Git or put them in build args.

## 3. Smoke tests

After Railway reports deployment healthy:

- Gateway: `GET https://<gateway-domain>/healthz` returns `200 {"status":"ok"}`.
- Gateway: `GET /v1/health` **without** authorization returns **401**. With a valid Gateway tenant Bearer token returns 200.
- Gateway: create session via `POST /v1/sessions` with the tenant Bearer token, then `POST /v1/chat` with both tenant Bearer and issued `X-Purr-Session`. This first test runs deterministic inference; **do not interpret latency as real AI performance**.
- Operations: Railway deployment health status should be healthy via `/healthz` even though the service has **no public domain**. Verify its private-to-private Gateway URL through internal service logs/diagnostics after configuring a safe access method. Do **not** publicly expose Operations merely to test the UI.
- Perform a controlled Operations restart/redeploy and verify that the SQLite DB on `/data` survives. A mounted Railway volume is required; without it benchmark history will be lost.

## Security and readiness limits

- No anonymous public Console login, no production auto-login, no browser bearer secret, no frontend CORS-based workaround.
- A public Gateway domain still requires rate limits, abuse monitoring, a trusted server-side application client, and a proper visitor/session identity integration before accepting unrestricted users. **Never place `PURR_CLIENTS_JSON` credentials in frontend code**.
- `/healthz` is *liveness only*. It does not certify model availability, Gateway authentication, Redis, Operations-to-Gateway reachability, or storage durability.
- The operation runner is single-instance and benchmarks aren't distributed; no Redis failover, credential rotation, or real-model benchmark claims.
- Railway may briefly interrupt service redeployment when a volume is attached. Monitor resource/cost usage, particularly on Free.
- If a Railway volume has permission problems under UID 10001, diagnose volume ownership rather than running the application as root without review.

## Next milestone

Build the React Operations dashboard for Plesk with a **server-side protected API access layer**, or deploy an authenticated proxy; then define cross-origin session, CSRF, and operator roles explicitly. No direct public Operations backend until this boundary is implemented.
