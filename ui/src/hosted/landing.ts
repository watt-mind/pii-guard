import type { EntityType } from "../api/types";
import { modelLabel } from "../lib/entities";
import { tokenize } from "../lib/placeholders";
import type { Account } from "./api";

/** A model id as a person reads it: "muse-spark-1.3" -> "Muse Spark 1.3 (Meta API)", "Llama-4-Maverick-17B-…" -> "Llama 4 Maverick". */
export function friendlyModel(model: string) {
  const llama = /^(?:.*\/)?Llama-(\d+(?:\.\d+)?)-([A-Za-z]+)/i.exec(model);
  return llama ? `Llama ${llama[1]} ${llama[2]}` : modelLabel(model);
}

/** "0 of 5 free runs today · resets in 6 h", from the account's usage and limit. */
export function usageLine(account: Account, now = Date.now()) {
  const perDay = account.limits.requests_per_day;
  const used = account.usage.requests_today;
  const runs = typeof perDay === "number" ? `${used} of ${perDay} ${account.authenticated ? "runs" : "free runs"} today` : `${used} ${used === 1 ? "run" : "runs"} today`;
  const reset = new Date(account.usage.resets_at).getTime();
  if (Number.isNaN(reset)) return runs;
  const minutes = Math.max(0, Math.round((reset - now) / 60_000));
  return `${runs} · resets in ${minutes >= 60 ? `${Math.round(minutes / 60)} h` : `${Math.max(1, minutes)} min`}`;
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
