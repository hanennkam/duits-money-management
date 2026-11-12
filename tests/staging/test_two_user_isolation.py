"""Real two-account isolation checks against the guarded STAGING Supabase project.

These tests intentionally write only to two dedicated staging accounts. They restore finance settings
and delete every transaction/commitment they create, even when an assertion fails.
Never point the staging runner at production.

The `finally:` block cannot run when the process is killed (SIGKILL, a crashed machine, a CI timeout).
Every delete in it is idempotent and scoped to an id this test created, so a rerun is safe;
NEXT_STEPS.md holds the read-only residue check and the staging-only recovery steps.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

pytestmark = pytest.mark.staging


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"Missing {name} in .env.staging; value is intentionally not shown.")
    return value


def _login(email_name: str, password_name: str) -> str:
    settings = get_settings()
    publishable_key = settings.supabase_publishable_key
    if not publishable_key:
        pytest.fail("SUPABASE_PUBLISHABLE_KEY is missing from .env.staging.")
    response = httpx.post(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/token?grant_type=password",
        headers={"apikey": publishable_key, "Content-Type": "application/json"},
        json={"email": _required(email_name), "password": _required(password_name)},
        timeout=20.0,
    )
    if response.status_code != 200:
        pytest.fail(
            f"Staging sign-in failed for {email_name}; verify the dedicated account, password "
            "and email-confirmation status. Response details are intentionally suppressed."
        )
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        pytest.fail("Supabase staging sign-in returned no access token.")
    return token


def _service_headers() -> dict[str, str]:
    """Service-key headers for the two direct reads and the restore-to-absence delete."""
    key = get_settings().supabase_service_key
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _stored_settings(user_id: str) -> list[dict[str, Any]]:
    """The settings row as stored, or [] when the API has only ever served its defaults."""
    base = get_settings().supabase_url.rstrip("/")
    response = httpx.get(
        f"{base}/rest/v1/user_finance_settings",
        headers=_service_headers(),
        params={"user_id": f"eq.{user_id}", "select": "*"},
        timeout=20.0,
    )
    if response.status_code != 200:
        pytest.fail(f"Could not read the staging settings row (HTTP {response.status_code}).")
    return response.json()


def _delete(client: TestClient, path: str, headers: dict[str, str], label: str,
            problems: list[str]) -> None:
    """Delete one created row. 404 means it is already gone (a rerun or an earlier partial cleanup)."""
    try:
        response = client.delete(path, headers=headers)
    except Exception as exc:  # a transport failure must not stop the other ids
        problems.append(f"{label}: {exc}")
        return
    if response.status_code not in (200, 204, 404):
        problems.append(f"{label}: HTTP {response.status_code} {response.text[:120]}")


def test_two_staging_users_cannot_access_each_others_financial_data() -> None:
    """Exercise the real Auth/JWKS/API/DB path with two existing staging accounts."""
    token_a = _login("STAGING_USER_A_EMAIL", "STAGING_USER_A_PASSWORD")
    token_b = _login("STAGING_USER_B_EMAIL", "STAGING_USER_B_PASSWORD")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    settings = get_settings()
    assert settings.supabase_url.rstrip("/").endswith(".supabase.co")

    month = date.today().strftime("%Y-%m")
    marker = f"STAGING-ISOLATION-{uuid4().hex[:12]}"
    transaction_a_id: str | None = None
    transaction_b_id: str | None = None
    commitment_a_id: str | None = None
    commitment_b_id: str | None = None

    with TestClient(app) as client:
        original_settings_a = client.get("/finance/settings", headers=headers_a)
        original_settings_b = client.get("/finance/settings", headers=headers_b)
        assert original_settings_a.status_code == 200, "Could not read staging user A settings."
        assert original_settings_b.status_code == 200, "Could not read staging user B settings."
        before_a = original_settings_a.json()
        before_b = original_settings_b.json()
        user_a = before_a["user_id"]
        # The API serves defaults without writing a row, so ask the table directly whether one existed.
        settings_existed = bool(_stored_settings(user_a))

        try:
            # Give A a distinctive temporary value and prove B's settings do not change.
            changed = client.put(
                "/finance/settings",
                headers=headers_a,
                json={"opening_balance": 812345.67, "monthly_budget": 98765.43},
            )
            assert changed.status_code == 200, "Could not update staging user A settings."
            after_b = client.get("/finance/settings", headers=headers_b)
            assert after_b.status_code == 200, "Could not re-read staging user B settings."
            assert after_b.json()["opening_balance"] == before_b["opening_balance"]
            assert after_b.json()["monthly_budget"] == before_b["monthly_budget"]

            # Create one transaction for each owner.
            created_a = client.post(
                "/transactions",
                headers=headers_a,
                json={
                    "amount": 12.34,
                    "txn_date": date.today().isoformat(),
                    "merchant": f"{marker}-A",
                    "category": "other",
                    "type": "expense",
                },
            )
            assert created_a.status_code == 201, "Could not create staging user A transaction."
            transaction_a_id = created_a.json()["id"]

            created_b = client.post(
                "/transactions",
                headers=headers_b,
                json={
                    "amount": 56.78,
                    "txn_date": date.today().isoformat(),
                    "merchant": f"{marker}-B",
                    "category": "other",
                    "type": "expense",
                },
            )
            assert created_b.status_code == 201, "Could not create staging user B transaction."
            transaction_b_id = created_b.json()["id"]

            list_a = client.get(f"/transactions?month={month}", headers=headers_a)
            list_b = client.get(f"/transactions?month={month}", headers=headers_b)
            assert list_a.status_code == 200 and transaction_a_id in {
                row["id"] for row in list_a.json()
            }
            assert list_b.status_code == 200 and transaction_b_id in {
                row["id"] for row in list_b.json()
            }
            assert transaction_a_id not in {row["id"] for row in list_b.json()}
            assert transaction_b_id not in {row["id"] for row in list_a.json()}

            # B must not read, mutate or delete A's transaction.
            assert client.get(
                f"/transactions/{transaction_a_id}", headers=headers_b
            ).status_code == 404
            assert client.patch(
                f"/transactions/{transaction_a_id}",
                headers=headers_b,
                json={"amount": 999.99},
            ).status_code == 404
            assert client.delete(
                f"/transactions/{transaction_a_id}", headers=headers_b
            ).status_code == 404

            # Commitments and paid marks must also be owner-scoped.
            created_commitment_a = client.post(
                "/commitments",
                headers=headers_a,
                json={"name": f"{marker}-A", "amount": 123.45, "day_of_month": 15},
            )
            assert created_commitment_a.status_code == 201, "Could not create user A commitment."
            commitment_a_id = created_commitment_a.json()["id"]

            created_commitment_b = client.post(
                "/commitments",
                headers=headers_b,
                json={"name": f"{marker}-B", "amount": 234.56, "day_of_month": 20},
            )
            assert created_commitment_b.status_code == 201, "Could not create user B commitment."
            commitment_b_id = created_commitment_b.json()["id"]

            assert client.patch(
                f"/commitments/{commitment_a_id}",
                headers=headers_b,
                json={"name": f"{marker}-HIJACK"},
            ).status_code == 404
            assert client.delete(
                f"/commitments/{commitment_a_id}", headers=headers_b
            ).status_code == 404
            assert client.post(
                f"/commitments/{commitment_a_id}/paid",
                headers=headers_b,
                json={"month": month},
            ).status_code == 404

            commitments_b = client.get(f"/commitments?month={month}", headers=headers_b)
            assert commitments_b.status_code == 200
            assert commitment_a_id not in {row["id"] for row in commitments_b.json()}

        finally:
            # Cleanup is owner-authenticated and does not touch pre-existing user data. Every failure is
            # collected and raised at the end: a bad delete cannot pass silently, and the other ids are
            # still attempted.
            problems: list[str] = []
            if transaction_a_id:
                _delete(client, f"/transactions/{transaction_a_id}", headers_a,
                        "delete A transaction", problems)
            if transaction_b_id:
                _delete(client, f"/transactions/{transaction_b_id}", headers_b,
                        "delete B transaction", problems)
            if commitment_a_id:
                _delete(client, f"/commitments/{commitment_a_id}", headers_a,
                        "delete A commitment", problems)
            if commitment_b_id:
                _delete(client, f"/commitments/{commitment_b_id}", headers_b,
                        "delete B commitment", problems)

            try:
                if settings_existed:
                    restored = client.put(
                        "/finance/settings",
                        headers=headers_a,
                        json={
                            "opening_balance": before_a["opening_balance"],
                            "monthly_budget": before_a["monthly_budget"],
                        },
                    )
                    if restored.status_code != 200:
                        problems.append(f"restore A settings: HTTP {restored.status_code}")
                    elif any(
                        restored.json().get(key) != before_a.get(key)
                        for key in ("opening_balance", "monthly_budget", "currency")
                    ):
                        problems.append("A settings did not read back as they were before the test")
                else:
                    # No row existed before the test, so putting the defaults back would create one.
                    # Delete the row the test made, scoped to A's own id, and verify absence.
                    base = get_settings().supabase_url.rstrip("/")
                    removed = httpx.delete(
                        f"{base}/rest/v1/user_finance_settings",
                        headers=_service_headers(),
                        params={"user_id": f"eq.{user_a}"},
                        timeout=20.0,
                    )
                    if removed.status_code not in (200, 204):
                        problems.append(f"delete A settings row: HTTP {removed.status_code}")
                    elif _stored_settings(user_a):
                        problems.append("A settings row still exists; there was no row before the test")
            except Exception as exc:
                problems.append(f"A settings restore failed: {exc}")

            if problems:
                raise AssertionError("staging cleanup failed:\n" + "\n".join(problems))


def _settings_snapshot(user_id: str) -> dict[str, Any] | None:
    """The raw settings row, or None when the API is serving defaults with no stored row."""
    rows = _stored_settings(user_id)
    return rows[0] if rows else None


def _settings_values_match(row: dict[str, Any] | None, snapshot: dict[str, Any] | None) -> bool:
    """Compare the values the API restores; `updated_at` legitimately changes on a restore write."""
    if snapshot is None:
        return row is None
    if row is None:
        return False
    try:
        return (
            str(row.get("user_id")) == str(snapshot.get("user_id"))
            and Decimal(str(row.get("opening_balance"))) == Decimal(str(snapshot.get("opening_balance")))
            and Decimal(str(row.get("monthly_budget"))) == Decimal(str(snapshot.get("monthly_budget")))
            and row.get("currency") == snapshot.get("currency")
        )
    except Exception:
        return False


def _settings_row_match(row: dict[str, Any] | None, snapshot: dict[str, Any] | None) -> bool:
    """Exact row comparison, including updated_at, for proving an untouched account stayed untouched."""
    if snapshot is None:
        return row is None
    if row is None:
        return False
    return all(
        str(row.get(key)) == str(snapshot.get(key))
        for key in ("user_id", "opening_balance", "monthly_budget", "currency", "updated_at")
    )


def _restore_settings(
    client: TestClient,
    headers: dict[str, str],
    label: str,
    user_id: str,
    snapshot: dict[str, Any] | None,
    problems: list[str],
) -> None:
    """Restore one account's settings to its pre-test state, or delete the row the test created."""
    try:
        current = _settings_snapshot(user_id)
        if snapshot is None:
            if current is None:
                return
            base = get_settings().supabase_url.rstrip("/")
            removed = httpx.delete(
                f"{base}/rest/v1/user_finance_settings",
                headers=_service_headers(),
                params={"user_id": f"eq.{user_id}"},
                timeout=20.0,
            )
            if removed.status_code not in (200, 204):
                problems.append(f"{label} settings row delete: HTTP {removed.status_code}")
            elif _settings_snapshot(user_id) is not None:
                problems.append(f"{label} settings row still exists after delete")
            return

        if current is not None and _settings_values_match(current, snapshot):
            return
        restored = client.put(
            "/finance/settings",
            headers=headers,
            json={
                "opening_balance": snapshot["opening_balance"],
                "monthly_budget": snapshot["monthly_budget"],
            },
        )
        if restored.status_code != 200:
            problems.append(f"{label} settings restore: HTTP {restored.status_code}")
        elif not _settings_values_match(_settings_snapshot(user_id), snapshot):
            problems.append(f"{label} settings did not read back as before")
    except Exception as exc:
        problems.append(f"{label} settings restore failed: {exc}")


