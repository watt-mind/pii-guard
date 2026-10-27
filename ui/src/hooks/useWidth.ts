import { useCallback, useEffect, useState } from "react";

/** The width of a chart's container in CSS pixels, so SVG charts are drawn at their real size. */
export function useWidth(fallback = 720) {
  // A callback ref: the observer attaches whenever the chart's container mounts, even if the
  // first render returned the empty state.
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  const ref = useCallback((node: HTMLDivElement | null) => {
    setEl(node);
    if (node && node.clientWidth > 0) setWidth(Math.floor(node.clientWidth)); // first paint, before any resize event
  }, []);
  return [ref, width] as const;
}
