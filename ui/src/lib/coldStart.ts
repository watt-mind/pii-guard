/**
 * How long the console keeps retrying a server that doesn't answer yet, before it falls back.
 *
 * Hosted scales to zero: the first load after an idle spell waits for a cold start (container
 * plus the NER model), tens of seconds. These waits (about 37 s in all) cover that, and a
 * deploy's revision swap, before the Overview switches to recorded traffic or setup warns
 * (LAB-1703, LAB-1710).
 */
export const COLD_START_RETRY_MS: readonly number[] = [2000, 5000, 10000, 20000];
