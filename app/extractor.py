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
IMAGE_UNREADABLE = "That image could not be read. Try a clearer one, or type the transaction in."

# The tool schema is the Extraction model, so the two can never drift apart.
TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": ("Record the single transaction found in a photo of a receipt, a bank or "
                    "e-wallet screenshot, or a short text note."),
    "input_schema": Extraction.model_json_schema(),
}

_SYSTEM_PROMPT = """\
You convert an image or a short free-text note into one transaction for a Malaysian expense tracker.

The image is either a photo of a paper receipt, or a **screenshot of a bank or e-wallet screen** \
(Maybank MAE/M2U, DuitNow QR, Touch 'n Go eWallet, GrabPay and the like), typically headed \
"Payment Successful", "Transfer Successful" or "Transaction Details".

Always report the result by calling the `record_transaction` tool. Never reply with prose or JSON text.

1. What kind of document is it?
- document_kind: "receipt" for a photo of paper, "bank_screenshot" for a phone screen showing a \
completed transaction. Decide from the layout, not from the wording of the message.

2. Read these off the document:
- merchant: for a receipt, the shop. For a screenshot, the **recipient or sender** name — what follows \
"Transfer to", "Payment to", "Paid to", "DuitNow to", "Received from", "From". Null if unreadable.
- amount: a plain number with no currency symbol. On a screenshot use the transaction amount — never a \
balance, an available limit, a points total, or an amount shown elsewhere on the screen.
- txn_date: YYYY-MM-DD. Malaysian documents usually write dates as DD/MM/YYYY. Today is {today}: use it \
when the date is missing.
- txn_time: "HH:MM" in 24-hour form when the screen prints a time ("14:32", "2:32 PM" -> "14:32"). Null \
when there is none or it is unreadable.
- reference: the reference, transaction or receipt number exactly as printed — a bank app screenshot \
almost always shows one. Null when unreadable.
- currency: ISO code, default "MYR".
- category: one of {categories}, picked from the merchant when that is obvious (Kopitiam -> food, \
TNB -> bills, Grab -> transport, Uniqlo -> shopping). Use "other" when it is not obvious; null only if \
the document itself is unreadable.

3. Which way did the money go? This decides the type:
- expense: money left the account — "Transfer to", "Payment", "Paid", "DuitNow to", "Sent", a minus \
sign, or an amount in red.
- income: money arrived — "Received from", "Credit", "Refund", "Cash in", a plus sign.
- If you cannot tell which, leave type null rather than guessing; do not default to expense on a \
screenshot. On a paper receipt the money always left, so default to expense.

4. Never do these:
- Never return an account number, card number, phone number or balance — not in any field, and not \
inside a note. They are not part of the transaction and we do not keep them.
- Never invent a value. A field you cannot read is null, and that is the correct answer.
- For a bank_screenshot leave items null: a screen has no line items.

Call the tool even when the image is faded, creased, cropped or blurred. Report whatever you can read \
and leave the rest null.
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
        {"type": "text", "text": "Record the transaction on this receipt or bank/e-wallet screenshot."},
    ]
    try:
        return _extract(content)
    except ExtractionError as exc:
        log.warning("Image could not be read: %s", exc)
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
