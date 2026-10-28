import type { TextEntityType } from "../api/types";
import type { Policy } from "../lib/entities";

export interface Project { id: string; name: string; default_policy_id: string }
export interface ProjectList { projects: Project[]; default_project_id: string }
export interface PolicyVersion {
  id: string; policy_id: string; policy_version_id: string; name: string; version: number;
  entity_policies: Record<TextEntityType, Policy>; language: string; mode: string;
  detection_profile: string;
}
export interface Endpoint {
  id: string; name: string; project_id: string; policy_id: string;
  policy_version_id: string; policy_version: number; provider: string;
  /** `null`: pass-through, the client's own model is forwarded unchanged (LAB-1451). */
  base_url: string; model: string | null; credential_configured: boolean; enabled: boolean; base_path: string;
}
export interface EndpointKey { id: string; name: string; created_at: string; revoked_at?: string | null }
export const projectPath = (id: string) => `/v1/projects/${encodeURIComponent(id)}`;
/** `POST …/endpoints/models`: model ids for the endpoint form (provider catalog or allow-list). */
export interface EndpointModels { models: string[] }
export interface EndpointModelsQuery { provider: string; base_url?: string; api_key?: string; endpoint_id?: string }

/** An illustrative model ID per provider for pass-through hints ("for example …"); none for custom. */
const EXAMPLE_MODEL: Record<string, string> = {
  meta: "muse-spark-1.3",
  sponsored: "muse-spark-1.3",
  openai: "gpt-4.1-mini",
  fireworks: "accounts/fireworks/models/llama-v3p1-8b-instruct",
  openrouter: "openai/gpt-4.1-mini",
};
export const exampleModel = (provider: string | null | undefined): string | null => (provider ? EXAMPLE_MODEL[provider] ?? null : null);
