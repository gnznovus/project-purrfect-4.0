# Project Purrfect 4.0

Python 3.14+ foundation for Purra, a product-specialized guidance system.

## Status

**Goal 1.1:** deterministic guidance contract.

**Goal 1.2:** provider-neutral objective selection using an LLM, with Ollama as the first real adapter. The LLM can select only advertised product objectives. Missing inputs, allowed options, target IDs and output structure are controlled by the product's guidance definition. Invalid model output fails closed to an unsupported response.

Not implemented: real product/RAG retrieval, diagnosis, general answer generation, Child networking, persistence, premium automation, execution, Sophira or Aurora integration. The code never executes client product actions. The examples in tests are fixed fixtures, not live product knowledge.

## Architecture direction

- **Purra:** reasoning and guided product support (primary focus).
- **Purr Child:** product-specific assistant; UUIDv7 identity planned.
- **Sophira:** future shared, human-approved knowledge repository.
- **Aurora:** separate future execution integration.

Clients interact with Child. Developers may communicate with Purra directly. No network protocol has been chosen.

## Development

Goal → Contract → Implement → Validate → Document.

Windows PowerShell using Python 3.14 directly (no virtual environment):

```powershell
py -3.14 -m pip install -e ".[dev]"
py -3.14 -m pytest
```

CI automatically installs and runs all tests for pushes and pull requests.

## Usage boundary

`PurraBrain(model).start(user_message, product_objectives)` selects an advertised `ProductObjective` by ID and returns a `GuidanceSession` with typed interactive inputs. A product integration must supply its own objective catalog and actual target options. `OllamaModel` communicates with a running local Ollama server (default model `llama3.2:3b`) but live-model testing requires that server/model; deterministic CI tests use a fake model and a mocked HTTP adapter.

Purra's output does not authorize or run commands. Developer setup/test commands run through project CI, not through the LLM.


## Goal 1.3 — Stateful conversation experiment

Two isolated adapters (`CustomConversation` and `LangGraphConversation`) use the exact same pure domain transition function in `stateful.py`. Parameterized tests compare ordered multi-turn input, target corrections, session isolation, and rejection of invalid answers. Correcting an earlier answer invalidates downstream selections.

LangGraph uses an in-memory checkpointer, not durable storage. State does **not** survive a process restart. This experiment does not test real LLM decisions, interruption/resume through external IO, performance, or production persistence. LangGraph is installed as a **development-only** dependency while we evaluate it. No production adoption decision has been made.


### Recovery comparison (experimental)

Both reference adapters optionally accept a SQLite file path and recover conversation answers after the adapter is recreated. The same parameterized tests cover resuming guidance, correcting an earlier target (clearing downstream selections), and preserving separate session IDs. The custom implementation persists JSON state; LangGraph uses `SqliteSaver` from `langgraph-checkpoint-sqlite`.

The recovered state is validated against the existing product-owned guidance contract before accepting new answers. CI passed the recovery suite on Python 3.14. SQLite is a **local experiment**, not an approved production storage choice. The tests do not simulate a crashed OS process, concurrent writers, genuine LangGraph interrupts, real LLM interaction, or network disconnection. No framework selection is finalized.


## Goal 1.4 — Adaptive decision routing

`AdaptiveGuide` coordinates the existing custom Python or LangGraph guidance adapters. The LLM returns a constrained route: continue, correct, switch objectives, or clarify. Product-provided definitions remain authoritative for valid objectives, input keys, and selectable target IDs. Earlier answers are retained on objective changes only if compatible with the new product requirements and revalidated. Switching back to an abandoned objective starts a fresh revision.

Verified by shared, parameterized tests for both backends, including valid continuations, corrections, product objective changes, ambiguous/unsupported model output, and separate client sessions.

**Current limitations:** The routing model is fake in CI; no live LLM/product integration was tested. The adaptive coordinator's objective bindings and revisions are kept in memory and are not durable across process restarts. Existing stateful adapter persistence tests remain in place, but do not establish persistence of the new coordinator. No product operation, automatic repair, knowledge retrieval, or publication is implemented. This remains isolated feature work pending broader validation.


## Goal 1.5 — Product discovery and knowledge-grounded support (experimental)

- **1.5A:** `wordpress/purr-child/` contains a read-only WordPress plugin. The admin-only `GET /wp-json/purrfect/v1/discovery` endpoint enumerates active plugins (including multisite network activations), current theme and parent theme, and accepts **explicit** `purrfect/product_signals` declarations only for installed active component keys. The plugin does **not** transmit inventory to Purra on its own. A sample integration is in `wordpress/examples/product-integration.php`. Install/activate the plugin on an actual WP site before claiming live-site compatibility.
- **1.5B:** `purrfect.discovery.discover` checks snapshot shape, active keys, contract version, knowledge identity/version and duplicate IDs. `SiteKnowledge` provides deterministic token-overlap retrieval scoped to selected active products and a tiny read-only Everyday WordPress FAQ. It is **not** vector/semantic RAG and does not ingest web pages or execute diagnostics.
- **1.5C:** `ScopeGuide` selects product/general-WP/clarification/unsupported through the existing `TextModel` interface, verifies all model-returned product IDs, and returns evidence verbatim with source records. `choose` consumes interactive user selections. No product operations are allowed.

