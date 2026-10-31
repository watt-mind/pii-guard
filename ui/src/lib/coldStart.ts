/**
 * How long the console keeps retrying a server that doesn't answer yet, before it falls back.
 *
 * Hosted scales to zero: the first load after an idle spell waits for a cold start (container
 * plus the NER model), tens of seconds. These waits (about 37 s in all) cover that, and a
 * deploy's revision swap, before the Overview switches to recorded traffic or setup warns
 * (LAB-1703, LAB-1710).
 */
export const COLD_START_RETRY_MS: readonly number[] = [2000, 5000, 10000, 20000];

/**
 * The longest one console read may take before it counts as failed and the retries above take over.
 * A request held open by a dropped connection or a replica that went away mid-swap would otherwise
 * wait out the requester's 180 s limit on every attempt (LAB-1729).
 */
export const READ_TIMEOUT_MS = 15000;

/** `promise`, or a rejection once `ms` pass first. */
export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), ms);
    promise.then((value) => { clearTimeout(timer); resolve(value); }, (error: unknown) => { clearTimeout(timer); reject(error); });
  });
}
