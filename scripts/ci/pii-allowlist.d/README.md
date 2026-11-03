# Per-language allow-lists

`scripts/ci/pii_in_diff.py` reads every `*.txt` here as well as `../pii-allowlist.txt`, in the
same format: one fictional value per line, `#` starts a comment. A language pack keeps its
fictional identifiers that pass a validated rule in `<code>.txt` (for example `fr.txt`), so
adding a pack never edits the shared list (LAB-1773). Add a value only if it is fictional.
