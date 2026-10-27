"""Put a client, such as a coding agent, behind the gateway: ``pii-guard connect <client>``.

- :mod:`~pii_guard.integrations.pi`: pi (``@earendil-works/pi-coding-agent``), configured as a
  custom OpenAI-compatible provider in ``~/.pi/agent/models.json``.
- :mod:`~pii_guard.integrations.muse_code`: Muse Code, Meta's coding agent. Its provider
  speaks the OpenAI Responses API, which the gateway doesn't serve yet, so ``connect`` only
  explains what was checked (docs/integrations/muse-code.md).
- :mod:`~pii_guard.integrations.common`: what every client shares: the gateway URL, the model
  list (``GET /v1/models``), writing a config file with a backup, and the ``--check`` canary.

Docs: ``docs/integrations/``. The fictional mini-repo the tests use: ``examples/coding-agents/``.
"""

from __future__ import annotations

__all__: list[str] = []
