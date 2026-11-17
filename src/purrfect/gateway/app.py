"""FastAPI boundary: authentication, tenant grants, admission, public contracts."""
import asyncio
from fastapi import Depends, FastAPI, Header, HTTPException
from purrfect.core.contracts import ChatCommand, TenantContext
from purrfect.core.service import AccessDenied, PurrCore
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.schemas import ChatRequest, ChatResponse

class Admission:
    """Per-process bounded inference admission; not a distributed scheduler."""
    def __init__(self, slots: int = 1, waiting: int = 4, queue_timeout: float = 5.0):
        if slots < 1 or waiting < 0 or queue_timeout <= 0:
            raise ValueError("Invalid admission limits")
        self._slots = asyncio.Semaphore(slots)
        self._maximum = slots + waiting
        self._waiting = 0
        self._lock = asyncio.Lock()
        self.timeout = queue_timeout

    async def acquire(self):
        async with self._lock:
            if self._waiting >= self._maximum:
                raise HTTPException(429, detail="Purr is busy", headers={"Retry-After": "2"})
            self._waiting += 1
        acquired = False
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=self.timeout)
            acquired = True
        except TimeoutError:
            raise HTTPException(503, detail="Inference queue timed out", headers={"Retry-After": "2"}) from None
        finally:
            if not acquired:
                async with self._lock:
                    self._waiting -= 1

    async def release(self):
        async with self._lock:
            self._waiting -= 1
            self._slots.release()

def create_app(core: PurrCore, registry: CredentialRegistry, admission: Admission | None = None) -> FastAPI:
    app = FastAPI(title="Purr Gateway", version="1.0.0")
    limiter = admission or Admission()

    def authenticate(authorization: str | None = Header(default=None)) -> TenantContext:
        tenant = registry.resolve(authorization)
        if tenant is None:
            raise HTTPException(401, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        return tenant

    @app.get("/v1/health")
    async def health(tenant: TenantContext = Depends(authenticate)):
        return {"service": "purr-gateway", "status": "healthy"}

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, tenant: TenantContext = Depends(authenticate)):
        if request.product_id is not None and request.product_id not in tenant.allowed_products:
            raise HTTPException(403, detail="Product not authorized")
        await limiter.acquire()
        try:
            command = ChatCommand(**request.model_dump())
            result = await core.respond(tenant, command)
        except AccessDenied as exc:
            raise HTTPException(403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, detail="Purr Core is temporarily unavailable") from exc
        finally:
            await limiter.release()
        return ChatResponse(session_id=result.session_id, status=result.status,
                            message=result.message,
                            sources=[dict(id=s.id, source=s.source, product_id=s.product_id)
                                     for s in result.sources])
    return app
