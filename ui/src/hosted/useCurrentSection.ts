import { useEffect, useState } from "react";

/**
 * The id of the landing section the reader is in, for the sticky nav's marker (L1 carryover 8):
 * the last of `ids` whose top has passed a line a little below the sticky header. Null above
 * the first one and below the last. Re-picked on scroll and resize, once per frame.
 */
export function useCurrentSection(ids: readonly string[]): string | null {
  const [current, setCurrent] = useState<string | null>(null);
  const key = ids.join(" ");
  useEffect(() => {
    const sections = key.split(" ").map((id) => document.getElementById(id)).filter((el): el is HTMLElement => el !== null);
    if (!sections.length) return;
    const pick = () => {
      const line = 120;
      let found: string | null = null;
      for (const el of sections) if (el.getBoundingClientRect().top <= line) found = el.id;
      // Past the end of the last section (the footer): no marker.
      const last = sections[sections.length - 1]!;
      if (found === last.id && last.getBoundingClientRect().bottom < line) found = null;
      setCurrent(found);
    };
    let frame = 0;
    const schedule = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; pick(); }); };
    addEventListener("scroll", schedule, { passive: true });
    addEventListener("resize", schedule, { passive: true });
    pick();
    return () => { removeEventListener("scroll", schedule); removeEventListener("resize", schedule); cancelAnimationFrame(frame); };
  }, [key]);
  return current;
}
