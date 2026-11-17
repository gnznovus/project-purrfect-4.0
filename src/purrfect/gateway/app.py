"""Public API gateway; model scheduling stays inside Core infrastructure."""
from fastapi import Depends, FastAPI, Header, HTTPException
from purrfect.core.contracts import ChatCommand, TenantContext
from purrfect.core.service import AccessDenied, PurrCore
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.schemas import ChatRequest, ChatResponse
from purrfect.infrastructure.scheduler import SchedulerOverloaded, SchedulerTimeout


def create_app(core: PurrCore, registry: CredentialRegistry) -> FastAPI:
    app = FastAPI(title="Purr Gateway", version="1.0.0")

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
        try:
            command = ChatCommand(**request.model_dump())
            result = await core.respond(tenant, command)
        except AccessDenied as exc:
            raise HTTPException(403, detail=str(exc)) from exc
        except SchedulerOverloaded as exc:
            raise HTTPException(429, detail=str(exc), headers={"Retry-After": "2"}) from exc
        except SchedulerTimeout as exc:
            raise HTTPException(503, detail=str(exc), headers={"Retry-After": "2"}) from exc
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, detail="Purr Core is temporarily unavailable") from exc
        return ChatResponse(session_id=result.session_id, status=result.status,
                            message=result.message,
                            sources=[dict(id=s.id, source=s.source, product_id=s.product_id)
                                     for s in result.sources])
    return app
