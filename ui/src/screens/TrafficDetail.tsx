import type { ReactNode } from "react";
import { labelledScenarioFor, type LabelledMatch } from "../api/demoTraffic";
import { outboundCheckLabel, type TrafficEvent } from "../api/traffic";
import type { EntityType } from "../api/types";
import { MaskedText } from "../components/MaskedText";
import { NerHint } from "../components/NerHint";
import { Pane } from "../components/Pane";
import { RestoredText } from "../components/RestoredText";
import { Button } from "../components/ui";
import { useHostedSession } from "../hosted/session";
import type { TrafficSource } from "../hooks/useTraffic";
import { metaFor } from "../lib/entities";
import { errorCopy } from "../lib/errorCopy";
import { tokenize } from "../lib/placeholders";
import {
  OUTCOME_LABEL,
  SESSION_SOURCE_LABEL,
  alignValues,
  canShowOriginals,
  clock,
  detectorName,
  maskedCounts,
  refusalDetail,
  requestExtras,
  requestMessages,
  requestTools,
  responseChoices,
  type Choice,
  type Message,
  type Part,
} from "../lib/traffic";
import { setSelectedEndpoint } from "../projects/selection";
import { TimingWaterfall } from "./TrafficCharts";

/** Language codes in words (LAB-1626). */
const LANGUAGE_NAME: Record<string, string> = { hu: "Hungarian", en: "English", de: "German" };

