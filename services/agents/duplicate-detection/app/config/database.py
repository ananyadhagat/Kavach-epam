"""Database configuration read from the process environment.

The existing application must keep working without a database, so
:func:`get_database_url` returns ``None`` when neither supported variable is
set. ``app.main`` uses that signal to choose between the in-memory default app
and the database-backed consolidation runtime.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: Preferred environment variable name.
PRIMARY_ENV_VAR = "KAVACH_DATABASE_URL"

#: Fallback used by many deployment platforms.
FALLBACK_ENV_VAR = "DATABASE_URL"


def get_database_url(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return the configured database URL, or ``None`` when absent.

    Blank values are ignored so an empty deployment variable does not silently
    disable the default application.
    """

    source = os.environ if environ is None else environ
    for name in (PRIMARY_ENV_VAR, FALLBACK_ENV_VAR):
        value = source.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def is_database_configured(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether a database URL is configured."""

    return get_database_url(environ) is not None


__all__ = [
    "FALLBACK_ENV_VAR",
    "PRIMARY_ENV_VAR",
    "get_database_url",
    "is_database_configured",
]
