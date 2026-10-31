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
// Eager on purpose: lazy-loading it behind `Suspense fallback={null}` left the hosted landing blank
// until its chunk arrived. The hosted build is the only one that renders it.
import { HostedApp } from "./hosted/HostedApp";
import { isApiHash } from "./hosted/apiConfig";
import { chatModesOf, offersDemoTraffic, offersSection, offersTab, useCapabilities, type Capabilities } from "./lib/capabilities";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createHttpChat, createMockChat, type ChatClient } from "./api/chat";
import { endpointSnippets } from "./api/connect";
import { engineReason, type EngineState } from "./api/engine";
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
import { useEngine, type EngineHandle } from "./hooks/useEngine";
import { useServerStatus, type StatusLoader } from "./hooks/useServerStatus";
import { useTheme } from "./hooks/useTheme";
import { useTraffic, type TrafficHandle } from "./hooks/useTraffic";
import { initialAnswer, knownSignatureOf, runGuard, toRunError, type KnownSession, type RunError, type RunResult } from "./lib/run";
import { DEFAULT_ROUTE, PLAYGROUND_TABS, SECTIONS, hashOf, parseHash, routeFromLocation, sameRoute, type EvaluationParams, type PlaygroundTab, type Route, type Section } from "./lib/routes";
import type { VaultClient } from "./api/vault";
import { newKnownRow, type KnownRow } from "./lib/knownRows";
import { Overview } from "./screens/Overview";
import { Logs } from "./screens/Traffic";
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
    <HostedApp console={(session) => <SignedInConsole session={session} {...props} />} />
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

function isOverviewLandingHash(hash: string): boolean {
  return hash === "" || hash === "#" || hash === "#overview";
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
        const needsSetup = Boolean(first.key) || first.state === "needs_key";
        if (!live || !needsSetup || !isOverviewLandingHash(globalThis.location?.hash ?? "")) return;
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

function useHashSync(hosted: boolean, navigate: (next: Route, how?: "push" | "replace" | "none") => void, setApiOpen: (open: boolean) => void) {
  useEffect(() => {
    const currentHash = globalThis.location?.hash ?? "";
    // An old tab link (#traffic, #benchmarks …) lands on its new place, with the URL rewritten.
    const initial = parseHash(currentHash);
    // Hosted, #api is the API reference inside the console (LAB-1626): not a section to rewrite.
    if (initial?.redirect && !(hosted && isApiHash(currentHash))) writeHash(initial.route, "replace");
    // Only route hashes switch sections (the skip link's #main must not). Back and forward
    // fire popstate, a typed or linked hash fires hashchange: both land here.
    const onHash = () => {
      const hash = globalThis.location.hash;
      // The public page's anchors belong to the hosted page around the console.
      if (hosted && isApiHash(hash)) return setApiOpen(true);
      if (hosted && SITE_HASHES.has(hash)) return;
      const parsed = parseHash(hash);
      if (parsed) navigate(parsed.route, parsed.redirect ? "replace" : "none");
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, [navigate, hosted, setApiOpen]);
}

function useConsoleNavigation(caps: Capabilities, hosted: HostedSession | null, capsKnown: boolean) {
  const [requestedRoute, setRouteState] = useState<Route>(routeFromLocation);
  // A section or tab the server doesn't offer opens the Overview (or the first offered tab).
  const route = allowedRoute(requestedRoute, caps);
  // Mount each route on its first visit, then retain its drafts/results until scope changes.
  const routeKey = route.section === "playground" ? `playground/${route.tab}` : route.section;
  const [visited, setVisited] = useState(() => new Set([routeKey]));
  if (!visited.has(routeKey)) setVisited(new Set([...visited, routeKey]));
  const opened = (key: string) => key === routeKey || visited.has(key);
  const sectionOpened = (key: string) => key === route.section || [...visited].some((visitedKey) => visitedKey.split("/")[0] === key);
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
  const reportEvaluation = useCallback((evaluation: EvaluationParams) => navigate({ section: "evaluation", tab: "text", evaluation }, "replace"), [navigate]);
  useHashSync(hosted !== null, navigate, setApiOpen);
  // Rewrite the URL only once the server has said what it offers: until then a deep link to a
  // section the defaults leave out (hosted #playground/images) must survive (LAB-1448).
  useEffect(() => {
    if (capsKnown && route !== requestedRoute) writeHash(route, "replace");
  }, [capsKnown, route, requestedRoute]);

  return { route, opened, sectionOpened, apiOpen, navigate, openSection, openTab, reportEvaluation };
}

function usePlaygroundRunner(engine: EngineHandle) {
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

  return { sampleId, text, language, setLanguage, known, setKnown, result, answer, setAnswer, running, error, run, pickSample, editText };
}

/** First paint waits (briefly) until the engine and the traffic log have settled (CLS, LAB-1448). */
function useConsoleSettled(engineState: EngineState, trafficOpened: boolean, trafficHandle: TrafficHandle, accounts: boolean, section: Section): boolean {
  const [settleTimedOut, setSettleTimedOut] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSettleTimedOut(true), SETTLE_CAP_MS);
    return () => clearTimeout(t);
  }, []);
  const setupPending = useSetupPending() && accounts && section === "overview";
  // An unreachable traffic log switches to the recorded demo by itself: wait for that switch too.
  const trafficConnecting = trafficHandle.status.state === "connecting" || trafficHandle.status.state === "offline";
  const trafficSettled = !trafficOpened || trafficHandle.source === "fixture" || !trafficConnecting;
  return settleTimedOut || (engineState.status.state !== "checking" && trafficSettled && !setupPending);
}

