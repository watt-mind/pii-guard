# NER v4: the first multilingual fine-tune, and v2.0 still stays (2026-10-29)

LAB-1535. The first training on the LAB-1525 data beyond hu/en/de: OpenPII-1M rows in 19 more
EU languages, fictional Muse documents in Latvian, Lithuanian, Croatian and Slovene, hard
negatives in 19 languages and English court-style text that names people by surname alone.
The protocol was LAB-1512's, unchanged, plus a per-language gate on the new fictional sets.
It was committed with the candidates before anything was trained.

1. **A:** v2.0 warm start, 2,500 OpenPII rows per language, 1 epoch at lr 1e-5.
2. **B-raw:** the same with 5,000 rows per language, 2 epochs at 2e-5.
3. **B:** a weight soup, 0.5 v2.0 + 0.5 B-raw. The LAB-1494 soups were the best near-miss so
   far, so B tests interpolating back toward v2.0.

Each mix replays v2.0's own hu/en/de data, and both trainings ran on one A10G on Modal.

| rules + NER, % | smoke leak / over-mask | inflection leak | eu sets leak (of 315) | agent-traffic-dev leak / over-mask | MAPA-21 leak |
| -- | --: | --: | --: | --: | --: |
| **v2.0 (kept)** | **0.00** / 1.09 | 2.0 | 0.95 (3) | 0.13 / **1.84** | 8.5 |
| A | 0.58 / **1.08** | **0.0** | 0.95 (3) | **0.00** / 3.38 | **5.8** |
| B | 0.00 / 1.62 | 2.0 | 1.27 (4) | 0.00 / 3.21 | 7.2 |
| B-raw | 0.00 / 3.23 | 2.0 | 0.95 (3) | 0.00 / 5.42 | 8.5 |

- **Every candidate fails a gate.** On the selection set, all three stop leaking but over-mask
  twice as much as v2.0. Most of the extra false alarms are `ADDRESS` spans in agent text (6
  for v2.0, 26–57 for the candidates). A also misses the Hungarian smoke name every v3.x
  round has missed. B and B-raw over-mask smoke past the 0.5 pp margin.
- **The new-language gate sets don't separate the models.** v2.0 already leaks only 3 of
  their 315 values. Each candidate also loses one Maltese value, in a language none of them
  trained on.
- **A leaks a third fewer MAPA names than v2.0** (43 of 740 vs 63; held out,
  report-only, scored on this Mac because MAPA court text never leaves it). That is the gain
  the data was meant to bring. It doesn't overrule a gate, but it points at what to fix next:
  keep the multilingual names and stop teaching loose addresses.
- **The LAB-1525 Muse corpus had to be rebuilt.** It was lost when its worktree was removed
  (LAB-1542). The template data rebuilt byte for byte.
- **Cost: about $1.10 of Modal free credit and $2.50 of Meta credits** (the Muse rerun).
  Nothing was published. The production pin is unchanged.

Full tables, per-language results and the reproduce steps:
[results README](../../eval/results/2026-10-29-lab-1535-ner-v4/README.md).
