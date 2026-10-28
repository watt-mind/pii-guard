import { useMemo } from "react";
import { useHostedSession } from "../hosted/session";
import type { ServerStatus } from "../api/status";
import type { PlaygroundTab, Section } from "./routes";

// What the server offers the console. Screens are shown or hidden only through this, never
// through the build flag, so a local and a hosted server run the same console.
export const CAPABILITY_KEYS = ["text", "chat", "images", "logs", "vault", "server_policy", "projects", "connect", "evaluation", "accounts"] as const;
export type Capability = (typeof CAPABILITY_KEYS)[number];
export type Capabilities = Readonly<Record<Capability, boolean>>;

/** The server's own defaults (status.py `capabilities`): the traffic log is off unless configured. */
export const LOCAL_CAPABILITIES: Capabilities = { text: true, chat: true, images: true, logs: false, vault: true, server_policy: true, projects: true, connect: true, evaluation: true, accounts: false };
/** Text only, owner-scoped: no image masking and no server policy; each owner has a log and a vault. */
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
const SECTION_CAPABILITY: Record<Section, Capability | null> = { overview: null, playground: null, logs: null, vault: null, projects: "projects", connect: "connect", policy: "server_policy", evaluation: "evaluation" };
const TAB_CAPABILITY: Record<PlaygroundTab, Capability> = { text: "text", chat: "chat", images: "images" };

export const offersTab = (caps: Capabilities, tab: PlaygroundTab) => caps[TAB_CAPABILITY[tab]];
export function offersSection(caps: Capabilities, section: Section): boolean {
  if (section === "playground") return offersTab(caps, "text") || offersTab(caps, "chat") || offersTab(caps, "images");
  const key = SECTION_CAPABILITY[section];
  return key === null || caps[key];
}

/** The console's capabilities, from the server's status and whether a hosted owner is signed in. */
export function useCapabilities(status: ServerStatus | null): Capabilities {
  const hosted = useHostedSession()?.account.mode === "hosted";
  return useMemo(() => capabilitiesOf(status, hosted), [status, hosted]);
}
