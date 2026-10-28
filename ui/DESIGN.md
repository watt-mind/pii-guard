# Design: pii-guard console

The locked design system for `ui/`. Every screen follows it; extend this file when the system
needs to grow instead of styling one screen on its own. Tokens live in `src/index.css`.

## Genre and tone

Modern-minimal developer console: calm, light, precise. Light is the first look (README
screenshots, the default for a new visitor); dark is a full equal derived from the same
family, not an inversion. "System" stays available in the theme toggle.

The look and feel follows the account console of a hosted inference provider
(reference: https://app.fireworks.ai/account/home, measured 2026-10-28): a warm off-white canvas
under white cards, warm neutrals, a plum primary, a magenta-plum accent family and a light neo-grotesk. Only
the feel is shared. The name, logo, copy and fonts are pii-guard's own; no marks, logos or
proprietary fonts of the reference are used.

## Colour carries meaning

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--canvas`, `--surface` | `#faf9f7`, `#ffffff` | `#121110`, `#191816` | page; cards and panes (white on the warm canvas) |
| `--surface-2`, `--surface-3` | `#f5f2ef`, `#eeeae5` | `#211f1d`, `#2a2725` | active nav item, pane headers, subtle fills, hover |
| `--ink` | `#1e1d1b` | `#f3f0ec` | text, focus ring |
| `--muted`, `--faint` | `#57524d`, `#6b6762` | `#b3ada7`, `#948e88` | secondary text, hints and group labels |
| `--line`, `--line-strong` | `#e6e1dc`, `#d6cfc8` | `#33302d`, `#45403c` | hairlines on cards and dividers (decorative, about 1.3:1); the stronger one for segment rings and secondary button borders |
| `--field` | `#8f8780` | `#807973` | the outline of inputs, selects and text areas (3:1) |
| `--primary` / `--on-primary` | `#5c0a3f` / white | `#b8468f` / white | the primary action: a plum button with white text in both themes |
| `--accent` family | `#a71e7e` | `#ec7fc4` | brand only: badges, the wordmark, the header hairline; never a state, never a placeholder |
| `--guard` | `#047a56` (dot `#05aa77`) | `#3fd6a0` | protected: the boundary, a live connection, values put back |

Every neutral is warm (red above blue): no pure greys. The header hairline is `--accent-gradient` (`#ff7c57` → `#a71e7e` → `#610a45`, 92°) at 35 %
over a soft peach-pink wash, 4 px under the page header. The gradient is for the hero and the
wordmark only, never a button.

What happened to a value keeps its own tokens, so components never name a hue:

| Token | Means | Used for |
|---|---|---|
| `--masked` | replaced by a placeholder | original values on your side, placeholders on the model's side |
| `--restored` | real value put back | restored values in answers |
| `--kept`, `--kept-ink` | detected, left in place by policy | dashed outline in `--kept` (3:1, the same grey as `--field`), no fill; "kept" labels and chip text in `--kept-ink` (4.5:1) |
| `--blocked` | fail closed: nothing was sent | blocked notices, refused calls |
| `--leak` | a value reached the model unmasked | unresolved placeholders, leak figures |
| `--model` | the model's side of the boundary | pane headers and labels |
| `--focus` | keyboard focus | neutral ink, so it never reads as a state |

Status hues follow the reference family, darkened where they carry text: green `#05aa77`
(dots) / `#047a56` (text), red `#c8331c` (an orange-red, so it never reads as the brand magenta), orange `#9a5300` (reference
`#f98d00`), blue `#005fc7` (reference `#007aff`).

Entity types are never told apart by hue: the type is always written (`[[EMAIL_…]]`, "Email").
Charts use the categorical slots `--series-1…8` in fixed order: blue, rose, violet, brown, teal,
red, slate, green. Every slot is 3:1 or more on its surface in both themes, adjacent slots stay
apart under deutan, protan and tritan simulation, and slots 1 to 5 avoid the status hues (no green,
red or amber). The live-traffic stages take slots 1 to 5 in pipeline order, then unmask takes the
green slot (values put back) and the response the slate one; the red slot is never a stage. The
upstream is a warm neutral. Seventeen entity types fold into five families for charts (`ENTITY_GROUPS` in
`src/lib/entities.ts`). Status colours are never chart series. The recall heatmap ramps from
the surface to `--heat` (`#4a8ade` light, `#2c66bd` dark), tuned so its ink text keeps 4.5:1 on
every step.

## Contrast (WCAG 2.2 AA)

Text needs 4.5:1, large text and UI outlines 3:1. Measured with the WCAG relative-luminance
formula.

| Pair | Light | Dark |
|---|---|---|
| ink on canvas | 16.0 | 16.6 |
| ink on surface-2 | 15.1 | 14.5 |
| muted on surface | 7.7 | 8.0 |
| muted on canvas | 7.3 | 8.5 |
| faint on surface-2 (worst case for hints) | 5.0 | 5.1 |
| on-primary on primary (button text) | 13.4 | 4.9 |
| on-primary on primary-hover | 10.7 | 5.8 |
| white on accent (badge text) | 6.7 | n/a |
| accent on surface (accent text) | 6.7 | 7.1 |
| guard on surface (restored, protected text) | 5.4 | 9.6 |
| model on model-soft (model pane labels) | 5.5 | 7.7 |
| warn on warn-soft (blocked notices) | 5.3 | 8.8 |
| danger on surface | 5.3 | 7.4 |
| danger on danger-soft (leak, errors) | 4.7 | 6.5 |
| masked on masked-soft (placeholders) | 5.0 | 6.3 |
| kept-ink on surface-2 ("kept" chips) | 4.9 | 6.1 |
| kept on surface (dashed outline, 3:1) | 3.5 | 3.7 |
| field on surface (control outline, 3:1) | 3.5 | 4.1 |
| field on canvas | 3.4 | 4.4 |
| chart series, worst slot on surface (3:1) | 3.9 | 3.6 |
| line on surface (decorative, about 1.3) | 1.3 | 1.35 |
| ink on the recall heatmap, worst step | 5.1 | 5.2 |
| focus ring (ink) on canvas | 16.0 | 16.6 |

`src/palette.test.ts` reads these tokens from `src/index.css` and asserts every ratio above (and
the hue rules for the chart slots, danger and the primary), so a token change that breaks one
fails CI.

Hairlines (`--line`) are decorative: cards and dividers are identified by their content, not
their border. The live dot (`--guard-dot`, 3.0:1) always sits next to its written label. The
active nav item is marked by `aria-current`, its fill and a 500 weight, not by fill alone.

## Type

- **Geist** for interface text and **Geist Mono** for documents, placeholders, values, codes
  and the boundary labels ("Inside your network", or "Your input" on the hosted console, where the
  input is processed on our server; "Sent to the model"), both self-hosted from
  `@fontsource-variable/*` (SIL OFL 1.1, latin-ext included for Hungarian).
- Why Geist: the reference uses Monument Grotesk, a commercial neo-grotesk. Geist is the
  closest open match in proportion and tone (a neutral, slightly squared grotesk with open
  apertures that stays clean at 14 px and light at 400/500), and it ships a mono with the same
  metrics, so values sit on the same rhythm as labels. Hanken Grotesk was the alternative; it
  is rounder and warmer, further from the reference, and has no matching mono.
- Scale (no other sizes, no arbitrary `text-[…]`):

  | Role | Class | Size / line height / weight |
  |---|---|---|
  | Page title (`h1`, exactly one per screen, `PageHeader`) | `text-2xl font-medium` | 24 / 32 / 500 |
  | Lead under the page title | `text-sm sm:text-base text-muted`, `max-w-3xl` | 14→16 / 20→24 / 400 |
  | Card and pane title (`h2`, or `h3` inside a section) | `text-lg font-normal` | 18 / 28 / 400 |
  | Metric value (`Metric`) | `text-lg font-medium tabular-nums` | 18 / 28 / 500 |
  | Header bar | `text-base` | 16 / 24 / 400 |
  | Body, controls, table cells, card subtitles | `text-sm` | 14 / 20 / 400 |
  | Item title, step title, field label, emphasis | `text-sm font-medium` | 14 / 20 / 500 |
  | Help text, hints, metric label | `text-xs text-muted` | 12 / 16 / 400 |
  | Dense meta text, code blocks and text areas | `text-ui` | 13 / 20 |
  | Documents (`.doc`: masked and restored text) | `.doc` | 13 / 24 (1.85), so highlights on adjacent lines don't touch |
  | Group label, badge, pane eyebrow | `text-2xs` (+ `uppercase tracking-[0.04em]` for sidebar groups only) | 11 / 16 / 500 |

  Mono (`font-mono`) is for values, codes, IDs and documents, never for counts.
- Weights stay light: 400 for body, card titles and buttons; 500 for page headings, labels and
  the active nav item. Never 600 or bold (chart labels included). Headings are never italic.
  Line height 1.4.
- Labels are sentence case. The only uppercase is the sidebar group labels (Inspect, Set up,
  Measure: 11 px, 500, 0.04 em tracking, faint) and badges.

## Shape and depth

- Radii: `rounded-sm` (4 px) for chips, highlights and nav items; `rounded-md` (6 px) for
  badges, code blocks and segments; `rounded-lg` (10 px) for every button, input, select,
  notice and segmented track; `rounded-control` (12 px) for the popover only; `rounded-xl`
  (20 px) for cards and panes. `rounded-full` only for dots, avatars and the boundary mark.
- Spacing (Tailwind steps, 4 px base):

  | Step | Use |
  |---|---|
  | 4 (`gap-1`, `mt-0.5`/`mt-1`) | label and value, title and subtitle |
  | 8 (`gap-2`) | inline controls, chips, button rows |
  | 12 (`py-3`) | pane and list-header vertical padding |
  | 16 / 20 (`p-4 sm:p-5`) | **every** card and pane inset, its header included |
  | 24 (`gap-6`, `space-y-6`) | between cards, grid columns and sections |
  | 32 (`pt-8`) | header bar to the page title |

- Depth comes from hairlines and the surface steps, never shadows. The only shadow is the
  floating popover.
- No card inside a card: empty states and notes inside a panel are plain text.

## Components

Every screen builds from these, in `src/components/ui.tsx` (class names for elements that are
not a `<button>` in `src/components/controls.ts`). There are no element-selector stylesheets for
controls; the hosted landing uses the same components. `className` on a component is for layout
only (width, margin, flex): it never changes colour, height or radius, because classes are not
merged.

- **`Button`** `variant`: `primary` (plum fill and white text in both themes, never the gradient, the one main action of a form or pane),
  `secondary` (surface, `--line-strong` border deepening to `--field` on hover), `ghost` (text
  only, low-weight actions inside a pane) and `danger` (red text and border: destructive actions
  and their confirmation). `size`: `sm` 32 px, `md` 36 px; both become 44 px on a coarse pointer
  (`pointer-coarse:`), so touch sizing follows the device, not hosted or local mode or the window
  width (the header's project switcher and avatar included). Icons are 16 px line glyphs at a
  1.5 stroke; only the 24 px brand and boundary marks are heavier. Every
  button has the 10 px radius and 14 px text at 400. `busy` keeps it focusable (`aria-disabled`,
  clicks ignored), so keyboard focus is never dropped while work runs. `ButtonLink` is the same
  look on an `<a>`, for navigation.
- **`Field`** wraps one control with its label (14/500), an optional hint (12 px muted, linked by
  `aria-describedby`, never inside the label), an error slot (12 px danger) and a required
  marker. **`Input`**, **`Select`** and **`Textarea`** share the height (36 px, `sm` 32 px,
  44 px on touch), the 10 px radius, the `--field` outline and the neutral focus ring; text areas
  are 13 px mono on `--surface-2`. `Select` draws one chevron of its own (`appearance: none`, the
  `--chevron` token, 10 px from the right edge) and keeps `pr-8`, so the arrow's room is reserved once.
  Disabled buttons and controls take no hover (`not-disabled:hover:`).
- **`Checkbox`**: a native 16 px checkbox with the primary as its accent and its label beside it.
- **`SegmentedControl`**: native radios in a `radiogroup` (one tab stop, arrow keys). The track is
  `--surface-2`; the selected segment is a raised `--surface` with a `--line-strong` ring and ink
  text, never the primary fill, so it can't be mistaken for an action. Switching between panels
  stays a tab list with the ink underline.
- **`ConfirmAction`**: every destructive action (revoke a key, disconnect a provider, disable an
  endpoint, drop a session) takes two steps. The trigger opens an inline box naming the object
  and the consequence ("Revoke key 'ci'? Apps using it stop working."); the `danger` button takes
  focus; Cancel and Escape return focus to the trigger. After the action the screen announces the
  result and moves focus to the list it changed. Verbs: Revoke (keys), Disconnect (provider
  connections), Disable (endpoints), Drop (vault sessions).
- **`Notice`** `tone`: `info`, `warn`, `danger`, `success`; `live` makes it a status (polite) or
  an alert. It replaces ad-hoc error paragraphs. Create, save and connect confirm with a live
  `success` notice ("Endpoint 'Support bot' created."). `BlockedNotice` is the fail-closed variant
  for gateway errors; the hosted console shows its code and mapped copy only, never server text.
- **`SecretReveal`**: a copy-once secret. A warning box, announced, focus on Copy; "Copied" shows
  on the button; dismissing an uncopied secret asks first.
- **`Metric`**: a label (12 px muted) over a value (18/500 tabular): one look for every count,
  latency and total.
- **`PageHeader`**: the screen's one `h1`, the section name as the menu says it, and its lead
  sentence. Playground's tabs and their views sit below it.
- **`Pane`** pairs (Text, Images): the header holds only the eyebrow and title (a Copy action at
  most), so side-by-side headers are equal at every width; the controls for the input (language,
  Run, Show regions) sit in a toolbar row above the panes. Grids inside a column that sits beside
  another (Logs' call detail) use container queries (`@container`, `@2xl:`, `@3xl:`) so they follow
  the column, not the viewport.
- **Visually hidden inputs** (`sr-only` radios and checkboxes in sample cards and chips) are
  absolutely positioned: their label is always `relative`, or the input escapes a horizontal
  scroller and widens the page.
- **First paint** waits (at most 1.2 s) until the engine, the traffic log and, on a hosted
  Overview, the setup list have answered, and `<main>` is at least a viewport tall, so notices and
  late cards never push a painted page down (CLS under 0.1 on every screen).
- **Hosted setup list** (Overview): one ordered list (model → policy → endpoint → endpoint key →
  first call) ticked from the owner's own data, with one primary button: the next step.
- **`Card`**: white (`--surface`) on the warm canvas, 1 px `--line`, 20 px radius, `p-4 sm:p-5`, an 18/400 title and a 14 px muted
  subtitle (`mt-0.5`). `Pane` uses the same insets and title; side-by-side cards share them so
  their titles line up.
- **`KeyValues`**: label/value rows with a fixed 8.5 rem label column (one column below 640 px),
  so neighbouring cards line up.
- **Sidebar:** 216 px (13.5 rem) from 1024 px, no fill, a 1 px line on its right. Items are 14 px
  with a 16 px icon, ink coloured; the active one has the `--surface-2` fill and a 4 px radius.
  Groups (Inspect, Set up, Measure) keep the sections in their order; Overview stands alone at
  the top. Hints under each label show only in the phone menu.
- **Brand row:** 48 px from 1024 px, the height of the page header bar, in the nav items'
  gutter so the mark sits over their icons: a 24 px shield glyph (no tile) and "pii-guard" in
  Geist 16/500. The product is always written "pii-guard": console, landing and copy.
- **Sidebar footer:** the Engine select, then the connection as a quiet line beside the theme
  control: a 6 px dot and the API version in muted 12 px, with "API connected · fast mode ·
  rules" in the tooltip (a click checks again). The label only appears when something differs:
  "Demo mode" in orange when the demo engine answers, in red when the API is down and nobody
  chose the demo engine. Only that case also turns the notice above the content red ("API not
  reachable.").
- **Page header bar:** 48 px with the section (and Playground tab) over the accent hairline, from
  1024 px. Below that width the menu's top bar names the section and the hairline sits under it.
- **Hosted landing:** composed from the console's own components, so it can't drift from the
  dashboard: `Logo` and the 56/48 px header over the `header-hairline`, `Card`, `Pane` and
  `Boundary` for the demo (your text → pii-guard → sent to the model, then the model's answer →
  pii-guard → restored), `MaskedText`, `RestoredText`, `Placeholder` and `Legend` for values,
  `Notice`, `Metric`, `KeyValues`, `Badge`, `Field`, `SegmentedControl` and `ThemeToggle`.
  Values are marked exactly as in the Playground: a value in your text and its placeholder are
  masked blue (`meta.mark`, `<Placeholder>`), a value put back is restored green. The image
  showcase draws regions like the Images screen. Layout is Tailwind only (`max-w-[1280px] px-4
  sm:px-6`, `gap-6` between cards, `space-y-16 lg:space-y-24` between sections); there is no
  landing stylesheet. Section titles are the console's 24/500; the one landing-only size is the
  hero `h1`, `text-3xl sm:text-5xl font-medium leading-tight` (30→48 / 1.25 / 500, no tracking,
  all ink). One primary button per card or hero; the header's sign-in is secondary. Below 1024 px
  the hero's mini flow is hidden (the demo follows). Below-the-fold modules that weigh more (the
  image showcase, the comparison chart) are lazy-loaded. The hosted build follows the system
  theme until a visitor picks one in the footer (the local console starts light).

## Motion

120 ms colour transitions on controls, `--ease-out`. Restored values flash once. Everything
collapses under `prefers-reduced-motion`.

## Screenshots

README screenshots (`docs/assets/demo/`) come from `pii-guard up --mock` (rules only, the
built UI copied to `src/pii_guard/_ui/`), with `scripts/demo_traffic.py` sent through it, in
the light theme, captured by headless Chromium at 1440 × 900 (phone shots 375 × 812 at 2×)
and encoded with `cwebp -q 82`. `demo.webp` is six of those frames at 2.4 s each
(`img2webp -lossy -q 78`): Overview, Text masked and then scrolled to the output, Chat, Logs, Connect.

## Copy

English UI. Hungarian appears only as content of a Hungarian sample, and sample titles lead
in English. Say what ran ("4 values masked by Rules + checksum"), never what might have.