function useHostedTrafficSync(section: Section, trafficHandle: TrafficHandle, refreshAccount: (() => Promise<void>) | undefined) {
  // Overview's usage counters come from /v1/account: read it again each time Overview opens.
  useEffect(() => {
    if (section === "overview") void refreshAccount?.();
  }, [section, refreshAccount]);

  // Hosted: the traffic log answered 401, so ask /v1/account whether the session ended; if it
  // did, the hosted shell swaps the console for the "Your session ended" panel (LAB-1519).
  const signedOut = trafficHandle.status.state === "denied" && trafficHandle.status.reason === "signed_out";
  useEffect(() => {
    if (signedOut) void refreshAccount?.();
  }, [signedOut, refreshAccount]);
}

/** A `#vault/<ref>` deep link opens that session once the section mounts (LAB-1333). */
function resolveVaultFocus(route: Route, vaultFocus: { ref: string; nonce: number } | null): { ref: string; nonce: number } | null {
  if (vaultFocus) return vaultFocus;
  const ref = route.section === "vault" ? (route.ref ?? null) : null;
  if (ref === null) return null;
  const nonce = [...ref].reduce((n, c) => (n * 31 + c.charCodeAt(0)) | 0, 7);
  return { ref, nonce };
}

function demoSectionNotice(section: Section, tab: PlaygroundTab): string {
  if (section === "playground" && tab === "images") {
    return "Images replay regions recorded from a real SAM 3.1 run on the built-in samples; uploads need the API.";
  }
  switch (section) {
    case "evaluation":
      return "Benchmarks are bundled with this page, so they are the same with or without the API.";
    case "vault":
      return "The vault lives in the PII Guard server; demo mode has none to inspect.";
    case "overview":
    case "logs":
      return "Overview and Logs replay calls recorded from the demo stack (masked level, no original values).";
    case "connect":
    case "policy":
      return "The server can't be asked for its configuration, so this shows the defaults.";
    default:
      return "Detection runs in your browser with a small built-in rule set, so results are illustrative.";
  }
}

