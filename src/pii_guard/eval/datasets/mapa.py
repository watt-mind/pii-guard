"""MAPA EUR-Lex PII: two EU legal opinions in 21 parallel languages (LAB-1392).

`piimb/mapa-eur-lex-pii <https://huggingface.co/datasets/piimb/mapa-eur-lex-pii>`_
(CC-BY-4.0, curated by camillevanhoffelen from the MAPA project's EUR-Lex test split): two
Advocate General opinions of the Court of Justice of the EU, each in its official translations
into 20 other EU languages, including Hungarian, Czech, Slovak and Romanian. The English
versions were annotated by hand; the other languages' spans were projected onto the human
translations by an LLM and are not exhaustively verified, so read per-language numbers as
indicative.

The **texts are real, published court documents** that name real people (the parties, the
Advocate General, the judges in cited cases). Like TAB, they are therefore **never
committed**: only the manifest (document ids and hashes) is; ``fetch`` rebuilds the fixture
files in the git-ignored cache, and they are never sent to a remote model.

Scored: first and last names as ``PERSON`` (a given name and a surname next to each other
merge into one span) and ``employer`` as ``ORGANIZATION`` (a ``keep`` type). Case and
directive numbers and ECLI identifiers (``unique_id``), dates, occupations, titles, education,
ages, nationalities and URLs have no pii-guard type: ignore regions.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from pii_guard.eval.datasets._common import LabelMap, Row
from pii_guard.eval.datasets.spec import Dataset, SourceFile
from pii_guard.types import EntityType

__all__ = ["DATASET", "LABELS", "LANGUAGES", "rows"]

REPO = "piimb/mapa-eur-lex-pii"
REVISION = "a44958f9799ec2377d0e7d6ef8438411c2344449"
#: Every language of the set, in the source's order (Spanish rows carry no ``_es`` suffix).
LANGUAGES = (
    "en", "es", "bg", "cs", "da", "de", "el", "ga", "et", "fi", "fr",
    "hu", "it", "lt", "lv", "mt", "nl", "pt", "ro", "sk", "sv",
)  # fmt: skip

LABELS = LabelMap(
    types={
        "first_name": EntityType.PERSON,
        "last_name": EntityType.PERSON,
        "employer": EntityType.ORGANIZATION,
        "unique_id": None,
        "date": None,
        "occupation": None,
        "education_level": None,
        "title": None,
        "age": None,
        "url": None,
        "race_ethnicity": None,
        "nationality": None,
    },
    notes={
        "employer": "ORGANIZATION is a keep type: scored for recall, never a leak",
        "unique_id": "case and directive numbers, ECLI identifiers: they identify a case",
        "date": "no date in this set is marked as a birth date",
        "title": "honorifics, and in a few rows initials: policy-excluded",
    },
)


def rows(paths: Sequence[Path]) -> Iterator[Row]:
    with paths[0].open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            entities = raw.get("entities") or []
            yield Row(
                str(raw["uid"]).removesuffix(".txt"),
                str(raw["language"]),
                str(raw["text"]),
                tuple((int(e["start"]), int(e["end"]), str(e["label"])) for e in entities),
                meta={"annotation": "hand" if raw["language"] == "en" else "llm-projected"},
            )


DATASET = Dataset(
    name="mapa-eur-lex",
    title="MAPA EUR-Lex PII",
    homepage=f"https://huggingface.co/datasets/{REPO}",
    revision=REVISION,
    files=(
        SourceFile(
            "test.jsonl",
            f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/test.jsonl",
            "7aa297f23890759a1f587a176422a24bd93d830f49ca1aa61f1efa64e13a09a3",
        ),
    ),
    license="CC-BY-4.0; texts are public EUR-Lex documents",
    license_url="https://creativecommons.org/licenses/by/4.0/",
    attribution="camillevanhoffelen, piimb/mapa-eur-lex-pii, from the MAPA project (EUR-Lex)",
    languages=LANGUAGES,
    source_split="test (the whole set: 2 documents x 21 languages)",
    split="test",
    synthetic=False,
    commit_rows=False,
    description="two long EU legal opinions in 21 languages; names and employers",
    sample=dict.fromkeys(LANGUAGES, 2),
    seed=2026,
    labels=LABELS,
    read=rows,
    notes=(
        "Real published documents naming real people: fixture files are rebuilt locally by "
        "fetch and never committed; no LLM or remote model is run on them.",
        "English spans are hand-annotated; the other 20 languages are LLM-projected and not "
        "exhaustively verified.",
        "Documents are long (35,000 to 75,000 characters).",
    ),
)
