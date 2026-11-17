"""Persistent, Git-ignored local settings; environment overrides remain optional.

Read only the fixed config/local.json file under the source checkout root.
Never write local secrets automatically on application startup.
"""
import argparse
import json
import os
import secrets
from pathlib import Path


def config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "local.json"


class Settings:
    def __init__(self, data: dict):
        if not isinstance(data, dict) or any(not isinstance(k, str) or not k.startswith("PURR_") for k in data):
            raise ValueError("Local config must be an object with PURR_ setting keys")
        self._data = data

    def get(self, key: str, default=None):
        if key in os.environ:
            return os.environ[key]
        value = self._data.get(key, default)
        if isinstance(value, (list, dict)):
            return json.dumps(value, separators=(",", ":"))
        if value is None:
            return None
        if isinstance(value, (str, int, float)):
            return str(value)
        raise ValueError(f"Invalid setting type: {key}")


def load_settings(path: Path | None = None) -> Settings:
    target = path or config_path()
    if not target.is_file():
        return Settings({})
    if target.is_symlink():
        raise ValueError("Refusing symlinked secrets configuration")
    data = json.loads(target.read_text(encoding="utf-8"))
    return Settings(data)


def initialize(path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise FileExistsError("Refusing to overwrite symlink")
    gateway = secrets.token_hex(32)
    monitor = secrets.token_hex(32)
    settings = {
        "PURR_CLIENTS_JSON": [{"token": gateway, "tenant_id": "dev", "products": ["demo"]}],
        "PURR_SESSION_SIGNING_KEY": secrets.token_hex(32),
        "PURR_METRICS_TOKEN": monitor,
        "PURR_MODEL_BACKEND": "deterministic",
        "PURR_OPERATIONS_TOKEN": secrets.token_hex(32),
        "PURR_OPERATIONS_GATEWAY_TOKEN": gateway,
        "PURR_OPERATIONS_METRICS_TOKEN": monitor,
        "PURR_OPERATIONS_GATEWAY_URL": "http://127.0.0.1:8765",
        "PURR_OPERATIONS_MODEL_LABEL": "Development Gateway",
    }
    # Exclusive creation: repeated invocation never clobbers existing credentials.
    with target.open("x", encoding="utf-8") as handle:
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass  # Windows permissions are managed by local ACLs.
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Purr local configuration")
    parser.add_argument("action", choices=["init"])
    args = parser.parse_args()
    if args.action == "init":
        try:
            result = initialize()
        except FileExistsError:
            parser.error("config/local.json already exists; refusing to overwrite secrets")
        print(f"Created ignored local configuration: {result}")
        print("Keep it private. Run the Gateway and Console from the repo checkout.")


if __name__ == "__main__":
    main()
