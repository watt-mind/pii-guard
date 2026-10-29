"""Weight soups of two NER checkpoints with the same architecture (LAB-1494).

``w = alpha * w_b + (1 - alpha) * w_a`` for every floating-point tensor, averaged in fp32 and
saved in ``a``'s dtype; integer buffers are copied from ``a``. Refuses checkpoints whose
config (label map included), tensor names, shapes or tokenizer differ. Config and tokenizer
files are copied from ``a``::

    uv run --no-sync python training/ner/soup.py --a <v2.0 dir> --b <v3.1-B dir> \\
        --alpha 0.3 --out models/ner/pii-guard-ner-xlmr-base-v32-s30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

COPIED = ("config.json", "tokenizer.json", "tokenizer_config.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_compatible(a: Path, b: Path) -> None:
    """Raise ``ValueError`` unless ``a`` and ``b`` can be averaged tensor by tensor."""
    from safetensors import safe_open

    ca = json.loads((a / "config.json").read_text(encoding="utf-8"))
    cb = json.loads((b / "config.json").read_text(encoding="utf-8"))
    diff = sorted(k for k in set(ca) | set(cb) if ca.get(k) != cb.get(k))
    if diff:
        raise ValueError(f"config differs: {diff}")
    if _sha(a / "tokenizer.json") != _sha(b / "tokenizer.json"):
        raise ValueError("tokenizer differs")
    with (
        safe_open(a / "model.safetensors", "pt") as fa,
        safe_open(b / "model.safetensors", "pt") as fb,
    ):
        if set(fa.keys()) != set(fb.keys()):
            raise ValueError("tensor names differ")
        for key in fa.keys():  # noqa: SIM118 - safe_open is not a dict
            if fa.get_slice(key).get_shape() != fb.get_slice(key).get_shape():
                raise ValueError(f"shape differs: {key}")


def soup(a: Path, b: Path, alpha: float, out: Path) -> dict[str, object]:
    import torch
    from safetensors.torch import load_file, save_file

    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0, 1]")
    check_compatible(a, b)
    ta, tb = load_file(a / "model.safetensors"), load_file(b / "model.safetensors")
    mixed: dict[str, torch.Tensor] = {}
    copied = 0
    for key, wa in ta.items():
        if not wa.is_floating_point():
            mixed[key] = wa.clone()
            copied += 1
            continue
        avg = alpha * tb[key].to(torch.float32) + (1.0 - alpha) * wa.to(torch.float32)
        mixed[key] = avg.to(wa.dtype).contiguous()
    out.mkdir(parents=True, exist_ok=True)
    save_file(mixed, out / "model.safetensors", metadata={"format": "pt"})
    for name in COPIED:
        if (a / name).is_file():
            shutil.copyfile(a / name, out / name)
    meta = {
        "soup": {
            "alpha_b": alpha,
            "a": {"path": a.name, "weights_sha256": _sha(a / "model.safetensors")},
            "b": {"path": b.name, "weights_sha256": _sha(b / "model.safetensors")},
            "tensors": len(ta),
            "integer_tensors_copied_from_a": copied,
        },
        "weights_sha256": _sha(out / "model.safetensors"),
    }
    (out / "training_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--a", type=Path, required=True, help="first checkpoint (weight 1 - alpha)")
    parser.add_argument("--b", type=Path, required=True, help="second checkpoint (weight alpha)")
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(soup(args.a, args.b, args.alpha, args.out), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
