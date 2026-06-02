"""Alfard — secure-by-default local AI agent orchestration framework."""

from importlib.metadata import version as _pkg_version, PackageNotFoundError as _PackageNotFoundError

try:
    __version__: str = _pkg_version("alfard")
except _PackageNotFoundError:
    __version__ = "unknown"
