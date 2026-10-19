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
