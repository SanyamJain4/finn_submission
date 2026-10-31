import httpx

from app import http, llm
from app.config import settings


def _openai_settings(monkeypatch):
    # Settings is a frozen dataclass, so bypass __setattr__ and restore the originals afterwards.
    for name, value in (("llm_provider", "openai"), ("llm_api_key", "k"),
                        ("llm_base_url", "https://router.huggingface.co/v1"), ("llm_fast_model", "m"),
                        ("llm_smart_model", "m")):
        original = getattr(settings, name)
        object.__setattr__(settings, name, value)
        _restore.append((name, original))


_restore: list = []


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    while _restore:
        name, original = _restore.pop()
        object.__setattr__(settings, name, original)


def _patch_client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_openai_provider_retries_without_response_format(monkeypatch):
    _openai_settings(monkeypatch)
    seen = []

    def handler(req):
        body = req.read().decode()
        seen.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format unsupported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}], "usage": {}})

    _patch_client(monkeypatch, handler)
    text, _, _ = llm._call_provider("some-model", "sys", "prompt", 100)
    assert text == '{"a": 1}'
    assert seen == [True, False]


def test_key_rejection_message_is_provider_neutral(monkeypatch):
    _openai_settings(monkeypatch)
    monkeypatch.setattr(type(settings), "llm_enabled", property(lambda s: True))
    _patch_client(monkeypatch, lambda req: httpx.Response(401, json={"error": {"message": "bad token"}}))
    from pydantic import BaseModel

    class Out(BaseModel):
        a: int

    try:
        llm.complete_json(Out, "p", tier="fast", purpose="test", cache_ttl_s=0)
    except llm.LLMError as e:
        assert "openai" in str(e) and "Gemini" not in str(e)
        assert llm.public_message(e) == "the AI provider rejected the configured key"
    else:
        raise AssertionError("expected LLMError")


def test_public_message_hides_internal_detail():
    assert "unreachable" in llm.public_message(llm.LLMError("all models failed - gemini: HTTP 429 quota ..."))
    assert llm.public_message(llm.LLMUnavailable("x")) == "no AI model is configured"


def test_403_trips_breaker(monkeypatch):
    http._breaker.clear()
    monkeypatch.setattr(http, "_polite", lambda host: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    msgs = []
    for _ in range(5):
        try:
            http.fetch(client, "https://api.bseindia.com/x", "BSE")
        except http.SourceError as e:
            msgs.append(e.message)
    assert msgs[:3] == ["HTTP 403"] * 3
    assert all("unreachable" in m for m in msgs[3:])
    http._breaker.clear()
