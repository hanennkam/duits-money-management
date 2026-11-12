"""Redact sensitive Supabase Auth values from Uvicorn access logs.

Uvicorn 0.54 emits an access record as::

    '%s - "%s %s HTTP/%s" %d'

with ``(client_addr, method, full_path, http_version, status_code)`` as the arguments.
``full_path`` carries the query string, so email links such as
``/?token_hash=…&type=signup`` and OAuth callbacks such as ``/?code=…`` would otherwise
be written verbatim by every access-log handler.

A ``logging.Filter`` on the ``uvicorn.access`` logger rewrites every string argument
before any formatter sees it. Method, path, status code and latency stay intact; only
the values of sensitive parameters are replaced. The original ASGI scope is never
modified.

The filter is installed when ``app.main`` is imported. Uvicorn configures logging in
``Config.__init__`` before importing the app, and ``dictConfig`` does not clear an
existing logger's filters, so the install applies to both documented startup paths
(``Dockerfile`` and ``ctl.sh``), which both run ``uvicorn app.main:app``.
"""

from __future__ import annotations

import logging
from urllib.parse import unquote_plus

REDACTED = "[REDACTED]"
SENSITIVE_PARAMETERS = frozenset({"token_hash", "code"})
ACCESS_LOGGER = "uvicorn.access"


def redact_query(query: str) -> str:
    """Redact every sensitive value in a query string, preserving everything else.

    Keys are decoded before matching and compared case-insensitively, so
    ``token%5Fhash``, ``TOKEN_HASH``, ``Token_Hash`` and ``co%64e`` are all matched.
    Values are replaced wholesale, so a percent-encoded value cannot bypass the match.
    Repeated parameters are all redacted; order, unrelated parameters and their original
    encoding are kept exactly as received.
    """
    if not query:
        return query
    parts = query.split("&")
    for index, part in enumerate(parts):
        if not part:
            continue
        key, _separator, _value = part.partition("=")
        try:
            decoded_key = unquote_plus(key)
        except Exception:  # unquote_plus is forgiving; this is belt and braces
            decoded_key = key
        if decoded_key.lower() in SENSITIVE_PARAMETERS:
            parts[index] = key + "=" + REDACTED
    return "&".join(parts)


def redact_path(value: str) -> str:
    """Redact the query part of a request target such as ``/?token_hash=…&type=signup``."""
    if not isinstance(value, str):
        return value
    path, separator, query = value.partition("?")
    if not separator:
        return value
    return path + "?" + redact_query(query)


def _redact_argument(value: object) -> object:
    if isinstance(value, str):
        return redact_path(value)
    return value


class RedactTokenHashFilter(logging.Filter):
    """Rewrite access-log arguments so sensitive Auth values cannot be formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_argument(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact_argument(value) for key, value in record.args.items()
            }
        elif isinstance(record.args, str):
            record.args = redact_path(record.args)

        # A message with no arguments is already final text; redact it directly.
        if not record.args and isinstance(record.msg, str):
            record.msg = redact_path(record.msg)

        # Some Uvicorn versions attach the ASGI scope. Sanitise a copy: the request's own
        # scope must never be modified.
        scope = getattr(record, "scope", None)
        if isinstance(scope, dict):
            query = scope.get("query_string")
            if isinstance(query, (bytes, bytearray)):
                try:
                    cleaned = redact_query(query.decode("latin-1")).encode("latin-1")
                except Exception:
                    cleaned = b""
                safe_scope = dict(scope)
                safe_scope["query_string"] = cleaned
                record.scope = safe_scope
        return True


def install() -> None:
    """Attach the filter once. Safe to call at import and at startup."""
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(
        isinstance(existing, RedactTokenHashFilter) for existing in logger.filters
    ):
        logger.addFilter(RedactTokenHashFilter())
