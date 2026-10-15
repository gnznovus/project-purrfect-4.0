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
