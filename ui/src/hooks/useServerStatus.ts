import { useCallback, useEffect, useRef, useState } from "react";
import { fetchStatus, type StatusResult } from "../api/status";

export type StatusLoader = () => Promise<StatusResult>;

export type ServerStatusState = StatusResult | { state: "loading" };

/**
 * The server's `/v1/status`, loaded when the API is online and again each time it comes back.
 * Demo mode (API offline) leaves it "offline": the screens then say what they can't know.
 */
export function useServerStatus(api: "checking" | "online" | "offline", load: StatusLoader = fetchStatus): { result: ServerStatusState; reload: () => void } {
  const [result, setResult] = useState<ServerStatusState>({ state: "loading" });
  const seq = useRef(0);
  const reload = useCallback(() => {
    const id = ++seq.current;
    void load().then(
      (r) => {
        if (id === seq.current) setResult(r);
      },
      () => {
        if (id === seq.current) setResult({ state: "offline" });
      },
    );
  }, [load]);

  useEffect(() => {
    if (api === "checking") return;
    if (api === "offline") {
      seq.current++;
      const t = setTimeout(() => setResult({ state: "offline" }), 0);
      return () => clearTimeout(t);
    }
    reload();
  }, [api, reload]);

  return { result, reload };
}
