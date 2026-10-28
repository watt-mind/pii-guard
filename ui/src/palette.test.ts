// The palette's contrast contract (LAB-1464, ui/DESIGN.md "Contrast"). Reads the tokens straight
// from src/index.css, light at :root and dark under .dark, so a token change that breaks a ratio
// fails here instead of in an audit.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Read from disk: the test config turns CSS imports off (css: false).
const read = (path: string) => readFileSync(join(import.meta.dirname, path), "utf-8");
const css = read("index.css");
const controls = read("components/controls.ts");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no ${selector} block in index.css`);
  const body = css.slice(start, css.indexOf("\n}", start));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/^\s*--([\w-]+):\s*([^;]+);/gm)) if (m[1] && m[2]) out[m[1]] = m[2].trim();
  return out;
}

const LIGHT = block(":root");
const DARK = { ...LIGHT, ...block(".dark") };
const THEMES = { light: LIGHT, dark: DARK } as const;
type Theme = keyof typeof THEMES;
type RGB = [number, number, number];

function parse(value: string, theme: Theme, over?: RGB): RGB {
  const v = value.trim();
  const ref = /^var\(--([\w-]+)\)$/.exec(v);
  if (ref?.[1]) return parse(token(theme, ref[1]), theme, over);
  const hex = /^#([0-9a-f]{6})$/i.exec(v);
  if (hex) return [0, 2, 4].map((i) => parseInt((hex[1] ?? "").slice(i, i + 2), 16)) as RGB;
  const rgba = /^rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)\)$/.exec(v);
  if (rgba) {
    // A translucent fill is measured where it is drawn: over the surface.
    const base = over ?? color(theme, "surface");
    const a = Number(rgba[4]);
    return [1, 2, 3].map((i, k) => Number(rgba[i]) * a + (base[k] ?? 0) * (1 - a)) as RGB;
  }
  throw new Error(`cannot measure ${v}`);
}

function token(theme: Theme, name: string): string {
  const v = THEMES[theme][name];
  if (v === undefined) throw new Error(`--${name} is not defined (${theme})`);
  return v;
}

const color = (theme: Theme, name: string): RGB => parse(token(theme, name), theme);

function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(a: RGB, b: RGB): number {
  const [la, lb] = [luminance(a), luminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const contrast = (theme: Theme, fg: string, bg: string) => ratio(color(theme, fg), color(theme, bg));

function hsl([r, g, b]: RGB): { h: number; s: number } {
  const [R, G, B] = [r / 255, g / 255, b / 255];
  const max = Math.max(R, G, B);
  const min = Math.min(R, G, B);
  const d = max - min;
  const l = (max + min) / 2;
  if (d === 0) return { h: 0, s: 0 };
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === R ? ((G - B) / d) % 6 : max === G ? (B - R) / d + 2 : (R - G) / d + 4;
  return { h: (h * 60 + 360) % 360, s };
}

const hueGap = (a: number, b: number) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b));
const SERIES = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `series-${n}`);

describe.each(["light", "dark"] as const)("palette contrast (%s)", (theme) => {
  it.each([
    // [foreground, background, minimum]: text 4.5, large text and UI outlines 3.
    ["ink", "canvas", 4.5],
    ["ink", "surface-2", 4.5],
    ["muted", "surface", 4.5],
    ["muted", "surface-2", 4.5],
    ["faint", "surface", 4.5],
    ["faint", "surface-2", 4.5],
    ["on-primary", "primary", 4.5],
    ["accent", "surface", 4.5],
    ["guard", "surface", 4.5],
    ["model", "model-soft", 4.5],
    ["masked", "masked-soft", 4.5],
    ["warn", "warn-soft", 4.5],
    ["danger", "surface", 4.5],
    ["danger", "danger-soft", 4.5],
    ["kept-ink", "surface", 4.5],
    ["kept-ink", "surface-2", 4.5],
    ["kept", "surface", 3],
    ["field", "surface", 3],
    ["field", "canvas", 3],
    ["focus", "canvas", 3],
  ])("%s on %s reaches %s:1", (fg, bg, min) => {
    expect(contrast(theme, fg, bg)).toBeGreaterThanOrEqual(min);
  });

  it.each(SERIES)("chart %s reaches 3:1 on the surface", (s) => {
    expect(contrast(theme, s, "surface")).toBeGreaterThanOrEqual(3);
  });

  it("chart slots 1-5 keep clear of the status hues", () => {
    const status = ["guard", "danger", "warn"].map((t) => hsl(color(theme, t)).h);
    for (const s of SERIES.slice(0, 5)) {
      const { h, s: sat } = hsl(color(theme, s));
      // A low-saturation brown reads as brown, not as a warning or an error.
      if (sat < 0.3) continue;
      for (const st of status) expect(hueGap(h, st), `${s} vs a status hue`).toBeGreaterThanOrEqual(25);
    }
  });

  it("hairlines are quiet and --line-strong is clearly stronger", () => {
    const line = contrast(theme, "line", "surface");
    expect(line).toBeGreaterThanOrEqual(1.2);
    expect(line).toBeLessThanOrEqual(1.4);
    expect(contrast(theme, "line-strong", "surface")).toBeGreaterThanOrEqual(line + 0.15);
  });

  it("danger is orange-red, apart from the brand magenta", () => {
    const danger = hsl(color(theme, "danger")).h;
    expect(hueGap(danger, hsl(color(theme, "accent")).h)).toBeGreaterThanOrEqual(40);
    expect(danger <= 20 || danger >= 355).toBe(true);
  });
});

describe("palette (light)", () => {
  it("muted secondary text keeps 7:1 on the canvas and on cards", () => {
    expect(contrast("light", "muted", "surface")).toBeGreaterThanOrEqual(7);
    expect(contrast("light", "muted", "canvas")).toBeGreaterThanOrEqual(7);
  });

  it("the primary is a visible plum with white text at 10:1", () => {
    expect(token("light", "on-primary")).toBe("#ffffff");
    expect(contrast("light", "on-primary", "primary")).toBeGreaterThanOrEqual(10);
    expect(contrast("light", "on-primary", "primary-hover")).toBeGreaterThanOrEqual(10);
    // Visible plum, not near-black.
    expect(luminance(color("light", "primary"))).toBeGreaterThan(0.015);
  });

  it("white cards sit on a warm off-white canvas", () => {
    expect(token("light", "surface")).toBe("#ffffff");
    expect(token("light", "canvas")).not.toBe("#ffffff");
  });

  it("every neutral is warm", () => {
    const neutrals = ["canvas", "surface-2", "surface-3", "ink", "muted", "faint", "line", "line-strong", "field", "kept", "kept-ink", "region-kept", "stage-upstream", "stage-other"];
    for (const theme of ["light", "dark"] as const) {
      for (const n of neutrals) {
        const [r, , b] = color(theme, n);
        expect(r, `--${n} (${theme}) is warm`).toBeGreaterThan(b);
      }
    }
  });
});

describe("palette (dark)", () => {
  it("the primary is a plum button with white text", () => {
    expect(token("dark", "on-primary")).toBe("#ffffff");
    expect(contrast("dark", "on-primary", "primary")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("dark", "on-primary", "primary-hover")).toBeGreaterThanOrEqual(4.5);
    const { h, s } = hsl(color("dark", "primary"));
    expect(hueGap(h, 320)).toBeLessThanOrEqual(20);
    expect(s).toBeGreaterThan(0.3);
  });
});

describe("palette usage", () => {
  it("buttons never carry the brand gradient", () => {
    expect(controls).not.toMatch(/accent-gradient|gradient/);
  });
});