function DemoRecoveryHint({ state }: { state: EngineState }) {
  if (state.status.state !== "online") {
    return <>Start it with <code className="rounded-sm bg-surface px-1 font-mono text-xs">pii-guard up</code> for the real pipeline.</>;
  }
  return state.preference === "mock" ? (
    <>Switch the engine to Auto or Live API for the real pipeline.</>
  ) : (
    <>The real pipeline takes over as soon as the API serves the /v1 routes.</>
  );
}

function DemoModeBanner({ state, section, tab }: { state: EngineState; section: Section; tab: PlaygroundTab }) {
  // Nobody chose the demo engine and the API does not answer: the notice turns red.
  const apiDown = state.preference !== "mock" && state.status.state === "offline";
  return (
    <div role="status" className={apiDown ? "border-b border-danger/30 bg-danger-soft" : "border-b border-warn/30 bg-warn-soft"}>
      <p className="mx-auto max-w-[1280px] px-4 py-2 text-xs text-ink sm:px-6 sm:text-sm">
        {apiDown ? <strong className="font-medium text-danger">API not reachable.</strong> : <strong className="font-medium text-warn">Demo mode.</strong>}{" "}
        {engineReason(state)}. {demoSectionNotice(section, tab)} <DemoRecoveryHint state={state} />
      </p>
    </div>
  );
}

function ConsoleFooter({ accounts, section, tab }: { accounts: boolean; section: Section; tab: PlaygroundTab }) {
  return (
    <footer className="mx-auto max-w-[1280px] px-4 pb-10 text-xs text-faint sm:px-6">
      {accounts ? (
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
  );
}

function buildChatDraftFromPlayground(text: string, language: "hu" | "en", result: RunResult | null, chatClient: ChatClient): ChatDraft {
  const sample = sampleBehind(text);
  // The same vault session, so Chat shows the same placeholders (LAB-1261);
  // only when Chat runs on the engine that made it.
  const session = result?.mask.session_id ?? null;
  const sameEngine = session !== null && session.startsWith(MOCK_SESSION_PREFIX) === (chatClient.kind === "mock");
  return {
    text: sample ? `${sample.task}\n\n${text}` : text,
    language,
    nonce: Date.now(),
    sessionId: sameEngine ? session : null,
  };
}

interface PlaygroundTextPanelProps {
  hidden: boolean;
  opened: boolean;
  playground: ReturnType<typeof usePlaygroundRunner>;
  engine: EngineHandle;
  chatClient: ChatClient;
  onContinueToChat: (draft: ChatDraft) => void;
}

function PlaygroundTextPanel({ hidden, opened, playground, engine, chatClient, onContinueToChat }: PlaygroundTextPanelProps) {
  const [textView, setTextView] = useState<"mask" | "roundtrip">("mask");
  const { sampleId, text, language, setLanguage, known, setKnown, result, answer, setAnswer, running, error, run, pickSample, editText } = playground;
  const tryKnownSuffix = language === "hu" ? "\n\nA lakás kulcsait Gyakorló Tihamérnak kell átadni." : "\n\nPlease hand the keys to Gyakorló Tihamér's assistant.";

  return (
    <div id="panel-text" role="tabpanel" aria-labelledby="tab-text" hidden={hidden} className="space-y-6">
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
        <PageLoadBoundary>
          <Suspense fallback={<p role="status">Loading text…</p>}>
            {opened && (
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
                  editText(text.replace(/\s*$/, "") + tryKnownSuffix);
                }}
                onContinue={() => onContinueToChat(buildChatDraftFromPlayground(text, language, result, chatClient))}
              />
            )}
          </Suspense>
        </PageLoadBoundary>
      </div>
      {textView === "roundtrip" && (
        <PageLoadBoundary>
          <Suspense fallback={<p role="status">Loading round trip…</p>}>
            <RoundTrip key={result?.mask.session_id ?? "none"} client={engine.client} result={result} answer={answer} onAnswer={setAnswer} running={running} onRun={() => void run()} />
          </Suspense>
        </PageLoadBoundary>
      )}
    </div>
  );
}

