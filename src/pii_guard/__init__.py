"""pii-guard: a privacy firewall for AI agents."""

from importlib.metadata import PackageNotFoundError, version

#: The distribution name on PyPI (``[project] name`` in pyproject.toml); the command is
#: ``pii-guard`` and the import package ``pii_guard``.
DISTRIBUTION = "wattmind-pii-guard"

try:
    __version__ = version(DISTRIBUTION)
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = ["DISTRIBUTION", "__version__"]
