"""The package logger.

One named logger, configured by the CLI entry point only -- a library
module that configures logging would fight whoever imports it.
"""

from __future__ import annotations

import logging

log = logging.getLogger("oscmix-session")
