import { useCallback, useMemo, useRef, useState } from "react";
import { engineReason } from "./api/engine";
import { createHttpClient, type HttpGuardClient } from "./api/http";
import { createMockClient } from "./api/mock";
import type { GuardClient } from "./api/types";
import { Header, type Screen } from "./components/Header";
import { DEFAULT_SAMPLE, SAMPLES, type Sample } from "./content/samples";
import { useEngine } from "./hooks/useEngine";
import { useTheme } from "./hooks/useTheme";
import { initialAnswer, runGuard, toRunError, type RunError, type RunResult } from "./lib/run";
import { Playground } from "./screens/Playground";
import { RoundTrip } from "./screens/RoundTrip";

export interface AppProps {
  api?: HttpGuardClient;
  mock?: GuardClient;
  envMode?: string;
}

export function App({ api, mock, envMode = import.meta.env.VITE_PII_GUARD_MODE }: AppProps) {
  const apiClient = useMemo(() => api ?? createHttpClient(), [api]);
  const mockClient = useMemo(() => mock ?? createMockClient({ latencyMs: 220 }), [mock]);
  const engine = useEngine(apiClient, mockClient, envMode);
  const [theme, setTheme] = useTheme();

  const [screen, setScreen] = useState<Screen>("playground");
  const [sampleId, setSampleId] = useState<string | null>(DEFAULT_SAMPLE.id);
  const [text, setText] = useState(DEFAULT_SAMPLE.text);
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
      const r = await runGuard(engine.client, text, sampleId);
      if (id !== runId.current) return;
      setResult(r);
      setAnswer(initialAnswer(r, SAMPLES.find((s) => s.id === r.sampleId)));
    } catch (err) {
      if (id !== runId.current) return;
      // Fail closed: drop any previous masked output so nothing stale is shown as current.
      setResult(null);
      setError(toRunError(err));
    } finally {
      if (id === runId.current) setRunning(false);
    }
  }, [engine.client, text, sampleId]);

  const pickSample = (s: Sample) => {
    setSampleId(s.id);
    setText(s.text);
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
        onScreen={setScreen}
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
            <strong className="font-semibold text-warn">Demo mode.</strong> {engineReason(engine.state)}. Detection runs in your browser with a small built-in rule set, so results are illustrative.{" "}
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
            onContinue={() => {
              setScreen("roundtrip");
              window.scrollTo?.({ top: 0 });
            }}
          />
        </div>
        <div id="panel-roundtrip" role="tabpanel" aria-labelledby="tab-roundtrip" hidden={screen !== "roundtrip"}>
          <RoundTrip
            key={result?.mask.session_id ?? "none"}
            client={engine.client}
            result={result}
            answer={answer}
            onAnswer={setAnswer}
            running={running}
            onRun={() => void run()}
          />
        </div>
      </main>

      <footer className="mx-auto max-w-[1440px] px-4 pb-10 text-xs text-faint sm:px-6">
        All sample data is fictional. This page only talks to pii-guard and never calls a model provider; the model answers on the Round trip screen are simulated.
      </footer>
    </div>
  );
}
