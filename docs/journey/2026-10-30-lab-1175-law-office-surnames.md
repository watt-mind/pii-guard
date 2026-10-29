# A law office no longer forwards its lawyer's surname (2026-10-30)

LAB-1175, found in the LAB-1151 demo critique. On the built-in `contract` sample, the lawyer
`Somogyi Ádám` was masked, but the office `Somogyi Ügyvédi Iroda` was kept whole as an
`ORGANIZATION`, so the surname reached the model anyway. The LAB-1149 rule for person names
inside company names only knew legal forms (`Bt.`, `Kft.`, `e.v.`, ...).

The rule now also anchors on `Ügyvédi Iroda`, `Közjegyzői Iroda` and `Szabadalmi Ügyvivői
Iroda`, inflected or in lower case. Such an office is named after its members, so a surname
there counts even when it is also an everyday word (`Somogyi`, `Kovács`). An unknown name
(`Mintás és Társa`) counts too. A place adjective alone (`Budapesti Ügyvédi Iroda`) and the
office words with no name stay kept
([tests](../../tests/languages/test_hu_companies.py)).

Fast mode (rules + NER v2.0) on `hu-smoke` + `hu-company-names` + the `contract` sample:

| | before | after |
| -- | --: | --: |
| masked person's surname left in the masked text (of 99) | 4 | **2** |
| partial leak, % | 2.1 | **1.4** |
| leak, % | 0.0 | 0.0 |
| over-masking, % | 2.7 | 2.7 |
| company-names person leak / plain-company over-masking | 0 of 54 / 2 of 30 | 0 of 54 / 2 of 30 |

- Both fixed cases are offices: `Somogyi` (the sample) and `Mintás` (`Mintás és Társa
  Ügyvédi Iroda`, hu-poa-0003). The two that remain aren't offices. One is a name in a
  greeting that the NER misses (`Kedves Próba Piroska!`). The other is a false alarm of the
  count: `Fekete Kavics Kft.` is a different, plain company.
- PERSON exact precision falls from 86.9 to 86.1 %. The smoke gold labels the whole
  `Mintás és Társa Ügyvédi Iroda` as one `ORGANIZATION`, so the newly masked surname
  scores as an unmatched prediction.
- Cost: $0, all local.
