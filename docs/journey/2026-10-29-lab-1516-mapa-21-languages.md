# Measured in 21 EU languages, not just gated in 3 (2026-10-29)

LAB-1516. Measure only, no training. This scored the production path (rules + NER v2.0,
`watt-mind/pii-guard-ner-xlmr-base@95f612a9`) on every language of the MAPA EUR-Lex test
split: real EU court opinions, 2 documents per language. It ran from one clean commit, next
to NER alone, the rules alone and two public EU-multilingual models.

- **MAPA has 21 of the 24 EU languages.** Croatian, Polish and Slovenian are missing (Polish is
  measured on pl-pii-bench). So the claim is "gated in en/de/hu, measured in 21".
- **Pooled leak of person names:** pii-guard fast **8.5 %**, tabularisai/eu-pii-safeguard
  21.9 %, bardsai/eu-pii-anonimization-multilang v1 29.5 %. v2.0 has the fewest leaks in 19 of
  21 languages and is one value behind in the other two (lv, ga).
- **Zero-shot:** 13 of the 18 languages v2.0 was never trained on leak at most 2 of about 35
  names (≤ 6.1 %).
- **Weak:**
  - Maltese, 25.7 %, and 7 % precision.
  - Latvian, Lithuanian and Irish, 17–24 %.
  - English, 24.3 %: the only hand-annotated language, with the standalone-surname family
    from LAB-1511.

  Those four set the order of the add-a-language roadmap. One value is about 3 points in each
  language cell.
- **Cost: $0.** Local CPU, because the court text never leaves the machine. Latency was
  withheld because the shared machine was overloaded.

Tables, method and roadmap: [results README](../../eval/results/2026-10-29-lab-1516-mapa-24/README.md).
