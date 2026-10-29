/**
 * How to get free-text names masked, NER first (LAB-1291): the on-device NER is the production
 * path; audit mode's LLM detector is a remote spot check, not the fix. The install hint holds
 * for both a checkout and `uvx` (the `pii-guard up` banner prints the exact command).
 */
export function NerHint() {
  return (
    <>
      the on-device NER: install the <code className="font-mono">ner</code> extra (<code className="font-mono">wattmind-pii-guard[ner]</code>) and restart;{" "}
      <code className="font-mono">pii-guard up</code> prints the exact install command when it starts
    </>
  );
}
