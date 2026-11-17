"""Composition root: gateway configuration is independent of Purr Core."""
import os
from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.infrastructure.cache import RetrievalCache
from purrfect.infrastructure.scheduler import FairInferenceScheduler
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
    scheduler = FairInferenceScheduler(
        slots=int(os.getenv("PURR_INFERENCE_CONCURRENCY", "1")),
        max_waiting=int(os.getenv("PURR_QUEUE_LIMIT", "4")),
        max_waiting_per_tenant=int(os.getenv("PURR_TENANT_QUEUE_LIMIT", "2")),
        queue_timeout=float(os.getenv("PURR_QUEUE_TIMEOUT", "5")),
    )
    core = PurrCore(catalog=DurableSophira(path) if path else None,
                    model=model, scheduler=scheduler,
                    evidence_cache=RetrievalCache(int(os.getenv("PURR_RETRIEVAL_CACHE_SIZE", "512"))))
    return create_app(core, registry)
