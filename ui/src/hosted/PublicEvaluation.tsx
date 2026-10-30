import { lazy, Suspense, useEffect, type MouseEvent } from "react";
import { PublicHeader } from "./PublicHeader";
import { loginFor } from "./consoleLink";

// The landing doesn't download the benchmark screen until someone opens it (LAB-1450).
const Benchmarks = lazy(() => import("../screens/Benchmarks").then((m) => ({ default: m.Benchmarks })));

/**
 * The Evaluation page for a visitor who isn't signed in (LAB-1533). It shows the benchmark
 * results bundled with the page as static files (the same data as docs/benchmarks.md), so it
 * calls no API and shows nothing of any account. "Sign in" returns to Evaluation after authentication.
 */
export function PublicEvaluation({ loginUrl, hash }: { loginUrl: string; hash: string }) {
  // Opened from a link on the public page: start at the top, not at that page's scroll position.
  useEffect(() => {
    globalThis.scrollTo?.(0, 0);
  }, []);
  // The hash routes this page, so the skip link moves focus without touching it.
  function skip(e: MouseEvent<HTMLAnchorElement>) {
    e.preventDefault();
    document.getElementById("main")?.focus();
  }

  return (
    <div className="public-teal-theme min-h-dvh bg-canvas text-sm text-ink">
      <a href="#main" onClick={skip} className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-40 focus:rounded focus:bg-surface focus:px-3 focus:py-1">
        Skip to content
      </a>
      <PublicHeader current="results" accountHref={loginFor(loginUrl, hash)} />
      <main id="main" tabIndex={-1} className="mx-auto min-h-screen max-w-[1280px] px-4 py-6 focus:outline-none sm:px-6 sm:py-8 lg:px-10">
        <Suspense fallback={<p role="status" className="text-muted">Loading the benchmarks…</p>}>
          <Benchmarks />
        </Suspense>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-4 px-4 py-6 sm:px-6 lg:px-10">
          <p className="text-xs text-muted">Published benchmark results, the same for every visitor. No account data is shown here.</p>
        </div>
      </footer>
    </div>
  );
}
