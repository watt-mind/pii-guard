import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { TOOLS, firstRequest, loadSnippets, newSessionId, type Snippets, type SnippetsLoader, type SnippetsResult, type ToolId, type ToolSnippet } from "../api/connect";
import type { TrafficEvent, TrafficStatus } from "../api/traffic";
import { Button, SegmentedControl, Select } from "../components/ui";
import { readPref, writePref } from "../lib/storage";
import { exampleModel } from "../projects/api";
import { totalMasked } from "../lib/traffic";

/** The tabs, in order, while the server can't be asked (the server's list wins when it answers). */
const isTool = (v: string | null): v is ToolId => TOOLS.some((t) => t.id === v);
const SESSION_RE = /^[A-Za-z0-9_-]{1,128}$/;

/** What step 3 reads: the live traffic the console already follows (Overview, Logs). */
export interface QuickstartTraffic {
  events: readonly TrafficEvent[];
  status: TrafficStatus;
  source: "api" | "fixture";
}

export interface ConnectQuickstartProps {
  traffic?: QuickstartTraffic;
  /** Whether the gateway detects free-text names (the NER extra); null when unknown. */
  ner?: boolean | null;
  /** Open one call on the Logs screen. */
  onOpenLog?: (id: string) => void;
  /** Open the tool's vault session (Vault screen), by its traffic-log ref. */
  onOpenSession?: (ref: string) => void;
  load?: SnippetsLoader;
  /** A `#connect/<client>` deep link names this tab first (LAB-1314). */
  initialTool?: string | null;
}

/** One vault session per tool, kept across reloads, so the block stays the same and step 3
 *  can tell that tool's first request apart from every other call. */
function sessionFor(tool: ToolId): string {
  const saved = readPref(`connect-session-${tool}`);
  if (saved && SESSION_RE.test(saved)) return saved;
  const id = newSessionId();
  writePref(`connect-session-${tool}`, id);
  return id;
}

export function ConnectQuickstart({ traffic, ner = null, onOpenLog, onOpenSession, load = loadSnippets, initialTool = null }: ConnectQuickstartProps) {
  const [tool, setToolState] = useState<ToolId>(() => {
    if (isTool(initialTool)) return initialTool;
    const saved = readPref("connect-tool");
    return isTool(saved) ? saved : "muse-code";
  });
  const [session, setSession] = useState(() => sessionFor(tool));
  const [model, setModel] = useState<string | null>(null);
  const [result, setResult] = useState<{ key: string; value: SnippetsResult } | null>(null);
  const key = `${session}:${model ?? ""}`;

  useEffect(() => {
    const controller = new AbortController();
    load({ session, model }, controller.signal).then(
      (value) => !controller.signal.aborted && setResult({ key, value }),
      () => !controller.signal.aborted && setResult({ key, value: { state: "offline" } }),
    );
    return () => controller.abort();
  }, [load, session, model, key]);

  const setTool = (t: ToolId) => {
    setToolState(t);
    setSession(sessionFor(t));
    writePref("connect-tool", t);
  };
  // A `#connect/<client>` deep link arriving while the screen is open picks that tab.
  const [linked, setLinked] = useState(initialTool);
  if (initialTool !== linked) {
    setLinked(initialTool);
    if (isTool(initialTool)) setTool(initialTool);
  }
  const current = result?.key === key ? result.value : null;
  const snippets = current?.state === "ok" ? current.snippets : null;
  // Until the first answer, the tabs keep their place; after it, the server's list is the list.
  const tabs = snippets ? snippets.tools.map((t) => ({ id: t.id as ToolId, label: t.label })) : TOOLS;
  const snippet = snippets?.tools.find((t) => t.id === tool) ?? null;
  const label = tabs.find((t) => t.id === tool)?.label ?? tool;

  return (
    <section aria-labelledby="quickstart-title" className="min-w-0 overflow-hidden rounded-xl border border-line bg-surface">
      <div className="border-b border-line px-4 pt-4 sm:px-5">
        <h2 id="quickstart-title" className="text-lg font-normal text-ink">
          Start building with your coding agent
        </h2>
        <p className="mt-0.5 text-sm text-muted">Three steps: a gateway with a real model, one paste in your terminal, one prompt. Every block is filled in for this server.</p>
        <ToolTabs tabs={tabs} tool={tool} onTool={setTool} />
      </div>
      <div id={`quickstart-panel-${tool}`} role="tabpanel" aria-labelledby={`quickstart-tab-${tool}`} className="space-y-6 p-4 sm:p-5">
        {current === null ? (
          <p className="text-sm text-muted" role="status">
            Asking the server…
          </p>
        ) : snippets === null ? (
          <Unavailable missing={current.state === "missing"} tool={tool} />
        ) : snippet && !snippet.supported ? (
          <ComingSoon snippet={snippet} />
        ) : snippet ? (
          <>
            <StartStep snippets={snippets} />
            <PasteStep snippets={snippets} snippet={snippet} onModel={setModel} />
            <FirstRequestStep snippets={snippets} label={label} tool={tool} traffic={traffic} ner={ner} onOpenLog={onOpenLog} onOpenSession={onOpenSession} />
          </>
        ) : (
          <Unavailable missing tool={tool} />
        )}
      </div>
    </section>
  );
}

