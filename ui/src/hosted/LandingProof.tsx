import type { ReactNode } from "react";
import { AGENT_TRAFFIC, HARD_CASES, INFLECTION, LATENCY, OPEN_MODELS, POLISH, SMOKE_BY_LANGUAGE } from "./proof";

/*
 * The landing's second row of results (LAB-1656), every figure from `proof.ts` (checked against
 * docs/benchmarks.md by proof.source.test.ts): agent traffic against the comparison tools, our NER
 * against other open models with the same rules, and the narrower facts that matter for agents
 * (each language, valid and mistyped numbers, Hungarian inflection, CPU cost, Polish).
 */

const cell = "px-2 py-2 text-right font-mono tabular-nums";
const head = "px-2 py-2 text-right font-medium";
const LANGUAGE: Record<string, string> = { de: "German", en: "English", hu: "Hungarian", pl: "Polish" };

function Table({ caption, children, label }: { caption: string; label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="-mx-4 overflow-x-auto px-4 focus-visible:outline-2 focus-visible:outline-ink sm:mx-0 sm:px-0">
      <table className="w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

/**
 * Agent traffic: over-masking first, then leak, against the lowest-leak other tool (both on the
 * same documents), so a low leak bought by masking everything shows.
 */
export function AgentTrafficTable() {
  const ours = AGENT_TRAFFIC.find((r) => r.ours)!;
  const rival = AGENT_TRAFFIC.filter((r) => !r.ours && !r.partial).reduce((a, b) => (Number(b.leak) < Number(a.leak) ? b : a));
  const partial = AGENT_TRAFFIC.filter((r) => r.partial);
  return (
    <figure className="rounded-xl border border-line bg-surface p-4 sm:p-6">
      <h3 className="text-base font-medium text-ink">Agent traffic: tool calls, JSON and logs</h3>
      <p className="mt-1 text-sm text-ink">
        {ours.over}&nbsp;% of masked spans weren’t personal data, against {rival.over}&nbsp;% for {rival.system}. Leaked: {ours.leak}&nbsp;% against {rival.leak}&nbsp;%.
      </p>
      <p className="mt-1 mb-4 text-xs text-muted">Same {ours.docs} documents for every tool. Lower is better in both columns.</p>
      <Table label="Agent traffic results, scrolls sideways" caption="Over-masking and leak on generated agent traffic, by tool">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th scope="col" className="py-2 pr-3 font-medium">Tool</th>
            <th scope="col" className={head}>Over-masked</th>
            <th scope="col" className={head}>Leaked</th>
            <th scope="col" className={head}>Docs</th>
          </tr>
        </thead>
        <tbody>
          {AGENT_TRAFFIC.map((r) => (
            <tr key={r.system} className="border-b border-line last:border-0">
              <th scope="row" className={["py-2 pr-3 text-left", r.ours ? "font-medium text-ink" : "font-normal text-muted"].join(" ")}>
                {r.system}
                {r.partial && <span className="ml-1 text-faint" aria-label="ran on fewer languages">§</span>}
              </th>
              <td className={cell}>{r.over}&nbsp;%</td>
              <td className={cell}>{r.leak}&nbsp;%</td>
              <td className={`${cell} text-muted`}>{r.docs}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      {partial.length > 0 && (
        <figcaption className="mt-3 text-xs text-muted">§ Not run on every language, so not like-for-like: {partial.map((r) => `${r.system} (${r.partial})`).join("; ")}.</figcaption>
      )}
    </figure>
  );
}

/** Our NER against the other open PII models, the same rules around each: only the model differs. */
export function OpenModelsTable() {
  return (
    <figure className="rounded-xl border border-line bg-surface p-4 sm:p-6">
      <h3 className="text-base font-medium text-ink">Our NER against other open PII models</h3>
      <p className="mt-1 mb-4 text-xs text-muted">Hand-written German, English, Hungarian and Polish set. Each model runs inside PII Guard with the same rules, so only the model differs. The other models were scored on an earlier commit; v2.0’s leak, F1 and over-masking were the same on both.</p>
      <Table label="Open model comparison, scrolls sideways" caption="Leak, F1 and over-masking of open PII models with the same rules">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th scope="col" className="py-2 pr-3 font-medium">Model</th>
            <th scope="col" className={head}>Leaked</th>
            <th scope="col" className={head}>F1</th>
            <th scope="col" className={head}>Over-masked</th>
          </tr>
        </thead>
        <tbody>
          {OPEN_MODELS.map((m) => (
            <tr key={m.id} className="border-b border-line last:border-0">
              <th scope="row" className={["py-2 pr-3 text-left", "ours" in m ? "font-medium text-ink" : "font-normal text-muted"].join(" ")}>
                <a className="underline-offset-4 hover:underline" href={`https://huggingface.co/${m.id}`}>{m.model}</a>
              </th>
              <td className={cell}>{m.leak}&nbsp;%</td>
              <td className={cell}>{m.f1}&nbsp;%</td>
              <td className={cell}>{m.over}&nbsp;%</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </figure>
  );
}

function Fact({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <li className={["space-y-1 bg-surface p-4", wide ? "sm:col-span-2" : ""].join(" ")}>
      <h3 className="text-sm font-medium text-ink">{title}</h3>
      <p className="text-sm text-muted">{children}</p>
    </li>
  );
}

/** The narrower facts, in the order the landing argues them. */
export function ProofFacts() {
  const [ours, ...tools] = HARD_CASES.rows;
  const langs = Object.entries(SMOKE_BY_LANGUAGE);
  const allZero = langs.every(([, v]) => Number(v) === 0);
  return (
    <ul aria-label="More measured results" className="grid grid-cols-[minmax(0,1fr)] gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
      <Fact title={allZero ? "No leaks in any language" : "Leaks per language"}>
        {langs.map(([lang, leak]) => `${LANGUAGE[lang] ?? lang} ${leak}\u00a0%`).join(" · ")} on the hand-written set.
      </Fact>
      <Fact title="Valid and mistyped numbers">
        On {HARD_CASES.set}: {ours!.valid}&nbsp;% of checksum-valid numbers leaked and {ours!.invalid}&nbsp;% of mistyped ones (
        {tools.map((t) => `${t.system} ${t.valid} / ${t.invalid}\u00a0%`).join(", ")}).
      </Fact>
      <Fact title="Hungarian inflection">
        Names change with every case, and the ending stays outside the placeholder. On {INFLECTION.docs} hand-written documents full of inflected names, {INFLECTION.leak}&nbsp;% of values leaked, against {INFLECTION.rulesLeak}&nbsp;% with rules alone.
      </Fact>
      <Fact title="On a CPU, no GPU">The NER takes {LATENCY.value} per message ({LATENCY.hint}).</Fact>
      {/* Five facts on a three-column grid: the last one closes the row. */}
      <Fact title="Polish, through its language pack" wide>
        {POLISH.leak}&nbsp;% leaked on the public pl-pii-bench set ({POLISH.docs} documents), against {POLISH.rulesLeak}&nbsp;% with rules alone.
      </Fact>
    </ul>
  );
}
