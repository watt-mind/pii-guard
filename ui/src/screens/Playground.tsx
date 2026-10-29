import { useMemo, useState } from "react";
import type { EntityType } from "../api/types";
import { Boundary } from "../components/Boundary";
import { EntityTable } from "../components/EntityTable";
import { HighlightedText } from "../components/HighlightedText";
import { Inspector, type InspectorInfo } from "../components/Inspector";
import { KnownValues } from "../components/KnownValues";
import type { KnownRow } from "../lib/knownRows";
import { Legend } from "../components/Legend";
import { MaskedText } from "../components/MaskedText";
import { Pane } from "../components/Pane";
import { Popover } from "../components/Popover";
import { BlockedNotice, Button, EmptyState, KeyValues, Metric, Select, Textarea } from "../components/ui";
import { useHostedSession } from "../hosted/session";
import { SAMPLES, sampleBehind, type Sample } from "../content/samples";
import { detectorsUsed, isKept, joinList, spanKey, summarize, type Summary } from "../lib/analysis";
import type { RunError, RunResult } from "../lib/run";

interface Props {
  text: string;
  onText: (t: string) => void;
  sampleId: string | null;
  onSample: (s: Sample) => void;
  result: RunResult | null;
  running: boolean;
  error: RunError | null;
  onRun: () => void;
  onContinue: () => void;
  language: "hu" | "en";
  onLanguage: (l: "hu" | "en") => void;
  known: KnownRow[];
  onKnown: (rows: KnownRow[]) => void;
  onTryKnown: () => void;
  /** Known-value rows as they were when `result` was made; a change makes the result stale. */
  knownSignature: string;
}

