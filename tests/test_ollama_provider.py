"""OllamaProvider — chamada padrão (complete) e a rodada de tool calling."""

from __future__ import annotations

import pytest

from core.errors import ProviderError
from core.settings import OllamaSettings
from providers.ollama_provider import OllamaProvider


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        return self._payload


def _provider(**overrides) -> OllamaProvider:
    return OllamaProvider(OllamaSettings(**overrides))


def test_chat_with_tools_returns_message_dict(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse(200, {"message": {"role": "assistant", "content": "", "tool_calls": []}})

    monkeypatch.setattr("providers.ollama_provider.requests.post", fake_post)
    provider = _provider()
    message = provider.chat_with_tools(
        [{"role": "user", "content": "oi"}], tools=[{"type": "function", "function": {"name": "x"}}]
    )
    assert message == {"role": "assistant", "content": "", "tool_calls": []}
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["tools"]
    assert captured["json"]["stream"] is False


def test_chat_with_tools_missing_model_raises_clear_error(monkeypatch):
    monkeypatch.setattr(
        "providers.ollama_provider.requests.post",
        lambda url, json, timeout: FakeResponse(404, {}),
    )
    provider = _provider(model="modelo-que-nao-existe")
    with pytest.raises(ProviderError, match="modelo-que-nao-existe"):
        provider.chat_with_tools([{"role": "user", "content": "oi"}], tools=[])


def test_chat_with_tools_missing_message_field_raises(monkeypatch):
    monkeypatch.setattr(
        "providers.ollama_provider.requests.post",
        lambda url, json, timeout: FakeResponse(200, {"unexpected": True}),
    )
    provider = _provider()
    with pytest.raises(ProviderError, match="message"):
        provider.chat_with_tools([{"role": "user", "content": "oi"}], tools=[])


def test_chat_with_tools_connection_error_raises_provider_error(monkeypatch):
    import requests

    def fake_post(url, json, timeout):
        raise requests.ConnectionError("recusado")

    monkeypatch.setattr("providers.ollama_provider.requests.post", fake_post)
    provider = _provider()
    with pytest.raises(ProviderError, match="tool loop"):
        provider.chat_with_tools([{"role": "user", "content": "oi"}], tools=[])
