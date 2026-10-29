import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TEXT_ENTITY_TYPES } from "../api/types";
import type { Requester } from "../hosted/api";
import { ENTITY_META } from "../lib/entities";
import type { PolicyVersion } from "../projects/api";
import { OwnerPolicy } from "./Policy";

const policy: PolicyVersion = {
  id: "family", policy_id: "family", policy_version_id: "v1", name: "Synthetic default", version: 1, language: "hu", mode: "fast", detection_profile: "standard",
  visual_detection: "local",
  entity_policies: { ...(Object.fromEntries(TEXT_ENTITY_TYPES.map((t) => [t, ENTITY_META[t].policy])) as PolicyVersion["entity_policies"]), SIGNATURE: "keep" },
};

function call(version: PolicyVersion): Requester {
  return vi.fn(async (path: string) => {
    if (path === "/v1/projects") return { projects: [{ id: "p1", name: "Synthetic project", default_policy_id: "family" }], default_project_id: "p1" };
    return { policies: [version] };
  }) as unknown as Requester;
}

describe("hosted read-only policy view", () => {
  it("shows image detection and each image type's action", async () => {
    render(<OwnerPolicy call={call(policy)} />);
    expect(await screen.findByText("On-device (fast)")).toBeInTheDocument();
    const images = screen.getByRole("table", { name: "Images" });
    expect(images).toHaveTextContent(/Signature SIGNATUREKept in place/);
    expect(images).toHaveTextContent(/Face FACEMasked/);
  });

  it("reads a version saved before image settings as on-device", async () => {
    const legacy: PolicyVersion = { ...policy };
    delete legacy.visual_detection;
    render(<OwnerPolicy call={call(legacy)} />);
    expect(await screen.findByText("On-device (fast)")).toBeInTheDocument();
  });
});
