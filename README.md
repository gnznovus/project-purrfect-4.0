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
