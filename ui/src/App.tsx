import { Workspace } from "./projects/Workspace";
import { getSelectedProject, setSelectedProject, useSelectedScope } from "./projects/selection";
import { HostedApp } from "./hosted/HostedApp";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createHttpChat, createMockChat, type ChatClient } from "./api/chat";
import { engineReason } from "./api/engine";
import { createHttpClient, type HttpGuardClient } from "./api/http";
import { MOCK_SESSION_PREFIX, createMockClient } from "./api/mock";
import type { GuardClient } from "./api/types";
import type { ServerStatus } from "./api/status";
import { Sidebar } from "./components/Sidebar";
import { DEFAULT_SAMPLE, SAMPLES, sampleBehind, type Sample } from "./content/samples";
import type { BenchmarkLoader } from "./api/benchmarks";
import { useEngine } from "./hooks/useEngine";
import { useServerStatus, type StatusLoader } from "./hooks/useServerStatus";
import { useTheme } from "./hooks/useTheme";
import { useTraffic } from "./hooks/useTraffic";
import { initialAnswer, runGuard, toRunError, type RunError, type RunResult } from "./lib/run";
import { PLAYGROUND_TABS, SECTIONS, hashOf, parseHash, routeFromLocation, sameRoute, type PlaygroundTab, type Route, type Section } from "./lib/routes";
import { Playground } from "./screens/Playground";
import { Benchmarks } from "./screens/Benchmarks";
import { Connect } from "./screens/Connect";
import { Images } from "./screens/Images";
import { Overview } from "./screens/Overview";
import { Policy } from "./screens/Policy";
import { RoundTrip } from "./screens/RoundTrip";
import { Chat, type ChatDraft } from "./screens/Chat";
import { Logs, type TrafficProps } from "./screens/Traffic";
import { Vault } from "./screens/Vault";
import type { VaultClient } from "./api/vault";
import type { KnownRow } from "./lib/knownRows";
import { knownSignatureOf, type KnownSession } from "./lib/run";
import { newKnownRow } from "./lib/knownRows";

export interface AppProps {
  api?: HttpGuardClient;
  mock?: GuardClient;
  envMode?: string;
  /** Loads a sample image's bytes (Images screen); injectable for tests. */
  loadImage?: (src: string) => Promise<Blob>;
  /** Loads the benchmark index (Evaluation screen); injectable for tests. */
  loadBenchmarks?: BenchmarkLoader;
  /** Gateway chat clients (Chat screen); injectable for tests. */
  chat?: { api?: ChatClient; mock?: ChatClient };
  /** Traffic log options (Overview and Logs); injectable for tests. */
  traffic?: Omit<TrafficProps, "forceFixture">;
  /** Loads `/v1/status` (Overview, Connect, Policy); injectable for tests. */
  loadStatus?: StatusLoader;
  /** The vault inspector's client (Vault screen); injectable for tests. */
  vault?: VaultClient;
}

/** Hosted deployment is an explicit build choice; the local console remains the default. */
export function App(props: AppProps) {
  const scope = useSelectedScope();
  return import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? <HostedApp /> : <LocalApp key={scope} {...props} />;
}

/** A user's navigation adds a history entry (Back returns); a redirect replaces the current one. */
function writeHash(route: Route, how: "push" | "replace") {
  try {
    if (globalThis.location.hash === hashOf(route)) return;
    if (how === "push") history.pushState(null, "", hashOf(route));
    else history.replaceState(null, "", hashOf(route));
  } catch {
    // sandboxed frames may refuse; the section still opens
  }
}

