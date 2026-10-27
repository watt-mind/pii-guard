import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createHttpChat, createMockChat, type ChatClient } from "./api/chat";
import { engineReason } from "./api/engine";
import { createHttpClient, type HttpGuardClient } from "./api/http";
import { createMockClient } from "./api/mock";
import type { GuardClient } from "./api/types";
import { Header, type Screen } from "./components/Header";
import { DEFAULT_SAMPLE, SAMPLES, sampleBehind, type Sample } from "./content/samples";
import type { BenchmarkLoader } from "./api/benchmarks";
import { useEngine } from "./hooks/useEngine";
import { useTheme } from "./hooks/useTheme";
import { initialAnswer, runGuard, toRunError, type RunError, type RunResult } from "./lib/run";
import { Playground } from "./screens/Playground";
import { Benchmarks } from "./screens/Benchmarks";
import { Images } from "./screens/Images";
import { RoundTrip } from "./screens/RoundTrip";
import { Chat, type ChatDraft } from "./screens/Chat";
import type { KnownRow } from "./lib/knownRows";
import { knownSignatureOf, type KnownSession } from "./lib/run";
import { newKnownRow } from "./lib/knownRows";

// The open tab lives in the URL hash, so a reload (or a shared link) lands on the same screen.
const HASH_TO_SCREEN: Record<string, Screen> = { "#mask": "playground", "#chat": "chat", "#images": "images", "#benchmarks": "benchmarks" };
const SCREEN_TO_HASH: Record<Screen, string> = { playground: "#mask", chat: "#chat", images: "#images", benchmarks: "#benchmarks" };
const screenFromHash = (): Screen => HASH_TO_SCREEN[globalThis.location?.hash ?? ""] ?? "playground";

export interface AppProps {
  api?: HttpGuardClient;
  mock?: GuardClient;
  envMode?: string;
  /** Loads a sample image's bytes (Images screen); injectable for tests. */
  loadImage?: (src: string) => Promise<Blob>;
  /** Loads the benchmark index (Benchmarks screen); injectable for tests. */
  loadBenchmarks?: BenchmarkLoader;
  /** Gateway chat clients (Chat screen); injectable for tests. */
  chat?: { api?: ChatClient; mock?: ChatClient };
}

export function App({ api, mock, envMode = import.meta.env.VITE_PII_GUARD_MODE, loadImage, loadBenchmarks, chat }: AppProps) {
  const apiClient = useMemo(() => api ?? createHttpClient(), [api]);
  const mockClient = useMemo(() => mock ?? createMockClient({ latencyMs: 220 }), [mock]);
  const engine = useEngine(apiClient, mockClient, envMode);
  const apiChat = useMemo(() => chat?.api ?? createHttpChat(), [chat?.api]);
  const mockChat = useMemo(() => chat?.mock ?? createMockChat(mockClient), [chat?.mock, mockClient]);
  const [chatDraft, setChatDraft] = useState<ChatDraft | null>(null);
  const [theme, setTheme] = useTheme();

  const [screen, setScreenState] = useState<Screen>(screenFromHash);
  // Benchmarks load their data lazily on first open, then stay mounted (filters survive tab switches).
  const [benchmarksOpened, setBenchmarksOpened] = useState(() => screenFromHash() === "benchmarks");
  const setScreen = useCallback((s: Screen) => {
    if (s === "benchmarks") setBenchmarksOpened(true);
    setScreenState(s);
    try {
      if (globalThis.location.hash !== SCREEN_TO_HASH[s]) history.replaceState(null, "", SCREEN_TO_HASH[s]);
    } catch {
      // sandboxed frames may refuse; the tab still works
    }
  }, []);
  const openScreen = setScreen;
  useEffect(() => {
    // Only tab hashes switch tabs (the skip link's #main must not).
    const onHash = () => {
      const s = HASH_TO_SCREEN[globalThis.location.hash];
      if (s) setScreen(s);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [setScreen]);
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

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <Header
        screen={screen}
        onScreen={openScreen}
        engineState={engine.state}
        engine={engine.engine}
        onPreference={engine.setPreference}
        onRecheck={engine.recheck}
        theme={theme}
        onTheme={setTheme}
      />

      {engine.engine === "mock" && (
        <div role="status" className="border-b border-warn/30 bg-warn-soft">
          <p className="mx-auto max-w-[1440px] px-4 py-2 text-xs text-ink sm:px-6 sm:text-sm">
            <strong className="font-semibold text-warn">Demo mode.</strong> {engineReason(engine.state)}.{" "}
            {screen === "images"
              ? "Images replay regions recorded from a real SAM 3.1 run on the built-in samples; uploads need the API."
              : screen === "benchmarks"
                ? "Benchmarks are bundled with this page, so they are the same with or without the API."
                : "Detection runs in your browser with a small built-in rule set, so results are illustrative."}{" "}
            {engine.state.status.state === "online" ? (
              engine.state.preference === "mock" ? (
                <>Switch the engine to Auto or Live API for the real pipeline.</>
              ) : (
                <>The real pipeline takes over as soon as the API serves the /v1 routes.</>
              )
            ) : (
              <>
                Start the API with <code className="rounded bg-surface px-1 font-mono text-xs">uv run pii-guard serve</code> for the real pipeline.
              </>
            )}
          </p>
        </div>
      )}

      <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8">
        <div id="panel-playground" role="tabpanel" aria-labelledby="tab-playground" hidden={screen !== "playground"}>
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
              setChatDraft({ text: sample ? `${sample.task}\n\n${text}` : text, language, nonce: Date.now() });
              setScreen("chat");
              window.scrollTo?.({ top: 0 });
            }}
          />
        </div>
        <div id="panel-chat" role="tabpanel" aria-labelledby="tab-chat" hidden={screen !== "chat"}>
          <Chat
            client={engine.engine === "api" ? apiChat : mockChat}
            live={engine.state.status.state === "online"}
            draft={chatDraft}
            replay={
              <RoundTrip
                key={result?.mask.session_id ?? "none"}
                client={engine.client}
                result={result}
                answer={answer}
                onAnswer={setAnswer}
                running={running}
                onRun={() => void run()}
              />
            }
          />
        </div>
        <div id="panel-images" role="tabpanel" aria-labelledby="tab-images" hidden={screen !== "images"}>
          <Images client={engine.client} engineState={engine.state} loadImage={loadImage} />
        </div>
        <div id="panel-benchmarks" role="tabpanel" aria-labelledby="tab-benchmarks" hidden={screen !== "benchmarks"}>
          {benchmarksOpened && <Benchmarks load={loadBenchmarks} />}
        </div>
      </main>

      <footer className="mx-auto max-w-[1440px] px-4 pb-10 text-xs text-faint sm:px-6">
        All sample data is fictional. This page only talks to pii-guard and never calls a model provider itself (SAM 3.1 is called by the pii-guard server); on the Chat screen the model is real only when the API runs with an upstream; the document replay and demo mode use a simulated answer.
      </footer>
    </div>
  );
}
