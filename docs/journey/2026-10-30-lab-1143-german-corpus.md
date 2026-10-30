# A language pack brings its own synthetic corpus, and German gets one (2026-10-30)

LAB-1143. **Before:** after LAB-1130 every per-language part lived in a `LanguagePack` except
the synthetic corpus. `eval/identities.py` kept its own `LANGUAGES = {hu, en}` dict, and the
document templates were looked up by file name, so adding a language still meant editing
eval internals. German, the worked example of [languages.md](../languages.md), was measured
on its 10-document smoke set only. **After:** the corpus is an optional pack part,
`identity_generator` plus `corpus_templates`, and `identities.LANGUAGES` is a view of the
registry. The conformance suite reports a pack without one as "no synthetic corpus: the
language is measured on its smoke set only". It also checks that every field a template asks
for exists on the generator's records.

- **German generator.** [`languages/de/identities.py`](../../src/pii_guard/languages/de/identities.py)
  makes fictional people from hand-curated name, street and town lists, so there are no
  third-party terms to clear (ADR 0009). Each person has a checksum-valid Steuer-ID, a DE IBAN
  and a Personalausweis-style number, and phone numbers come from the Bundesnetzagentur's film
  and TV ranges. Every generated address, phone, labelled Steuer-ID and IBAN is recognized by
  the German rules (a test checks this).
  [`corpus.toml`](../../src/pii_guard/languages/de/corpus.toml) has nine document kinds,
  including an employment contract with a Steuer-ID.
- **Sample.** [`de-synth-sample.jsonl`](../../eval/fixtures/de-synth-sample.jsonl) is 14
  documents written by `muse-spark-1.3-contributor` (seed 2026). All 14 were accepted, with 157
  gold spans and 14 model calls on free hackathon credits.
- **Baseline on it** (no detector change): rules alone leak 57.0 % of 114 values
  ([run](../../eval/results/runs/2026-10-29-lab-1143-de-synth-sample-rules.json)). Fast mode
  with the published NER v2.0 leaks 0.9 % (1 value, a licence plate), with 0.0 % over-masking
  and 100 % round trip ([run](../../eval/results/runs/2026-10-29-lab-1143-de-synth-sample-fast.json)).
  The `synth-sample` row in [benchmarks.md](../benchmarks.md#synth-sample) now covers
  de + en + hu.
