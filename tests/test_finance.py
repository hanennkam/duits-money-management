"""The derived money arithmetic: balance, unpaid commitments, safe-to-spend, remaining budget.

`app/finance.py` is pure, so these tests need no Supabase, no token and no network. The point of the suite
is the rule the feature exists for: paying a commitment must never take the money twice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app import db, finance

USER = "5b1f2e8a-0c3d-4e5f-8a9b-1c2d3e4f5a6b"


def view_row(
    month: str, mode: str, *, income: Any = None, expense: Any = None, commitment: Any = None
) -> dict[str, Any]:
    """One `public.transaction_totals` row. `month` is a date there, not a YYYY-MM string."""
    return {
        "user_id": USER,
        "mode": mode,
        "month": f"{month}-01",
        "total_income": income,
        "total_expense": expense,
        "commitment_expense": commitment,
        "row_count": 1,
    }


def commitment(
    commitment_id: str, amount: Any, *, day: int = 1, active: bool = True, name: str = "Sewa rumah"
) -> dict[str, Any]:
    return {
        "id": commitment_id,
        "user_id": USER,
        "name": name,
        "amount": amount,
        "day_of_month": day,
        "active": active,
    }


def payment(commitment_id: str, month: str) -> dict[str, Any]:
    return {
        "id": f"pay-{commitment_id}-{month}",
        "user_id": USER,
        "commitment_id": commitment_id,
        "month": f"{month}-01",
        "paid_at": "2026-10-05T09:00:00+00:00",
    }


# ---------------------------------------------------------------- the double-count rule

def test_paying_a_commitment_does_not_change_the_money_twice() -> None:
    """The worked example: budget 2000, commitment 300, other spend 200. Before and after must match.

    The bar leaves the Pay expense out by its link (0004), and `unpaid` is not in the bar at all.
    Before paying: month spend 200, no Pay expense in it -> remaining 2000 - 200 = 1800. After paying:
    the 300 expense joins the month (spend 500) but carries commitment_expense 300 -> remaining
    2000 - (500 - 300) = 1800. The balance drops by 300 while `unpaid` drops by 300, so safe-to-spend
    does not move either — and the bar itself never jumps, because the two figures it subtracts move
    by the same amount.
    """
    commitments = [commitment("c1", "300.00")]
    budget = Decimal("2000.00")
    opening, income = Decimal("1000.00"), Decimal("1200.00")

    before_expense, before_unpaid = Decimal("200.00"), finance.unpaid_commitments(
        commitments, [], month="2026-10"
    )
    before = finance.derive(
        opening_balance=opening,
        total_income=income,
        total_expense=before_expense,
        month_expense=before_expense,
        month_commitment_expense=Decimal("0.00"),
        unpaid=before_unpaid,
        monthly_budget=budget,
    )

    after_expense = Decimal("500.00")  # the 200 plus the paid commitment
    after_unpaid = finance.unpaid_commitments(
        commitments, [payment("c1", "2026-10")], month="2026-10"
    )
    after = finance.derive(
        opening_balance=opening,
        total_income=income,
        total_expense=after_expense,
        month_expense=after_expense,
        month_commitment_expense=Decimal("300.00"),  # the same expense, labelled by its Pay link
        unpaid=after_unpaid,
        monthly_budget=budget,
    )

    assert before_unpaid == Decimal("300.00") and after_unpaid == Decimal("0")
    assert before["remaining_budget"] == after["remaining_budget"] == Decimal("1800.00")
    assert before["safe_to_spend"] == after["safe_to_spend"] == Decimal("1700.00")


def test_the_budget_bar_ignores_bills_that_have_not_been_paid_yet() -> None:
    """`unpaid` never enters the remaining budget: the bar is money that has actually left the account.

    Budget 2000, month spend 800, one unpaid bill of 300: the bar still reads 1200 left, because that
    spend may never happen. Safe to spend is the figure that carries the bill.
    """
    figures = finance.derive(
        opening_balance=Decimal("1000.00"),
        total_income=Decimal("1600.00"),
        total_expense=Decimal("800.00"),
        month_expense=Decimal("800.00"),
        month_commitment_expense=Decimal("0.00"),
        unpaid=Decimal("300.00"),
        monthly_budget=Decimal("2000.00"),
    )

    assert figures["remaining_budget"] == Decimal("1200.00")
    assert figures["safe_to_spend"] == Decimal("1500.00")


def test_month_commitment_expense_is_scoped_like_the_month_spend() -> None:
    """The Pay-flow slice answers for its own month and mode, and NULL counts as zero, never an error."""
    rows = [
        view_row("2026-10", "personal", expense="500.00", commitment="300.00"),
        view_row("2026-09", "personal", expense="80.00", commitment="80.00"),
        view_row("2026-10", "business", expense="40.00", commitment="40.00"),
        view_row("2026-10", "business", expense="10.00", commitment=None),
    ]

    assert finance.month_commitment_expense(rows, "2026-10", "personal") == Decimal("300.00")
    assert finance.month_commitment_expense(rows, "2026-09", "personal") == Decimal("80.00")
    assert finance.month_commitment_expense(rows, "2026-10", "business") == Decimal("40.00")
    assert finance.month_commitment_expense(rows, "2026-10", "personal") != finance.month_expense(
        rows, "2026-10", "personal"
    )


def test_a_payment_recorded_for_another_month_does_not_mark_this_one_paid() -> None:
    """September's payment must not take October's commitment out of the sum."""
    commitments = [commitment("c1", "300.00")]
    payments = [payment("c1", "2026-09")]

    assert finance.unpaid_commitments(commitments, payments, month="2026-10") == Decimal("300.00")
    assert finance.unpaid_commitments(commitments, payments, month="2026-09") == Decimal("0")


def test_paid_commitment_ids_are_scoped_to_the_month() -> None:
    payments = [payment("c1", "2026-10"), payment("c2", "2026-09")]

    assert finance.paid_commitment_ids(payments, month="2026-10") == {"c1"}
    assert finance.paid_commitment_ids(payments, month="2026-09") == {"c2"}
    assert finance.paid_commitment_ids(payments, month="2026-11") == set()


# ---------------------------------------------------------------- who counts as unpaid

def test_inactive_commitments_are_out_of_the_sum() -> None:
    """`active` is the only "not this month" mechanism, so a switched-off commitment never counts."""
    commitments = [
        commitment("c1", "300.00"),
        commitment("c2", "120.50", active=False),
    ]

    assert finance.unpaid_commitments(commitments, [], month="2026-10") == Decimal("300.00")


def test_two_payments_for_the_same_month_do_not_subtract_twice() -> None:
    """One paid mark is enough: a duplicate row (a retried request) cannot take the money twice."""
    commitments = [commitment("c1", "300.00")]

    assert finance.unpaid_commitments(
        commitments, [payment("c1", "2026-10"), payment("c1", "2026-10")], month="2026-10"
    ) == Decimal("0")


def test_unpaid_commitments_are_added_exactly() -> None:
    """Decimals, not floats: 0.10 + 0.20 is 0.30 to the cent."""
    commitments = [commitment("c1", "0.10"), commitment("c2", "0.20")]

    total = finance.unpaid_commitments(commitments, [], month="2026-10")

    assert total == Decimal("0.30")
    assert isinstance(total, Decimal)


# ---------------------------------------------------------------- safe-to-spend, budget

def test_safe_to_spend_goes_negative_when_the_bills_exceed_the_balance() -> None:
    """Negative is a real answer: it means the bills still due are bigger than the balance."""
    figures = finance.derive(
        opening_balance=Decimal("0.00"),
        total_income=Decimal("0.00"),
        total_expense=Decimal("100.00"),
        month_expense=Decimal("100.00"),
        month_commitment_expense=Decimal("0.00"),
        unpaid=Decimal("250.00"),
        monthly_budget=Decimal("500.00"),
    )

    assert figures["current_balance"] == Decimal("-100.00")
    assert figures["safe_to_spend"] == Decimal("-350.00")


def test_no_budget_means_no_remaining_budget() -> None:
    """0 means "no budget set", so the figure is None and the UI has nothing to show."""
    common = {
        "opening_balance": Decimal("100.00"),
        "total_income": Decimal("0.00"),
        "total_expense": Decimal("20.00"),
        "month_expense": Decimal("20.00"),
        "month_commitment_expense": Decimal("0.00"),
        "unpaid": Decimal("0.00"),
    }

    assert finance.derive(**common, monthly_budget=Decimal("0"))["remaining_budget"] is None
    assert finance.derive(**common, monthly_budget=Decimal("300"))["remaining_budget"] == Decimal("280.00")


def test_the_balance_and_the_budget_are_both_scoped_to_the_asked_mode() -> None:
    """One balance and one budget spend per mode: business rows stay stored but out of personal."""
    rows = [
        view_row("2026-10", "personal", income="0", expense="200.00"),
        view_row("2026-10", "business", income="0", expense="50.00"),
        view_row("2026-09", "personal", income="1000.00", expense="0"),
    ]

    assert finance.totals(rows, "personal") == (Decimal("1000.00"), Decimal("200.00"))
    assert finance.totals(rows, "business") == (Decimal("0"), Decimal("50.00"))
    assert finance.month_expense(rows, "2026-10", "personal") == Decimal("200.00")
    assert finance.month_expense(rows, "2026-10", "business") == Decimal("50.00")
    assert finance.month_expense(rows, "2026-09", "personal") == Decimal("0")


# ---------------------------------------------------------------- sign convention, NULLs

def test_a_month_with_no_income_counts_as_zero_not_an_error() -> None:
    """`sum(amount) filter (where type = 'income')` is NULL for an ordinary no-income month."""
    rows = [view_row("2026-10", "personal", income=None, expense="42.00")]

    assert finance.money(None) == Decimal("0")
    assert finance.totals(rows, "personal") == (Decimal("0"), Decimal("42.00"))


def test_the_balance_keeps_summarize_s_sign_convention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A negative stored amount moves finance and db.summarize() the same way, so the two agree.

    `db.summarize()` adds the row's amount to `total_expense` without an abs(), so a stored -50 pulls the
    expense total down. The balance subtracts that same figure, so it must rise by 50. Neither routine is
    allowed to "fix" the sign on its own — the two Home figures would then contradict each other.
    """
    rows = [
        {"amount": -50.0, "type": "expense", "category": "food"},
        {"amount": 100.0, "type": "expense", "category": "food"},
        {"amount": 200.0, "type": "income", "category": "other"},
    ]
    monkeypatch.setattr("app.db.list_transactions", lambda *a, **kw: rows)
    summarised = db.summarize(date(2026, 10, 1), date(2026, 11, 1), "personal", user_id=USER)

    assert summarised["total_expense"] == Decimal("50")
    assert summarised["total_income"] == Decimal("200")

    view = [view_row("2026-10", "personal", income="200", expense="50")]
    income, expense = finance.totals(view, "personal")
    assert (income, expense) == (summarised["total_income"], summarised["total_expense"])
    assert finance.month_expense(view, "2026-10", "personal") == summarised["total_expense"]

    figures = finance.derive(
        opening_balance=Decimal("0"),
        total_income=income,
        total_expense=expense,
        month_expense=expense,
        month_commitment_expense=Decimal("0"),
        unpaid=Decimal("0"),
        monthly_budget=Decimal("0"),
    )
    assert figures["current_balance"] == Decimal("150")  # 200 in, 50 out — not 350


