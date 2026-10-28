import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "../api/http";
import type { EntityType } from "../api/types";
import { SOURCE_LABEL, createVaultClient, type SessionSource, type VaultClient, type VaultSessionDetail, type VaultSessionList, type VaultSessionSummary } from "../api/vault";
import { Button } from "../components/ui";
import type { ServerStatusState } from "../hooks/useServerStatus";
import { useNow } from "../hooks/useNow";
import { metaFor } from "../lib/entities";

export interface VaultProps {
  status: ServerStatusState;
  /** The real API answers (not the demo engine). */
  live: boolean;
  /** The section is on screen: the list refreshes only then. */
  active: boolean;
  client?: VaultClient;
  /** Open this session (a Logs row's "Open in Vault"); `nonce` reopens the same one. */
  focus?: { ref: string; nonce: number } | null;
  refreshMs?: number;
}

type ListState = { state: "loading" } | { state: "ok"; list: VaultSessionList } | { state: "error"; code: string; message: string };
type DetailState = { state: "idle" } | { state: "loading" } | { state: "ok"; detail: VaultSessionDetail } | { state: "error"; code: string; message: string };

const SOURCES: SessionSource[] = ["path", "prompt_cache_key", "default", "header", "api"];
const mono = (s: ReactNode) => <code className="font-mono text-xs">{s}</code>;

function errorOf(err: unknown): { code: string; message: string } {
  if (err instanceof ApiError) return { code: err.code, message: err.message };
  return {
    code: "unreachable",
    message: err instanceof Error ? err.message : "pii-guard API is not reachable",
  };
}

function ago(iso: string | null, now: number): string {
  if (!iso) return "not recorded";
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return s < 5 ? "just now" : `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min ago`;
}

function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}

const typeLabel = (t: string) => metaFor(t as EntityType).label ?? t;