function LocalApp({ api, mock, envMode = import.meta.env.VITE_PII_GUARD_MODE, loadImage, loadBenchmarks, chat, traffic, loadStatus, vault }: AppProps) {
  const apiClient = useMemo(() => api ?? createHttpClient(), [api]);
  const mockClient = useMemo(() => mock ?? createMockClient({ latencyMs: 220 }), [mock]);
  const engine = useEngine(apiClient, mockClient, envMode);
  const apiChat = useMemo(() => chat?.api ?? createHttpChat(), [chat?.api]);
  const mockChat = useMemo(() => chat?.mock ?? createMockChat(mockClient), [chat?.mock, mockClient]);
  const [chatDraft, setChatDraft] = useState<ChatDraft | null>(null);
  const [theme, setTheme] = useTheme();
  const { result: status } = useServerStatus(engine.engine === "mock" ? "offline" : engine.state.status.state, loadStatus);
  const server = status.state === "ok" ? status.status : null;

  const [route, setRouteState] = useState<Route>(routeFromLocation);
  // Evaluation loads its data lazily on first open, then stays mounted (filters survive).
  const [evaluationOpened, setEvaluationOpened] = useState(() => route.section === "evaluation");
  const [textView, setTextView] = useState<"mask" | "roundtrip">("mask");
  const navigate = useCallback((next: Route, how: "push" | "replace" | "none" = "push") => {
    if (next.section === "evaluation") setEvaluationOpened(true);
    setRouteState((prev) => (sameRoute(prev, next) ? prev : next));
    if (how !== "none") writeHash(next, how);
  }, []);
  const openSection = useCallback((section: Section) => navigate({ section, tab: section === "playground" ? route.tab : "text" }), [navigate, route.tab]);
  const openTab = useCallback((tab: PlaygroundTab) => navigate({ section: "playground", tab }), [navigate]);

  useEffect(() => {
    // An old tab link (#traffic, #benchmarks …) lands on its new place, with the URL rewritten.
    const initial = parseHash(globalThis.location?.hash ?? "");
    if (initial?.redirect) writeHash(initial.route, "replace");
    // Only route hashes switch sections (the skip link's #main must not). Back and forward
    // fire popstate, a typed or linked hash fires hashchange: both land here.
    const onHash = () => {
      const parsed = parseHash(globalThis.location.hash);
      if (parsed) navigate(parsed.route, parsed.redirect ? "replace" : "none");
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, [navigate]);

  // The traffic log feeds Overview, Logs and Connect; it connects when one first opens.
  const followsTraffic = route.section === "overview" || route.section === "logs" || route.section === "connect";
  const [trafficOpened, setTrafficOpened] = useState(() => followsTraffic);
  if (!trafficOpened && followsTraffic) setTrafficOpened(true);
  const forceFixture = engine.state.preference === "mock";
  const trafficHandle = useTraffic({ forceFixture, connect: trafficOpened ? traffic?.connect : idleConnect, fixtureIntervalMs: traffic?.fixtureIntervalMs });
  const [logFocus, setLogFocus] = useState<{ id: string; nonce: number } | null>(null);
  const [vaultFocus, setVaultFocus] = useState<{ ref: string; nonce: number } | null>(null);

  const [sampleId, setSampleId] = useState<string | null>(DEFAULT_SAMPLE.id);
  const [text, setText] = useState(DEFAULT_SAMPLE.text);
  const [language, setLanguage] = useState<"hu" | "en">(DEFAULT_SAMPLE.language);
  const [known, setKnown] = useState<KnownRow[]>([]);
  const knownSession = useRef<KnownSession | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [answer, setAnswer] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<RunError | null>(null);
  const runId = useRef(0);

  const run = useCallback(async () => {
    const id = ++runId.current;
    setRunning(true);
    setError(null);
    try {
      const values = known.filter((k) => k.value.trim() !== "").map((k) => ({ value: k.value, entity_type: k.entity_type }));
      if (knownSession.current && knownSession.current.engine !== engine.engine) knownSession.current = null;
      const r = await runGuard(engine.client, text, sampleId, {
        language,
        known: values,
        knownSession: knownSession.current,
        onKnownSession: (s) => (knownSession.current = s),
      });
      if (id !== runId.current) return;
      setResult(r);
      setAnswer(initialAnswer(r, SAMPLES.find((s) => s.id === r.sampleId)));
    } catch (err) {
      if (id !== runId.current) return;
      // Fail closed: drop any previous masked output so nothing stale is shown as current.
      setResult(null);
      const e = toRunError(err);
      if (e.code === "not_found") knownSession.current = null;
      setError(e);
    } finally {
      if (id === runId.current) setRunning(false);
    }
  }, [engine.client, engine.engine, text, sampleId, language, known]);

  const pickSample = (s: Sample) => {
    setSampleId(s.id);
    setText(s.text);
    setLanguage(s.language);
    setError(null);
  };

  const editText = (t: string) => {
    setText(t);
    const match = SAMPLES.find((s) => s.text === t);
    setSampleId(match?.id ?? null);
  };

  const chatClient = engine.engine === "api" ? apiChat : mockChat;
  // Nobody chose the demo engine and the API does not answer: the notice turns red.
  const apiDown = engine.engine === "mock" && engine.state.preference !== "mock" && engine.state.status.state === "offline";
  const section = route.section;
  const tab = route.tab;

  return (
    <div className="min-h-dvh bg-canvas text-ink lg:grid lg:grid-cols-[13.5rem_minmax(0,1fr)]">
      <Sidebar
        route={route}
        onSection={openSection}
        engineState={engine.state}
        engine={engine.engine}
        onPreference={engine.setPreference}
        onRecheck={engine.recheck}
        theme={theme}
        onTheme={setTheme}
        statusDetail={server ? statusDetailOf(server) : null}
      />

      <div className="min-w-0">
        <PageHeader route={route} />
        {engine.engine === "mock" && (
          <div role="status" className={apiDown ? "border-b border-danger/30 bg-danger-soft" : "border-b border-warn/30 bg-warn-soft"}>
            <p className="mx-auto max-w-[1280px] px-4 py-2 text-xs text-ink sm:px-6 sm:text-sm">
              {apiDown ? <strong className="font-medium text-danger">API not reachable.</strong> : <strong className="font-medium text-warn">Demo mode.</strong>} {engineReason(engine.state)}.{" "}
              {section === "playground" && tab === "images"
                ? "Images replay regions recorded from a real SAM 3.1 run on the built-in samples; uploads need the API."
                : section === "evaluation"
                  ? "Benchmarks are bundled with this page, so they are the same with or without the API."
                  : section === "vault"
                    ? "The vault lives in the pii-guard server; demo mode has none to inspect."
                    : section === "overview" || section === "logs"
                    ? "Overview and Logs replay calls recorded from the demo stack (masked level, no original values)."
                    : section === "connect" || section === "policy"
                      ? "The server can't be asked for its configuration, so this shows the defaults."
                      : "Detection runs in your browser with a small built-in rule set, so results are illustrative."}{" "}
              {engine.state.status.state === "online" ? (
                engine.state.preference === "mock" ? (
                  <>Switch the engine to Auto or Live API for the real pipeline.</>
                ) : (
                  <>The real pipeline takes over as soon as the API serves the /v1 routes.</>
                )
              ) : (
                <>
                  Start it with <code className="rounded-sm bg-surface px-1 font-mono text-xs">pii-guard up</code> for the real pipeline.
                </>
              )}
            </p>
          </div>
        )}

        <main id="main" tabIndex={-1} className="mx-auto max-w-[1280px] px-4 py-6 focus:outline-none sm:px-6 sm:py-8">
          <section id="section-overview" aria-label="Overview" hidden={section !== "overview"}>
            {trafficOpened && (
              <Overview
                t={trafficHandle}
                status={status}
                forced={forceFixture}
                sendDemo={traffic?.sendDemo}
                onOpenCall={(id) => {
                  setLogFocus({ id, nonce: Date.now() });
                  openSection("logs");
                }}
              />
            )}
          </section>

          <section id="section-playground" aria-label="Playground" hidden={section !== "playground"} className="space-y-6">
            <PlaygroundTabs tab={tab} onTab={openTab} />
            <div id="panel-text" role="tabpanel" aria-labelledby="tab-text" hidden={tab !== "text"} className="space-y-6">
              <div role="group" aria-label="Text view" className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
                {(
                  [
                    ["mask", "Mask a document"],
                    ["roundtrip", "Round trip"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={textView === id}
                    onClick={() => setTextView(id)}
                    className={["rounded-md px-3 py-1.5 font-medium", textView === id ? "bg-primary text-on-primary" : "text-muted hover:text-ink"].join(" ")}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div hidden={textView !== "mask"}>
                <Playground
                  text={text}
                  onText={editText}
                  sampleId={sampleId}
                  onSample={pickSample}
                  result={result}
                  running={running}
                  error={error}
                  onRun={() => void run()}
                  language={language}
                  onLanguage={setLanguage}
                  known={known}
                  onKnown={setKnown}
                  knownSignature={knownSignatureOf(known)}
                  onTryKnown={() => {
                    setKnown((rows) => [...rows, newKnownRow("Gyakorló Tihamér")]);
                    editText(
                      text.replace(/\s*$/, "") +
                        (language === "hu" ? "\n\nA lakás kulcsait Gyakorló Tihamérnak kell átadni." : "\n\nPlease hand the keys to Gyakorló Tihamér's assistant."),
                    );
                  }}
                  onContinue={() => {
                    const sample = sampleBehind(text);
                    // The same vault session, so Chat shows the same placeholders (LAB-1261);
                    // only when Chat runs on the engine that made it.
                    const session = result?.mask.session_id ?? null;
                    const sameEngine = session !== null && session.startsWith(MOCK_SESSION_PREFIX) === (chatClient.kind === "mock");
                    setChatDraft({ text: sample ? `${sample.task}\n\n${text}` : text, language, nonce: Date.now(), sessionId: sameEngine ? session : null });
                    openTab("chat");
                    window.scrollTo?.({ top: 0 });
                  }}
                />
              </div>
              {textView === "roundtrip" && (
                <RoundTrip
                  key={result?.mask.session_id ?? "none"}
                  client={engine.client}
                  result={result}
                  answer={answer}
                  onAnswer={setAnswer}
                  running={running}
                  onRun={() => void run()}
                />
              )}
            </div>
            <div id="panel-chat" role="tabpanel" aria-labelledby="tab-chat" hidden={tab !== "chat"}>
              <Chat client={chatClient} live={engine.state.status.state === "online"} draft={chatDraft} ner={server ? server.ner.available : null} mockUpstream={server?.upstream.mock ?? false} />
            </div>
            <div id="panel-images" role="tabpanel" aria-labelledby="tab-images" hidden={tab !== "images"}>
              <Images client={engine.client} engineState={engine.state} loadImage={loadImage} replayRecorded={mockClient.maskImage?.bind(mockClient)} serverImages={server?.images ?? null} />
            </div>
          </section>

          <section id="section-logs" aria-label="Logs" hidden={section !== "logs"}>
            {trafficOpened && (
              <Logs
                t={trafficHandle}
                forceFixture={forceFixture}
                sendDemo={traffic?.sendDemo}
                pageHost={traffic?.pageHost}
                mockUpstream={server?.upstream.mock ?? false}
                focus={logFocus}
                onOpenSession={(ref) => {
                  setVaultFocus({ ref, nonce: Date.now() });
                  openSection("vault");
                }}
              />
            )}
          </section>
          <section id="section-vault" aria-label="Vault" hidden={section !== "vault"}>
            <Vault status={status} live={engine.engine === "api"} active={section === "vault"} client={vault} focus={vaultFocus} />
          </section>
          <section id="section-connect" aria-label="Connect" hidden={section !== "connect"}>
            <Connect
              status={status}
              traffic={trafficOpened ? trafficHandle : undefined}
              onOpenLog={(id) => {
                setLogFocus({ id, nonce: Date.now() });
                openSection("logs");
              }}
              onOpenSession={(ref) => {
                setVaultFocus({ ref, nonce: Date.now() });
                openSection("vault");
              }}
            />
          </section>
          <section id="section-projects" aria-label="Projects" hidden={section !== "projects"}>
            {section === "projects" && <Workspace onProject={selectProject} projectId={getCurrentProject()} />}
          </section>
          <section id="section-policy" aria-label="Policy" hidden={section !== "policy"}>
            <Policy status={status} />
          </section>
          <section id="section-evaluation" aria-label="Evaluation" hidden={section !== "evaluation"}>
            {evaluationOpened && <Benchmarks load={loadBenchmarks} />}
          </section>
        </main>

        <footer className="mx-auto max-w-[1280px] px-4 pb-10 text-xs text-faint sm:px-6">
          All sample data is fictional. This page talks only to pii-guard, never to a model provider: image segmentation and the Chat model run behind the pii-guard server. The Chat
          model is real only when the server has an upstream; the round trip and demo mode use a simulated answer.
        </footer>
      </div>
    </div>
  );
}

/** The status tooltip's detail: "fast mode · rules+ner". */
function statusDetailOf(s: ServerStatus): string {
  const mode = s.gateway.modes[s.gateway.default_mode as keyof ServerStatus["gateway"]["modes"]];
  return [`${s.gateway.default_mode} mode`, mode?.detectors.join("+")].filter(Boolean).join(" · ");
}

/** The bar above every section: where you are, over the accent hairline. Below 1024 px the
 *  menu's top bar names the section, so only the hairline shows. */
function PageHeader({ route }: { route: Route }) {
  const section = SECTIONS.find((s) => s.id === route.section)!;
  const tab = route.section === "playground" ? PLAYGROUND_TABS.find((t) => t.id === route.tab) : undefined;
  return (
    <header>
      <p className="hidden h-12 items-center gap-2 px-6 text-base text-ink lg:flex">
        <span>{section.label}</span>
        {tab && (
          <>
            <span aria-hidden="true" className="text-faint">
              /
            </span>
            <span className="text-muted">{tab.label}</span>
          </>
        )}
      </p>
      <div aria-hidden="true" className="header-hairline" />
    </header>
  );
}

/** Before Overview or Logs first opens, the traffic hook holds no connection. */
const idleConnect = () => ({ close() {} });

function PlaygroundTabs({ tab, onTab }: { tab: PlaygroundTab; onTab: (t: PlaygroundTab) => void }) {
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = PLAYGROUND_TABS.findIndex((t) => t.id === tab);
    const next = PLAYGROUND_TABS[(i + (e.key === "ArrowRight" ? 1 : PLAYGROUND_TABS.length - 1)) % PLAYGROUND_TABS.length]!;
    onTab(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };
  return (
    <div role="tablist" aria-label="Playground" className="flex gap-1 border-b border-line">
      {PLAYGROUND_TABS.map((t) => {
        const selected = t.id === tab;
        return (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onTab(t.id)}
            onKeyDown={onKey}
            className={[
              "relative px-3 py-2.5 text-sm font-medium whitespace-nowrap transition-colors",
              "after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-full",
              selected ? "text-ink after:bg-ink" : "text-muted hover:text-ink after:bg-transparent",
            ].join(" ")}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

const selectProject = (project: { id: string }) => setSelectedProject(project.id);
const getCurrentProject = () => getSelectedProject() ?? undefined;
