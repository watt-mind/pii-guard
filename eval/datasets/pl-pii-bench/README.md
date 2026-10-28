# pl-pii-bench

| | |
|---|---|
| Files | `pl-pl-pii-bench.jsonl` (346 documents: every document of the `core`, `identifiers`, `address`, `negative` and `inflection` lanes) |
| Manifest | [`manifest.json`](manifest.json): revision, file SHA-256s, label mapping, document ids and hashes, label counts |
| Source | [`pl-pii-bench/pl-pii-bench`](https://huggingface.co/datasets/pl-pii-bench/pl-pii-bench) v1.0.0, `data/` at revision `bef947d33bc37ec3f8f759ba251bf27208de239f` |
| Licence | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (the data in `data/`, per its `DATA_LICENSE`) |
| Attribution | pl-pii-bench, version 1.0.0, Anonimator, CC BY 4.0 |
| Changes | Labels mapped to pii-guard types, adjacent address parts merged, policy-excluded labels (REGON, VIN, a town or postcode on its own) turned into ignore regions; the text is unchanged. The `robustness` and `pdf` lanes are left out. |

The corpus is fully synthetic: its card says every identifier is synthetic and checksum-valid
identifiers "do not belong to real people". It is an evaluation set, and its card asks that
nobody train on it. pii-guard never does: `training/ner/decontam.py` drops any training
document that duplicates one of these (LAB-1392).

Rebuild and check:

```bash
uv run --no-sync python -m pii_guard.eval.datasets fetch pl-pii-bench
uv run --no-sync python -m pii_guard.eval.datasets check pl-pii-bench
```

The label mapping and caveats are in [docs/datasets.md](../../../docs/datasets.md).
