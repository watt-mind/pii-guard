# Design: pii-guard console

The locked design system for `ui/`. Every screen follows it; extend this file when the system
needs to grow instead of styling one screen on its own. Tokens live in `src/index.css`.

## Genre and tone

Modern-minimal developer console: calm, light, precise. Light is the first look (README
screenshots, the default for a new visitor); dark is a full equal derived from the same
family, not an inversion. "System" stays available in the theme toggle.

The look and feel follows the account console of a hosted inference provider
(reference: https://app.fireworks.ai/account/home, measured 2026-10-28): white paper, warm
neutrals, a plum-black primary, a magenta-plum accent family and a light neo-grotesk. Only
the feel is shared. The name, logo, copy and fonts are pii-guard's own; no marks, logos or
proprietary fonts of the reference are used.

## Colour carries meaning

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--canvas`, `--surface` | `#ffffff` | `#121110`, `#191816` | page, cards, panes |
| `--surface-2`, `--surface-3` | `#f9f7f5`, `#f4f0ec` | `#211f1d`, `#2a2725` | active nav item, pane headers, subtle fills, hover |
| `--ink` | `#1e1d1b` | `#f3f0ec` | text, focus ring |
| `--muted`, `--faint` | `#595959`, `#6b6762` | `#b3ada7`, `#948e88` | secondary text, hints and group labels |
| `--line`, `--line-strong` | `#eeeeee`, `#e2ddd8` | `#2a2826`, `#3a3633` | hairlines on cards and dividers (decorative) |
| `--field` | `#8f8780` | `#807973` | the outline of inputs, selects and text areas (3:1) |
| `--primary` / `--on-primary` | `#280016` / white | `#f6dcec` / `#280016` | the primary action, selected segment |
| `--accent` family | `#a71e7e` | `#ec7fc4` | badges, the header hairline; never a state |
| `--guard` | `#047a56` (dot `#05aa77`) | `#3fd6a0` | protected: the boundary, a live connection, values put back |

The header hairline is `--accent-gradient` (`#ff7c57` → `#a71e7e` → `#610a45`, 92°) at 35 %
over a soft peach-pink wash, 4 px under the page header.

What happened to a value keeps its own tokens, so components never name a hue:

| Token | Means | Used for |
|---|---|---|
| `--masked` | replaced by a placeholder | original values on your side, placeholders on the model's side |
| `--restored` | real value put back | restored values in answers |
| `--kept` | detected, left in place by policy | dashed outline, no fill |
| `--blocked` | fail closed: nothing was sent | blocked notices, refused calls |
| `--leak` | a value reached the model unmasked | unresolved placeholders, leak figures |
| `--model` | the model's side of the boundary | pane headers and labels |
| `--focus` | keyboard focus | neutral ink, so it never reads as a state |

Status hues follow the reference family, darkened where they carry text: green `#05aa77`
(dots) / `#047a56` (text), red `#d2192d` (reference `#fd293e`), orange `#9a5300` (reference
`#f98d00`), blue `#005fc7` (reference `#007aff`).

Entity types are never told apart by hue: the type is always written (`[[EMAIL_…]]`, "Email").
Charts use the categorical slots `--series-1…8` in fixed order (dataviz reference palette,
unchanged by the restyle); the live-traffic stages take slots 1 to 7 and the upstream is a warm
neutral. Seventeen entity types fold into five families for charts (`ENTITY_GROUPS` in
`src/lib/entities.ts`). Status colours are never chart series. The recall heatmap ramps from
the surface to `--heat` (`#4a8ade` light, `#2c66bd` dark), tuned so its ink text keeps 4.5:1 on
every step.

## Contrast (WCAG 2.2 AA)

Text needs 4.5:1, large text and UI outlines 3:1. Measured with the WCAG relative-luminance
formula.

| Pair | Light | Dark |
|---|---|---|
| ink on canvas | 16.8 | 16.6 |
| ink on surface-2 | 15.8 | 14.5 |
| muted on surface | 7.0 | 8.0 |
| faint on surface-2 (worst case for hints) | 5.3 | 5.1 |
| on-primary on primary (button text) | 19.1 | 14.9 |
| white on accent (badge text) | 6.7 | n/a |
| accent on surface (accent text) | 6.7 | 7.1 |
| guard on surface (restored, protected text) | 5.4 | 9.6 |
| model on model-soft (model pane labels) | 5.5 | 7.7 |
| warn on warn-soft (blocked notices) | 5.3 | 8.8 |
| danger on danger-soft (leak, errors) | 4.6 | 6.6 |
| field on surface (control outline, 3:1) | 3.5 | 4.1 |
| ink on the recall heatmap, worst step | 5.1 | 5.2 |
| focus ring (ink) on canvas | 16.8 | 16.6 |

Hairlines (`--line`) are decorative: cards and dividers are identified by their content, not
their border. The live dot (`--guard-dot`, 3.0:1) always sits next to its written label. The
active nav item is marked by `aria-current`, its fill and a 500 weight, not by fill alone.

## Type

- **Geist** for interface text and **Geist Mono** for documents, placeholders, values, codes
  and the boundary labels ("Inside your network", "Sent to the model"), both self-hosted from
  `@fontsource-variable/*` (SIL OFL 1.1, latin-ext included for Hungarian).
- Why Geist: the reference uses Monument Grotesk, a commercial neo-grotesk. Geist is the
  closest open match in proportion and tone (a neutral, slightly squared grotesk with open
  apertures that stays clean at 14 px and light at 400/500), and it ships a mono with the same
  metrics, so values sit on the same rhythm as labels. Hanken Grotesk was the alternative; it
  is rounder and warmer, further from the reference, and has no matching mono.
- Scale: `text-2xs` (11 px) · `text-xs` (12 px, subtitles) · `text-ui` (13 px) · `text-sm`
  (14 px, body and controls) · `text-base` (16 px, header bar) · `text-lg` (18 px, card and
  section titles) · `text-2xl` (24 px, the one page heading). No other sizes.
- Weights stay light: 400 for body, card titles and buttons; 500 for page headings, labels and
  the active nav item. Never 600 or bold. Headings are never italic. Line height 1.4.
- Labels are sentence case. The only uppercase is the sidebar group labels (Inspect, Set up,
  Measure: 11 px, 500, 0.04 em tracking, faint) and badges.

## Shape and depth

- Radii: `rounded-sm` (4 px) for chips, highlights and nav items; `rounded-md` (6 px) for
  badges and segment buttons; `rounded-lg` (10 px) for the primary button and inputs;
  `rounded-control` (12 px) for secondary "quick action" buttons and the popover; `rounded-xl`
  (20 px) for cards and panes. `rounded-full` only for dots and the boundary mark.
- Depth comes from hairlines and the surface steps, never shadows. The only shadow is the
  floating popover.
- No card inside a card: empty states and notes inside a panel are plain text.

## Components

- **Primary button:** `bg-primary text-on-primary`, 10 px radius, 12 px side padding, 14 px
  at 400, darker plum on hover.
- **Secondary button:** white, 1 px `--line` border, 12 px radius, 16 px side padding; the
  border and a warm fill deepen on hover.
- **Cards and panes:** white, 1 px `--line`, 20 px radius, 16 to 20 px padding, title 18/400
  and a 12 to 14 px muted subtitle.
- **Sidebar:** 216 px (13.5 rem) from 1024 px, no fill, a 1 px line on its right. Items are
  14 px with a 16 px icon, ink coloured; the active one has the `--surface-2` fill and a 4 px
  radius. Groups (Inspect, Set up, Measure) keep the sections in their order; Overview stands
  alone at the top. Hints under each label show only in the phone menu.
- **Page header:** a 48 px bar with the section (and Playground tab) over the accent hairline,
  from 1024 px. Below that width the menu's top bar names the section and the hairline sits
  under it.
- **Inputs:** 10 px radius, `--field` outline, white fill (text areas `--surface-2`).
- **Segments and tabs:** the selected segment is `bg-primary`; tabs keep the ink underline.

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