function ToolTabs({ tabs, tool, onTool }: { tabs: { id: ToolId; label: string }[]; tool: ToolId; onTool: (t: ToolId) => void }) {
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = tabs.findIndex((t) => t.id === tool);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]!;
    onTool(next.id);
    document.getElementById(`quickstart-tab-${next.id}`)?.focus();
  };
  return (
    <div role="tablist" aria-label="Your tool" className="-mx-1 mt-3 flex gap-1 overflow-x-auto [mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)] sm:[mask-image:none]">
      {tabs.map((t) => {
        const selected = t.id === tool;
        return (
          <button
            key={t.id}
            id={`quickstart-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`quickstart-panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onTool(t.id)}
            onKeyDown={onKey}
            className={[
              "relative shrink-0 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition-colors pointer-coarse:min-h-11",
              "after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full",
              selected ? "text-ink after:bg-ink" : "text-muted after:bg-transparent hover:text-ink",
            ].join(" ")}
          >
            {t.label}
            {t.id === "claude-code" && <span className="ml-1.5 rounded-sm bg-surface-2 px-1 py-px text-2xs font-normal text-muted">soon</span>}
          </button>
        );
      })}
    </div>
  );
}

function StartStep({ snippets }: { snippets: Snippets }) {
  const presets = snippets.presets;
  const [chosen, setChosen] = useState(presets[0]?.id ?? "meta");
  const up = snippets.upstream;
  if (up.connected) {
    return (
      <Step n={1} title="Start the gateway with a model" done>
        <p className="text-sm text-ink">
          Already connected to {up.label ?? "a model provider"}
          {up.origin ? <> at {mono(up.origin)}</> : null}. Nothing to do here.
        </p>
      </Step>
    );
  }
  const preset = presets.find((p) => p.id === chosen) ?? presets[0];
  return (
    <Step n={1} title="Start the gateway with a model">
      <p className="text-sm text-muted">
        {up.mock ? (
          <>This server runs the offline mock model: it echoes what it gets and can't drive an agent. Stop it and start it again with a real provider:</>
        ) : (
          <>No model provider is configured yet. Start the gateway with one:</>
        )}
      </p>
      {presets.length > 1 && preset && (
        <SegmentedControl label="Model provider" size="sm" options={presets.map((p) => ({ value: p.id, label: p.label }))} value={preset.id} onChange={setChosen} className="overflow-x-auto" />
      )}
      {preset && <CodeBlock text={preset.command} label={`Copy the ${preset.label} start command`} />}
      {preset && (
        <p className="text-xs text-muted">
          Your key stays in your shell: the gateway reads {mono(`$${preset.key_env}`)} and sends it to {mono(preset.base_url)} only with masked text. Already exported? Skip the first line.
        </p>
      )}
    </Step>
  );
}

