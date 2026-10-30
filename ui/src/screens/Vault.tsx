import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/http";
import type { EntityType } from "../api/types";
import { SOURCE_LABEL, createVaultClient, type SessionSource, type VaultClient, type VaultSessionDetail, type VaultSessionList, type VaultSessionSummary } from "../api/vault";
import { Button, Card, ConfirmAction, Input, KeyValues, Metric, Notice, PageHeader, Select } from "../components/ui";
import type { ServerStatusState } from "../hooks/useServerStatus";
import { useNow } from "../hooks/useNow";
import { metaFor } from "../lib/entities";
import { relativeTime } from "../lib/time";
import { useHostedSession } from "../hosted/session";
import type { Endpoint } from "../projects/api";
import { localRequest } from "../projects/request";
import { getSelectedProject, setSelectedEndpoint, useSelectedEndpoint } from "../projects/selection";

export interface VaultProps {
  status: ServerStatusState;
  /** The real API answers (not the demo engine). */
  live: boolean;
  /** The section is on screen: the list refreshes only then. */
  active: boolean;
  client?: VaultClient;
  /** Open this session (a Logs row's "Open in Vault", or a #vault/<ref> deep link); `nonce` reopens the same one. */
  focus?: { ref: string; nonce: number } | null;
  /** The open session changed (or cleared): the URL hash follows it (LAB-1333). */
  onSelectRef?: (ref: string | null) => void;
  refreshMs?: number;
}

type ListState = { state: "loading" } | { state: "ok"; list: VaultSessionList } | { state: "error"; code: string; message: string };
type DetailState = { state: "idle" } | { state: "loading" } | { state: "ok"; detail: VaultSessionDetail } | { state: "error"; code: string; message: string };

const SOURCES: SessionSource[] = ["path", "prompt_cache_key", "default", "header", "api"];
const mono = (s: ReactNode) => <code className="font-mono text-xs">{s}</code>;

/**
 * Hosted has no "Send demo traffic" (LAB-1619). A call through an endpoint keeps its session under
 * that endpoint, so the project-wide view stays empty after a first call: say where it is, and
 * offer the switch when the project has exactly one endpoint.
 */
