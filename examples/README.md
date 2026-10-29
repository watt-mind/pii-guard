# Examples

## Connect an application

The [integration guide](../docs/integrations.md) and [runnable clients](integrations/)
cover cURL and the OpenAI Python SDK for self-hosted and hosted project endpoints,
streaming, credential boundaries and the self-hosted image path.

## Images that keep their meaning: "which parties have an ID?"

[`which_parties_have_an_id.py`](which_parties_have_an_id.py) sends one chat turn through the
gateway: a fictional sales contract naming three parties, the ID cards of two of them (one
printed in capitals, one expired) and the question. Everything is fictional
([ADR 0005](../docs/decisions/0005-synthetic-data-only.md)).

```bash
uv run python examples/which_parties_have_an_id.py                  # mocked upstream, no keys
uv run python examples/which_parties_have_an_id.py --render opaque  # the same with black boxes
uv run python examples/which_parties_have_an_id.py --live --out /tmp/demo   # Baseten, BASETEN_API_KEY
```

What happens on the way to the model:

1. The contract's names become placeholders (`Fiktív Mária` → `[[PERSON_a1b2c3]]`). The
   example pre-loads the parties as known values (`POST /v1/sessions`), as an application
   that knows its contract would.
2. Each card is masked in the **same vault session**. Its values are fuzzy-matched to the
   session's: `FIKTÍV` / `MÁRIA` under the card's captions is the contract's `Fiktív Mária`,
   so the card shows `[[PERSON_a1b2c3]]` where the name was, and `PHOTO · [[PERSON_a1b2c3]]`
   on the portrait. A near-namesake (`Fiktív Márta`) is never merged: a close but uncertain
   match gets a new placeholder and is flagged.
3. After each image the gateway adds a text part: the document summary (type, holder,
   `expired`, MRZ validity, placeholders only) and the masked transcript.
4. The model answers with placeholders; the gateway restores the names.

With placeholder labels the model can answer per party (present / expired / missing); with
opaque boxes it sees anonymous black rectangles and can't tie a card to anyone. Measured
answers and cost: milestone 27 of [the journey](../docs/journey.md).

The same works without the gateway: `POST /v1/mask/image` with `"session_id"` (and
`"render": "labels"`, the default) returns the labelled image, `transcript` and `summary`
([contracts](../docs/contracts.md#post-v1maskimage)). Set `PII_GUARD_IMAGE_RENDER=opaque` to
go back to solid boxes everywhere.

By default the example uses recorded OCR words and no SAM (faces and signatures stay
visible); `--ocr tesseract` and `--sam live` (`META_API_KEY`) run the full pipeline.