function playgroundLeadText(accounts: boolean): string {
  return accounts
    ? "PII Guard finds personal data in what you send, swaps it for reversible placeholders before the model sees it, and puts the real values back into the answer."
    : "PII Guard finds personal data before a request leaves your network, swaps it for reversible placeholders, and puts the real values back into the answer.";
}

interface PlaygroundSectionProps {
  tab: PlaygroundTab;
  openTab: (t: PlaygroundTab) => void;
  caps: Capabilities;
  opened: (key: string) => boolean;
  playground: ReturnType<typeof usePlaygroundRunner>;
  engine: EngineHandle;
  mockClient: GuardClient;
  chatClient: ChatClient;
  chatDraft: ChatDraft | null;
  setChatDraft: (draft: ChatDraft | null) => void;
  loadImage?: (src: string) => Promise<Blob>;
  server: ServerStatus | null;
}

function PlaygroundSection({ tab, openTab, caps, opened, playground, engine, mockClient, chatClient, chatDraft, setChatDraft, loadImage, server }: PlaygroundSectionProps) {
  const showImages = caps.images && opened("playground/images");
  return (
    <>
      <PageHeader title="Playground" lead={playgroundLeadText(caps.accounts)} />
      <PlaygroundTabs tab={tab} onTab={openTab} caps={caps} />
      <PlaygroundTextPanel
        hidden={tab !== "text"}
        opened={opened("playground/text")}
        playground={playground}
        engine={engine}
        chatClient={chatClient}
        onContinueToChat={(draft) => {
          setChatDraft(draft);
          openTab("chat");
          window.scrollTo?.({ top: 0 });
        }}
      />
      <div id="panel-chat" role="tabpanel" aria-labelledby="tab-chat" hidden={tab !== "chat"}>
        <PageLoadBoundary>
          <Suspense fallback={<p role="status">Loading chat…</p>}>
            {opened("playground/chat") && (
              <Chat client={chatClient} live={engine.state.status.state === "online"} draft={chatDraft} ner={server ? server.ner.available : null} mockUpstream={Boolean(server?.upstream?.mock)} modes={chatModesOf(server, caps)} />
            )}
          </Suspense>
        </PageLoadBoundary>
      </div>
      <div id="panel-images" role="tabpanel" aria-labelledby="tab-images" hidden={tab !== "images"}>
        <PageLoadBoundary>
          <Suspense fallback={<p role="status">Loading images…</p>}>
            {showImages && <Images client={engine.client} engineState={engine.state} loadImage={loadImage} replayRecorded={mockClient.maskImage?.bind(mockClient)} serverImages={server?.images ?? null} />}
          </Suspense>
        </PageLoadBoundary>
      </div>
    </>
  );
}

function useTrafficFollow(section: Section, forceFixture: boolean, traffic?: Omit<TrafficProps, "forceFixture">) {
  // The traffic log feeds Overview, Logs and Connect; it connects when one first opens.
  const followsTraffic = section === "overview" || section === "logs" || section === "connect";
  const [trafficOpened, setTrafficOpened] = useState(() => followsTraffic);
  if (!trafficOpened && followsTraffic) setTrafficOpened(true);
  const trafficHandle = useTraffic({ forceFixture, connect: trafficOpened ? traffic?.connect : idleConnect, fixtureIntervalMs: traffic?.fixtureIntervalMs });
  return { trafficOpened, trafficHandle };
}

function LazySection({ id, label, active, opened, loadingText, className, children }: { id: string; label: string; active: boolean; opened: boolean; loadingText: string; className?: string; children: ReactNode }) {
  return (
    <section id={id} aria-label={label} hidden={!active} className={className}>
      {opened && (
        <PageLoadBoundary>
          <Suspense fallback={<p role="status" className="text-sm text-muted">{loadingText}</p>}>{children}</Suspense>
        </PageLoadBoundary>
      )}
    </section>
  );
}

