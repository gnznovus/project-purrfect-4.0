"""Ollama text adapter, isolated behind the TextModel protocol."""

import httpx


class OllamaCompletion(str):
    """Text with Ollama performance counters; compatible with existing callers."""

    def __new__(cls, content: str, metrics: dict):
        obj = str.__new__(cls, content)
        obj.metrics = metrics
        return obj


class OllamaModel:
    def __init__(
        self,
        model: str = "llama3.2:3b",
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def complete(self, system: str, user: str, *, temperature: float = 0.0) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_predict": 160, "num_ctx": 2048},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()

        content = body.get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError("Ollama returned no text content")
        metrics = {}
        for key in ("total_duration", "load_duration", "prompt_eval_duration",
                    "eval_duration"):
            value = body.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics[key.replace("_duration", "_ms")] = round(value / 1_000_000)
        for key in ("prompt_eval_count", "eval_count"):
            value = body.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                metrics[key] = value
        return OllamaCompletion(content, metrics)
