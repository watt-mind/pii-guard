# Design: pii-guard demo UI

The locked design system for `ui/`. Every screen follows it; extend this file when the system
needs to grow instead of styling one screen on its own. Tokens live in `src/index.css`.

## Genre and tone

Modern-minimal developer tool: precise, quiet, dense. Dark is the primary look (README and
video); light is a full equal, not an inversion.

## Colour carries meaning

One accent, the guard green (`--guard`), for "protected": the boundary, a live connection,
values put back. Everything else is ink on graphite (dark) or warm paper (light).

| Token | Means | Used for |
|---|---|---|
| `--masked` | replaced by a placeholder | original values on your side, placeholders on the model's side |
| `--restored` | real value put back | restored values in answers |
| `--kept` | detected, left in place by policy | dashed outline, no fill |
| `--blocked` | fail closed: nothing was sent | blocked notices, refused calls |
| `--leak` | a value reached the model unmasked | unresolved placeholders, leak figures |
| `--model` | the model's side of the boundary | pane headers and labels |
| `--focus` | keyboard focus | neutral ink, so it never reads as a state |

Entity types are never told apart by hue: the type is always written (`[[EMAIL_…]]`, "Email").
Charts use the categorical slots `--series-1…8` in fixed order (dataviz reference palette);
the live-traffic stages take slots 1 to 7. Seventeen entity types fold into five families
for charts (`ENTITY_GROUPS` in `src/lib/entities.ts`). Status colours are never chart series.

## Type

- Instrument Sans for interface text; JetBrains Mono for documents, placeholders, values,
  codes and the boundary labels ("Inside your network", "Sent to the model").
- Scale: `text-2xs` (11 px) · `text-xs` · `text-ui` (13 px) · `text-sm` · `text-base` ·
  `text-lg` · `text-2xl/3xl` for the one page heading. No other sizes.
- Weights: 400 body, 500 labels and controls, 600 headings only. Headings are never italic.
- Labels are sentence case. No uppercase tracked eyebrows.

## Shape and depth

- Three radii: `rounded-sm`/`md` (3 to 4 px) for chips and highlights, `rounded-lg` (6 px) for
  controls, `rounded-xl` (8 px) for panels. `rounded-full` only for dots and the boundary mark.
- Depth comes from hairline borders and the surface steps, not shadows. The only shadow is
  the floating popover.
- No card inside a card: empty states and notes inside a panel are plain text.

## Motion

120 ms colour transitions on controls, `--ease-out`. Restored values flash once. Everything
collapses under `prefers-reduced-motion`.

## Copy

English UI. Hungarian appears only as content of a Hungarian sample, and sample titles lead
in English. Say what ran ("4 values masked by Rules + checksum"), never what might have.