export function OutcomeBadge({ outcome }: { outcome: string }) {
  if (outcome === "ok") return null;
  const blocked = outcome === "blocked" || outcome === "refused";
  const tone = blocked ? "bg-warn-soft text-warn ring-warn/40" : "bg-danger-soft text-danger ring-danger/40";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ring-1 ring-inset ${tone}`}>
      <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="8" cy="8" r="6" />
        <path d="M4 12 12 4" />
      </svg>
      {OUTCOME_LABEL[outcome] ?? outcome}
    </span>
  );
}

/**
 * A labelled demo scenario: its name needs the NER. When the name went through, that is a leak,
 * shown with the leak treatment even though it is expected; when the NER caught it, a neutral tag.
 */
export function LabelTag({ match }: { match: LabelledMatch }) {
  const missed = match.missed.length > 0;
  const suffix = missed ? ": in rules-only mode its name is an expected miss" : "";
  const tone = missed ? "bg-leak-soft text-leak ring-leak/40" : "text-muted ring-line-strong";
  return (
    <span
      title={`Demo scenario labeled “${match.scenario.label}”${suffix}`}
      className={`rounded-sm px-1.5 py-0.5 text-2xs font-medium whitespace-nowrap ring-1 ring-inset ${tone}`}
    >
      needs NER{missed ? <span className="font-normal"> · leaked, expected</span> : null}
    </span>
  );
}

/** Why the labelled demo call's name reached the model as written (or that the NER caught it). */
function LabelledNote({ match }: { match: LabelledMatch }) {
  const missed = match.missed.length > 0;
  const boxTone = missed ? "border-leak/40 bg-leak-soft" : "border-line bg-surface-2";
  const headingTone = missed ? "text-leak" : "text-ink";
  const summary = missed ? "Expected miss in rules-only mode." : "The NER ran and masked the name.";
  return (
    <div role="note" className={`mt-3 rounded-lg border p-3 text-sm ${boxTone}`}>
      <p className={`font-medium ${headingTone}`}>
        Demo scenario {match.scenario.name}: {match.scenario.label}. {summary}
      </p>
      <p className="mt-1 text-ink">
        {missed ? (
          <>
            This call names a person in free text, with no pre-loaded known value and nothing a rule can recognize, so the name ({match.missed.join(", ")}) reached the
            mock model as written. Every other demo call masks its names, because they are pre-loaded as session known values. This one is kept on purpose, to show what
            the NER adds. With <NerHint />, it is masked too.
          </>
        ) : (
          <>Without the NER this free-text name would reach the model as written: no known value and no rule covers it.</>
        )}
      </p>
    </div>
  );
}

export function EntityChips({ counts }: { counts: Partial<Record<EntityType, number>> }) {
  const entries = (Object.entries(counts) as [EntityType, number][]).filter(([, n]) => n > 0);
  if (!entries.length) return <span className="text-xs text-faint">nothing masked</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([type, n]) => (
        <span
          key={type}
          title={`${metaFor(type).label}: ${n} masked`}
          className={`rounded-md px-1.5 py-px font-mono text-2xs font-medium whitespace-nowrap ring-1 ring-inset ${metaFor(type).chip}`}
        >
          {metaFor(type).short} {n}
          <span className="sr-only"> {metaFor(type).label}</span>
        </span>
      ))}
    </span>
  );
}

/** The model a call went to; the offline mock upstream only echoes, whatever model was asked for (LAB-1264). */
function modelOf(e: TrafficEvent, mockUpstream: boolean): string {
  if (e.outcome === "blocked" || e.outcome === "refused") return "not forwarded";
  if (mockUpstream) return "mock upstream (echo)";
  return e.upstream?.model ?? e.model ?? "–";
}

function failCodeOf(e: TrafficEvent): string | undefined {
  if (e.error?.code) return e.error.code;
  if (e.outcome === "upstream_error") return "upstream_error";
  if (e.outcome === "upstream_failed") return "upstream_unavailable";
  if (e.outcome === "stream_error") return "stream_failed";
  return undefined;
}

function languageText(language: string | null | undefined): string {
  if (!language) return "auto";
  return LANGUAGE_NAME[language] ?? language;
}

function sessionText(e: TrafficEvent): string {
  if (!e.session_ref) return "–";
  return `${e.session_new ? "new" : "continued"} · ${e.session_ref}`;
}

function sessionSourceText(source: string | null | undefined): string {
  if (!source) return "–";
  return SESSION_SOURCE_LABEL[source] ?? source;
}

function detectorsText(detectors: string[]): string {
  return detectors.length ? detectors.map((d) => detectorName(d)).join(", ") : "–";
}

function tokensText(usage: TrafficEvent["usage"]): string {
  if (usage?.total_tokens === undefined) return "–";
  return `${usage.prompt_tokens ?? "?"} in · ${usage.completion_tokens ?? "?"} out`;
}

function cacheText(cache: TrafficEvent["cache"]): string {
  return cache ? `${cache.hits} hit · ${cache.misses} miss` : "–";
}

function CallMetaGrid({ event: e, mockUpstream }: { event: TrafficEvent; mockUpstream: boolean }) {
  return (
    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs @xl:grid-cols-3 @3xl:grid-cols-4">
      {e.endpoint && <Meta label="Endpoint" value={e.endpoint.name} />}
      <Meta label="Mode" value={e.mode ?? "–"} />
      <Meta label="Model" value={modelOf(e, mockUpstream)} />
      <Meta label="Language" value={languageText(e.language)} />
      <Meta label="Session" value={sessionText(e)} />
      <Meta label="Session from" value={sessionSourceText(e.session_source)} />
      <Meta label="Outbound check" value={outboundCheckLabel(e.outbound_check)} />
      <Meta label="Detectors" value={detectorsText(e.detectors)} />
      {/* Whose status: the model's provider here, PII Guard's own in the failure note (LAB-1640). */}
      <Meta label="Model provider answered" value={e.upstream?.status ? `HTTP ${e.upstream.status}` : "not called"} />
      <Meta label="Tokens" value={tokensText(e.usage)} />
      <Meta label="Detection cache" value={cacheText(e.cache)} />
      {e.audit_escalations != null && (
        <Meta label="LLM escalations" value={`${e.audit_escalations} text${e.audit_escalations === 1 ? "" : "s"}, masked windows`} />
      )}
    </dl>
  );
}

function SessionButton({
  event: e,
  aggregated,
  onOpenSession,
  onRememberCall,
}: {
  event: TrafficEvent;
  aggregated: boolean;
  onOpenSession?: (ref: string) => void;
  onRememberCall?: (id: string) => void;
}) {
  if (!e.session_ref || !onOpenSession) return null;
  if (aggregated && e.endpoint) {
    // The Vault is per endpoint: switch the console to this one, where the session lives.
    return (
      <Button
        size="sm"
        className="mt-3 h-auto! min-h-8 max-w-full py-1.5 text-left whitespace-normal! pointer-coarse:min-h-11"
        title={`Switches the console to endpoint ${e.endpoint.name}, where this call's session is kept`}
        onClick={() => {
          onRememberCall?.(e.id);
          setSelectedEndpoint(e.endpoint!.id);
        }}
      >
        <span className="min-w-0 break-words">Open session in {e.endpoint.name}</span>
      </Button>
    );
  }
  return (
    <Button id="open-session" size="sm" className="mt-3" onClick={() => onOpenSession(e.session_ref!)}>
      Open session <span className="font-mono">{e.session_ref}</span> in Vault
    </Button>
  );
}

