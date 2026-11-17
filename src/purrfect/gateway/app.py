"""Public API boundary: verified tenant/session scope, HTTP and SSE contracts."""
import json
import secrets
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.responses import StreamingResponse
from purrfect.core.contracts import ChatCommand, TenantContext
from purrfect.core.service import AccessDenied, PurrCore
from purrfect.gateway.auth import ClientVerifier
from purrfect.gateway.schemas import ChatRequest, ChatResponse, SessionResponse
from purrfect.gateway.session_tokens import InvalidSession, SessionTickets
from purrfect.infrastructure.scheduler import SchedulerOverloaded, SchedulerTimeout
from purrfect.infrastructure.coordination_errors import GlobalInferenceLeaseLost, SessionBusy, SessionLeaseLost


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, AccessDenied):
        return HTTPException(403, detail="Product not authorized")
    if isinstance(exc, SchedulerOverloaded):
        return HTTPException(429, detail="Inference queue is full", headers={"Retry-After": "2"})
    if isinstance(exc, (SchedulerTimeout, SessionBusy)):
        return HTTPException(503, detail="Inference queue timed out", headers={"Retry-After": "2"})
    if isinstance(exc, (GlobalInferenceLeaseLost, SessionLeaseLost)):
        return HTTPException(503, detail="Distributed coordination unavailable")
    if isinstance(exc, ValueError):
        return HTTPException(400, detail=str(exc))
    return HTTPException(503, detail="Purr Core is temporarily unavailable")


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(core: PurrCore, registry: ClientVerifier, tickets: SessionTickets, *, metrics=None, metrics_token: str | None = None) -> FastAPI:
    app = FastAPI(title="Purr Gateway", version="1.0.0")

    if metrics is not None:
        @app.middleware("http")
        async def record_request(request: Request, call_next):
            # Static, bounded route labels; no full paths, credentials, or user data.
            routes = {"/v1/chat": "chat", "/v1/chat/stream": "stream",
                      "/v1/sessions": "session", "/v1/health": "health"}
            route = routes.get(request.url.path)
            if route is None:
                return await call_next(request)
            start = time.monotonic()
            try:
                response = await call_next(request)
            except Exception:
                metrics.observe("request", "error", time.monotonic() - start, route=route)
                raise
            # Streaming is recorded on completion inside events(), not on headers.
            if route != "stream" or response.status_code != 200:
                outcome = "ok" if response.status_code < 400 else "error"
                metrics.observe("request", outcome, time.monotonic() - start, route=route)
            return response

    if metrics is not None and metrics_token is not None:
        if len(metrics_token) < 32:
            raise ValueError("Monitoring bearer secret must be 32+ characters")

        @app.get("/internal/metrics", include_in_schema=False)
        async def protected_metrics(authorization: str | None = Header(default=None)):
            supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
            if not secrets.compare_digest(supplied, metrics_token):
                raise HTTPException(401, detail="Invalid monitoring credentials")
            return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


    def authenticate(authorization: str | None = Header(default=None)) -> TenantContext:
        tenant = registry.resolve(authorization)
        if tenant is None:
            raise HTTPException(401, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        return tenant

    def require_session(
        tenant: TenantContext = Depends(authenticate),
        x_purr_session: str | None = Header(default=None),
    ) -> str:
        try:
            return tickets.verify(x_purr_session, tenant.tenant_id)
        except InvalidSession as exc:
            raise HTTPException(401, detail="Invalid or expired session credential") from exc

    def command_for(request: ChatRequest, tenant: TenantContext, session_id: str) -> ChatCommand:
        if request.session_id is not None and request.session_id != session_id:
            raise HTTPException(403, detail="Session does not match credential")
        if request.product_id is not None and request.product_id not in tenant.allowed_products:
            raise HTTPException(403, detail="Product not authorized")
        return ChatCommand(session_id=session_id, message=request.message,
                           product_id=request.product_id, product_version=request.product_version)

    @app.get("/v1/health")
    async def health(tenant: TenantContext = Depends(authenticate)):
        return {"service": "purr-gateway", "status": "healthy"}

    @app.post("/v1/sessions", response_model=SessionResponse)
    async def create_session(tenant: TenantContext = Depends(authenticate)):
        result = tickets.issue(tenant.tenant_id)
        return SessionResponse(**vars(result))

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, tenant: TenantContext = Depends(authenticate),
                   session_id: str = Depends(require_session)):
        command = command_for(request, tenant, session_id)
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
    async def chat_stream(request: ChatRequest, tenant: TenantContext = Depends(authenticate),
                          session_id: str = Depends(require_session)):
        command = command_for(request, tenant, session_id)

        async def events():
            start = time.monotonic()
            outcome = "cancelled"
            try:
                async for event in core.stream(tenant, command):
                    if event["event"] == "done":
                        outcome = "ok"
                    yield _frame(event["event"], event["data"])
            except Exception as exc:
                outcome = "error"
                error = _translate(exc)
                yield _frame("error", {"status": error.status_code, "message": error.detail})
            finally:
                if metrics is not None:
                    metrics.observe("stream", outcome, time.monotonic() - start, route="stream")

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return app