Run `py -3.14 -m pip install -e ".[dev]"` and `py -3.14 -m pytest` on Windows. CI also runs `php -l` and `php tests/php/test_discovery.php`.

**Boundaries:** The Child does not provide an authenticated Python service/client or any deployment wiring yet; snapshots are supplied to Python explicitly. The PHP smoke test uses WordPress function shims and does not establish real WP runtime compatibility. PHP product signals share WordPress's plugin trust boundary and are not independently cryptographically attributable to the plugin file they claim. Do not expose plugin inventory to unauthenticated clients. Knowledge records are only as trustworthy as the participating product's declared data; the included WordPress FAQ is deliberately basic. Objective selection, coordinator persistence, real model behavior, network integration, full WordPress E2E, and real document ingestion need separate validation. Sophira and automated remediation remain out of scope.


## Goal 1.5D — Purr Child heartbeat + Docker lab

The **Child owns one traffic-independent wall-clock tick**, with independently registered component intervals. The first component is a five-minute product registry check. WordPress activation/deactivation, update and theme-switch hooks mark it dirty for the next tick. Per-component options track attempts, successes, failures and due times; `add_option` prevents normal concurrent runs, and abandoned locks expire. Failure of a component is caught and does not stop subsequent components. Changed registry snapshots are written only when their SHA-256 digest differs.

To try the isolated WordPress lab (Docker Desktop and Docker Compose required):

```powershell
cd wordpress/lab
docker compose up -d --build
docker compose --profile tools run --rm cli wp core install --url=http://localhost:8084 --title="Purr Child Lab" --admin_user=purr-lab --admin_password="local-lab-only-change-me" --admin_email=lab@example.invalid --skip-email
cd ../..
py -3.14 -m pip install -e ".[dev]"
py -3.14 wordpress/lab/acceptance.py
```

The WP site is at http://localhost:8084. The acceptance test activates two **mock products** (layout, translation), refreshes the registry through the heartbeat, checks Python knowledge separation, deactivates one mock product, confirms removal, then restores it. The Child endpoint `/wp-json/purrfect/v1/discovery` requires `manage_options`; it must not be made publicly readable.

Use `docker compose -f wordpress/lab/compose.yaml down` to stop containers. Do **not** use `down -v` unless you intentionally want to erase this lab's WordPress and database volumes.

The `clock` container aligns wakeups to minute boundaries; checks choose their own intervals and can be marked dirty. Normal WordPress WP-Cron is disabled inside the lab. Outside this lab, the plugin provides WP-Cron as a traffic-dependent fallback; a production-quality always-on clock requires a reliable external runner. This is **not** real-time immediate triggering: an activation marks the registry dirty and the next clock tick handles it.

**Validation distinction:** CI verifies PHP syntax, simulated WordPress heartbeat behaviors, and Python tests. The opt-in Docker acceptance test needs a machine with Docker; it has not been run by this assistant. No LLM service or cross-process RPC has been wired, and retrieval uses deterministic mock knowledge rather than vector RAG. This branch must not be called production-complete.


## Goal 1.6 — WordPress GUI ↔ local Python POC

**Local-only, not production authentication/deployment.** Reuses WordPress on port 8084, active mock product registry, and Purr Child. The WordPress admin menu **Purr Child Lab** provides a minimal chat; admin-ajax.php validates the logged-in administrator's capability and nonce before WordPress sends JSON to the internal `purra:8765/v1/chat` Python container. No Python port is published to the host or browser. Browser text is rendered as text, never HTML.

From the repository root (after switching to `feat/purr-local-chat-1-6`):
```powershell
docker compose -f wordpress/lab/compose.yaml up -d --build
docker compose -f wordpress/lab/compose.yaml ps
```
Visit http://localhost:8084/wp-admin/ and sign in using your existing **lab** administrator account (do not rerun WordPress core install). Open **Purr Child Lab** from the left admin menu. Try “I can't edit my page”: Purra should ask which registered product or WordPress area, then render clickable options. Choose Mock Layout to retrieve mock knowledge. Ask “login password” for general WP basics; ask about an unsupported area to see clarification. The two mock product plugins must be active and the registry heartbeat must have refreshed.

