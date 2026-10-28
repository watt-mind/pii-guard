import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { TOOLS, fetchSnippets, type Snippets, type ToolSnippet } from "../api/connect";
import { Button, ButtonLink, Field, Input, Notice, Select } from "../components/ui";
import { projectPath, type Endpoint, type ProjectList } from "../projects/api";
import { getSelectedProject, setSelectedEndpoint, useSelectedEndpoint } from "../projects/selection";
import { CodeBlock, CopyButton } from "../screens/ConnectQuickstart";
import { readPref, writePref } from "../lib/storage";
import { recovery, type Requester } from "./api";
import {
  ENDPOINT_KEY_ENV,
  META_KEY_URL,
  addMetaKey,
  endpointState,
  forgetShownKey,
  getShownKey,
  loadFirstRun,
  rememberKey,
  sendTestRequest,
  testRecovery,
  withKey,
  type FirstRun,
  type FirstRunState,
  type IssuedKey,
  type TestRoundTrip,
} from "./firstRun";
import { useHostedSession } from "./session";

type Loaded = { state: "loading" } | { state: "failed" } | { state: "ok"; endpoints: Endpoint[]; first: FirstRun | null; projectId: string };

/**
 * Hosted Connect, "Connect your client" (LAB-1455): the first screen after sign-in. The server
 * provisions a default endpoint once (`/v1/account/first-run`), so a new owner gets a guard key,
 * copy-paste blocks for their tool and a test request without creating anything. With sponsored
 * inference unavailable it first asks for one thing: the owner's own Meta API key.
 */
