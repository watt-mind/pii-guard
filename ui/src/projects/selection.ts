import { useSyncExternalStore } from "react";

// Selection is tab-local. A project switch must remount request/session state in the UI;
// never persist vault session ids, provider credentials, or response data alongside it.
let selectedProject: string | null = null;
let selectedEndpoint: string | null = null;
const listeners = new Set<() => void>();

export function getSelectedProject(): string | null { return selectedProject; }
export function getSelectedEndpoint(): string | null { return selectedEndpoint; }
// Primitive snapshots remain stable between reads, as useSyncExternalStore requires.
export function getSelectedScope(): string { return JSON.stringify([selectedProject, selectedEndpoint]); }

export function setSelectedProject(id: string | null): void {
  if (selectedProject === id && selectedEndpoint === null) return;
  selectedProject = id;
  selectedEndpoint = null;
  for (const listener of listeners) listener();
}

export function setSelectedEndpoint(id: string | null): void {
  if (selectedEndpoint === id) return;
  selectedEndpoint = id;
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
