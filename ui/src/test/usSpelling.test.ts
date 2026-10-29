import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/*
 * The UI's copy is US English, like the video (LAB-1523). This scans every user-facing string in
 * ui/src (string and template literals, JSX text) plus ui/index.html for British spellings, so a
 * new "anonymise" or "labelled" fails here instead of shipping. Comments, identifiers, tests and
 * recorded JSON fixtures are not scanned.
 */

// Vitest runs from ui/.
const UI = process.cwd();
const SRC = join(UI, "src");

/** -ise/-isation stems: each matches only followed by se/ses/sed/sing/sation/sations/ser/sers. */
const ISE_STEMS = [
  "anonymi", "pseudonymi", "minimi", "maximi", "optimi", "authori", "organi", "recogni", "normali",
  "prioriti", "summari", "categori", "customi", "utili", "visuali", "initiali", "synchroni", "seriali",
  "finali", "reali", "standardi", "capitali", "tokeni", "saniti", "emphasi", "apologi", "speciali",
  "generali", "memori", "locali", "digiti", "legali", "stabili", "characteri", "personali", "plurali",
  "randomi", "parameteri", "containeri", "vectori", "neutrali", "centrali", "moderni", "itemi",
];

const BRITISH: RegExp[] = [
  new RegExp(`\\b(?:${ISE_STEMS.join("|")})s(?:e|es|ed|ing|ation|ations|er|ers)\\b`, "i"),
  /\banalys(?:e|ed|ing)\b/i, // "analyses" is also the US plural of analysis
  /\b(?:colour|behaviour|favour|honour|labour|neighbour|flavour|humour|rumour|savour)\w*/i,
  /\b(?:licence|licences|licenced|centre|centres|centred|metre|metres|litre|litres|catalogue|catalogues|catalogued)\b/i,
  /\b(?:judgement|judgements|programme|programmes|enrol|enrols|enrolment|enrolled|enrolling)\b/i,
  /\b(?:cancelled|cancelling|travelled|travelling|traveller|travellers|modelled|modelling|labelled|labelling|signalled|signalling|fuelled|totalled|levelled|counselled)\b/i,
  /\b(?:grey|greyed|greys|whilst|amongst|learnt|spelt|fulfil|fulfils|fulfilment|defence|offence|cheque|cheques|practise|practised)\b/i,
  /\be-mail|\bE-mail\b/, // case-sensitive: German "E-Mail" in fictional samples is fine
];

/**
 * Exact text allowed to keep a British form: quoted legal text and official names, verbatim
 * (e.g. the GDPR's own "pseudonymisation" when quoted with its article). Keep it short.
 */
const ALLOWED: string[] = [];

/** Fictional non-English sample data (Hungarian, German) keeps its own language's spelling. */
const NON_ENGLISH = /[áéíóöőúüűÁÉÍÓÖŐÚÜŰäßÄ]/;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "test" ? [] : sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts") ? [path] : [];
  });
}

/** Every string a user could read in `file`: literals, template pieces, JSX text. */
function strings(file: string): string[] {
  const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return; // module specifiers
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node) || ts.isJsxText(node)) {
      out.push(node.text);
    }
    node.forEachChild(visit);
  };
  visit(source);
  return out;
}

function britishIn(text: string): string | null {
  if (NON_ENGLISH.test(text) || ALLOWED.some((allowed) => text.includes(allowed))) return null;
  for (const pattern of BRITISH) {
    const match = pattern.exec(text);
    if (match) return match[0];
  }
  return null;
}

describe("UI copy uses US spelling (LAB-1523)", () => {
  it("the patterns catch British forms and leave US ones alone", () => {
    for (const word of ["pseudonymisation", "Anonymise", "summarised", "authorised", "labelled", "colour", "e-mail", "grey", "analysed", "serialising", "recognise"]) {
      expect(britishIn(word), word).not.toBeNull();
    }
    for (const word of ["pseudonymization", "anonymize", "summarized", "labeled", "color", "email", "gray", "analyses", "promise", "otherwise", "noise", "raised", "E-Mail Adresse", "Kárbejelentő e-mail"]) {
      expect(britishIn(word), word).toBeNull();
    }
  });

  it("no user-facing string in ui/src is British", () => {
    const hits = sources(SRC).flatMap((file) =>
      strings(file).flatMap((text) => {
        const word = britishIn(text);
        return word ? [`${relative(UI, file)}: "${word}" in ${JSON.stringify(text.trim().slice(0, 120))}`] : [];
      }),
    );
    expect(hits).toEqual([]);
  });

  it("ui/index.html is not British", () => {
    const html = readFileSync(join(UI, "index.html"), "utf8");
    expect(BRITISH.flatMap((pattern) => pattern.exec(html)?.[0] ?? [])).toEqual([]);
  });
});
