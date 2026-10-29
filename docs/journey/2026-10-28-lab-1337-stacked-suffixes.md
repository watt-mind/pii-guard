# A family suffix and a case ending after a known name (2026-10-28)

LAB-1337. **Before:** once the vault held a Hungarian name, it masked the name with one case
ending after it (`Kerekes Ottótól`), but not with the possessive `-é`, the family plural `-ék`
or the plural possessive `-éi` followed by a case ending of its own. Those forms are
everyday Hungarian (`Kerekes Ottóéknál`, "at the Ottós'"), and they stayed in clear text. A
fictional probe of 10 given names x 13 suffix chains x 5 surnames (`Kerekes Ottó írt nekünk.
Tegnap Kerekes Ottóéknál voltunk.`, the bare name labeled) leaked the name in **650 of 650**
cases. **After:** **0 of 650**. All 650 use one placeholder for both occurrences and give back
the text exactly on unmask.

- **Fix.** The Hungarian pack's suffix pattern accepts `-é`, `-ék` or `-éi` followed by an
  optional case ending, in both vowel harmonies (`Ottóéknál`, `Tihaméréknek`), with the
  forms that change after them (`Ottóékkal`, `Ottóékat`, `Ottóéval`). The chain also follows
  a lengthened stem (`Teszt Hajnáéknál` → `Hajna`). `splits` reads these forms too, so the
  detectors' suffix trim (LAB-1174) ends a span found whole, such as `Kerekes Ottóéknál`, at
  `Kerekes Ottó`. A chain the upstream model adds is re-inflected (`[[PERSON_x]]éknak` →
  `Teszt Hajnáéknak`). The probe is a test: `test_stacked_suffix_probe` in
  [`tests/vault/test_vault_inflection_hu.py`](../../tests/vault/test_vault_inflection_hu.py).
- **No over-masking from the new pattern:** eight held values next to ordinary words that
  begin with them (`kerekesszék`, `Bálint`, `kisebb`, `fehérje`, `mintaképe`, ...) still get
  one placeholder each. Known limit: a held value that is also a common word matches that
  word's real inflections. Held `Kerek` now also masks `kerekéket`, the same way held `Bor`
  already masked `bort`.
- **Other sets** (rules, and rules + NER): leak, over-masking, round trip and consistency
  are unchanged on hu-inflection and hu-smoke. Neither set contains a stacked form. The
  quality gate is unchanged in all 6 suites.
- **Cost:** $0, offline.
