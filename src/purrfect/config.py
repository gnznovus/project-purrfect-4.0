"""Git-ignored .env settings with optional process-environment overrides.

Read the fixed repository .env without mutating os.environ. The one-time
bootstrap can migrate existing config/local.json secrets without rotating them.
"""
import argparse
import json
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values


def config_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def legacy_config_path() -> Path:
    return config_path().parent / "config" / "local.json"


class Settings:
    def __init__(self, data: dict[str, str | None]):
        if not isinstance(data, dict) or any(
            not isinstance(k, str) or not k.startswith("PURR_")
            or (v is not None and not isinstance(v, str))
            for k, v in data.items()
        ):
            raise ValueError("Invalid .env setting; expected PURR_ keys and string values")
        self._data = dict(data)

    def get(self, key: str, default=None):
        if key in os.environ:
            return os.environ[key]
        value = self._data.get(key)
        return default if value is None else value


def load_settings(path: Path | None = None) -> Settings:
    target = path if path is not None else config_path()
    if target.is_symlink():
        raise ValueError("Refusing symlinked secrets configuration")
    if not target.exists():
        return Settings({})
    if not target.is_file():
        raise ValueError("Configuration path must be a file")
    return Settings(dict(dotenv_values(target, interpolate=False, encoding="utf-8")))


def _new_secrets() -> dict[str, str]:
    gateway = secrets.token_hex(32)
    monitor = secrets.token_hex(32)
    return {
        "PURR_ENV": "development",
        "PURR_CLIENTS_JSON": json.dumps(
            [{"token": gateway, "tenant_id": "dev", "products": ["demo"]}],
            separators=(",", ":"),
        ),
        "PURR_SESSION_SIGNING_KEY": secrets.token_hex(32),
        "PURR_METRICS_TOKEN": monitor,
        "PURR_MODEL_BACKEND": "deterministic",
        "PURR_OPERATIONS_TOKEN": secrets.token_hex(32),
        "PURR_OPERATIONS_GATEWAY_TOKEN": gateway,
        "PURR_OPERATIONS_METRICS_TOKEN": monitor,
        "PURR_OPERATIONS_GATEWAY_URL": "http://127.0.0.1:8765",
        "PURR_OPERATIONS_MODEL_LABEL": "Development Gateway",
        "PURR_OPERATIONS_DEV_AUTO_AUTH": "1",
    }


def _migrate_legacy(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise ValueError("Refusing symlinked legacy secrets configuration")
    old = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(old, dict) or any(
        not isinstance(k, str) or not k.startswith("PURR_") for k in old
    ):
        raise ValueError("Legacy config must be a PURR_ settings object")
    migrated = {}
    for key, value in old.items():
        if isinstance(value, (list, dict)):
            migrated[key] = json.dumps(value, separators=(",", ":"))
        elif isinstance(value, str):
            migrated[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            migrated[key] = str(value)
        else:
            raise ValueError(f"Unsupported legacy config value: {key}")
    return migrated


def initialize(path: Path | None = None, *, legacy_path: Path | None = None) -> Path:
    target = path if path is not None else config_path()
    if os.environ.get("PURR_ENV", "development").lower() != "development":
        raise RuntimeError("Development secrets bootstrap disabled outside development")
    old = legacy_path if legacy_path is not None else legacy_config_path()
    if target.is_symlink() or target.exists():
        raise FileExistsError(".env already exists; refusing to overwrite credentials")
    values = _migrate_legacy(old) if old.is_file() or old.is_symlink() else _new_secrets()
    # Existing legacy values remain intact; add only the missing dev convenience flag.
    values.setdefault("PURR_OPERATIONS_DEV_AUTO_AUTH", "1")
    target.parent.mkdir(parents=True, exist_ok=True)
    # dotenv accepts JSON-quoted values and decodes escaping; no interpolation.
    content = (
        "# Project Purrfect — PRIVATE LOCAL CONFIGURATION\n"
        "# Ignored by Git. Never commit or share this file.\n\n"
        + "".join(f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in values.items())
    )
    with target.open("x", encoding="utf-8") as handle:
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass  # Windows ACLs remain controlled by the local account.
        handle.write(content)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Purr local .env configuration")
    parser.add_argument("action", choices=["init"])
    args = parser.parse_args()
    try:
        path = initialize()
    except FileExistsError:
        parser.error(".env already exists; refusing to overwrite credentials")
    print(f"Local configuration ready: {path}")
    if legacy_config_path().is_file():
        print("Credentials migrated from config/local.json. Check .env, then delete the old local JSON yourself.")
    else:
        print("Fresh secrets generated. Keep .env private.")


if __name__ == "__main__":
    main()
