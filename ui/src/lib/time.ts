/**
 * One date and time format for the whole console (LAB-1619): EU English with a 24-hour clock,
 * never the browser's locale. "14:05:09", "14:05", "30 Oct 2026, 14:05".
 */
const LOCALE = "en-GB";

const valid = (d: Date) => !Number.isNaN(d.getTime());

/** A clock time with seconds, "14:05:09"; the input back unchanged when it isn't a date. */
export function clockTime(value: string | number): string {
  const d = new Date(value);
  return valid(d) ? d.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : String(value);
}

/** A clock time without seconds, "14:05" (chart axes). */
export function clockMinutes(value: string | number): string {
  const d = new Date(value);
  return valid(d) ? d.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit", hour12: false }) : String(value);
}

/** A date with its time, "30 Oct 2026, 14:05"; "not available" when missing or invalid. */
export function dateTime(value: string | undefined | null): string {
  if (!value) return "not available";
  const d = new Date(value);
  return valid(d) ? d.toLocaleString(LOCALE, { dateStyle: "medium", timeStyle: "short", hour12: false }) : "not available";
}

/** How long ago, "just now", "40 s ago", "12 min ago", "3 h ago", "2 h 5 min ago", "4 days ago". */
export function relativeTime(value: string | null | undefined, now: number = Date.now()): string {
  if (!value) return "not recorded";
  const t = Date.parse(value);
  if (Number.isNaN(t)) return "not recorded";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86_400) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return m ? `${h} h ${m} min ago` : `${h} h ago`;
  }
  const days = Math.floor(s / 86_400);
  return `${days} ${days === 1 ? "day" : "days"} ago`;
}
