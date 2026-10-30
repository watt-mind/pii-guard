import type { ChatDraft } from "./screens/Chat";
import type { TrafficProps } from "./screens/Traffic";
import { useOwnerRevision } from "./api/localOwner";
import { getSelectedEndpoint, getSelectedProject, setSelectedProject, useSelectedScope } from "./projects/selection";
import { AccountSummary, ProviderConnections } from "./hosted/AccountPanels";
import { useSetupPending } from "./hosted/setup";
import { ClientSetup } from "./hosted/ClientSetup";
import { loadFirstRun } from "./hosted/firstRun";
import { HostedSessionContext, SITE_HASHES, hostedChatFetch, useHostedSession, type HostedSession } from "./hosted/session";
import { ApiReference } from "./hosted/ApiReference";
import { isApiHash } from "./hosted/apiConfig";
import { chatModesOf, offersDemoTraffic, offersSection, offersTab, useCapabilities, type Capabilities } from "./lib/capabilities";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createHttpChat, createMockChat, type ChatClient } from "./api/chat";
import { endpointSnippets } from "./api/connect";
import { engineReason } from "./api/engine";
import { createHttpClient, type HttpGuardClient } from "./api/http";
import { MOCK_SESSION_PREFIX, createMockClient } from "./api/mock";
import type { GuardClient } from "./api/types";
import type { ServerStatus } from "./api/status";
import { PageLoadBoundary } from "./components/PageLoadBoundary";
import { Sidebar } from "./components/Sidebar";
import { PageHeader, SegmentedControl } from "./components/ui";
import { ProfileMenu } from "./components/ProfileMenu";
import { ProjectSwitcher } from "./projects/ProjectSwitcher";
import { DEFAULT_SAMPLE, SAMPLES, sampleBehind, type Sample } from "./content/samples";
import type { BenchmarkLoader } from "./api/benchmarks";
import { useEngine } from "./hooks/useEngine";
import { useServerStatus, type StatusLoader } from "./hooks/useServerStatus";
import { useTheme } from "./hooks/useTheme";
import { useTraffic } from "./hooks/useTraffic";
import { initialAnswer, runGuard, toRunError, type RunError, type RunResult } from "./lib/run";
import { DEFAULT_ROUTE, PLAYGROUND_TABS, SECTIONS, hashOf, parseHash, routeFromLocation, sameRoute, type EvaluationParams, type PlaygroundTab, type Route, type Section } from "./lib/routes";
import type { VaultClient } from "./api/vault";
import type { KnownRow } from "./lib/knownRows";
import { knownSignatureOf, type KnownSession } from "./lib/run";
import { newKnownRow } from "./lib/knownRows";
import { Overview } from "./screens/Overview";
import { Logs } from "./screens/Traffic";
// Keep HostedApp and its recorded demo / agent replay fixtures out of the local console entry.
const HostedApp = lazy(() => import("./hosted/HostedApp").then((module) => ({ default: module.HostedApp })));
// Keep Evaluation and its charts out of the console entry: first-visit mounting alone
// defers its data requests, but an eager import still downloads that code on every route.
const Benchmarks = lazy(() => import("./screens/Benchmarks").then((module) => ({ default: module.Benchmarks })));
const Workspace = lazy(() => import("./projects/Workspace").then((module) => ({ default: module.Workspace })));
const Playground = lazy(() => import("./screens/Playground").then((module) => ({ default: module.Playground })));
const Connect = lazy(() => import("./screens/Connect").then((module) => ({ default: module.Connect })));
const Images = lazy(() => import("./screens/Images").then((module) => ({ default: module.Images })));
const OwnerPolicy = lazy(() => import("./screens/Policy").then((module) => ({ default: module.OwnerPolicy })));
const Policy = lazy(() => import("./screens/Policy").then((module) => ({ default: module.Policy })));
const RoundTrip = lazy(() => import("./screens/RoundTrip").then((module) => ({ default: module.RoundTrip })));
const Chat = lazy(() => import("./screens/Chat").then((module) => ({ default: module.Chat })));
const Vault = lazy(() => import("./screens/Vault").then((module) => ({ default: module.Vault })));

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
  return import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? (
    <Suspense fallback={null}>
      <HostedApp console={(session) => <SignedInConsole session={session} {...props} />} />
    </Suspense>
  ) : (
    <LocalConsole {...props} />
  );
}

