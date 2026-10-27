"""Teacher-label merging: planted gold wins, disagreements are excluded from the loss."""

from __future__ import annotations

import json
from pathlib import Path

from pii_guard.eval.fixtures import Document, GoldSpan
from pii_guard.types import EntityType as T


def doc(text: str, *spans: tuple[str, str], kind: str = "letter") -> Document:
    gold = []
    for entity_type, value in spans:
        start = text.index(value)
        gold.append(GoldSpan(start, start + len(value), T(entity_type), value))
    gold.sort(key=lambda s: s.start)
    return Document("en-distill-s1-00000", "en", text, tuple(gold), {"kind": kind})


def hit(label_mod, text: str, value: str, entity_type: str, nth: int = 0):
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return label_mod.Hit(start, start + len(value), T(entity_type))


def test_agreeing_teacher_changes_nothing(label_mod) -> None:
    text = "Dear Amelia Carter, thank you."
    d = doc(text, ("PERSON", "Amelia Carter"))
    merged = label_mod.merge(d, [hit(label_mod, text, "Amelia Carter", "PERSON")], [])
    assert [(s.text, s.entity_type) for s in merged.spans] == [("Amelia Carter", T.PERSON)]
    assert merged.ignore == []
    assert merged.counts["agree"] == 1


def test_teacher_running_past_gold_is_ignored_outside_gold(label_mod) -> None:
    text = "Dear Dr. Amelia Carter, thank you."
    d = doc(text, ("PERSON", "Amelia Carter"))
    merged = label_mod.merge(d, [hit(label_mod, text, "Dr. Amelia Carter", "PERSON")], [])
    assert [s.text for s in merged.spans] == ["Amelia Carter"]  # gold wins
    assert [text[s:e] for s, e in merged.ignore] == ["Dr"]
    assert merged.counts["disagree"] == 1


def test_type_conflict_inside_gold_keeps_gold(label_mod) -> None:
    text = "Signed by Carter Holdings Ltd today."
    d = doc(text, ("ORGANIZATION", "Carter Holdings Ltd"))
    merged = label_mod.merge(d, [hit(label_mod, text, "Carter", "PERSON")], [])
    assert [(s.text, s.entity_type) for s in merged.spans] == [
        ("Carter Holdings Ltd", T.ORGANIZATION)
    ]
    assert merged.ignore == []


def test_new_person_is_adopted_new_address_is_ignored(label_mod) -> None:
    text = "Amelia Carter met Tom Reed in Leeds."
    d = doc(text, ("PERSON", "Amelia Carter"))
    teacher = [
        hit(label_mod, text, "Amelia Carter", "PERSON"),
        hit(label_mod, text, "Tom Reed", "PERSON"),
        hit(label_mod, text, "Leeds", "ADDRESS"),
    ]
    merged = label_mod.merge(d, teacher, [])
    assert [s.text for s in merged.spans] == ["Amelia Carter", "Tom Reed"]
    assert [text[s:e] for s, e in merged.ignore] == ["Leeds"]
    assert merged.counts["adopted_person"] == 1


def test_hard_negatives_never_gain_labels(label_mod) -> None:
    text = "By June the rose was in bloom."
    d = doc(text, kind="negative-prose")
    merged = label_mod.merge(d, [hit(label_mod, text, "June", "PERSON")], [], negative=True)
    assert merged.spans == []
    assert [text[s:e] for s, e in merged.ignore] == ["June"]


def test_rule_hit_blocks_adoption(label_mod) -> None:
    text = "Write to amelia.carter@example.org today."
    d = doc(text, ("EMAIL", "amelia.carter@example.org"))
    rules = [hit(label_mod, text, "amelia.carter@example.org", "EMAIL")]
    teacher = [hit(label_mod, text, "amelia", "PERSON")]
    merged = label_mod.merge(d, teacher, rules)
    assert [s.entity_type for s in merged.spans] == [T.EMAIL]  # overlaps gold: gold wins
    assert merged.ignore == []


def test_labelled_document_and_cache_round_trip(label_mod, tmp_path: Path) -> None:
    text = "Amelia Carter met Tom Reed."
    d = doc(text, ("PERSON", "Amelia Carter"))
    hits = [hit(label_mod, text, "Tom Reed", "PERSON")]
    cache = label_mod.TeacherCache(tmp_path / "teacher-cache.jsonl")
    cache.put(d, hits)
    again = label_mod.TeacherCache(tmp_path / "teacher-cache.jsonl")
    assert again.get(d) == hits
    out = label_mod.labelled_document(d, label_mod.merge(d, hits, []))
    record = json.loads(json.dumps(out.to_dict()))
    assert record["meta"]["loss_ignore"] == []
    assert record["meta"]["teacher"]["model"] == "muse-glimmer"
    assert [s["text"] for s in record["spans"]] == ["Amelia Carter", "Tom Reed"]


def test_run_teacher_uses_cache_and_survives_failures(label_mod, tmp_path: Path) -> None:
    text = "Amelia Carter wrote."
    good = doc(text, ("PERSON", "Amelia Carter"))
    bad = Document("en-distill-s1-00001", "en", "Tom wrote.", (), {})

    class Fake:
        calls = 0

        def detect(self, text: str, language: str):
            Fake.calls += 1
            if text.startswith("Tom"):
                raise RuntimeError("boom")
            from pii_guard.types import Span

            return [Span(0, 13, T.PERSON, "Amelia Carter", 0.9, "llm")]

    cache = label_mod.TeacherCache(tmp_path / "c.jsonl")
    out = label_mod.run_teacher([good, bad], Fake(), cache, workers=2)
    assert out[bad.id] is None
    assert out[good.id] == [label_mod.Hit(0, 13, T.PERSON)]
    Fake.calls = 0
    label_mod.run_teacher([good], Fake(), cache, workers=1)
    assert Fake.calls == 0
