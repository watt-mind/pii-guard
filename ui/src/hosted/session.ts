import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore } from "react";
import { recovery, type Account, type Requester } from "./api";

/** The signed-in hosted owner the console runs for; null in the local console. */
export interface HostedSession { account: Account; error: string; refresh: () => Promise<void>; call: Requester }
export const HostedSessionContext = createContext<HostedSession | null>(null);
export const useHostedSession = () => useContext(HostedSessionContext);

/** The project's source repository: the public page's and the console's GitHub and docs links. */
export const SOURCE = "https://github.com/watt-mind/pii-guard";

/** The public page's section anchors, plus #site for the console's "Visit site"; every other hash is the console's. */
export const SITE_HASHES: ReadonlySet<string> = new Set(["#site", "#demo", "#why", "#for", "#how", "#images", "#meta", "#results", "#run", "#data", "#privacy"]);

/** `/v1/account`, kept on a failed refresh so a signed-in owner stays in the console. */
export function useAccount(call: Requester) {
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try { const next = await call<Account>("/v1/account"); if (next.mode !== "hosted") throw new Error(); setAccount(next); setError(""); }
    catch (e) { setError(recovery(e)); }
  }, [call]);
  useEffect(() => {
    let active = true;
    call<Account>("/v1/account").then((next) => { if (next.mode !== "hosted") throw new Error(); if (active) setAccount(next); }).catch((e: unknown) => { if (active) setError(recovery(e)); });
    return () => { active = false; };
  }, [call]);
  return { account, error, refresh };
}

function subscribeHash(listener: () => void) {
  window.addEventListener("hashchange", listener);
  window.addEventListener("popstate", listener);
  return () => { window.removeEventListener("hashchange", listener); window.removeEventListener("popstate", listener); };
}
export const useHash = () => useSyncExternalStore(subscribeHash, () => globalThis.location?.hash ?? "", () => "");

// The provider connection the Playground's Chat sends through. Per tab, like the project.
// Kept in sessionStorage (an id, never the key) so a reload keeps the choice in this tab.
const CONNECTION_KEY = "pii-guard:playground-connection";
let connection = (() => {
  try {
    return globalThis.sessionStorage?.getItem(CONNECTION_KEY) ?? "";
  } catch {
    return "";
  }
})();
const listeners = new Set<() => void>();
export const getPlaygroundConnection = () => connection;
export function setPlaygroundConnection(id: string) {
  if (connection === id) return;
  connection = id;
  try {
    globalThis.sessionStorage?.setItem(CONNECTION_KEY, id);
  } catch {
    // storage can be blocked; the choice still holds for this page
  }
  for (const listener of listeners) listener();
}
const subscribeConnection = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export const usePlaygroundConnection = () => useSyncExternalStore(subscribeConnection, getPlaygroundConnection, () => "");

/** Hosted chat: same-origin cookies, and the chosen provider connection when there is one. */
export const hostedChatFetch: typeof fetch = (input, init) => {
  const headers = new Headers(init?.headers);
  if (connection) headers.set("X-PII-Guard-Connection", connection);
  return fetch(input, { ...init, credentials: "same-origin", headers });
};

export function time(value: string | undefined) {
  if (!value) return "not available";
  const date = new Date(value);
  // EU English ("29 Oct 2026, 04:49"), not the browser's US default (LAB-1466).
  return Number.isNaN(date.getTime()) ? "not available" : date.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}
