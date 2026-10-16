"""Who is calling. Every request carries a Supabase access token (Authorization: Bearer).

The user id comes only from the token's `sub` claim, never from the body, the query or a path. A legacy
X-API-Key is accepted only when ALLOW_LEGACY_API_KEY is on, and then it acts as LEGACY_USER_ID.
"""

from __future__ import annotations

import secrets
import time
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings

# Brute-force throttling. ponytail: counters live in this process, so with several
# replicas each one counts separately and a restart forgets; move to Redis if that
# ever matters.
FAILURE_LIMIT = 10
FAILURE_WINDOW_SECONDS = 60
_failures: dict[str, list[float]] = {}

JWT_AUDIENCE = "authenticated"
JWT_ALGORITHMS = ["ES256"]  # the project's signing key; HS256 and "none" are never accepted
CLOCK_LEEWAY_SECONDS = 30
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss"]


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
    """Note one bad credential from this IP."""
    _failures.setdefault(ip, []).append(time.monotonic())


def clear_failures(ip: str) -> None:
    """A good credential wipes the slate for that IP."""
    _failures.pop(ip, None)


def key_matches(provided: str | None, expected: str) -> bool:
    """Constant-time compare. Bytes, because compare_digest(str) raises on non-ASCII."""
    if provided is None:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def jwks_url(settings: Settings) -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def issuer(settings: Settings) -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1"


@lru_cache(maxsize=4)
def jwks_client(url: str) -> jwt.PyJWKClient:
    """Fetches and caches the project's public keys. An unknown `kid` triggers one refetch (rotation)."""
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=10)


def signing_key_for(token: str, url: str) -> Any:
    """The public key the token's `kid` names. Raises a PyJWT error for an unknown or missing kid."""
    return jwks_client(url).get_signing_key_from_jwt(token).key


def user_from_token(token: str, settings: Settings) -> UUID:
    """The verified user id in `sub`. Raises jwt.PyJWTError for anything that is not a valid token."""
    claims = jwt.decode(
        token,
        signing_key_for(token, jwks_url(settings)),
        algorithms=JWT_ALGORITHMS,
        audience=JWT_AUDIENCE,
        issuer=issuer(settings),
        leeway=CLOCK_LEEWAY_SECONDS,
        options={"require": REQUIRED_CLAIMS},
    )
    try:
        return UUID(str(claims["sub"]))
    except ValueError as exc:
        raise jwt.exceptions.InvalidSubjectError("sub is not a user id") from exc


async def current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> UUID:
    """The caller's user id. 429 once an IP keeps failing; 503 if the signing keys cannot be fetched."""
    ip = client_ip(request)
    if recent_failures(ip) >= FAILURE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {FAILURE_WINDOW_SECONDS} seconds.",
            headers={"Retry-After": str(FAILURE_WINDOW_SECONDS)},
        )

    user: UUID | None = None
    if authorization and authorization.lower().startswith("bearer "):
        try:
            user = user_from_token(authorization[7:].strip(), settings)
        except jwt.PyJWKClientConnectionError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not fetch the sign-in keys. Try again shortly.",
            ) from exc
        except jwt.PyJWTError:
            user = None
    elif settings.allow_legacy_api_key and key_matches(x_api_key, settings.api_key):
        user = settings.legacy_user_id

    if user is None:
        record_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid credentials.",
        )
    clear_failures(ip)
    return user


CurrentUser = Annotated[UUID, Depends(current_user)]
