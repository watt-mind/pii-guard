# A literal password with a `{word}` in it is masked, templates still are not (2026-10-30)

LAB-1383. The secrets rule dropped any quoted value after a password key that contained a
`{...}` group anywhere, to keep format templates like `password = "{password}"` readable. That
also dropped literal passwords: `password="Fake{0000}pw"` and `db_password = 'pre{fix}0000x'`
reached the model in full. Now a quoted value is a template only when it looks like one: the
whole value is one field, it has a `%(x)s` or positional (`{}`, `{0}`) field, it has two or more
fields (`{user}:{password}@{host}`), or a field names a credential (`pw-{db_password}`).

The five shapes that were a documented known miss moved into the gated secrets fixture
(`eval/fixtures/secrets/en-secrets.jsonl`, document `en-secrets-brace-literal-password`), and
the template hard negatives grew from 4 to 13 lines (`en-secrets-neg-template-fields`). Rules
detector, same fixture file (22 documents, 36 gold `SECRET` values):

| Detector | `SECRET` recall | `SECRET` precision | Leak (overall) | Over-masking |
|---|---:|---:|---:|---:|
| before | 86.1 % | 100.0 % | 13.9 % | 0.0 % |
| after | 100.0 % | 100.0 % | 0.0 % | 0.0 % |

- **Gate:** the `secrets` suite keeps its leak limit of 0.0; every other suite is unchanged.
- **Kept readable:** `"{password}"`, `f"{db_password}"`, `"%(passwd)s"`, `"Synth{0}pass"`,
  `"{cfg.db.password}"`, `"{prefix}-{suffix}"`, `"{{ db_password }}"` and `"${DB_PASSWORD}"`.
- **Cost:** $0, rules only, local.
