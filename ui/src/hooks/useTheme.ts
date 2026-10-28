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
    // Light is the console's first look; "system" is kept when someone picked it.
    return stored === "light" || stored === "dark" || stored === "system" ? stored : "light";
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