def test_month_key_takes_a_date_or_a_month() -> None:
    """The view answers with a date; the API takes YYYY-MM. Both must land on the same key."""
    assert finance.month_key("2026-10-01") == "2026-10"
    assert finance.month_key("2026-10") == "2026-10"
    assert finance.month_key(date(2026, 10, 1)) == "2026-10"


# ---------------------------------------------------------------- month and day validation

@pytest.mark.parametrize("month", ["2026-01", "2026-10", "2026-12", "1999-07"])
def test_a_real_yyyy_mm_month_is_valid(month: str) -> None:
    assert finance.valid_month(month)


@pytest.mark.parametrize(
    "month", ["", "2026", "2026-13", "2026-00", "2026-1", "26-10", "2026-10-01", "2026/10", "abcd-ef"]
)
def test_anything_else_is_not_a_month(month: str) -> None:
    assert not finance.valid_month(month)


@pytest.mark.parametrize("day", [1, 15, 31])
def test_day_of_month_1_to_31_is_valid(day: int) -> None:
    assert finance.valid_day_of_month(day)


@pytest.mark.parametrize("day", [0, 32, -1, 1.5, "5", None, True])
def test_day_of_month_outside_1_to_31_is_not(day: Any) -> None:
    """0 and 32 are the off-by-one cases; a bool, a string and a fraction are not days either."""
    assert not finance.valid_day_of_month(day)
