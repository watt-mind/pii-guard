# Blurring the context around placeholders barely changes linkage (2026-10-30)

LAB-1152. **Before:** given a five-value candidate list, Muse Spark Open linked a masked value
to the right candidate 39.2 % of the time, against 20 % chance
([2026-10-27 red team](../../eval/results/2026-10-27-redteam/README.md)). The guess was that
readable context did it: `Ms` before a name, a Hungarian `-nek` that says the name ends in a
front vowel, a kept company name that matches an e-mail domain.

**After:** an opt-in linkage protection that removes those clues, and a measurement that
tests the guess.

- **What it does.** [`vault/generalize.py`](../../src/pii_guard/vault/generalize.py) drops
  gendered titles next to a name (`Ms`, `Herr`, `Frau`, `úr`, `-né`), makes German
  salutations neutral, coarsens ages to the decade and writes Hungarian case endings on a
  name in one vowel harmony. Unmasking still restores `Teszt Eleknek`, because the Hungarian
  matcher now re-inflects a suffix written in the wrong harmony. `LINKAGE_OVERRIDES` in
  [`policy.py`](../../src/pii_guard/policy.py) also masks organizations.
- **Measured** on the same 81 fictional documents, one masking run, three contexts
  ([results](../../eval/results/2026-10-30-redteam-generalized/README.md)): `decoys` 39.3 %
  (the baseline reproduces), `decoys+generalized` **36.5 %**, `decoys-isolated` (no
  cross-type candidates) **36.2 %**. `PERSON` 47.9 → 43.2 %, `EMAIL` 76 → 76 %. Both drops
  are within the noise of one run.
- **Standard suite:** precision, recall and leak rate unchanged; generalization reuses the
  detections.
- **Cost:** about $2.00 of Baseten credits (attacker $1.77, masking detector $0.23).
- **Decision:** the guess was mostly wrong. This corpus has few such clues (the generalizer
  made 10 rewrites in 81 documents), and taking away cross-candidate agreement helps no more.
  The protection stays opt-in, as a library function and an eval mode, not a gateway default.
  The next measurement is the candidate lists themselves: a larger pool, matched to each
  value's format.
