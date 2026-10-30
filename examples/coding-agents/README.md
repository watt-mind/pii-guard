# Coding agents: the fictional mini-repo

A tiny "support desk" project for a bakery. A coding agent works on it through pii-guard in
the end-to-end test ([tests/integrations/test_pi_e2e.py](../../tests/integrations/test_pi_e2e.py))
and the live run (`python -m pii_guard.integrations.e2e`). **Every value is fictional**
(ADR 0005): names like *Jane Placeholder*, `example.*` e-mail addresses, test phone numbers
and textbook IBANs. The keys in `env.fake` are fake.

| File | What it carries |
|---|---|
| `mini-repo/client-letter.md` | A client letter: two names, two e-mail addresses, a phone number, an IBAN |
| `mini-repo/customers.csv` | Three customers: name, e-mail, phone and IBAN per row (en, hu, de) |
| `mini-repo/env.fake` | Fake keys, a fake password and a support address. The harness copies it in as `.env` |
| `mini-repo/src/notify.py` | Ordinary code: identifiers, a path and a URL that must *not* be masked |
| `gold.json` | The values that must never reach the model (the `.env` secrets too, `SECRET` type) and the known gaps (none since LAB-1258) |

The task the agent gets: read the letter, the CSV and `.env`, then write `reply.md` with the
client's IBAN, e-mail and phone, plus every customer's e-mail. The model only ever sees
placeholders. `reply.md` ends up with the real values, because the agent's `write` tool-call
arguments come back restored.

Try it yourself with pi: see [docs/integrations/pi.md](../../docs/integrations/pi.md).
