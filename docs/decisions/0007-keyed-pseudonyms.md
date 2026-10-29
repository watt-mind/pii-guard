# 0007. Keyed, reversible pseudonyms

- **Status:** accepted
- **Date:** 2026-10-26

## Context

One-way redaction (`[REDACTED]`) makes the model's answer useless when it needs to refer to a
specific party. Sequential placeholders (`PERSON_1`, `PERSON_2`) are reversible but guessable
and leak structure. We need placeholders the model can reason with, that we can reverse, and
that nobody else can.

## Decision

- Placeholders are typed and keyed: `[[<TYPE>_<id>]]`, where `id` is a truncated
  HMAC-SHA256 of the normalized value under a per-tenant key (optionally mixed with a session
  key).
- The same value maps to the same placeholder within a session, so the model sees consistent
  references.
- Collisions within a session are detected and resolved by extending the id.
- Occurrences of a value match case-insensitively and, by default, share its placeholder;
  unmask restores the casing the value was first written in. Opt-in
  `PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS` mixes the casing class (upper, lower, mixed)
  into the HMAC for occurrences in another class, so they get their own id and round-trip
  exactly (LAB-1119).
- The mapping from placeholder to original value (and its inflected surface forms) is stored
  only inside pii-guard, with a TTL.

## Consequences

- Without the tenant key, placeholders can't be reversed, enumerated or linked across tenants.
- Key rotation makes old placeholders unresolvable; that is intended.
- Re-identification needs the mapping to still exist; long-running workflows must pick a TTL
  that covers them.

## Addendum (2026-10-29): the placeholder note (LAB-1471)

**Context.** The type label is part of what the model sees. On `muse-spark-1.3` it is also a
reason to refuse: in the real-harness run (LAB-1469) 7 of 15 agent turns ended in a full or
partial refusal to copy `[[NATIONAL_ID_HU_TAJ_…]]` or `[[BANK_ACCOUNT_…]]` ("a sensitive
health-insurance identifier"), although the gateway answered every request. A project
`AGENTS.md` hint saying placeholders are restored locally was present and not enough.

**Options measured** (synthetic replay of the failing turns, 60 calls,
[results](../../eval/results/2026-10-29-lab-1471-placeholder-refusals/README.md)):

| Option | Refused |
|---|--:|
| typed labels, `AGENTS.md` hint only (before) | 5 of 15 |
| (a) a gateway system note: placeholders are opaque tokens, copy them as written | **0 of 15** |
| (b) neutral labels (`[[REF_<id>]]`) for identifier and account types | 4 of 15 |
| (c) both | 0 of 15 |

**Decision.** (a). When a forwarded request holds a placeholder its session issued, the gateway
puts one constant note in front of it (Chat Completions: a first `system` message; Responses:
the start of `instructions`). On by default; `PII_GUARD_GATEWAY_PLACEHOLDER_NOTE=false` turns
it off. The placeholder grammar and the type label stay as decided above.

**Why not (b).** It barely helped: the field names around a value (`IBAN:`, `TAJ szám:`) tell
the model what a neutral token stands for. It would also cost what the type label gives: the
model can't tell an email from an IBAN and so writes worse answers about them, and every
reader of `PLACEHOLDER_RE`'s type group (the mask API, the eval scorer, the red-team and e2e
reports, the visual labeller) would have to look the type up instead. Restore never depended on
the type: it is keyed by the whole placeholder string.

**Privacy.** The note is a fixed string: no value, no placeholder, nothing from the request. It
is added after masking, so it is never scanned and can't bring a value along. It holds no
placeholder-shaped token (`[[TYPE_id]]` doesn't match `PLACEHOLDER_RE`), so a model quoting it
back produces nothing the restorer would touch, and it can't collide with or forge a
placeholder. It tells the provider no more than the placeholders already do: that the request
was masked.

**Trade-offs.** About 100 tokens more per request that carries a placeholder. The note is the
first item, so a conversation that starts with placeholders keeps a stable prompt-cache prefix;
one that gets its first placeholder in a later turn changes its prefix once. It changes what
the model is told, which a deployment may not want (a provider that bills for system tokens, a
client that pins its whole prompt): hence the switch. The echo header reports it as
`placeholder_note: true` rather than as a message, so UIs that show the client's own system
message still find it.
