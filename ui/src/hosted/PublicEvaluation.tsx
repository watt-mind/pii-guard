import { lazy, Suspense, useEffect, type MouseEvent } from "react";
import { ButtonLink, Logo, ThemeToggle } from "../components/ui";
import { useTheme } from "../hooks/useTheme";
import { loginFor } from "./consoleLink";

// The landing doesn't download the benchmark screen until someone opens it (LAB-1450).
const Benchmarks = lazy(() => import("../screens/Benchmarks").then((m) => ({ default: m.Benchmarks })));

/**
 * The Evaluation page for a visitor who isn't signed in (LAB-1533). It shows the benchmark
 * results bundled with the page as static files (the same data as docs/benchmarks.md), so it
 * calls no API and shows nothing of any account. "Console" signs in and returns to Evaluation.
 */
export function PublicEvaluation({ loginUrl, hash }: { loginUrl: string; hash: string }) {
  const [theme, setTheme] = useTheme();
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
    <div className="min-h-dvh bg-canvas text-sm text-ink">
      <a href="#main" onClick={skip} className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-40 focus:rounded focus:bg-surface focus:px-3 focus:py-1">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 bg-canvas">
        <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-2 px-4 sm:px-6 lg:h-12 lg:px-10">
          <a href="#" className="flex h-9 shrink-0 items-center gap-2.5 rounded-sm text-base font-medium text-ink">
            <Logo />
            PII Guard
          </a>
          <nav aria-label="Main navigation" className="flex min-w-0 items-center gap-3 sm:gap-5">
            <a className="hidden text-muted hover:text-ink sm:inline" href="#demo">Demo</a>
            <a className="hidden text-muted hover:text-ink sm:inline" href="#results">Results</a>
            <span aria-current="page" className="hidden text-ink underline decoration-guard decoration-2 underline-offset-[6px] sm:inline">Evaluation</span>
            <a className="inline-flex min-h-9 items-center gap-1.5 whitespace-nowrap text-muted hover:text-ink pointer-coarse:min-h-11" href="#api"><span>API</span></a>
            <ButtonLink href={loginFor(loginUrl, hash)}>Console</ButtonLink>
          </nav>
        </div>
        <div aria-hidden="true" className="header-hairline" />
      </header>
      <main id="main" tabIndex={-1} className="mx-auto min-h-screen max-w-[1280px] px-4 py-6 focus:outline-none sm:px-6 sm:py-8 lg:px-10">
        <Suspense fallback={<p role="status" className="text-muted">Loading the benchmarks…</p>}>
          <Benchmarks />
        </Suspense>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-4 px-4 py-6 sm:px-6 lg:px-10">
          <p className="text-xs text-muted">Published benchmark results, the same for every visitor. No account data is shown here.</p>
          <div className="flex items-center gap-5">
            <a className="inline-flex min-h-9 items-center gap-1.5 whitespace-nowrap text-xs text-muted hover:text-ink pointer-coarse:min-h-11" href="#api">API reference</a>
            <ThemeToggle theme={theme} onTheme={setTheme} />
          </div>
        </div>
      </footer>
    </div>
  );
}
