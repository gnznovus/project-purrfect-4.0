"""Composition root: isolate client identity, storage, and model execution."""
import json
import os

from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.session_tokens import SessionTickets
from purrfect.infrastructure.cache import RetrievalCache
from purrfect.infrastructure.scheduler import FairInferenceScheduler
from purrfect.infrastructure.sessions import MemorySessions, SQLiteSessions
from purrfect.ollama import OllamaModel
from purrfect.sophira_storage import DurableSophira


def build_app():
    clients = os.environ.get("PURR_CLIENTS_JSON")
    if not clients:
        raise RuntimeError("PURR_CLIENTS_JSON is required (never accept anonymous tenants)")
    registry = CredentialRegistry.from_json(clients)
    signing_key = os.environ.get("PURR_SESSION_SIGNING_KEY")
    if not signing_key:
        raise RuntimeError("PURR_SESSION_SIGNING_KEY is required")
    previous = json.loads(os.environ.get("PURR_SESSION_PREVIOUS_KEYS", "[]"))
    if not isinstance(previous, list):
        raise ValueError("PURR_SESSION_PREVIOUS_KEYS must be an array")
    tickets = SessionTickets(
        signing_key, lifetime=int(os.getenv("PURR_SESSION_TTL", "86400")),
        previous_secrets=tuple(previous),
    )
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
    redis_url = os.getenv("PURR_REDIS_URL")
    coordinator = None
    if redis_url:
        import redis
        from purrfect.infrastructure.redis_sessions import RedisSessions, RedisSessionCoordinator
        client = redis.Redis.from_url(redis_url, decode_responses=True,
                                      socket_connect_timeout=2, socket_timeout=3)
        # Fail startup instead of falling back to isolated per-worker sessions.
        client.ping()
        namespace = os.getenv("PURR_REDIS_NAMESPACE", "purr")
        sessions = RedisSessions(client, namespace=namespace,
                                 history_limit=int(os.getenv("PURR_HISTORY_LIMIT", "6")),
                                 idle_ttl=int(os.getenv("PURR_SESSION_IDLE_TTL", "604800")))
        coordinator = RedisSessionCoordinator(
            client, namespace=namespace,
            lease_seconds=int(os.getenv("PURR_SESSION_LEASE_SECONDS", "30")),
            wait_seconds=float(os.getenv("PURR_SESSION_WAIT_SECONDS", "5")),
        )
    else:
        session_db = os.getenv("PURR_SESSION_DB", "./purr-sessions.db")
        sessions = (SQLiteSessions(session_db, history_limit=int(os.getenv("PURR_HISTORY_LIMIT", "6")))
                    if session_db else MemorySessions())
    core = PurrCore(catalog=DurableSophira(path) if path else None,
                    model=model, scheduler=scheduler, sessions=sessions,
                    session_coordinator=coordinator,
                    evidence_cache=RetrievalCache(int(os.getenv("PURR_RETRIEVAL_CACHE_SIZE", "512"))))
    return create_app(core, registry, tickets)
