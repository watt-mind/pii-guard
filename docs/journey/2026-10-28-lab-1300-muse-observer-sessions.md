# One Muse task, one vault session, on the plain URL too (2026-10-28)

LAB-1300. **Without the session path, Muse Code split one task over four vault sessions.** The
gateway picks a session per `prompt_cache_key` when the URL names none (LAB-1286), and Muse
sends one key for its main agent (`tbh:main:<conversation uuid>`) and one per reminder
observer (`tbh:skill-reminder:<first 8 hex of that uuid>:...`, `goal-`, `verify-`). Every value
was masked under up to four placeholders, and the observers detected the same instructions
again in sessions of their own. Everything was still restored.

- **Observers follow their conversation.** The gateway now remembers each main key's session
  under its 8-hex prefix and the client identity, and an observer key with the same prefix and
  identity uses that session. Main keys keep their own sessions, and nothing is shared across
  client identities. The index is in memory, like the vault, and holds the newest 4,096
  conversations. An observer seen before its main key keeps a session of its own, as before.
- **Limit.** The prefix is a UUIDv7 timestamp, about 65 seconds wide. When one client starts
  two Muse conversations in the same window, the observers follow the newer one. The LAB-1299
  captures had two runs with the same prefix.

Scripted Muse 1.4.14 e2e (`python -m pii_guard.integrations.e2e --client muse-code --session
auto`), `develop` → the fix:

| | before | after | path URL |
| -- | -- | -- | -- |
| Vault sessions for the task | 4 | 1 | 1 |
| Gold values under more than one placeholder | 14 of 14 | 0 of 14 | 0 of 14 |
| Most placeholders for one gold value | 4 | 1 | 1 |
| Distinct placeholders upstream | 57 | 15 | 15 |

- **Cost:** $0 (scripted upstream).
