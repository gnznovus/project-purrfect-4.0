"""Standalone local HTTP server."""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from purrfect.ollama import OllamaModel
from purrfect.provider import Purr
from purrfect.sophira_storage import DurableSophira

def serve():
    host = os.getenv("PURR_HOST", "127.0.0.1")
    port = int(os.getenv("PURR_PORT", "8765"))
    token = os.getenv("PURR_API_TOKEN")
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise ValueError("Non-loopback binding requires PURR_API_TOKEN")
    backend = os.getenv("PURR_MODEL_BACKEND", "deterministic").lower()
    if backend not in ("deterministic", "ollama"):
        raise ValueError("Invalid inference backend")
    model = OllamaModel(model=os.getenv("PURR_OLLAMA_MODEL", "llama3.2:3b"),
                        base_url=os.getenv("PURR_OLLAMA_URL", "http://localhost:11434")) if backend == "ollama" else None
    db = os.getenv("PURR_SOPHIA_DB")
    provider = Purr(catalog=DurableSophira(db) if db else None, model=model)

    class Handler(BaseHTTPRequestHandler):
        def write_json(self, status, body):
            content = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        def authorized(self):
            return token is None or secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)
        def do_GET(self):
            if urlsplit(self.path).path != "/v1/health":
                return self.write_json(404, {"error": "Not found"})
            if not self.authorized():
                return self.write_json(401, {"error": "Unauthorized"})
            return self.write_json(200, {"service": "purr", "status": "healthy"})
        def do_POST(self):
            if urlsplit(self.path).path != "/v1/chat":
                return self.write_json(404, {"error": "Not found"})
            if not self.authorized():
                return self.write_json(401, {"error": "Unauthorized"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.write_json(415, {"error": "JSON required"})
            try:
                count = int(self.headers.get("Content-Length", "0"))
                if not 0 < count <= 16384:
                    raise ValueError("Invalid request size")
                result = provider.respond(json.loads(self.rfile.read(count)))
            except (ValueError, TypeError, KeyError) as exc:
                return self.write_json(400, {"error": str(exc)})
            except Exception:
                return self.write_json(503, {"error": "Provider unavailable"})
            return self.write_json(200, result)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
