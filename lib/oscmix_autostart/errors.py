"""Exception types shared across the package."""

from __future__ import annotations


class ConfigError(Exception):
    """A problem in routing.conf that the user has to fix."""
