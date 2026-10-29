# A Polish language pack: pl-pii-bench leak 17.5 → 3.5 % (2026-10-28)

LAB-1400, found in LAB-1392. Fast mode leaked 17.5 % of the labeled values on
pl-pii-bench, and 141 of the 144 leaks were Polish identifiers that no rule knew. So we built
a `pl` pack by following [languages.md](../languages.md), with the German pack as the worked
example. It adds validators for PESEL (including the date of birth and its century offset),
NIP (compact and in both dashed layouts), REGON 9 and 14, the ID card (dowód osobisty) and the
passport. It also adds cue words (a labeled number is masked even when its check digit fails,
and a driving-licence number after `prawo jazdy`), national phone numbers, addresses (`ul.`,
`al.`, `os.`, `pl.`, `NN-NNN Miasto`), the case endings that leave a name intact (`Nowaka`,
`Kowalskiego`), prompt notes, ID-card captions and brand names.

Fast mode (rules + the published NER v2.0) on pl-pii-bench, same commit, without and with the
pack ([before](../../eval/results/runs/2026-10-28-lab-1400-pl-pii-bench-before.json),
[after](../../eval/results/runs/2026-10-28-lab-1400-pl-pii-bench-after.json),
[per lane](../../eval/results/2026-10-28-lab-1400-pl-pack/README.md)):

| fast mode | leak | `identifiers` leak | `negative` over-masked spans | F1 |
| -- | --: | --: | --: | --: |
| before | 17.5 % | 47.0 % | 88 | 79.6 % |
| **after** | **3.5 %** | **9.0 %** | 117 | **89.2 %** |

- **Tuned without the test set.** pl-pii-bench has no dev split and is report-only. The pack
  was tuned on the new hand-written `pl-smoke` (11 documents: fast leak 0.0 %, rules 39.5 %)
  and on a 60-document synthetic dev split (seed 1400, not committed: fast leak 0.0 %).
  pl-pii-bench was scored once, at the end.
- **What is left.** All 27 identifiers that still leak fail their check digit and have no cue
  the pack knows. No checksum-valid value leaks (0 of 192).
- **Over-masking on the `negative` lane rose from 88 to 117 spans.** The validators reject
  every value there. The extra masks come from the cue rule: the lane labels numbers with a bad
  check digit (`PESEL …`), and pii-guard masks a labeled identifier whatever its check digit,
  since a mistyped real one is still personal data. The benchmark counts them as not personal
  data, so this target and the cue requirement conflict. We kept the policy.
- **Nothing else moved.** The hu/en/de smoke, synth-sample, ai4privacy and negative sets give
  the same counts before and after (rules, and fast on smoke). Rules alone on pl-pii-bench go
  from 84.1 to 54.1 %.
- **Cost:** $0. Everything ran on a local CPU.
