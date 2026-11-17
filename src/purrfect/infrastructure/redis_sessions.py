"""Redis-backed tenant sessions and fenced cross-worker conversation leases.

A session's write is atomic only while the caller still owns its Redis lease.
Expired lease holders cannot commit stale conversation turns. Shared Redis
also provides bounded history and idle-time retention without client storage.
"""
import asyncio
import contextvars
import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager

import redis
from redis.exceptions import RedisError
from purrfect.infrastructure.coordination_errors import SessionBusy, SessionLeaseLost


_lease_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "purr_redis_session_lease", default=None,
)


def _key(namespace: str, tenant: str, session: str) -> str:
    if not tenant or not session:
        raise ValueError("Tenant and session are required")
    digest = hashlib.sha256(f"{tenant}\x00{session}".encode()).hexdigest()
    return f"{namespace}:session:{digest}"


# Append is fenced by the associated lock. No stale worker can write after
# lease loss, even if it resumes after another worker acquired the session.
_APPEND = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('RPUSH', KEYS[2], ARGV[2])
redis.call('LTRIM', KEYS[2], -tonumber(ARGV[3]), -1)
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
return 1
"""

_RENEW = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]))
"""

_RELEASE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


class RedisSessions:
    def __init__(self, client: redis.Redis, *, namespace: str = "purr",
                 history_limit: int = 6, idle_ttl: int = 604800):
        if history_limit < 1 or not 60 <= idle_ttl <= 31536000 or not namespace:
            raise ValueError("Invalid Redis session configuration")
        self._client = client
        self._namespace = namespace
        self._history_limit = history_limit
        self._idle_ttl = idle_ttl

    def read(self, tenant: str, session: str) -> tuple[tuple[str, str], ...]:
        values = self._client.lrange(_key(self._namespace, tenant, session), 0, -1)
        return tuple(tuple(json.loads(value)) for value in values)

    def append(self, tenant: str, session: str, question: str, answer: str) -> None:
        token = _lease_token.get()
        if token is None:
            raise SessionLeaseLost("Session write requires an active distributed lease")
        session_key = _key(self._namespace, tenant, session)
        lock_key = session_key + ":lock"
        written = self._client.eval(
            _APPEND, 2, lock_key, session_key, token,
            json.dumps([question, answer], ensure_ascii=False),
            self._history_limit, self._idle_ttl,
        )
        if written != 1:
            raise SessionLeaseLost("Session lease was lost before conversation commit")


class RedisSessionCoordinator:
    """One owner per tenant/session, with renewable leased locks.

    This is a *single Redis primary* coordination model, not consensus across
    asynchronous failover. Lease loss rejects stale writes instead of corrupting
    conversation order. Reconnect/failover must be separately validated.
    """

    def __init__(self, client: redis.Redis, *, namespace: str = "purr",
                 lease_seconds: int = 30, wait_seconds: float = 5):
        if not namespace or lease_seconds < 3 or wait_seconds <= 0:
            raise ValueError("Invalid lease configuration")
        self._client = client
        self._namespace = namespace
        self._lease_ms = lease_seconds * 1000
        self._wait_seconds = wait_seconds

    async def _redis(self, method, *args, **kwargs):
        return await asyncio.to_thread(method, *args, **kwargs)

    async def _keepalive(self, lock_key: str, token: str, stop: asyncio.Event,
                         lost: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._lease_ms / 3000)
                return
            except TimeoutError:
                pass
            try:
                ok = await self._redis(self._client.eval, _RENEW, 1, lock_key,
                                       token, self._lease_ms)
                if ok != 1:
                    lost.set()
                    return
            except RedisError:
                lost.set()
                return

    @asynccontextmanager
    async def lock(self, tenant: str, session: str):
        lock_key = _key(self._namespace, tenant, session) + ":lock"
        token = secrets.token_urlsafe(32)
        deadline = time.monotonic() + self._wait_seconds
        while True:
            acquired = await self._redis(self._client.set, lock_key, token,
                                         nx=True, px=self._lease_ms)
            if acquired:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SessionBusy("Session is busy")
            await asyncio.sleep(min(0.05, remaining))

        stop = asyncio.Event()
        lost = asyncio.Event()
        marker = _lease_token.set(token)
        heartbeat = asyncio.create_task(self._keepalive(lock_key, token, stop, lost))
        try:
            yield
            if lost.is_set():
                raise SessionLeaseLost("Session lease renewal failed")
        finally:
            stop.set()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            _lease_token.reset(marker)
            # Idempotent token-checked release never unlocks another worker.
            try:
                await self._redis(self._client.eval, _RELEASE, 1, lock_key, token)
            except RedisError:
                # TTL handles cleanup; if Redis is down, the write path fails closed.
                pass
