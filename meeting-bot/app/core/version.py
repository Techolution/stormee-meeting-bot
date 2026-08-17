"""Service identity.

Read from installed package metadata where available, so the version reported
by ``/health`` is the version that was actually deployed rather than a constant
someone forgot to bump.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

SERVICE_NAME = "meeting-bot"

try:
    VERSION = _package_version(SERVICE_NAME)
except PackageNotFoundError:  # running from a source checkout
    VERSION = "0.0.0+local"

__all__ = ["SERVICE_NAME", "VERSION"]
