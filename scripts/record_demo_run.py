"""Record the landing's default demo run: a real model through the real gateway (LAB-1503).

The landing's Demo section (``ui/src/hosted/HostedApp.tsx``) used to open on a hand-written
example. It now opens on a recorded run of the hosted preview's own ``/v1/demo``: the
server-curated fictional sample (``DEMO_SAMPLES`` in ``src/pii_guard/hosted/routes.py``) is
masked by the gateway in fast mode (rules + the published NER), sent to the included Meta model
(Muse Spark), and the answer is restored. This script makes that recording by calling a running
hosted deployment as an anonymous guest, exactly as a visitor's "Run the live demo" does (one
free run per language; the sponsored model's credit is spent).

The written JSON holds what ``/v1/demo`` returns, minus the per-request ids: the fictional
sample, the masked text, the model's masked answer, the restored answer, the entity offsets and
the model name, plus the date and the deployment it came from. The only personal-looking values
in it are the sample's fictional ones; the script fails if the original isn't the curated sample,
if a sample value reaches the masked text or the model's answer, or if the offsets don't match::

    uv run --no-sync python scripts/record_demo_run.py                    # guard-dev, writes it
    uv run --no-sync python scripts/record_demo_run.py --base https://guard.watt-mind.com
    uv run --no-sync python scripts/record_demo_run.py --check            # checks the file only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from pii_guard.hosted.routes import DEMO_SAMPLES
from pii_guard.vault import PLACEHOLDER_RE

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ui" / "src" / "content" / "demoRecording.json"
DEFAULT_BASE = "https://guard-dev.watt-mind.com"
KEYS = ("original", "masked", "answer", "restored", "entities", "model")


def check_run(language: str, run: dict[str, Any]) -> None:
    """Raise if ``run`` isn't a clean, consistent run of the curated sample for ``language``."""
    sample = next(text for lang, text in DEMO_SAMPLES.values() if lang == language)
    if run["original"] != sample:
        raise SystemExit(f"{language}: the original is not the curated sample")
    for key in ("masked", "answer", "restored", "model"):
        if not isinstance(run[key], str) or not run[key].strip():
            raise SystemExit(f"{language}: {key} is empty")
    if not run["entities"]:
        raise SystemExit(f"{language}: nothing was masked")
    values = []
    for entity in run["entities"]:
        start, end = entity["start"], entity["end"]
        if not (0 <= start < end <= len(sample)) or not isinstance(entity["type"], str):
            raise SystemExit(f"{language}: bad entity offsets {entity}")
        values.append(sample[start:end])
    for value in values:
        for key in ("masked", "answer"):
            if value in run[key]:
                raise SystemExit(f"{language}: a sample value reached the model ({key})")
    if not PLACEHOLDER_RE.search(run["masked"]) or not PLACEHOLDER_RE.search(run["answer"]):
        raise SystemExit(f"{language}: no placeholder in the masked text or the answer")
    if PLACEHOLDER_RE.search(run["restored"]):
        raise SystemExit(f"{language}: the restored answer still has a placeholder")


def record(base: str) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    with httpx.Client(base_url=base, timeout=180, follow_redirects=False) as client:
        for sample_id, (language, _) in DEMO_SAMPLES.items():
            response = client.post(
                "/v1/demo",
                json={"sample_id": sample_id, "language": language},
                headers={"Origin": base},
            )
            response.raise_for_status()
            body = response.json()
            run = {key: body[key] for key in KEYS}
            check_run(language, run)
            runs[language] = run
    return {
        "recorded_at": dt.date.today().isoformat(),
        "source": base,
        "note": "Recorded by scripts/record_demo_run.py: /v1/demo on the hosted preview, "
        "fast mode, the included Meta model. Fictional sample data only.",
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default=DEFAULT_BASE, help="hosted deployment to record from")
    parser.add_argument("--check", action="store_true", help="check the committed file only")
    args = parser.parse_args()
    if args.check:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        for language, run in data["runs"].items():
            check_run(language, run)
        print(f"{OUT.relative_to(ROOT)}: ok ({', '.join(data['runs'])})")
        return 0
    data = record(args.base)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} from {args.base}")
    for language, run in data["runs"].items():
        print(f"--- {language} · {run['model']}\n{run['masked']}\n>> {run['answer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
