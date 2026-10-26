import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  checkHealth,
  createRoutingClient,
  effectiveEngine,
  parseModePreference,
  type EngineKind,
  type EngineState,
  type ModePreference,
  type RoutingClient,
} from "../api/engine";
import type { HttpGuardClient } from "../api/http";
import type { GuardClient } from "../api/types";
import { readPref, writePref } from "../lib/storage";

const HEALTH_INTERVAL_MS = 15_000;

export interface EngineHandle {
  state: EngineState;
  engine: EngineKind;
  client: RoutingClient;
  setPreference: (p: ModePreference) => void;
  recheck: () => void;
}

export function initialPreference(envMode: string | undefined): ModePreference {
  return parseModePreference(readPref("mode") ?? envMode);
}

/** Engine state lives outside React so the routing client can read it at call time. */
function createEngineStore(initial: EngineState) {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    update(fn: (s: EngineState) => EngineState) {
      state = fn(state);
      listeners.forEach((l) => l());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export function useEngine(api: HttpGuardClient, mock: GuardClient, envMode?: string): EngineHandle {
  const [store] = useState(() =>
    createEngineStore({ preference: initialPreference(envMode), status: { state: "checking" }, endpointsMissing: false }),
  );
  const state = useSyncExternalStore(store.subscribe, store.get, store.get);

  const recheck = useCallback(() => {
    void checkHealth(api.health).then((status) =>
      store.update((s) => ({
        ...s,
        status,
        // An API that just came (back) online may have gained its routes; try them again.
        endpointsMissing: status.state === "online" && s.status.state !== "online" ? false : s.endpointsMissing,
      })),
    );
  }, [api, store]);

  useEffect(() => {
    recheck();
    const id = setInterval(recheck, HEALTH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [recheck]);

  const client = useMemo(
    () =>
      createRoutingClient({
        api,
        mock,
        getState: store.get,
        onEndpointsMissing: () => store.update((s) => ({ ...s, endpointsMissing: true })),
        onUnreachable: () => store.update((s) => ({ ...s, status: { state: "offline" } })),
      }),
    [api, mock, store],
  );

  const setPreference = useCallback(
    (preference: ModePreference) => {
      writePref("mode", preference);
      store.update((s) => ({ ...s, preference, endpointsMissing: false }));
    },
    [store],
  );

  return { state, engine: effectiveEngine(state), client, setPreference, recheck };
}
