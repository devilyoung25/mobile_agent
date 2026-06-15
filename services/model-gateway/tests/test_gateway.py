import pytest
from fastapi.testclient import TestClient
from model_gateway import catalog
from model_gateway.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    catalog.reset_state()
    yield
    catalog.reset_state()


def _configure_providers(monkeypatch, *, ollama=True, openrouter=True) -> None:
    if ollama:
        monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
        monkeypatch.setenv("GATEWAY_OLLAMA_BASE_URL", "https://ollama.test/v1")
    else:
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    if openrouter:
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        monkeypatch.setenv("GATEWAY_OPENROUTER_BASE_URL", "https://or.test/api/v1")
        monkeypatch.setenv("GATEWAY_OPENROUTER_MODELS", "openrouter/free")
    else:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


async def _fake_discover(provider):
    return ["coder-x"] if provider.id == "ollama" else list(provider.static_models)


def test_health() -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_models_tagged_with_provider_and_available(monkeypatch) -> None:
    _configure_providers(monkeypatch)
    monkeypatch.setattr(catalog, "_discover", _fake_discover)

    data = client.get("/v1/models").json()["data"]

    by_id = {m["id"]: m for m in data}
    assert by_id["coder-x"]["provider"] == "ollama"
    assert by_id["coder-x"]["available"] is True
    assert by_id["openrouter/free"]["provider"] == "openrouter"
    for field in ("max_input_tokens", "efforts", "default_effort"):
        assert field in by_id["coder-x"]


def test_providers_grouped_for_tabs(monkeypatch) -> None:
    _configure_providers(monkeypatch)
    monkeypatch.setattr(catalog, "_discover", _fake_discover)

    providers = {p["id"]: p for p in client.get("/v1/providers").json()["providers"]}

    assert {"ollama", "openrouter"} <= providers.keys()
    assert providers["ollama"]["label"] == "Ollama Cloud"
    assert any(m["id"] == "coder-x" for m in providers["ollama"]["models"])
    assert any(m["id"] == "openrouter/free" for m in providers["openrouter"]["models"])


def test_chat_routes_to_provider_drops_params(monkeypatch) -> None:
    _configure_providers(monkeypatch, openrouter=False)
    monkeypatch.setattr(catalog, "_discover", _fake_discover)
    captured: dict = {}

    class FakeResp:
        content = b'{"ok": true}'
        status_code = 200
        headers = {"content-type": "application/json"}

    class FakeClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json, headers):
            captured.update(url=url, json=json, headers=headers)
            return FakeResp()

    monkeypatch.setattr("model_gateway.app.httpx.AsyncClient", FakeClient)

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "coder-x", "messages": [{"role": "user", "content": "hi"}], "reasoning_effort": "high"},
    )

    assert resp.status_code == 200
    assert captured["url"] == "https://ollama.test/v1/chat/completions"  # routed to ollama
    assert captured["json"]["model"] == "coder-x"
    assert "reasoning_effort" not in captured["json"]
    assert captured["headers"]["Authorization"] == "Bearer ollama-key"


def test_rate_limit_marks_model_unavailable(monkeypatch) -> None:
    _configure_providers(monkeypatch, openrouter=False)
    monkeypatch.setattr(catalog, "_discover", _fake_discover)

    class Resp429:
        content = b'{"error": "rate limited"}'
        status_code = 429
        headers = {"retry-after": "30", "content-type": "application/json"}

    class FakeClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json, headers):
            return Resp429()

    monkeypatch.setattr("model_gateway.app.httpx.AsyncClient", FakeClient)

    resp = client.post("/v1/chat/completions", json={"model": "coder-x", "messages": []})
    assert resp.status_code == 429
    assert catalog.is_available("coder-x") is False

    entry = next(m for m in client.get("/v1/models").json()["data"] if m["id"] == "coder-x")
    assert entry["available"] is False


def test_unknown_model_without_fallback_is_404(monkeypatch) -> None:
    _configure_providers(monkeypatch)
    monkeypatch.setattr(catalog, "_discover", _fake_discover)
    monkeypatch.delenv("MODEL_GATEWAY_DEFAULT_UPSTREAM_MODEL", raising=False)

    resp = client.post("/v1/chat/completions", json={"model": "nope", "messages": []})
    assert resp.status_code == 404


def test_inbound_auth_enforced_when_configured(monkeypatch) -> None:
    _configure_providers(monkeypatch)
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "secret")

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "coder-x", "messages": []},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401
