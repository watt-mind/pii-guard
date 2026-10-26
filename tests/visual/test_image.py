"""mask_image: solid fill over every region, metadata stripped, never the original bytes."""

from __future__ import annotations

import io

import pytest
from PIL import Image, PngImagePlugin
from visual_helpers import FACE_BOX, SIGNATURE_BOX, id_card_png, png_bytes, render_id_card

from pii_guard.types import EntityType, MaskingError
from pii_guard.visual import Box, Region, encode_image, load_image, mask_image

FILL = (0, 0, 0)


def region(box: Box, entity_type: EntityType = EntityType.FACE) -> Region:
    return Region(entity_type, box, None, "test")


def open_png(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def assert_filled(image: Image.Image, box: Box, fill: tuple[int, int, int]) -> None:
    rgb = image.convert("RGB")
    for y in range(box.y1, box.y2 + 1):
        for x in range(box.x1, box.x2 + 1):
            assert rgb.getpixel((x, y)) == fill, f"pixel ({x}, {y}) not covered"


def jpeg_with_exif() -> bytes:
    image = render_id_card()
    exif = Image.Exif()
    exif[0x010F] = "FictionalCam"  # Make
    exif[0x0131] = "editor-1.0"  # Software
    exif[0x9286] = "fictional comment"  # UserComment
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_every_region_is_fully_covered_with_the_fill_colour() -> None:
    regions = [region(FACE_BOX), region(SIGNATURE_BOX, EntityType.SIGNATURE)]
    masked = open_png(mask_image(id_card_png(), regions, padding=0))
    for r in regions:
        assert_filled(masked, r.box, FILL)
    # Pixels outside the boxes are untouched.
    assert masked.convert("RGB").getpixel((620, 380)) == (235, 240, 250)


def test_custom_fill_and_padding_grow_the_cover() -> None:
    box = Box(100, 100, 110, 110)
    masked = open_png(mask_image(id_card_png(), [region(box)], fill=(255, 0, 255), padding=3))
    assert_filled(masked, Box(97, 97, 113, 113), (255, 0, 255))
    assert masked.convert("RGB").getpixel((95, 95)) != (255, 0, 255)


def test_exif_is_stripped() -> None:
    source = jpeg_with_exif()
    assert Image.open(io.BytesIO(source)).getexif()  # the input really has EXIF
    for image_format in ("PNG", "JPEG", "WEBP"):
        out = mask_image(source, [region(FACE_BOX)], image_format=image_format)
        image = open_png(out)
        assert not image.getexif(), image_format
        assert "exif" not in image.info
        assert b"FictionalCam" not in out
        assert b"fictional comment" not in out
        if image_format == "PNG":  # lossy formats only approximate the fill colour
            assert_filled(image, Box(80, 120, 160, 230), FILL)


def test_png_text_chunks_and_icc_are_dropped() -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Fictional Author")
    source = png_bytes(render_id_card(), pnginfo=info, icc_profile=b"\0" * 128)
    out = mask_image(source, [])
    assert b"Fictional Author" not in out
    image = open_png(out)
    assert "Author" not in image.info and "icc_profile" not in image.info


def test_no_regions_still_reencodes_never_returns_the_input() -> None:
    source = jpeg_with_exif()
    out = mask_image(source, [])
    assert out != source
    assert open_png(out).format == "PNG"


def test_exif_orientation_is_applied_before_masking() -> None:
    # A 40x20 landscape image stored with "rotate 90 CW" orientation is 20x40 when viewed.
    image = Image.new("RGB", (40, 20), (255, 255, 255))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes())
    out = open_png(mask_image(buf.getvalue(), [region(Box(0, 0, 19, 9))], padding=0))
    assert out.size == (20, 40)
    assert_filled(out, Box(0, 0, 19, 9), FILL)


def test_transparent_pixels_are_flattened() -> None:
    image = Image.new("RGBA", (10, 10), (200, 10, 10, 0))  # hidden red under alpha 0
    out = open_png(mask_image(png_bytes(image), []))
    assert out.mode == "RGB"
    assert out.getpixel((5, 5)) == (255, 255, 255)


def test_boxes_are_clipped_and_outside_boxes_ignored() -> None:
    out = open_png(
        mask_image(
            id_card_png(),
            [region(Box(600, 380, 900, 900)), region(Box(1000, 1000, 1010, 1010))],
            padding=0,
        )
    )
    assert_filled(out, Box(600, 380, 639, 399), FILL)


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\n broken"])
def test_undecodable_input_raises_masking_error(data: bytes) -> None:
    with pytest.raises(MaskingError):
        mask_image(data, [region(FACE_BOX)])


def test_invalid_arguments_raise_masking_error() -> None:
    with pytest.raises(MaskingError):
        mask_image(id_card_png(), [region(FACE_BOX)], padding=-1)
    with pytest.raises(MaskingError):
        mask_image(id_card_png(), [region(FACE_BOX)], image_format="GIF")
    with pytest.raises(MaskingError):
        mask_image(id_card_png(), [FACE_BOX])  # type: ignore[list-item]


def test_oversized_image_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pii_guard.visual.image.MAX_PIXELS", 100)
    with pytest.raises(MaskingError):
        mask_image(id_card_png(), [])


def test_load_and_encode_helpers() -> None:
    image = load_image(id_card_png())
    assert image.mode == "RGB" and image.size == (640, 400)
    assert open_png(encode_image(image, "jpg")).format == "JPEG"
    with pytest.raises(ValueError):
        load_image("text")  # type: ignore[arg-type]
