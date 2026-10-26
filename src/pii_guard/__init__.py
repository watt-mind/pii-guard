"""pii-guard: a privacy firewall for AI agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pii-guard")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
