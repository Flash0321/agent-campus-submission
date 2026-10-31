"""HTTP adapter protocol tests with no network or actual API credentials."""
import io
import json
import urllib.error

import pytest

from src import model_client
from src.model_client import ModelError, NoRedirect, RealClient, scrub


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.response).encode("utf-8"))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(model_client, "load_environment", lambda: None)
    monkeypatch.setenv("LLM_API_KEY", "dummy-test-credential-no-network")
    monkeypatch.setenv("LLM_BASE_URL", "https://unit-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "7")
    return RealClient()


def response():
    return {"model": "qwen-plus-2025-12-01", "choices": [{
        "message": {"role": "assistant", "content": "{}", "reasoning_content": "internal not returned"},
        "finish_reason": "stop",
    }], "usage": {"total_tokens": 2}}


def test_http_payload_and_tool_roundtrip_shape(client):
    opener = FakeOpener(response=response()); client.opener = opener
    result = client.complete(model="qwen-plus-2025-12-01", messages=[{"role": "user", "content": "query"}],
                             tools=[{"type": "function", "function": {"name": "search_documents"}}], tool_choice="none", stage="P4")
    request, timeout = opener.calls[0]
    payload = json.loads(request.data)
    assert request.full_url.endswith("/compatible-mode/v1/chat/completions")
    assert payload["enable_thinking"] is False and payload["parallel_tool_calls"] is False
    assert payload["tool_choice"] == "none" and "response_format" not in payload
    assert timeout == 7 and len(opener.calls) == 1
    assert "reasoning_content" not in result["message"]


def test_json_mode_is_separate_from_function_calling(client):
    opener = FakeOpener(response=response()); client.opener = opener
    client.complete(model="qwen-flash-2025-07-28", messages=[{"role": "user", "content": "JSON"}], json_mode=True, stage="P3")
    payload = json.loads(opener.calls[0][0].data)
    assert payload["response_format"] == {"type": "json_object"}
    assert "tools" not in payload and "parallel_tool_calls" not in payload


def test_complete_endpoint_not_appended_twice(client):
    client.base += "/chat/completions"
    client.opener = FakeOpener(response=response())
    client.complete(model="x", messages=[])
    assert client.opener.calls[0][0].full_url.count("/chat/completions") == 1


def test_network_error_is_counted_once_without_hidden_retry(client):
    client.opener = FakeOpener(error=urllib.error.URLError("transient"))
    with pytest.raises(ModelError) as exc:
        client.complete(model="x", messages=[])
    assert exc.value.code == "NETWORK_ERROR" and len(client.opener.calls) == 1


def test_provider_http_error_is_sanitized(client):
    body = json.dumps({"error": {"code": "InvalidApiKey", "message": "bad key: " + client.key}}).encode()
    client.opener = FakeOpener(error=urllib.error.HTTPError("https://example.invalid", 401, "Unauthorized", {}, io.BytesIO(body)))
    with pytest.raises(ModelError) as exc:
        client.complete(model="x", messages=[])
    assert client.key not in str(exc.value) and "[REDACTED]" in str(exc.value)
    assert exc.value.code == "HTTP_401:InvalidApiKey"
    assert len(client.opener.calls) == 1


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": []}]}, []])
def test_malformed_provider_response_becomes_model_error(client, body):
    client.opener = FakeOpener(response=body)
    with pytest.raises(ModelError) as exc:
        client.complete(model="x", messages=[])
    assert exc.value.code == "INVALID_API_RESPONSE"


@pytest.mark.parametrize("base", [
    "http://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://dashscope.aliyuncs.com.evil.invalid/v1",
    "https://user:password@dashscope.aliyuncs.com/v1",
    "https://dashscope.aliyuncs.com/v1?token=secret",
])
def test_invalid_endpoint_is_rejected_before_sending_credentials(client, base):
    client.base = base; client.opener = FakeOpener(response=response())
    with pytest.raises(ModelError):
        client.complete(model="x", messages=[])
    assert client.opener.calls == []


def test_empty_credentials_do_not_call_network(client):
    client.key = ""; client.opener = FakeOpener(response=response())
    with pytest.raises(ModelError) as exc:
        client.complete(model="x", messages=[])
    assert exc.value.code == "CONFIGURATION_MISSING" and client.opener.calls == []


def test_redirects_are_not_followed():
    assert NoRedirect().redirect_request(None, None, 302, "Moved", {}, "https://other.invalid") is None


def test_scrub_removes_auth_fields_and_reasoning_recursively(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "full-local-secret")
    assert scrub({"Authorization": "Bearer full-local-secret", "nested": [{"api_key": "x", "reasoning_content": "hidden", "message": "full-local-secret"}]}) == {
        "nested": [{"message": "[REDACTED]"}],
    }
