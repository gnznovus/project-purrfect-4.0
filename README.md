# Project Purrfect 4.0

Python 3.14+ foundation for Purra, a product-specialized guidance system.

## Status

**Goal 1.1: deterministic guidance contract (development slice).**

Implemented: typed input requirements, stable option IDs, sequential target collection, input validation, and guidance-ready responses.

Not implemented: LLM reasoning, RAG, product-state retrieval, real Child communications, permissions, automation, execution, Sophira, or Aurora integration. Test examples are fixtures, **not** live product knowledge. A guidance-ready response does **not** authorize or perform an action.

## Architecture direction

- **Purra:** reasoning and guided product support (primary focus).
- **Purr Child:** product-specific assistant; UUIDv7 identity planned.
- **Sophira:** future shared, human-approved knowledge repository.
- **Aurora:** separate future execution integration.

Clients interact with Child. Developers may communicate with Purra directly. No network protocol has been chosen.

## Development

Goal → Contract → Implement → Validate → Document.

Windows PowerShell, using installed Python 3.14 (no virtual environment):

```powershell
py -3.14 -m pip install -e ".[dev]"
py -3.14 -m pytest
```

## Guidance contract example

`GuidanceSession` accepts a product-supplied `GuidanceDefinition` listing required inputs and valid target IDs. `current()` returns a message, status and structured interaction; `submit(key, value)` validates and advances. No LLM-generated options or command execution.
