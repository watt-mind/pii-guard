# Judge walkthrough: useful answers without forwarding the original values

A repeatable three-minute walkthrough, with an optional two-minute technical extension.
This is the live presentation runbook; [demo-script.md](demo-script.md) is the separate
submission-video shot list. Use only fictional text and the bundled **MINTA / SPECIMEN**
images. Never use a real identity document, even with the owner's permission.

The story: an assistant needs to reply to a person and understand an attached document.
Blanking everything destroys useful links; pii-guard replaces detected values with session
placeholders, lets the downstream model work with those links, and restores text values in
its answer. Show what crossed the downstream boundary before saying that it worked.

## Choose the route before presenting

| Route | What can be shown | What must be said |
|---|---|---|
| Self-hosted console, mock upstream | Live text masking, gateway round trip and streaming; bundled image recording | The upstream echoes masked text; this proves the transport and restoration, not generation quality. A recorded image run is labelled as a recording. |
| Self-hosted console, prepared real provider | The same text flow with a generated answer; live images only after image preflight below | Name the configured downstream and detector boundary. A provider key, model access or current quota is never assumed. |
| Hosted text experience | Curated anonymous text walkthrough, or signed-in editable text when enabled; configured project endpoints | The hosted service receives original text. It currently refuses image uploads/parts. Switch visibly to the self-hosted console or a recording for the image segment. |