function CallSummaryHeader({
  event: e,
  following,
  onFollow,
  mockUpstream,
  aggregated,
  onOpenSession,
  onRememberCall,
}: {
  event: TrafficEvent;
  following: boolean;
  onFollow: () => void;
  mockUpstream: boolean;
  aggregated: boolean;
  onOpenSession?: (ref: string) => void;
  onRememberCall?: (id: string) => void;
}) {
  const labelled = labelledScenarioFor(e);
  const unresolved = e.upstream?.unresolved_placeholders ?? 0;
  return (
    <section aria-labelledby="detail-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="detail-title" tabIndex={-1} className="flex flex-wrap items-center gap-2 text-lg font-normal text-ink outline-none">
            Call at {clock(e.time)} <OutcomeBadge outcome={e.outcome} />
          </h2>
          <p className="mt-0.5 font-mono text-xs break-all text-faint">{e.id}</p>
        </div>
        {following ? (
          <span className="rounded-full bg-surface-2 px-2.5 py-1 text-xs text-muted ring-1 ring-line">Following the latest call</span>
        ) : (
          <Button size="sm" onClick={onFollow}>
            Follow the latest call
          </Button>
        )}
      </div>
      <CallMetaGrid event={e} mockUpstream={mockUpstream} />
      <SessionButton event={e} aggregated={aggregated} onOpenSession={onOpenSession} onRememberCall={onRememberCall} />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>Masked:</span>
        <EntityChips counts={maskedCounts(e)} />
        {labelled && labelled.missed.length > 0 ? <span className="text-leak">· {labelled.missed.length} name reached the model (expected, needs NER)</span> : null}
        {unresolved ? (
          <span className="rounded-sm bg-leak-soft px-2 py-0.5 font-medium text-leak ring-1 ring-leak/40">
            {unresolved} placeholder{unresolved === 1 ? "" : "s"} the model invented (not restored)
          </span>
        ) : null}
      </div>
      {labelled && <LabelledNote match={labelled} />}
    </section>
  );
}

function errorEntityTypesText(entityTypes: Record<string, number> | undefined): string {
  if (!entityTypes) return "";
  const formatted = Object.entries(entityTypes)
    .map(([k, n]) => `${metaFor(k as EntityType).label} ×${n}`)
    .join(", ");
  return ` · ${formatted}`;
}

function failureStatusOf(e: TrafficEvent): number | null {
  return e.error?.status ?? e.upstream?.status ?? null;
}

function localFailureTitle(outcome: string): string {
  return `${outcome === "blocked" ? "Blocked by policy." : "Refused."} Nothing was sent to the model.`;
}

function failureStatusNote(e: TrafficEvent): string {
  return e.error?.status ? ` · PII Guard answered your client HTTP ${e.error.status}` : "";
}

function failureCodeOf(e: TrafficEvent): string {
  return e.error?.code ?? e.outcome;
}

function hasImageEntities(e: TrafficEvent): boolean {
  return Boolean(e.entities?.images);
}

function buildFailureView(e: TrafficEvent, forwarded: boolean): { kind: string; title: string; code: string; statusNote: string; body: string } | null {
  if (e.outcome === "ok") return null;
  // An upstream refusal reached the model's provider (masked); everything else here stopped in pii-guard (LAB-1335).
  const upstreamCopy = errorCopy(failCodeOf(e), failureStatusOf(e));
  const upstreamSide = upstreamCopy.kind === "upstream" || upstreamCopy.kind === "stream";
  if (forwarded && !upstreamSide) return null;
  return {
    kind: upstreamSide ? upstreamCopy.kind : e.outcome === "blocked" ? "policy" : "fail_closed",
    title: upstreamSide ? upstreamCopy.title : localFailureTitle(e.outcome),
    code: failureCodeOf(e),
    statusNote: failureStatusNote(e),
    body: upstreamSide ? upstreamCopy.body : refusalDetail(e.error, hasImageEntities(e)),
  };
}