/** A signed-in hosted owner gets the same console; the server's capabilities decide its sections. */
export function SignedInConsole({ session, ...props }: AppProps & { session: HostedSession }) {
  const hostedChat = useMemo(() => createHttpChat({ fetch: hostedChatFetch }), []);
  useFirstRunLanding(session.call);
  return (
    <HostedSessionContext.Provider value={session}>
      <LocalConsole {...props} envMode={props.envMode ?? "api"} chat={{ ...props.chat, api: props.chat?.api ?? hostedChat }} />
    </HostedSessionContext.Provider>
  );
}

/**
 * First run (LAB-1455): straight after sign-in the server provisions the owner's default
 * endpoint and its first key. While that key is on this page (or the endpoint still needs the
 * owner's Meta key), sign-in lands on Connect, "Connect your client", instead of the Overview,
 * unless the owner has already moved elsewhere. A failed first run leaves the console as it is.
 */
function useFirstRunLanding(call: HostedSession["call"]) {
  useEffect(() => {
    let live = true;
    loadFirstRun(call).then(
      (first) => {
        const hash = globalThis.location?.hash ?? "";
        if (!live || !(first.key || first.state === "needs_key") || !(hash === "" || hash === "#" || hash === "#overview")) return;
        writeHash({ section: "connect", tab: "text" }, "replace");
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [call]);
}

function LocalConsole(props: AppProps) {
  const scope = useSelectedScope();
  const ownerRevision = useOwnerRevision();
  return <LocalApp key={`${scope}:${ownerRevision}`} {...props} />;
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
  const hosted = useHostedSession();
  const caps = useCapabilities(server);
  // A hosted owner's snippets are one endpoint's (the project menu's "Inspect activity & vault"); the
  // console remounts when it changes.
  const [snippetsEndpoint] = useState(getSelectedEndpoint);
  const hostedSnippets = useMemo(() => (caps.accounts && snippetsEndpoint ? endpointSnippets(snippetsEndpoint) : undefined), [caps.accounts, snippetsEndpoint]);

  const [requestedRoute, setRouteState] = useState<Route>(routeFromLocation);
  // A section or tab the server doesn't offer opens the Overview (or the first offered tab).
  const route = allowedRoute(requestedRoute, caps);
  // Mount each route on its first visit, then retain its drafts/results until scope changes.
  const routeKey = route.section === "playground" ? `playground/${route.tab}` : route.section;
  const [visited, setVisited] = useState(() => new Set([routeKey]));
  if (!visited.has(routeKey)) setVisited(new Set([...visited, routeKey]));
  const opened = (key: string) => key === routeKey || visited.has(key);
  const sectionOpened = (key: string) => key === route.section || [...visited].some((visitedKey) => visitedKey.split("/")[0] === key);
  const [textView, setTextView] = useState<"mask" | "roundtrip">("mask");
  // Hosted, #api shows the API reference in the console's main area (LAB-1626); any navigation leaves it.
  const [apiOpen, setApiOpen] = useState(() => hosted !== null && isApiHash(globalThis.location?.hash ?? ""));
  const navigate = useCallback((next: Route, how: "push" | "replace" | "none" = "push") => {
    setApiOpen(false);
    setRouteState((prev) => (sameRoute(prev, next) ? prev : next));
    if (how !== "none") writeHash(next, how);
  }, []);
  // The Evaluation screen's filters survive leaving the section: returning to it (sidebar,
  // Back) restores the same view instead of resetting to the defaults (LAB-1133).
  const lastEvaluation = useRef<EvaluationParams | null>(null);
  useEffect(() => {
    if (route.section === "evaluation" && route.evaluation) lastEvaluation.current = route.evaluation;
  }, [route]);
  const openSection = useCallback(
    (section: Section) =>
      navigate({
        section,
        tab: section === "playground" ? route.tab : "text",
        ...(section === "evaluation" && lastEvaluation.current ? { evaluation: lastEvaluation.current } : {}),
      }),
    [navigate, route.tab],
  );
  const openTab = useCallback((tab: PlaygroundTab) => navigate({ section: "playground", tab }), [navigate]);
  // The open Evaluation screen reports its filters so the URL stays shareable; off-section
  // nothing is reported, so a still-loading screen can't pull the user back (LAB-1133).
  const reportEvaluation = useCallback(
    (evaluation: EvaluationParams) => navigate({ section: "evaluation", tab: "text", evaluation }, "replace"),
    [navigate],
  );

  useEffect(() => {
    // An old tab link (#traffic, #benchmarks …) lands on its new place, with the URL rewritten.
    const initial = parseHash(globalThis.location?.hash ?? "");
    // Hosted, #api is the API reference inside the console (LAB-1626): not a section to rewrite.
    if (initial?.redirect && !(hosted && isApiHash(globalThis.location?.hash ?? ""))) writeHash(initial.route, "replace");
    // Only route hashes switch sections (the skip link's #main must not). Back and forward
    // fire popstate, a typed or linked hash fires hashchange: both land here.
    const onHash = () => {
      // The public page's anchors belong to the hosted page around the console.
      if (hosted && isApiHash(globalThis.location.hash)) return setApiOpen(true);
      if (hosted && SITE_HASHES.has(globalThis.location.hash)) return;
      const parsed = parseHash(globalThis.location.hash);
      if (parsed) navigate(parsed.route, parsed.redirect ? "replace" : "none");
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, [navigate, hosted]);

  // Rewrite the URL only once the server has said what it offers: until then a deep link to a
  // section the defaults leave out (hosted #playground/images) must survive (LAB-1448).
  const capsKnown = status.state !== "loading";
  useEffect(() => {
    if (capsKnown && route !== requestedRoute) writeHash(route, "replace");
  }, [capsKnown, route, requestedRoute]);

  // The traffic log feeds Overview, Logs and Connect; it connects when one first opens.
  const followsTraffic = route.section === "overview" || route.section === "logs" || route.section === "connect";
  const [trafficOpened, setTrafficOpened] = useState(() => followsTraffic);
  if (!trafficOpened && followsTraffic) setTrafficOpened(true);
  const forceFixture = engine.state.preference === "mock";
  const trafficHandle = useTraffic({ forceFixture, connect: trafficOpened ? traffic?.connect : idleConnect, fixtureIntervalMs: traffic?.fixtureIntervalMs });
  const [logFocus, setLogFocus] = useState<{ id: string; nonce: number } | null>(null);
  const [vaultFocus, setVaultFocus] = useState<{ ref: string; nonce: number } | null>(null);
  // A #vault/<ref> deep link opens that session once the section mounts (LAB-1333); the
  // nonce is derived from the ref, so a different deep link reopens the detail.
  const routeVaultRef = route.section === "vault" ? (route.ref ?? null) : null;
  const routeVaultNonce =
    routeVaultRef === null
      ? 0
      : [...routeVaultRef].reduce((n, c) => (n * 31 + c.charCodeAt(0)) | 0, 7);
  const vaultFocusProp =
    vaultFocus ?? (routeVaultRef !== null ? { ref: routeVaultRef, nonce: routeVaultNonce } : null);

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

  // First paint waits (briefly) until the engine and the traffic log have settled, so the
  // demo-mode notice and the recorded-traffic box don't push a painted page down (CLS, LAB-1448).
  const [settleTimedOut, setSettleTimedOut] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSettleTimedOut(true), SETTLE_CAP_MS);
    return () => clearTimeout(t);
  }, []);
  const setupPending = useSetupPending() && caps.accounts && route.section === "overview";
  // An unreachable traffic log switches to the recorded demo by itself: wait for that switch too.
  const trafficSettled = !trafficOpened || trafficHandle.source === "fixture" || (trafficHandle.status.state !== "connecting" && trafficHandle.status.state !== "offline");
  const settled = settleTimedOut || (engine.state.status.state !== "checking" && trafficSettled && !setupPending);

  // Overview's usage counters come from /v1/account: read it again each time Overview opens.
  const refreshAccount = hosted?.refresh;
  useEffect(() => {
    if (route.section === "overview") void refreshAccount?.();
  }, [route.section, refreshAccount]);

  // Hosted: the traffic log answered 401, so ask /v1/account whether the session ended; if it
  // did, the hosted shell swaps the console for the "Your session ended" panel (LAB-1519).
  const signedOut = trafficHandle.status.state === "denied" && trafficHandle.status.reason === "signed_out";
  useEffect(() => {
    if (signedOut) void refreshAccount?.();
  }, [signedOut, refreshAccount]);

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
        caps={caps}
        apiOpen={apiOpen}
      />

      <div className={["min-w-0", settled ? "" : "invisible"].join(" ")} data-settled={settled || undefined}>
        <HeaderBar route={route} caps={caps} apiOpen={apiOpen} projectsEnabled={caps.accounts || engine.engine === "api"} />
        {engine.engine === "mock" && (
          <div role="status" className={apiDown ? "border-b border-danger/30 bg-danger-soft" : "border-b border-warn/30 bg-warn-soft"}>
            <p className="mx-auto max-w-[1280px] px-4 py-2 text-xs text-ink sm:px-6 sm:text-sm">
              {apiDown ? <strong className="font-medium text-danger">API not reachable.</strong> : <strong className="font-medium text-warn">Demo mode.</strong>} {engineReason(engine.state)}.{" "}
              {section === "playground" && tab === "images"
                ? "Images replay regions recorded from a real SAM 3.1 run on the built-in samples; uploads need the API."
                : section === "evaluation"
                  ? "Benchmarks are bundled with this page, so they are the same with or without the API."
                  : section === "vault"
                    ? "The vault lives in the PII Guard server; demo mode has none to inspect."
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

        {/* The main landmark. On the API page the reference's own <main> (Scalar renders one) is
            the page's main instead: a nested main, or a role on it, fails axe (LAB-1640). A div
            with the role, so switching keeps the element and the screens' state. */}
        <div id="main" role={apiOpen ? undefined : "main"} tabIndex={-1} className="mx-auto min-h-dvh max-w-[1280px] px-4 py-6 focus:outline-none sm:px-6 sm:py-8">
          {apiOpen && <ApiReference embedded />}
          <div hidden={apiOpen} className="console-views">
          <section id="section-overview" aria-label="Overview" hidden={section !== "overview"}>
            {sectionOpened("overview") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading overview…</p>}>
            {trafficOpened && (
              <Overview
                t={trafficHandle}
                status={status}
                forced={forceFixture}
                sendDemo={traffic?.sendDemo}
                demoTraffic={offersDemoTraffic(caps)}
                serverSetup={server !== null || !caps.accounts}
                account={caps.accounts ? <AccountSummary active={section === "overview"} calls={trafficHandle.source === "api" ? trafficHandle.events.length : 0} /> : undefined}
                onOpenCall={(id) => {
                  setLogFocus({ id, nonce: Date.now() });
                  openSection("logs");
                }}
              />
            )}
            </Suspense></PageLoadBoundary>}
          </section>

          <section id="section-playground" aria-label="Playground" hidden={section !== "playground"} className="space-y-6">
            {sectionOpened("playground") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading playground…</p>}>
            <PageHeader
              title="Playground"
              lead={
                caps.accounts
                  ? "PII Guard finds personal data in what you send, swaps it for reversible placeholders before the model sees it, and puts the real values back into the answer."
                  : "PII Guard finds personal data before a request leaves your network, swaps it for reversible placeholders, and puts the real values back into the answer."
              }
            />
            <PlaygroundTabs tab={tab} onTab={openTab} caps={caps} />
            <div id="panel-text" role="tabpanel" aria-labelledby="tab-text" hidden={tab !== "text"} className="space-y-6">
              <SegmentedControl
                label="Text view"
                value={textView}
                onChange={setTextView}
                options={[
                  { value: "mask", label: "Mask a document" },
                  { value: "roundtrip", label: "Round trip" },
                ]}
              />
              <div hidden={textView !== "mask"}>
                <PageLoadBoundary><Suspense fallback={<p role="status">Loading text…</p>}>{opened("playground/text") && <Playground
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
                />}</Suspense></PageLoadBoundary>
              </div>
              {textView === "roundtrip" && (
                <PageLoadBoundary><Suspense fallback={<p role="status">Loading round trip…</p>}><RoundTrip
                  key={result?.mask.session_id ?? "none"}
                  client={engine.client}
                  result={result}
                  answer={answer}
                  onAnswer={setAnswer}
                  running={running}
                  onRun={() => void run()}
                /></Suspense></PageLoadBoundary>
              )}
            </div>
            <div id="panel-chat" role="tabpanel" aria-labelledby="tab-chat" hidden={tab !== "chat"}>
              <PageLoadBoundary><Suspense fallback={<p role="status">Loading chat…</p>}>{opened("playground/chat") && <Chat
                client={chatClient} live={engine.state.status.state === "online"} draft={chatDraft} ner={server ? server.ner.available : null} mockUpstream={server?.upstream?.mock ?? false}
                modes={chatModesOf(server, caps)}
              />}</Suspense></PageLoadBoundary>
            </div>
            <div id="panel-images" role="tabpanel" aria-labelledby="tab-images" hidden={tab !== "images"}>
              <PageLoadBoundary><Suspense fallback={<p role="status">Loading images…</p>}>{caps.images && opened("playground/images") && <Images client={engine.client} engineState={engine.state} loadImage={loadImage} replayRecorded={mockClient.maskImage?.bind(mockClient)} serverImages={server?.images ?? null} />}</Suspense></PageLoadBoundary>
            </div>
            </Suspense></PageLoadBoundary>}
          </section>

          <section id="section-logs" aria-label="Logs" hidden={section !== "logs"}>
            {sectionOpened("logs") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading logs…</p>}>
            {trafficOpened && (
              <Logs
                t={trafficHandle}
                forceFixture={forceFixture}
                sendDemo={traffic?.sendDemo}
                demoTraffic={offersDemoTraffic(caps)}
                pageHost={traffic?.pageHost}
                mockUpstream={server?.upstream?.mock ?? false}
                focus={logFocus}
                onOpenSession={(ref) => {
                  setVaultFocus({ ref, nonce: Date.now() });
                  navigate({ section: "vault", tab: "text", ref }, "push");
                }}
              />
            )}
            </Suspense></PageLoadBoundary>}
          </section>
          <section id="section-vault" aria-label="Vault" hidden={section !== "vault"}>
            {sectionOpened("vault") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading vault…</p>}>
            <Vault status={status} live={engine.engine === "api"} active={section === "vault"} client={vault} focus={vaultFocusProp} onSelectRef={(ref) => navigate({ section: "vault", tab: route.tab, ref: ref ?? undefined }, ref ? "push" : "replace")} />
            </Suspense></PageLoadBoundary>}
          </section>
          <section id="section-connect" aria-label="Connect" hidden={section !== "connect"}>
            {sectionOpened("connect") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading connect…</p>}>
            <Connect
              status={status}
              initialClient={route.section === "connect" ? (route.client ?? null) : null}
              serverSnippets={!caps.accounts || (server !== null && hostedSnippets !== undefined)}
              loadSnippets={hostedSnippets}
              gatewayLine={!caps.accounts}
              accounts={caps.accounts ? <ProviderConnections /> : undefined}
              clientSetup={caps.accounts && hosted ? () => <ClientSetup call={hosted.call} onOpenLog={(id) => { setLogFocus({ id, nonce: Date.now() }); openSection("logs"); }} /> : undefined}
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
            </Suspense></PageLoadBoundary>}
          </section>
          <section id="section-projects" aria-label="Projects" hidden={section !== "projects"}>
            {sectionOpened("projects") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading projects…</p>}>
            {/* Unlike ordinary drafts, provider credentials and key reveals must clear on departure. */}
            {section === "projects" && <Workspace call={hosted?.call} hosted={caps.accounts} onProject={selectProject} projectId={getCurrentProject()} />}
            </Suspense></PageLoadBoundary>}
          </section>
          <section id="section-policy" aria-label="Policy" hidden={section !== "policy"}>
            {sectionOpened("policy") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading policy…</p>}>
            {caps.server_policy ? <Policy status={status} /> : section === "policy" && <OwnerPolicy call={hosted?.call} projectId={getCurrentProject()} />}
            </Suspense></PageLoadBoundary>}
          </section>
          <section id="section-evaluation" aria-label="Evaluation" hidden={section !== "evaluation"}>
            {sectionOpened("evaluation") && <PageLoadBoundary><Suspense fallback={<p role="status" className="text-sm text-muted">Loading evaluation…</p>}>
            {opened("evaluation") && <Benchmarks load={loadBenchmarks} initial={route.section === "evaluation" ? (route.evaluation ?? null) : undefined} onParams={route.section === "evaluation" ? reportEvaluation : undefined} />}
            </Suspense></PageLoadBoundary>}
          </section>
          </div>
        </div>

        <footer className="mx-auto max-w-[1280px] px-4 pb-10 text-xs text-faint sm:px-6">
          {caps.accounts ? (
            <>
              All sample data is fictional. This page talks only to PII Guard, never to a model provider: PII Guard masks what you send and forwards it to the model your
              endpoint or connection names.
              {/* Only where it applies, not on every screen (LAB-1629). */}
              {section === "playground" && tab === "text" && " The Playground round trip uses a simulated answer; the test request on Connect goes to your endpoint’s real model."}
            </>
          ) : (
            <>
              All sample data is fictional. This page talks only to PII Guard, never to a model provider: image segmentation and the Chat model run behind the PII Guard server.
              The Chat model is real only when the server has an upstream; the round trip and demo mode use a simulated answer.
            </>
          )}
        </footer>
      </div>
    </div>
  );
}

