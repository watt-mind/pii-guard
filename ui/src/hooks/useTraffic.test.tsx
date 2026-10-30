import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseTrafficEvent, type TrafficConnectOptions, type TrafficEvent } from "../api/traffic";
import { useTraffic } from "./useTraffic";

const ev = (id: string, seq: number): TrafficEvent =>
  parseTrafficEvent({ id, seq, timing: {} }) as TrafficEvent;

describe("useTraffic run breaks", () => {
  it("marks the first call after a backend restart, once", () => {
    let opts!: TrafficConnectOptions;
    const connect = (o: TrafficConnectOptions) => {
      opts = o;
      return { close() {} };
    };
    const { result } = renderHook(() => useTraffic({ connect }));
    act(() => {
      opts.onEvents([ev("a1", 1), ev("a2", 2)]);
    });
    expect(result.current.events.map((e) => e.id)).toEqual(["a1", "a2"]);
    expect(result.current.runBreaks).toEqual([]);
    act(() => {
      opts.onRestart!("boot_b");
    });
    // No new call yet: nothing anchored, the flag waits.
    expect(result.current.runBreaks).toEqual([]);
    act(() => {
      opts.onEvents([ev("b1", 1)]);
    });
    expect(result.current.runBreaks.map((b) => b.beforeId)).toEqual(["b1"]);
    expect(result.current.runBreaks[0]).toMatchObject({ boot: "boot_b" });
    // Redelivered calls do not anchor a second divider for the same boot.
    act(() => {
      opts.onRestart!("boot_b");
      opts.onEvents([ev("b1", 1), ev("b2", 2)]);
    });
    expect(result.current.runBreaks).toHaveLength(1);
    expect(result.current.events.map((e) => e.id)).toEqual(["a1", "a2", "b1", "b2"]);
    act(() => {
      result.current.clear();
    });
    expect(result.current.runBreaks).toEqual([]);
    expect(result.current.events).toEqual([]);
  });
});
