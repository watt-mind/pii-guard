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
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