function HostedEmpty() {
  const endpointSelected = useSelectedEndpoint() !== null;
  const project = getSelectedProject();
  const [only, setOnly] = useState<Endpoint | null>(null);
  useEffect(() => {
    if (endpointSelected || !project) return;
    let live = true;
    localRequest<{ endpoints: Endpoint[] }>(`/v1/projects/${encodeURIComponent(project)}/endpoints`).then(
      (data) => {
        const enabled = Array.isArray(data.endpoints) ? data.endpoints.filter((e) => e.enabled) : [];
        if (live) setOnly(enabled.length === 1 ? enabled[0]! : null);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [endpointSelected, project]);
  if (endpointSelected)
    return <p className="py-6 text-center text-sm text-muted">No sessions on this endpoint yet. Send a call through it from your client, or open Connect to send a test request.</p>;
  return (
    <div className="space-y-3 py-4 text-center text-sm text-muted">
      <p>
        No sessions in this view. Calls through an endpoint keep their sessions under that endpoint: pick it in the header menu (Inspect activity &amp; vault), or open a call
        in Logs.
      </p>
      {only && (
        <Button size="sm" className="h-auto! min-h-8 max-w-full py-1.5 whitespace-normal! pointer-coarse:min-h-11" onClick={() => setSelectedEndpoint(only.id)}>
          Show the sessions of {only.name}
        </Button>
      )}
    </div>
  );
}

function errorOf(err: unknown): { code: string; message: string } {
  if (err instanceof ApiError) return { code: err.code, message: err.message };
  return {
    code: "unreachable",
    message: err instanceof Error ? err.message : "PII Guard API is not reachable",
  };
}

const ago = (iso: string | null, now: number): string => relativeTime(iso, now);

function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  const minutes = Math.floor((s % 3600) / 60);
  return minutes ? `${Math.floor(s / 3600)} h ${minutes} min` : `${Math.floor(s / 3600)} h`;
}

const typeLabel = (t: string) => metaFor(t as EntityType).label ?? t;

export function Vault({ status, live, active, client, focus = null, onSelectRef, refreshMs = 5000 }: VaultProps) {
  const vault = useMemo(() => client ?? createVaultClient(), [client]);
  const server = status.state === "ok" ? status.status : null;
  const mode = server?.vault_inspect ?? (server ? "masked" : null);
  const usable = live && server !== null && mode !== "off";
  const hosted = useHostedSession() !== null;

  const [list, setList] = useState<ListState>({ state: "loading" });
  const [source, setSource] = useState<SessionSource | "all">("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailState>({ state: "idle" });
  // Revealed values live only in this component's memory, for the session on screen.
  const [revealed, setRevealed] = useState(false);
  const [dropping, setDropping] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [handledFocus, setHandledFocus] = useState<number | null>(null);
  const [autoPicked, setAutoPicked] = useState(false);
  // The detail to load: a new object (nonce) refetches, e.g. after a drop or a reveal.
  const [want, setWant] = useState<{ ref: string; reveal: boolean; nonce: number } | null>(null);
  // What the open detail was loaded at (generation, counts): when the list shows the session
  // changed, the detail reloads, keeping the reveal state.
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  // After a drop, focus moves to the list it changed (or to the detail's error); never to <body>.
  const [focusAfterDrop, setFocusAfterDrop] = useState<{ to: "list" | "detail"; nonce: number } | null>(null);
  useEffect(() => {
    if (!focusAfterDrop) return;
    if (focusAfterDrop.to === "list") document.getElementById("vault-sessions-title")?.focus();
    else detailRef.current?.focus();
  }, [focusAfterDrop]);
  // Bring the detail into view once a session the user picked has loaded (phones stack it
  // under the list).
  const [scrollRequest, setScrollRequest] = useState(0);
  const scrolledFor = useRef(0);
  const now = useNow(5000);

  const refreshList = useCallback(async () => {
    try {
      const l = await vault.list();
      setList({ state: "ok", list: l });
    } catch (err) {
      setList({ state: "error", ...errorOf(err) });
    }
  }, [vault]);

  useEffect(() => {
    if (!active || !usable) return;
    const first = setTimeout(() => void refreshList(), 0);
    const t = setInterval(() => void refreshList(), refreshMs);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [active, usable, refreshList, refreshMs]);

  useEffect(() => {
    if (want === null) return;
    let stale = false;
    vault.detail(want.ref, want.reveal).then(
      (d) => {
        if (!stale) setDetail({ state: "ok", detail: d });
      },
      (err: unknown) => {
        if (!stale) setDetail({ state: "error", ...errorOf(err) });
      },
    );
    return () => {
      stale = true;
    };
  }, [vault, want]);

  useEffect(() => {
    if (detail.state !== "ok" || scrollRequest === scrolledFor.current) return;
    scrolledFor.current = scrollRequest;
    const heading = detailHeading.current;
    heading?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    heading?.focus({ preventScroll: true });
  }, [detail, scrollRequest]);

  const open = (ref: string) => {
    setScrollRequest((n) => n + 1);
    setSelected(ref);
    setRevealed(false);
    setNotice(null);
    setDetail({ state: "loading" });
    setWant((w) => ({ ref, reveal: false, nonce: (w?.nonce ?? 0) + 1 }));
    onSelectRef?.(ref);
  };

  if (focus && focus.nonce !== handledFocus && usable) {
    setHandledFocus(focus.nonce);
    setSource("all");
    setQuery("");
    open(focus.ref);
  }

  // Leaving the section forgets revealed values: they are fetched again only on demand.
  if (!active && revealed && selected) {
    setRevealed(false);
    setWant((w) => ({ ref: selected, reveal: false, nonce: (w?.nonce ?? 0) + 1 }));
  }

  const sessions = list.state === "ok" ? list.list.sessions : [];
  const shown = sessions.filter((s) => (source === "all" || s.source === source) && (query.trim() === "" || s.ref.includes(query.trim().toLowerCase())));
  // A filter that hides the open session clears its detail (LAB-1333): the screen never
  // shows a session under a list that no longer contains it. Without a filter the detail
  // stays, so an expired session still says it is gone instead of vanishing silently.
  if (selected !== null && (source !== "all" || query.trim() !== "") && !shown.some((s) => s.ref === selected)) {
    setSelected(null);
    setDetail({ state: "idle" });
    setWant(null);
    setRevealed(false);
    onSelectRef?.(null);
  }
  const current = detail.state === "ok" && detail.detail.ref === selected ? detail.detail : null;

  // Like Logs, the screen opens on a session (LAB-1626): the most recently used one, once, without
  // moving focus or the page. Not after a drop, whose confirmation sits where the detail goes.
  if (!autoPicked && selected === null && notice === null && want === null && shown.length > 0) {
    setAutoPicked(true);
    const recent = shown.reduce((a, b) => (b.last_used > a.last_used ? b : a));
    setSelected(recent.ref);
    setDetail({ state: "loading" });
    setWant((w) => ({ ref: recent.ref, reveal: false, nonce: (w?.nonce ?? 0) + 1 }));
  }

  const latest = sessions.find((s) => s.ref === selected);
  const latestKey = latest ? `${latest.generation}|${latest.entries}|${latest.occurrences}|${latest.known_values}` : null;
  if (current && latestKey !== null && latestKey !== syncedAt) {
    setSyncedAt(latestKey);
    const loadedKey = `${current.generation}|${current.entries}|${current.occurrences}|${current.known_values}`;
    if (loadedKey !== latestKey) setWant((w) => ({ ref: current.ref, reveal: revealed, nonce: (w?.nonce ?? 0) + 1 }));
  }

  const toggleReveal = () => {
    if (!selected) return;
    const next = !revealed;
    setRevealed(next);
    setWant((w) => ({ ref: selected, reveal: next, nonce: (w?.nonce ?? 0) + 1 }));
  };

  const drop = async () => {
    if (!selected) return;
    setDropping(true);
    try {
      await vault.drop(selected);
      setNotice(`Dropped session ${selected}. Its placeholders can't be restored any more.`);
      setSelected(null);
      onSelectRef?.(null);
      setDetail({ state: "idle" });
      setWant(null);
      setRevealed(false);
      setFocusAfterDrop((f) => ({ to: "list", nonce: (f?.nonce ?? 0) + 1 }));
    } catch (err) {
      setNotice(null);
      setDetail({ state: "error", ...errorOf(err), message: `Couldn't drop the session: ${errorOf(err).message}` });
      setFocusAfterDrop((f) => ({ to: "detail", nonce: (f?.nonce ?? 0) + 1 }));
    } finally {
      setDropping(false);
      void refreshList();
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Vault"
        lead={
          hosted
            ? "The vault sessions of this project: where each came from, and which placeholder stands for which value. For troubleshooting a value that was or wasn't restored. Values are shown as redacted hints; originals are never shown on the hosted service."
            : "The vault sessions this server holds: where each came from, and which placeholder stands for which value. For troubleshooting a value that was or wasn't restored. Values are shown as redacted hints; originals only on demand, when the server runs the inspector in full mode on localhost."
        }
      />

      {!usable ? (
        <Notice live>
          {!live ? (
            <>The vault lives in the PII Guard server, so this needs the live API. Start it with {mono("pii-guard up")}; if the engine is set to Demo engine, switch it to Auto.</>
          ) : status.state === "loading" ? (
            "Asking the server…"
          ) : server === null ? (
            "This PII Guard server doesn't report its configuration (it predates /v1/status), so the vault inspector isn't available."
          ) : (
            <>
              The vault inspector is off on this server. Turn it on and restart the server ({mono("PII_GUARD_VAULT_INSPECT=masked")}, or {mono("full")} on localhost).
            </>
          )}
        </Notice>
      ) : (
        <>
          {hosted ? <p className="text-xs text-muted">Original values are never sent to this page.</p> : <ModeNote mode={mode === "full" ? "full" : "masked"} />}
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)]">
            <Card
              title="Sessions"
              titleId="vault-sessions-title"
              subtitle={list.state === "ok" ? (shown.length === sessions.length ? `${sessions.length} live` : `${shown.length} of ${sessions.length} shown`) : "Loading…"}
            >
              <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
                <label className="sr-only" htmlFor="vault-source">
                  Source
                </label>
                <Select id="vault-source" value={source} onChange={(e) => setSource(e.target.value as SessionSource | "all")} className="sm:flex-1 lg:flex-none">
                  <option value="all">All sources</option>
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {SOURCE_LABEL[s]}
                    </option>
                  ))}
                </Select>
                <label className="sr-only" htmlFor="vault-search">
                  Search by session ref
                </label>
                <Input
                  id="vault-search"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by session ref (s_…)"
                  className="sm:flex-1 lg:flex-none"
                />
              </div>
              <div className="mt-3">
                {list.state === "loading" && <p className="py-6 text-center text-sm text-muted">Loading sessions…</p>}
                {list.state === "error" && (
                  <p role="alert" className="py-4 text-sm text-danger">
                    Couldn't list the sessions: {list.message}
                  </p>
                )}
                {list.state === "ok" && sessions.length === 0 &&
                  (hosted ? (
                    <HostedEmpty />
                  ) : (
                    <p className="py-6 text-center text-sm text-muted">
                      No live sessions. Send traffic through the gateway (Overview or Logs: "Send demo traffic") or mask a text in the Playground.
                    </p>
                  ))}
                {list.state === "ok" && sessions.length > 0 && shown.length === 0 && <p className="py-6 text-center text-sm text-muted">No session matches.</p>}
                {/* Capped like the Logs list, so the detail stays beside it (LAB-1626). */}
                <ul className="max-h-[26rem] space-y-1 overflow-y-auto overscroll-contain lg:max-h-[calc(100dvh-16rem)]" aria-label="Vault sessions">
                  {shown.map((s) => (
                    <li key={s.ref}>
                      <SessionRow s={s} now={now} selected={s.ref === selected} onOpen={() => open(s.ref)} />
                    </li>
                  ))}
                </ul>
              </div>
            </Card>

            <Card as="section" aria-label="Session detail" ref={detailRef} tabIndex={-1} className="min-w-0 focus:outline-none">
              {selected === null ? (
                <div className="space-y-4 text-sm">
                  {notice && (
                    <Notice tone="success" live>
                      {notice}
                    </Notice>
                  )}
                  <p className="py-6 text-center text-muted">Pick a session to see its placeholders.</p>
                </div>
              ) : detail.state === "error" ? (
                <p role="alert" className="py-6 text-sm text-danger">
                  {detail.code === "not_found" ? "This session is gone: it expired or was dropped." : `Couldn't open the session: ${detail.message}`}
                </p>
              ) : current === null ? (
                <p className="py-10 text-center text-sm text-muted">Opening the session…</p>
              ) : (
                <SessionDetail
                  headingRef={detailHeading}
                  d={current}
                  now={now}
                  canReveal={mode === "full"}
                  revealed={revealed && current.revealed}
                  onReveal={toggleReveal}
                  dropping={dropping}
                  onDrop={drop}
                />
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function ModeNote({ mode }: { mode: "masked" | "full" }) {
  return (
    <p className="text-xs text-muted">
      {mode === "masked"
        ? "Values are never sent to this page"
        : "Originals can be revealed per session, on this machine only, and every reveal is logged on the server"}{" "}
      (inspector mode <span className="font-medium text-ink">{mode}</span>).
    </p>
  );
}

function SessionRow({ s, now, selected, onOpen }: { s: VaultSessionSummary; now: number; selected: boolean; onOpen: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onOpen}
      className={["w-full rounded-sm px-3 py-2 text-left transition-colors", selected ? "bg-surface-2" : "hover:bg-surface-2"].join(" ")}
    >
      <span className="flex items-baseline justify-between gap-2">
        <span className={["font-mono text-xs text-ink", selected ? "font-medium" : ""].join(" ")}>{s.ref}</span>
        <span className="text-2xs whitespace-nowrap text-muted">{ago(s.last_used, now)}</span>
      </span>
      <span className="mt-0.5 block text-xs text-muted">
        {SOURCE_LABEL[s.source] ?? s.source} · {s.entries} placeholder
        {s.entries === 1 ? "" : "s"}
        {s.known_values ? ` · ${s.known_values} known` : ""}
      </span>
    </button>
  );
}

interface DetailProps {
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  d: VaultSessionDetail;
  now: number;
  canReveal: boolean;
  revealed: boolean;
  onReveal: () => void;
  dropping: boolean;
  onDrop: () => Promise<void>;
}

function SessionDetail({ headingRef, d, now, canReveal, revealed, onReveal, dropping, onDrop }: DetailProps) {
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 ref={headingRef} tabIndex={-1} className="text-lg font-normal text-ink focus:outline-none">
            Session <span className="font-mono text-base">{d.ref}</span>
          </h2>
          {revealed && d.session_id && <p className="mt-0.5 font-mono text-xs break-all text-muted">id {d.session_id}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canReveal && (
            <Button size="sm" onClick={onReveal}>
              {revealed ? "Hide values" : "Reveal values"}
            </Button>
          )}
          <ConfirmAction
            size="sm"
            trigger="Drop session…"
            triggerLabel={`Drop session ${d.ref}`}
            title={<>Drop session {mono(d.ref)}?</>}
            body={
              <>
                Its placeholders can't be restored afterwards. A client that still names it gets 404 (header {mono("X-PII-Guard-Session")}); a derived session starts again
                empty.
              </>
            }
            confirm="Drop session"
            busy={dropping}
            onConfirm={onDrop}
          />
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-3 sm:flex sm:flex-wrap sm:gap-x-8" aria-label="Session counts">
        <Metric label="Placeholders" value={d.entries} />
        <Metric label="Known values" value={d.known_values} />
        <Metric label="Masked so far" value={d.occurrences} suffix={d.occurrences === 1 ? "occurrence" : "occurrences"} />
      </dl>
      <KeyValues
        className="mt-4"
        items={[
          { label: "Source", value: SOURCE_LABEL[d.source] ?? d.source },
          { label: "Client", value: d.client ?? "not recorded" },
          { label: "Created", value: ago(d.created, now) },
          { label: "Last used", value: ago(d.last_used, now) },
          { label: "Expires in", value: `${duration(d.ttl_left_seconds)} unless used` },
        ]}
      />

      <div className="mt-4">
        {d.items.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">This session holds no placeholders yet.</p>
        ) : (
          <>
            <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <table className="w-full text-sm">
              <caption className="sr-only">
                Placeholders of session {d.ref}
                {revealed ? ", with original values" : ", values as hints"}
              </caption>
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Placeholder
                  </th>
                  <th scope="col" className="px-2 py-2 font-medium">
                    {revealed ? "Value" : "Hint"}
                  </th>
                  <th scope="col" className="hidden px-2 py-2 font-medium sm:table-cell">
                    Type
                  </th>
                  <th scope="col" className="hidden px-2 py-2 font-medium md:table-cell">
                    Origin
                  </th>
                  <th scope="col" className="hidden px-2 py-2 font-medium lg:table-cell">
                    Detector
                  </th>
                  <th scope="col" className="hidden px-2 py-2 text-right font-medium sm:table-cell">
                    Masked
                  </th>
                  <th scope="col" className="hidden px-2 py-2 text-right font-medium lg:table-cell">
                    Seen
                  </th>
                  <th scope="col" className="hidden py-2 pl-2 text-right font-medium md:table-cell">
                    Forms
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((item, i) => (
                  <tr key={item.placeholder ?? `pending-${i}`} className="border-b border-line align-top last:border-0">
                    <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap text-masked">
                      {item.placeholder ?? <span className="font-sans text-muted">not matched yet</span>}
                      {item.variant_of && <span className="block font-sans text-2xs whitespace-normal text-muted">variant of {item.variant_of}</span>}
                      <span className="block font-sans text-2xs whitespace-normal text-muted sm:hidden">
                        {typeLabel(item.entity_type)} · {item.origin === "known" ? "known value" : "detected"} · masked {item.count}×
                      </span>
                    </td>
                    <td className="px-2 py-2 font-mono text-xs [overflow-wrap:anywhere]">
                      {revealed && item.original != null ? (
                        <>
                          <span className="text-ink" data-original>
                            {item.original}
                          </span>
                          {item.known_forms && item.known_forms.length > 0 && <span className="block text-2xs text-muted">also {item.known_forms.join(", ")}</span>}
                        </>
                      ) : (
                        <span className="text-muted">{item.hint}</span>
                      )}
                    </td>
                    <td className="hidden px-2 py-2 text-xs whitespace-nowrap sm:table-cell">{typeLabel(item.entity_type)}</td>
                    <td className="hidden px-2 py-2 text-xs whitespace-nowrap text-muted md:table-cell">{item.origin === "known" ? "Known value" : "Detected"}</td>
                    <td className="hidden px-2 py-2 font-mono text-xs whitespace-nowrap text-muted lg:table-cell">{item.detector ?? "—"}</td>
                    <td className="hidden px-2 py-2 text-right text-xs tabular-nums sm:table-cell">{item.count}</td>
                    <td className="hidden px-2 py-2 text-right text-xs whitespace-nowrap tabular-nums text-muted lg:table-cell" title="Vault-clock seconds of the first and latest masked occurrence">
                      {item.first_seen == null ? "—" : `${item.first_seen.toFixed(1)} → ${(item.last_seen ?? item.first_seen).toFixed(1)}`}
                    </td>
                    <td className="hidden py-2 pl-2 text-right text-xs tabular-nums md:table-cell">{item.forms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <p className="mt-3 text-xs text-pretty text-muted">
              <span className="text-ink">Hint</span>: a redacted shape of the value (a word's first letter and length, a number's last two digits, nothing of a secret).{" "}
              <span className="text-ink">Masked</span>: occurrences replaced by the placeholder so far. <span className="text-ink">Forms</span>: other written forms matched onto
              the same value, such as inflections. <span className="text-ink">Detector</span>: the detector
              of the first span that created the entry. <span className="text-ink">Seen</span>: vault-clock seconds
              of the first → latest masked occurrence. <span className="text-ink">Known value</span>: pre-loaded with {mono("POST /v1/sessions")} rather than detected.
            </p>
          </>
        )}
      </div>
    </>
  );
}
