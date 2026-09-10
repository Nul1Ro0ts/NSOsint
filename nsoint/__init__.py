"""NSOsint package root.

Light by design. Does NOT import cli here — that pulls click + rich
into any process that merely wants nsoint.core. Use `python -m nsoint`
or the `nsoint` console script to run the CLI.
"""

from ._version import __version__
from .core import CACHE, Cache, Result, cache_key, make_session, safe_fetch

__all__ = [
    "__version__",
    "CACHE",
    "Cache",
    "Result",
    "cache_key",
    "make_session",
    "safe_fetch",
]
