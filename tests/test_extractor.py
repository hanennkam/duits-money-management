"""Extraction via Claude tool use. Claude is mocked: no network, no API key needed."""

from __future__ import annotations

import base64
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

import anthropic
import httpx
import pytest

from app import extractor
from app.config import get_settings

GOOD_INPUT: dict[str, Any] = {
    "txn_date": "2026-10-11",
    "amount": 15.08,
    "currency": "MYR",
    "merchant": "Restoran Nasi Kandar Pelita",
    "category": "food",
    "type": "expense",
    "items": [{"name": "Nasi Lemak Ayam", "qty": 1, "price": 8.5}],
}


def reply(tool_input: dict[str, Any] | None = GOOD_INPUT, text: str = "") -> SimpleNamespace:
    """A stand-in for an anthropic Message: text blocks and/or one tool_use block."""
    blocks = []
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))
    if tool_input is not None:
        blocks.append(SimpleNamespace(type="tool_use", name=extractor.TOOL_NAME, input=tool_input))
    return SimpleNamespace(content=blocks)


def bad_request(message: str) -> anthropic.BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json={"error": {"message": message}})
    return anthropic.BadRequestError(message, response=response, body=None)


def server_error() -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError("overloaded", response=httpx.Response(500, request=request), body=None)


class FakeMessages:
    """Records every request and replays canned replies in order."""

    def __init__(self, replies: list[Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._replies = list(replies)

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self._replies.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def models(self) -> list[str]:
        return [call["model"] for call in self.calls]

    @property
    def tool_choices(self) -> list[str]:
        return [call["tool_choice"]["type"] for call in self.calls]


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], FakeMessages]:
    def install(replies: list[Any]) -> FakeMessages:
        fake = FakeMessages(replies)
        monkeypatch.setattr(extractor, "_client", lambda: SimpleNamespace(messages=fake))
        return fake

    return install


def test_tool_use_input_becomes_a_validated_extraction(
    claude: Callable[[list[Any]], FakeMessages]
) -> None:
    fake = claude([reply()])

    extraction = extractor.extract_from_image(b"\xff\xd8jpeg", "image/jpeg")

    assert extraction.amount == Decimal("15.08")
    assert extraction.txn_date.isoformat() == "2026-10-11"
    assert extraction.merchant == "Restoran Nasi Kandar Pelita"
    assert extraction.items is not None and extraction.items[0].price == Decimal("8.50")
    assert extraction.needs_review is False

    call = fake.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": extractor.TOOL_NAME}
    assert [tool["name"] for tool in call["tools"]] == [extractor.TOOL_NAME]
    # Haiku 5.5 rejects these, so they must never be sent.
    assert "temperature" not in call and "top_p" not in call


def test_tool_schema_is_the_extraction_model(claude: Callable[[list[Any]], FakeMessages]) -> None:
    schema = extractor.TOOL["input_schema"]
    assert set(schema["properties"]) >= {"txn_date", "amount", "merchant", "category", "type", "items"}
    assert "food" in str(schema["properties"]["category"])
    assert "LineItem" in schema["$defs"]


def test_image_is_sent_base64_encoded(claude: Callable[[list[Any]], FakeMessages]) -> None:
    fake = claude([reply()])
    original = b"\xff\xd8\xff\xe0fake-jpeg-bytes"

    extractor.extract_from_image(original, "image/jpeg")

    block = fake.calls[0]["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/jpeg"
    assert base64.standard_b64decode(block["source"]["data"]) == original


def test_text_notes_are_extracted_the_same_way(claude: Callable[[list[Any]], FakeMessages]) -> None:
    fake = claude([reply({**GOOD_INPUT, "merchant": None})])

    extraction = extractor.extract_from_text("makan tengah hari 12 ringgit")

    assert extraction.needs_review is True  # no merchant -> flagged for review
    assert "makan tengah hari 12 ringgit" in fake.calls[0]["messages"][0]["content"][0]["text"]


def test_falls_back_to_the_fallback_model_when_validation_fails(
    claude: Callable[[list[Any]], FakeMessages]
) -> None:
    settings = get_settings()
    fake = claude([reply({**GOOD_INPUT, "category": "foods"}), reply()])

    extraction = extractor.extract_from_image(b"jpeg", "image/jpeg")

    assert fake.models == [settings.claude_model, settings.claude_fallback_model]
    assert settings.claude_fallback_model == "claude-sonnet-5-5"
    assert extraction.amount == Decimal("15.08")


def test_falls_back_when_the_tool_was_never_called(
    claude: Callable[[list[Any]], FakeMessages]
) -> None:
    fake = claude([reply(tool_input=None, text="Sorry, I cannot read this."), reply()])

    assert extractor.extract_from_image(b"jpeg", "image/jpeg").amount == Decimal("15.08")
    assert len(fake.calls) == 2


def test_falls_back_when_the_total_is_missing(claude: Callable[[list[Any]], FakeMessages]) -> None:
    without_amount = {key: value for key, value in GOOD_INPUT.items() if key != "amount"}
    fake = claude([reply(without_amount), reply(without_amount)])

    with pytest.raises(extractor.ExtractionError):
        extractor.extract_from_image(b"jpeg", "image/jpeg")

    assert len(fake.calls) == 2  # primary model, then the fallback model


def test_unreadable_receipt_asks_for_a_retake(claude: Callable[[list[Any]], FakeMessages]) -> None:
    claude([reply(tool_input=None), reply(tool_input=None)])

    with pytest.raises(extractor.ExtractionError) as caught:
        extractor.extract_from_image(b"jpeg", "image/jpeg")

    assert str(caught.value) == "Receipt is unreadable. Retake it in better light, or type it in."


def test_forced_tool_choice_downgrades_to_auto(claude: Callable[[list[Any]], FakeMessages]) -> None:
    fake = claude([bad_request("tool_choice is not supported for this model"), reply()])

    extraction = extractor.extract_from_image(b"jpeg", "image/jpeg")

    assert fake.tool_choices == ["tool", "auto"]
    assert fake.models == [get_settings().claude_model] * 2  # same model, not the fallback
    assert extraction.amount == Decimal("15.08")


def test_forced_tool_choice_that_keeps_failing_is_an_upstream_error(
    claude: Callable[[list[Any]], FakeMessages]
) -> None:
    claude([bad_request("tool_choice is not supported"), server_error()])

    with pytest.raises(extractor.UpstreamError):
        extractor.extract_from_image(b"jpeg", "image/jpeg")


def test_other_api_errors_are_upstream_errors(claude: Callable[[list[Any]], FakeMessages]) -> None:
    claude([anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))])

    with pytest.raises(extractor.UpstreamError):
        extractor.extract_from_text("makan tengah hari 12 ringgit")