function PasteStep({ snippets, snippet, onModel }: { snippets: Snippets; snippet: ToolSnippet; onModel: (m: string) => void }) {
  const title = snippet.kind === "request" ? "Send one fictional request" : `Paste this in a terminal to start ${snippet.label}`;
  return (
    <Step n={2} title={title}>
      <CodeBlock text={snippet.code} label={`Copy the ${snippet.label} block`} />
      <p className="text-xs text-pretty text-muted">
        {snippet.note}
        {snippet.kind === "connect" && (
          <>
            {" "}
            The same block: {mono(`pii-guard connect ${snippet.id} --print`)}.
          </>
        )}
      </p>
      {(snippet.more ?? []).map((m) => (
        <div key={m.title} className="space-y-1.5">
          <p className="text-xs font-medium text-ink">{m.title}</p>
          <CodeBlock text={m.code} label={`Copy the ${snippet.label} ${m.title} block`} />
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
        {snippets.models.length > 1 && snippets.model !== null && snippet.code.includes(snippets.model) && (
          <label className="flex items-center gap-2">
            Model
            <span className="w-64 max-w-full">
              <Select size="sm" value={snippets.model ?? ""} onChange={(e) => onModel(e.target.value)}>
                {snippets.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </span>
          </label>
        )}
        {snippet.tested_version && <span>Tested end to end with {snippet.label} {snippet.tested_version}.</span>}
        {snippet.docs && (
          <a href={snippet.docs} target="_blank" rel="noreferrer" className="text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink">
            Docs
          </a>
        )}
      </div>
      {!snippets.model &&
        (snippets.endpoint ? (
          <p className="text-xs text-muted">
            This endpoint lets your client choose the model: replace {mono("<model-id>")} with the model your client uses
            {exampleModel(snippets.upstream.preset) ? <>, for example {mono(exampleModel(snippets.upstream.preset)!)}</> : " (a model ID your endpoint serves)"}, or set it in the client’s own settings.
          </p>
        ) : (
          <p className="text-xs text-warn">The gateway lists no model yet: replace {mono("<model-id>")} with one your provider serves.</p>
        ))}
    </Step>
  );
}

function FirstRequestStep({
  snippets,
  label,
  tool,
  traffic,
  ner,
  onOpenLog,
  onOpenSession,
}: {
  snippets: Snippets;
  label: string;
  tool: ToolId;
  traffic?: QuickstartTraffic;
  ner: boolean | null;
  onOpenLog?: (id: string) => void;
  onOpenSession?: (ref: string) => void;
}) {
  const ask =
    tool === "curl" || tool === "python"
      ? "Run it."
      : `Ask ${label} something with fictional contact details in it, e.g. “Write a short note to jane.placeholder@example.net, phone +44 20 7946 0958”.`;
  const noNames =
    ner === false ? (
      <p role="note" className="text-xs text-warn">
        This server runs rules only: email addresses, phone numbers and IBANs are masked, free-text names are not (they reach the model as written). Install the ner extra to mask names.
      </p>
    ) : null;
  if (!snippets.session_ref || !traffic || traffic.source !== "api" || traffic.status.state === "disabled") {
    return (
      <Step n={3} title="Run one prompt">
        <p className="text-sm text-ink">{ask}</p>
        {noNames}
        <p className="text-xs text-muted">
          {traffic?.source === "fixture"
            ? "The console plays recorded demo traffic, so it can't watch for your first request here."
            : (
              <>
                The traffic log is off, so this page can't watch for the first request. {mono("pii-guard up")} turns it on; with {mono("pii-guard serve")}, turn it on
                yourself ({mono("PII_GUARD_TRAFFIC_LOG=masked")}).
              </>
            )}
        </p>
      </Step>
    );
  }
  const event = firstRequest(traffic.events, snippets.session_ref);
  if (!event) {
    return (
      <Step n={3} title="Run one prompt">
        <p className="text-sm text-ink">{ask}</p>
        {noNames}
        <p role="status" className="flex items-center gap-2 text-sm text-muted">
          <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-line-strong motion-reduce:animate-none" />
          Waiting for {label}…
        </p>
      </Step>
    );
  }
  const ok = event.outcome === "ok";
  const masked = totalMasked(event);
  const detected = Object.values(event.entities?.detected ?? {}).reduce((a, b) => a + (b ?? 0), 0);
  const kept = Math.max(0, detected - Object.values(event.entities?.masked ?? {}).reduce((a, b) => a + (b ?? 0), 0));
  return (
    <Step n={3} title="Run one prompt" done={ok}>
      <p role="status" className={["text-sm font-medium", ok ? "text-guard-ink" : "text-blocked"].join(" ")}>
        {ok ? (
          <>
            ✓ First request from {label}: {masked} {masked === 1 ? "value" : "values"} masked, {kept === 0 ? "0 of them reached the model" : `${kept} more kept by policy`}.
          </>
        ) : (
          <>
            First request from {label} was stopped ({event.error?.code ?? event.outcome}): nothing was sent to the model.
          </>
        )}
      </p>
      <p className="text-xs text-muted">
        {ok && masked === 0 ? "Nothing personal in that one: try a prompt with a fictional name or email address. " : null}
        Every later call in this session shows up in Logs too.
      </p>
      {noNames}
      {(onOpenLog || onOpenSession) && (
        <div className="flex flex-wrap gap-2">
          {onOpenLog && <Button onClick={() => onOpenLog(event.id)}>Open in Logs</Button>}
          {onOpenSession && event.session_ref && <Button onClick={() => onOpenSession(event.session_ref!)}>Open session in Vault</Button>}
        </div>
      )}
    </Step>
  );
}

function ComingSoon({ snippet }: { snippet: ToolSnippet }) {
  return (
    <div role="note" className="space-y-2 text-sm">
      <p className="font-medium text-ink">{snippet.label} is coming soon.</p>
      <p className="text-pretty text-muted">{snippet.note}</p>
      <p className="text-muted">Until then, Codex, OpenCode, Muse Code and pi are tested end to end through the gateway.</p>
    </div>
  );
}

function Unavailable({ missing, tool }: { missing: boolean; tool: ToolId }) {
  return (
    <div className="space-y-3 text-sm">
      <p className="text-ink">
        {missing ? "This PII Guard server predates the quickstart." : "The PII Guard API isn't reachable from this page."} Start the gateway with a model, then reload:
      </p>
      <CodeBlock text={"export META_API_KEY=<your-key>\npii-guard up --upstream meta"} label="Copy the start command" />
      <p className="text-xs text-muted">
        Or print this tool's block in a terminal: {mono(`pii-guard connect ${tool} --print`)}.
      </p>
    </div>
  );
}

const mono = (s: string) => <code className="font-mono text-xs">{s}</code>;

function Step({ n, title, done = false, children }: { n: number; title: string; done?: boolean; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 gap-y-2">
      <span
        aria-hidden="true"
        className={[
          "grid size-7 place-items-center rounded-full border font-mono text-xs",
          done ? "border-guard bg-guard-soft text-guard-ink" : "border-line text-muted",
        ].join(" ")}
      >
        {done ? "✓" : n}
      </span>
      <div className="min-w-0 space-y-2">
        <h3 className="pt-1 text-sm font-medium text-ink">
          <span className="sr-only">Step {n}: </span>
          {title}
          {done && <span className="sr-only"> (done)</span>}
        </h3>
        {children}
      </div>
    </div>
  );
}

export function CodeBlock({ text, label }: { text: string; label: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-line bg-surface-2">
      <div className="flex items-center justify-between gap-2 border-b border-line py-1 pr-1.5 pl-3 pointer-coarse:pr-2">
        <span className="text-2xs text-muted">{text.startsWith("import ") || text.startsWith("from ") ? "Python" : "Terminal"}</span>
        <CopyButton text={text} label={label} />
      </div>
      <pre className="min-w-0 overflow-x-auto px-3 py-2 font-mono text-ui whitespace-pre text-ink">{text}</pre>
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const copy = () => {
    const done = (r: "ok" | "failed") => {
      setCopied(r);
      setTimeout(() => setCopied(null), 1600);
    };
    if (!navigator.clipboard) return done("failed");
    navigator.clipboard.writeText(text).then(
      () => done("ok"),
      () => done("failed"),
    );
  };
  return (
    <Button size="sm" onClick={copy} aria-label={label} className="shrink-0">
      <span aria-live="polite">{copied === "ok" ? "Copied" : copied === "failed" ? "Select and copy" : "Copy"}</span>
    </Button>
  );
}