Communication passes through real HTTP and JSON (WordPress → Python container); product identification is deliberately **deterministic and basic**, not live LLM reasoning. `src/purrfect/local_api.py` holds ephemeral Python-side sessions in process memory; restart erases context. The browser session is generated anew per page load. This is not the final cross-site bridge, not real RAG, not complete 1.4 adaptive flow, and not independently authenticated at the Python service boundary. The backend's default HTTP binding is only appropriate inside this isolated Docker network. Do not expose port 8765 publicly. The discovery snapshot is currently forwarded on each request: final multi-tenant installation identity and authorization still need design.

Test failures: `docker compose -f wordpress/lab/compose.yaml logs --tail=80 purra wp`.
Stop without deleting database: `docker compose -f wordpress/lab/compose.yaml down`. No `down -v`.


## Goal 1.6 — Optional local Ollama Brain integration

The WordPress lab's existing chat can now route new questions through `select_scope`, backed by the existing `OllamaModel` adapter and a constrained selection schema. Only active product IDs, basic WordPress, out-of-scope, or clarification are permitted; responses still come verbatim from verified evidence, not generated troubleshooting text. Interactive selections remain deterministic and validated against the latest installed inventory.

The lab defaults to the **previous deterministic mode** until Ollama is explicitly enabled. To enable real local model routing, run from the repo root:

```powershell
git switch feat/purra-ollama-brain-1-6
docker compose -f wordpress/lab/compose.yaml --profile brain up -d --build
docker compose -f wordpress/lab/compose.yaml exec ollama ollama pull llama3.2:3b
$env:PURRA_BRAIN_MODE = "ollama"
docker compose -f wordpress/lab/compose.yaml --profile brain up -d --force-recreate purra
docker compose -f wordpress/lab/compose.yaml logs --tail=30 purra
```

Open http://localhost:8084/wp-admin/ and use **Purr Child Lab**. The transcript includes a routing marker (`brain`, `brain-clarify`, or `brain-unavailable`) when Ollama mode is active. Compare an explicit mock translation request, ambiguous editing question, ordinary WordPress password issue, and unsupported question. The Python model timeout is 5 seconds; unavailable models yield an explicit explanation and interactive choices, never fabricated guidance.

PowerShell environment overrides apply to the Compose invocation that starts the service. To return to deterministic mode, set `$env:PURRA_BRAIN_MODE = "deterministic"` and recreate just `purra`. The Ollama model remains a **local optional Docker service**, with no host port published.

**Limitations:** This is classification + verified retrieval, not free-form LLM answers, complete 1.4 multi-turn reasoning, production authentication, or semantic RAG. CI tests use fake models and do not verify actual Ollama availability or inference quality. Only enable in the isolated Docker lab.


## Goal 1.7 — Floating admin Purr Child (POC)

The existing WordPress plugin now mounts a fixed bottom-right Purr Child chat widget on **WordPress admin pages for users with manage_options**. It stays collapsed until opened, showing a short greeting bubble once per browser tab session. The old full-page **Purr Child Lab** remains available for debugging.

The widget stores a bounded display history, session identifier, pending option labels, open state and prior text context in **sessionStorage**, scoped to origin, site and current WordPress user. Navigation and refresh in the same tab restore these; a new tab generally starts separately. Browser session-restore and duplicated-tab behavior remain browser-dependent. Browser context is untrusted: the backend validates shape/length and checks any product selection against the current active registry on every request.

Purra handles greetings and basic conversational acknowledgements, and passes a previous-question hint to its existing constrained Brain scope classifier for follow-ups. Answers still come only from currently registered evidence or the Everyday WordPress FAQ. Backend memory and browser display history are separate: browser context can recover basic topic/selection after a Python restart, but **not the complete experimental CustomConversation/AdaptiveGuide checkpoints**. Integration of their richer guidance-task state into this live chat remains future hardening; no autonomous steps or knowledge writes were introduced.

### Local acceptance

```powershell
git fetch origin
git switch --track origin/feat/purr-conversation-widget-1-7
docker compose -f wordpress/lab/compose.yaml --profile brain up -d --build
```

If you had already enabled Ollama, set `$env:PURRA_BRAIN_MODE = "ollama"` **before** the compose command above, or recreate the `purra` service with that environment afterward. No WordPress database wipe is required.

Open http://localhost:8084/wp-admin/ then navigate around multiple admin pages and refresh. Confirm the bottom-right greeting and expandable widget, conversation transcript and pending choices persist. Try "Hi Purra!", "Can I ask something else?", a translation question, "What about that step?", and a correction to another product. For a fresh tab verify a separate conversation; deactivate a mock plugin and confirm the old restored context cannot produce its guidance. The old lab chat is still accessible for comparisons.

The floating chat is an **admin-only local POC**, not a production-ready distributed assistant. CI covers Python behavior, PHP syntax, and JS syntax; live WordPress browser acceptance still requires the local Docker lab.
