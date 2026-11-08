"""Derived money figures: the balance, unpaid commitments, safe-to-spend and the remaining budget.

Pure functions over rows the API has already fetched. Nothing here talks to Supabase, which is what makes
the arithmetic testable on its own — and this arithmetic is the whole feature: every number on Home comes
out of this module.

Two rules the rest of the code depends on:

- **No abs(), no sign guessing.** `totals()` adds income and expense exactly as `db.summarize()` does, so
  the balance and the Home hero can never disagree about what a row means. A row stored with a negative
  amount pulls both figures the same way.
- **A paid commitment leaves the unpaid set; it is never also subtracted again.** The expense the user
  logged when paying is already in `total_expense`, so subtracting the commitment as well would take the
  money twice — that is what `commitment_payments` exists for. The budget bar handles the same expense
  the other way round: rows saved through the Pay flow carry `commitment_id`, and the bar leaves them
  out (`month_commitment_expense`), so a paid bill stops eating the budget the moment it is paid and the
  bills still due are `unpaid`'s job alone.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

# A month as the API takes it: YYYY-MM, and only a real month (2026-13 and 2026-00 are not months).
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# `day_of_month` is a due-date label, not a schedule: 1-31, and 31 in a 30-day month reads as "the 31st".
DAY_MIN, DAY_MAX = 1, 31


def valid_month(month: str) -> bool:
    """True for a YYYY-MM month that exists."""
    return bool(MONTH_RE.fullmatch(month or ""))


def valid_day_of_month(day: Any) -> bool:
    """True for a whole number in 1..31. A bool is not a day number, however Python feels about it."""
    return isinstance(day, int) and not isinstance(day, bool) and DAY_MIN <= day <= DAY_MAX


def money(value: Any) -> Decimal:
    """A numeric cell as an exact Decimal.

    NULL counts as zero: `sum(amount) filter (where type = 'income')` is NULL for a month with nothing
    coming in, which is an ordinary month, not an error.
    """
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def month_key(value: Any) -> str:
    """The YYYY-MM part of a month. The view returns a date ("2026-10-01"); the API takes "2026-10"."""
    return str(value)[:7]


def totals(rows: Iterable[Mapping[str, Any]], mode: str) -> tuple[Decimal, Decimal]:
    """All-time (income, expenses) for one mode over `public.transaction_totals` rows.

    The app is personal-only: the balance is one real-world number for the rows the user is shown, so a
    stored business row (kept in the database, hidden from the UI) no longer moves it. The figures are
    added, never abs()'d, which is exactly what db.summarize() does with one month of rows.
    """
    income = Decimal("0")
    expense = Decimal("0")
    for row in rows:
        if row.get("mode") != mode:
            continue
        income += money(row.get("total_income"))
        expense += money(row.get("total_expense"))
    return income, expense


def month_expense(rows: Iterable[Mapping[str, Any]], month: str, mode: str) -> Decimal:
    """One month's raw expenses for one mode: every expense row the month holds, Pay flow or not.

    This is the spend the balance's month behaves on and what the month cards read. The budget bar
    measures it less the Pay-flow slice (see `month_commitment_expense`), and is scoped to the mode the
    caller is looking at rather than to every row the account holds, exactly like this call.
    """
    return sum(
        (
            money(row.get("total_expense"))
            for row in rows
            if month_key(row.get("month")) == month and row.get("mode") == mode
        ),
        Decimal("0"),
    )


def month_commitment_expense(rows: Iterable[Mapping[str, Any]], month: str, mode: str) -> Decimal:
    """The slice of one month's expenses that came from the Pay flow, as the totals view labels them.

    The view sums expenses whose `commitment_id` is set into `commitment_expense` (migrations/0004); a
    null counts as zero, the same way an empty month's total is zero. `remaining_budget` subtracts this
    from `month_expense`, so a paid bill stops eating the budget — its money is already reflected where
    it belongs: the balance and `unpaid_commitments`, which drops by the same amount when the mark lands.
    """
    return sum(
        (
            money(row.get("commitment_expense"))
            for row in rows
            if month_key(row.get("month")) == month and row.get("mode") == mode
        ),
        Decimal("0"),
    )


def paid_commitment_ids(payments: Iterable[Mapping[str, Any]], *, month: str) -> set[str]:
    """The commitment ids marked paid for `month`.

    The month is filtered here rather than assumed by the caller, so a payment recorded for another month
    can never quietly mark this one paid.
    """
    return {
        str(payment.get("commitment_id"))
        for payment in payments
        if month_key(payment.get("month")) == month
    }


def unpaid_commitments(
    commitments: Iterable[Mapping[str, Any]],
    payments: Iterable[Mapping[str, Any]],
    *,
    month: str,
) -> Decimal:
    """Active commitments with no paid mark for `month`, as one sum.

    `active` is the only "not this month" mechanism: there is no per-month skip, so an inactive
    commitment is out of the sum entirely until it is switched back on.
    """
    paid = paid_commitment_ids(payments, month=month)
    return sum(
        (
            money(commitment.get("amount"))
            for commitment in commitments
            if commitment.get("active") and str(commitment.get("id")) not in paid
        ),
        Decimal("0"),
    )


def derive(
    *,
    opening_balance: Decimal,
    total_income: Decimal,
    total_expense: Decimal,
    month_expense: Decimal,
    month_commitment_expense: Decimal,
    unpaid: Decimal,
    monthly_budget: Decimal,
) -> dict[str, Decimal | None]:
    """Balance, safe-to-spend and remaining budget from the figures above.

    - `current_balance` = opening + income − expenses, over the asked mode and every month.
    - `safe_to_spend`   = balance − unpaid commitments: what is left after the bills still to come.
    - `remaining_budget`= budget − the month's spend **that is not a Pay expense**
      (`month_expense − month_commitment_expense`), and **None when no budget is set** (0 means
      "not set"), so the UI hides the line instead of showing a meaningless one. `unpaid` is
      deliberately NOT in it: the bills still due are already on the same card through `safe_to_spend`,
      and a bill the owner has not paid yet has not left the account, so subtracting it here would put
      the same amount on the card twice.

    Paying a commitment therefore cannot move the bar: `month_expense` rises by the amount the Pay
    expense adds and `month_commitment_expense` rises by the same amount, so the two cancel — and the
    balance drops by it while `unpaid` does too, which leaves `safe_to_spend` exactly where it was.
    """
    current_balance = opening_balance + total_income - total_expense
    safe_to_spend = current_balance - unpaid
    remaining_budget = (
        monthly_budget - (month_expense - month_commitment_expense)
        if monthly_budget > 0
        else None
    )
    return {
        "current_balance": current_balance,
        "safe_to_spend": safe_to_spend,
        "remaining_budget": remaining_budget,
    }
