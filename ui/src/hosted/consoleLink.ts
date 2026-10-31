// Where a signed-out console deep link points (LAB-1519).
import { LEGACY_HASHES, SECTIONS, type Section } from "../lib/routes";
import { SITE_HASHES } from "./session";

const SECTION_IDS = new Set<string>(SECTIONS.map((s) => s.id));

/** The console section a hash opens (`#logs`, `#playground/chat`, `#cli-auth`, the old `#traffic`), or null for the public page's anchors and anything else. */
export function consoleSectionOf(hash: string): Section | null {
  if (SITE_HASHES.has(hash)) return null;
  if (/^#cli-auth(?:\?[^#]*)?$/.test(hash)) return "connect";
  const legacy = LEGACY_HASHES[hash];
  if (legacy) return legacy.section;
  const m = /^#([a-z]+)(?:\/[a-z]+)?$/.exec(hash);
  return m && SECTION_IDS.has(m[1]!) ? (m[1] as Section) : null;
}

/** The server's Google sign-in URL, returning to `hash` instead of the default Overview. */
export function loginFor(loginUrl: string, hash: string): string {
  try {
    const url = new URL(loginUrl, "https://pii-guard.invalid");
    url.searchParams.set("post_login_redirect_uri", `/${hash}`);
    return `${url.pathname}${url.search}`;
  } catch {
    return loginUrl;
  }
}
