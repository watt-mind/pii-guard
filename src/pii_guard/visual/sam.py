"""SAM 3.1 segmentation on the Meta Model API (``POST /v1/responses``).

``sam-3.1`` is served only on the Responses API, not on Chat Completions. One request is made
per concept prompt (``"face"``, ``"signature"``): SAM 3.1 segments every instance of a
single noun phrase, and a combined prompt such as ``"face. signature"`` returned nothing in
testing. Every request sends ``"store": false`` (the API default is to store responses).

Observed response format (2026-10-26, synthetic images, see ``tests/fixtures/visual/``): a
normal Responses API object whose single ``output_text`` is a token string::

    <0f>0<|box;x1=71;y1=111;x2=169;y2=238;w=640;h=400|><|mask;x=0;y=0;data=128,99,~...|>,1<|box;...|><|mask;...|>

- ``<0f>``: frame marker (frame 0; SAM 3.1 also tracks objects through video frames);
- ``0``, ``1``, ...: object ids, objects separated by ``,``;
- ``box``: inclusive pixel corners in an image of size ``w`` x ``h``;
- ``mask``: ``data=H,W,~<base-85 payload>``, an undocumented entropy-coded bitmap kept
  opaquely in :class:`~pii_guard.visual.regions.SamMask`.

No object found → empty ``output_text``. The API returns no confidence scores.

Fail closed (ADR 0006): timeouts, HTTP errors, a non-``completed`` status and output that
does not parse raise :class:`~pii_guard.types.DetectionError`. Messages carry status codes
and counts only, never the image or the key.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from pii_guard.config import Settings, get_settings
from pii_guard.detection_profile import refuse_remote
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.image import encode_image, load_image
from pii_guard.visual.regions import Box, Region, SamMask

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_PROMPTS",
    "SamClient",
    "parse_sam_output",
]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "sam-3.1"
MODEL_ENV_VAR = "PII_GUARD_SAM_MODEL"
API_KEY_ENV_VAR = "PII_GUARD_SAM_API_KEY"

#: Concept prompts per visual entity type. One request per prompt; results are merged.
#: ``STAMP`` is listed but not segmented by default (its default policy is ``keep``).
#: ``SIGNATURE``: on the Meta API (2026-10-26) ``"signature"`` and ``"handwriting"`` returned
#: nothing for drawn or script-font signatures on synthetic documents, while
#: ``"squiggly line"`` found the pen scribbles; it may also cover other squiggles (over-masking
#: is the safe side). On 30 official specimen ID documents (``pii-guard eval visual
#: --prompt-study``, 2026-10-27) ``"signature"`` found 90 % of real signatures and
#: ``"squiggly line"`` none, so both stay: one for real documents, one for drawn ones.
#: ``ID_PHOTO``: on the same specimens ``"id photo"`` and ``"passport photo"`` returned nothing
#: (0/37 portraits), while ``"photo of a person"`` found 89 % at IoU >= 0.5 with 3 stray
#: regions; see ``eval/results/visual/``.
DEFAULT_PROMPTS: dict[EntityType, tuple[str, ...]] = {
    EntityType.FACE: ("face",),
    EntityType.SIGNATURE: ("signature", "squiggly line"),
    EntityType.ID_PHOTO: ("photo of a person",),
    EntityType.STAMP: ("stamp",),
}
DEFAULT_ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType.FACE,
    EntityType.SIGNATURE,
    EntityType.ID_PHOTO,
)

_RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

_FRAME_RE = re.compile(r"<(\d+)f>")
_OBJECT_RE = re.compile(
    r"(?P<id>\d+)<\|box;(?P<box>[^|]*)\|>(?:<\|mask;(?P<mask>[^|]*)\|>)?",
)
_KV_RE = re.compile(r"([a-z0-9]+)=([^;]*)")


def _kv(raw: str) -> dict[str, str]:
    return dict(_KV_RE.findall(raw))


def _parse_mask(raw: str | None) -> SamMask | None:
    if raw is None:
        return None
    fields = _kv(raw)
    data = fields.get("data", "")
    head, sep, payload = data.partition(",~")
    dims = head.split(",")
    if not sep or len(dims) != 2:
        raise DetectionError("SAM mask has an unexpected format")
    try:
        return SamMask(
            x=int(fields.get("x", "0")),
            y=int(fields.get("y", "0")),
            height=int(dims[0]),
            width=int(dims[1]),
            data=payload,
        )
    except ValueError as exc:
        raise DetectionError("SAM mask has an unexpected format") from exc


def parse_sam_output(
    text: str, entity_type: EntityType, image_size: tuple[int, int]
) -> list[Region]:
    """Parse a SAM 3.1 ``output_text`` into regions in an image of ``image_size`` (w, h).

    Boxes are rescaled if the API reports a different image size than ``image_size`` (scaled
    outwards, never smaller) and clipped to the image. Empty text means nothing was found.
    Text that is not empty but contains no well-formed object raises ``DetectionError``.
    """
    if not text.strip():
        return []
    width, height = image_size
    body = _FRAME_RE.sub("", text)
    regions: list[Region] = []
    consumed = 0
    for match in _OBJECT_RE.finditer(body):
        consumed += len(match.group(0))
        fields = _kv(match.group("box"))
        try:
            x1, y1, x2, y2 = (int(fields[k]) for k in ("x1", "y1", "x2", "y2"))
            ref_w = int(fields.get("w", width))
            ref_h = int(fields.get("h", height))
        except (KeyError, ValueError) as exc:
            raise DetectionError("SAM box has an unexpected format") from exc
        if ref_w <= 0 or ref_h <= 0:
            raise DetectionError("SAM box has an unexpected format")
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(ref_w - 1, x2), min(ref_h - 1, y2)
        if x2 < x1 or y2 < y1:
            raise DetectionError("SAM box has an unexpected format")
        box = Box(x1, y1, x2, y2)
        if (ref_w, ref_h) != (width, height):
            box = box.scaled(width / ref_w, height / ref_h)
            box = Box(box.x1, box.y1, min(box.x2, width - 1), min(box.y2, height - 1))
        regions.append(Region(entity_type, box, None, "sam", mask=_parse_mask(match.group("mask"))))
    # Everything left over should be object separators; anything else is a format change.
    leftover = _OBJECT_RE.sub("", body).replace(",", "").strip()
    if not regions or leftover:
        raise DetectionError("SAM output has an unexpected format")
    return regions


def _resolve_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.endswith("/responses") else f"{url}/responses"


class SamClient:
    """Segment visual personal data with SAM 3.1 over the Meta Responses API.

    Keyword-only, all optional; unset values come from the environment and :class:`Settings`:

    - ``base_url``: ``PII_GUARD_SAM_URL``, default ``https://api.meta.ai/v1`` (``/responses``
      is appended unless already there), so a self-hosted SAM 3.1 behind the same API shape
      works by configuration;
    - ``api_key``: ``PII_GUARD_SAM_API_KEY``, else ``META_API_KEY``;
    - ``model``: ``PII_GUARD_SAM_MODEL``, default ``sam-3.1``;
    - ``prompts``: concept prompts per entity type (default :data:`DEFAULT_PROMPTS`);
    - ``timeout``: seconds per request; ``max_retries``: extra attempts after a timeout,
      transport error or retryable HTTP status (429/5xx).
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | SecretStr | None = None,
        model: str | None = None,
        prompts: Mapping[EntityType, Sequence[str]] | None = None,
        timeout: float = 60.0,
        max_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        refuse_remote(settings, "SAM segmentation")
        self._settings = settings
        self.url = _resolve_url(base_url or settings.sam_url or DEFAULT_BASE_URL)
        if api_key is None:
            # An explicitly emptied PII_GUARD_SAM_API_KEY disables SAM even when META_API_KEY
            # (or the repo .env) has a key: the smoke stack is offline by contract (LAB-1255).
            # Empty counts as unset everywhere else (Settings ignores empty values too).
            env_key = os.environ.get(API_KEY_ENV_VAR)
            api_key = (env_key or None) if env_key is not None else settings.meta_api_key
        self._api_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        self.model = model or os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL
        self.prompts: dict[EntityType, tuple[str, ...]] = {
            EntityType(k): tuple(v) for k, v in (prompts or DEFAULT_PROMPTS).items()
        }
        for entity_type, texts in self.prompts.items():
            if not entity_type.is_visual:
                raise ValueError(f"{entity_type.value} is not a visual entity type")
            if not texts or not all(isinstance(t, str) and t.strip() for t in texts):
                raise ValueError(f"empty prompt for {entity_type.value}")
        if timeout <= 0 or max_retries < 0:
            raise ValueError("timeout must be > 0 and max_retries >= 0")
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport

    def __repr__(self) -> str:  # never the key
        return f"SamClient(url={self.url!r}, model={self.model!r})"

    @property
    def configured(self) -> bool:
        """True when an API key is set (without one every call fails closed)."""
        return bool(self._api_key)

    def segment(
        self,
        image: bytes,
        entity_types: Sequence[EntityType | str] | None = None,
    ) -> list[Region]:
        """Return the regions of ``entity_types`` (default ``FACE``, ``SIGNATURE``,
        ``ID_PHOTO``) found in ``image``.

        The image is re-encoded from pixels as PNG before it is sent (no metadata leaves).
        Raises :class:`DetectionError` on any failure.
        """
        if not self._api_key:
            raise DetectionError("SAM client has no API key configured")
        types = [EntityType(t) for t in (entity_types or DEFAULT_ENTITY_TYPES)]
        missing = [t.value for t in types if t not in self.prompts]
        if missing:
            raise DetectionError(f"no SAM prompt configured for {', '.join(missing)}")
        try:
            decoded = load_image(bytes(image))
        except ValueError as exc:
            raise DetectionError("image could not be decoded for segmentation") from exc
        data_url = "data:image/png;base64," + base64.b64encode(encode_image(decoded)).decode()

        from pii_guard.visual.ocr import check_deadline  # local import: ocr never imports sam

        regions: list[Region] = []
        with self._client() as client:
            for entity_type in types:
                for prompt in self.prompts[entity_type]:
                    # The request's image deadline (LAB-1234): stop before a prompt whose
                    # time is already up, so a timed-out request frees its image-pool slot
                    # instead of holding it for prompts x timeout x (1 + retries).
                    check_deadline()
                    text = self._request(client, prompt, data_url)
                    regions.extend(parse_sam_output(text, entity_type, decoded.size))
        logger.debug("sam: %d region(s) for %s", len(regions), ",".join(t.value for t in types))
        return regions

    def payload(self, prompt: str, data_url: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(self.timeout),
            transport=self._transport,
        )

    def _request(self, client: httpx.Client, prompt: str, data_url: str) -> str:
        from pii_guard.visual.ocr import remaining  # local import: ocr never imports sam

        refuse_remote(self._settings, "SAM segmentation")
        payload = self.payload(prompt, data_url)
        last: str = "no attempt"
        for _attempt in range(self.max_retries + 1):
            # Cap this request at the image deadline and skip retries once it is up
            # (LAB-1234): each call gets at most the time the request still has.
            left = remaining()
            if left is not None and left <= 0:
                raise DetectionError("SAM request ran past the image deadline")
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
                raise DetectionError(f"SAM request failed: HTTP {response.status_code}")
            return _output_text(response)
        raise DetectionError(f"SAM request failed: {last}")


def _output_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError as exc:
        raise DetectionError("SAM response is not JSON") from exc
    if not isinstance(body, dict):
        raise DetectionError("SAM response has an unexpected format")
    if body.get("error"):
        raise DetectionError("SAM response reports an error")
    if body.get("status") != "completed":
        raise DetectionError(f"SAM response status is {str(body.get('status'))[:32]!r}")
    output = body.get("output")
    if not isinstance(output, list):
        raise DetectionError("SAM response has an unexpected format")
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if not isinstance(text, str):
                    raise DetectionError("SAM response has an unexpected format")
                texts.append(text)
    if not texts:
        raise DetectionError("SAM response has no output text")
    return "".join(texts)
