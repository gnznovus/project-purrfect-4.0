# Purr Operations Console — V2.9

This is a separate **operator-only webapp**, not an extension of Purr Core and not a public client widget.

## Single-command supervisor (Windows development only)

After a new checkout, run `purrfect.init` (or `.\\purrfect.init.cmd`) once. It creates the project's Python 3.14 `.venv`, installs dev dependencies and initializes the private `.env`. Running it again does **not** rotate or overwrite secrets.

Daily commands:

```powershell
.\\purrfect.start.cmd
.\\purrfect.status.cmd
.\\purrfect.restart.cmd
.\\purrfect.stop.cmd
```

`start` detaches a supervisor which owns the local Gateway and Console child processes and writes local logs under `.purrfect/`. You may close the terminal afterward; use `stop` for clean shutdown. The supervisor never kills unrelated port occupants.

Set `PURR_ENV=production` in the actual process environment or `.env` to disable development initialization and supervisor commands. Production process management and credentials are handled separately. The Windows supervisor does not install or start Ollama or Redis, and health readiness currently checks local listener ports, not authenticated application probes.

## Windows quick start (PowerShell)

From the repository root, run `.\\setup-local.ps1` once. This uses `py -3.14` to create a project-local virtual environment, installs dependencies, then initializes `.env` only when missing. It never overwrites existing credentials.

Run `.\\start-gateway.ps1` and `.\\start-console.ps1` in **separate terminals**. Both call their own project-local Python directly; no virtual environment activation or PowerShell environment variables are needed. The Console is available at `http://127.0.0.1:8775`.

If PowerShell execution policy blocks local scripts, use `.\\.venv\\Scripts\\python.exe -m purrfect` and `.\\.venv\\Scripts\\python.exe -m purrfect.operations` directly (in separate terminals). Neither requires activation.

## Preferred setup — Git-ignored .env

From the repository checkout, initialize the project once:

```powershell
python -m pip install -e ".[dev]"
python -m purrfect.config init
```

The initializer writes a private `.env` containing matching Gateway client and Console service credentials, distinct monitoring and operator secrets, and default local ports. It **never overwrites an existing `.env`**. If an older `config/local.json` exists, initialization migrates its original values without rotating secrets. After verifying the new `.env`, remove the old JSON file manually. The Git-tracked `.env.example` contains only placeholders.

Then launch the two services from the repository in separate terminals:

```powershell
python -m purrfect
python -m purrfect.operations
```

Open `http://127.0.0.1:8775`. The Console login token is `PURR_OPERATIONS_TOKEN` from `.env`. Editing `.env` is enough to update settings for the next process start; **restart the affected service after edits**. Process environment variables can override the file for deployment, but are not needed in local PowerShell.

## Manual environment-based launch (optional)

Start Purr Gateway separately (`python -m purrfect`) with `PURR_CLIENTS_JSON` and `PURR_SESSION_SIGNING_KEY`. For live inference, configure `PURR_MODEL_BACKEND=ollama` and `PURR_OLLAMA_URL`/model as appropriate. For operational telemetry, configure `PURR_METRICS_TOKEN` on the Gateway.

On the Console process (Python 3.14+):

```powershell
$env:PURR_OPERATIONS_TOKEN = "replace-with-random-32-plus-character-operator-secret"
$env:PURR_OPERATIONS_GATEWAY_TOKEN = "local-development-token-12345"
$env:PURR_OPERATIONS_METRICS_TOKEN = "your-separate-gateway-monitoring-secret"
$env:PURR_OPERATIONS_GATEWAY_URL = "http://127.0.0.1:8765"
$env:PURR_OPERATIONS_MODEL_LABEL = "llama3.2:3b / local"
python -m purrfect.operations
```

Open `http://127.0.0.1:8775` and supply `PURR_OPERATIONS_TOKEN` in the login overlay. The token remains in browser runtime memory (a tab refresh requires re-entry) and is only submitted in Authorization headers. **Do not expose the Console directly to the internet.** The default host is loopback; remote binding requires `PURR_OPERATIONS_ALLOW_REMOTE=1`, TLS reverse proxy, and additional ingress access control.

## Pages

- **Overview:** Gateway health probe, latest P95/success rate, run trend and process-local Prometheus operation breakdown.
- **Benchmark Lab:** Fixed test profiles, 1–8 requests, 1–3 concurrent requests, one experiment at a time. Each sample uses a fresh authenticated Gateway session. Measures HTTP chat completion latency and saves only status/timing metadata; output text is deliberately discarded.
- **Run History:** SQLite-persisted run summaries, sample statuses and latencies, percentile comparisons across experiments. In-progress runs are marked interrupted after restart.
- **Reliability:** Non-destructive Gateway and metrics reachability diagnostics, plus known infrastructure limitations.

Tests call the **configured Gateway origin only** (no user-provided target URLs). Product-specific test content, model switching and prompt customization are not available in this foundation. To compare model configurations, change the Gateway's model, update `PURR_OPERATIONS_MODEL_LABEL`, run another benchmark, and compare saved histories. The model label is operator-supplied, not cryptographically verified from the inference backend.

## Configuration

- `PURR_OPERATIONS_TOKEN` — required, independent operator access secret, 32+ chars.
- `PURR_OPERATIONS_GATEWAY_TOKEN` — required server-side Gateway tenant application credential; **never supplied to the browser**.
- `PURR_OPERATIONS_METRICS_TOKEN` — optional Gateway monitoring secret; must correspond to Gateway `PURR_METRICS_TOKEN`.
- `PURR_OPERATIONS_GATEWAY_URL` — fixed trusted Gateway origin (default `http://127.0.0.1:8765`).
- `PURR_OPERATIONS_MODEL_LABEL` — human-provided backend configuration label.
- `PURR_OPERATIONS_DB` — SQLite report DB path (default `./purr-operations.db`).
- `PURR_OPERATIONS_HOST` — defaults to `127.0.0.1`.
- `PURR_OPERATIONS_PORT` — defaults to `8775`.

## Security & limitations

The Console is a **single-process** service for controlled engineering use. Its synchronous-request benchmark is an awaited HTTP operation; it does not enqueue unattended background jobs and does not survive an interrupted HTTP request. At most one experiment is processed at a time in each process; deploy one Console instance only. Samples are sent to the configured Gateway using a private service credential. The Gateway's own tenant queues/global admission limits still apply.

This is a measurement foundation, not a calibrated hardware benchmark. The saved P50/P95 are interpolated percentiles of **successful** HTTP chat completion latencies; no token-per-second measurement, cold-start separation, model identification, distributed traces or calibrated model performance isolation is claimed. With only a handful of samples, P95 is exploratory rather than statistically stable.

Metrics reflect only the configured Gateway instance and cannot substitute for multi-worker aggregation. Monitoring endpoints should be shielded at the network layer. This Console is **not** a user IAM system: rotate secrets through deployments, and use external authentication/access controls for a production operator plane. No arbitrary HTTP targets, code execution, Redis fault injection, or destructive controls are exposed.
