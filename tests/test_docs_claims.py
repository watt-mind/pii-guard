"""Every piece of evidence the differentiator docs cite exists in the repository (LAB-1165).

`docs/why-pii-guard.md`, `docs/submission.md` and the README's "Why pii-guard" section back
each claim with a link to a committed file. This test fails when a linked file or a linked
heading goes away, so a claim can't silently lose its evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("docs/why-pii-guard.md", "docs/submission.md", "README.md")
REPO_URL = "https://github.com/watt-mind/pii-guard/blob/develop/"

LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)


def _slug(heading: str) -> str:
    """GitHub's anchor for a Markdown heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    return {_slug(h) for h in HEADING_RE.findall(path.read_text(encoding="utf-8"))}


def _targets(doc: str) -> list[tuple[str, str, Path]]:
    """(link, target, base directory) for every local or repository link in ``doc``."""
    source = ROOT / doc
    text = source.read_text(encoding="utf-8")
    links = LINK_RE.findall(text) + re.findall(re.escape(REPO_URL) + r"[^\s|)]+", text)
    out = []
    for link in links:
        if link.startswith(REPO_URL):
            out.append((link, link.removeprefix(REPO_URL), ROOT))
        elif not re.match(r"^[a-z]+:", link):
            out.append((link, link, source.parent))
    return out


@pytest.mark.parametrize("doc", DOCS)
def test_cited_files_and_headings_exist(doc: str) -> None:
    source = ROOT / doc
    missing = []
    for link, target, base in _targets(doc):
        path_part, _, anchor = target.partition("#")
        path = (base / path_part).resolve() if path_part else source
        if not path.exists():
            missing.append(f"{link}: no such file")
        elif anchor and path.suffix == ".md" and anchor not in _anchors(path):
            missing.append(f"{link}: no heading #{anchor}")
    assert not missing, f"{doc} cites evidence that does not exist:\n" + "\n".join(missing)


def test_readme_links_the_differentiators_page() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Why pii-guard" in readme
    assert "docs/why-pii-guard.md" in readme
    assert "why-pii-guard.md" in (ROOT / "docs/INDEX.md").read_text(encoding="utf-8")


def test_every_differentiator_has_a_status() -> None:
    page = (ROOT / "docs/why-pii-guard.md").read_text(encoding="utf-8")
    sections = re.split(r"^## \d+\. ", page, flags=re.M)[1:]
    assert len(sections) >= 8
    for section in sections:
        assert "**Status:**" in section, section.splitlines()[0]
        assert "](" in section, f"no evidence link: {section.splitlines()[0]}"


def test_tagline_fits_the_form() -> None:
    page = (ROOT / "docs/submission.md").read_text(encoding="utf-8")
    tagline = re.search(r"## Tagline.*?```text\n(.+?)\n```", page, re.S)
    assert tagline is not None
    assert len(tagline.group(1)) <= 140
