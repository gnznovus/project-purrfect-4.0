import httpx
import pytest

from purrfect.ollama import OllamaModel


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": '{"objective_id":"translate"}'}}


class FakeClient:
    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def post(self, url, json):
        self.url = url
        self.payload = json
        assert url == "http://localhost:11434/api/chat"
        assert json["format"] == "json"
        assert json["stream"] is False
        assert json["options"]["temperature"] == 0
        return FakeResponse()


@pytest.mark.asyncio
async def test_ollama_adapter(monkeypatch):
    fake = FakeClient(1.0)
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: fake)
    output = await OllamaModel(timeout=1.0).complete("system", "user")
    assert output == '{"objective_id":"translate"}'
    assert fake.payload["messages"][0]["role"] == "system"
    assert fake.payload["keep_alive"] == "30m"
    assert fake.payload["options"]["num_predict"] == 160
    assert fake.payload["options"]["num_ctx"] == 2048
    assert isinstance(output.metrics, dict)


@pytest.mark.asyncio
async def test_structured_output_budget_and_metrics(monkeypatch):
    class MetricsResponse(FakeResponse):
        def json(self):
            return {"message": {"content": '{"intent":"product","target":"layout","response":null}'},
                    "total_duration": 2_000_000_000, "load_duration": 10_500_000,
                    "prompt_eval_duration": 500_000_000, "eval_duration": 1_250_000_000,
                    "prompt_eval_count": 100, "eval_count": 25, "done_reason": "stop"}

    class StructuredClient(FakeClient):
        async def post(self, url, json):
            self.payload = json
            return MetricsResponse()

    fake = StructuredClient(1.0)
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: fake)
    schema = {"type": "object", "properties": {"intent": {"type": "string"}}}
    output = await OllamaModel().complete('system', 'user', schema=schema, num_predict=80)
    assert fake.payload['format'] == schema
    assert fake.payload['options']['num_predict'] == 80
    assert output.metrics['load_ms'] == 10.5
    assert output.metrics['prompt_eval_tokens_per_second'] == 200
    assert output.metrics['eval_tokens_per_second'] == 20
    assert output.metrics['done_reason'] == 'stop'
    assert output.metrics['system_chars'] == 6
    assert output.metrics['response_chars'] == len(output)
