import { useEffect, useState } from "react";
import { readPref, writePref } from "../lib/storage";

export type ThemePref = "system" | "light" | "dark";

function systemDark(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

export function useTheme(): [ThemePref, (t: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(() => {
    const stored = readPref("theme");
    // Light is the local console's first look; the hosted build follows the system (index.html).
    // "system" is kept when someone picked it.
    const fallback: ThemePref = import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? "system" : "light";
    return stored === "light" || stored === "dark" || stored === "system" ? stored : fallback;
  });

  useEffect(() => {
    const apply = () => {
      const dark = pref === "dark" || (pref === "system" && systemDark());
      document.documentElement.classList.toggle("dark", dark);
    };
    apply();
    writePref("theme", pref);
    if (pref !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [pref]);

  return [pref, setPref];
}