function CallFailureNote({ event: e, forwarded }: { event: TrafficEvent; forwarded: boolean }) {
  const view = buildFailureView(e, forwarded);
  if (!view) return null;
  return (
    <div role="note" data-error-kind={view.kind} className="rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm sm:p-4">
      <p className="font-medium text-warn">{view.title}</p>
      <p className="mt-1 text-ink">
        <code className="font-mono text-xs">{view.code}</code>
        {view.statusNote}
        {errorEntityTypesText(e.error?.entity_types)}
      </p>
      <p className="mt-2 text-muted">{view.body}</p>
    </div>
  );
}

function OriginalOmittedNote({ event: e, source, hosted }: { event: TrafficEvent; source: TrafficSource; hosted: boolean }) {
  if (source === "fixture") return <Quiet>Recorded demo traffic never holds original values.</Quiet>;
  if (hosted) return <Quiet>Not kept: the hosted service never stores original values. This log holds only what was sent to the model.</Quiet>;
  if (e.level === "full") return <Quiet>The server logged originals, but they are only shown on a page served from localhost.</Quiet>;
  return (
    <Quiet>
      Not kept: the traffic log holds only what left the machine (level <code className="font-mono">masked</code>). To see originals here, run the API on localhost
      with its traffic log at level full, with fictional data only (<code className="font-mono">PII_GUARD_TRAFFIC_LOG=full</code>).
    </Quiet>
  );
}

export function CallDetail({
  event: e,
  following,
  source,
  pageHost,
  onFollow,
  mockUpstream,
  onOpenSession,
  onRememberCall,
  aggregated = false,
}: {
  event: TrafficEvent;
  following: boolean;
  source: TrafficSource;
  pageHost: string;
  onFollow: () => void;
  mockUpstream: boolean;
  onOpenSession?: (ref: string) => void;
  onRememberCall?: (id: string) => void;
  /** The project's merged view: an endpoint call's vault session lives on that endpoint. */
  aggregated?: boolean;
}) {
  const showOriginals = canShowOriginals(e, pageHost, source);
  const hosted = useHostedSession() !== null;
  const maskedBody = e.request?.masked;
  const forwarded = maskedBody !== undefined && maskedBody !== null;
  return (
    <>
      <CallSummaryHeader
        event={e}
        following={following}
        onFollow={onFollow}
        mockUpstream={mockUpstream}
        aggregated={aggregated}
        onOpenSession={onOpenSession}
        onRememberCall={onRememberCall}
      />

      <CallFailureNote event={e} forwarded={forwarded} />

      <section aria-labelledby="timing-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
        <h2 id="timing-title" className="mb-4 text-lg font-normal text-ink">
          Timing
        </h2>
        <TimingWaterfall event={e} />
      </section>

      <div className="grid gap-6 @3xl:grid-cols-2">
        <DetailPane id="log-original" eyebrow="Your app sent" title="Original request" side="you">
          {showOriginals && e.request?.original ? (
            <OriginalView original={e.request.original} masked={maskedBody} />
          ) : (
            <OriginalOmittedNote event={e} source={source} hosted={hosted} />
          )}
        </DetailPane>
        <DetailPane id="log-masked" eyebrow="The model received" title="Masked request" side="model">
          {forwarded ? <MaskedRequestView body={maskedBody} event={e} /> : <Quiet>Nothing was forwarded.</Quiet>}
        </DetailPane>
        <DetailPane id="log-response" eyebrow="The model answered" title="Response, masked → restored" side="model" wide>
          <ResponseView event={e} showOriginals={showOriginals} />
        </DetailPane>
      </div>
    </>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="truncate text-ink" title={value}>
        {value}
      </dd>
    </div>
  );
}