interface OverviewViewProps {
  active: boolean;
  trafficOpened: boolean;
  trafficHandle: TrafficHandle;
  status: ReturnType<typeof useServerStatus>["result"];
  forceFixture: boolean;
  traffic?: Omit<TrafficProps, "forceFixture">;
  caps: Capabilities;
  server: ServerStatus | null;
  onOpenCall: (id: string) => void;
}

function OverviewView({ active, trafficOpened, trafficHandle, status, forceFixture, traffic, caps, server, onOpenCall }: OverviewViewProps) {
  if (!trafficOpened) return null;
  const liveCalls = trafficHandle.source === "api" ? trafficHandle.events.length : 0;
  return (
    <Overview
      t={trafficHandle}
      status={status}
      forced={forceFixture}
      sendDemo={traffic?.sendDemo}
      demoTraffic={offersDemoTraffic(caps)}
      serverSetup={server !== null || !caps.accounts}
      account={caps.accounts ? <AccountSummary active={active} calls={liveCalls} /> : undefined}
      onOpenCall={onOpenCall}
    />
  );
}

interface ConnectViewProps {
  route: Route;
  caps: Capabilities;
  status: ReturnType<typeof useServerStatus>["result"];
  server: ServerStatus | null;
  hosted: HostedSession | null;
  hostedSnippets: ReturnType<typeof endpointSnippets> | undefined;
  trafficOpened: boolean;
  trafficHandle: TrafficHandle;
  onOpenLog: (id: string) => void;
  onOpenSession: (ref: string) => void;
}

function ConnectView({ route, caps, status, server, hosted, hostedSnippets, trafficOpened, trafficHandle, onOpenLog, onOpenSession }: ConnectViewProps) {
  const initialClient = route.section === "connect" ? (route.client ?? null) : null;
  const serverSnippets = !caps.accounts || (server !== null && hostedSnippets !== undefined);
  return (
    <Connect
      status={status}
      initialClient={initialClient}
      serverSnippets={serverSnippets}
      loadSnippets={hostedSnippets}
      gatewayLine={!caps.accounts}
      accounts={caps.accounts ? <ProviderConnections /> : undefined}
      clientSetup={caps.accounts && hosted ? () => <ClientSetup call={hosted.call} onOpenLog={onOpenLog} /> : undefined}
      traffic={trafficOpened ? trafficHandle : undefined}
      onOpenLog={onOpenLog}
      onOpenSession={onOpenSession}
    />
  );
}

function PolicyView({ caps, active, status, hosted }: { caps: Capabilities; active: boolean; status: ReturnType<typeof useServerStatus>["result"]; hosted: HostedSession | null }) {
  if (caps.server_policy) return <Policy status={status} />;
  return active ? <OwnerPolicy call={hosted?.call} projectId={getCurrentProject()} /> : null;
}

interface LogsViewProps {
  trafficOpened: boolean;
  trafficHandle: TrafficHandle;
  forceFixture: boolean;
  traffic?: Omit<TrafficProps, "forceFixture">;
  caps: Capabilities;
  server: ServerStatus | null;
  logFocus: { id: string; nonce: number } | null;
  onOpenSession: (ref: string) => void;
}

function LogsView({ trafficOpened, trafficHandle, forceFixture, traffic, caps, server, logFocus, onOpenSession }: LogsViewProps) {
  if (!trafficOpened) return null;
  return (
    <Logs
      t={trafficHandle}
      forceFixture={forceFixture}
      sendDemo={traffic?.sendDemo}
      demoTraffic={offersDemoTraffic(caps)}
      pageHost={traffic?.pageHost}
      mockUpstream={Boolean(server?.upstream?.mock)}
      focus={logFocus}
      onOpenSession={onOpenSession}
    />
  );
}

