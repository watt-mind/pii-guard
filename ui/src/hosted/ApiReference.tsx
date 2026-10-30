import { lazy, Suspense, useEffect, useMemo, useState, useSyncExternalStore, type MouseEvent } from "react";
import specUrl from "../../../docs/openapi.json?url";
import { ButtonLink } from "../components/ui";
import type { Endpoint, ProjectList } from "../projects/api";
import { localRequest } from "../projects/request";
import { getSelectedProject, useSelectedEndpoint } from "../projects/selection";
import { hostedServers } from "./apiConfig";
import { SOURCE } from "./session";
import { PublicHeader } from "./PublicHeader";

// The renderer is heavy and only this page needs it: the landing never downloads it, and only
// the hosted build has it (the local build, bundled into the wheel, links to the hosted page).
const ScalarReference = import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? lazy(() => import("./ScalarReference")) : null;
const HOSTED_REFERENCE = "https://guard.watt-mind.com/#api";

const GUIDE = `${SOURCE}/blob/develop/docs/api.md`;
const CONTRACTS = `${SOURCE}/blob/develop/docs/contracts.md#rest-api-implemented`;

// `html.dark` is set by useTheme (and by index.html before the first paint).
const subscribeDark = (cb: () => void) => {
  const observer = new MutationObserver(cb);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
};
const isDark = () => document.documentElement.classList.contains("dark");

/**
 * With no endpoint picked in the header, the current project's first enabled endpoint, so the
 * examples carry a real endpoint id rather than `your-endpoint-id` (LAB-1629).
 */
function useFallbackEndpoint(enabled: boolean): string | null {
  const [fallback, setFallback] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    (async () => {
      const list = await localRequest<ProjectList>("/v1/projects");
      const projectId = getSelectedProject() ?? list.default_project_id ?? list.projects?.[0]?.id;
      if (!projectId) return null;
      const data = await localRequest<{ endpoints: Endpoint[] }>(`/v1/projects/${encodeURIComponent(projectId)}/endpoints`);
      return (Array.isArray(data.endpoints) ? data.endpoints : []).find((e) => e.enabled)?.id ?? null;
    })().then(
      (id) => live && setFallback(id),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [enabled]);
  return fallback;
}

/**
 * The public, read-only API reference (LAB-1586): the committed docs/openapi.json, bundled with
 * the page and rendered by Scalar with no "try it". It calls no API, so it is the same for every
 * visitor, signed in or not. The server's own /docs and /openapi.json stay off in production.
 */
export function ApiReference(props: { consoleHref: string; embedded?: false } | { embedded: true; consoleHref?: undefined }) {
  const dark = useSyncExternalStore(subscribeDark, isDark, () => false);
  // In the console the examples default to this service, then the endpoint the header picked (LAB-1626).
  const picked = useSelectedEndpoint();
  const fallback = useFallbackEndpoint(Boolean(props.embedded) && picked === null);
  const endpoint = picked ?? fallback;
  const servers = useMemo(() => (props.embedded ? hostedServers(globalThis.location?.origin ?? "", endpoint) : undefined), [props.embedded, endpoint]);
  useEffect(() => {
    // Opened from a link further down another page: start at the top.
    if (globalThis.location?.hash === "#api") globalThis.scrollTo?.(0, 0);
  }, []);
  function skip(e: MouseEvent<HTMLAnchorElement>) {
    e.preventDefault();
    document.getElementById("main")?.focus();
  }
  const intro = (
    <section aria-labelledby="api-title" className={props.embedded ? "" : "mx-auto max-w-[1280px] px-4 py-8 sm:px-6 sm:py-10 lg:px-10"}>
      {!props.embedded && (
        <p className="font-mono text-xs text-muted">Developer docs · Read-only reference</p>
      )}
      <h1 id="api-title" className={props.embedded ? "text-2xl font-medium text-balance text-ink" : "mt-4 text-3xl font-medium tracking-tight sm:text-4xl"}>API reference</h1>
      <p className={props.embedded ? "mt-2 max-w-3xl text-sm text-pretty text-muted sm:text-base" : "mt-3 max-w-[68ch] leading-relaxed text-muted"}>
        {props.embedded ? (
          <>
            The OpenAI-compatible gateway and the masking routes. The examples use this service; for your own client pick your endpoint under Server, its base URL ends in{" "}
            <code className="font-mono text-ink">/v1</code>. This page is read-only and sends no requests.
          </>
        ) : (
          <>
            The OpenAI-compatible gateway and the masking routes. Point an OpenAI SDK at the guard&apos;s <code className="font-mono text-ink">/v1</code> base URL; the provider only sees placeholders.
            This page is read-only and sends no requests.
          </>
        )}
      </p>
      <nav aria-label="API resources" className="mt-5 flex flex-wrap gap-2">
        <ButtonLink size="sm" href={GUIDE}>Guide: quickstart, keys, sessions ↗</ButtonLink>
        <ButtonLink size="sm" href={CONTRACTS}>Full contract ↗</ButtonLink>
        <ButtonLink size="sm" href={specUrl} download="pii-guard-openapi.json">openapi.json</ButtonLink>
      </nav>
    </section>
  );
  const reference = (
    <div className={props.embedded ? "api-reference-frame mt-6 min-h-dvh border-t border-line" : "api-reference-frame mx-auto min-h-dvh max-w-[1280px] border-t border-line"}>
      {ScalarReference ? (
        <Suspense fallback={<p role="status" className="mx-auto max-w-[1280px] px-4 py-6 text-muted sm:px-6 lg:px-10">Loading the reference…</p>}>
          <ScalarReference specUrl={specUrl} dark={dark} servers={servers} endpoint={props.embedded ? endpoint : null} />
        </Suspense>
      ) : (
        <p className="mx-auto max-w-[1280px] px-4 py-6 text-muted sm:px-6 lg:px-10">
          The rendered reference is on the hosted site: <a className="underline underline-offset-4 hover:text-ink" href={HOSTED_REFERENCE}>guard.watt-mind.com/#api ↗</a>
        </p>
      )}
    </div>
  );
  if (props.embedded) {
    return (
      <div className="pii-guard-api text-sm text-ink">
        {intro}
        {reference}
      </div>
    );
  }

  return (
    <div className="pii-guard-api public-teal-theme min-h-dvh bg-canvas text-sm text-ink">
      <a href="#main" onClick={skip} className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-40 focus:rounded focus:bg-surface focus:px-3 focus:py-1">
        Skip to content
      </a>
      <PublicHeader current="api" accountHref={props.consoleHref} />
      {/* With Scalar, its own <main> is the page's main; a nested one fails axe (LAB-1640). */}
      <div id="main" role={ScalarReference ? undefined : "main"} tabIndex={-1} className="focus:outline-none">
        {intro}
        {reference}
      </div>
      <footer className="public-footer border-t border-line">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-4 px-4 py-6 sm:px-6 lg:px-10">
          <p className="text-xs text-muted">Generated from the code and checked in CI. Every example is fictional.</p>
          <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
            <a href="#site">Home</a>
            <a href="#evaluation">Benchmarks</a>
            <a href="#api" aria-current="page">API reference</a>
            <a href={GUIDE}>API guide ↗</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
