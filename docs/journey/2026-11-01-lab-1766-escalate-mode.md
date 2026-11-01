# Escalate mode: Muse Spark Open looks only where fast mode is unsure (2026-11-01)

LAB-1766. A third gateway mode between `fast` and `audit`. Fast mode runs as before; a
selector picks the places it is unsure of (low-score NER spans, capitalised words after a form
of address or next to a name, long numbers no rule matched, unvalidated rules-vs-NER type
conflicts), and only windows of about ±200 characters around them go to Muse Spark Open, with
every value already found replaced by a placeholder. The model can add spans or settle a type,
never unmask one; a failed call masks the uncertain words. Text with nothing uncertain makes
no call. Design and settings: [architecture-gateway.md](../architecture-gateway.md#escalate-mode).

**Fast against escalate,** same documents and code
([results](../../eval/results/2026-11-01-lab-1766-escalate/README.md)):

| | Hand-written (106 docs) fast / escalate | Ai4Privacy (600 docs) fast / escalate |
|---|--:|--:|
| Leak | 0.51 % / 0.34 % (3 → 2 of 583) | 0.37 % / 0.37 % (8 of 2,185) |
| Over-masking | 0.41 % / 0.54 % (3 → 4) | 0.28 % / 0.28 % |
| Documents escalated | 46 % | 30 % |
| Added latency, escalated docs, p50 / p95 | 1.5 / 2.9 s | 1.4 / 2.8 s |
| Cost per 1,000 messages | $0.89 | $0.57 |

The leak change is one vehicle plate on the hand-written set and nothing on Ai4Privacy: within
noise. Escalate is about a quarter to a third of audit's cost and sends far less text, but on
these sets it does not cut leaks measurably, so it stays opt-in and the hosted default stays
fast mode. Cost of the evaluation: $0.56 of Baseten credit (fictional and public synthetic
documents only; no court text left the machine).