export function Playground({ text, onText, sampleId, onSample, result, running, error, onRun, onContinue, language, onLanguage, known, onKnown, onTryKnown, knownSignature }: Props) {
  const hosted = useHostedSession() !== null;
  const [editing, setEditing] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const activate = (key: string | null, el?: HTMLElement | null) => {
    setActiveKey(key);
    setAnchor(key ? (el ?? null) : null);
  };

  const fresh = result !== null && result.input === text && result.language === language && result.knownSignature === knownSignature;
  const showHighlighted = fresh && !editing;
  const sample = SAMPLES.find((s) => s.id === sampleId) ?? sampleBehind(text);

  const summary = useMemo(() => (result ? summarize(result.spans, result.mask) : null), [result]);
  const counts = useMemo(() => {
    const m = new Map<EntityType, number>();
    result?.spans.forEach((s) => m.set(s.entityType, (m.get(s.entityType) ?? 0) + 1));
    return m;
  }, [result]);
  const keptTypes = useMemo(
    () => new Set<EntityType>(result?.spans.filter(isKept).map((s) => s.entityType) ?? []),
    [result],
  );

  const info: InspectorInfo | null = useMemo(() => {
    if (!result || !activeKey) return null;
    const own = result.spans.filter((s) => spanKey(s) === activeKey);
    const first = own[0];
    const entity = result.mask.entities.find((e) => e.placeholder === activeKey);
    if (!first && !entity) return null;
    return {
      entityType: first?.entityType ?? entity?.entity_type ?? null,
      placeholder: first?.placeholder ?? entity?.placeholder ?? null,
      kept: first ? isKept(first) : false,
      detector: first?.detector,
      score: own.length ? Math.max(...own.map((s) => s.score)) : undefined,
      subtype: first?.subtype,
      occurrences: entity?.count ?? own.length,
    };
  }, [result, activeKey]);

  const run = () => {
    setEditing(false);
    onRun();
  };

  return (
    <div className="space-y-6">
      <p className="sr-only" aria-live="polite">
        {running ? "Masking the document" : error ? "" : fresh && summary ? `Done: ${summary.masked} values masked, ${summary.kept} kept by policy` : ""}
      </p>

      <SamplePicker selected={sampleId} onPick={(s) => { setEditing(false); onSample(s); }} />

      <KnownValues
        rows={known}
        onRows={onKnown}
        onTry={onTryKnown}
        found={fresh && result ? result.spans.filter((s) => s.detector === "known").length : null}
        counts={fresh ? (result?.known ?? null) : null}
        error={error?.code === "invalid_known_value" && error.knownIndex !== undefined ? { index: error.knownIndex, message: error.message } : null}
      />

      {/* The document's controls sit above the panes, so both pane headers hold only their
          titles and stay the same height at every width (LAB-1448). */}
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="doc-language" className="text-sm text-muted">
          Language
        </label>
        <div className="w-36">
          <Select
            id="doc-language"
            aria-label="Document language"
            value={language}
            onChange={(e) => onLanguage(e.target.value as "hu" | "en")}
            title="Language of the document: decides which rules and inflections apply"
          >
            <option value="hu">Hungarian</option>
            <option value="en">English</option>
          </Select>
        </div>
        <Button variant="primary" onClick={run} busy={running} disabled={!running && text.trim() === ""} aria-describedby="run-hint">
          {running ? "Masking…" : fresh ? "Run again" : "Mask document"}
          <span aria-hidden="true">→</span>
        </Button>
      </div>

      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <Pane
          id="input"
          side="you"
          eyebrow={hosted ? "Your input" : "Inside your network"}
          title="Your document"
          className="lg:flex-1"
          footer={
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              {showHighlighted ? (
                <span className="min-w-0 flex-1">Hover, tap or tab to a highlight to see its type, detector and confidence.</span>
              ) : (
                <span id="run-hint" className="min-w-0 flex-1">
                  Paste any text, or pick a sample. Only fictional data, please: this is a demo.<span className="pointer-coarse:hidden">
                    {" "}
                    <kbd className="rounded border border-line px-1 font-mono text-2xs">⌘/Ctrl ↵</kbd> runs it.
                  </span>
                </span>
              )}
              {(showHighlighted || text !== "") && (
                <span className="flex shrink-0 items-center gap-1">
                  {showHighlighted && (
                    <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
                      Edit text
                    </Button>
                  )}
                  {text !== "" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(false);
                        activate(null);
                        onText("");
                        requestAnimationFrame(() => document.getElementById("doc-input")?.focus());
                      }}
                    >
                      Clear
                    </Button>
                  )}
                </span>
              )}
            </div>
          }
        >
          {showHighlighted && result ? (
            <HighlightedText text={result.input} spans={result.spans} activeKey={activeKey} onActivate={activate} />
          ) : (
            <>
              <label htmlFor="doc-input" className="sr-only">
                Document text
              </label>
              <Textarea
                id="doc-input"
                value={text}
                onChange={(e) => onText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    run();
                  }
                }}
                spellCheck={false}
                rows={16}
                className="doc block"
                placeholder="Paste a contract, an email, a referral… (fictional data only)"
              />
            </>
          )}
        </Pane>

        <Boundary direction="outbound" label="PII Guard boundary: only masked text crosses it">
          {summary && fresh && (
            <dl className="flex gap-3 text-center lg:flex-col lg:gap-2">
              <Metric label="found" value={summary.detected} className="min-w-12" />
              <Metric label="masked" value={summary.masked} className="min-w-12" />
              <Metric label="kept" value={summary.kept} className="min-w-12" />
            </dl>
          )}
        </Boundary>

        <Pane
          id="model"
          side="model"
          eyebrow="Sent to the model"
          title="What the model saw"
          className="lg:flex-1"
          actions={
            result && fresh ? (
              <CopyButton text={result.mask.masked_text} />
            ) : undefined
          }
          footer={
            result && fresh && summary ? (
              result.engine === "mock" ? (
                <span>Demo engine: a small rule set running in your browser, so it misses more than the live pipeline.</span>
              ) : undefined
            ) : undefined
          }
        >
          {error ? (
            <BlockedNotice error={error} onRetry={text.trim() !== "" ? run : undefined} />
          ) : running ? (
            <SkeletonLines />
          ) : result && fresh ? (
            <div className="space-y-4">
              {sample && result.input.startsWith(sample.text) && (
                <p className="border-l-2 border-model pl-3 text-sm text-ink">
                  <span className="font-medium text-model">Instruction: </span>
                  {sample.task}
                </p>
              )}
              {summary && <ScopeNote summary={summary} detectors={detectorsUsed(result.spans)} demo={result.engine === "mock"} />}
              <MaskedText text={result.mask.masked_text} activeKey={activeKey} onActivate={activate} />
            </div>
          ) : (
            <EmptyState
              title={result ? (result.input === text ? "The settings changed" : "The document changed") : "Nothing has been sent yet"}
              body={
                result
                  ? "Run the guard again to see what the model would get for this version."
                  : hosted
                    ? "Mask the document to see exactly what the model would get."
                    : "Mask the document to see exactly what would leave your network."
              }
            />
          )}
        </Pane>
      </div>

      {result && fresh && !error && (
        <section aria-labelledby="session-title" className="grid grid-cols-[minmax(0,1fr)] gap-6 border-t border-line pt-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <div className="space-y-4">
            <div>
              <h2 id="session-title" className="text-lg font-normal text-ink">
                Detected entities
              </h2>
              <p className="mt-0.5 text-sm text-muted">
                Blue values were replaced by a placeholder. A dashed outline means a value was detected but kept by policy (organizations, for example, are usually not personal data and the model needs them).
              </p>
            </div>
            <Legend counts={counts} kept={keptTypes} activeType={info?.entityType ?? null} known={result.spans.filter((s) => s.detector === "known").length} />
            <KeyValues
              items={[
                {
                  label: "Session",
                  value: (
                    <span className="block truncate font-mono" title={result.mask.session_id}>
                      {result.mask.session_id}
                    </span>
                  ),
                },
                { label: "Engine", value: result.engine === "api" ? "PII Guard API" : "Demo engine (in browser)" },
                { label: "Round trip", value: <span className="tabular-nums">{result.ms} ms</span> },
              ]}
            />
            <Button variant="primary" onClick={onContinue}>
              Send it to the model <span aria-hidden="true">→</span>
            </Button>
          </div>
          <div>
            <h3 className="mb-2 text-lg font-normal text-ink">Placeholder map</h3>
            <EntityTable entities={result.mask.entities} spans={result.spans} activeKey={activeKey} onActivate={activate} />
          </div>
        </section>
      )}

      <Popover anchor={info ? anchor : null}>
        <Inspector info={info} hint="" />
      </Popover>
    </div>
  );
}

