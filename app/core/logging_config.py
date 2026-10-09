"""Central logging configuration for SlideCast (desktop + web).

All modules should log via the standard library::

    import logging
    logger = logging.getLogger(__name__)

Entry points (``main.py`` for desktop, ``app.web.server`` for the API) must
call :func:`setup_logging` once at startup. The log level can be tuned with
the ``LOG_LEVEL`` environment variable (default: ``INFO``).
"""

import logging
import os
import sys

_configured = False


def setup_logging(level: str | None = None) -> None:
    """Configure the root logger once; safe to call multiple times."""
    global _configured
    if _configured:
        return

    raw_level = level or os.environ.get("LOG_LEVEL", "INFO")
    numeric_level = getattr(logging, str(raw_level).upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(numeric_level)
    # Avoid duplicate handlers when a host (e.g. uvicorn) already configured root.
    if not root.handlers:
        root.addHandler(handler)
    _configured = True
