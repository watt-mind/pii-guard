"""Run the documented clients offline: real cURL, real SDK, mocked provider, synthetic only."""

from __future__ import annotations

import importlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIError, OpenAI
from PIL import Image

from pii_guard.api.app import create_app
from pii_guard.config import Settings

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "integrations"
EMAIL = "sample.person@example.com"
GUARD_KEY = "synthetic-guard-credential"
PROVIDER_KEY = "synthetic-provider-credential"


@pytest.fixture
def examples(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(EXAMPLES))
    monkeypatch.setenv("GUARD_BASE_URL", "http://127.0.0.1:8787/v1")
    monkeypatch.setenv("GUARD_MODEL", "synthetic-model")
    monkeypatch.setenv("GUARD_API_KEY", GUARD_KEY)
    return tuple(importlib.import_module(name) for name in ("common", "curl_chat", "openai_chat"))


@pytest.mark.parametrize("stream", [False, True])
def test_sdk_uses_guard_and_restores_provider_placeholders(examples, capsys, stream: bool) -> None:
    common, _, sdk = examples
    forwarded = []

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        forwarded.append(body)
        assert request.headers["authorization"] == "Bearer " + PROVIDER_KEY
        masked = body["messages"][0]["content"]
        assert EMAIL not in masked
        assert "[[EMAIL_" in masked
        answer = masked[masked.index("[[EMAIL_") :].split("]]", 1)[0] + "]]"
        choice = {"index": 0, "message": {"role": "assistant", "content": answer}}
        base = {"id": "synthetic", "created": 0, "model": "synthetic-model"}
        if not stream:
            choice["finish_reason"] = "stop"
            return httpx.Response(
                200, json={**base, "object": "chat.completion", "choices": [choice]}
            )
        chunks = [
            {"delta": {"role": "assistant"}, "finish_reason": None},
            # Split inside a placeholder: the guard, not the client, must buffer it.
            {"delta": {"content": answer[:5]}, "finish_reason": None},
            {"delta": {"content": answer[5:]}, "finish_reason": None},
            {"delta": {}, "finish_reason": "stop"},
        ]
        events = [
            {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, **chunk}]}
            for chunk in chunks
        ]
        events.append({**base, "object": "chat.completion.chunk", "choices": [], "usage": {}})
        content = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(
            200,
            text=content + "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    app = create_app(
        Settings(
            tenant_key="00" * 32,
            api_token=GUARD_KEY,
            upstream_base_url="https://upstream.example/v1",
            upstream_api_key=PROVIDER_KEY,
        )
    )
    app.state.gateway_transport = httpx.MockTransport(upstream)
    with (
        TestClient(app) as guard,
        OpenAI(
            base_url="http://127.0.0.1:8787/v1", api_key=GUARD_KEY, http_client=guard, max_retries=0
        ) as client,
    ):
        sdk.chat(client, common.read_request(["--stream"] if stream else []))
    assert len(forwarded) == 1
    assert capsys.readouterr().out == EMAIL + "\n"


def test_sdk_surfaces_error_inside_http_200_stream(examples, capsys) -> None:
    common, _, sdk = examples
    event = {"error": {"code": "stream_failed", "message": "the response stream failed"}}
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            text="data: " + json.dumps(event) + "\n\n",
            headers={"content-type": "text/event-stream"},
        )
    )
    with (
        httpx.Client(transport=transport) as http_client,
        OpenAI(api_key=GUARD_KEY, http_client=http_client, max_retries=0) as client,
        pytest.raises(APIError),
    ):
        sdk.chat(client, common.read_request(["--stream"]))
    assert capsys.readouterr().out == ""


def test_sdk_rejects_stream_without_finish_event(examples) -> None:
    common, _, sdk = examples
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"}
        )
    )
    with (
        httpx.Client(transport=transport) as http_client,
        OpenAI(api_key=GUARD_KEY, http_client=http_client, max_retries=0) as client,
        pytest.raises(ValueError, match="finish event"),
    ):
        sdk.chat(client, common.read_request(["--stream"]))


@pytest.mark.parametrize("stream", [False, True])
def test_curl_runs_with_key_on_stdin_and_valid_json(examples, monkeypatch, capfd, stream) -> None:
    _, curl, _ = examples
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers.get("Authorization"), body))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"data: [DONE]\n\n" if stream else b'{"synthetic":true}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("GUARD_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("GUARD_MODEL", 'synthetic-"quoted-model"')
    real_run = curl.subprocess.run

    def check_arguments(command, **kwargs):
        assert GUARD_KEY not in repr(command)
        assert GUARD_KEY in kwargs["input"]
        return real_run(command, **kwargs)

    monkeypatch.setattr(curl.subprocess, "run", check_arguments)
    try:
        assert curl.main(["--stream"] if stream else []) == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    path, authorization, body = received[0]
    assert path == "/v1/chat/completions"
    assert authorization == "Bearer " + GUARD_KEY
    assert body["model"] == 'synthetic-"quoted-model"'
    assert body["stream"] is stream
    assert EMAIL in body["messages"][0]["content"]
    output = capfd.readouterr()
    assert GUARD_KEY not in output.out + output.err


def test_image_is_inline_png_and_project_endpoints_refuse_it(
    examples, monkeypatch, tmp_path
) -> None:
    common, _, _ = examples
    image = tmp_path / "synthetic.png"
    Image.new("RGB", (30, 20), "white").save(image)
    request = common.read_request(["--image", str(image)])
    parts = request.body["messages"][0]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    monkeypatch.setenv("GUARD_BASE_URL", "https://guard.example/e/synthetic-endpoint/v1")
    with pytest.raises(ValueError, match="Project endpoints do not support images"):
        common.read_request(["--image", str(image)])


def test_generator_creates_synthetic_png(examples, monkeypatch, tmp_path, capsys) -> None:
    generator = importlib.import_module("make_synthetic_image")
    monkeypatch.setattr(generator.tempfile, "mkdtemp", lambda **_: str(tmp_path))
    saved = []
    original_save = Image.Image.save

    def save_to_memory(image, path):
        saved.append(path)
        buffer = io.BytesIO()
        original_save(image, buffer, format="PNG")
        assert buffer.getvalue().startswith(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr(Image.Image, "save", save_to_memory)
    generator.main()
    assert saved == [tmp_path / "synthetic.png"]
    assert capsys.readouterr().out == str(saved[0]) + "\n"


@pytest.mark.parametrize(
    "url",
    [
        "https://credential@guard.example/v1",
        "https://guard.example/v1?key=synthetic",
        "https://guard.example/v1#synthetic",
    ],
)
def test_credentials_cannot_be_put_in_url(examples, monkeypatch, url) -> None:
    common, _, _ = examples
    monkeypatch.setenv("GUARD_BASE_URL", url)
    with pytest.raises(ValueError, match="GUARD_BASE_URL"):
        common.read_request([])