The hosted service and self-hosting have different trust boundaries. Self-hosting puts the
original text and local detection in the operator's environment; the hosted service processes
original text on its server. Neither path establishes automatic GDPR compliance or
anonymisation. Detection can miss values, and context can still identify someone. The
[privacy model](privacy-model.md) and [hosted processing table](hosted.md#what-each-mode-processes)
are the reference for these statements.

## Preflight: prepare once, rehearse before every presentation

Record the checkout SHA with `git rev-parse HEAD`. Do preparation before screen sharing;
never show environment files, credentials, authentication headers or provider consoles.

### Reliable local baseline: no model or provider required

Prerequisites: a checkout, Python 3.12/`uv`, Node 22+ and `pnpm`. Ports 5173, 8787 and 8790
must be free. Run from the repository root:

```bash
uv sync --locked
pnpm --dir ui install --frozen-lockfile
uv run --no-sync python scripts/demo.py --mode rules --mock --traffic-log masked
```

Open `http://localhost:5173`. The startup banner must say **mock upstream** and **rules
only**. Select the live API engine in the console if it was previously set to Demo; confirm
`http://127.0.0.1:8787/healthz` returns success. This baseline deliberately uses the e-mail
rule and preloaded known values, so it needs no NER download and makes no claim about
free-text name detection. The image segment uses the bundled recording.

For the automatic free-text-name demonstration, prepare the NER ahead of time using
[the fast-mode setup](../README.md#try-it), then start:

```bash
uv sync --locked --extra ner
uv run --no-sync python scripts/demo.py --mode fast --mock --traffic-log masked
```

Fast mode can download about 1.1 GB on first use. Do that before the presentation. Confirm
`GET /v1/status` reports `ner.available: true` and `ner.state: "ready"`; the console must
name the loaded model. A rules-only banner is a signal to use the known-value baseline,
not evidence that automatic name detection succeeded. For an external downstream, follow
[the gateway configuration](operations.md#one-command-pii-guard-up), rehearse with fictional
data, and confirm the console no longer says mock. Keep its credentials off screen.

### Optional live image preparation

Use the existing [image setup](operations.md#segmenter-faces-on-the-device-signatures-on-sam-31):
Tesseract plus the `ocr` extra and Hungarian/English language data; a configured visual
segmenter; a tenant key for labelled rendering; and the text detectors required by the
chosen route. Provision models and authorized SAM access before rehearsing. Confirm
`GET /v1/status` reports `images.available: true`, then actually run the bundled ID card;
a configuration status alone does not prove inference will succeed.

The default hybrid path uses local YuNet for faces/photos and sends the image
as **normalized, unmasked pixels** to Meta SAM 3.1 for signatures (EXIF/metadata are stripped first). A missing local face detector can make hybrid use SAM for
faces too. Describe this as a detector service boundary, separate from the downstream model
that receives the masked image. Fully local segmentation cannot detect signatures/stamps;
with the default signature-mask policy it refuses the image. Do not relax policies or turn
OCR off just to obtain a successful demonstration.

For a replay, no OCR, SAM access or image model is needed: use a bundled sample and the
console's recorded-run fallback. Rehearse the fallback once and keep its recording label
visible. Recordings only support their exact bundled samples, not arbitrary uploads.

### If presenting hosted text

Use only an operator-confirmed origin. No URL, sponsored budget, model access or deployment
readiness is implied by this document. Before the audience arrives:

1. Open the hosted landing page and complete the curated text flow. If sponsorship is
   unavailable, use the local mock baseline above; do not improvise a sponsored route.
2. For editable text, sign in and verify the app shows the owner state and intended
   playground. An Azure “You have successfully signed in” page at `/.auth/login/done`
   confirms an authentication step, not a working app session. If shown, use **Return to
   website**, then verify the app session before continuing.
3. Verify any chosen project endpoint and provider using synthetic text. Endpoint
   configuration persisting is separate from the temporary vault session: do not promise
   restoration after a restart or session expiry.
4. Prepare a visibly separate self-hosted image segment or labelled recording. The hosted
   initial release does not accept images. See [hosted.md](hosted.md) and
   [projects.md](projects.md) for its actual scope.

## The three-minute story

The default route below is the local mock baseline, which works without provider/model
access. For a hosted presentation use the hosted text flow for beats 2–3, then explicitly
switch to the self-hosted recording for beat 4.

| Time | Exact action and expected result | Say |
|---|---|---|
| 0:00–0:20 | Open Playground → Text. State that every value is fictional. | “An assistant needs enough detail to help someone. pii-guard keeps detected identity values behind a boundary while preserving links the assistant can use.” |
| 0:20–0:55 | Replace the document with the Hungarian sentence below and choose Hungarian. Under **Known values**, add `Próba Zsuzsanna` as Person (`PERSON`). Click **Mask document**. Expect a PERSON placeholder for the name stem and an EMAIL placeholder; the Hungarian ending remains outside the person placeholder. Hover a placeholder to show the link. | “Here the application already knows its customer, so it preloads the name. This example uses rules and the vault, without an LLM detector. The same person gets a session placeholder, with the Hungarian ending kept outside it.” |
| 0:55–1:30 | Click **Send it to the model** to continue to Chat in that session. Send the same sentence. Inspect **What the model received**, then the answer. Expect placeholders upstream and the fictional name/e-mail restored in `Echo: …`; Chat streams the response. | “This is a real request through the gateway to an offline echo upstream. The upstream gets placeholders; the client gets restored text while the answer streams. With a prepared provider, the same boundary wraps generation.” |
| 1:30–2:15 | Switch to Playground → Images. Click the bundled **ID card**. If the server refuses it, click **Replay the recorded run instead**. Keep the live/recorded label visible. Inspect the covered portrait/signature/text regions and displayed region provenance. | “The image path covers regions and can label them with session placeholders, plus a masked transcript and document summary. That lets an assistant connect an ID to a party without seeing the covered values. This is [a live run / the bundled recorded run]. SAM, when used, sees normalized unmasked pixels as a detector.” |
| 2:15–2:40 | Open Evaluation and choose the relevant committed run/fixture set. Show the denominator and one weak dataset alongside the result. | “We measure leaks, over-masking and round trip on synthetic fixtures. A result belongs to its model and dataset; it does not prove that every new document is safe. The linked records make our limits inspectable.” |
| 2:40–3:00 | Return to the input → masked → restored view. Leave the repository link visible. | “Reversible text placeholders preserve useful answers, and labelled image masking preserves document relationships. Self-host it inside your boundary, or review the hosted service's different boundary. It is an open-source hackathon build, with measured limitations.” |

The exact synthetic sentence for beats 2–3:

```text
Kérem, írjon Próba Zsuzsannának a zsuzsa.proba@example.com címre.
```

Placeholder IDs vary by session and key. Check their relationship, not a hardcoded suffix.
If the prepared NER is ready, an optional second run can omit the known value to show
automatic detection. Say which detector ran; do not describe a preloaded name as an NER
result. If a value remains visible upstream, stop that example and show the miss honestly.

The Images screen alone demonstrates image masking. Claim a **live multimodal gateway
round trip** only after separately rehearsing an inline-image Chat/Responses request and
inspecting the masked request at the upstream. Use the self-hosted legacy root `/v1` route
without a nondefault project selection for inline images: configured project endpoints are
text-only in both hosted and self-hosted mode. A standalone mask result is not that proof.
Labelled image rendering does not reconstruct the original portrait, signature or pixels;
text restoration uses the vault. The Images screen also does not prove that its session is
the same as the Text screen's: cross-modal consistency requires the same explicit session.

## Optional extension: minutes three to five

1. **A client behind the gateway (about 45 seconds).** Use the following deterministic
   request in a second terminal while the baseline runs, then open its entry in **Logs**.
   The client receives `Echo: Please reply to demo.sender@example.com.` while the masked
   request/response in Logs contain an EMAIL placeholder. This is the core base-URL
   integration, with no provider key:

   ```bash
   curl --fail-with-body --silent --show-error \
     http://127.0.0.1:8787/v1/chat/completions \
     -H 'Content-Type: application/json' \
     --data-binary @- <<'JSON'
   {"model":"pii-guard-mock","messages":[{"role":"user","content":"Please reply to demo.sender@example.com."}],"stream":false}
   JSON
   ```

   For actual agents and tool calls use the already documented
   [coding-agent harness](../examples/coding-agents/README.md) or
   [Muse Code setup](integrations/muse-code.md). Rehearse the exact installed client version
   first. Do not turn a pre-existing run record into a claim about today's live request.
2. **Cross-modal depth (about 45 seconds, only when prepared).** Start a text session,
   preload a party's known value, then send the bundled specimen through
   [`POST /v1/mask/image`](contracts.md) with that explicit `session_id` and `render=labels`.
   Inspect the returned `session_id`, region `placeholder`/`match`, masked `transcript` and
   `summary`. Claim a match only where those fields show it. An `uncertain` match gets a new
   placeholder rather than guessing. Show the covered PNG; do not promise pixel recovery.
3. **The engineering tradeoff (about 30 seconds).** Show [models.md](models.md): XLM-R NER
   distilled from Glimmer labels for the fast path, SAM 3.1 for visual segmentation, optional
   remote audit detection. The model actually used must match the status/run record. Close
   on [privacy-model.md](privacy-model.md): local detection, remote detection and downstream
   generation are separate boundaries.

## Recovery and recording plan

| Failure during rehearsal or presentation | Repeatable fallback and truthful narration |
|---|---|
| Provider unavailable, sponsored allowance disabled or model access absent | Restart the local baseline with `--mock`. Say “offline echo upstream”; show the upstream placeholders and restored echo. A mock never proves a generated answer's quality. |
| NER not installed/ready | Use `--mode rules --mock` and preload the fictional known value. Say “rules plus a known value”; do not claim automatic free-text name detection. |
| OCR, visual segmenter or SAM unavailable | Show the refusal, then choose the bundled sample's recorded-run fallback. Say “recorded regions for this exact specimen”; do not upload another image or imply inference just ran. |
| Hosted login ends on the Azure success page | Use **Return to website**, verify owner state. If the app session is unavailable, switch to the pre-rehearsed local baseline; do not call the authentication success page the completed demo. |
| Network or browser breaks entirely | Play a previously captured local recording with its checkout SHA, route, detector/model names and date in the opening slate. Keep the mock/recorded-image labels in frame. Say “recording”, then show the matching source/evidence files. |

Capture the fallback video before the event: the six beats above, using only the bundled
specimen and the synthetic sentence. Use separate visible slates for hosted text,
self-hosted text and recorded/live images. Record only the application window, and inspect
the full video for credentials, account information, unrelated tabs or real personal data
before sharing it. Store no real credentials or personal screenshots in the repository.
No video is provided by this runbook; recording and the final submission link are owner
presentation steps.

## Evidence to keep beside the presentation

- [Gateway contract](architecture-gateway.md),
  [stream restoration tests](../tests/vault/test_vault_stream.py) and the
  [mock upstream](../src/pii_guard/bench/mock_upstream.py) support the text story.
- [Image API](../src/pii_guard/api/routes/image.py),
  [specimen provenance](../eval/fixtures/visual/generation.json),
  [recording engine](../ui/src/api/imageMock.ts) and
  [image comparison results](../eval/results/2026-10-27-image-baselines/README.md) support
  the image story. Printed text on security-patterned IDs remains a known OCR weakness.
- [Benchmarks](benchmarks.md), [model limitations](../training/ner/model-card.md#limitations)
  and [why-pii-guard.md](why-pii-guard.md) supply dataset-specific evidence. Read the current
  run records before quoting a number; this runbook intentionally fixes no headline metric.
