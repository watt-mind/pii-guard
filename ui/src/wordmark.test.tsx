// The wordmark rule (LAB-1486): the product is "PII Guard" wherever a person reads it, and
// `pii-guard` only where something is typed or read by a machine (the CLI, the package, the repo,
// env vars, headers), which the UI always sets in code font. This walks the rendered landing and
// console shells and fails on a lowercase `pii-guard` outside <code>/<pre>, or a made-up spelling.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { UnreachableError, type HttpGuardClient } from "./api/http";
import { createMockClient } from "./api/mock";
import { HostedApp } from "./hosted/HostedApp";
import type { Account, Requester } from "./hosted/api";

const CODE = "code, pre, kbd, samp, textarea, script, style";
const WRONG = /pii-guard|PIIGuard|Pii Guard|PII-Guard/;
const ATTRS = ["title", "aria-label", "alt", "placeholder", "aria-description"];
/** Identifiers that may show as plain text: the HF model id, the repo path, the PyPI package. */
const IDS = /[\w.-]+\/pii-guard[\w./-]*|wattmind-pii-guard(?:\[\w+\])?/g;
const wrong = (s: string) => WRONG.test(s.replace(IDS, ""));

/** Every piece of visible (or announced) text that names the product the wrong way. */
function offenders(root: HTMLElement = document.body): string[] {
  const found: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.textContent ?? "";
    if (wrong(text) && !n.parentElement?.closest(CODE)) found.push(`text: ${text.trim()}`);
  }
  for (const el of root.querySelectorAll<HTMLElement>("*")) {
    if (el.closest(CODE)) continue;
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (v && wrong(v)) found.push(`${el.tagName.toLowerCase()}[${a}]: ${v}`);
    }
  }
  return found;
}

const flush = () => act(() => new Promise((r) => setTimeout(r, 50)));

function offlineApi(): HttpGuardClient {
  const down = () => Promise.reject(new UnreachableError());
  return { health: down, analyze: down, mask: down, unmask: down };
}

const account = (authenticated: boolean): Account => ({
  mode: "hosted", authenticated, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F",
  tier: authenticated ? "standard" : "anonymous", providers: ["meta"], included_model: "muse-spark-1.3", limits: { requests_per_day: 3 },
  usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [],
});

const requester = (signedIn: boolean) =>
  vi.fn(async (path: string) => {
    if (path === "/v1/account") return account(signedIn);
    if (path === "/v1/projects") return { projects: [], default_project_id: null };
    return {};
  }) as unknown as Requester;

beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, "", location.pathname);
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});

describe("wordmark: PII Guard in visible text, pii-guard only in code (LAB-1486)", () => {
  it("the offender check catches lowercase prose and ignores code", () => {
    const root = document.createElement("div");
    root.innerHTML = `<p>Start it with <code>pii-guard up</code>.</p><p title="PII Guard overhead">PII Guard masks</p>`;
    expect(offenders(root)).toEqual([]);
    root.innerHTML = `<p>pii-guard masks</p><span aria-label="pii-guard boundary"></span><p>PIIGuard</p><p title="watt-mind/pii-guard-ner-xlmr-base">model</p>`;
    expect(offenders(root)).toHaveLength(3);
  });

  it("the page title and share tags say PII Guard", () => {
    const html = readFileSync(resolve(__dirname, "../index.html"), "utf8");
    expect(html).toMatch(/<title>PII Guard · /);
    const shown = [...html.matchAll(/<meta (?:property|name)="(?:og:[\w:]+|twitter:[\w:]+|description)" content="([^"]*)"/g)].map((m) => m[1]);
    expect(shown.length).toBeGreaterThan(5);
    for (const c of shown) expect(c).not.toMatch(WRONG);
    expect(html).toContain('<meta property="og:site_name" content="PII Guard" />');
  });

  it.each([true, false])("the hosted landing and header (signed in: %s)", async (signedIn) => {
    render(<HostedApp call={requester(signedIn)} />);
    await flush();
    expect(screen.getAllByText("PII Guard").length).toBeGreaterThan(0);
    expect(offenders()).toEqual([]);
  });

  it.each([
    ["#overview", "Overview"],
    ["#playground/text", "Playground"],
    ["#playground/chat", "Playground"],
    ["#playground/images", "Playground"],
    ["#logs", "Logs"],
    ["#vault", "Vault"],
    ["#connect", "Connect"],
    ["#policy", "Policy"],
    ["#evaluation", "Evaluation"],
  ])("the console shell at %s", async (hash, section) => {
    history.replaceState(null, "", hash);
    render(<App api={offlineApi()} mock={createMockClient()} traffic={{ connect: vi.fn(() => ({ close() {} })), fixtureIntervalMs: 60_000 }} />);
    expect(await screen.findByRole("region", { name: section })).toBeVisible();
    await flush();
    expect(screen.getAllByText("PII Guard").length).toBeGreaterThan(0);
    expect(offenders()).toEqual([]);
  });
});
