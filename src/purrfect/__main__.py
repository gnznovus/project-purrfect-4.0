"""Launch Purr Gateway with a framework-independent Core."""
import uvicorn
from purrfect.config import load_settings
from purrfect.infrastructure.runtime import build_app

if __name__ == "__main__":
    settings = load_settings()
    host = settings.get("PURR_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "::1", "localhost") and not settings.get("PURR_ALLOW_REMOTE") == "1":
        raise RuntimeError("Remote binding requires explicit PURR_ALLOW_REMOTE=1 and HTTPS reverse proxy")
    uvicorn.run(build_app(), host=host, port=int(settings.get("PURR_PORT", "8765")), workers=1)
