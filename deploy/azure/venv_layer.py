"""Copy what installing the project added to a virtualenv into its own image layer (LAB-1449).

    python venv_layer.py BASE FULL OUT

BASE is the dependency-only venv (``uv sync --no-install-project``), FULL is the same venv after
the project was installed into it, and OUT receives every file or symlink in FULL that is new or
different from BASE, at the same relative path. Dockerfile.hosted copies BASE and then OUT into
the runtime image, so the multi-GB dependency layer keeps its digest across src-only changes and
only the small project layer changes.

A layered copy cannot express a deletion, so a file that exists in BASE but not in FULL fails
the split instead of shipping a venv that differs from the one the build tested.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import stat
import sys
from pathlib import Path


def _same(base: Path, full: Path) -> bool:
    try:
        b = base.lstat()
    except FileNotFoundError:
        return False
    f = full.lstat()
    if stat.S_IFMT(b.st_mode) != stat.S_IFMT(f.st_mode) or b.st_mode != f.st_mode:
        return False
    if stat.S_ISLNK(f.st_mode):
        return os.readlink(base) == os.readlink(full)
    if b.st_size != f.st_size:
        return False
    # An untouched file keeps its mtime in a later stage; only a rewrite costs a byte compare.
    return b.st_mtime_ns == f.st_mtime_ns or filecmp.cmp(base, full, shallow=False)


def split(base: Path, full: Path, out: Path) -> tuple[int, int]:
    """Copy FULL's additions over BASE into OUT; return (files copied, bytes copied)."""
    removed = [
        str(rel / name)
        for root, dirs, names in os.walk(base)
        for rel in [Path(root).relative_to(base)]
        for name in sorted(dirs + names)
        if not os.path.lexists(full / rel / name)
    ]
    if removed:
        raise SystemExit(f"venv_layer: installing the project removed {removed[:10]}")
    files = size = 0
    for root, dirs, names in os.walk(full):
        rel = Path(root).relative_to(full)
        # A symlinked directory is copied as a link, never followed.
        entries = names + [d for d in dirs if (Path(root) / d).is_symlink()]
        for name in sorted(entries):
            src = Path(root) / name
            if _same(base / rel / name, src):
                continue
            dst = out / rel / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                dst.symlink_to(os.readlink(src))
            else:
                shutil.copy2(src, dst)
                size += src.stat().st_size
            files += 1
    # Directories the copy created keep the venv's modes and times, not the umask's.
    for dirpath, _dirs, _names in os.walk(out):
        rel = Path(dirpath).relative_to(out)
        shutil.copystat(full / rel, dirpath)
    return files, size


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    base, full, out = (Path(arg) for arg in argv)
    out.mkdir(parents=True, exist_ok=True)
    files, size = split(base, full, out)
    if not files:
        raise SystemExit("venv_layer: the project added nothing to the venv")
    print(f"venv_layer: {files} files, {size / 1e6:.1f} MB in the project layer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
