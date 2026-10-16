"""Signed receipt URLs must come back absolute.

Supabase answers a signed URL with a path relative to its Storage API. A client cannot open
`/object/sign/...` on its own, so db.create_receipt_url joins it to the project's Storage base.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from app import db
from conftest import SETTINGS

USER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """db.get_settings is read at call time; point it at the test settings, never the live .env."""
    monkeypatch.setattr("app.db.get_settings", lambda: SETTINGS)


def test_a_relative_signed_path_is_joined_to_the_storage_base() -> None:
    url = db.absolute_receipt_url("/object/sign/receipts/2026/10/x.jpg?token=abc")
    assert url == f"{SETTINGS.supabase_url}/storage/v1/object/sign/receipts/2026/10/x.jpg?token=abc"


def test_a_path_without_a_leading_slash_is_still_joined() -> None:
    url = db.absolute_receipt_url("object/sign/receipts/x.jpg?token=abc")
    assert url.startswith(f"{SETTINGS.supabase_url}/storage/v1/object/sign/")


def test_an_absolute_url_is_left_alone() -> None:
    for url in ("https://cdn.example/x.jpg", "http://cdn.example/x.jpg"):
        assert db.absolute_receipt_url(url) == url


def test_the_supabase_url_trailing_slash_does_not_double_up() -> None:
    joined = db.absolute_receipt_url("/object/sign/x.jpg")
    assert "//storage" not in joined.replace("https://", "")


def test_create_receipt_url_returns_an_absolute_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end through the helper: the storage client's relative path comes back absolute."""
    seen: list[str] = []

    class FakeBucket:
        def create_signed_url(self, path: str, expires_in: int) -> dict[str, str]:
            seen.append(path)
            return {"signedURL": f"/object/sign/receipts/{path}?token=t"}

    class FakeClient:
        class _Storage:
            def from_(self, name: str) -> FakeBucket:
                return FakeBucket()

        storage = _Storage()

    monkeypatch.setattr("app.db.get_supabase", lambda: FakeClient())
    monkeypatch.setattr("app.db.get_settings", lambda: SETTINGS)

    path = f"{USER}/2026/10/abc.jpg"
    url = db.create_receipt_url(path, 60, user_id=USER)

    assert seen == [path]
    assert url == f"{SETTINGS.supabase_url}/storage/v1/object/sign/receipts/{path}?token=t"


def test_the_owner_folder_is_still_checked_before_signing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The absolute-URL work must not weaken the ownership check."""
    monkeypatch.setattr("app.db.get_supabase", lambda: None)
    monkeypatch.setattr("app.db.get_settings", lambda: SETTINGS)
    with pytest.raises(ValueError, match="outside the owner"):
        db.create_receipt_url("2026/10/x.jpg", 60, user_id=USER)


def test_a_path_outside_the_owner_folder_reads_as_no_receipt() -> None:
    """The rule the routes use to decide between "no receipt" and a 500."""
    mine = f"{USER}/2026/10/abc.jpg"
    assert db.owned_receipt_path(mine, user_id=USER) == mine
    assert db.owned_receipt_path(None, user_id=USER) is None
    assert db.owned_receipt_path("", user_id=USER) is None
    # a migration leftover: another owner's folder, or the un-prefixed legacy form
    assert db.owned_receipt_path("other/2026/10/abc.jpg", user_id=USER) is None
    assert db.owned_receipt_path("2026/10/abc.jpg", user_id=USER) is None
