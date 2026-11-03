"""Original image pixels and OCR text must stay in pipes, including on failure (LAB-1753)."""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw, ImageFont

from pii_guard.visual import ocr_transport
from pii_guard.visual.ocr import OcrTimeoutError, TesseractOcr

TSV = (
    b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    b"5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t98.7\tSYNTHETIC\n"
)


def test_transport_uses_png_stdin_and_stdout_without_tempfiles(monkeypatch: pytest.MonkeyPatch):
    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert argv == [
            "tesseract",
            "stdin",
            "stdout",
            "-l",
            "eng",
            "-c",
            "tessedit_create_tsv=1",
            "--psm",
            "6",
            "-c",
            "user_defined_dpi=150",
        ]
        assert Image.open(io.BytesIO(kwargs["input"])).size == (32, 16)
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 0.5
        return subprocess.CompletedProcess(argv, 0, TSV, b"")

    monkeypatch.setattr(ocr_transport.subprocess, "run", run)
    data = ocr_transport.image_to_data(
        Image.new("RGB", (32, 16)),
        lang="eng",
        config="--psm 6 -c 'user_defined_dpi=150'",
        timeout=0.5,
    )
    assert data["text"] == ["SYNTHETIC"]
    assert data["conf"] == [98]  # Preserve pytesseract's dictionary conversion.
    assert data["left"] == [10]


@pytest.mark.parametrize("timeout", [False, True])
def test_subprocess_errors_do_not_expose_output(monkeypatch: pytest.MonkeyPatch, timeout: bool):
    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if timeout:
            raise subprocess.TimeoutExpired(argv, 1, output=b"SYNTHETIC SECRET")
        return subprocess.CompletedProcess(argv, 1, b"SYNTHETIC SECRET", b"SYNTHETIC SECRET")

    monkeypatch.setattr(ocr_transport.subprocess, "run", run)
    expected = OcrTimeoutError if timeout else RuntimeError
    engine = TesseractOcr(upscale_to=None)
    with pytest.raises(expected) as error:
        if timeout:
            engine._osd_turn(Image.new("RGB", (32, 16)), 1)
        else:
            ocr_transport.image_to_data(Image.new("RGB", (32, 16)), lang="eng")
    assert "SECRET" not in str(error.value)
    assert error.value.__suppress_context__


def test_osd_uses_pipes_and_preserves_rotation(monkeypatch: pytest.MonkeyPatch):
    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert argv == ["tesseract", "stdin", "stdout", "-l", "osd", "--psm", "0"]
        return subprocess.CompletedProcess(argv, 0, b"Rotate: 90\n", b"")

    monkeypatch.setattr(ocr_transport.subprocess, "run", run)
    assert TesseractOcr()._osd_turn(Image.new("RGB", (32, 16)), 1) == 270


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_real_tesseract_leaves_no_image_or_text_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=32)
    for row in range(12):
        draw.text((20, row * 50), "SYNTHETIC SAMPLE FOR OCR TESTING", font=font, fill="black")
    # Fail at the write itself, even if a wrapper would unlink the file afterwards.
    save = Image.Image.save

    def memory_save(self: Image.Image, fp: Any, *args: Any, **kwargs: Any) -> None:
        assert isinstance(fp, io.BytesIO), "OCR attempted to serialize pixels to a file"
        save(self, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", memory_save)
    engine = TesseractOcr(lang="eng", config="--psm 6", upscale_to=None)
    words, _ = engine._tesseract(image, 1, (0, 0), ())
    assert "SYNTHETIC" in [word.text for word in words]
    # Exercise both orientation success and its safe fallback on systems without OSD data.
    assert TesseractOcr()._osd_turn(image, 1) in (None, 0, 90, 180, 270)
    assert list(tmp_path.iterdir()) == []
