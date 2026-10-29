# Person placeholders vs "Customer n" labels (2026-10-29)

LAB-1475. Does a person placeholder next to an identity number make `muse-spark-1.3` refuse,
as LAB-1471's through-gateway check (customers named "Customer 1" and "Customer 2", no
refusals) suggested? [`probe-person-labels.json`](probe-person-labels.json) is the output of

    set -a; . ../pii-guard/.env; set +a
    uv run --no-sync python scripts/probe_placeholder_refusals.py \
        --conditions baseline,labels --scenarios pi-add-taj,pi-create-contacts --reps 2 \
        --max-calls 8 --ticket LAB-1475 \
        --out eval/results/2026-10-29-lab-1475-harness-rerun/probe-person-labels.json

Placeholders only, no placeholder note in either arm (with the note LAB-1471 measured 0 of 15
refused, so there is nothing to compare). The turns are LAB-1471's two most refused ones
([scenarios](../2026-10-29-lab-1471-placeholder-refusals/README.md)).

| Condition | What the model sees | OK | Refused |
|---|---|---|---|
| `baseline` | `[[PERSON_…]]` placeholders for the two customers | 4 of 4 | 0 of 4 |
| `labels` | "Customer 1" / "Customer 2" instead | 2 of 4 | 2 of 4 |

Both refusals are `pi-add-taj` under `labels`: the model calls the TAJ szám "a sensitive
Hungarian social security identifier" and won't copy it. The hypothesis is not supported:
taking the person placeholders out does not stop the refusal; the field name next to the
value is enough. 4 turns an arm is a small sample, and the baseline refused less often here
than in LAB-1471 (0 of 4 against 4 of 6), so read this as "labels are not the fix", not as a
rate. 8 calls to the Meta Model API. The real-harness re-run this belongs to is
[harness-matrix-2026-10-29.md](../../../docs/integrations/harness-matrix-2026-10-29.md).
