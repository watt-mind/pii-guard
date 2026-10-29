"""Create an obviously fictional PNG for the self-hosted image integration example."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    image = Image.new("RGB", (1000, 240), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=34)
    draw.text((30, 30), "SYNTHETIC SAMPLE - NOT AN ID DOCUMENT", font=font, fill="black")
    draw.text((30, 100), "Email: sample.person@example.com", font=font, fill="black")
    draw.text((30, 170), "Fictional data for an integration check", font=font, fill="black")
    path = Path(tempfile.mkdtemp(prefix="pii-guard-integration-")) / "synthetic.png"
    image.save(path)
    print(path)


if __name__ == "__main__":
    main()
