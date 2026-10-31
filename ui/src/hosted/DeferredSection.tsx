import { Component, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { errorCopy } from "../lib/errorCopy";
import { Button, Notice } from "../components/ui";

/**
 * A rejected lazy import must not leave a permanent silent placeholder. The first Retry
 * remounts the section, which recovers transient render failures; a rejected chunk
 * download stays rejected (React caches the lazy payload), so a second failure offers a
 * page reload instead of another doomed remount.
 */
class DeferredLoadBoundary extends Component<
  { retried: boolean; onRetry: () => void; reload: () => void; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const copy = errorCopy("section_load_failed");
    return (
      <Notice
        tone="danger"
        live
        title={copy.title}
        data-error-kind={copy.kind}
        action={this.props.retried
          ? <Button size="sm" onClick={this.props.reload}>Reload page</Button>
          : <Button size="sm" onClick={this.props.onRetry}>Retry</Button>}
      >
        <p>{copy.body}</p>
      </Notice>
    );
  }
}

/** Keep anchors and reserved space in the document while heavier content waits for proximity. */
export function DeferredSection({ anchor, className, children, reload }: { anchor: string; className: string; children: ReactNode; reload?: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(() => typeof IntersectionObserver === "undefined" || location.hash === `#${anchor}`);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (ready) return;
    const showAnchor = () => { if (location.hash === `#${anchor}`) setReady(true); };
    addEventListener("hashchange", showAnchor);
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setReady(true);
    }, { rootMargin: "300px" });
    if (ref.current) observer?.observe(ref.current);
    return () => { observer?.disconnect(); removeEventListener("hashchange", showAnchor); };
  }, [anchor, ready]);
  const label = anchor === "images" ? "image example" : "comparison chart";
  const placeholder = <div className={className}>{ready
    ? <span role="status" className="sr-only">Loading {label}…</span>
    : <Button onClick={() => setReady(true)}>Load {label}</Button>}</div>;
  const doReload = reload ?? (() => window.location.reload());
  return <div ref={ref} className={className}>{ready
    ? <DeferredLoadBoundary key={attempt} retried={attempt > 0} onRetry={() => setAttempt((n) => n + 1)} reload={doReload}>
        <Suspense fallback={placeholder}>{children}</Suspense>
      </DeferredLoadBoundary>
    : placeholder}</div>;
}
