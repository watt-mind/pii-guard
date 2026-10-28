# "Meta" is a company, not a person: brand names stay readable (2026-10-28)

LAB-1336. **In fast mode, `Write a haiku about Meta that greets me by name.` went upstream as
`Write a haiku about [[PERSON_…]] …`.** The NER v2.0 model tagged the bare word `Meta` as
`PERSON` with a score of 0.97, so no threshold could help. The answer came back restored, but
the upstream model had lost the topic of the prompt. In a Meta hackathon demo it is the first
thing anyone types. `Llama`, `Muse` and `Gemini` in one comparison prompt went the same way.

- **The fix: a gazetteer, as language-pack data, no retraining.**
  [`detect/ner_orgs.py`](../../src/pii_guard/detect/ner_orgs.py) checks the NER's `PERSON`
  spans before they leave the detector. A span that is exactly a listed company, product or
  model name becomes `ORGANIZATION`, which policy keeps, so the word stays in the prompt. A
  policy with `ORGANIZATION=mask` still masks it. The name may carry a suffix that the text
  language's inflection matcher allows for an organisation (`Meta's`, `Google-nél`, Hungarian
  `Metáról` with its lengthened stem).
- **Add-a-language.** The cross-language names (Meta, Llama, Muse, WhatsApp, Instagram,
  Google, OpenAI, Anthropic …) are in `languages/brands.tsv`. Each pack adds its own with the
  new optional `LanguagePack.brands` field (`hu`: `OTP Bank`, `MOL`, `Yettel`; `de`:
  `Deutsche Bahn`, `Lufthansa`; `en`: `BBC`, `NHS`). The conformance suite checks the file and
  `pii-guard lang new` writes a commented one. See [languages.md](../languages.md).
- **Persons stay persons.** A span is not relabelled when it is longer than the name
  (`Meta Kovács`), when an honorific stands next to it (`Ms. Apple`, `Herr Meta`, `Meta úr`),
  when another person span or a known given name or surname touches it (`Kovács Meta`), or
  when a pack's name lexicon lists the name. Brands that are also common personal names are
  left off the list (Ford, Dell, Tesla, Siemens, Porsche, Disney, Claude, Alexa, Otto). For
  those a missed brand costs readability, while a missed person would be a leak.
  `PII_GUARD_NER_BRANDS=false` turns the check off.

Fast mode (rules + NER v2.0, with LAB-1338's word snapping), with the check off and on, on the same
commit:

| set (split) | over-masking (spans) | precision | recall | leak (values) |
| -- | -- | -- | -- | -- |
| brand-name probe (24 prompts) | 14 → 2 masked spans | — | — | — |
| agent-traffic-dev (dev) | 2.2 → 1.9 % (37 → 32) | 94.5 → 94.5 % | 97.7 → 97.7 % | 0.13 → 0.13 % (2 → 2) |
| agent-traffic (test) | 2.0 → 1.7 % (112 → 96) | 93.8 → 93.8 % | 97.3 → 97.3 % | 0.23 → 0.23 % (12 → 12) |
| ai4privacy (test) | 1.4 → 1.4 % (31 → 31) | 97.9 → 97.9 % | 98.9 → 98.9 % | 0.37 → 0.37 % (8 → 8) |
| nemotron-pii (test) | 1.4 → 1.4 % (12 → 12) | 91.0 → 91.0 % | 87.9 → 87.9 % | 0.72 → 0.72 % (5 → 5) |
| cee-pii (test) | 27.8 → 27.8 % (194 → 194) | 70.5 → 70.5 % | 97.2 → 97.2 % | 0.40 → 0.40 % (2 → 2) |
| hu fixtures (`eval/fixtures`, hu) | 1.4 → 1.4 % (8 → 8) | 90.7 → 90.7 % | 94.1 → 94.1 % | 0.92 → 0.92 % (4 → 4) |

Recall and the number of leaked values are unchanged on every set. On agent-traffic there are 16
fewer over-masked spans (5 on the dev split). The check only relabels, so all of them were
listed brand names tagged `PERSON`. The set's hard negatives include public companies in
context.
The brand probe is committed as run records
([before](../../eval/results/runs/2026-10-28-lab-1336-brands-before.json),
[after](../../eval/results/runs/2026-10-28-lab-1336-brands-after.json)) on
`eval/fixtures/negative/*-brand-names.jsonl`. The dataset runs are not committed. Their record
ids (`2026-10-28-datasets-<set>-fast`) already hold LAB-1293's evidence from the same day, and
the runner can't take another slug yet (LAB-1347).

- **What's left on the probe.** Two spans: `Haiku` tagged as a person and a stray `G` tagged as
  an ID document. Because the check runs after LAB-1338 snaps NER spans to whole words,
  sub-word pieces such as `Met` from `Metáról` and `ettel` from `Yettel` reach it as whole
  words and are kept. Teaching the model itself that a brand on its own is not a person is
  LAB-1346 (hard negatives).
- **Cost:** $0, offline, no model change.
