"""Conformance checks for a language pack: what is missing, what is broken, how it scores.

One function per concern, all returning :class:`Finding` lists, so the pytest suite
(``tests/languages/test_conformance.py``), ``pii-guard lang check`` and a third-party
package's own tests run the same checks::

    from pii_guard.languages.conformance import assert_conformant

    def test_my_pack_conforms():
        assert_conformant("xx")  # or a LanguagePack object

Severities: ``error`` fails the check; ``warning`` is a gap worth fixing (fewer than ten smoke
documents, a ``TODO`` left in the prompt); ``info`` says which fallback an optional part
that the pack leaves out gets (``no inflection matcher: exact matching``).

Findings never contain fixture text or values, only ids, counts and part names (the fixtures
are fictional, but the habit is the point: ``AGENTS.md`` rule 3).
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pii_guard.languages import (
    CODE_RE,
    LanguagePack,
    SurfaceForms,
    get_pack,
    primary_language,
    register_pack,
    unregister_pack,
)
from pii_guard.types import TEXT_ENTITY_TYPES, EntityType

if TYPE_CHECKING:
    from pii_guard.eval.fixtures import Document

__all__ = [
    "DEFAULT_FIXTURES_DIR",
    "MIN_RULES_PRECISION",
    "MIN_SMOKE_DOCUMENTS",
    "ConformanceError",
    "ConformanceReport",
    "Finding",
    "assert_conformant",
    "check_fixtures",
    "check_pack",
    "check_roundtrip",
    "check_structure",
    "fixture_paths",
    "load_smoke_documents",
    "smoke_scores",
    "temporarily_registered",
]

Severity = Literal["error", "warning", "info"]

#: Where relative ``smoke_fixtures`` names are looked up (relative to the working directory).
DEFAULT_FIXTURES_DIR = Path("eval/fixtures")
#: Recommended size of a pack's hand-written smoke set.
MIN_SMOKE_DOCUMENTS = 10
#: The rules are the high-precision layer: overlap precision on the smoke set must reach this.
MIN_RULES_PRECISION = 0.9

_PROBE_VALUES = ("Sample", "Sample Name", "Example Street 12", "ABC-123", "12345678")
_PROBE_TYPES = (
    EntityType.PERSON,
    EntityType.ADDRESS,
    EntityType.ORGANIZATION,
    EntityType.ID_DOCUMENT,
)
_PROBE_TEXT = "Sample Name, born 01.02.1990, lives at Example Street 12; phone 0123 456789."


@dataclass(frozen=True, slots=True)
class Finding:
    """One result: ``check`` names the part (``structure.prompt``, ``fixtures.files`` ...)."""

    check: str
    severity: Severity
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.check}: {self.message}"


@dataclass(slots=True)
class ConformanceReport:
    """Every finding for one pack, plus the smoke-set scores when they were computed."""

    code: str
    findings: list[Finding] = field(default_factory=list)
    scores: dict[str, float | int | None] | None = None

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        """A plain-text report: verdict, findings by severity, smoke scores."""
        verdict = "conforms" if self.ok else f"FAILS ({len(self.errors)} error(s))"
        lines = [f"language pack {self.code!r}: {verdict}"]
        order = {"error": 0, "warning": 1, "info": 2}
        lines += [f"  {f}" for f in sorted(self.findings, key=lambda f: order[f.severity])]
        if self.scores:
            parts = ", ".join(f"{k}={_fmt(v)}" for k, v in self.scores.items())
            lines.append(f"  smoke set (rules detector): {parts}")
        return "\n".join(lines)


class ConformanceError(AssertionError):
    """Raised by :func:`assert_conformant`; the message is the rendered report."""


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _error(check: str, message: str) -> Finding:
    return Finding(check, "error", message)


def _warning(check: str, message: str) -> Finding:
    return Finding(check, "warning", message)


def _info(check: str, message: str) -> Finding:
    return Finding(check, "info", message)


# --- Structure ------------------------------------------------------------------------------


def check_structure(pack: LanguagePack) -> list[Finding]:
    """Required parts present and every present part well-formed. Needs no fixtures."""
    findings: list[Finding] = []
    findings += _check_identity(pack)
    findings += _check_prompt(pack)
    findings += _check_rules(pack)
    findings += _check_inflection(pack)
    findings += _check_surface_forms(pack)
    findings += _check_lexicons(pack)
    findings += _check_captions(pack)
    if not pack.smoke_fixtures:
        findings.append(
            _error(
                "structure.smoke_fixtures",
                f"no smoke fixtures declared: add smoke_fixtures=('{pack.code}-smoke.jsonl',) "
                "and write the file (docs/languages.md, step 5)",
            )
        )
    for name in pack.smoke_fixtures:
        base = Path(os.fspath(name)).name
        if not re.fullmatch(rf"{re.escape(pack.code)}-[\w.-]+\.jsonl", base):
            findings.append(
                _error(
                    "structure.smoke_fixtures",
                    f"fixture {base!r} must be named '{pack.code}-<name>.jsonl' so the "
                    "evaluation reports it under its language",
                )
            )
    return findings


def _check_identity(pack: LanguagePack) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(pack.code, str) or not CODE_RE.match(pack.code):
        findings.append(
            _error(
                "structure.code",
                f"code {pack.code!r} must be a lowercase ISO 639-1 (or 639-3) code like 'de'",
            )
        )
    if not isinstance(pack.name, str) or not pack.name.strip():
        findings.append(_error("structure.name", "name must be the language's English name"))
    registered = get_pack(pack.code) if isinstance(pack.code, str) else None
    if registered is None:
        findings.append(
            _warning(
                "structure.registered",
                "not registered: add a 'pii_guard.languages' entry point (or put the pack in "
                "src/pii_guard/languages/<code>/) so the components find it",
            )
        )
    return findings


def _check_prompt(pack: LanguagePack) -> list[Finding]:
    from pii_guard.detect.llm import ENTITY_DESCRIPTIONS, build_messages, pack_profile

    findings: list[Finding] = []
    if pack.prompt is None:
        return [
            _error(
                "structure.prompt",
                "no prompt notes: add prompt.md (LLM instructions for this language) and set "
                "prompt=files(__name__).joinpath('prompt.md')",
            )
        ]
    if not isinstance(pack.prompt, Traversable):
        return [_error("structure.prompt", "prompt must be a resource (importlib.resources)")]
    try:
        notes = pack.prompt.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return [_error("structure.prompt", f"prompt notes cannot be read: {type(exc).__name__}")]
    if not notes:
        return [_error("structure.prompt", "prompt notes are empty")]
    if "TODO" in notes:
        findings.append(_warning("structure.prompt", "prompt notes still contain 'TODO'"))
    for t in pack.country_entity_types:
        if t not in TEXT_ENTITY_TYPES or t not in ENTITY_DESCRIPTIONS:
            findings.append(
                _error(
                    "structure.country_entity_types",
                    f"{getattr(t, 'value', t)!r} is not a text entity type the LLM can be "
                    "asked for (pii_guard.types, detect/llm.py ENTITY_DESCRIPTIONS)",
                )
            )
    if findings and any(f.severity == "error" for f in findings):
        return findings
    try:
        system, _user = build_messages("Probe text.", pack.code, profile=pack_profile(pack))
    except Exception as exc:
        return [*findings, _error("structure.prompt", f"prompt fails to render: {exc!r}")]
    content = system["content"]
    leftover = re.findall(r"\{(?:entity_types|language_name|language_notes)\}", content)
    if leftover or notes not in content:
        findings.append(_error("structure.prompt", "prompt notes are not substituted"))
    return findings


def _check_rules(pack: LanguagePack) -> list[Finding]:
    findings: list[Finding] = []
    if not pack.everywhere and not pack.rules:
        return [
            _info(
                "structure.rules",
                "no rules: texts in this language get the language-independent rules and "
                "every pack's 'everywhere' rules only",
            )
        ]
    for scope, rules in (("everywhere", pack.everywhere), ("rules", pack.rules)):
        if not isinstance(rules, tuple):
            findings.append(_error(f"structure.{scope}", "must be a tuple of rule functions"))
            continue
        for rule in rules:
            name = getattr(rule, "__name__", repr(rule))
            if not callable(rule):
                findings.append(_error(f"structure.{scope}", f"{name} is not callable"))
                continue
            for text in ("", _PROBE_TEXT):
                problem = _probe_rule(rule, text)
                if problem:
                    findings.append(_error(f"structure.{scope}", f"rule {name}: {problem}"))
                    break
    return findings


def _probe_rule(rule: object, text: str) -> str | None:
    try:
        hits = list(rule(text))  # type: ignore[operator]
    except Exception as exc:
        return f"raises {type(exc).__name__} on a probe text"
    for hit in hits:
        start, end = getattr(hit, "start", None), getattr(hit, "end", None)
        entity_type, score = getattr(hit, "entity_type", None), getattr(hit, "score", None)
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
            return "yields a hit with offsets outside the text"
        if entity_type not in TEXT_ENTITY_TYPES:
            return f"yields entity type {entity_type!r}, not a text entity type"
        if not (isinstance(score, float | int) and 0 < score <= 1):
            return "yields a score outside (0, 1]"
    return None


def _check_inflection(pack: LanguagePack) -> list[Finding]:
    from pii_guard.languages.inflection import InflectionMatcher

    matcher = pack.inflection
    if matcher is None:
        return [_info("structure.inflection", "no inflection matcher: exact matching")]
    if not isinstance(matcher, InflectionMatcher):
        return [_error("structure.inflection", "inflection must implement suffix_pattern()")]
    for value in _PROBE_VALUES:
        for entity_type in _PROBE_TYPES:
            try:
                pattern = matcher.suffix_pattern(value, entity_type)
            except Exception as exc:
                return [_error("structure.inflection", f"suffix_pattern raises {exc!r}")]
            if not isinstance(pattern, str):
                return [_error("structure.inflection", "suffix_pattern must return a str")]
            try:
                compiled = re.compile(pattern)
            except re.error:
                return [_error("structure.inflection", "suffix_pattern is not a valid regex")]
            if compiled.groups:
                return [
                    _error(
                        "structure.inflection",
                        "suffix_pattern must not have capturing groups (use (?:...))",
                    )
                ]
    for method in ("variant_stems", "splits", "restore"):
        if hasattr(matcher, method) and not callable(getattr(matcher, method)):
            return [_error("structure.inflection", f"{method} must be a method")]
    return []


def _check_surface_forms(pack: LanguagePack) -> list[Finding]:
    forms = pack.surface_forms
    if forms is None:
        return [_info("structure.surface_forms", "no surface forms: exact matching, no stopwords")]
    if not isinstance(forms, SurfaceForms):
        return [_error("structure.surface_forms", "surface_forms must be a SurfaceForms")]
    findings: list[Finding] = []
    if not isinstance(forms.stopwords, frozenset) or any(
        not isinstance(w, str) or not w.strip() for w in forms.stopwords
    ):
        findings.append(_error("structure.surface_forms", "stopwords must be non-empty str"))
    for value in _PROBE_VALUES:
        try:
            variants = forms.stem_variants(value, EntityType.PERSON)
            for variant in variants:
                re.compile(variant)
        except (re.error, TypeError):
            findings.append(_error("structure.surface_forms", "stem_variants must be regexes"))
            break
        except Exception as exc:
            findings.append(_error("structure.surface_forms", f"stem_variants raises {exc!r}"))
            break
    return findings


def _check_lexicons(pack: LanguagePack) -> list[Finding]:
    spec = pack.lexicons
    if spec is None:
        return [
            _info("structure.lexicons", "no lexicons (pii_guard.lang raises LexiconUnavailable)")
        ]
    findings: list[Finding] = []
    for kind in spec.kinds:
        names = spec.merges.get(kind, (kind,))
        present = []
        for name in names:
            resource = spec.directory.joinpath(f"{name}.tsv")
            with contextlib.suppress(OSError):
                if resource.is_file() and resource.read_text(encoding="utf-8").strip():
                    present.append(name)
        if not present:
            findings.append(_error("structure.lexicons", f"lexicon {kind!r} is missing or empty"))
    return findings


def _check_captions(pack: LanguagePack) -> list[Finding]:
    if pack.captions is None:
        return [
            _info(
                "structure.captions",
                "no document field captions (values next to captions in images are left to "
                "the text detectors)",
            )
        ]
    if not isinstance(pack.captions, Traversable):
        return [_error("structure.captions", "captions must be a resource (importlib.resources)")]
    from pii_guard.visual.captions import load_captions

    try:
        captions = load_captions(pack.captions, pack.code)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return [_error("structure.captions", f"captions.tsv is invalid: {exc}")]
    if not any(c.entity_type is not None for c in captions):
        return [_error("structure.captions", "captions.tsv has no personal-data caption")]
    return []


# --- Fixtures -------------------------------------------------------------------------------


def fixture_paths(pack: LanguagePack, fixtures_dir: str | Path | None = None) -> list[Path]:
    """Where the pack's smoke fixtures are: relative names under ``fixtures_dir``."""
    base = Path(fixtures_dir) if fixtures_dir is not None else DEFAULT_FIXTURES_DIR
    paths = []
    for name in pack.smoke_fixtures:
        path = Path(os.fspath(name))
        paths.append(path if path.is_absolute() else base / path)
    return paths


