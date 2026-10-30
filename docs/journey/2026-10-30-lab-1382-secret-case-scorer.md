# The scorer keys `SECRET` values by case, the same as the vault (2026-10-30)

LAB-1382. Since LAB-1350 the vault treats two tokens that differ only in letter case as two
credentials with two placeholders. The eval scorer still grouped gold values case-folded, so it
counted them as one entity and charged the vault for the second placeholder. The old vault, which
collapsed both tokens into one placeholder (and could not round-trip them), scored 100 %
consistency. The metric rewarded the bug.

Now leak dedup and consistency grouping key `SECRET` (`CASE_SENSITIVE_TYPES`) by exact value,
with only the detection fold and whitespace normalized, and only an exact-case occurrence of a
`SECRET` counts as a leak. Every other type is unchanged. Rules detector, secrets fixture (22
documents, 38 gold spans: 36 `SECRET`, 2 `EMAIL`;
[run record](../../eval/results/runs/2026-10-30-secrets-case-sensitive.json)):

| Scorer | Consistency | `SECRET` leak values | Leak | Round trip |
|---|---:|---:|---:|---:|
| before | 94.4 % (34/36; multi-occurrence 0/2) | 34 | 0.0 % | 100 % |
| after | 100.0 % (38/38) | 36 | 0.0 % | 100 % |

- **Gate:** the `secrets` suite had no run record matching its fixture since LAB-1383 changed it;
  this record restores its baseline. Limits unchanged.
- **Cost:** $0, rules only, local.
