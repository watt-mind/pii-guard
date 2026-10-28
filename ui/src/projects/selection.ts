import { useSyncExternalStore } from "react";

// Selection is tab-local. A project switch must remount request/session state in the UI;
// never persist vault session ids, provider credentials, or response data alongside it.
// The project and endpoint ids (never secrets) survive a reload in this tab: sessionStorage.
const KEY = "pii-guard:selection";
function readSelection(): [string | null, string | null] {
  try {
    const v = JSON.parse(globalThis.sessionStorage?.getItem(KEY) ?? "null");
    return Array.isArray(v) ? [typeof v[0] === "string" ? v[0] : null, typeof v[1] === "string" ? v[1] : null] : [null, null];
  } catch {
    return [null, null];
  }
}
function saveSelection() {
  try {
    globalThis.sessionStorage?.setItem(KEY, JSON.stringify([selectedProject, selectedEndpoint]));
  } catch {
    // storage can be blocked; the selection still holds for this page
  }
}
let [selectedProject, selectedEndpoint] = readSelection();
const listeners = new Set<() => void>();

export function getSelectedProject(): string | null { return selectedProject; }
export function getSelectedEndpoint(): string | null { return selectedEndpoint; }
// Primitive snapshots remain stable between reads, as useSyncExternalStore requires.
export function getSelectedScope(): string { return JSON.stringify([selectedProject, selectedEndpoint]); }

export function setSelectedProject(id: string | null): void {
  if (selectedProject === id && selectedEndpoint === null) return;
  selectedProject = id;
  selectedEndpoint = null;
  saveSelection();
  for (const listener of listeners) listener();
}

export function setSelectedEndpoint(id: string | null): void {
  if (selectedEndpoint === id) return;
  selectedEndpoint = id;
  saveSelection();
  for (const listener of listeners) listener();
}

export function subscribeProject(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useSelectedProject(): string | null {
  return useSyncExternalStore(subscribeProject, getSelectedProject, () => null);
}

export function useSelectedEndpoint(): string | null {
  return useSyncExternalStore(subscribeProject, getSelectedEndpoint, () => null);
}

export function useSelectedScope(): string {
  return useSyncExternalStore(subscribeProject, getSelectedScope, () => "[null,null]");
}
