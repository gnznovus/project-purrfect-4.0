"""Start Purr Operations Console separately from public Gateway."""

import uvicorn
from purrfect.config import load_settings
from purrfect.operations.app import build_console
from purrfect.operations.store import BenchmarkStore


def main():
    settings = load_settings()
    host = settings.get("PURR_OPERATIONS_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "::1", "localhost") and settings.get("PURR_OPERATIONS_ALLOW_REMOTE") != "1":
        raise RuntimeError("Remote operations binding requires explicit opt-in and HTTPS reverse proxy")
    token = settings.get("PURR_OPERATIONS_TOKEN")
    client_token = settings.get("PURR_OPERATIONS_GATEWAY_TOKEN")
    if not token or not client_token:
        raise RuntimeError("Operations and Gateway service credentials are required")
    app = build_console(
        operator_token=token,
        gateway_token=client_token,
        gateway_url=settings.get("PURR_OPERATIONS_GATEWAY_URL", "http://127.0.0.1:8765"),
        metrics_token=settings.get("PURR_OPERATIONS_METRICS_TOKEN") or None,
        store=BenchmarkStore(settings.get("PURR_OPERATIONS_DB", "./purr-operations.db")),
        model_label=settings.get("PURR_OPERATIONS_MODEL_LABEL", "Configured Gateway"),
    )
    uvicorn.run(app, host=host, port=int(settings.get("PURR_OPERATIONS_PORT", "8775")), workers=1)


if __name__ == "__main__":
    main()