def check_fixtures(
    pack: LanguagePack, fixtures_dir: str | Path | None = None
) -> tuple[list[Finding], list[Document]]:
    """The smoke fixtures exist, validate, are in the pack's language and are enough."""
    from pii_guard.eval.fixtures import FixtureError, load_fixtures

    findings: list[Finding] = []
    paths = fixture_paths(pack, fixtures_dir)
    missing = [p for p in paths if not p.is_file()]
    for path in missing:
        example = path.with_name(path.name + ".example")
        hint = f" (start from {example.name})" if example.is_file() else ""
        findings.append(_error("fixtures.files", f"{path} not found{hint}"))
    present = [p for p in paths if p.is_file()]
    if not present:
        return findings, []
    try:
        documents = load_fixtures(present)
    except (FixtureError, OSError) as exc:
        return [*findings, _error("fixtures.validate", str(exc))], []
    wrong = [d.id for d in documents if d.primary_language != pack.code]
    if wrong:
        findings.append(
            _error(
                "fixtures.language",
                f"{len(wrong)} document(s) not in {pack.code!r}: {', '.join(wrong[:5])}",
            )
        )
    if not documents:
        findings.append(_error("fixtures.validate", "the smoke fixtures contain no documents"))
    elif len(documents) < MIN_SMOKE_DOCUMENTS:
        findings.append(
            _warning(
                "fixtures.size",
                f"{len(documents)} smoke document(s); aim for at least {MIN_SMOKE_DOCUMENTS}",
            )
        )
    if documents and not any(d.spans for d in documents):
        findings.append(_error("fixtures.validate", "no labelled spans in the smoke fixtures"))
    return findings, documents


