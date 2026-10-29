// Per-viewer conveniences only (theme, mode). Storage can be blocked; never rely on it.

export function readPref(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(`pii-guard:${key}`) ?? null;
  } catch {
    return null;
  }
}

export function writePref(key: string, value: string): void {
  try {
    globalThis.localStorage?.setItem(`pii-guard:${key}`, value);
  } catch {
    // ignore
  }
}
