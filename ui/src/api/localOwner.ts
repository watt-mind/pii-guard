import { useSyncExternalStore } from "react";

// Local owner access is tab memory only. No token enters storage, a URL, or a snippet.
let ownerToken: string | null = null;
let revision = 0;
const listeners = new Set<() => void>();
export const getOwnerToken = () => ownerToken;
export const getOwnerRevision = () => revision;
export function setOwnerToken(token: string | null) {
  if (ownerToken === token) return;
  ownerToken = token;
  revision += 1;
  for (const listener of listeners) listener();
}
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function useOwnerRevision() { return useSyncExternalStore(subscribe, getOwnerRevision, () => 0); }
