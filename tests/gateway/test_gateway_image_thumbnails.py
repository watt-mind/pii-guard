"""Through the gateway: an image call's traffic event carries a thumbnail of the masked image,
never the client's original (LAB-1188).

Synthetic only (ADR 0005): the Pillow-drawn card, mocked SAM and OCR of ``test_image_parts``.
"""

from __future__ import annotations

import base64
import io
import json

from fastapi.testclient import TestClient
from gateway_helpers import FakeLlm, MockUpstream
from PIL import Image
from test_image_parts import FACE, FakeOcr, H, Sam, W, data_url, make_app, messages_with, png

from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
from pii_guard.observability import Observability, ObservabilitySettings


def test_image_call_event_carries_the_masked_thumbnail_and_no_original() -> None:
    upstream, sam = MockUpstream(), Sam()
    app = make_app(upstream, sam)
    obs = Observability(ObservabilitySettings(traffic_log="masked"))
    base, config = app.state.gateway, GatewayConfig(mode=Mode.AUDIT)
    app.state.gateway = Gateway(
        settings=base.settings,
        vault=base.vault,
        config=config,
        detectors=build_mode_detectors(base.settings, config, llm_detector=FakeLlm()),
        transport=upstream.transport(),
        sam=base._sam,
        ocr=FakeOcr(),
        observability=obs,
    )
    original = png()
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": messages_with(data_url(original))},
        )
    assert response.status_code == 200, response.text
    (event,) = obs.traffic.recent()
    dumped = json.dumps(event)
    assert base64.b64encode(original).decode() not in dumped
    assert "Teszt Elek" not in dumped
    (thumb,) = event["request"]["thumbnails"]
    assert (thumb["index"], thumb["width"], thumb["height"]) == (0, W, H)
    head, _, payload = thumb["data"].partition(",")
    assert head == "data:image/webp;base64"
    image = Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGB")
    centre = ((FACE.x1 + FACE.x2) // 2, (FACE.y1 + FACE.y2) // 2)
    assert max(image.getpixel(centre)) < 24  # the face is blacked out