def load_smoke_documents(
    pack: LanguagePack, fixtures_dir: str | Path | None = None
) -> list[Document]:
    """The pack's smoke documents (raises :class:`ConformanceError` when they don't load)."""
    findings, documents = check_fixtures(pack, fixtures_dir)
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        raise ConformanceError("\n".join(str(f) for f in errors))
    return documents


# --- Behaviour ------------------------------------------------------------------------------


@contextlib.contextmanager
def temporarily_registered(pack: LanguagePack) -> Iterator[LanguagePack]:
    """Make ``pack`` the active pack for its language inside the block (then restore)."""
    code = primary_language(pack.code)
    previous = get_pack(code)
    if previous is pack:
        yield pack
        return
    register_pack(pack)
    try:
        yield pack
    finally:
        unregister_pack(code)
        current = get_pack(code)
        if previous is not None and current is not previous:
            register_pack(previous)


def _gold_spans(document: Document) -> list[object]:
    from pii_guard.eval.scorer import DEFAULT_POLICY
    from pii_guard.types import Span

    return [
        Span(g.start, g.end, g.entity_type, g.text, 1.0, "gold")
        for g in document.spans
        if DEFAULT_POLICY.get(g.entity_type, "mask") != "keep"
    ]


def check_roundtrip(pack: LanguagePack, documents: Iterable[Document]) -> list[Finding]:
    """Masking every gold value and unmasking the result gives back the original text."""
    from pii_guard.eval.scorer import EVAL_TENANT_KEY
    from pii_guard.vault import Vault

    failed: list[str] = []
    vault = Vault(EVAL_TENANT_KEY)
    with temporarily_registered(pack):
        for document in documents:
            session = vault.session()
            try:
                masked = session.mask(document.text, _gold_spans(document), language=pack.code)  # type: ignore[arg-type]
                if session.unmask(masked) != document.text:
                    failed.append(document.id)
            except Exception:
                failed.append(document.id)
            finally:
                vault.drop(session.session_id)
    if failed:
        return [
            _error(
                "roundtrip",
                f"mask -> unmask does not restore {len(failed)} document(s): "
                f"{', '.join(failed[:5])}",
            )
        ]
    return []