/** A request or response pane: the shared `Pane`, its body capped and scrolled. */
function DetailPane({ id, eyebrow, title, side, wide, children }: { id: string; eyebrow: string; title: string; side: "you" | "model"; wide?: boolean; children: ReactNode }) {
  return (
    <Pane id={id} eyebrow={eyebrow} title={title} side={side} scroll className={wide ? "@3xl:col-span-2" : ""}>
      <div className="space-y-3">{children}</div>
    </Pane>
  );
}

/** A quiet note inside a pane (no card inside a card). */
function Quiet({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}

function Role({ role }: { role: string }) {
  return <p className="mb-1 font-mono text-2xs text-muted">{role}</p>;
}

interface Thumbnail {
  index: number;
  width?: number;
  height?: number;
  data?: string;
  omitted?: string;
}

function isValidThumbnail(t: unknown): t is Thumbnail {
  if (typeof t !== "object" || t === null || typeof (t as Thumbnail).index !== "number") return false;
  const data = (t as Thumbnail).data;
  return data === undefined || /^data:image\/(?:webp|png);base64,/.test(data);
}

/** The masked-image thumbnails of an event by image index (LAB-1188); the log keeps no originals. */
function thumbnailsOf(event?: TrafficEvent): Map<number, Thumbnail> {
  const out = new Map<number, Thumbnail>();
  const list = (event?.request as { thumbnails?: unknown } | null | undefined)?.thumbnails;
  if (!Array.isArray(list)) return out;
  for (const t of list) {
    if (isValidThumbnail(t)) out.set(t.index, t);
  }
  return out;
}

function sumCounts(counts: Partial<Record<string, number>>): number {
  return Object.values(counts).reduce<number>((a, b) => a + (b ?? 0), 0);
}

function imageStatsNote(event?: TrafficEvent): string {
  const img = event?.entities?.images;
  if (!img) return "";
  return `${sumCounts(img.masked)} regions blacked out, ${sumCounts(img.kept)} kept, OCR ${img.ocr ? "on" : "off"}. `;
}

function imageStorageNote(thumbnail?: Thumbnail): string {
  if (thumbnail?.data) return "A downscaled copy of the masked image the model received; the original is never kept.";
  if (thumbnail?.omitted) return "The masked image was too large or unreadable for a thumbnail, so the log keeps only this summary.";
  return "The log keeps a summary of each image, not its pixels.";
}

function ImagePart({ summary, event, thumbnail }: { summary: string; event?: TrafficEvent; thumbnail?: Thumbnail }) {
  const shown = thumbnail?.data;
  return (
    <div className="flex items-start gap-3 rounded-lg border border-field bg-surface-2 p-3 text-xs text-muted">
      {shown ? (
        <img
          src={shown}
          width={thumbnail?.width}
          height={thumbnail?.height}
          alt="The masked image as sent to the model (downscaled)"
          data-testid="masked-thumbnail"
          className="h-auto max-h-48 w-auto max-w-[min(100%,20rem)] shrink-0 rounded border border-line bg-surface"
        />
      ) : (
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-8 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <rect x="6" y="8" width="5" height="5" fill="currentColor" />
          <path d="M13 9h5M13 12h5M6 16h12" />
        </svg>
      )}
      <p className="min-w-0">
        <span className="font-medium text-ink">Image</span> <span className="break-all font-mono">{summary}</span>
        <br />
        {imageStatsNote(event)}
        {imageStorageNote(thumbnail)}
      </p>
    </div>
  );
}

function MessageList({ messages, event }: { messages: Message[]; event?: TrafficEvent }) {
  const thumbnails = thumbnailsOf(event);
  // Image index across all messages, the way the server numbers its thumbnails.
  let imageIndex = 0;
  return (
    <>
      {messages.map((m, i) => (
        <div key={i}>
          <Role role={m.role} />
          <div className="space-y-2">
            {m.parts.map((p, j) => (p.kind === "text" ? <MaskedText key={j} text={p.text} /> : <ImagePart key={j} summary={p.summary} event={event} thumbnail={thumbnails.get(imageIndex++)} />))}
            {m.toolCalls.map((c, j) => (
              <ToolCallView key={`t${j}`} name={c.name}>
                <MaskedText text={c.arguments} />
              </ToolCallView>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function ToolCallView({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-line p-2">
      <p className="mb-1 font-mono text-2xs text-muted">
        tool call · <span className="text-ink">{name}</span>
      </p>
      {children}
    </div>
  );
}

function MaskedRequestView({ body, event }: { body: unknown; event: TrafficEvent }) {
  const tools = requestTools(body);
  const extras = requestExtras(body);
  return (
    <div data-testid="masked-request" className="space-y-3">
      <DetectorCaveat event={event} />
      <MessageList messages={requestMessages(body)} event={event} />
      {tools.length > 0 && (
        <details className="rounded-lg border border-line p-2" open>
          <summary className="cursor-pointer text-xs font-medium text-ink">
            Tools ({tools.length}) <span className="font-normal text-muted">definitions are masked like messages</span>
          </summary>
          <div className="mt-2 space-y-2">
            {tools.map((tool, i) => (
              <MaskedText key={i} text={tool.json} />
            ))}
          </div>
        </details>
      )}
      {extras && (
        <details className="rounded-lg border border-line p-2">
          <summary className="cursor-pointer text-xs font-medium text-ink">Other fields</summary>
          <div className="mt-2">
            <MaskedText text={extras} />
          </div>
        </details>
      )}
    </div>
  );
}

function AlignedText({ masked, value, outgoing }: { masked: string; value: string; outgoing?: boolean }) {
  const segments = alignValues(masked, value);
  if (!segments) return <div className="doc text-ink">{value}</div>;
  return <RestoredText segments={segments} outgoing={outgoing} />;
}

function OriginalPartView({ part, maskedPart }: { part: Part; maskedPart?: Part }) {
  if (part.kind === "image") return <ImagePart summary={part.summary} />;
  if (maskedPart?.kind === "text") return <AlignedText masked={maskedPart.text} value={part.text} outgoing />;
  return <div className="doc text-ink">{part.text}</div>;
}

function OriginalView({ original, masked }: { original: unknown; masked: unknown }) {
  const orig = requestMessages(original);
  const mask = requestMessages(masked);
  return (
    <div data-testid="original-request" className="space-y-3">
      {orig.map((m, i) => (
        <div key={i}>
          <Role role={m.role} />
          <div className="space-y-2">
            {m.parts.map((p, j) => (
              <OriginalPartView key={j} part={p} maskedPart={mask[i]?.parts[j]} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Which detectors ran, in words, and what they can't find: the Mask screen's caveat, per call. */
function DetectorCaveat({ event: e }: { event: TrafficEvent }) {
  const free = e.detectors.some((d) => d === "ner" || d === "llm");
  const names = e.detectors.map((d) => detectorName(d)).join(", ");
  return (
    <p className="text-xs text-muted">
      Only highlighted values were replaced; anything else reached the model as written.{" "}
      {free ? null : e.detectors.includes("known") ? (
        <>
          This call ran {names}: pre-loaded known values (names included) and structured values (email, phone, IBAN, IDs) are
          masked; other names need <NerHint />.
        </>
      ) : e.detectors.length ? (
        <>
          This call ran {names} only, which finds structured values (email, phone, IBAN, IDs) but{" "}
          <strong className="font-medium text-ink">not names</strong>: names need <NerHint />.
        </>
      ) : (
        // No detector list logged (LAB-1629): say what the rules cover, without "ran no detector only".
        <>
          Structured values (email, phone, IBAN, IDs) are found by rules, but <strong className="font-medium text-ink">not names</strong>: names need <NerHint />.
        </>
      )}
    </p>
  );
}

const placeholdersIn = (text: string) => tokenize(text).filter((t) => t.kind === "placeholder").length;

function choicePlaceholders(choices: Choice[]): number {
  return choices.reduce((n, c) => n + placeholdersIn(c.content ?? "") + c.toolCalls.reduce((k, t) => k + placeholdersIn(t.arguments), 0), 0);
}

function emptyResponseCopy(outcome: string): string {
  if (outcome === "ok") return "No answer was logged.";
  if (outcome === "upstream_failed" || outcome === "upstream_error") {
    return "No answer: the masked request was forwarded, but the model's provider did not answer usably.";
  }
  return "No answer: the call did not reach the model.";
}

function unmaskedOmittedNote(streamedTool: boolean, count: number, showOriginals: boolean, hosted: boolean): string {
  const restoration = streamedTool
    ? "The streamed tool-call arguments were restored on the way to your app; the log doesn't keep them. "
    : count
      ? `${count} placeholder${count === 1 ? " was" : "s were"} put back before the answer reached your app. `
      : "Nothing to restore in this answer. ";
  if (showOriginals) return restoration;
  const storage = hosted
    ? "The restored answer holds real values, so the hosted service doesn't keep it."
    : "The restored answer holds real values, so it is only logged at level full, on localhost.";
  return restoration + storage;
}

function MaskedChoicesList({ choices, streamed }: { choices: Choice[]; streamed: boolean }) {
  const nothing = choices.every((c) => !c.content && !c.toolCalls.length);
  if (nothing) {
    return <Quiet>{streamed ? "A streamed tool call: the log keeps streamed text, not tool-call arguments." : "Empty answer."}</Quiet>;
  }
  return (
    <>
      {choices.map((c) => (
        <div key={c.index} className="space-y-2">
          {c.content !== null && <MaskedText text={c.content} />}
          {c.toolCalls.map((t, j) => (
            <ToolCallView key={j} name={t.name}>
              <MaskedText text={t.arguments} />
            </ToolCallView>
          ))}
        </div>
      ))}
    </>
  );
}

function UnmaskedChoicesList({ unmasked, masked }: { unmasked: Choice[]; masked: Choice[] }) {
  return (
    <>
      {unmasked.map((c) => {
        const m = masked.find((x) => x.index === c.index);
        return (
          <div key={c.index} className="space-y-2">
            {c.content !== null && <AlignedText masked={m?.content ?? ""} value={c.content} />}
            {c.toolCalls.map((t, j) => (
              <ToolCallView key={j} name={t.name}>
                <AlignedText masked={m?.toolCalls[j]?.arguments ?? ""} value={t.arguments} />
              </ToolCallView>
            ))}
          </div>
        );
      })}
    </>
  );
}

function ResponseView({ event: e, showOriginals }: { event: TrafficEvent; showOriginals: boolean }) {
  const hosted = useHostedSession() !== null;
  if (!e.response) return <Quiet>{emptyResponseCopy(e.outcome)}</Quiet>;
  const masked = responseChoices(e.response.masked);
  const unmasked = showOriginals ? responseChoices(e.response.unmasked) : [];
  const nothing = masked.every((c) => !c.content && !c.toolCalls.length);
  const streamedTool = nothing && e.stream && e.outcome === "ok";
  const count = choicePlaceholders(masked);
  return (
    <div className="grid gap-4 @2xl:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
      <div data-testid="masked-response" className="min-w-0 space-y-2">
        <p className="mb-1 text-xs font-medium text-model">From the model{e.stream ? ` (streamed, ${e.response.chunks ?? "?"} chunks)` : ""}</p>
        <MaskedChoicesList choices={masked} streamed={e.stream} />
      </div>
      <div aria-hidden="true" className="flex items-center gap-2 font-mono text-2xs text-guard @2xl:flex-col @2xl:justify-center">
        <span className="h-px flex-1 bg-guard/40 @2xl:h-auto @2xl:w-px" />
        <span className="whitespace-nowrap">PII Guard</span>
        <span className="text-faint">
          <span className="@2xl:hidden">↓</span>
          <span className="hidden @2xl:inline">→</span>
        </span>
        <span className="h-px flex-1 bg-guard/40 @2xl:h-auto @2xl:w-px" />
      </div>
      <div data-testid="unmasked-response" className="min-w-0 space-y-2">
        <p className="mb-1 text-xs font-medium text-guard">To your app</p>
        {showOriginals && unmasked.length ? (
          <UnmaskedChoicesList unmasked={unmasked} masked={masked} />
        ) : (
          <Quiet>{unmaskedOmittedNote(streamedTool, count, showOriginals, hosted)}</Quiet>
        )}
      </div>
    </div>
  );
}