/** Live mode: say exactly what this engine did, so gaps read as known scope rather than a promise. */
function ScopeNote({ summary, detectors, demo }: { summary: Summary; detectors: string[]; demo: boolean }) {
  return (
    <div className="text-sm text-ink" data-testid="scope-note">
      <p>
        <span className="font-medium">
          {summary.masked} {summary.masked === 1 ? "value" : "values"} masked
        </span>
        {detectors.length > 0 && <> by {joinList(detectors)}</>}
        {summary.kept > 0 && <>, {summary.kept} kept by policy</>}.
      </p>
      <p className="mt-0.5 text-muted">
        Only highlighted values were replaced. Anything without a highlight on the left was not detected {demo ? "by the in-browser demo rules" : "by the detectors running on this API"} and reached the model as written.
      </p>
    </div>
  );
}

function SamplePicker({ selected, onPick }: { selected: string | null; onPick: (s: Sample) => void }) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-xs font-medium text-muted">Fictional samples</legend>
      <div className="-mx-4 flex snap-x scroll-px-4 gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible lg:grid-cols-4 sm:px-0 sm:pb-0">
        {SAMPLES.map((s) => (
          <label
            key={s.id}
            className={[
              // relative: the sr-only radio is absolute and must stay inside the scroller.
              "group relative flex w-[15rem] shrink-0 cursor-pointer snap-start items-center justify-between gap-3 rounded-lg border border-line px-3.5 py-2.5 text-left transition-colors sm:w-auto",
              "hover:border-line-strong hover:bg-surface has-[:checked]:border-line-strong has-[:checked]:bg-surface has-[:checked]:shadow-[0_0_0_1px_var(--line-strong)]",
              "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--focus)]",
            ].join(" ")}
          >
            <input
              type="radio"
              name="playground-sample"
              value={s.id}
              checked={s.id === selected}
              onChange={(e) => {
                e.currentTarget.closest("label")?.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "smooth" });
                onPick(s);
              }}
              className="peer sr-only"
            />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-ink">{s.title}</span>
              <span className="block truncate text-xs text-muted">{s.subtitle}</span>
            </span>
            <span
              aria-hidden="true"
              className="size-4 shrink-0 rounded-full border-2 border-line-strong peer-checked:border-ink peer-checked:bg-ink peer-checked:shadow-[inset_0_0_0_3px_var(--surface)]"
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function SkeletonLines() {
  return (
    <div aria-hidden="true" className="space-y-3 motion-safe:animate-pulse">
      {[92, 78, 85, 60, 88, 70, 40].map((w, i) => (
        <div key={i} className="h-3 rounded bg-line" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? "Copied" : "Copy masked"}
    </Button>
  );
}
