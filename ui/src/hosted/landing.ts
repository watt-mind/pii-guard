import type { EntityType } from "../api/types";
import { modelLabel } from "../lib/entities";
import { alignLoose, alignRestored, tokenize, type RestoredSegment } from "../lib/placeholders";
import type { Account } from "./api";

const PROVIDER_LABEL: Record<string, string> = { meta: "Meta", openai: "OpenAI", fireworks: "Fireworks", openrouter: "OpenRouter", custom: "Custom HTTPS endpoint" };
/** A provider id as a person reads it ("openai" -> "OpenAI"). */
export const providerLabel = (provider: string) => PROVIDER_LABEL[provider] ?? provider;

/** A model id as a person reads it: "muse-spark-1.3" -> "Muse Spark 1.3 (Meta API)", "Llama-4-Maverick-17B-…" -> "Llama 4 Maverick". */
export function friendlyModel(model: string) {
  const llama = /^(?:.*\/)?Llama-(\d+(?:\.\d+)?)-([A-Za-z]+)/i.exec(model);
  return llama ? `Llama ${llama[1]} ${llama[2]}` : modelLabel(model);
}

/** A model id by its name alone: "muse-spark-1.3" -> "Muse Spark 1.3" (no provider note). */
export const modelName = (model: string) => friendlyModel(model).replace(/ \([^)]*\)$/, "");

/** "resets in 6 h", from the account's reset time; null when the server didn't send one. */
export function resetsIn(account: Account, now = Date.now()) {
  const reset = new Date(account.usage.resets_at).getTime();
  if (Number.isNaN(reset)) return null;
  const minutes = Math.max(0, Math.round((reset - now) / 60_000));
  return `in ${minutes >= 60 ? `${Math.round(minutes / 60)} h` : `${Math.max(1, minutes)} min`}`;
}

/** "4 of 5 free runs left today", or null without a daily limit. */
export function runsLeft(account: Account) {
  const perDay = account.limits.requests_per_day;
  if (typeof perDay !== "number") return null;
  return `${Math.max(0, perDay - account.usage.requests_today)} of ${perDay} ${account.authenticated ? "runs" : "free runs"} left today`;
}

/** "0 of 5 free runs today · resets in 6 h", from the account's usage and limit. */
export function usageLine(account: Account, now = Date.now()) {
  const perDay = account.limits.requests_per_day;
  const used = account.usage.requests_today;
  const runs = typeof perDay === "number" ? `${used} of ${perDay} ${account.authenticated ? "runs" : "free runs"} today` : `${used} ${used === 1 ? "run" : "runs"} today`;
  const reset = resetsIn(account, now);
  return reset ? `${runs} · resets ${reset}` : runs;
}

/** Entity types found in a masked text, with how many distinct values each, in first-seen order. */
export function placeholderCounts(masked: string): [EntityType | null, string, number][] {
  const counts = new Map<string, { type: EntityType | null; n: number }>();
  const seen = new Set<string>();
  for (const t of tokenize(masked)) if (t.kind === "placeholder" && !seen.has(t.text)) {
    seen.add(t.text);
    const key = t.entityType ?? "UNKNOWN";
    const prev = counts.get(key);
    counts.set(key, { type: t.entityType, n: (prev?.n ?? 0) + 1 });
  }
  return [...counts.entries()].map(([key, v]) => [v.type, key, v.n]);
}

/**
 * The answer with the real values put back, as segments for `RestoredText`. The values found in
 * your text (masked vs original) settle where each value ends, e.g. an email followed by a full stop.
 */
export function restoredSegments({ answer, restored, masked, original }: { answer: string; restored: string; masked: string; original: string }): RestoredSegment[] {
  const values = new Map<string, string>();
  for (const s of alignLoose(masked, original) ?? []) if (s.kind === "restored") values.set(s.placeholder, s.text);
  return alignRestored(answer, restored, [], (placeholder) => values.get(placeholder)) ?? alignLoose(answer, restored) ?? [{ kind: "text", text: restored }];
}