def smoke_scores(
    pack: LanguagePack, documents: Sequence[Document]
) -> tuple[list[Finding], dict[str, float | int | None]]:
    """Run the rules detector over the smoke set; gate on round trip and rules precision.

    Recall is reported, not gated: the rules only cover structured identifiers, names and
    dates are the NER and LLM passes' job.
    """
    from pii_guard.eval.scorer import DetectorAnalyzer, run_documents, summarize

    with temporarily_registered(pack):
        results = run_documents(documents, DetectorAnalyzer(["rules"]))
    summary = summarize(results)
    exact = summary["detection"]["exact"]["micro"]  # type: ignore[index]
    overlap = summary["detection"]["overlap"]["micro"]  # type: ignore[index]
    scores: dict[str, float | int | None] = {
        "documents": len(documents),
        "gold": overlap["gold"],
        "precision_overlap": overlap["precision"],
        "recall_overlap": overlap["recall"],
        "recall_exact": exact["recall"],
        "leak_rate": summary["leak"]["rate"],  # type: ignore[index]
        "roundtrip": summary["roundtrip"]["rate"],  # type: ignore[index]
    }
    findings: list[Finding] = []
    if scores["roundtrip"] is not None and scores["roundtrip"] < 1.0:
        findings.append(_error("smoke.roundtrip", "masking does not round-trip on the smoke set"))
    precision = scores["precision_overlap"]
    if precision is not None and precision < MIN_RULES_PRECISION:
        findings.append(
            _error(
                "smoke.precision",
                f"rules overlap precision {precision:.3f} < {MIN_RULES_PRECISION}: a rule "
                "fires on text that is not labelled (or a label is missing)",
            )
        )
    return findings, scores