function EvaluationView({ opened, route, loadBenchmarks, reportEvaluation }: { opened: boolean; route: Route; loadBenchmarks?: BenchmarkLoader; reportEvaluation: (evaluation: EvaluationParams) => void }) {
  if (!opened) return null;
  const active = route.section === "evaluation";
  return <Benchmarks load={loadBenchmarks} initial={active ? (route.evaluation ?? null) : undefined} onParams={active ? reportEvaluation : undefined} />;
}

interface ConsoleSectionsProps {
  route: Route;
  caps: Capabilities;
  opened: (key: string) => boolean;
  sectionOpened: (key: string) => boolean;
  navigate: (next: Route, how?: "push" | "replace" | "none") => void;
  openSection: (s: Section) => void;
  openTab: (t: PlaygroundTab) => void;
  reportEvaluation: (evaluation: EvaluationParams) => void;
  playground: ReturnType<typeof usePlaygroundRunner>;
  engine: EngineHandle;
  mockClient: GuardClient;
  chatClient: ChatClient;
  chatDraft: ChatDraft | null;
  setChatDraft: (draft: ChatDraft | null) => void;
  loadImage?: (src: string) => Promise<Blob>;
  loadBenchmarks?: BenchmarkLoader;
  status: ReturnType<typeof useServerStatus>["result"];
  server: ServerStatus | null;
  hosted: HostedSession | null;
  hostedSnippets: ReturnType<typeof endpointSnippets> | undefined;
  trafficOpened: boolean;
  trafficHandle: TrafficHandle;
  forceFixture: boolean;
  traffic?: Omit<TrafficProps, "forceFixture">;
  vault?: VaultClient;
}

function ConsoleSections({
  route,
  caps,
  opened,
  sectionOpened,
  navigate,
  openSection,
  openTab,
  reportEvaluation,
  playground,
  engine,
  mockClient,
  chatClient,
  chatDraft,
  setChatDraft,
  loadImage,
  loadBenchmarks,
  status,
  server,
  hosted,
  hostedSnippets,
  trafficOpened,
  trafficHandle,
  forceFixture,
  traffic,
  vault,
}: ConsoleSectionsProps) {
  const [logFocus, setLogFocus] = useState<{ id: string; nonce: number } | null>(null);
  const [vaultFocus, setVaultFocus] = useState<{ ref: string; nonce: number } | null>(null);
  const vaultFocusProp = resolveVaultFocus(route, vaultFocus);
  const section = route.section;
  const openLogCall = (id: string) => {
    setLogFocus({ id, nonce: Date.now() });
    openSection("logs");
  };

  return (
    <>
      <LazySection id="section-overview" label="Overview" active={section === "overview"} opened={sectionOpened("overview")} loadingText="Loading overview…">
        <OverviewView active={section === "overview"} trafficOpened={trafficOpened} trafficHandle={trafficHandle} status={status} forceFixture={forceFixture} traffic={traffic} caps={caps} server={server} onOpenCall={openLogCall} />
      </LazySection>

      <LazySection id="section-playground" label="Playground" active={section === "playground"} opened={sectionOpened("playground")} loadingText="Loading playground…" className="space-y-6">
        <PlaygroundSection tab={route.tab} openTab={openTab} caps={caps} opened={opened} playground={playground} engine={engine} mockClient={mockClient} chatClient={chatClient} chatDraft={chatDraft} setChatDraft={setChatDraft} loadImage={loadImage} server={server} />
      </LazySection>

      <LazySection id="section-logs" label="Logs" active={section === "logs"} opened={sectionOpened("logs")} loadingText="Loading logs…">
        <LogsView
          trafficOpened={trafficOpened}
          trafficHandle={trafficHandle}
          forceFixture={forceFixture}
          traffic={traffic}
          caps={caps}
          server={server}
          logFocus={logFocus}
          onOpenSession={(ref) => {
            setVaultFocus({ ref, nonce: Date.now() });
            navigate({ section: "vault", tab: "text", ref }, "push");
          }}
        />
      </LazySection>

      <LazySection id="section-vault" label="Vault" active={section === "vault"} opened={sectionOpened("vault")} loadingText="Loading vault…">
        <Vault status={status} live={engine.engine === "api"} active={section === "vault"} client={vault} focus={vaultFocusProp} onSelectRef={(ref) => navigate({ section: "vault", tab: route.tab, ref: ref ?? undefined }, ref ? "push" : "replace")} />
      </LazySection>

      <LazySection id="section-connect" label="Connect" active={section === "connect"} opened={sectionOpened("connect")} loadingText="Loading connect…">
        <ConnectView
          route={route}
          caps={caps}
          status={status}
          server={server}
          hosted={hosted}
          hostedSnippets={hostedSnippets}
          trafficOpened={trafficOpened}
          trafficHandle={trafficHandle}
          onOpenLog={openLogCall}
          onOpenSession={(ref) => {
            setVaultFocus({ ref, nonce: Date.now() });
            openSection("vault");
          }}
        />
      </LazySection>

      <LazySection id="section-projects" label="Projects" active={section === "projects"} opened={sectionOpened("projects")} loadingText="Loading projects…">
        {/* Unlike ordinary drafts, provider credentials and key reveals must clear on departure. */}
        {section === "projects" && <Workspace call={hosted?.call} hosted={caps.accounts} onProject={selectProject} projectId={getCurrentProject()} />}
      </LazySection>

      <LazySection id="section-policy" label="Policy" active={section === "policy"} opened={sectionOpened("policy")} loadingText="Loading policy…">
        <PolicyView caps={caps} active={section === "policy"} status={status} hosted={hosted} />
      </LazySection>

      <LazySection id="section-evaluation" label="Evaluation" active={section === "evaluation"} opened={sectionOpened("evaluation")} loadingText="Loading evaluation…">
        <EvaluationView opened={opened("evaluation")} route={route} loadBenchmarks={loadBenchmarks} reportEvaluation={reportEvaluation} />
      </LazySection>
    </>
  );
}

