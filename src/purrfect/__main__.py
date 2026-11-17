"""Launch Purr Gateway with a framework-independent Core."""
import os
import uvicorn
from purrfect.infrastructure.runtime import build_app

if __name__ == "__main__":
    host = os.environ.get("PURR_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "::1", "localhost") and not os.environ.get("PURR_ALLOW_REMOTE") == "1":
        raise RuntimeError("Remote binding requires explicit PURR_ALLOW_REMOTE=1 and HTTPS reverse proxy")
    uvicorn.run(build_app(), host=host, port=int(os.getenv("PURR_PORT", "8765")), workers=1)
