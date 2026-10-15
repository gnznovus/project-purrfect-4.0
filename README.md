# Project Purrfect 4.0

A Python-based foundation for reusable AI intelligence and specialized product assistants.

## Status

**Bootstrap only.** No Parent, Child, orchestration, memory, RAG, or execution integration is implemented yet.

## Architectural direction

- **Purr Base:** shared intelligence infrastructure.
- **Purr Parent:** shared reasoning and knowledge service; also provides a developer-facing interface.
- **Purr Child:** product-specific client interface and bounded diagnostic endpoint.
- **Host product:** defines, validates, and authorizes the commands available to its Child.
- **Aurora:** potential future execution backend; not a dependency.

Conceptual client flow: Client ↔ Child ↔ Parent.

Conceptual developer flow: Developer ↔ Parent ↔ target Child ↔ product-defined diagnostic capability.

These are responsibility boundaries, **not** predefined processes or deployment topology.

## Development workflow

Goal → Contract → Implement → Validate → Document.

Keep slices small, reuse proven 3.0 components selectively, and distinguish proposed behavior from working behavior.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
# Activate the virtual environment using your shell
python -m pip install -e ".[dev]"
python -m pytest
```

No service or model is required to run the initial smoke test.
