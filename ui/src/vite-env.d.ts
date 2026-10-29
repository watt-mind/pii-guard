/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Explicit public hosted shell; omitted builds retain the local console. */
  readonly VITE_PII_GUARD_HOSTED?: string;
  /** "mock" forces the built-in demo engine, "api" forces the live API; anything else means auto. */
  readonly VITE_PII_GUARD_MODE?: string;
  /** Model the Chat screen asks the gateway's upstream for. */
  readonly VITE_PII_GUARD_CHAT_MODEL?: string;
  /** Model "Send demo traffic" (Live traffic screen) asks for; default pii-guard-mock. */
  readonly VITE_PII_GUARD_DEMO_MODEL?: string;
  /** The landing's 3-minute demo video (a page or file URL); the slot is hidden while unset. */
  readonly VITE_PII_GUARD_DEMO_VIDEO_URL?: string;
  /** Optional poster image for the demo video slot. */
  readonly VITE_PII_GUARD_DEMO_VIDEO_POSTER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
