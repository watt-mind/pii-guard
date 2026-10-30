import { useEffect, useId, useRef, type MouseEvent, type RefObject } from "react";
import { ButtonLink, Logo, ThemeToggle } from "../components/ui";
import { useTheme, type ThemePref } from "../hooks/useTheme";
import { SOURCE } from "./session";
import "./publicNavigation.css";

interface NavItem {
  href: string;
  label: string;
}

const PRIMARY: readonly NavItem[] = [
  { href: "#demo", label: "Demo" },
  { href: "#how", label: "How it works" },
  { href: "#results", label: "Benchmarks" },
  { href: "#api", label: "API" },
];
const RESOURCES: readonly NavItem[] = [
  { href: "#technical", label: "Technical overview" },
  { href: "#images", label: "Image masking" },
  { href: "#trust", label: "Privacy & trust" },
  { href: "#account", label: "Get started" },
  { href: `${SOURCE}#try-it`, label: "Self-hosting guide" },
];

const THEME_ICON_PATHS: Record<ThemePref, string> = {
  dark: "M13 9.6A5.5 5.5 0 0 1 6.4 3a5.5 5.5 0 1 0 6.6 6.6Z",
  light: "M8 2v1M8 13v1M2 8h1M13 8h1M4 4l1 1M11 11l1 1M12 4l-1 1M5 11l-1 1M10.5 8a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z",
  system: "M2.5 3.5h11v7h-11zM6 13.5h4M8 10.5v3",
};

function themeIconPath(theme: ThemePref): string {
  return THEME_ICON_PATHS[theme];
}

function isPlainLeftClick(e: MouseEvent<HTMLAnchorElement>): boolean {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

function focusHashTarget(href: string, from: Element | null): void {
  if (document.activeElement !== from && document.activeElement !== document.body) return;
  const pageHeading = document.getElementById("public-page-heading");
  if (["#demo", "#trust", "#technical"].includes(href) && pageHeading) {
    globalThis.scrollTo?.(0, 0);
    pageHeading.focus({ preventScroll: true });
    return;
  }
  const target = document.getElementById(href.slice(1));
  target?.scrollIntoView({ block: "start" });
  target?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
}

/**
 * Closes the disclosure on outside pointer or focus, Escape, scroll and resize. Opening the other
 * header disclosure is an outside pointer/focus event, so this alone keeps them mutually exclusive.
 */
function useDisclosureDismissal(disclosure: RefObject<HTMLDetailsElement | null>) {
  useEffect(() => {
    const menu = disclosure.current!;
    let openedAt = scrollY;
    const close = () => menu.removeAttribute("open");
    const closeAndFocusSummary = () => {
      close();
      menu.querySelector("summary")?.focus();
    };
    const toggle = () => {
      openedAt = scrollY;
    };
    const scroll = () => {
      if (menu.open && Math.abs(scrollY - openedAt) > 48) close();
    };
    const outside = (e: Event) => {
      if (!menu.contains(e.target as Node)) close();
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || !menu.open) return;
      e.preventDefault();
      closeAndFocusSummary();
    };
    // A resized disclosure must not leave focus on a mobile-only, now hidden link.
    const resize = () => {
      if (menu.open) closeAndFocusSummary();
    };
    menu.addEventListener("toggle", toggle);
    window.addEventListener("scroll", scroll, { passive: true });
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", resize);
    return () => {
      menu.removeEventListener("toggle", toggle);
      window.removeEventListener("scroll", scroll);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", resize);
    };
  }, [disclosure]);
}

function PublicNavLink({ item, current, mobile = false, onClick }: { item: NavItem; current?: string | null; mobile?: boolean; onClick: (e: MouseEvent<HTMLAnchorElement>) => void }) {
  const isCurrent = current === item.href.slice(1);
  return (
    <a
      className={mobile ? "public-mobile-link" : undefined}
      href={item.href}
      onClick={onClick}
      aria-current={isCurrent ? "location" : undefined}
    >
      {item.label}
      {item.href.startsWith("https:") && <span aria-hidden="true">{"\u2197"}</span>}
    </a>
  );
}

function AccountButton({ accountHref, signedIn }: { accountHref: string; signedIn: boolean }) {
  return (
    <ButtonLink variant="primary" href={accountHref} aria-label={signedIn ? "Open console" : "Sign in to console"}>
      {signedIn ? (
        <>
          <span className="public-signin-suffix">Open{"\u00a0"}</span>
          <span className="public-console-label">console</span>
        </>
      ) : (
        <>
          Sign in<span className="public-signin-suffix">{"\u00a0"}to console</span>
        </>
      )}
    </ButtonLink>
  );
}

/** Plain navigation disclosure: normal Tab order, no application-menu focus trap. */
export function PublicHeader({ current, accountHref, signedIn = false }: { current?: string | null; accountHref: string; signedIn?: boolean }) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  const appearance = useRef<HTMLDetailsElement>(null);
  const panelId = useId();
  const themePanelId = useId();
  const [theme, setTheme] = useTheme();
  useDisclosureDismissal(disclosure);
  useDisclosureDismissal(appearance);

  function navigate(e: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainLeftClick(e)) return;
    disclosure.current?.removeAttribute("open");
    const href = e.currentTarget.getAttribute("href")!;
    if (!href.startsWith("#")) return;
    // Hash routing may first replace Evaluation/the signed-out page with the landing.
    // Wait for that render before scrolling and moving focus out of the closed disclosure.
    const from = document.activeElement;
    requestAnimationFrame(() => requestAnimationFrame(() => focusHashTarget(href, from)));
  }

  const resourceCurrent = RESOURCES.some((item) => item.href === `#${current}`);
  return (
    <header className="public-header">
      <div className="public-header-bar">
        <a href="#site" className="public-brand"><Logo />PII Guard</a>
        <nav aria-label="Main navigation" className="public-nav">
          <div className="public-primary">
            {PRIMARY.map((item) => <PublicNavLink key={item.href} item={item} current={current} onClick={navigate} />)}
          </div>
          <details ref={disclosure} className="public-disclosure">
            <summary aria-controls={panelId} className={resourceCurrent ? "public-resource-current" : undefined}>
              <span className="public-desktop-label">Resources</span>
              <span className="public-mobile-label">Menu</span>
              <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m4 6 4 4 4-4" /></svg>
            </summary>
            <div id={panelId} className="public-nav-panel">
              {PRIMARY.map((item) => <PublicNavLink key={item.href} item={item} current={current} mobile onClick={navigate} />)}
              <p className="public-resource-label">Resources</p>
              {RESOURCES.map((item) => <PublicNavLink key={item.href} item={item} current={current} onClick={navigate} />)}
            </div>
          </details>
        </nav>
        <div className="public-account">
          <details ref={appearance} className="public-appearance">
            <summary aria-label="Appearance" aria-controls={themePanelId} title="Appearance">
              <svg aria-hidden="true" viewBox="0 0 16 16" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d={themeIconPath(theme)} />
              </svg>
            </summary>
            <div id={themePanelId} className="public-appearance-panel">
              <p>Appearance</p>
              <ThemeToggle theme={theme} onTheme={setTheme} />
            </div>
          </details>
          <a className="public-source-link" href={SOURCE} aria-label="Source on GitHub" title="Source on GitHub">
            <img src="/brands/github.svg" alt="" width="20" height="20" />
          </a>
          <AccountButton accountHref={accountHref} signedIn={signedIn} />
        </div>
      </div>
    </header>
  );
}
