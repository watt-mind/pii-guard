"""LAB-1571: hosted middleware resolves endpoint keys case-insensitively."""

from __future__ import annotations

import inspect

from pii_guard.api.security import looks_like_endpoint_key
from pii_guard.hosted import middleware as hosted_middleware


def test_endpoint_key_predicate_is_case_insensitive() -> None:
    assert looks_like_endpoint_key("pg_ep_synthetic")
    assert looks_like_endpoint_key("PG_EP_SYNTHETIC")
    assert looks_like_endpoint_key("  Pg_Ep_synthetic  ")
    assert not looks_like_endpoint_key("Bearer synthetic-token")
    assert not looks_like_endpoint_key("")


def test_hosted_middleware_uses_shared_predicate() -> None:
    """The middleware must not keep its own case-sensitive startswith check."""
    source = inspect.getsource(hosted_middleware.HostedMiddleware.__call__)
    assert "looks_like_endpoint_key" in source
    assert 'startswith("pg_ep_")' not in source
    assert "startswith('pg_ep_')" not in source
