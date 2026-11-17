"""Container-only Railway staging entrypoint.

Production services are distinct, use Railway's PORT, and never start the
Windows dev supervisor or development auto-auth.
"""
import argparse
import os

import uvicorn

from purrfect.config import load_settings


def deployment_config(service: str) -> tuple[str, int]:
    settings = load_settings()
    if settings.get("PURR_ENV", "").lower() != "production":
        raise RuntimeError("Container deployment requires PURR_ENV=production")
    if service not in ("gateway", "operations"):
        raise ValueError("Unknown service")
    if service == "operations" and settings.get("PURR_OPERATIONS_DEV_AUTO_AUTH", "0") == "1":
        raise RuntimeError("Development auto-auth may not be enabled in hosted operations")
    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be in range 1-65535")
    return "0.0.0.0", port


def main() -> None:
    parser = argparse.ArgumentParser(description="Purr Railway container entrypoint")
    parser.add_argument("service", choices=("gateway", "operations"))
    args = parser.parse_args()
    host, port = deployment_config(args.service)
    if args.service == "gateway":
        from purrfect.infrastructure.runtime import build_app
        app = build_app()
    else:
        from purrfect.operations.app import build_console
        from purrfect.operations.store import BenchmarkStore
        settings = load_settings()
        operator_token = settings.get("PURR_OPERATIONS_TOKEN")
        gateway_token = settings.get("PURR_OPERATIONS_GATEWAY_TOKEN")
        gateway_url = settings.get("PURR_OPERATIONS_GATEWAY_URL")
        db_path = settings.get("PURR_OPERATIONS_DB", "/data/purr-operations.db")
        if not operator_token or not gateway_token or not gateway_url:
            raise RuntimeError("Operations service credentials and Gateway URL are required")
        if not os.path.isabs(db_path) or not os.path.realpath(db_path).startswith("/data/"):
            raise RuntimeError("Hosted Operations DB must be on persistent /data volume")
        app = build_console(
            operator_token=operator_token,
            gateway_token=gateway_token,
            gateway_url=gateway_url,
            metrics_token=settings.get("PURR_OPERATIONS_METRICS_TOKEN") or None,
            store=BenchmarkStore(db_path),
            model_label=settings.get("PURR_OPERATIONS_MODEL_LABEL", "Staging Gateway"),
            dev_auto_auth=False,
        )
    uvicorn.run(app, host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
