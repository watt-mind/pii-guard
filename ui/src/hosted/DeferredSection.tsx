import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "../components/ui";

/** Keep anchors and reserved space in the document while heavier content waits for proximity. */
export function DeferredSection({ anchor, className, children }: { anchor: string; className: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(() => typeof IntersectionObserver === "undefined" || location.hash === `#${anchor}`);
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
  return <div ref={ref} className={className}>{ready ? <Suspense fallback={placeholder}>{children}</Suspense> : placeholder}</div>;
}
