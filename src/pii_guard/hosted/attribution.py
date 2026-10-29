"""Fixed identification headers for the hosted sponsored (Meta) route only (LAB-1461).

The sponsored gateway runs on the operator's credential, so its upstream calls name the
software and the deployment, never a user: no principal, project, session or network value
reaches either header. Bring-your-own-key and custom endpoints get neither header.
"""

from __future__ import annotations

from pii_guard import __version__
from pii_guard.config import Settings

SOURCE_HEADER = "X-PII-Guard-Source"
USER_AGENT = f"pii-guard/{__version__} (+https://github.com/watt-mind/pii-guard)"


def sponsored_upstream_headers(settings: Settings) -> dict[str, str]:
    """The headers every sponsored upstream request carries (the tag is validated in config)."""
    return {"User-Agent": USER_AGENT, SOURCE_HEADER: settings.hosted_source_tag}
