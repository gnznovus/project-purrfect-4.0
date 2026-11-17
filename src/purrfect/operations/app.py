"""Isolated operator-only ASGI application, independent of public Purr Gateway."""
import asyncio
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from purrfect.operations.benchmark import BenchmarkConfig, BenchmarkRunner, PROFILES
from purrfect.operations.store import BenchmarkStore
from purrfect.operations.telemetry import project


STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str
    samples: int = Field(ge=1, le=8)
    concurrency: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def verify_controls(self):
        if self.profile not in PROFILES or self.concurrency > self.samples:
            raise ValueError("Invalid benchmark controls")
        return self


def build_console(*, operator_token: str, gateway_token: str, gateway_url: str,
                  metrics_token: str | None, store: BenchmarkStore,
                  model_label: str = "Configured Gateway",
                  transport: httpx.AsyncBaseTransport | None = None,
                  runner: BenchmarkRunner | None = None,
                  dev_auto_auth: bool = False) -> FastAPI:
    if (not isinstance(operator_token, str) or len(operator_token) < 32
            or not isinstance(gateway_token, str) or len(gateway_token) < 16
            or (metrics_token is not None and len(metrics_token) < 32)):
        raise ValueError("Missing/weak operations credentials")
    url = urlsplit(gateway_url)
    if (url.scheme not in {"http", "https"} or not url.hostname or
            url.username or url.password or url.path not in ("", "/")
            or url.query or url.fragment):
        raise ValueError("Invalid configured Gateway origin")
    config = BenchmarkConfig(gateway_url.rstrip("/"), gateway_token, model_label)
    benchmark = runner or BenchmarkRunner(config, transport=transport)
    app = FastAPI(title="Purr Operations", docs_url=None, redoc_url=None, openapi_url=None)
    busy = asyncio.Lock()

    def allowed_local(request: Request) -> bool:
        """Dev-only same-machine trust; never disclose the operator secret."""
        if not dev_auto_auth:
            return False
        client = request.client.host if request.client else ""
        host = request.url.hostname
        if client not in ("127.0.0.1", "::1") or host not in ("127.0.0.1", "::1", "localhost"):
            return False
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            return False
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return False
        return True

    def authorized(request: Request, authorization: str | None = Header(default=None)):
        value = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if secrets.compare_digest(value, operator_token) or allowed_local(request):
            return True
        raise HTTPException(401, detail="Invalid operations credentials")

    @app.get("/healthz", include_in_schema=False)
    async def deploy_health():
        # Railway liveness: never report private metrics or credentials.
        return {"status": "ok"}

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        # The browser learns only the authentication mode, not the .env secret.
        return {"auto_login": allowed_local(request)}

    @app.middleware("http")
    async def harden(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/assets/app.css", include_in_schema=False)
    async def css():
        return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.get("/assets/app.js", include_in_schema=False)
    async def script():
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/api/overview", dependencies=[Depends(authorized)])
    async def overview():
        auth = {"Authorization": "Bearer " + gateway_token}
        health = {"status": "unreachable", "latency_ms": None}
        start = asyncio.get_running_loop().time()
        try:
            async with httpx.AsyncClient(
                base_url=config.gateway_url, transport=transport,
                timeout=3, trust_env=False, follow_redirects=False,
            ) as client:
                response = await client.get("/v1/health", headers=auth)
            if response.status_code == 200:
                health = {"status": "healthy", "latency_ms":
                          round((asyncio.get_running_loop().time() - start) * 1000, 2)}
            else:
                health["status"] = "unhealthy"
        except (httpx.HTTPError, ValueError):
            pass
        history = await asyncio.to_thread(store.list, 12)
        completed = [item for item in history if item["report"] is not None]
        return {
            "gateway": health, "model_label": config.model_label,
            "recent_runs": len(history), "latest_run": completed[0] if completed else None,
        }

    @app.get("/api/telemetry", dependencies=[Depends(authorized)])
    async def telemetry():
        if not metrics_token:
            return {"available": False, "reason": "Monitoring token not configured", "series": []}
        try:
            async with httpx.AsyncClient(
                base_url=config.gateway_url, transport=transport, timeout=3,
                trust_env=False, follow_redirects=False,
            ) as client:
                response = await client.get(
                    "/internal/metrics",
                    headers={"Authorization": "Bearer " + metrics_token},
                )
            if response.status_code != 200:
                return {"available": False, "reason": "Gateway metrics unavailable", "series": []}
            return {"available": True, "series": project(response.text)}
        except (httpx.HTTPError, ValueError):
            return {"available": False, "reason": "Gateway metrics unavailable", "series": []}

    @app.get("/api/runs", dependencies=[Depends(authorized)])
    async def history():
        return {"runs": await asyncio.to_thread(store.list, 30)}

    @app.get("/api/runs/{run_id}", dependencies=[Depends(authorized)])
    async def run_detail(run_id: str):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise HTTPException(404, detail="Run not found")
        run = await asyncio.to_thread(store.get, run_id)
        if run is None:
            raise HTTPException(404, detail="Run not found")
        return run

    @app.post("/api/benchmarks", dependencies=[Depends(authorized)])
    async def execute(request: RunRequest):
        if busy.locked():
            raise HTTPException(409, detail="A benchmark is already running")
        async with busy:
            run_id = await asyncio.to_thread(
                store.start, profile=request.profile, model_label=config.model_label,
                samples=request.samples, concurrency=request.concurrency,
            )
            try:
                report = await benchmark.run(
                    profile=request.profile, samples=request.samples,
                    concurrency=request.concurrency,
                )
            except BaseException:
                await asyncio.to_thread(store.complete, run_id, {}, "interrupted")
                raise
            await asyncio.to_thread(store.complete, run_id, report)
            return await asyncio.to_thread(store.get, run_id)

    return app
