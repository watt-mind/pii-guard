"""Visual personal data: SAM 3.1 regions, OCR text regions, and image masking.

See ``docs/architecture.md`` (visual) and ``docs/entities.md`` (visual entities).

    from pii_guard.detect.rules import RuleDetector
    from pii_guard.visual import SamClient, TesseractOcr, mask_visual

    result = mask_visual(png_bytes, sam=SamClient(), ocr=TesseractOcr(),
                         detectors=[RuleDetector()])
    result.image    # masked PNG, metadata stripped
    result.regions  # what was covered (no raw values)
"""

from pii_guard.visual.image import DEFAULT_FILL, encode_image, load_image, mask_image
from pii_guard.visual.ocr import (
    OcrEngine,
    OcrWord,
    TesseractOcr,
    join_words,
    tesseract_available,
    text_regions,
)
from pii_guard.visual.pipeline import VisualResult, analyze_image, mask_visual
from pii_guard.visual.regions import Box, Region, SamMask
from pii_guard.visual.sam import DEFAULT_PROMPTS, SamClient, parse_sam_output

__all__ = [
    "DEFAULT_FILL",
    "DEFAULT_PROMPTS",
    "Box",
    "OcrEngine",
    "OcrWord",
    "Region",
    "SamClient",
    "SamMask",
    "TesseractOcr",
    "VisualResult",
    "analyze_image",
    "encode_image",
    "join_words",
    "load_image",
    "mask_image",
    "mask_visual",
    "parse_sam_output",
    "tesseract_available",
    "text_regions",
]
