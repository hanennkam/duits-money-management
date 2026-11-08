"""Real two-account isolation checks against the guarded STAGING Supabase project.

These tests intentionally write only to two dedicated staging accounts. They restore finance settings
and delete every transaction/commitment they create, even when an assertion fails.
Never point the staging runner at production.
"""
from __future__ import annotations

import os
from datetime import date
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
            # Cleanup is owner-authenticated and does not touch pre-existing user data.
            if transaction_a_id:
                client.delete(f"/transactions/{transaction_a_id}", headers=headers_a)
            if transaction_b_id:
                client.delete(f"/transactions/{transaction_b_id}", headers=headers_b)
            if commitment_a_id:
                client.delete(f"/commitments/{commitment_a_id}", headers=headers_a)
            if commitment_b_id:
                client.delete(f"/commitments/{commitment_b_id}", headers=headers_b)

            restored = client.put(
                "/finance/settings",
                headers=headers_a,
                json={
                    "opening_balance": before_a["opening_balance"],
                    "monthly_budget": before_a["monthly_budget"],
                },
            )
            assert restored.status_code == 200, "Could not restore staging user A settings."
