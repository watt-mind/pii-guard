import { useCallback, useEffect, useRef, useState } from "react";
import {
  connectTraffic,
  parseTrafficEvent,
  startFixtureFeed,
  type TrafficConnectOptions,
  type TrafficEvent,
  type TrafficStatus,
} from "../api/traffic";
import fixture from "../content/trafficFixture.json";

/** Events kept in the browser; older ones drop off. */
export const MAX_EVENTS = 500;

export const FIXTURE_EVENTS: TrafficEvent[] = (fixture.events as unknown[])
  .map(parseTrafficEvent)
  .filter((e): e is TrafficEvent => e !== null);

export type TrafficSource = "api" | "fixture";

export interface TrafficOptions {
  /** Use the recorded fixture instead of the API (the header's engine is set to Demo engine). */
  forceFixture?: boolean;
  connect?: (o: TrafficConnectOptions) => { close(): void };
  fixtureIntervalMs?: number;
}

export interface TrafficHandle {
  source: TrafficSource;
  status: TrafficStatus;
  /** The API's own status (also while the fixture plays: why it plays). */
  apiStatus: TrafficStatus;
  events: TrafficEvent[];
  paused: boolean;
  /** Events that arrived while paused (shown on resume). */
  held: number;
  setPaused: (p: boolean) => void;
  clear: () => void;
  /** Switch to the recorded demo traffic while the API is offline or its log is off. */
  showFixture: () => void;
  /** Leave the fixture and connect to the API again. */
  retryApi: () => void;
}

export function useTraffic({ forceFixture = false, connect = connectTraffic, fixtureIntervalMs }: TrafficOptions = {}): TrafficHandle {
  const [chosenFixture, setChosenFixture] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const source: TrafficSource = forceFixture || chosenFixture ? "fixture" : "api";
  // Everything below belongs to one connection; a new source or retry starts from empty.
  const key = `${source}:${attempt}`;
  const [store, setStore] = useState<{ key: string; events: TrafficEvent[]; held: TrafficEvent[]; status: TrafficStatus }>({
    key,
    events: [],
    held: [],
    status: { state: "connecting" },
  });
  const [paused, setPausedState] = useState(false);
  const pausedRef = useRef(false);
  const current = store.key === key ? store : { key, events: [], held: [], status: { state: "connecting" } as TrafficStatus };

  const ingest = useCallback(
    (incoming: TrafficEvent[]) =>
      setStore((prev) => {
        const base = prev.key === key ? prev : { key, events: [], held: [], status: { state: "connecting" } as TrafficStatus };
        // A reconnect (or React re-running the effect) replays the backlog: keep each call once.
        const known = new Set([...base.events, ...base.held].map((e) => e.id));
        incoming = incoming.filter((e) => !known.has(e.id) && (known.add(e.id), true));
        if (!incoming.length) return prev;
        return pausedRef.current
          ? { ...base, held: [...base.held, ...incoming].slice(-MAX_EVENTS) }
          : { ...base, events: [...base.events, ...incoming].slice(-MAX_EVENTS) };
      }),
    [key],
  );
  const onStatus = useCallback(
    (status: TrafficStatus) =>
      setStore((prev) => (prev.key === key ? { ...prev, status } : { key, events: [], held: [], status })),
    [key],
  );

  useEffect(() => {
    if (source === "fixture") {
      const feed = startFixtureFeed(FIXTURE_EVENTS, ingest, { intervalMs: fixtureIntervalMs });
      return () => feed.close();
    }
    const conn = connect({ onEvents: ingest, onStatus });
    return () => conn.close();
  }, [source, connect, ingest, onStatus, fixtureIntervalMs]);

  const apiStatus: TrafficStatus = source === "api" ? current.status : { state: "offline", message: "" };
  // Offline on first contact: fall back to the recorded traffic, as the other screens fall
  // back to the demo engine. A disabled log is explained instead (it is a server setting).
  const [lastApi, setLastApi] = useState<TrafficStatus>({ state: "connecting" });
  const sawLive = useRef(false);
  useEffect(() => {
    if (source !== "api") return;
    if (current.status.state === "live") sawLive.current = true;
    if (current.status.state === "offline" && !sawLive.current) {
      const t = setTimeout(() => {
        setLastApi(current.status);
        setChosenFixture(true);
      }, 0);
      return () => clearTimeout(t);
    }
  }, [current.status, source]);

  const setPaused = useCallback((p: boolean) => {
    pausedRef.current = p;
    setPausedState(p);
    if (!p) setStore((prev) => (prev.held.length ? { ...prev, events: [...prev.events, ...prev.held].slice(-MAX_EVENTS), held: [] } : prev));
  }, []);

  const clear = useCallback(() => setStore((prev) => ({ ...prev, events: [], held: [] })), []);

  return {
    source,
    status: source === "fixture" ? { state: "live", via: "poll", level: "masked", size: FIXTURE_EVENTS.length } : current.status,
    apiStatus: source === "api" ? apiStatus : lastApi,
    events: current.events,
    paused,
    held: current.held.length,
    setPaused,
    clear,
    showFixture: useCallback(() => {
      setLastApi(current.status);
      setChosenFixture(true);
    }, [current.status]),
    retryApi: useCallback(() => {
      sawLive.current = true; // an explicit retry shows "offline" instead of bouncing back to the fixture
      setChosenFixture(false);
      setAttempt((a) => a + 1);
    }, []),
  };
}
