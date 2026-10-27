"""Public benchmarks, converted to the fixture format at run time. See ``docs/evaluation.md``.

A loader fetches a pinned revision, draws a seeded sample, converts it to
:mod:`pii_guard.eval.fixtures` documents and writes a manifest (source, revision, file hash,
licence, seed, label mapping, sample ids) under ``eval/fixtures/public/``. Rows are committed
only when the dataset's licence allows redistribution; otherwise point ``--out`` at a
gitignored directory (``data/``) and commit the manifest alone.

- :mod:`pii_guard.eval.public.ai4privacy`: Ai4Privacy OpenPII 1M (CC-BY-4.0).
"""
