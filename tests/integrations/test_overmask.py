"""The over-masking check: code identifiers, paths and URLs must not be masked."""

from __future__ import annotations

import json
from pathlib import Path

from pii_guard.integrations.e2e import EXAMPLE_DIR
from pii_guard.integrations.overmask import classify, main

MINI_REPO = EXAMPLE_DIR / "mini-repo"


def test_classify() -> None:
    assert classify("https://payments.example.com/v2") == "url"
    assert classify("src/notify.py") == "path"
    assert classify("load_customers") == "identifier"
    assert classify("customer.iban") == "identifier"
    assert classify("Jane Placeholder") == "value"
    assert classify("jane.placeholder@example.net") == "value"


def test_mini_repo_code_is_not_masked(tmp_path: Path) -> None:
    record = tmp_path / "record.json"
    files = [MINI_REPO / "src" / "notify.py", MINI_REPO / "client-letter.md"]
    assert main([*map(str, files), "--record", str(record)]) == 0
    result = json.loads(record.read_text())
    assert result["code_spans"] == []
    assert result["by_kind"]["value"] >= 4  # the letter's e-mail, phone and IBAN, the address
    assert result["files"] == ["notify.py", "client-letter.md"]
