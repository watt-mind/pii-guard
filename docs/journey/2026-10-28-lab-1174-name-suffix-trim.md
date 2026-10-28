# The case ending stays outside the name, whoever found it (2026-10-28)

LAB-1174. **Before:** a detector that found a Hungarian name whole with its case ending
(NER: `Tihamérnak`; the LLM on the demo's referral sample: `Kerekes Ottótól`) handed the vault
the inflected word. The vault narrows a span to its stem only for an unambiguous reading
(`Zsuzsannának`) or a lemma it has already seen, so `Kerekes Ottótól` became the value and an
English answer read "Referred by GP Kerekes Ottótól". On a fictional probe of 5 surnames x 20
inflected given names (`A levelet Kerekes Ottótól kaptuk meg tegnap.`, fast mode: rules + NER),
a placeholder on its own restored the name without the ending in **24 of 100**. **After:**
**80 of 100**; the 20 left are names NER misses or cuts inside a word, and `-ért` after a name
not in the lexicons (`Tihamérért`), which is left to the vault on purpose.

- **Fix.** `pii_guard.detect.suffix_trim` runs after the resolver in every detection pipeline
  and ends a whole-word PERSON span at its stem when the language pack reads it confidently:
  the Hungarian pack's `confident_split` takes a reading whose lemma ends in a lexicon name
  while the surface doesn't (`Ottó` + `tól`, `Béla` + `t`), a strong one (`Hajnának`), a doubled
  digraph (`Szabolccsal`), or a long ending no name ends in (`-nak`, `-tól`, `-hoz` ...). The
  vault's own lemma logic does the rest (`Hajná|nak` → `Hajna`).
- **No false trims.** 24 names that only look inflected (`Márton`, `Kornél`, `Simon`, `Kelemen`,
  `Gellért`, `Klára`, `Zoltán`, `Bálint` ...) x 5 surnames: 119 of 120 kept whole, as before
  (the one miss is an NER fragment). Tests: `tests/languages/test_hu_suffix_trim.py`,
  `tests/detect/test_suffix_trim.py`.
- **Other sets** (rules + NER). hu-inflection: leak 1/30, consistency 16/18, round trip 8/8,
  unchanged. hu-smoke: leak 0/106, consistency 105/106, round trip 31/31, unchanged; `Teszt
  Eleknek` in one chat now restores `Teszt Elek`. The quality gate (rules) is unchanged in all
  6 suites. PERSON exact-match F1 on hu-inflection falls 0.519 → 0.296, because those gold
  spans include the case ending and the predicted spans now don't: the same convention the
  `known` detector already follows ([evaluation](../evaluation.md)). Overlap F1 is unchanged
  (0.926).
- **Cost:** $0, offline, local NER checkpoint.
