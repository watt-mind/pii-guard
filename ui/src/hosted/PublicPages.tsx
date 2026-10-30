import { useEffect, type ReactNode } from "react";

import type { PublicPage } from "./publicRoutes";

export type PublicSections = Record<"imagePreview" | "hero" | "why" | "demo" | "meta" | "europe" | "images" | "results" | "how" | "data" | "privacy" | "account", ReactNode>;
const PAGE_COPY = {
  demo: ["Interactive demo", "Follow a request through PII Guard, then explore image masking."],
  trust: ["Privacy & trust", "Understand the hosted preview’s data handling, retention and limits before you use it."],
  technical: ["Technical overview", "The models, architecture and EU context behind PII Guard."],
} as const;

/** Public journeys share a shell and state; only the selected page’s content is mounted. */
export function PublicPageContent({ page, hash, sections }: { page: PublicPage; hash: string; sections: PublicSections }) {
  useEffect(() => {
    const from = document.activeElement;
    const frame = requestAnimationFrame(() => {
      if (document.activeElement !== from && document.activeElement !== document.body) return;
      const canonical = ["#demo", "#trust", "#technical", "#site", ""].includes(hash);
      const anchor = canonical ? null : document.getElementById(hash.slice(1));
      if (anchor) {
        anchor.scrollIntoView({ block: "start" });
        anchor.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
      } else {
        globalThis.scrollTo?.(0, 0);
        (document.getElementById("public-page-heading") ?? document.getElementById("main"))?.focus({ preventScroll: true });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [page, hash]);
  return <>
    {page !== "home" && <div className="space-y-3 pt-10 sm:pt-14">
      <a href="#site" className="inline-flex min-h-11 items-center rounded-sm text-muted underline underline-offset-4 hover:text-ink">← Back to the overview</a>
      <h1 id="public-page-heading" tabIndex={-1} className="text-3xl font-medium text-ink focus:outline-none sm:text-4xl">{PAGE_COPY[page][0]}</h1>
      <p className="max-w-2xl text-base text-muted">{PAGE_COPY[page][1]}</p>
    </div>}
    {page === "home" && <>{sections.hero}{sections.imagePreview}{sections.how}{sections.results}{sections.account}</>}
    {page === "demo" && <>{sections.demo}{sections.images}</>}
    {page === "trust" && <>{sections.data}{sections.privacy}</>}
    {page === "technical" && <>{sections.why}{sections.meta}{sections.europe}</>}
  </>;
}
