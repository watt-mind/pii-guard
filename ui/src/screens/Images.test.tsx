import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { HttpGuardClient } from "../api/http";
import { ApiError, UnreachableError } from "../api/http";
import { IMAGE_RECORDINGS } from "../api/imageMock";
import { createMockClient } from "../api/mock";
import type { ImageMaskResponse } from "../api/types";
import type { RoutingClient } from "../api/engine";
import type { Account } from "../hosted/api";
import { HostedSessionContext, type HostedSession } from "../hosted/session";
import { Images } from "./Images";

const loadImage = vi.fn(async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: "image/png" }));

function offlineApi(): HttpGuardClient {
  const down = () => Promise.reject(new UnreachableError());
  return { health: down, analyze: down, mask: down, unmask: down, maskImage: down };
}

function liveApi(maskImage: HttpGuardClient["maskImage"]): HttpGuardClient {
  const backend = createMockClient();
  return {
    health: () => Promise.resolve({ status: "ok", version: "0.1.0" }),
    analyze: backend.analyze,
    mask: backend.mask,
    unmask: backend.unmask,
    maskImage,
  };
}

function recorded(id: string, overrides: Partial<ImageMaskResponse> = {}): ImageMaskResponse {
  return { ...structuredClone(IMAGE_RECORDINGS.samples[id]!), image: "iVBORw0KGgo=", ...overrides };
}

async function openImages(api: HttpGuardClient) {
  const user = userEvent.setup();
  render(<App api={api} mock={createMockClient()} loadImage={loadImage} />);
  await user.click(await screen.findByRole("tab", { name: /images/i }));
  await screen.findByRole("button", { name: /mask image/i });
  return { user, panel: screen.getByRole("tabpanel", { name: /images/i }) };
}

beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, "", "#playground/text");
  loadImage.mockClear();
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
  URL.createObjectURL ??= vi.fn(() => "blob:fake");
  URL.revokeObjectURL ??= vi.fn();
});

