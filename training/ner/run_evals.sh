#!/usr/bin/env bash
# Scorecards for the ner detector: rules vs rules,ner on the smoke sets, the committed synth
# samples and the generated synth dev split. Usage:
#   training/ner/run_evals.sh <label> [PII_GUARD_NER_MODEL]   (label: rules | zero-shot | fine-tuned)
set -euo pipefail
label="$1"
out="eval/results/ner/${label}"
mkdir -p "$out"
detectors="rules,ner"
[[ "$label" == "rules" ]] && detectors="rules"
[[ $# -ge 2 ]] && export PII_GUARD_NER_MODEL="$2"
sets=(eval/fixtures/hu-smoke.jsonl eval/fixtures/en-smoke.jsonl
      eval/fixtures/hu-synth-sample.jsonl eval/fixtures/en-synth-sample.jsonl)
for dev in eval/generated/ner-s7/hu-synth-dev.jsonl eval/generated/ner-s7/en-synth-dev.jsonl; do
  [[ -f "$dev" ]] && sets+=("$dev")
done
for fixture in "${sets[@]}"; do
  name="$(basename "$fixture" .jsonl)"
  uv run --extra ner pii-guard eval --fixtures "$fixture" --detectors "$detectors" \
    --json "$out/$name.json" --markdown "$out/$name.md" > /dev/null
  echo "wrote $out/$name.{json,md}"
done
