/**
 * How to get free-text names masked, NER first (LAB-1291): the on-device NER is the production
 * path; audit mode's LLM detector is a remote spot check, not the fix. torch and transformers
 * are core dependencies (LAB-1733), so rules only means they were skipped (the rules-only Docker
 * image) or the NER is switched off; the `pii-guard up` banner prints the exact command.
 */
export function NerHint() {
  return (
    <>
      the on-device NER: it ships with <code className="font-mono">wattmind-pii-guard</code>, so use an install that has torch and transformers (not the rules-only Docker image) and restart;{" "}
      <code className="font-mono">pii-guard up</code> prints the exact install command when it starts
    </>
  );
}
