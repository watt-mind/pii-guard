# Names in CSV rows are found whole (2026-10-30)

LAB-1258, found in LAB-1236 and again in LAB-1256's Muse Code run. **Before:** in a CSV row
such as `2,Teszt Elek,teszt.elek@example.com`, the comma is glued to the name, so the
tokenizer turns its first word into a sub-word piece. The previous default NER
(`Davlan/xlm-roberta-base-ner-hrl`) then returned `Elek,teszt.elek@example.com,+36` and let
`Teszt` through. The published model (`watt-mind/pii-guard-ner-xlmr-base`) found the name in
two pieces: `szt` at score 0.58, just over the 0.5 threshold, snapped to `Teszt`, and `Elek`
at 0.92. That gave two placeholders for one person. `examples/coding-agents/gold.json` listed
both names as `known_gaps.csv_names`.

- **The model sees each cell**
  ([`detect/ner.py`](../../src/pii_guard/detect/ner.py), `model_view`). A `,` or `;` directly
  followed by a capital letter becomes a space in the text the model reads. The text keeps
  its length, so offsets don't change. Prose (`Anna, thanks`), decimals (`1,5`) and lower-case
  header rows (`id,name,tax_id`) are left alone, because the model reads number types from
  headers.
- **Spans stop at a cell boundary.** A `PERSON`, `ORGANIZATION` or `ADDRESS` span that runs
  across one of those delimiters is split there (`Peter Nagy;Szeged` becomes `Peter Nagy` and
  `Szeged`). Numbers that run across fields are still split by `check_numbers` (LAB-1293).
- **Gold:** `Teszt Elek` and `Max Mustermann` moved from `known_gaps` to `ner`, so
  `known_gaps` is now empty. The agent-text fixtures
  ([builder](../../eval/fixtures/build_agent_text.py)) gain one positive in each of hu, en and
  de: a `read_file` of customers.csv with an id column and a line-number gutter. They also gain
  one negative: an inventory CSV whose cells are glued status words.

On `customers.csv`, the published model now returns `Teszt Elek` whole at 1.00. Davlan now
finds `Jane Placeholder` and `Max Mustermann` whole. It still misses the Hungarian name, which
it never knew without context.

Fast mode (rules + NER, `watt-mind/pii-guard-ner-xlmr-base`), local CPU,
`pii-guard eval --detectors rules,ner`. Before is `develop` `8b04cca`, run on the new fixture
rows. After is this branch.

| set | leak (values) | over-masking | recall (overlap) |
| -- | -- | -- | -- |
| agent-text (hu/en/de) | 0/126 → 0/126 | 0/132 → 0/132 | 132/132 → 132/132 |
| agent-traffic-dev | 2/1555 → 2/1555 | 28/1683 → 28/1683 | 1657/1687 → 1655/1687 |
| smoke (hu/en/de/pl) | 0/216 → 0/216 | 2/229 → 2/229 | 229/241 → 229/241 |
| hu-inflection | 1/50 → 1/50 | 0/57 → 0/57 | 57/61 → 57/61 |

The aggregate numbers barely move: in context, as in the new fixture rows, the published
model already found these names. On agent-traffic-dev the only differences are type labels
on numbers inside delimited rows, such as `ID_DOCUMENT` ↔ `PHONE`. Those values are masked
either way, so leak and over-masking don't change. Recall, which counts a span only when its
type matches, drops by two: one `NATIONAL_ID_HU_TAX` and one `ID_DOCUMENT`, both now labelled
with another number type. Names (540/540) and addresses (88/88) don't change.

LAB-1604 (triage) tracks a separate problem: a number span that runs across a newline, so the
next row's id is masked as `BANK_ACCOUNT`.
