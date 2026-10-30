import { useEffect, type ReactNode } from "react";

import { SOURCE } from "./session";
import type { PublicPage } from "./publicRoutes";

export type PublicSections = Record<"imagePreview" | "hero" | "why" | "demo" | "meta" | "europe" | "images" | "results" | "how" | "data" | "privacy" | "account", ReactNode>;
const PAGE_COPY = {
  demo: ["Interactive demo", "Start with a recorded fictional example. Run it live when the service is available, or explore how images are masked."],
  trust: ["Privacy & trust", "See who receives your data, how long the hosted preview keeps it, and what masking cannot guarantee."],
  technical: ["Technical overview", "Understand the detection approach, each model’s role, and the EU context for deploying a privacy gateway."],
} as const;

const CONTENTS = {
  demo: [{ href: "#run", label: "Text walkthrough" }, { href: "#images", label: "Image masking" }],
  trust: [{ href: "#data", label: "Data handling" }, { href: "#privacy", label: "Limits & caveats" }],
  technical: [{ href: "#why", label: "Approach" }, { href: "#meta", label: "Model roles" }, { href: "#europe", label: "EU context" }],
} as const;
const NEXT = {
  demo: [{ href: "#trust", label: "Understand Privacy & trust", description: "Processing, retention and detection limits." }, { href: "#technical", label: "Explore the technical overview", description: "See the models and the approach behind the flow." }],
  trust: [{ href: "#demo", label: "Inspect the recorded demo", description: "Check the masked request and restored answer." }, { href: `${SOURCE}#try-it`, label: "Review self-hosting options", description: "Choose the guard, detectors and provider you operate." }],
  technical: [{ href: "#evaluation", label: "Explore the benchmarks", description: "Inspect datasets, comparison tools and committed runs." }, { href: `${SOURCE}/blob/develop/docs/integrations/README.md`, label: "Read the integration guide", description: "Connect an OpenAI-compatible client to the gateway." }],
} as const;

/** Public journeys share a shell and state; only the selected page’s content is mounted. */
export function PublicPageContent({ page, hash, sections }: { page: PublicPage; hash: string; sections: PublicSections }) {
  useEffect(() => {
    const from = document.activeElement;
    const frame = requestAnimationFrame(() => {
      if (document.activeElement !== from && document.activeElement !== document.body) return;
      const canonical = ["#demo", "#trust", "#technical", "#site", ""].includes(hash);
      const anchor = canonical ? null : document.getElementById(hash === "#run" ? "demo" : hash.slice(1));
      if (anchor) {
        anchor.scrollIntoView({ block: "start" });
        const heading = anchor.querySelector<HTMLElement>("h2, h3");
        if (heading && !heading.hasAttribute("tabindex")) heading.tabIndex = -1;
        heading?.focus({ preventScroll: true });
      } else {
        globalThis.scrollTo?.(0, 0);
        (document.getElementById("public-page-heading") ?? document.getElementById("main"))?.focus({ preventScroll: true });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [page, hash]);
  return <>
    {page !== "home" && <div className="public-page-intro space-y-3 pt-8 sm:pt-12">
      <a href="#site" className="inline-flex min-h-11 items-center rounded-sm text-muted underline underline-offset-4 hover:text-ink">← Back to the overview</a>
      <h1 id="public-page-heading" tabIndex={-1} className="text-3xl font-medium text-ink focus:outline-none sm:text-4xl">{PAGE_COPY[page][0]}</h1>
      <p className="max-w-2xl text-base text-muted">{PAGE_COPY[page][1]}</p>
      <nav aria-label="On this page" className="public-page-contents">
        <span>On this page</span>
        {CONTENTS[page].map((item) => <a key={item.href} href={item.href} aria-current={hash === item.href ? "location" : undefined}>{item.label}</a>)}
      </nav>
    </div>}
    {page === "home" && <>{sections.hero}{sections.imagePreview}{sections.how}{sections.results}{sections.account}</>}
    {page === "demo" && <>{sections.demo}{sections.images}</>}
    {page === "trust" && <>{sections.data}{sections.privacy}</>}
    {page === "technical" && <>{sections.why}{sections.meta}{sections.europe}</>}
    {page !== "home" && <aside aria-labelledby="public-next-heading" className="public-page-next">
      <h2 id="public-next-heading">Continue exploring</h2>
      <div>{NEXT[page].map((item) => <a key={item.href} href={item.href}>
        <span>{item.label}{item.href.startsWith("https:") && <span aria-hidden="true"> ↗</span>}</span>
        <span>{item.description}</span>
      </a>)}</div>
    </aside>}
  </>;
}