function useConsoleClients(api: HttpGuardClient | undefined, mock: GuardClient | undefined, envMode: string | undefined, chat: AppProps["chat"]) {
  const apiClient = useMemo(() => api ?? createHttpClient(), [api]);
  const mockClient = useMemo(() => mock ?? createMockClient({ latencyMs: 220 }), [mock]);
  const engine = useEngine(apiClient, mockClient, envMode);
  const apiChat = useMemo(() => chat?.api ?? createHttpChat(), [chat?.api]);
  const mockChat = useMemo(() => chat?.mock ?? createMockChat(mockClient), [chat?.mock, mockClient]);
  const chatClient = engine.engine === "api" ? apiChat : mockChat;
  return { mockClient, engine, chatClient };
}

function useServerCapabilities(engine: EngineHandle, loadStatus: StatusLoader | undefined) {
  const { result: status } = useServerStatus(engine.engine === "mock" ? "offline" : engine.state.status.state, loadStatus);
  const server = status.state === "ok" ? status.status : null;
  const caps = useCapabilities(server);
  // A hosted owner's snippets are one endpoint's (the project menu's "Inspect activity & vault"); the
  // console remounts when it changes.
  const [snippetsEndpoint] = useState(getSelectedEndpoint);
  const hostedSnippets = useMemo(
    () => (caps.accounts && snippetsEndpoint ? endpointSnippets(snippetsEndpoint) : undefined),
    [caps.accounts, snippetsEndpoint],
  );
  return { status, server, caps, hostedSnippets, capsKnown: status.state !== "loading" };
}

