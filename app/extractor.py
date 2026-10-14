"""Claude extraction: receipt image or free text -> validated `Extraction`."""

from __future__ import annotations

import base64
import logging
from datetime import date
from functools import lru_cache
from typing import Any

import anthropic

from app.config import get_settings
from app.models import CATEGORIES, Extraction

log = logging.getLogger(__name__)

MAX_TOKENS = 2048
TOOL_NAME = "record_transaction"
IMAGE_UNREADABLE = "Receipt is unreadable. Retake it in better light, or type it in."

# The tool schema is the Extraction model, so the two can never drift apart.
TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "Record the single transaction found in a receipt image or a short text note.",
    "input_schema": Extraction.model_json_schema(),
}

_SYSTEM_PROMPT = """\
You convert receipts and short free-text notes into one transaction for a Malaysian expense tracker.

Always report the result by calling the `record_transaction` tool. Never reply with prose or JSON text.

Field rules:
- txn_date: the transaction date as YYYY-MM-DD. Malaysian receipts usually write dates as DD/MM/YYYY. \
If the date is missing, use today's date ({today}).
- amount: the TOTAL actually paid, as a plain number with no currency symbol. Not the subtotal. \
Include tax and service charge.
- currency: ISO code, default "MYR". Amounts are Malaysian Ringgit (RM/MYR) unless the receipt \
clearly shows another currency.
- merchant: shop or payee name, or null.
- category: one of {categories}, or null.
- type: "expense" or "income" (salary, refund, money received = income). Default "expense".
- items: line items if the receipt lists them, otherwise null. Keep each item name as printed, but \
drop any leading product or SKU code (e.g. "SKU 99123 Nasi Lemak" becomes "Nasi Lemak").

If you are unsure about a field, leave it null. Never invent data, and call the tool even when the \
receipt is faded, creased, or partly cut off — report whatever you can read.
"""


class ExtractionError(ValueError):
    """Claude did not return usable structured data (mapped to HTTP 422)."""


class UpstreamError(Exception):
    """The Anthropic API call itself failed (mapped to HTTP 502)."""


def _system_prompt() -> str:
    return _SYSTEM_PROMPT.format(today=date.today().isoformat(), categories=", ".join(CATEGORIES))


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def _create(content: list[dict[str, Any]], model: str, force_tool: bool) -> anthropic.types.Message:
    return _client().messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=_system_prompt(),
        messages=[{"role": "user", "content": content}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL_NAME} if force_tool else {"type": "auto"},
    )


def _tool_choice_unsupported(exc: anthropic.APIError) -> bool:
    """Some models (Haiku 5.5) reject a forced tool_choice with a 400."""
    detail = str(exc).lower()
    return "tool_choice" in detail or "does not support tool" in detail


def _message(content: list[dict[str, Any]], model: str) -> anthropic.types.Message:
    """One Claude turn with the record_transaction tool available."""
    try:
        return _create(content, model, force_tool=True)
    except anthropic.BadRequestError as exc:
        if not _tool_choice_unsupported(exc):
            raise UpstreamError(f"{type(exc).__name__}: {exc}") from exc
        log.warning("Model %s rejected forced tool use, retrying with tool_choice auto: %s", model, exc)
        try:
            return _create(content, model, force_tool=False)
        except anthropic.APIError as retry_exc:
            raise UpstreamError(f"{type(retry_exc).__name__}: {retry_exc}") from retry_exc
    except anthropic.APIError as exc:
        raise UpstreamError(f"{type(exc).__name__}: {exc}") from exc


def _extraction_from(message: anthropic.types.Message) -> Extraction:
    """Validate the tool_use block Claude was asked to produce."""
    for block in message.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return Extraction.model_validate(dict(block.input))
    raise ExtractionError("Claude did not call the record_transaction tool.")


def _extract(content: list[dict[str, Any]]) -> Extraction:
    """Try the configured model, then the fallback model, then give up."""
    settings = get_settings()
    models = [settings.claude_model]
    if settings.claude_fallback_model not in models:
        models.append(settings.claude_fallback_model)

    problem = "no usable output"
    for model in models:
        try:
            extraction = _extraction_from(_message(content, model))
        except ValueError as exc:  # pydantic.ValidationError / ExtractionError
            problem = str(exc)
            log.warning("Extraction with %s failed: %s", model, exc)
            continue
        if extraction.amount is None:
            problem = "the total amount could not be read"
            log.warning("Extraction with %s found no amount", model)
            continue
        return extraction
    raise ExtractionError(f"Could not extract a transaction from this input ({problem}).")


def extract_from_image(image: bytes, media_type: str) -> Extraction:
    """Extract a transaction from a receipt photo."""
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image).decode("ascii"),
            },
        },
        {"type": "text", "text": "Record this receipt with the tool."},
    ]
    try:
        return _extract(content)
    except ExtractionError as exc:
        log.warning("Receipt could not be read: %s", exc)
        raise ExtractionError(IMAGE_UNREADABLE) from exc


def extract_from_text(text: str) -> Extraction:
    """Extract a transaction from a short note such as "makan tengah hari 12 ringgit"."""
    content = [{"type": "text", "text": f"Record this transaction with the tool:\n\n{text.strip()}"}]
    try:
        return _extract(content)
    except ExtractionError as exc:
        raise ExtractionError(
            "Could not read a transaction from that. Try something like "
            "\u201cmakan tengah hari 12 ringgit\u201d."
        ) from exc
