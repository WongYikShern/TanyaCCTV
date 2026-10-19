"""Exercise the visual bridge protocol with a fake SDK; never contacts Google."""
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def bridge(monkeypatch):
    spec = importlib.util.spec_from_file_location("visual_bridge_under_test",
        Path(__file__).resolve().parents[2] / "search_engine" / "visual_review_bridge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    class Client:
        def __init__(self, **kwargs):
            module.client_options = kwargs
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        @property
        def models(self):
            return self
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            if getattr(module, "fake_error", None):
                raise module.fake_error
            return SimpleNamespace(text=json.dumps({"results": []}))
    types = SimpleNamespace(Part=SimpleNamespace(from_text=lambda **kw: kw, from_bytes=lambda **kw: kw),
        HttpOptions=lambda **kw: kw, HttpRetryOptions=lambda **kw: kw, GenerateContentConfig=lambda **kw: kw,
        ThinkingConfig=lambda **kw: kw, ThinkingLevel=SimpleNamespace(MINIMAL="MINIMAL"))
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.Client = Client
    genai.types = types
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setenv("GEMINI_API_KEY", "FAKE-TEST-KEY-visual-not-real")
    monkeypatch.delenv("TANYA_VERIFY_MODEL", raising=False)
    payload = {"query": "black shirt", "candidates": [{"id": "0", "frames": [
        {"timestamp_sec": 0, "jpeg": "AA=="}]}]}
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
    return module, calls, payload


def test_default_model_and_structured_request(bridge, capsys):
    module, calls, _ = bridge
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "results": []}
    assert calls[0]["model"] == "gemini-3.8-flash"
    assert module.client_options["http_options"]["retry_options"] == {"attempts": 1}
    assert calls[0]["config"]["response_json_schema"] == module.SCHEMA
    # Model listing/countTokens did not establish that MINIMAL thinking was supported.
    # Let the provider use its supported default rather than forcing a rejected setting.
    assert "thinking_config" not in calls[0]["config"]


def test_provider_error_exposes_status_but_never_credential_message(bridge, capsys):
    module, _, _ = bridge
    class ClientError(Exception):
        code = 404
        message = "Request key FAKE-TEST-KEY-visual-not-real failed; see https://example.invalid/?key=FAKE-TEST-KEY-visual-not-real"
    module.fake_error = ClientError("https://example.invalid/?key=FAKE-TEST-KEY-visual-not-real")
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "HTTP 404" in json.loads(output)["error"]
    assert "FAKE-TEST-KEY" not in output and "example.invalid" not in output


def test_frame_limit_rejected_before_api_call(bridge, monkeypatch, capsys):
    module, calls, payload = bridge
    payload["candidates"][0]["frames"] *= 7
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
    assert module.main() == 1 and not calls
    assert json.loads(capsys.readouterr().out)["ok"] is False