function LocalApp({ api, mock, envMode = import.meta.env.VITE_PII_GUARD_MODE, loadImage, loadBenchmarks, chat, traffic, loadStatus, vault }: AppProps) {
  const { mockClient, engine, chatClient } = useConsoleClients(api, mock, envMode, chat);
  const [chatDraft, setChatDraft] = useState<ChatDraft | null>(null);
  const [theme, setTheme] = useTheme();
  const hosted = useHostedSession();
  const { status, server, caps, hostedSnippets, capsKnown } = useServerCapabilities(engine, loadStatus);
  const { route, opened, sectionOpened, apiOpen, navigate, openSection, openTab, reportEvaluation } = useConsoleNavigation(caps, hosted, capsKnown);
  const forceFixture = engine.state.preference === "mock";
  const { trafficOpened, trafficHandle } = useTrafficFollow(route.section, forceFixture, traffic);
  const playground = usePlaygroundRunner(engine);
  const settled = useConsoleSettled(engine.state, trafficOpened, trafficHandle, caps.accounts, route.section);
  useHostedTrafficSync(route.section, trafficHandle, hosted?.refresh);

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
        {engine.engine === "mock" && <DemoModeBanner state={engine.state} section={route.section} tab={route.tab} />}

        {/* The main landmark. On the API page the reference's own <main> (Scalar renders one) is
            the page's main instead: a nested main, or a role on it, fails axe (LAB-1640). A div
            with the role, so switching keeps the element and the screens' state. */}
        <div id="main" role={apiOpen ? undefined : "main"} tabIndex={-1} className="mx-auto min-h-dvh max-w-[1280px] px-4 py-6 focus:outline-none sm:px-6 sm:py-8">
          {apiOpen && <ApiReference embedded />}
          <div hidden={apiOpen} className="console-views">
            <ConsoleSections
              route={route}
              caps={caps}
              opened={opened}
              sectionOpened={sectionOpened}
              navigate={navigate}
              openSection={openSection}
              openTab={openTab}
              reportEvaluation={reportEvaluation}
              playground={playground}
              engine={engine}
              mockClient={mockClient}
              chatClient={chatClient}
              chatDraft={chatDraft}
              setChatDraft={setChatDraft}
              loadImage={loadImage}
              loadBenchmarks={loadBenchmarks}
              status={status}
              server={server}
              hosted={hosted}
              hostedSnippets={hostedSnippets}
              trafficOpened={trafficOpened}
              trafficHandle={trafficHandle}
              forceFixture={forceFixture}
              traffic={traffic}
              vault={vault}
            />
          </div>
        </div>

        <ConsoleFooter accounts={caps.accounts} section={route.section} tab={route.tab} />
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

function HeaderTitle({ route, apiOpen }: { route: Route; apiOpen: boolean }) {
  const section = SECTIONS.find((s) => s.id === route.section)!;
  const tab = !apiOpen && route.section === "playground" ? PLAYGROUND_TABS.find((t) => t.id === route.tab) : undefined;
  return (
    <p className="hidden min-w-0 items-center gap-2 text-base text-ink lg:flex">
      <span>{apiOpen ? "API reference" : section.label}</span>
      {tab && (
        <>
          <span aria-hidden="true" className="text-faint">/</span>
          <span className="text-muted">{tab.label}</span>
        </>
      )}
    </p>
  );
}

/** The bar above every section, over the accent hairline: where you are on the left (from
 *  1024 px; below it the menu's top bar names the section) and, on the right, the project
 *  switcher and, for a signed-in hosted owner, the profile menu. */
function HeaderBar({ route, caps, apiOpen = false, projectsEnabled = true }: { route: Route; caps: Capabilities; apiOpen?: boolean; projectsEnabled?: boolean }) {
  const session = useHostedSession();
  return (
    <header>
      {/* Below 1024 px the row shows only when it holds a switcher or an avatar. */}
      <div className="hidden h-12 items-center gap-3 px-4 has-[[data-header-item]]:flex sm:px-6 lg:flex">
        <HeaderTitle route={route} apiOpen={apiOpen} />
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