# --- All of it ------------------------------------------------------------------------------


def check_pack(
    pack: LanguagePack | str,
    *,
    fixtures_dir: str | Path | None = None,
    structure_only: bool = False,
) -> ConformanceReport:
    """Every check for ``pack`` (a pack, or the code of a registered one)."""
    if isinstance(pack, str):
        found = get_pack(pack)
        if found is None:
            report = ConformanceReport(primary_language(pack))
            report.findings.append(_error("registry", f"no language pack for {pack!r}"))
            return report
        pack = found
    report = ConformanceReport(pack.code)
    report.findings += check_structure(pack)
    if structure_only or report.errors:
        return report
    findings, documents = check_fixtures(pack, fixtures_dir)
    report.findings += findings
    if not documents or any(f.severity == "error" for f in findings):
        return report
    report.findings += check_roundtrip(pack, documents)
    findings, scores = smoke_scores(pack, documents)
    report.findings += findings
    report.scores = scores
    return report


def assert_conformant(
    pack: LanguagePack | str,
    *,
    fixtures_dir: str | Path | None = None,
    structure_only: bool = False,
) -> ConformanceReport:
    """:func:`check_pack`, raising :class:`ConformanceError` with the report on any error."""
    report = check_pack(pack, fixtures_dir=fixtures_dir, structure_only=structure_only)
    if not report.ok:
        raise ConformanceError(report.render())
    return report
