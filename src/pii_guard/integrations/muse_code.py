"""Muse Code (Meta's coding agent) and the gateway: not connectable yet.

Checked on Muse Code 1.4.13 (``muse --version``: ``1.4.13-R6996.1``), installed with the
official installer into a throwaway ``HOME`` (docs/integrations/muse-code.md has the steps):

- A custom endpoint **is** configurable: ``--base-url <URL>`` (the API key is then withheld
  unless the settings pin it) or ``~/.config/muse/settings.json``::

      {"schema_version": 1,
       "endpoint_transport": {"base_url": "http://127.0.0.1:8787/v1", "auth": "bearer"}}

- But the ``meta`` provider speaks the **OpenAI Responses API**, not Chat Completions: it
  first reads a Muse-specific catalog, ``GET <host>/muse-code/models`` (per-model client
  settings under ``metadata["muse-code"]``), then sends ``POST <base_url>/responses`` with
  ``input``/``instructions``/``reasoning``/``include: ["reasoning.encrypted_content"]``,
  ``store: false`` and ``stream: true``. The gateway serves ``POST /v1/chat/completions`` only.
- The other providers don't help: ``--provider local`` runs Muse's embedded llama.cpp with
  downloaded Glimmer weights and ignores ``--base-url``; ``echo`` is a test stub.

So pi is the supported coding agent for now. Supporting Muse Code needs a Responses API front
end in the gateway (masking ``input`` items, ``instructions``, function-call arguments and
outputs, restoring streamed ``response.*`` events) plus the ``/muse-code/models`` catalog.
"""

from __future__ import annotations

__all__ = ["FINDING", "MUSE_VERSION_CHECKED"]

MUSE_VERSION_CHECKED = "1.4.13-R6996.1"

FINDING = f"""\
Muse Code can't be put behind pii-guard yet (checked on Muse Code {MUSE_VERSION_CHECKED}).

What works: Muse Code accepts a custom endpoint, either `muse --base-url <URL>` or
~/.config/muse/settings.json:
  {{"schema_version": 1, "endpoint_transport": {{"base_url": "<URL>", "auth": "bearer"}}}}

What doesn't: its Meta provider speaks the OpenAI Responses API (POST <URL>/responses) and
first reads a Muse-specific model catalog (GET /muse-code/models). The pii-guard gateway serves
Chat Completions (POST /v1/chat/completions) only, so Muse Code's requests would be refused.
pii-guard does not intercept traffic (no HTTPS_PROXY / MITM).

Use pi instead (`pii-guard connect pi`), or any client that speaks Chat Completions.
Details and the exact checks: docs/integrations/muse-code.md
"""
