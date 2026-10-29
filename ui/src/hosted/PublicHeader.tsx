import { useEffect, useId, useRef, type MouseEvent } from "react";
import { ButtonLink, Logo } from "../components/ui";
import { SOURCE } from "./session";
import "./publicNavigation.css";

const PRIMARY = [{ href: "#demo", label: "Demo" }, { href: "#how", label: "How it works" }, { href: "#results", label: "Benchmarks" }];
const RESOURCES = [
  { href: "#meta", label: "Model details" },
  { href: "#images", label: "Image masking" },
  { href: "#data", label: "Privacy" },
  { href: "#privacy", label: "Privacy limits" },
  { href: "#europe", label: "Why Europe" },
  { href: "#account", label: "Get started" },
  { href: `${SOURCE}#try-it`, label: "Self-hosting guide" },
];

/** Plain navigation disclosure: normal Tab order, no application-menu focus trap. */
export function PublicHeader({ current, accountHref, signedIn = false }: { current?: string | null; accountHref: string; signedIn?: boolean }) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  const panelId = useId();
  useEffect(() => {
    const menu = disclosure.current!;
    let openedAt = scrollY;
    const close = () => menu.removeAttribute("open");
    const toggle = () => { openedAt = scrollY; };
    const scroll = () => { if (menu.open && Math.abs(scrollY - openedAt) > 48) close(); };
    const outside = (e: Event) => { if (!menu.contains(e.target as Node)) close(); };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && menu.open) { e.preventDefault(); close(); menu.querySelector("summary")?.focus(); }
    };
    // A resized disclosure must not leave focus on a mobile-only, now hidden link.
    const resize = () => { if (menu.open) { close(); menu.querySelector("summary")?.focus(); } };
    menu.addEventListener("toggle", toggle);
    window.addEventListener("scroll", scroll, { passive: true });
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", resize);
    return () => {
      menu.removeEventListener("toggle", toggle); window.removeEventListener("scroll", scroll);
      document.removeEventListener("pointerdown", outside); document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape); window.removeEventListener("resize", resize);
    };
  }, []);

  function navigate(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    disclosure.current?.removeAttribute("open");
    const href = e.currentTarget.getAttribute("href")!;
    if (!href.startsWith("#")) return;
    // Hash routing may first replace Evaluation/the signed-out page with the landing.
    // Wait for that render before scrolling and moving focus out of the closed disclosure.
    const from = document.activeElement;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (document.activeElement !== from && document.activeElement !== document.body) return;
      const target = document.getElementById(href.slice(1));
      target?.scrollIntoView({ block: "start" });
      target?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
    }));
  }
  const navLink = (item: { href: string; label: string }, mobile = false) => <a key={item.href} className={mobile ? "public-mobile-link" : undefined} href={item.href} onClick={navigate} aria-current={current === item.href.slice(1) ? "location" : undefined}>{item.label}{item.href.startsWith("https:") && <span aria-hidden="true">↗</span>}</a>;
  return <header className="public-header">
    <div className="public-header-bar">
      <a href="#" className="public-brand"><Logo />PII Guard</a>
      <nav aria-label="Main navigation" className="public-nav">
        <div className="public-primary">{PRIMARY.map((item) => navLink(item))}</div>
        <details ref={disclosure} className="public-disclosure">
          <summary aria-controls={panelId} className={RESOURCES.some((item) => item.href === `#${current}`) ? "public-resource-current" : undefined}>
            <span className="public-desktop-label">Resources</span><span className="public-mobile-label">Menu</span>
            <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m4 6 4 4 4-4" /></svg>
          </summary>
          <div id={panelId} className="public-nav-panel">
            {PRIMARY.map((item) => navLink(item, true))}
            <p className="public-resource-label">Resources</p>
            {RESOURCES.map((item) => navLink(item))}
          </div>
        </details>
      </nav>
      <div className="public-account"><ButtonLink href={accountHref}>{signedIn ? "Open console" : "Sign in"}</ButtonLink></div>
    </div>
  </header>;
}
