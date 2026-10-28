import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore } from "react";
import { recovery, type Account, type Requester } from "./api";

/** The signed-in hosted owner the console runs for; null in the local console. */
export interface HostedSession { account: Account; error: string; refresh: () => Promise<void>; call: Requester }
export const HostedSessionContext = createContext<HostedSession | null>(null);
export const useHostedSession = () => useContext(HostedSessionContext);

/** The public page's anchors, plus #site for the console's "View site"; every other hash is the console's. */
export const SITE_HASHES: ReadonlySet<string> = new Set(["#site", "#demo", "#privacy"]);

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

// The provider connection the Playground's Chat sends through. Tab memory only, like the project.
let connection = "";
const listeners = new Set<() => void>();
export const getPlaygroundConnection = () => connection;
export function setPlaygroundConnection(id: string) {
  if (connection === id) return;
  connection = id;
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
  return Number.isNaN(date.getTime()) ? "not available" : date.toLocaleString();
}
