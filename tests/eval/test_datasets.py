"""The dataset registry (LAB-1226): declarations, conversion, committed samples, the CLI and runs.

Downloads are never made here: a ``file://`` URL stands in for the network, and Parquet reads
are replaced by in-memory rows. Every value in the fake rows is fictional (ADR 0005).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import ClassVar

import pytest

from pii_guard.eval.baselines import BaselineOutput, to_spans
from pii_guard.eval.datasets import REGISTRY, cee, get, gretel, nemotron, tab, test_datasets
from pii_guard.eval.datasets import _common as common
from pii_guard.eval.datasets import cli as ds_cli
from pii_guard.eval.datasets import run as ds_run
from pii_guard.eval.datasets._common import (
    ConversionError,
    LabelMap,
    Row,
    convert,
    download,
    sample,
    text_sha256,
)
from pii_guard.eval.datasets.spec import Dataset, SourceFile, check, fetch
from pii_guard.eval.fixtures import load_fixtures
from pii_guard.types import EntityType

ROOT = Path(__file__).resolve().parents[2]

LABELS = LabelMap(
    types={
        "first": EntityType.PERSON,
        "last": EntityType.PERSON,
        "street": EntityType.ADDRESS,
        "city": EntityType.ADDRESS,
        "mail": EntityType.EMAIL,
        "date": None,
    },
    part_only=frozenset({"city"}),
    per_language={"hu": {"mail": EntityType.EMAIL}},
)


@pytest.fixture(autouse=True)
def _repo_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


# --- Declarations -------------------------------------------------------------------------


def test_every_dataset_declares_source_licence_and_split() -> None:
    assert len([d for d in REGISTRY.values() if d.read is not None]) >= 3  # new public sets
    for ds in REGISTRY.values():
        assert ds.split in ("dev", "test"), ds.name
        assert ds.license and ds.license_url.startswith("https://"), ds.name
        assert ds.attribution and ds.revision and ds.languages, ds.name
        for f in ds.files:
            assert re.fullmatch(r"[0-9a-f]{64}", f.sha256), ds.name
            assert ds.revision in f.url, f"{ds.name}: download not pinned to the revision"
        # Rows are committed only for synthetic text with a licence that allows it.
        if ds.commit_rows:
            assert ds.synthetic, ds.name
        assert get(ds.name) is ds
    assert {d.name for d in test_datasets()} >= {"gretel-finance", "nemotron-pii", "cee-pii"}
    with pytest.raises(KeyError, match="unknown dataset"):
        get("nope")


def test_committed_samples_match_their_manifests() -> None:
    for ds in REGISTRY.values():
        manifest = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
        assert manifest.get("split", "test") == ds.split
        for path, lang in zip(ds.fixture_paths(), ds.languages, strict=True):
            if not ds.commit_rows:
                assert not (ROOT / path).exists() or "data/" in str(path)
                continue
            docs = load_fixtures([path])
            assert {d.language for d in docs} == {lang}
            block = manifest.get("languages", {}).get(lang)
            if block is None or "text_sha256" not in block:  # Ai4Privacy: its own manifest
                assert block is None or block["documents"] == len(docs)
                continue
            assert block["documents"] == len(docs)
            assert block["text_sha256"] == [text_sha256(d.text) for d in docs]


def test_real_documents_are_never_committed() -> None:
    tab_ds = get("tab-echr")
    assert not tab_ds.commit_rows and not tab_ds.synthetic
    assert all(str(p).startswith("data/") for p in tab_ds.fixture_paths())
    manifest = json.loads(tab_ds.manifest_path.read_text(encoding="utf-8"))
    assert manifest["rows_committed"] is False
    assert "text" not in json.dumps(manifest["languages"]).replace("text_sha256", "")


# --- Conversion -----------------------------------------------------------------------------


def _row(text: str, spans: list[tuple[str, str]], **kw: object) -> Row:
    out, cursor = [], 0
    for value, lab in spans:
        start = text.index(value, cursor)
        out.append((start, start + len(value), lab))
        cursor = start + len(value)
    return Row(kw.pop("uid", "1"), kw.pop("language", "en"), text, tuple(out), **kw)  # type: ignore[arg-type]


def test_convert_merges_names_and_keeps_ignore_regions() -> None:
    text = "Mail Teszt Elek at teszt.elek@example.com on 2026-01-02, 12 Fo utca, Szeged."
    row = _row(
        text,
        [
            ("Mail", "weird"),
            ("Teszt", "first"),
            ("Elek", "last"),
            ("teszt.elek@example.com", "mail"),
            ("2026-01-02", "date"),
            ("12 Fo utca", "street"),
            ("Szeged", "city"),
        ],
    )
    c = convert(row, LABELS, prefix="x", kind="public-x", source="s")
    spans = [(s.text, s.entity_type) for s in c.document.spans]
    assert spans == [
        ("Teszt Elek", EntityType.PERSON),
        ("teszt.elek@example.com", EntityType.EMAIL),
        ("12 Fo utca, Szeged", EntityType.ADDRESS),
    ]
    assert c.unknown == Counter({"weird": 1})
    assert c.dropped == Counter({"date": 1})
    assert [r["label"] for r in c.document.meta["ignore"]] == ["date"]
    assert c.document.id == "x-1"


def test_convert_part_only_label_alone_is_ignored() -> None:
    c = convert(
        _row("Lives in Szeged.", [("Szeged", "city")]), LABELS, prefix="x", kind="k", source="s"
    )
    assert c.document.spans == ()
    assert c.dropped == Counter({"city (on its own)": 1})
    assert c.document.meta["ignore"][0]["label"] == "city"


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (Row("1", "en", "Teszt Elek", ((0, 5, "first"),), values=("Tesz",)), "don't match"),
        (Row("1", "en", "Teszt Elek", ((0, 5, "first"),), values=()), "values don't match"),
        (Row("1", "en", "Teszt Elek", ((0, 50, "first"),)), "out of range"),
        (Row("1", "en", "  ", ()), "missing text"),
        (Row("1", "en", "Teszt Elek", ((0, 5, "first"), (2, 8, "street"))), "overlapping"),
        # Assembled at run time, so this file holds no token-shaped string.
        (Row("1", "en", "token " + "xox" + "b-" + "0" * 12, ()), "credential"),
    ],
)
def test_convert_rejects_bad_rows(row: Row, message: str) -> None:
    with pytest.raises(ConversionError, match=message):
        convert(row, LABELS, prefix="x", kind="k", source="s")


def test_holds_credential_shapes() -> None:
    from pii_guard.eval.datasets._common import holds_credential

    # Assembled at run time, so this file holds no token-shaped string.
    jwt = "ey" + "J" + "a" * 12 + ".ey" + "J" + "b" * 12 + ".sig"
    assert holds_credential(f"session={jwt};")
    assert holds_credential("API key shall be: " + "ab12" * 5)
    assert holds_credential("jwt_token=" + "Zz9" * 6 + ";")
    assert not holds_credential("Token: see the attached form")  # no digits
    assert not holds_credential("Invoice number: 2024-118834")  # no keyword


def test_convert_overlap_of_one_type_is_merged() -> None:
    row = Row("1", "en", "Teszt Elek Bela", ((0, 10, "first"), (6, 15, "last")))
    c = convert(row, LABELS, prefix="x", kind="k", source="s")
    assert [s.text for s in c.document.spans] == ["Teszt Elek Bela"]


def test_sample_is_seeded_and_independent_of_order() -> None:
    rows = [Row(str(i), "en" if i % 2 else "hu", f"Teszt {i}", ()) for i in range(40)]
    rows.append(Row("bad", "en", " ", ()))
    rows.append(Row("other", "fr", "x", ()))

    def to_doc(r: Row) -> common.Converted:
        return convert(r, LABELS, prefix="x", kind="k", source="s")

    a, seen = sample(rows, {"en": 5, "hu": 3}, 7, to_doc)
    b, _ = sample(list(reversed(rows)), {"en": 5, "hu": 3}, 7, to_doc)
    assert [c.document.id for c in a["en"]] == [c.document.id for c in b["en"]]
    assert len(a["hu"]) == 3 and seen["rows_en"] == 21
    c, _ = sample(rows, {"en": 5}, 8, to_doc)
    assert [x.document.id for x in c["en"]] != [x.document.id for x in a["en"]]


def test_label_table_lists_overrides() -> None:
    table = {r["label"]: r for r in LABELS.table()}
    assert table["mail"]["per_language"] == {"hu": "EMAIL"}
    assert table["city"]["part_only"] is True
    assert table["date"]["pii_guard_type"] is None


# --- Downloads ------------------------------------------------------------------------------


def test_download_checks_the_hash(tmp_path: Path) -> None:
    src = tmp_path / "src.json"
    src.write_text("[]", encoding="utf-8")
    sha = common.sha256_file(src)
    dest = tmp_path / "cache" / "f.json"
    assert download(src.as_uri(), sha, dest) == dest
    assert download("file:///nonexistent", sha, dest) == dest  # cached: no request
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        download(src.as_uri(), "0" * 64, tmp_path / "other.json")
    assert not (tmp_path / "other.json.part").exists()


def test_read_parquet_needs_pyarrow(tmp_path: Path) -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="pyarrow"):
            common.read_parquet(tmp_path / "x.parquet", ["a"])
    else:  # pragma: no cover - pyarrow isn't a dependency
        pytest.skip("pyarrow installed")


# --- Loaders --------------------------------------------------------------------------------


def test_gretel_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = [
        {"index": 1, "language": "German", "generated_text": "Herr Max Muster",
         "pii_spans": json.dumps([{"start": 5, "end": 15, "label": "name"}])},
        {"index": 2, "language": "Swedish", "generated_text": "x", "pii_spans": "[]"},
    ]  # fmt: skip
    monkeypatch.setattr(gretel, "read_parquet", lambda path, cols: fake)
    rows = list(gretel.rows([Path("x")]))
    assert [(r.uid, r.language, r.spans) for r in rows] == [("1", "de", ((5, 15, "name"),))]
    doc = gretel.DATASET.to_document(rows[0]).document
    assert (
        doc.spans[0].entity_type is EntityType.PERSON
        and doc.meta["kind"] == "public-gretel-finance"
    )


def test_nemotron_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = [{"start": 0, "end": 4, "text": "Anna", "label": "first_name"}]
    fake = [{"uid": "u", "text": "Anna Teszt", "spans": repr(spans), "locale": "us",
             "document_format": "unstructured"}]  # fmt: skip
    monkeypatch.setattr(nemotron, "read_parquet", lambda path, cols: fake)
    (row,) = nemotron.rows([Path("x")])
    assert row.uid == "u-us" and row.values == ("Anna",) and row.meta["locale"] == "us"


def test_cee_and_tab_rows(tmp_path: Path) -> None:
    cee_file = tmp_path / "cee.jsonl"
    cee_file.write_text(
        json.dumps({"text": "TAJ 123456788", "entities": [{"type": "taj", "start": 4,
                    "end": 13, "text": "123456788"}], "language": "hu", "seed": 5,
                    "registers": ["chat"], "has_noise": True}) + "\n"
        + json.dumps({"text": "x", "entities": [], "language": "pl", "seed": 6}) + "\n\n",
        encoding="utf-8",
    )  # fmt: skip
    (row,) = cee.rows([cee_file])
    assert (row.uid, row.language, row.meta["variant"]) == ("5", "hu", "hu")
    doc = cee.DATASET.to_document(row).document
    assert doc.spans[0].entity_type is EntityType.NATIONAL_ID_HU_TAJ
    tab_file = tmp_path / "tab.json"
    mention = {
        "entity_type": "PERSON",
        "start_offset": 0,
        "end_offset": 10,
        "span_text": "Teszt Elek",
    }
    tab_file.write_text(
        json.dumps([
            {"doc_id": "001", "text": "Teszt Elek v. X", "quality_checked": ["a2"],
             "annotations": {"a1": {"entity_mentions": []}, "a2": {"entity_mentions": [mention]}}},
            {"doc_id": "002", "text": "none", "annotations": {}},
        ]),
        encoding="utf-8",
    )  # fmt: skip
    (row,) = tab.rows([tab_file])
    assert row.meta["annotator"] == "a2" and row.spans == ((0, 10, "PERSON"),)


def _toy_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dataset:
    src = tmp_path / "toy.jsonl"
    lines = [
        {"text": f"Ügyfél: Teszt Elek{i}, TAJ 123456788", "entities": [
            {"type": "person_name", "start": 8, "end": 18 + len(str(i)), "text": f"Teszt Elek{i}"}],
         "language": "hu", "seed": i}
        for i in range(6)
    ]  # fmt: skip
    src.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    monkeypatch.setattr("pii_guard.eval.datasets.spec.DATASETS_DIR", tmp_path / "datasets")
    return Dataset(
        name="toy",
        title="Toy",
        homepage="https://example.com/toy",
        revision="r1",
        license="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        attribution="nobody",
        languages=("hu",),
        source_split="test",
        split="test",
        synthetic=True,
        commit_rows=True,
        description="toy",
        files=(SourceFile("toy.jsonl", src.as_uri(), common.sha256_file(src)),),
        sample={"hu": 4},
        labels=cee.LABELS,
        read=cee.rows,
    )


def test_fetch_and_check_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = _toy_dataset(tmp_path, monkeypatch)
    cache = tmp_path / "cache"
    out = tmp_path / "datasets" / "toy"
    written = fetch(ds, cache=cache, out=out)
    assert [p.name for p in written] == ["hu-toy.jsonl", "manifest.json"]
    monkeypatch.setattr(Dataset, "fixtures_dir", property(lambda self: out))
    monkeypatch.setattr(Dataset, "manifest_path", property(lambda self: out / "manifest.json"))
    assert check(ds, cache=cache) == []
    (out / "hu-toy.jsonl").write_text("{}\n", encoding="utf-8")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["seed"] = 1
    manifest["languages"]["hu"]["documents"] = 99
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    problems = check(ds, cache=cache)
    assert any("'seed' differs" in p for p in problems)
    assert any("languages.hu.documents differs" in p for p in problems)
    assert any("differs from the rebuilt sample" in p for p in problems)
    (out / "manifest.json").write_text("{", encoding="utf-8")
    assert "unreadable" in check(ds, cache=cache)[0]
    with pytest.raises(ValueError, match="not a downloadable"):
        from pii_guard.eval.datasets.spec import build

        build(get("agent-traffic"))


# --- CLI ------------------------------------------------------------------------------------


def test_cli_list_paths_and_check(capsys: pytest.CaptureFixture[str]) -> None:
    assert ds_cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "gretel-finance" in out and "manifest only" in out
    assert ds_cli.main(["paths", "cee-pii"]) == 0
    assert "eval/datasets/cee-pii/hu-cee-pii.jsonl" in capsys.readouterr().out
    assert ds_cli.main(["check", "agent-traffic", "agent-traffic-dev"]) == 0
    assert ds_cli.main(["paths", "nope"]) == 2


def test_eval_cli_forwards_datasets(capsys: pytest.CaptureFixture[str]) -> None:
    from pii_guard.eval.cli import main as eval_main

    assert eval_main(["datasets", "paths", "agent-traffic"]) == 0
    assert "eval/synthetic/hu-agent-traffic.jsonl" in capsys.readouterr().out


# --- Runs -----------------------------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class FakeBaseline:
    name = "fake"
    reversible = True
    placeholder_re = re.compile(r"<[A-Z_]+_\d+>")
    info: ClassVar[dict[str, object]] = {"tool": "fake", "versions": {"fake": "1.0"}}

    def process(self, text: str, language: str) -> BaselineOutput:
        raw = [(m.start(), m.end(), "EMAIL_ADDRESS", 0.9) for m in _EMAIL.finditer(text)]
        spans, unmapped = to_spans(text, raw, self.name)
        masked = _EMAIL.sub("<EMAIL_ADDRESS_1>", text)
        return BaselineOutput(tuple(spans), masked, masked, 1.0, 0.5, unmapped)

    def close(self) -> None:
        pass


def test_run_records_rules_and_a_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pii_guard.eval.baselines as baselines

    monkeypatch.setattr(baselines, "create_baseline", lambda name: FakeBaseline())
    runs, counts = tmp_path / "runs", tmp_path / "counts"
    ds = get("agent-traffic")
    summaries = ds_run.run_dataset(
        ds,
        ["rules", "fake"],
        record=True,
        limit=4,
        runs_dir=runs,
        counts_dir=counts,
        day="2026-10-27",
    )
    assert [s["run_id"] for s in summaries] == [
        "2026-10-27-datasets-agent-traffic-rules-n4",
        "2026-10-27-datasets-agent-traffic-n4-fake",
    ]
    data = json.loads((counts / "2026-10-27-datasets-agent-traffic-rules-n4.json").read_text())
    assert len(data["documents"]) == 12 and data["split"] == "test"
    first = data["documents"][0]
    assert set(first) >= {"id", "gold", "tp_gold", "leaked", "masked", "over_masked", "detect_ms"}
    assert "text" not in json.dumps(data)  # counts only
    assert any("checksum" in d for d in data["documents"])
    assert data["summary"]["leak"]["low"] <= data["summary"]["leak"]["value"]
    record = json.loads((runs / "2026-10-27-datasets-agent-traffic-rules-n4.json").read_text())
    assert any("Fixed sample" in n for n in record["notes"])


def test_run_refuses_unsafe_or_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--limit"):
        ds_run.run_dataset(get("agent-traffic"), ["audit"])
    with pytest.raises(ValueError, match="never sent to a remote model"):
        ds_run.run_dataset(
            get("cee-pii").__class__(
                **{
                    **_fields(get("tab-echr")),
                    "external": ("eval/synthetic/en-agent-traffic.jsonl",),
                }
            ),
            ["audit"],
            limit=1,
        )
    with pytest.raises(FileNotFoundError, match="fetch"):
        ds_run.run_dataset(Dataset(**{**_fields(get("tab-echr")), "commit_rows": True}), ["rules"])


def _fields(ds: Dataset) -> dict[str, object]:
    return {f: getattr(ds, f) for f in ds.__dataclass_fields__}


def test_fetch_and_check_a_generated_set(tmp_path: Path) -> None:
    import dataclasses

    from pii_guard.eval.datasets import synthetic

    small = dataclasses.replace(
        get("agent-traffic-dev"),
        external=tuple(str(tmp_path / f"{lang}-x.jsonl") for lang in synthetic.LANGUAGES),
        manifest_file=str(tmp_path / "manifest.json"),
        builder=lambda: synthetic.build_split("dev", {"hu": 2, "en": 2, "de": 2}),
    )
    written = ds_cli._fetch_one(small)
    assert len(written) == 4 and all(p.is_file() for p in written)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["languages"]["hu"]["documents"] == 2 and manifest["split"] == "dev"
    assert ds_cli._check_one(small) == []
    (tmp_path / "manifest.json").write_text("{}\n", encoding="utf-8")
    assert ds_cli._check_one(small) == [f"{tmp_path / 'manifest.json'}: differs"]
    hu = tmp_path / "hu-x.jsonl"
    hu.write_text(hu.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    assert f"{hu}: differs from the generator output" in ds_cli._check_one(small)


def test_cli_run_without_record(capsys: pytest.CaptureFixture[str]) -> None:
    assert ds_cli.main(["run", "agent-traffic", "--system", "rules", "--limit", "1"]) == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["system"] == "rules" and line["documents"] == 3
    assert ds_cli.main(["run", "agent-traffic", "--system", "audit"]) == 2
