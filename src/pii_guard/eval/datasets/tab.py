"""TAB, the Text Anonymization Benchmark: European Court of Human Rights judgments (en).

`NorskRegnesentral/text-anonymization-benchmark
<https://github.com/NorskRegnesentral/text-anonymization-benchmark>`_ (Pilán et al., 2022;
annotations MIT): 1,268 ECHR judgments from HUDOC, each annotated by law students for the
spans that identify the applicant. The **texts are real court documents** that name real
people (applicants, lawyers, judges, witnesses). They are therefore **never committed**: only
the manifest (document ids and hashes) is; ``fetch`` rebuilds the fixture file in the
git-ignored cache, and the documents are never sent to a remote model.

Scored: ``PERSON`` (every person mention, whatever its masking decision in TAB, since pii-guard
masks every name) and ``ORGANIZATION`` (a ``keep`` type). Dates, places, codes (application
numbers), demographics, quantities and miscellaneous spans are ignore regions. The first
quality-checked annotator's spans are used.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from pii_guard.eval.datasets._common import LabelMap, Row
from pii_guard.eval.datasets.spec import Dataset, SourceFile
from pii_guard.types import EntityType

__all__ = ["DATASET", "LABELS", "rows"]

REPO = "NorskRegnesentral/text-anonymization-benchmark"
REVISION = "558e09e26d6b36f5f78440074e6a233946d98bd9"

LABELS = LabelMap(
    types={
        "PERSON": EntityType.PERSON,
        "ORG": EntityType.ORGANIZATION,
        "LOC": None,
        "DATETIME": None,
        "CODE": None,
        "DEM": None,
        "QUANTITY": None,
        "MISC": None,
    },
    notes={
        "PERSON": "every person mention, whatever TAB's DIRECT/QUASI/NO_MASK decision",
        "ORG": "ORGANIZATION is a keep type: scored for recall, never a leak",
        "LOC": "places are mostly courts, towns and countries: policy-excluded",
        "CODE": "mostly application and case numbers: policy-excluded",
    },
)


def rows(paths: Sequence[Path]) -> Iterator[Row]:
    documents = json.loads(paths[0].read_text(encoding="utf-8"))
    for doc in documents:
        annotations = doc.get("annotations") or {}
        checked = [a for a in doc.get("quality_checked") or [] if a in annotations]
        names = checked or sorted(annotations)
        if not names:
            continue
        mentions = annotations[names[0]].get("entity_mentions") or []
        yield Row(
            str(doc["doc_id"]),
            "en",
            str(doc["text"]),
            tuple(
                (int(m["start_offset"]), int(m["end_offset"]), str(m["entity_type"]))
                for m in mentions
            ),
            meta={"annotator": names[0]},
            values=tuple(str(m["span_text"]) for m in mentions),
        )


DATASET = Dataset(
    name="tab-echr",
    title="TAB: Text Anonymization Benchmark (ECHR)",
    homepage=f"https://github.com/{REPO}",
    revision=REVISION,
    files=(
        SourceFile(
            "echr_test.json",
            f"https://raw.githubusercontent.com/{REPO}/{REVISION}/echr_test.json",
            "cd0f0f15f84a8739654c7cf30c6be8ce27b051ef73974d39d792a0cb8c846379",
        ),
    ),
    license="MIT (annotations); texts are public ECHR judgments from HUDOC",
    license_url=f"https://github.com/{REPO}/blob/{REVISION}/LICENSE.txt",
    attribution="Pilán et al. (2022), Norsk Regnesentral / University of Oslo",
    languages=("en",),
    source_split="test",
    split="test",
    synthetic=False,
    commit_rows=False,
    description="long real court judgments; names of applicants, lawyers, judges, witnesses",
    sample={"en": 40},
    seed=2026,
    labels=LABELS,
    read=rows,
    notes=(
        "Real documents naming real people: fixture files are rebuilt locally by fetch and "
        "never committed; no LLM or remote model is run on them.",
        "Documents are long (median about 3,900 characters).",
    ),
)