export function Vault({ status, live, active, client, focus = null, refreshMs = 5000 }: VaultProps) {
  const vault = useMemo(() => client ?? createVaultClient(), [client]);
  const server = status.state === "ok" ? status.status : null;
  const mode = server?.vault_inspect ?? (server ? "masked" : null);
  const usable = live && server !== null && mode !== "off";

  const [list, setList] = useState<ListState>({ state: "loading" });
  const [source, setSource] = useState<SessionSource | "all">("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailState>({ state: "idle" });
  // Revealed values live only in this component's memory, for the session on screen.
  const [revealed, setRevealed] = useState(false);
  const [confirmDrop, setConfirmDrop] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [handledFocus, setHandledFocus] = useState<number | null>(null);
  // The detail to load: a new object (nonce) refetches, e.g. after a drop or a reveal.
  const [want, setWant] = useState<{ ref: string; reveal: boolean; nonce: number } | null>(null);
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

  const open = (ref: string) => {
    setSelected(ref);
    setRevealed(false);
    setConfirmDrop(false);
    setNotice(null);
    setDetail({ state: "loading" });
    setWant((w) => ({ ref, reveal: false, nonce: (w?.nonce ?? 0) + 1 }));
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
  const current = detail.state === "ok" && detail.detail.ref === selected ? detail.detail : null;

  const toggleReveal = () => {
    if (!selected) return;
    const next = !revealed;
    setRevealed(next);
    setWant((w) => ({ ref: selected, reveal: next, nonce: (w?.nonce ?? 0) + 1 }));
  };

  const drop = async () => {
    if (!selected) return;
    try {
      await vault.drop(selected);
      setNotice(`Dropped session ${selected}. Its placeholders can't be restored any more.`);
      setSelected(null);
      setDetail({ state: "idle" });
      setWant(null);
      setRevealed(false);
    } catch (err) {
      setNotice(`Couldn't drop the session: ${errorOf(err).message}`);
    } finally {
      setConfirmDrop(false);
      void refreshList();
    }
  };

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-medium text-balance text-ink">Vault</h1>
        <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
          The vault sessions this server holds: where each came from, and which placeholder stands for which value. For troubleshooting a value that was or wasn't restored. Values
          are shown as hints (first letter and length); originals only on demand, when the server runs the inspector in full mode on localhost.
        </p>
      </div>

      {!usable ? (
        <p role="status" className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-muted">
          {!live ? (
            "The vault lives in the pii-guard server, so this needs the live API. Start it with pii-guard up, or switch the engine to Auto or Live API."
          ) : status.state === "loading" ? (
            "Asking the server…"
          ) : server === null ? (
            "This pii-guard server doesn't report its configuration (it predates /v1/status), so the vault inspector isn't available."
          ) : (
            <>
              The vault inspector is off on this server. Set {mono("PII_GUARD_VAULT_INSPECT=masked")} (or {mono("full")} on localhost) and restart it.
            </>
          )}
        </p>
      ) : (
        <>
          <ModeNote mode={mode === "full" ? "full" : "masked"} />
          {notice && (
            <p role="status" className="rounded-xl border border-line bg-surface-2 px-4 py-2.5 text-sm text-ink">
              {notice}
            </p>
          )}
          <div className="grid items-start gap-4 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)]">
            <section aria-labelledby="vault-sessions-title" className="rounded-xl border border-line bg-surface p-4">
              <div className="flex items-baseline justify-between gap-2">
                <h2 id="vault-sessions-title" className="text-lg font-normal text-ink">
                  Sessions
                </h2>
                <span className="text-xs text-muted">
                  {list.state === "ok" ? (shown.length === sessions.length ? `${sessions.length} live` : `${shown.length} of ${sessions.length}`) : ""}
                </span>
              </div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row lg:flex-col">
                <label className="sr-only" htmlFor="vault-source">
                  Source
                </label>
                <select
                  id="vault-source"
                  value={source}
                  onChange={(e) => setSource(e.target.value as SessionSource | "all")}
                  className="h-9 rounded-lg border border-field bg-surface px-2 text-sm text-ink"
                >
                  <option value="all">All sources</option>
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {SOURCE_LABEL[s]}
                    </option>
                  ))}
                </select>
                <label className="sr-only" htmlFor="vault-search">
                  Search by session ref
                </label>
                <input
                  id="vault-search"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by session ref (s_…)"
                  className="h-9 min-w-0 flex-1 rounded-lg border border-field bg-surface px-3 font-mono text-xs text-ink placeholder:font-sans placeholder:text-sm placeholder:text-faint"
                />
              </div>
              <div className="mt-3">
                {list.state === "loading" && <p className="py-6 text-center text-sm text-muted">Loading sessions…</p>}
                {list.state === "error" && (
                  <p role="alert" className="py-4 text-sm text-danger">
                    Couldn't list the sessions: {list.message}
                  </p>
                )}
                {list.state === "ok" && sessions.length === 0 && (
                  <p className="py-6 text-center text-sm text-muted">
                    No live sessions. Send traffic through the gateway (Overview or Logs: "Send demo traffic") or mask a text in the Playground.
                  </p>
                )}
                {list.state === "ok" && sessions.length > 0 && shown.length === 0 && <p className="py-6 text-center text-sm text-muted">No session matches.</p>}
                <ul className="space-y-1" aria-label="Vault sessions">
                  {shown.map((s) => (
                    <li key={s.ref}>
                      <SessionRow s={s} now={now} selected={s.ref === selected} onOpen={() => open(s.ref)} />
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            <section aria-label="Session detail" className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5">
              {selected === null ? (
                <p className="py-10 text-center text-sm text-muted">Pick a session to see its placeholders.</p>
              ) : detail.state === "error" ? (
                <p role="alert" className="py-6 text-sm text-danger">
                  {detail.code === "not_found" ? "This session is gone: it expired or was dropped." : `Couldn't open the session: ${detail.message}`}
                </p>
              ) : current === null ? (
                <p className="py-10 text-center text-sm text-muted">Opening the session…</p>
              ) : (
                <SessionDetail
                  d={current}
                  now={now}
                  canReveal={mode === "full"}
                  revealed={revealed && current.revealed}
                  onReveal={toggleReveal}
                  confirmDrop={confirmDrop}
                  onDrop={() => setConfirmDrop(true)}
                  onCancelDrop={() => setConfirmDrop(false)}
                  onConfirmDrop={() => void drop()}
                />
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function ModeNote({ mode }: { mode: "masked" | "full" }) {
  return (
    <p className="text-xs text-muted">
      Inspector mode <span className="font-medium text-ink">{mode}</span>
      {mode === "masked" ? " · values are never sent to this page" : " · originals can be revealed per session, loopback only, and every reveal is logged on the server"}
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
  d: VaultSessionDetail;
  now: number;
  canReveal: boolean;
  revealed: boolean;
  onReveal: () => void;
  confirmDrop: boolean;
  onDrop: () => void;
  onCancelDrop: () => void;
  onConfirmDrop: () => void;
}

function SessionDetail({ d, now, canReveal, revealed, onReveal, confirmDrop, onDrop, onCancelDrop, onConfirmDrop }: DetailProps) {
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-normal text-ink">
            Session <span className="font-mono text-base">{d.ref}</span>
          </h2>
          {revealed && d.session_id && <p className="mt-0.5 font-mono text-xs break-all text-muted">id {d.session_id}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canReveal && (
            <Button className="h-8" aria-pressed={revealed} onClick={onReveal}>
              {revealed ? "Hide values" : "Reveal values"}
            </Button>
          )}
          {confirmDrop ? (
            <span role="group" aria-label="Confirm drop" className="flex items-center gap-2">
              <span className="text-xs text-ink">Drop for good?</span>
              <Button className="h-8 border-danger/50 text-danger hover:border-danger" onClick={onConfirmDrop}>
                Drop session
              </Button>
              <Button variant="ghost" className="h-8" onClick={onCancelDrop}>
                Cancel
              </Button>
            </span>
          ) : (
            <Button className="h-8" onClick={onDrop}>
              Drop…
            </Button>
          )}
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
        <Meta label="Source" value={SOURCE_LABEL[d.source] ?? d.source} />
        <Meta label="Client" value={d.client ?? "not recorded"} />
        <Meta label="Created" value={ago(d.created, now)} />
        <Meta label="Last used" value={ago(d.last_used, now)} />
        <Meta label="Expires in" value={`${duration(d.ttl_left_seconds)} unless used`} />
        <Meta label="Placeholders" value={String(d.entries)} />
        <Meta label="Known values" value={String(d.known_values)} />
        <Meta label="Generation" value={String(d.generation)} />
      </dl>
      {confirmDrop && (
        <p className="mt-3 text-xs text-muted">
          Its placeholders can't be restored afterwards: a client naming it in {mono("X-PII-Guard-Session")} gets 404, a derived session starts again empty.
        </p>
      )}

      <div className="mt-4 overflow-x-auto">
        {d.items.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">This session holds no placeholders yet.</p>
        ) : (
          <table className="w-full min-w-max text-sm">
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
                  Type
                </th>
                <th scope="col" className="px-2 py-2 font-medium">
                  Origin
                </th>
                <th scope="col" className="px-2 py-2 text-right font-medium">
                  Masked
                </th>
                <th scope="col" className="px-2 py-2 text-right font-medium">
                  Forms
                </th>
                <th scope="col" className="py-2 pl-2 font-medium">
                  {revealed ? "Value" : "Hint"}
                </th>
              </tr>
            </thead>
            <tbody>
              {d.items.map((item, i) => (
                <tr key={item.placeholder ?? `pending-${i}`} className="border-b border-line last:border-0 align-top">
                  <td className="py-2 pr-3 font-mono text-xs text-masked">
                    {item.placeholder ?? <span className="font-sans text-muted">not matched yet</span>}
                    {item.variant_of && <span className="block font-sans text-2xs text-muted">variant of {item.variant_of}</span>}
                  </td>
                  <td className="px-2 py-2 text-xs">{typeLabel(item.entity_type)}</td>
                  <td className="px-2 py-2 text-xs text-muted">{item.origin === "known" ? "Known value" : "Detected"}</td>
                  <td className="px-2 py-2 text-right font-mono text-xs tabular-nums">{item.count}</td>
                  <td className="px-2 py-2 text-right font-mono text-xs tabular-nums">{item.forms}</td>
                  <td className="py-2 pl-2 font-mono text-xs [overflow-wrap:anywhere]">
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
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs text-muted">{label}</dt>
      <dd className="truncate text-ink" title={value}>
        {value}
      </dd>
    </div>
  );
}
