"""Independent FastAPI identity boundary for Purr Assistant installations.

Run behind HTTPS reverse proxy. This is NOT yet a replacement for the legacy
lab chat transport. Pairing codes are minted through trusted operator CLI only.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from purrfect.pairing import PairingRegistry


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=160)
    assistant_id: str
    site_id: str
    site_url: str


def create_app(database: str | Path | None = None) -> FastAPI:
    db_path = database or os.environ.get("PURR_PAIRING_DB_PATH")
    if not db_path:
        raise RuntimeError("PURR_PAIRING_DB_PATH required for durable pairing")
    registry = PairingRegistry(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        registry.close()

    app = FastAPI(title="Purr Assistant Pairing API", version="1.0.0", lifespan=lifespan)

    @app.post("/v1/assistants/pair", status_code=201)
    def pair(request: PairRequest):
        try:
            return registry.pair(code=request.code, assistant_id=request.assistant_id,
                                 site_id=request.site_id, site_url=request.site_url)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Pairing denied") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    def installed(
        x_purr_assistant_id: str = Header(...),
        authorization: str = Header(...),
    ) -> dict:
        scheme, _, secret = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secret:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        identity = registry.authenticate(x_purr_assistant_id, secret)
        if identity is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return identity

    @app.get("/v1/assistants/me")
    def assistant_status(identity: dict = Depends(installed)):
        return {"assistant_id": identity["assistant_id"], "site_id": identity["site_id"],
                "site_url": identity["site_url"], "status": "paired"}

    app.state.pairing_registry = registry
    return app


# ASGI app initialized from explicit environment configuration.
# Example: PURR_PAIRING_DB_PATH=./purr-pairing.sqlite uvicorn purrfect.pairing_api:app
def build_app():
    return create_app()


app = build_app() if os.environ.get("PURR_PAIRING_DB_PATH") else None
