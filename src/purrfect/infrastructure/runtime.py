"""Composition root: gateway config can evolve without changing Core."""
import json
import os
from purrfect.core.service import PurrCore
from purrfect.gateway.app import Admission, create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.ollama import OllamaModel
from purrfect.sophira_storage import DurableSophira

def build_app():
    clients = os.environ.get("PURR_CLIENTS_JSON")
    if not clients:
        raise RuntimeError("PURR_CLIENTS_JSON is required (never accept anonymous tenants)")
    registry = CredentialRegistry.from_json(clients)
    backend = os.environ.get("PURR_MODEL_BACKEND", "deterministic").lower()
    if backend not in ("deterministic", "ollama"):
        raise ValueError("Unsupported inference backend")
    model = (OllamaModel(model=os.getenv("PURR_OLLAMA_MODEL", "llama3.2:3b"),
                         base_url=os.getenv("PURR_OLLAMA_URL", "http://localhost:11434"))
             if backend == "ollama" else None)
    path = os.environ.get("PURR_SOPHIA_DB")
    core = PurrCore(catalog=DurableSophira(path) if path else None, model=model)
    admission = Admission(slots=int(os.getenv("PURR_INFERENCE_CONCURRENCY", "1")),
                          waiting=int(os.getenv("PURR_QUEUE_LIMIT", "4")))
    return create_app(core, registry, admission)