function allowedRoute(route: Route, caps: Capabilities): Route {
  if (!offersSection(caps, route.section)) return DEFAULT_ROUTE;
  if (route.section !== "playground" || offersTab(caps, route.tab)) return route;
  return { section: "playground", tab: PLAYGROUND_TABS.find((t) => offersTab(caps, t.id))!.id };
}

/** The status tooltip's detail: "fast mode · rules+ner". */
function statusDetailOf(s: ServerStatus): string {
  const mode = s.gateway.modes[s.gateway.default_mode as keyof ServerStatus["gateway"]["modes"]];
  return [`${s.gateway.default_mode} mode`, mode?.detectors.join("+")].filter(Boolean).join(" · ");
}

/** The bar above every section, over the accent hairline: where you are on the left (from
 *  1024 px; below it the menu's top bar names the section) and, on the right, the project
 *  switcher and, for a signed-in hosted owner, the profile menu. */
function HeaderBar({ route, caps, apiOpen = false, projectsEnabled = true }: { route: Route; caps: Capabilities; apiOpen?: boolean; projectsEnabled?: boolean }) {
  const section = SECTIONS.find((s) => s.id === route.section)!;
  const tab = route.section === "playground" ? PLAYGROUND_TABS.find((t) => t.id === route.tab) : undefined;
  const session = useHostedSession();
  return (
    <header>
      {/* Below 1024 px the row shows only when it holds a switcher or an avatar. */}
      <div className="hidden h-12 items-center gap-3 px-4 has-[[data-header-item]]:flex sm:px-6 lg:flex">
        <p className="hidden min-w-0 items-center gap-2 text-base text-ink lg:flex">
          <span>{apiOpen ? "API reference" : section.label}</span>
          {tab && !apiOpen && (
            <>
              <span aria-hidden="true" className="text-faint">
                /
              </span>
              <span className="text-muted">{tab.label}</span>
            </>
          )}
        </p>
        <div className="ml-auto flex min-w-0 items-center gap-2.5">
          {caps.accounts && (
            <a data-header-item href="#api" aria-label="API reference" title="API reference" aria-current={apiOpen ? "page" : undefined} className="inline-flex min-h-9 shrink-0 items-center rounded-sm px-2 text-xs text-muted hover:bg-surface-2 hover:text-ink pointer-coarse:min-h-11">
              API
            </a>
          )}
          <ProjectSwitcher manage={caps.projects} enabled={projectsEnabled} />
          {caps.accounts && session && <ProfileMenu session={session} />}
        </div>
      </div>
      <div aria-hidden="true" className="header-hairline" />
    </header>
  );
}

/** The longest the first paint waits for the engine and traffic log to settle. */
const SETTLE_CAP_MS = 1200;

/** Before Overview or Logs first opens, the traffic hook holds no connection. */
const idleConnect = () => ({ close() {} });

function PlaygroundTabs({ tab, onTab, caps }: { tab: PlaygroundTab; onTab: (t: PlaygroundTab) => void; caps: Capabilities }) {
  const tabs = PLAYGROUND_TABS.filter((t) => offersTab(caps, t.id));
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = tabs.findIndex((t) => t.id === tab);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]!;
    onTab(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };
  return (
    <div role="tablist" aria-label="Playground" className="flex gap-1 border-b border-line">
      {tabs.map((t) => {
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
