"""Ollama text adapter, isolated behind the TextModel protocol."""

from time import perf_counter

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

    async def complete(self, system: str, user: str, *, temperature: float = 0.0,
                       schema: dict | None = None, num_predict: int = 160) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema if schema is not None else "json",
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": 2048},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        started = perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()

        content = body.get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError("Ollama returned no text content")
        metrics = {"http_ms": round((perf_counter() - started) * 1000, 2),
                   "done_reason": body.get("done_reason", "unknown"),
                   "system_chars": len(system), "user_chars": len(user),
                   "response_chars": len(content)}
        for key in ("total_duration", "load_duration", "prompt_eval_duration",
                    "eval_duration"):
            value = body.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics[key.replace("_duration", "_ms")] = round(value / 1_000_000, 2)
        for key in ("prompt_eval_count", "eval_count"):
            value = body.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                metrics[key] = value
        for prefix in ("prompt_eval", "eval"):
            duration = metrics.get(prefix + "_ms", 0)
            if duration > 0 and prefix + "_count" in metrics:
                metrics[prefix + "_tokens_per_second"] = round(
                    metrics[prefix + "_count"] * 1000 / duration, 2)
        if "total_ms" in metrics:
            metrics["transport_ms"] = round(max(0, metrics["http_ms"] - metrics["total_ms"]), 2)
        return OllamaCompletion(content, metrics)
