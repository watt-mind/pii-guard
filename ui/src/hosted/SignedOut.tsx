import { useEffect, useRef, type MouseEvent } from "react";
import { ButtonLink } from "../components/ui";
import { SECTIONS, type Section } from "../lib/routes";
import { PublicHeader } from "./PublicHeader";
import { loginFor } from "./consoleLink";

/** What a signed-out visitor is told about each console screen, and where the public page shows it. */
const SCREENS: Record<Section, { what: string; noun: string; site: { hash: string; label: string } }> = {
  overview: { noun: "your overview", what: "What the guard protected on your endpoints: requests, masked values and blocked calls, counted from the traffic log.", site: { hash: "#how", label: "See how it works" } },
  playground: { noun: "the playground", what: "Text, chat and images run through your own endpoint and policy, with what the model saw beside what you got back.", site: { hash: "#demo", label: "Try the demo without an account" } },
  logs: { noun: "your logs", what: "Every request your endpoints handled: what was masked, the latency, and the outbound check result.", site: { hash: "#demo", label: "Try the demo without an account" } },
  vault: { noun: "your vault", what: "The sessions behind your requests and their placeholders, until they expire.", site: { hash: "#data", label: "See what happens to your data" } },
  projects: { noun: "your projects", what: "Your gateway endpoints and the versioned policies each one runs.", site: { hash: "#how", label: "See how it works" } },
  connect: { noun: "your connection snippets", what: "Ready-to-copy settings that point your agent or client at your own gateway endpoint.", site: { hash: "#how", label: "See how it works" } },
  policy: { noun: "your policies", what: "The mode, the detectors and how each kind of personal data is handled.", site: { hash: "#how", label: "See how it works" } },
  evaluation: { noun: "the benchmarks", what: "Leak rates and detection time on public and fictional test sets.", site: { hash: "#results", label: "See the results" } },
};

/**
 * A console deep link opened without a session: one honest panel instead of an empty console
 * (LAB-1519). Never signed in this visit: "Sign in to see…"; signed in, then the session ended:
 * "Your session ended". Sign-in returns to the same screen.
 */
export function SignedOutConsole({ section, hash, loginUrl, expired }: { section: Section; hash: string; loginUrl: string; expired: boolean }) {
  const screen = SCREENS[section];
  const label = SECTIONS.find((s) => s.id === section)!.label;
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [section, expired]);

  // The public page renders only once the hash names one of its anchors, so scroll after it has.
  function toSite(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    globalThis.location.hash = screen.site.hash;
    requestAnimationFrame(() => {
      const target = document.getElementById(screen.site.hash.slice(1));
      target?.scrollIntoView({ block: "start" });
      document.getElementById(`${screen.site.hash.slice(1)}-heading`)?.focus({ preventScroll: true });
    });
  }

  return (
    <div className="public-teal-theme flex min-h-dvh flex-col bg-canvas text-sm text-ink">
      <PublicHeader accountHref={loginFor(loginUrl, hash)} />
      <main id="main" className="mx-auto flex w-full max-w-[1280px] flex-1 items-start justify-center px-4 py-12 sm:px-6 sm:py-20 lg:px-10">
        <section aria-labelledby="signed-out-heading" className="w-full max-w-xl rounded-xl border border-line bg-surface p-6 sm:p-8">
          <p className="font-mono text-xs text-guard">Console · {label}</p>
          <h1 id="signed-out-heading" ref={heading} tabIndex={-1} className="mt-2 text-2xl font-medium text-balance text-ink focus:outline-none">
            {expired ? "Your session ended" : `Sign in to see ${screen.noun}`}
          </h1>
          <p className="mt-3 text-pretty text-muted">
            {expired ? `Sign in again to get back to ${label}. ` : ""}
            {screen.what}
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <ButtonLink variant="primary" href={loginFor(loginUrl, hash)}>
              {expired ? "Sign in again with Google" : "Sign in with Google"}
            </ButtonLink>
            <ButtonLink href={screen.site.hash} onClick={toSite}>
              {screen.site.label}
            </ButtonLink>
          </div>
          <p className="mt-6 border-t border-line pt-4 text-xs text-muted">
            {expired ? "You'll come back to this screen after signing in." : "Your first sign-in sets up a private gateway endpoint of your own. You'll come back to this screen afterwards."}
          </p>
        </section>
      </main>
    </div>
  );
}
