/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" forces the built-in demo engine, "api" forces the live API; anything else means auto. */
  readonly VITE_PII_GUARD_MODE?: string;
  /** Model the Chat screen asks the gateway's upstream for. */
  readonly VITE_PII_GUARD_CHAT_MODEL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
