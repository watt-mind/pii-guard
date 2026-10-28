"""The evaluation dataset registry: every set pii-guard is scored on beyond its own fixtures.

```
python -m pii_guard.eval.datasets list                 # name, split, licence, languages, files
uv run --with pyarrow python -m pii_guard.eval.datasets fetch gretel-finance [NAME ...]
python -m pii_guard.eval.datasets check NAME [...]     # rebuild, compare, write nothing
python -m pii_guard.eval.datasets paths NAME           # its fixture files, for --fixtures
python -m pii_guard.eval.datasets run NAME --system fast|rules|presidio,llm-guard,privaite
pii-guard eval datasets ...                            # the same
```

One module per dataset declares its source (URL, pinned revision, file SHA-256), licence,
languages, label mapping and split (:class:`~pii_guard.eval.datasets.spec.Dataset`). How to add
one, the licence table and the split policy are in ``docs/datasets.md``.
"""

from __future__ import annotations

from pii_guard.eval.datasets import (
    cee,
    gretel,
    mapa,
    nemotron,
    openpii,
    pl_pii_bench,
    synthetic,
    tab,
)
from pii_guard.eval.datasets.spec import Dataset

__all__ = ["REGISTRY", "Dataset", "get", "test_datasets"]

#: Every registered dataset, by fixture-set name.
REGISTRY: dict[str, Dataset] = {
    ds.name: ds
    for ds in (
        openpii.DATASET,
        gretel.DATASET,
        nemotron.DATASET,
        cee.DATASET,
        tab.DATASET,
        pl_pii_bench.DATASET,
        mapa.DATASET,
        synthetic.DATASET,
        synthetic.DEV_DATASET,
    )
}


def get(name: str) -> Dataset:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown dataset {name!r} (known: {', '.join(REGISTRY)})") from None


def test_datasets() -> list[Dataset]:
    """The held-out sets: what the headline numbers may come from."""
    return [ds for ds in REGISTRY.values() if ds.split == "test"]


test_datasets.__test__ = False  # type: ignore[attr-defined]  # not a pytest test
