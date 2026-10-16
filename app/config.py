"""Runtime settings, read from the environment (.env loaded by python-dotenv).

Secrets never live in code: every value below comes from an env var.
"""

from __future__ import annotations

import os
from functools import lru_cache
from uuid import UUID

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

load_dotenv()

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5"
DEFAULT_CLAUDE_FALLBACK_MODEL = "claude-sonnet-5-5"
DEFAULT_RECEIPTS_BUCKET = "receipts"
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class Settings(BaseModel):
    """Validated application configuration."""

    model_config = ConfigDict(frozen=True)

    api_key: str
    supabase_url: str
    supabase_service_key: str
    anthropic_api_key: str
    claude_model: str = DEFAULT_CLAUDE_MODEL
    claude_fallback_model: str = DEFAULT_CLAUDE_FALLBACK_MODEL
    receipts_bucket: str = DEFAULT_RECEIPTS_BUCKET
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    # Temporary fallback for the single-owner period: X-API-Key acts as legacy_user_id. Off by default.
    allow_legacy_api_key: bool = False
    legacy_user_id: UUID | None = None


REQUIRED_ENV = ("API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "ANTHROPIC_API_KEY")


def env_value(name: str) -> str | None:
    """The variable's value, stripped, or None when unset or blank. Values are never reported."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def missing_env() -> list[str]:
    """Names of the required variables that are unset or blank (never their values)."""
    return [name for name in REQUIRED_ENV if env_value(name) is None]


def is_production() -> bool:
    """True when ENVIRONMENT=production: docs are off and startup insists on a real config."""
    return (env_value("ENVIRONMENT") or "").lower() == "production"


def max_upload_bytes() -> int:
    """MAX_UPLOAD_BYTES, or the 10 MB default when it is unset."""
    raw = env_value("MAX_UPLOAD_BYTES")
    if raw is None:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError("MAX_UPLOAD_BYTES must be a whole number of bytes.") from exc


def legacy_settings() -> tuple[bool, UUID | None]:
    """ALLOW_LEGACY_API_KEY (off unless 1/true/yes) and LEGACY_USER_ID, which it requires."""
    allowed = (env_value("ALLOW_LEGACY_API_KEY") or "").lower() in {"1", "true", "yes"}
    if not allowed:
        return False, None
    raw = env_value("LEGACY_USER_ID")
    try:
        return True, UUID(raw) if raw else None
    except ValueError:
        return True, None  # reported below by name, never by value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build settings from the environment. Cached; call `get_settings.cache_clear()` to reload."""
    missing = missing_env()
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Set them in the environment and restart."
        )

    allow_legacy, legacy_user_id = legacy_settings()
    if allow_legacy and legacy_user_id is None:
        raise RuntimeError(
            "ALLOW_LEGACY_API_KEY is on, so LEGACY_USER_ID must be set to a valid user id (UUID)."
        )

    return Settings(
        allow_legacy_api_key=allow_legacy,
        legacy_user_id=legacy_user_id,
        api_key=env_value("API_KEY") or "",
        supabase_url=env_value("SUPABASE_URL") or "",
        supabase_service_key=env_value("SUPABASE_SERVICE_KEY") or "",
        anthropic_api_key=env_value("ANTHROPIC_API_KEY") or "",
        claude_model=env_value("CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL,
        claude_fallback_model=env_value("CLAUDE_FALLBACK_MODEL") or DEFAULT_CLAUDE_FALLBACK_MODEL,
        receipts_bucket=env_value("RECEIPTS_BUCKET") or DEFAULT_RECEIPTS_BUCKET,
        max_upload_bytes=max_upload_bytes(),
    )
