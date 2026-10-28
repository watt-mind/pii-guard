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
  base_url: string; model: string; credential_configured: boolean; enabled: boolean; base_path: string;
}
export interface EndpointKey { id: string; name: string; created_at: string; revoked_at?: string | null }
export const projectPath = (id: string) => `/v1/projects/${encodeURIComponent(id)}`;