export function ClientSetup({ call }: { call: Requester }) {
  const session = useHostedSession();
  const sponsoredEnabled = session?.account.limits.sponsored_enabled === true;
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [revision, setRevision] = useState(0);
  const picked = useSelectedEndpoint();
  useEffect(() => {
    let live = true;
    (async () => {
      // An older server without first run: the console works as before.
      const first = await loadFirstRun(call).catch(() => null);
      const list = await call<ProjectList>("/v1/projects");
      const projectId = getSelectedProject() ?? list.default_project_id ?? list.projects[0]?.id;
      if (!projectId) return { first, endpoints: [], projectId: "" };
      const data = await call<{ endpoints: Endpoint[] }>(`${projectPath(projectId)}/endpoints`);
      return { first, endpoints: (data.endpoints ?? []).filter((e) => e.enabled), projectId };
    })().then(
      (value) => live && setLoaded({ state: "ok", ...value }),
      () => live && setLoaded({ state: "failed" }),
    );
    return () => {
      live = false;
    };
  }, [call, revision]);

  const ok = loaded.state === "ok" ? loaded : null;
  const endpoints = ok?.endpoints ?? [];
  const first = ok?.first ?? null;
  // The header's pick when it is one of these; else the default endpoint; else the first enabled.
  const current = endpoints.find((e) => e.id === picked) ?? endpoints.find((e) => e.id === first?.endpoint.id) ?? endpoints[0];
  const isDefault = Boolean(current && first && current.id === first.endpoint.id);
  const state: FirstRunState | null = current ? endpointState(current, first?.sponsored_enabled ?? sponsoredEnabled) : null;

  return (
    <section aria-labelledby="client-setup-title" className="space-y-4">
      <div>
        <h2 id="client-setup-title" className="text-lg font-normal text-ink">
          Connect your client
        </h2>
        <p className="mt-0.5 text-sm text-pretty text-muted">
          {state === "needs_key"
            ? "One step first: your endpoint needs a model key. Then copy your guard key, paste one block into your tool and send a test request."
            : "Your client sends real data to your pii-guard endpoint. The model gets placeholders; the answer comes back with the real values. Three steps: copy your guard key, paste one block into your tool, send a test request."}
        </p>
      </div>
      {loaded.state === "loading" ? (
        <p role="status" className="text-sm text-muted">
          Preparing your endpoint…
        </p>
      ) : loaded.state === "failed" ? (
        <Notice tone="danger" live action={<Button size="sm" onClick={() => setRevision((n) => n + 1)}>Retry</Button>}>
          Your endpoints could not be loaded. Retry, or open <a className="underline underline-offset-4" href="#projects">Projects</a>.
        </Notice>
      ) : !current || !ok ? (
        <NoEndpointPreview />
      ) : (
        <>
          {endpoints.length > 1 && (
            <Field label="Endpoint" hint="Also sets the endpoint the header's menu inspects." className="sm:max-w-md">
              <Select value={current.id} onChange={(e) => setSelectedEndpoint(e.target.value)}>
                {endpoints.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <ConnectEndpoint
            key={current.id}
            call={call}
            endpoint={current}
            projectId={ok.projectId}
            state={state!}
            isDefault={isDefault}
            first={isDefault ? first : null}
            onChanged={() => setRevision((n) => n + 1)}
          />
        </>
      )}
    </section>
  );
}

function ConnectEndpoint({
  call,
  endpoint,
  projectId,
  state,
  isDefault,
  first,
  onChanged,
}: {
  call: Requester;
  endpoint: Endpoint;
  projectId: string;
  state: FirstRunState;
  isDefault: boolean;
  first: FirstRun | null;
  onChanged: () => void;
}) {
  const url = first?.gateway_url || `${globalThis.location?.origin ?? ""}/e/${endpoint.id}/v1`;
  // The key this page was shown (first sign-in, or "Create a new guard key"): the blocks embed it.
  const [key, setKey] = useState<IssuedKey | null>(() => getShownKey(endpoint.id));
  const upstream = endpoint.provider === "sponsored" ? "Sponsored Meta" : endpoint.provider === "meta" ? "Your Meta API key" : endpoint.provider;
  return (
    <div className="space-y-5 rounded-xl border border-line bg-surface p-4 sm:p-5" data-testid="first-run">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 space-y-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
            {endpoint.name}
            <StateBadge state={state} />
          </p>
          <p className="text-xs text-muted">
            {upstream} · {endpoint.model ? <>model {mono(endpoint.model)}</> : "your client picks the model"} · policy version {endpoint.policy_version}
          </p>
        </div>
        <div className="flex min-w-0 max-w-full items-center gap-2">
          <code className="min-w-0 truncate font-mono text-xs text-ink" title={url}>
            {url}
          </code>
          <CopyButton text={url} label="Copy the endpoint base URL" />
        </div>
      </div>
      {state === "needs_key" ? (
        isDefault && endpoint.provider === "sponsored" ? (
          <MetaKeyStep call={call} onAdded={onChanged} />
        ) : (
          <Notice tone="warn" title="This endpoint can't answer yet">
            Sponsored inference is unavailable. Edit the endpoint in <a className="underline underline-offset-4" href="#projects">Projects</a> to use your own provider key.
          </Notice>
        )
      ) : state === "disabled" ? (
        <Notice tone="warn">This endpoint is disabled. Re-enable it in Projects to connect a client.</Notice>
      ) : (
        <ol className="space-y-6">
          <Step n={1} title="Copy your guard key">
            <KeyStep call={call} endpoint={endpoint} projectId={projectId} onKey={setKey} />
          </Step>
          <Step n={2} title="Paste one block into your tool">
            <SnippetStep endpointId={endpoint.id} guardKey={key?.key ?? null} />
          </Step>
          <Step n={3} title="Send a test request">
            <TestStep endpointId={endpoint.id} />
          </Step>
        </ol>
      )}
    </div>
  );
}

function StateBadge({ state }: { state: FirstRunState }) {
  const [tone, label] =
    state === "ready" ? ["border-guard/40 bg-guard-soft text-guard-ink", "Ready"] : state === "needs_key" ? ["border-warn/40 bg-warn-soft text-warn", "Needs a key"] : ["border-line bg-surface-2 text-muted", "Disabled"];
  return <span className={["rounded-full border px-2 py-px text-2xs font-medium", tone].join(" ")}>{label}</span>;
}

/** Sponsored inference is off: exactly one field, the owner's own Meta key (sent once, kept only by the guard). */
function MetaKeyStep({ call, onAdded }: { call: Requester; onAdded: () => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const key = value.trim();
    if (!key) return setError("Paste your Meta API key.");
    setBusy(true);
    setError("");
    try {
      await addMetaKey(call, key);
      setValue("");
      onAdded();
    } catch (err) {
      setError(recovery(err).startsWith("The request was refused") ? "That key could not be saved. Paste the whole key, without spaces or quotes." : recovery(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3" aria-labelledby="meta-key-title">
      <div>
        <h3 id="meta-key-title" className="text-sm font-medium text-ink">
          Add your Meta API key
        </h3>
        <p className="mt-0.5 text-sm text-pretty text-muted">
          Sponsored inference isn&apos;t available on this service yet, so your endpoint calls the Meta Model API with your own key. pii-guard sends it only to{" "}
          {mono("api.meta.ai")}, with masked text, and never falls back to another model.
        </p>
      </div>
      <Field
        label="Meta API key"
        error={error || undefined}
        hint={
          <>
            No key yet?{" "}
            <a href={META_KEY_URL} target="_blank" rel="noreferrer" className="text-ink underline underline-offset-2">
              Get one at dev.meta.ai ↗
            </a>
            . The key is encrypted in your project configuration; this page never stores it.
          </>
        }
        className="sm:max-w-md"
      >
        <Input type="password" autoComplete="off" spellCheck={false} value={value} onChange={(e) => setValue(e.target.value)} disabled={busy} />
      </Field>
      <Button type="submit" variant="primary" busy={busy}>
        {busy ? "Saving…" : "Save key and continue"}
      </Button>
    </form>
  );
}

function KeyStep({ call, endpoint, projectId, onKey }: { call: Requester; endpoint: Endpoint; projectId: string; onKey: (key: IssuedKey | null) => void }) {
  const [key, setKeyState] = useState<IssuedKey | null>(() => getShownKey(endpoint.id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const setKey = (next: IssuedKey | null) => {
    setKeyState(next);
    onKey(next);
  };
  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const issued = await call<IssuedKey>(`${projectPath(projectId || endpoint.project_id)}/endpoints/${encodeURIComponent(endpoint.id)}/keys`, { name: "Console key" });
      rememberKey(endpoint.id, issued);
      setKey(issued);
    } catch (e) {
      setError(recovery(e));
    } finally {
      setBusy(false);
    }
  };
  if (key) {
    return (
      <div className="space-y-2 rounded-lg border border-warn/40 bg-warn-soft p-3 sm:p-4" role="status">
        <p className="text-sm font-medium text-warn">Copy your guard key now. It is shown only once.</p>
        <CodeBlock text={`export ${ENDPOINT_KEY_ENV}=${key.key}`} label="Copy the export line with your guard key" />
        <p className="text-xs text-pretty text-muted">
          The blocks below already contain it. pii-guard keeps only a hash, so after you leave or reload this page it can&apos;t be shown again: store it now (for example in a
          password manager). It works only for this endpoint; revoke it in Projects.
        </p>
        <div className="flex flex-wrap gap-2">
          <CopyButton text={key.key} label="Copy the guard key only" />
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              forgetShownKey();
              setKey(null);
            }}
          >
            I&apos;ve stored it
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-pretty text-muted">
        Your guard key was shown once, when it was created. Use the key you stored, as {mono(`$${ENDPOINT_KEY_ENV}`)}, or create a new one in one click and the blocks below fill it in. Old keys keep working until you revoke them in{" "}
        <a className="text-ink underline underline-offset-4" href="#projects">
          Projects
        </a>
        .
      </p>
      {error && <p className="text-sm text-danger" role="alert">{error}</p>}
      <Button busy={busy} onClick={() => void create()}>
        {busy ? "Creating…" : "Create a new guard key"}
      </Button>
    </div>
  );
}

/** The tabs in the order a first-time developer looks for them; the server's blocks fill them. */
const ORDER = ["muse-code", "codex", "pi", "python", "curl", "opencode"] as const;
const LABEL: Record<string, string> = { python: "OpenAI SDK" };

function SnippetStep({ endpointId, guardKey }: { endpointId: string; guardKey: string | null }) {
  const [result, setResult] = useState<{ state: "loading" } | { state: "failed" } | { state: "ok"; snippets: Snippets }>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetchSnippets({ endpoint: endpointId }, undefined, "", controller.signal).then((r) => {
      if (!controller.signal.aborted) setResult(r.state === "ok" ? { state: "ok", snippets: r.snippets } : { state: "failed" });
    });
    return () => controller.abort();
  }, [endpointId, attempt]);
  const tools: ToolSnippet[] = result.state === "ok" ? ORDER.map((id) => result.snippets.tools.find((t) => t.id === id)).filter((t): t is ToolSnippet => Boolean(t)) : [];
  const tabs = tools.length ? tools.map((t) => ({ id: t.id, label: LABEL[t.id] ?? t.label })) : ORDER.map((id) => ({ id, label: LABEL[id] ?? TOOLS.find((t) => t.id === id)?.label ?? id }));
  const [tool, setTool] = useState<string>(() => readPref("first-run-tool") ?? "codex");
  const chosen = tools.find((t) => t.id === tool) ?? tools.find((t) => t.supported) ?? null;
  const pick = (id: string) => {
    setTool(id);
    writePref("first-run-tool", id);
  };
  const shown = chosen?.id ?? tool;
  return (
    <div className="space-y-3">
      <ToolTabs tabs={tabs} tool={shown} onTool={pick} />
      <div id={`first-run-panel-${shown}`} role="tabpanel" aria-labelledby={`first-run-tab-${shown}`} className="space-y-2">
        {result.state === "loading" ? (
          <p role="status" className="text-sm text-muted">
            Loading the blocks for this endpoint…
          </p>
        ) : result.state === "failed" || !chosen ? (
          <Notice tone="danger" action={<Button size="sm" onClick={() => setAttempt((n) => n + 1)}>Retry</Button>}>
            The blocks for this endpoint could not be loaded.
          </Notice>
        ) : !chosen.supported ? (
          <div role="note" className="space-y-1 text-sm">
            <p className="font-medium text-ink">{LABEL[chosen.id] ?? chosen.label} can&apos;t use an endpoint URL yet.</p>
            <p className="text-pretty text-muted">{chosen.note}</p>
            <p className="text-muted">Codex, pi, the OpenAI SDK and cURL work with this endpoint today.</p>
          </div>
        ) : (
          <>
            <CodeBlock text={withKey(chosen, guardKey)} label={`Copy the ${LABEL[chosen.id] ?? chosen.label} block`} />
            <p className="text-xs text-pretty text-muted">
              {guardKey ? "Your guard key is filled in: paste it as is. " : <>Reads your guard key from {mono(`$${ENDPOINT_KEY_ENV}`)}. </>}
              {chosen.note}
              {chosen.tested_version && <> Tested end to end with {chosen.label} {chosen.tested_version}.</>}{" "}
              {chosen.docs && (
                <a href={chosen.docs} target="_blank" rel="noreferrer" className="text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink">
                  Docs ↗
                </a>
              )}
            </p>
            {(chosen.more ?? []).map((m) => (
              <div key={m.title} className="space-y-1.5">
                <p className="text-xs font-medium text-ink">{m.title}</p>
                <CodeBlock text={m.code} label={`Copy the ${chosen.label} ${m.title} block`} />
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

function ToolTabs({ tabs, tool, onTool }: { tabs: { id: string; label: string }[]; tool: string; onTool: (t: string) => void }) {
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = tabs.findIndex((t) => t.id === tool);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]!;
    onTool(next.id);
    document.getElementById(`first-run-tab-${next.id}`)?.focus();
  };
  return (
    <div role="tablist" aria-label="Your tool" className="-mx-1 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => {
        const selected = t.id === tool;
        return (
          <button
            key={t.id}
            id={`first-run-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`first-run-panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onTool(t.id)}
            onKeyDown={onKey}
            className={[
              "relative shrink-0 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition-colors pointer-coarse:min-h-11",
              "after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-full",
              selected ? "text-ink after:bg-ink" : "text-muted after:bg-transparent hover:text-ink",
            ].join(" ")}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

function TestStep({ endpointId }: { endpointId: string }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TestRoundTrip | null>(null);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const resultId = useId();
  useEffect(() => () => controller.current?.abort(), []);
  const run = async () => {
    const abort = new AbortController();
    controller.current = abort;
    const timeout = setTimeout(() => abort.abort(), 180_000);
    setRunning(true);
    setError("");
    setResult(null);
    try {
      setResult(await sendTestRequest(endpointId, undefined, abort.signal));
    } catch (e) {
      if (!abort.signal.aborted || e instanceof Error) setError(testRecovery(e));
    } finally {
      clearTimeout(timeout);
      setRunning(false);
    }
  };
  return (
    <div className="space-y-3">
      <p className="text-sm text-pretty text-muted">
        One fictional prompt through this endpoint, as your client would send it. It uses one request from your daily allowance and shows what the model saw.
      </p>
      <Button variant="primary" busy={running} onClick={() => void run()} aria-describedby={result ? resultId : undefined}>
        {running ? "Sending…" : result ? "Send again" : "Send a test request"}
      </Button>
      <div aria-live="polite">
        {running && (
          <p role="status" className="text-sm text-muted">
            Masking, then waiting for the model. Reasoning models can take up to a minute.
          </p>
        )}
        {error && (
          <Notice tone="danger" className="mt-1">
            {error}
          </Notice>
        )}
        {result && (
          <div id={resultId} className="space-y-3">
            <p role="status" className="text-sm font-medium text-guard-ink">
              ✓ Round trip complete{result.maskedCount !== null ? `: ${result.maskedCount} ${result.maskedCount === 1 ? "value" : "values"} masked before the model saw it` : ""} ·{" "}
              {(result.ms / 1000).toFixed(1)} s
            </p>
            <div className="grid gap-3 lg:grid-cols-3">
              <Pane title="You sent" text={result.original} />
              <Pane title="The model saw" text={result.masked || "Not reported by the server."} tone="model" />
              <Pane title="You got back" text={result.restored || "The model returned an empty answer. Try again."} tone="restored" />
            </div>
            {result.maskedAnswer && (
              <details className="text-xs text-muted">
                <summary className="cursor-pointer">The model&apos;s own answer, with placeholders</summary>
                <p className="mt-2 font-mono whitespace-pre-wrap text-ink">{result.maskedAnswer}</p>
              </details>
            )}
            <p className="text-xs text-muted">
              Detection can miss values: check the masked request. Every call also shows up in <a className="text-ink underline underline-offset-4" href="#logs">Logs</a>.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function Pane({ title, text, tone }: { title: string; text: string; tone?: "model" | "restored" }) {
  return (
    <div className={["min-w-0 rounded-lg border p-3", tone === "model" ? "border-line-strong bg-surface-2" : tone === "restored" ? "border-guard/40 bg-guard-soft" : "border-line bg-surface"].join(" ")}>
      <p className="text-2xs font-medium tracking-wide text-muted uppercase">{title}</p>
      <p className="mt-1.5 text-sm break-words whitespace-pre-wrap text-ink">{text}</p>
    </div>
  );
}

const mono = (s: string) => <code className="font-mono text-xs">{s}</code>;

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 gap-y-2">
      <span aria-hidden="true" className="grid size-7 place-items-center rounded-full border border-line font-mono text-xs text-muted">
        {n}
      </span>
      <div className="min-w-0 space-y-2">
        <h3 className="pt-1 text-sm font-medium text-ink">
          <span className="sr-only">Step {n}: </span>
          {title}
        </h3>
        {children}
      </div>
    </li>
  );
}

/** No endpoint (an older server without first run): what the client setup will look like. */
function NoEndpointPreview() {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 sm:p-5" data-testid="client-setup-preview">
      <div role="tablist" aria-label="Your tool (available once you have an endpoint)" className="-mx-1 flex gap-1 overflow-x-auto">
        {TOOLS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={false} disabled className="px-3 py-2 text-sm whitespace-nowrap text-faint disabled:cursor-not-allowed">
            {t.label}
          </button>
        ))}
      </div>
      <pre aria-label="Example client settings" className="mt-3 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-ui whitespace-pre text-muted sm:p-4">
        {`OPENAI_BASE_URL=${globalThis.location?.origin ?? ""}/e/<your-endpoint>/v1\nOPENAI_API_KEY=<your endpoint key>`}
      </pre>
      <p className="mt-3 text-sm text-muted">Each endpoint has its own base URL and keys. Create an endpoint in Projects, then come back here for the blocks for your tool.</p>
      <ButtonLink variant="primary" href="#projects" className="mt-4">
        Create an endpoint <span aria-hidden="true">→</span>
      </ButtonLink>
    </div>
  );
}
