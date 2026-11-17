"""Ollama inference adapter with complete and native NDJSON streaming."""
import json
import httpx


class OllamaModel:
    def __init__(
        self, model: str = "llama3.2:3b",
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _payload(self, system: str, user: str, stream: bool) -> dict:
        return {
            "model": self.model, "stream": stream,
            "options": {"temperature": 0.3},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    async def complete(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/chat", json=self._payload(system, user, False))
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned no text content")
        return content

    async def stream(self, system: str, user: str):
        done = False
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat",
                json=self._payload(system, user, True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    packet = json.loads(line)
                    if packet.get("error"):
                        raise RuntimeError("Inference engine reported an error")
                    content = packet.get("message", {}).get("content", "")
                    if not isinstance(content, str):
                        raise ValueError("Ollama returned invalid stream content")
                    if content:
                        yield content
                    if packet.get("done") is True:
                        done = True
                        break
        if not done:
            raise RuntimeError("Ollama stream ended before completion")
