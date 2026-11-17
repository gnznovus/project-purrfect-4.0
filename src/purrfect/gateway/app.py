"""Public API boundary: auth, validation, HTTP and SSE contracts."""
import json

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from purrfect.core.contracts import ChatCommand, TenantContext
from purrfect.core.service import AccessDenied, PurrCore
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.schemas import ChatRequest, ChatResponse
from purrfect.infrastructure.scheduler import SchedulerOverloaded, SchedulerTimeout


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, AccessDenied):
        return HTTPException(403, detail="Product not authorized")
    if isinstance(exc, SchedulerOverloaded):
        return HTTPException(429, detail="Inference queue is full", headers={"Retry-After": "2"})
    if isinstance(exc, SchedulerTimeout):
        return HTTPException(503, detail="Inference queue timed out", headers={"Retry-After": "2"})
    if isinstance(exc, ValueError):
        return HTTPException(400, detail=str(exc))
    return HTTPException(503, detail="Purr Core is temporarily unavailable")


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(core: PurrCore, registry: CredentialRegistry) -> FastAPI:
    app = FastAPI(title="Purr Gateway", version="1.0.0")

    def authenticate(authorization: str | None = Header(default=None)) -> TenantContext:
        tenant = registry.resolve(authorization)
        if tenant is None:
            raise HTTPException(401, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        return tenant

    def command_for(request: ChatRequest, tenant: TenantContext) -> ChatCommand:
        if request.product_id is not None and request.product_id not in tenant.allowed_products:
            raise HTTPException(403, detail="Product not authorized")
        return ChatCommand(**request.model_dump())

    @app.get("/v1/health")
    async def health(tenant: TenantContext = Depends(authenticate)):
        return {"service": "purr-gateway", "status": "healthy"}

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, tenant: TenantContext = Depends(authenticate)):
        command = command_for(request, tenant)
        try:
            result = await core.respond(tenant, command)
        except Exception as exc:
            raise _translate(exc) from exc
        return ChatResponse(
            session_id=result.session_id, status=result.status,
            message=result.message,
            sources=[dict(id=s.id, source=s.source, product_id=s.product_id) for s in result.sources],
        )

    @app.post("/v1/chat/stream")
    async def chat_stream(request: ChatRequest, tenant: TenantContext = Depends(authenticate)):
        command = command_for(request, tenant)

        async def events():
            try:
                async for event in core.stream(tenant, command):
                    yield _frame(event["event"], event["data"])
            except Exception as exc:
                error = _translate(exc)
                # HTTP headers have already been sent: report terminal failure in SSE.
                yield _frame("error", {"status": error.status_code, "message": error.detail})

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return app