def test_finance_settings_are_owner_scoped_and_require_auth() -> None:
    """Close the finance-settings gaps: B creates/reads, target-user attempts fail, anon is refused."""
    token_a = _login("STAGING_USER_A_EMAIL", "STAGING_USER_A_PASSWORD")
    token_b = _login("STAGING_USER_B_EMAIL", "STAGING_USER_B_PASSWORD")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    settings = get_settings()
    assert settings.supabase_url.rstrip("/").endswith(".supabase.co")

    with TestClient(app) as client:
        original_a = client.get("/finance/settings", headers=headers_a)
        original_b = client.get("/finance/settings", headers=headers_b)
        assert original_a.status_code == 200, "Could not read staging user A settings."
        assert original_b.status_code == 200, "Could not read staging user B settings."
        before_a = original_a.json()
        user_a = before_a["user_id"]
        user_b = original_b.json()["user_id"]
        assert user_a != user_b
        snapshot_a = _settings_snapshot(user_a)
        snapshot_b = _settings_snapshot(user_b)

        problems: list[str] = []
        try:
            # 1. B creates and reads B's own settings. This must not touch A.
            b_written = client.put(
                "/finance/settings",
                headers=headers_b,
                json={"opening_balance": 111111.11, "monthly_budget": 22222.22},
            )
            assert b_written.status_code == 200, "B could not create their own settings."
            assert b_written.json()["user_id"] == user_b
            b_read = client.get("/finance/settings", headers=headers_b)
            assert b_read.status_code == 200
            assert b_read.json()["user_id"] == user_b
            assert Decimal(str(b_read.json()["opening_balance"])) == Decimal("111111.11")
            assert Decimal(str(b_read.json()["monthly_budget"])) == Decimal("22222.22")
            stored_b = _settings_snapshot(user_b)
            assert stored_b is not None and str(stored_b.get("user_id")) == user_b
            assert _settings_row_match(_settings_snapshot(user_a), snapshot_a), "B's write changed A"

            # 2. A asks for A's settings with a user_id=B query parameter. It must return A's
            # data or be rejected, never B's data.
            a_target = client.get(f"/finance/settings?user_id={user_b}", headers=headers_a)
            assert a_target.status_code in (200, 400, 403, 404, 422), a_target.status_code
            if a_target.status_code == 200:
                assert a_target.json()["user_id"] == user_a
                assert Decimal(str(a_target.json()["opening_balance"])) == Decimal(
                    str(before_a["opening_balance"])
                )
                assert Decimal(str(a_target.json()["monthly_budget"])) == Decimal(
                    str(before_a["monthly_budget"])
                )
            assert _settings_row_match(_settings_snapshot(user_a), snapshot_a), "A's query changed A"

            # 3. B tries to update A with a user_id=A query parameter. B may update only B;
            # A's stored row must remain byte-for-byte unchanged.
            b_target = client.put(
                f"/finance/settings?user_id={user_a}",
                headers=headers_b,
                json={"opening_balance": 333333.33, "monthly_budget": 44444.44},
            )
            assert b_target.status_code in (200, 400, 403, 404, 422), b_target.status_code
            assert _settings_row_match(_settings_snapshot(user_a), snapshot_a), "B changed A"
            if b_target.status_code == 200:
                assert b_target.json()["user_id"] == user_b
                assert str(_settings_snapshot(user_b).get("user_id")) == user_b
            b_after_attempt = _settings_snapshot(user_b)

            # 4. A submits user_id=B in the payload. The schema forbids extra fields, so this must
            # be a 422 and must leave both stored rows untouched.
            a_bad = client.put(
                "/finance/settings",
                headers=headers_a,
                json={
                    "opening_balance": 555555.55,
                    "monthly_budget": 66666.66,
                    "user_id": user_b,
                },
            )
            assert a_bad.status_code == 422, a_bad.status_code
            assert _settings_row_match(_settings_snapshot(user_a), snapshot_a), "A's rejected write changed A"
            assert _settings_values_match(_settings_snapshot(user_b), b_after_attempt), "A's rejected write changed B"

            # 5-7. Unauthenticated reads and writes are refused, including endpoints that share
            # the same CurrentUser dependency.
            assert client.get("/finance/settings").status_code == 401
            assert client.put(
                "/finance/settings",
                json={"opening_balance": 1, "monthly_budget": 1},
            ).status_code == 401
            month = date.today().strftime("%Y-%m")
            for path in (
                f"/finance/summary?month={month}",
                f"/commitments?month={month}",
                f"/transactions?month={month}",
            ):
                assert client.get(path).status_code == 401, path
            assert _settings_row_match(_settings_snapshot(user_a), snapshot_a), "anonymous access changed A"
            assert _settings_values_match(_settings_snapshot(user_b), b_after_attempt), "anonymous access changed B"
        finally:
            _restore_settings(client, headers_a, "A", user_a, snapshot_a, problems)
            _restore_settings(client, headers_b, "B", user_b, snapshot_b, problems)
        if problems:
            raise AssertionError("staging finance settings cleanup failed:\n" + "\n".join(problems))
