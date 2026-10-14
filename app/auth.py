"""Static API key auth for the iPhone Shortcut (header: X-API-Key)."""

from __future__ import annotations

import secrets
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings

# Brute-force throttling. ponytail: counters live in this process, so with several
# replicas each one counts separately and a restart forgets; move to Redis if that
# ever matters.
FAILURE_LIMIT = 10
FAILURE_WINDOW_SECONDS = 60
_failures: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    """First hop of X-Forwarded-For (the client as the outermost proxy saw it), else the peer."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    first_hop = forwarded.split(",")[0].strip()
    if first_hop:
        return first_hop
    return request.client.host if request.client else "unknown"


def recent_failures(ip: str) -> int:
    """Failed attempts from this IP inside the window, dropping anything older."""
    cutoff = time.monotonic() - FAILURE_WINDOW_SECONDS
    history = [stamp for stamp in _failures.get(ip, []) if stamp > cutoff]
    if history:
        _failures[ip] = history
    else:
        _failures.pop(ip, None)
    return len(history)


def record_failure(ip: str) -> None:
    """Note one bad key from this IP."""
    _failures.setdefault(ip, []).append(time.monotonic())


def clear_failures(ip: str) -> None:
    """A good key wipes the slate for that IP."""
    _failures.pop(ip, None)


def key_matches(provided: str | None, expected: str) -> bool:
    """Constant-time compare. Bytes, because compare_digest(str) raises on non-ASCII."""
    if provided is None:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def require_api_key(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Raise 401 unless `X-API-Key` matches API_KEY; 429 once an IP keeps failing."""
    ip = client_ip(request)
    if recent_failures(ip) >= FAILURE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed API key attempts. Try again in {FAILURE_WINDOW_SECONDS} seconds.",
            headers={"Retry-After": str(FAILURE_WINDOW_SECONDS)},
        )

    if key_matches(x_api_key, settings.api_key):
        clear_failures(ip)
        return

    record_failure(ip)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid X-API-Key header.",
    )
