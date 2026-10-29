# The secrets suite can see the LAB-1349 and LAB-1350 leaks (2026-10-28)

LAB-1362, found by LAB-1349. **Before:** the gated `secrets` suite (17 documents) scored 100 %
recall, 0 % leak and 100 % round trip both before and after the LAB-1349 and LAB-1350 fixes. It
had none of their shapes, so it could not catch either bug coming back. **After:** 21 documents
in [`eval/fixtures/secrets/build_secrets.py`](../../eval/fixtures/secrets/build_secrets.py).
Against the old detector or the old vault, the gate now fails.

- **New documents** (synthetic, made up for the fixture):
  - `padded-quotes`: whitespace inside the quotes, `password = " x"`, `token: "  x  "`.
  - `bracketed-password`: `password="a[b]c"`, `passwd = 'a(b)c'`, a password that starts
    with `[`.
  - `case-differing-tokens`: two GitHub-style tokens and two assigned tokens that differ only
    in letter case.
  - `neg-template-fields`: a hard negative. `"{password}"`, `f"{db_password}"`,
    `'%(passwd)s'`, `creds[0]`, `cfg[password]` and `pwd: /home/...` must stay readable.
- **Known miss, not in the gated file:** a literal quoted password that contains a `{word}`
  group (`password="Fake{0000}pw"`) is read as a format field and left in clear. It is
  documented in the builder. The suite's leak limit is 0.0, so it is a follow-up (LAB-1383)
  and not a failing document.

Rules only, offline. *Now* is `develop` @ `c45e64d` with the new fixtures
([run record](../../eval/results/runs/2026-10-28-secrets-fixtures.json)). The other two columns
put the detector from before PR #146 or the vault from before PR #147 back on the same 21
documents (not recorded).

| detector / vault | leak | recall (exact) | round trip | consistency |
| -- | -- | -- | -- | -- |
| before LAB-1349 (pre #146) | 9.7 % | 81.8 % | 100 % | 74.2 % |
| before LAB-1350 (pre #147) | 0.0 % | 100 % | 95.2 % | 100 % |
| now | 0.0 % | 100 % | 100 % | 93.5 % |

- **Consistency reads 93.5 %, not 100 %, and the vault is right.** The scorer groups gold
  values by case-folded text, so it counts the two case-differing tokens as one entity. It
  then charges the vault for giving them two placeholders, which LAB-1350 made the correct
  behavior. The old vault, which collapsed them, scores 100 %. This is a scorer follow-up
  (LAB-1382): SECRET should be grouped case-sensitively, the same as in the vault.
- **Cost:** $0. No detector or vault change.
