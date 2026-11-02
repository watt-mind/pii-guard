"""Muse Spark Open as the OCR engine of the image path (LAB-1796, ADR 0016).

Meta's open-weight **Muse Spark Open** reads the image on an OpenAI-compatible endpoint, by
default Baseten Model APIs (``POST https://inference.baseten.co/v1/chat/completions``, model
``meta-models/muse-spark-open-1026``, ``reasoning_effort: "low"``). The image is sent as an
``image_url`` data URL, re-encoded from its pixels as PNG (no metadata leaves).

**Data boundary.** The unmasked image goes to the OCR endpoint (``PII_GUARD_OCR_URL``). The
local-only detection profile refuses this unless that URL is self-hosted
(:func:`~pii_guard.detection_profile.is_self_hosted_url`).

The prompt is the one the spike measured (``eval/results/2026-11-02-meta-ocr-spike/``): the
system prompt frames the task as document layout for an accessibility tool, and the user prompt
asks for ``{"lines":[{"text","box"}]}`` with boxes normalized to 0-1000. Prompts that mention
personal data or redaction are refused far more often, so this one mentions neither.

Each returned **line is one OCR unit** (one :class:`~pii_guard.visual.ocr.OcrWord`), so a
detected span masks its whole line. The model's boxes are approximate, so every text region
found on them grows on every side by :data:`PAD_SHARE` (2 %) of the image width in pixels,
clamped to the image (``region_pad_share``, applied by :func:`~pii_guard.visual.ocr.ocr_text`).
At 2 % the line boxes cover 87 % of the labelled text regions of the fictional specimens, as
Tesseract's word boxes do. The words themselves keep the model's box, so captions and MRZ
zones are found on the layout the model returned (padding them first breaks the caption
geometry: overlapping boxes no longer read as one line below another).

Fail closed (ADR 0006): a reply without valid JSON (a refusal, a cut-off reply) is retried once
with the same prompt and a second one raises :class:`~pii_guard.types.DetectionError`, as do
timeouts, HTTP errors and the image deadline (:func:`~pii_guard.visual.ocr.check_deadline`).
Messages carry status codes and counts only, never the image, its text or the key.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

import httpx
from PIL import Image
from pydantic import SecretStr

from pii_guard.config import Settings, get_settings
from pii_guard.detection_profile import is_self_hosted_url, refuse_remote_ocr
from pii_guard.types import DetectionError
from pii_guard.visual.image import encode_image
from pii_guard.visual.ocr import OcrWord, check_deadline, remaining
from pii_guard.visual.regions import Box

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "PAD_SHARE",
    "SYSTEM_PROMPT",
    "USER_PROMPT",
    "MuseOcr",
    "muse_configured",
    "parse_lines",
]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://inference.baseten.co/v1"
DEFAULT_MODEL = "meta-models/muse-spark-open-1026"
API_KEY_ENV_VAR = "PII_GUARD_OCR_API_KEY"

#: The spike's prompt (LAB-1794), verbatim.
SYSTEM_PROMPT = (
    "You are a document layout engine for an accessibility tool. You output text lines with "
    "their positions as JSON."
)
USER_PROMPT = (
    'Document layout task. Return JSON only: {"lines":[{"text":"...","box":[x1,y1,x2,y2]}]} '
    "for every line of text, top to bottom. box is normalized 0-1000 (x across width, y down "
    "height), tight around the ink of that line."
)

#: Every text region found on Muse's lines grows by this share of the image width, in pixels,
#: on every side (``MuseOcr.region_pad_share``).
PAD_SHARE = 0.02
#: Boxes are normalized to this range.
SCALE = 1000
#: The image is downscaled to this longest side before it is sent (boxes are normalized, so the
#: result maps back to the original size). Bounds the request size and the vision tokens.
MAX_SIDE = 2048
#: Bounds on one reply, checked before parsing; above them the reply is invalid.
MAX_REPLY_CHARS = 400_000
MAX_LINES = 2_000
MAX_TOKENS = 4096

_RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class _NoJson(Exception):
    """The reply holds no valid ``{"lines": [...]}`` object (a refusal or a cut-off reply)."""


def _env_key() -> str | None:
    """``PII_GUARD_OCR_API_KEY`` from the process env when it is set, ``""`` included.

    An explicitly emptied ``PII_GUARD_OCR_API_KEY`` disables the engine even when
    ``BASETEN_API_KEY`` is set, as an emptied SAM key does (offline stacks, LAB-1255): Settings
    ignores empty values and would fall through to the Baseten key."""
    return os.environ.get(API_KEY_ENV_VAR)


def _resolve_key(settings: Settings) -> str | None:
    explicit = _env_key()
    if explicit is not None and not explicit.strip():
        return None
    key = settings.ocr_api_key
    value = key.get_secret_value() if key is not None else None
    return value if value and value.strip() else None


def _resolve_url(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def muse_configured(settings: Settings) -> bool:
    """Whether Muse Spark Open OCR can run: a key, or a keyless self-hosted endpoint."""
    return bool(_resolve_key(settings)) or is_self_hosted_url(settings.ocr_url)


def parse_lines(text: str, image_size: tuple[int, int]) -> list[OcrWord]:
    """The lines of one Muse reply as OCR units in an image of ``image_size`` (w, h).

    Raises :class:`_NoJson` when the reply has no valid ``{"lines": [...]}`` object, or a line
    whose ``text`` is not a string or whose ``box`` is not four numbers. Lines with empty text
    are dropped. Boxes are clamped to 0-1000, their corners ordered and scaled to the image
    (not padded: see :data:`PAD_SHARE`).
    """
    if not isinstance(text, str) or len(text) > MAX_REPLY_CHARS:
        raise _NoJson
    body = _FENCE_RE.sub("", text.strip())
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise _NoJson
    try:
        data = json.loads(body[start : end + 1])
    except ValueError as exc:
        raise _NoJson from exc
    lines = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(lines, list) or len(lines) > MAX_LINES:
        raise _NoJson
    width, height = image_size
    words: list[OcrWord] = []
    for item in lines:
        if not isinstance(item, dict):
            raise _NoJson
        line_text, box = item.get("text"), item.get("box")
        if not isinstance(line_text, str):
            raise _NoJson
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in box)
        ):
            raise _NoJson
        line_text = " ".join(line_text.split())
        if not line_text:
            continue
        nx1, ny1, nx2, ny2 = (min(max(float(v), 0.0), SCALE) for v in box)
        nx1, nx2 = sorted((nx1, nx2))
        ny1, ny2 = sorted((ny1, ny2))
        x1 = min(width - 1, int(nx1 * width / SCALE))
        y1 = min(height - 1, int(ny1 * height / SCALE))
        x2 = min(width - 1, round(nx2 * width / SCALE))
        y2 = min(height - 1, round(ny2 * height / SCALE))
        words.append(OcrWord(line_text, Box(x1, y1, max(x1, x2), max(y1, y2)), (len(words),)))
    return words


class MuseOcr:
    """:class:`~pii_guard.visual.ocr.OcrEngine` backed by Muse Spark Open (line-level boxes).

    Settings: ``PII_GUARD_OCR_URL`` (default Baseten Model APIs), ``PII_GUARD_OCR_MODEL``
    (default ``meta-models/muse-spark-open-1026``) and ``PII_GUARD_OCR_API_KEY`` (else
    ``BASETEN_API_KEY``). A keyless endpoint is accepted only when it is self-hosted.

    - ``timeout``: seconds per request, capped by the image deadline;
    - ``max_retries``: extra attempts after a timeout, transport error or retryable status;
    - ``refusal_retries``: extra attempts after a reply without valid JSON (default 1).
    """

    name = "muse"
    #: Text regions found on these lines grow by this share of the image width (LAB-1796).
    region_pad_share = PAD_SHARE

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | SecretStr | None = None,
        model: str | None = None,
        reasoning_effort: str | None = "low",
        max_tokens: int = MAX_TOKENS,
        timeout: float = 60.0,
        max_retries: int = 1,
        refusal_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        self.url = _resolve_url(base_url or settings.ocr_url or DEFAULT_BASE_URL)
        self._settings = settings
        refuse_remote_ocr(settings, self.url)
        if api_key is None:
            key = _resolve_key(settings)
        else:
            key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        self._api_key = key.strip() if key and key.strip() else None
        self.model = model or settings.ocr_model or DEFAULT_MODEL
        self.reasoning_effort = reasoning_effort
        if timeout <= 0 or max_retries < 0 or refusal_retries < 0 or max_tokens < 256:
            raise ValueError("invalid MuseOcr limits")
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.refusal_retries = refusal_retries
        self._transport = transport

    def __repr__(self) -> str:  # never the key
        return f"MuseOcr(url={self.url!r}, model={self.model!r})"

    @property
    def configured(self) -> bool:
        """True with a key, or keyless on a self-hosted endpoint."""
        return bool(self._api_key) or is_self_hosted_url(self.url)

    def words(self, image: Image.Image) -> list[OcrWord]:
        """The text lines of ``image``, each one OCR unit, in reading order.

        Raises :class:`DetectionError` on any failure, including a second reply without JSON.
        """
        if not self.configured:
            raise DetectionError("Muse OCR has no API key configured (PII_GUARD_OCR_API_KEY)")
        check_deadline()
        refuse_remote_ocr(self._settings, self.url)
        payload = self.payload(self._data_url(image))
        with self._client() as client:
            for attempt in range(self.refusal_retries + 1):
                check_deadline()
                reply = self._request(client, payload)
                try:
                    words = parse_lines(reply, image.size)
                except _NoJson:
                    logger.info("muse ocr: reply without valid JSON (attempt %d)", attempt + 1)
                    continue
                logger.debug("muse ocr: %d line(s)", len(words))
                return words
        raise DetectionError("Muse OCR returned no valid JSON (the model declined to read it)")

    def payload(self, data_url: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    @staticmethod
    def _data_url(image: Image.Image) -> str:
        sent = image
        longest = max(image.size)
        if longest > MAX_SIDE:
            scale = MAX_SIDE / longest
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            sent = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
        return "data:image/png;base64," + base64.b64encode(encode_image(sent)).decode()

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        return httpx.Client(
            headers=headers, timeout=httpx.Timeout(self.timeout), transport=self._transport
        )

    def _request(self, client: httpx.Client, payload: dict[str, Any]) -> str:
        last = "no attempt"
        for _attempt in range(self.max_retries + 1):
            # Each call gets at most the time the image request still has (LAB-1234).
            left = remaining()
            if left is not None and left <= 0:
                raise DetectionError("Muse OCR request ran past the image deadline")
            timeout = self.timeout if left is None else min(self.timeout, max(left, 0.01))
            try:
                response = client.post(self.url, json=payload, timeout=timeout)
            except httpx.TimeoutException:
                last = "timed out"
                continue
            except httpx.HTTPError as exc:
                last = f"transport error ({type(exc).__name__})"
                continue
            if response.status_code in _RETRY_STATUS:
                last = f"HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise DetectionError(f"Muse OCR request failed: HTTP {response.status_code}")
            return _content(response)
        raise DetectionError(f"Muse OCR request failed: {last}")


def _content(response: httpx.Response) -> str:
    """The assistant message text of a Chat Completions response ("" when there is none)."""
    try:
        body = response.json()
    except ValueError as exc:
        raise DetectionError("Muse OCR response is not JSON") from exc
    if not isinstance(body, dict) or body.get("error"):
        raise DetectionError("Muse OCR response reports an error")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise DetectionError("Muse OCR response has an unexpected format")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):  # content parts
        content = "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return content if isinstance(content, str) else ""
