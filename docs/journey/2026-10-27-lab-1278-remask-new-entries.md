# The second masking pass only looks for new values (2026-10-27)

LAB-1278. **Every gateway request masked each history text twice, and the second pass ran
every value of the session again.** The second pass exists so that a value confirmed in a later
message is masked in earlier ones too. But each text had already been scanned for every value
that existed when it was masked, and those occurrences were placeholders by then. Only values
created after that point can find anything new.

- **Entry generations.** The vault session now counts a generation. It goes up when a value is
  added, or when a value gets a new surface form or alias that changes what it matches. Each
  masked text records the generation it was masked at. The second pass scans only the values
  that changed after it. A request that adds no new value skips the second pass.
- **Same output.** A placeholder can create a word boundary that was not there before:
  `0101Placeholder` becomes `[[PHONE_x]]Placeholder`, and `Placeholder` then matches on its
  own. A full second pass finds those matches, so the shortcut checks every placeholder that
  touches a word. It rescans when a value ends right before the placeholder. When a word starts
  right after it, it tries the older values at that position. On 30,000 random sessions with
  values glued together, inflected, NFD-composed and split by zero-width characters, the output
  is byte-identical to the full pass. A gateway session that confirms names late (including the
  LAB-1284 widening cases) also gives byte-identical bodies and answers.

Measured on an M1 Max under heavy load, `develop` and the fix alternated three times, medians.
The session is the LAB-1268 bench: each turn adds a new email and phone, the restored answer
goes back as history, fast mode with rules only, and a 0 ms mock upstream.

| | turn 20 | turn 60 | turn 120 |
| -- | -- | -- | -- |
| Gateway `mask` stage | 5.8 → 4.8 ms | 31.4 → 20.1 ms | 118 → 79 ms (−33 %) |
| Values scanned per request | 3,044 → 1,560 | 28,324 → 14,280 | 114,244 → 57,360 |

In the vault alone (120 texts), the second pass drops from about 24 to 2.5 ms (about 10×). The
first pass is unchanged and now accounts for most of the mask stage.

- **Cost:** $0.
