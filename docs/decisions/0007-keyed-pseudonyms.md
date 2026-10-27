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
