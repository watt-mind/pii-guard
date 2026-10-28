# An order number is not a personal ID either (2026-10-28)

LAB-1327. **Before:** the Hungarian personal-ID rule masked a checksum-valid 11-digit number
after an order or reference label (`Order 75302022056`, `ticket: 28309121692`) as
`ID_DOCUMENT`. The TAJ and tax-ID rules already skipped such numbers (LAB-1227), and this one
never got the check. On agent-traffic-dev (rules) that was 1 of 9 `ID_DOCUMENT` predictions
wrong, and over-masking was 0.117 %. **After:** 8 of 8 correct, over-masking 0.0 %, and F1
0.6703 → 0.6706. Leak stays at 44.9 %.

- **Fix.** `_find_hu_personal_id` now skips a hit when `reference_or_amount_before()` is true
  and no personal-ID cue stands before it. A cue (`személyi azonosító`, `személyi szám`,
  `personal id`) still wins over an order label and scores 0.99; a bare number scores 0.85.
- **Other sets.** agent-traffic (test split, rules) had the same false positive in German
  (29 predicted, 28 correct → 28 of 28), with the same leak. The quality gate has the same
  leak and over-masking in all 6 suites.
- **Cost:** $0, rules only and offline.
