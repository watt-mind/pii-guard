# MAPA EUR-Lex PII

| | |
|---|---|
| Files | none committed: `fetch` rebuilds `data/datasets/fixtures/mapa-eur-lex/<lang>-mapa-eur-lex.jsonl` (42 documents, 2 per language, 21 languages) |
| Manifest | [`manifest.json`](manifest.json): revision, file SHA-256, label mapping, document ids and hashes, label counts. No text. |
| Source | [`piimb/mapa-eur-lex-pii`](https://huggingface.co/datasets/piimb/mapa-eur-lex-pii), `test.jsonl` at revision `a44958f9799ec2377d0e7d6ef8438411c2344449` |
| Licence | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); the texts are public EUR-Lex documents |
| Attribution | camillevanhoffelen, piimb/mapa-eur-lex-pii, built from the MAPA project's EUR-Lex test split (de Gibert Bonet et al., LREC 2022) |
| Changes | Labels mapped to pii-guard types (names and employers scored; case numbers, dates, occupations and the other labels are ignore regions); the text is unchanged. |

The texts are two real, published opinions of Advocates General of the Court of Justice of
the EU, with their official translations. They name real people, so, like TAB, **no text is
committed** and the documents are never sent to a remote model. The English spans are
hand-annotated; the other 20 languages were projected by an LLM and are not exhaustively
verified.

```bash
uv run --no-sync python -m pii_guard.eval.datasets fetch mapa-eur-lex   # into data/ (git-ignored)
uv run --no-sync python -m pii_guard.eval.datasets check mapa-eur-lex
```
