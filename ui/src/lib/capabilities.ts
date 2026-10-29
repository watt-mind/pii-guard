import { useMemo } from "react";
import { useHostedSession } from "../hosted/session";
import type { ChatMode } from "../api/chat";
import type { ServerStatus } from "../api/status";
import { PLAYGROUND_TABS, type PlaygroundTab, type Section } from "./routes";

// What the server offers the console. Screens are shown or hidden only through this, never
// through the build flag, so a local and a hosted server run the same console.
export const CAPABILITY_KEYS = ["text", "chat", "images", "logs", "vault", "server_policy", "projects", "connect", "evaluation", "accounts"] as const;
export type Capability = (typeof CAPABILITY_KEYS)[number];
export type Capabilities = Readonly<Record<Capability, boolean>>;

/** The server's own defaults (status.py `capabilities`): the traffic log is off unless configured. */
export const LOCAL_CAPABILITIES: Capabilities = { text: true, chat: true, images: true, logs: false, vault: true, server_policy: true, projects: true, connect: true, evaluation: true, accounts: false };
/** Owner-scoped: no server policy; each owner has a log and a vault. Images only once `/v1/status` reports them. */
export const HOSTED_CAPABILITIES: Capabilities = { ...LOCAL_CAPABILITIES, images: false, logs: true, server_policy: false, accounts: true };

/**
 * `/v1/status` `capabilities` when the server reports them (LAB-1431); until then, the
 * defaults for the mode, hosted when `/v1/account` says so.
 */
export function capabilitiesOf(status: ServerStatus | null, hosted: boolean): Capabilities {
  const defaults = hosted ? HOSTED_CAPABILITIES : LOCAL_CAPABILITIES;
  const reported = status?.capabilities;
  if (!reported || typeof reported !== "object") return defaults;
  return Object.fromEntries(CAPABILITY_KEYS.map((key) => [key, typeof reported[key] === "boolean" ? reported[key] : defaults[key]])) as Capabilities;
}

// Logs and Vault stay in the menu when the server's log or inspector is off: the screens say so
// and how to turn it on (Logs also replays recorded traffic), as the local console always has.
// Policy is the server's policy where the server has one, else the owner's project policies
// (read-only there, edited under Projects), so it needs either.
const SECTION_CAPABILITY: Record<Section, Capability | null> = { overview: null, playground: null, logs: null, vault: null, projects: "projects", connect: "connect", policy: "server_policy", evaluation: "evaluation" };
const TAB_CAPABILITY: Record<PlaygroundTab, Capability> = { text: "text", chat: "chat", images: "images" };

export const offersTab = (caps: Capabilities, tab: PlaygroundTab) => caps[TAB_CAPABILITY[tab]];
export function offersSection(caps: Capabilities, section: Section): boolean {
  if (section === "playground") return offersTab(caps, "text") || offersTab(caps, "chat") || offersTab(caps, "images");
  if (section === "policy") return caps.server_policy || caps.projects;
  const key = SECTION_CAPABILITY[section];
  return key === null || caps[key];
}

/** The Playground's menu hint, naming only the tabs the server offers: "Try text, chat and images". */
export function playgroundHint(caps: Capabilities): string {
  const names = PLAYGROUND_TABS.filter((t) => offersTab(caps, t.id)).map((t) => t.label.toLowerCase());
  const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : (names[0] ?? "");
  return `Try ${list}`;
}

const CHAT_MODES: readonly ChatMode[] = ["fast", "audit"];

/**
 * The detection modes Chat offers: the ones `/v1/status` `gateway.modes` lists (a hosted
 * owner's projection lists fast only). Before the status answers, a server with accounts
 * offers fast only; any other console keeps both, as the local console always has.
 */
export function chatModesOf(status: ServerStatus | null, caps: Capabilities): ChatMode[] {
  if (status) {
    const listed = CHAT_MODES.filter((m) => m in status.gateway.modes);
    return listed.length ? listed : ["fast"];
  }
  return caps.accounts ? ["fast"] : [...CHAT_MODES];
}

/**
 * "Send demo traffic" sends scripted calls through the server's own upstream with the demo
 * model. A server with accounts forwards each owner's calls to that owner's endpoints and the
 * sponsored model's allow-list, which would refuse it (or spend the owner's provider quota on
 * scripted calls), so there it is not offered.
 */
export const offersDemoTraffic = (caps: Capabilities) => !caps.accounts;

/** The console's capabilities, from the server's status and whether a hosted owner is signed in. */
export function useCapabilities(status: ServerStatus | null): Capabilities {
  const hosted = useHostedSession()?.account.mode === "hosted";
  return useMemo(() => capabilitiesOf(status, hosted), [status, hosted]);
}
