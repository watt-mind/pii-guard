"""The real HTTP server must not log bearer handles or caller query values (LAB-1753)."""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn

from pii_guard import cli


@pytest.mark.parametrize("reload", [False, True])
def test_serve_disables_access_logs_even_for_reload_workers(
    monkeypatch: pytest.MonkeyPatch, reload: bool
) -> None:
    captured: dict[str, Any] = {}

    def run(app: str, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setenv("PII_GUARD_LOG_LEVEL", "debug")
    assert cli.main(["serve", *(["--reload"] if reload else [])]) == 0
    assert captured["reload"] is reload
    assert captured["access_log"] is False


def test_live_serve_logs_route_templates_without_session_or_query(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    session = "synthetic_session_marker"
    query = "synthetic.person@example.org"
    caplog.set_level(logging.INFO, logger="pii_guard.api.access")
    monkeypatch.setenv("PII_GUARD_DETECTORS", "rules")

    def run(app: str, **kwargs: Any) -> None:
        # Keep pytest's logging handlers; run the same server configuration as the CLI.
        config = uvicorn.Config(app, **kwargs, lifespan="off", log_config=None)
        server = uvicorn.Server(config)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert server.started
                with httpx.Client(trust_env=False) as client:
                    response = client.get(
                        f"http://127.0.0.1:{port}/s/{session}/v1/traffic",
                        params={"probe": query},
                    )
                assert response.status_code == 404  # Traffic capture is off by default.
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                assert not thread.is_alive()

    monkeypatch.setattr(uvicorn, "run", run)
    assert cli.main(["serve"]) == 0
    server_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith(("pii_guard", "uvicorn"))
    ]
    assert any("GET /v1/traffic 404" in message for message in server_logs)
    assert all(session not in message and query not in message for message in server_logs)
