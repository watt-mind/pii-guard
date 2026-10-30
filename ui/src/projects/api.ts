import type { TextEntityType, VisualEntityType } from "../api/types";
import type { Policy } from "../lib/entities";

export interface Project { id: string; name: string; default_policy_id: string }
export interface ProjectList { projects: Project[]; default_project_id: string }
export interface PolicyVersion {
  id: string; policy_id: string; policy_version_id: string; name: string; version: number;
  /** Text types, and visual types (mask or keep) for versions saved since LAB-1444. */
  entity_policies: Record<TextEntityType, Policy> & Partial<Record<VisualEntityType, Policy>>;
  language: string; mode: string; detection_profile: string;
  /** Image detection; absent on versions saved before LAB-1444 (read as `local`). */
  visual_detection?: VisualDetection;
}
/** `local`: on-device faces, ID photos and signatures. `sam`: SAM 3.1 on the Meta API too. */
export type VisualDetection = "local" | "sam";
/** Hosted, "local" runs on the PII Guard server, not on the owner's device (LAB-1626). */
const HOSTED_BUILD = import.meta.env.VITE_PII_GUARD_HOSTED === "true";
/** What the Detection choice says, in the editor and the read-only policy view. */
export const VISUAL_DETECTION_LABEL: Record<VisualDetection, string> = {
  local: HOSTED_BUILD ? "On the PII Guard server (fast)" : "On-device (fast)",
  sam: "SAM 3.1 (better signatures, ~2–4 s, sends the image to Meta)",
};
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

/**
 * "Tune what is masked" on Connect (LAB-1626): Projects opens a new version of this policy family
 * once it has loaded; cleared when it opens.
 */
let policyEdit: string | null = null;
let policyEditEndpoint: string | null = null;
/** `endpointId`: the endpoint Connect tested, which "Save and apply" then moves to the new version (LAB-1629). */
export function requestPolicyEdit(policyId: string | null, endpointId: string | null = null) {
  policyEdit = policyId;
  policyEditEndpoint = policyId ? endpointId : null;
}
export function pendingPolicyEdit(): string | null {
  return policyEdit;
}
export function pendingPolicyEndpoint(): string | null {
  return policyEditEndpoint;
}
