"""Composition root: isolate client identity, storage, and model execution."""
import json

from purrfect.config import load_settings
from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.session_tokens import SessionTickets
from purrfect.infrastructure.cache import RetrievalCache
from purrfect.infrastructure.metrics import Metrics
from purrfect.infrastructure.instrumentation import InstrumentedScheduler
from purrfect.infrastructure.scheduler import FairInferenceScheduler
from purrfect.infrastructure.sessions import MemorySessions, SQLiteSessions
from purrfect.ollama import OllamaModel
from purrfect.sophira_storage import DurableSophira


def build_app():
    settings = load_settings()
    clients = settings.get("PURR_CLIENTS_JSON")
    if not clients:
        raise RuntimeError("PURR_CLIENTS_JSON is required (never accept anonymous tenants)")
    registry = CredentialRegistry.from_json(clients)
    signing_key = settings.get("PURR_SESSION_SIGNING_KEY")
    if not signing_key:
        raise RuntimeError("PURR_SESSION_SIGNING_KEY is required")
    previous = json.loads(settings.get("PURR_SESSION_PREVIOUS_KEYS", "[]"))
    if not isinstance(previous, list):
        raise ValueError("PURR_SESSION_PREVIOUS_KEYS must be an array")
    tickets = SessionTickets(
        signing_key, lifetime=int(settings.get("PURR_SESSION_TTL", "86400")),
        previous_secrets=tuple(previous),
    )
    backend = settings.get("PURR_MODEL_BACKEND", "deterministic").lower()
    if backend not in ("deterministic", "ollama"):
        raise ValueError("Unsupported inference backend")
    model = (OllamaModel(model=settings.get("PURR_OLLAMA_MODEL", "llama3.2:3b"),
                         base_url=settings.get("PURR_OLLAMA_URL", "http://localhost:11434"))
             if backend == "ollama" else None)
    path = settings.get("PURR_SOPHIA_DB")
    metrics = Metrics()
    scheduler = FairInferenceScheduler(
        slots=int(settings.get("PURR_INFERENCE_CONCURRENCY", "1")),
        max_waiting=int(settings.get("PURR_QUEUE_LIMIT", "4")),
        max_waiting_per_tenant=int(settings.get("PURR_TENANT_QUEUE_LIMIT", "2")),
        queue_timeout=float(settings.get("PURR_QUEUE_TIMEOUT", "5")),
        metrics=metrics,
    )
    redis_url = settings.get("PURR_REDIS_URL")
    coordinator = None
    if redis_url:
        import redis
        from purrfect.infrastructure.redis_sessions import RedisSessions, RedisSessionCoordinator
        client = redis.Redis.from_url(redis_url, decode_responses=True,
                                      socket_connect_timeout=2, socket_timeout=3)
        # Fail startup instead of falling back to isolated per-worker sessions.
        client.ping()
        namespace = settings.get("PURR_REDIS_NAMESPACE", "purr")
        sessions = RedisSessions(client, namespace=namespace,
                                 history_limit=int(settings.get("PURR_HISTORY_LIMIT", "6")),
                                 idle_ttl=int(settings.get("PURR_SESSION_IDLE_TTL", "604800")))
        coordinator = RedisSessionCoordinator(
            client, namespace=namespace,
            lease_seconds=int(settings.get("PURR_SESSION_LEASE_SECONDS", "30")),
            wait_seconds=float(settings.get("PURR_SESSION_WAIT_SECONDS", "5")),
        )
        if model is not None:
            from purrfect.infrastructure.redis_inference import RedisInferenceScheduler
            scheduler = RedisInferenceScheduler(
                client, namespace=namespace,
                global_slots=int(settings.get("PURR_GLOBAL_INFERENCE_SLOTS", "1")),
                per_tenant_slots=int(settings.get("PURR_GLOBAL_TENANT_SLOTS", "1")),
                lease_seconds=int(settings.get("PURR_INFERENCE_LEASE_SECONDS", "30")),
                wait_seconds=float(settings.get("PURR_GLOBAL_INFERENCE_WAIT_SECONDS", "5")),
                local_scheduler=scheduler,
                metrics=metrics,
            )
    else:
        session_db = settings.get("PURR_SESSION_DB", "./purr-sessions.db")
        sessions = (SQLiteSessions(session_db, history_limit=int(settings.get("PURR_HISTORY_LIMIT", "6")))
                    if session_db else MemorySessions())
    core = PurrCore(catalog=DurableSophira(path) if path else None,
                    model=model, scheduler=InstrumentedScheduler(scheduler, metrics), sessions=sessions,
                    session_coordinator=coordinator,
                    evidence_cache=RetrievalCache(int(settings.get("PURR_RETRIEVAL_CACHE_SIZE", "512"))))
    return create_app(core, registry, tickets, metrics=metrics,
                      metrics_token=settings.get("PURR_METRICS_TOKEN") or None)