describe("Images screen", () => {
  it("sends the English default image and honors a manual language override", async () => {
    const maskImage = vi.fn().mockResolvedValue(recorded("id-card-en"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("API up", { selector: "span" });
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    await within(panel).findByTestId("masked-image");
    expect(maskImage).toHaveBeenLastCalledWith(expect.objectContaining({ sampleId: "id-card-en", language: "en" }));
    expect(loadImage).toHaveBeenCalledWith("/samples/id-card-en.png");
    await user.selectOptions(within(panel).getByRole("combobox", { name: "Language of the text in the image" }), "hu");
    await user.click(within(panel).getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(maskImage).toHaveBeenLastCalledWith(expect.objectContaining({ sampleId: "id-card-en", language: "hu" })));
  });

  it("starts on the English specimen with an honest local-detector demo replay", async () => {
    const { user, panel } = await openImages(offlineApi());
    expect(within(panel).getByRole("combobox", { name: "Language of the text in the image" })).toHaveValue("en");
    expect(within(panel).getByRole("button", { name: /ID card \(English\)/ })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    expect(await within(panel).findByTestId("demo-masked-image")).toBeInTheDocument();
    expect(within(panel).getByTestId("image-scope-note")).toHaveTextContent("Nothing was sent anywhere just now");
    expect(within(panel).getByText(/black boxes are drawn/)).not.toHaveTextContent("SAM 3.1");
  });

  it("is the third tab and reachable with the arrow keys", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} loadImage={loadImage} />);
    await user.click(screen.getByRole("tab", { name: /chat/i }));
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /images/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: /images/i })).toBeVisible();
  });

  it("replays both Hungarian name lines with region boxes for the ID card", async () => {
    // LAB-1260: the stale SAM-era bundle left the surname without a region box; the replay
    // now sources the fresh local-detector recording, which covers both name lines.
    for (const id of ["id-card", "id-card-en"]) {
      const persons = IMAGE_RECORDINGS.samples[id]!.regions.filter(
        (r) => r.entity_type === "PERSON" && r.policy === "mask",
      );
      expect(persons.length, id).toBeGreaterThanOrEqual(2);
    }
  });

  it("in demo mode replays recorded regions for a sample and draws the masking in the browser", async () => {
    const { user, panel } = await openImages(offlineApi());
    // One click: picking a sample masks it.
    await user.click(within(panel).getByRole("button", { name: /signed letter/i }));

    expect(await within(panel).findByTestId("demo-masked-image")).toBeInTheDocument();
    const rec = IMAGE_RECORDINGS.samples["signed-letter"]!;
    const masked = rec.regions.filter((r) => r.policy === "mask").length;
    expect(within(panel).getAllByTestId("demo-mask")).toHaveLength(masked);
    expect(within(panel).getAllByTestId("region-box")).toHaveLength(rec.regions.length);
    expect(within(panel).getByRole("button", { name: "Stamp, found by SAM 3.1, kept by policy" })).toBeInTheDocument();
    expect(within(panel).getByTestId("image-scope-note")).toHaveTextContent(/Recorded .* Nothing was sent anywhere/);
    expect(within(panel).getByText(/black boxes are drawn in your browser/)).toBeInTheDocument();
    expect(within(panel).getByRole("table")).toHaveTextContent("Signature");
    // Labels follow what ran: the recorded run used the Muse Spark LLM detector.
    expect(within(panel).getByRole("table")).toHaveTextContent("OCR + Muse Spark 1.3 (Meta API)");
    expect(within(panel).getByRole("table")).toHaveTextContent(/OCR \+ Rules(?! \+)/);
  });

  it("marks the upload tile as needing the live API in demo mode", async () => {
    const { panel } = await openImages(offlineApi());
    await waitFor(() => expect(within(panel).getByText("Needs the live API: masking runs on the server.")).toBeInTheDocument());
  });

  it("tells a user who chose the demo engine with the API up to switch to Live API", async () => {
    localStorage.setItem("pii-guard:mode", "mock");
    const { user, panel } = await openImages(liveApi(vi.fn()));
    await screen.findByText(/^API v0.1.0/);
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    await user.upload(input, new File([new Uint8Array([0x89, 0x50])], "mine.png", { type: "image/png" }));
    expect(within(panel).getByText("Nothing has been sent yet")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent(/switch Engine in the sidebar to Live API/);
  });

  it("says an undecodable image could not be decoded", async () => {
    const maskImage = vi.fn().mockRejectedValue(new ApiError(422, "invalid_image", "image could not be decoded"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("API up", { selector: "span" });
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("This image couldn't be decoded.");
  });

  it("refuses an upload in demo mode and says nothing was sent", async () => {
    const { user, panel } = await openImages(offlineApi());
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    await user.upload(input, new File([new Uint8Array([0x89, 0x50])], "mine.png", { type: "image/png" }));
    expect(within(panel).getByText("mine.png")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("Uploads need the live API.");
    expect(alert).toHaveTextContent("was not sent anywhere");
  });

  it("rejects unsupported uploads before anything runs", async () => {
    const { panel } = await openImages(offlineApi());
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(input, new File(["GIF89a"], "anim.gif", { type: "image/gif" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Only PNG and JPEG");
  });

  it("sends an upload in English by default, and the picked language when changed (LAB-1242)", async () => {
    const maskImage = vi.fn().mockResolvedValue(recorded("id-card"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("API up", { selector: "span" });
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    await user.upload(input, new File([new Uint8Array([0x89, 0x50])], "letter.png", { type: "image/png" }));
    const language = within(panel).getByRole("combobox", { name: "Language of the text in the image" });
    expect(language).toHaveValue("en");
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    await waitFor(() => expect(maskImage).toHaveBeenLastCalledWith(expect.objectContaining({ sampleId: null, language: "en" })));
    await user.selectOptions(language, "hu");
    await user.click(within(panel).getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(maskImage).toHaveBeenLastCalledWith(expect.objectContaining({ language: "hu" })));
  });

  it("shows the API's masked PNG, the regions and what ran", async () => {
    const maskImage = vi.fn().mockResolvedValue(recorded("id-card"));
    const { user, panel } = await openImages(liveApi(maskImage));
    expect(await screen.findByText("API up", { selector: "span" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: /^ID cardFace/i }));

    const figure = await within(panel).findByTestId("masked-image");
    expect(figure.querySelector("img")!.getAttribute("src")).toBe("data:image/png;base64,iVBORw0KGgo=");
    expect(maskImage).toHaveBeenCalledWith(expect.objectContaining({ sampleId: "id-card", language: "hu" }));
    expect(loadImage).toHaveBeenCalledWith("/samples/id-card.png");
    const note = within(panel).getByTestId("image-scope-note");
    expect(note).toHaveTextContent(
      "The on-device face detector (YuNet) looked for faces and ID photos",
    );
    // The fresh local-detector recording runs rules only: the gaps read as known scope.
    expect(note).toHaveTextContent("Not covered");
    expect(within(panel).getByText(/exactly as the API returned it/)).toBeInTheDocument();

    // Hover a region box: the matching legend type lights up; the toggle hides the boxes.
    const face = within(panel).getByRole("button", { name: "Face, found by YuNet (on-device), masked" });
    await user.hover(face);
    expect(face).toHaveAttribute("aria-pressed", "true");
    await user.click(within(panel).getByRole("checkbox", { name: "Show regions" }));
    expect(within(panel).queryAllByTestId("region-box")).toHaveLength(0);
  });

  it("says when OCR did not run", async () => {
    const data = recorded("visitor-badge", {
      regions: recorded("visitor-badge").regions.filter((r) => r.source === "sam"),
      analysis: { sam: { model: "sam-3.1", entity_types: ["FACE"] }, ocr: { ran: false, engine: null, detectors: [], reason: "tesseract_unavailable" } },
    });
    const { user, panel } = await openImages(liveApi(vi.fn().mockResolvedValue(data)));
    await screen.findByText("API up", { selector: "span" });
    await user.click(within(panel).getByRole("button", { name: /visitor badge/i }));
    expect(await within(panel).findByText(/Text in this image was not checked/)).toBeInTheDocument();
  });

  it("fails closed: a 503 shows the blocked notice and no masked image", async () => {
    const maskImage = vi.fn().mockRejectedValue(new ApiError(503, "detection_failed", "SAM request failed: HTTP 500"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("API up", { selector: "span" });
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("Blocked. Nothing was sent to the model.");
    expect(alert).toHaveTextContent("detection_failed");
    expect(within(panel).queryByTestId("masked-image")).toBeNull();
    // The way out: replay the recorded run on the same sample, without leaving the live API (LAB-1265).
    await user.click(within(panel).getByRole("button", { name: "Replay the recorded run instead" }));
    expect(await within(panel).findByTestId("demo-masked-image")).toBeInTheDocument();
    expect(maskImage).toHaveBeenCalledTimes(1);
    expect(screen.getByText("API up", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByLabelText("Engine")).toHaveValue("auto");
    expect(screen.queryByText("Demo mode.")).toBeNull();
  });

  it("drops the result when an upload replaces the sample, and waits for a click", async () => {
    const maskImage = vi.fn().mockResolvedValue(recorded("id-card"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("API up", { selector: "span" });
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    await within(panel).findByTestId("masked-image");
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    await user.upload(input, new File([new Uint8Array([0x89, 0x50])], "mine.png", { type: "image/png" }));
    await waitFor(() => expect(within(panel).queryByTestId("masked-image")).toBeNull());
    expect(within(panel).getByText("Nothing has been sent yet")).toBeInTheDocument();
    expect(maskImage).toHaveBeenCalledTimes(1);
  });
});

describe("Images screen, hosted", () => {
  // Fictional owner; the server reports a 4 MiB decoded upload limit (ADR 0014).
  const account: Account = {
    mode: "hosted", authenticated: true, login_url: "/.auth/login/google", logout_url: "/.auth/logout", tier: "standard", providers: ["meta"],
    limits: { images_per_day: 20, max_image_bytes: 4 * 1024 * 1024 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" },
    state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [],
  };
  const session: HostedSession = { account, error: "", refresh: async () => {}, call: vi.fn() as unknown as HostedSession["call"] };
  const unused = () => Promise.reject(new Error("not used"));
  const client = { analyze: unused, mask: unused, unmask: unused, maskImage: unused, createSession: unused, addKnownValues: unused } as unknown as RoutingClient;
  const engineState = { preference: "api", status: { state: "online", version: "0.1.0" }, endpointsMissing: false } as const;

  function renderHostedImages() {
    return render(
      <HostedSessionContext.Provider value={session}>
        <Images client={client} engineState={engineState} loadImage={loadImage} />
      </HostedSessionContext.Provider>,
    );
  }

  it("says the image is processed in memory on the Azure server, not stored, and what stays visible", () => {
    renderHostedImages();
    const note = screen.getByRole("note", { name: /how hosted images are processed/i });
    expect(note).toHaveTextContent(/processed in memory on our Azure server and is not stored/i);
    expect(note).toHaveTextContent(/not sent to any other service/i);
    expect(note).toHaveTextContent(/faces, ID photos and signatures are found on that server's CPU/i);
    expect(note).toHaveTextContent(/stamps are not detected here/i);
    expect(screen.queryByText(/SAM 3\.1 segments signatures/i)).not.toBeInTheDocument();
  });

  it("refuses an upload over the hosted limit before sending it", async () => {
    const user = userEvent.setup();
    renderHostedImages();
    const big = new File([new Uint8Array(4 * 1024 * 1024 + 1)], "big.png", { type: "image/png" });
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await user.upload(input, big);
    expect(await screen.findByText(/over 4 MB, the hosted service's limit/i)).toBeInTheDocument();
  });

  it("shows no hosted note in the local console", () => {
    render(<Images client={client} engineState={engineState} loadImage={loadImage} />);
    expect(screen.queryByRole("note", { name: /how hosted images are processed/i })).not.toBeInTheDocument();
  });
});
