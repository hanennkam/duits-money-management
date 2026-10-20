"""Duits expense tracker — Phase 1 API.

One job per endpoint: take a receipt image or a text note, extract a transaction
with Claude, store it in Supabase. Built to be called from Apple Shortcuts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app import db, extractor, finance
from app.auth import CurrentUser
from app.config import Settings, get_settings, is_production
from app.models import (
    Commitment,
    CommitmentCreate,
    CommitmentPayment,
    CommitmentUpdate,
    Extraction,
    FinanceSettings,
    FinanceSettingsUpdate,
    FinanceSummary,
    Mode,
    ReceiptUrl,
    Source,
    Summary,
    TextTransactionRequest,
    Transaction,
    TransactionCreate,
    TransactionUpdate,
)

logger = logging.getLogger(__name__)

# Receipt images Claude accepts. HEIC is out of scope: have Shortcuts convert first.
IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

STATIC_DIR = Path(__file__).parent / "static"

# Receipt links are handed out just long enough to load the image.
RECEIPT_URL_TTL = 60

# ENVIRONMENT=production turns the interactive API docs off.
IS_PRODUCTION = is_production()

# API responses that must never be cached by a proxy, browser or CDN. `/health` is here so a
# keep-alive probe always reaches Render instead of being answered from a cache.
NO_STORE_PREFIXES = ("/health", "/transactions", "/summary", "/finance", "/commitments")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail fast: a container with missing configuration must not start serving."""
    settings = get_settings()  # raises with the missing NAME(s), never the values
    if not settings.supabase_publishable_key:
        logger.warning(
            "SUPABASE_PUBLISHABLE_KEY is not set: the web UI cannot sign in "
            "(the API and the Apple Shortcut are unaffected)."
        )
    logger.info(
        "Duits starting: environment=%s, model=%s, bucket=%s",
        "production" if IS_PRODUCTION else "development",
        settings.claude_model,
        settings.receipts_bucket,
    )
    yield


app = FastAPI(
    title="Duits Expense Tracker",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """No caching for API data, plus the usual hardening headers on every response."""
    response = await call_next(request)
    if request.url.path.startswith(NO_STORE_PREFIXES):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response



@app.exception_handler(extractor.ExtractionError)
async def extraction_error_handler(_request: Request, exc: extractor.ExtractionError) -> JSONResponse:
    """Claude could not produce a usable transaction."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )


@app.exception_handler(extractor.UpstreamError)
async def upstream_error_handler(_request: Request, exc: extractor.UpstreamError) -> JSONResponse:
    """Anthropic API failure."""
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": f"Claude API error: {exc}"}
    )


BUILD_PLACEHOLDER = "{{BUILD}}"
AUTH_PLACEHOLDER = "{{AUTH_CONFIG}}"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def build_stamp() -> str:
    """The Build row's text: the short commit Render deployed, or "dev" when it is not running on Render.

    RENDER_GIT_COMMIT is the full SHA, set by Render at runtime. Anything that is not a full SHA is dropped
    rather than written into the page.
    """
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip().lower()
    short = commit[:7] if COMMIT_SHA.fullmatch(commit) else "dev"
    return f"{short} · fullscreen"


def auth_config(settings: Settings) -> str:
    """The page's sign-in settings as a JSON object, ready to paste into one script.

    Only the project URL and the publishable key. The service key is server-side only and never reaches
    the page. ``<`` is escaped so a hostile value cannot close the script tag.
    """
    payload = {"url": settings.supabase_url.rstrip("/"), "key": settings.supabase_publishable_key}
    return json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")


def content_security_policy(nonce: str, settings: Settings) -> str:
    """A strict policy for a single-file page with no third-party code.

    What it has to allow, and why:
    - ``script-src 'self' 'nonce-…'``: the page's two inline <script> blocks carry the nonce. There is no
      ``'unsafe-inline'``, so an injected <script> or event handler cannot run.
    - ``style-src 'self' 'unsafe-inline'``: two inline <style> blocks, and twelve ``style="…"``
      attributes written by the page's own templates (category colours, row stagger, bar heights). Those
      values are escaped or drawn from constant colour maps. This is the one real loosening.
    - ``img-src 'self' blob: <project>``: local icons, the in-memory ``blob:`` preview built while a photo
      is downscaled, and the receipt photos Supabase signs (there are no ``data:`` URIs in the page).
    - ``connect-src 'self' <project>``: the API is same-origin; Supabase Auth is called over the project URL.
    """
    project = settings.supabase_url.rstrip("/")
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}'",
            "style-src 'self' 'unsafe-inline'",
            f"img-src 'self' blob: {project}",
            f"connect-src 'self' {project}",
            "font-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


@app.get("/", include_in_schema=False)
async def index(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    """The mobile-first UI. Public, but every API call it makes needs a Bearer token.

    ``no-store``: the page is never written to a cache at all. It carries the icon links and all of the
    CSS and JS inline, so a stale copy is a page with the wrong behaviour — and a Home Screen shortcut
    is exactly where one would survive. Freshness wins over the cost of re-sending the page.

    Three values are filled in per request: the Build stamp, the sign-in settings, and a fresh CSP nonce
    (the nonce is per response, so the page and its policy always agree).
    """
    nonce = secrets.token_urlsafe(18)
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    page = page.replace(BUILD_PLACEHOLDER, build_stamp())
    page = page.replace(AUTH_PLACEHOLDER, auth_config(settings))
    page = page.replace("<script>", f'<script nonce="{nonce}">').replace(
        "<style>", f'<style nonce="{nonce}">'
    )
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": content_security_policy(nonce, settings),
        },
    )


# The app icon: iOS probes apple-touch-icon(-120x120|-152x152).png by name, and Safari wants a plain
# favicon, so the same artwork is served at each size those slots ask for. All four are opaque — iOS
# paints transparency black — with square corners, because iOS applies its own rounded mask.
# Public like the page itself; the middleware still adds nosniff and Referrer-Policy.
#
# Deliberately cacheable but *not* immutable: the ?v= query in <head> is what busts iOS's Home Screen
# icon cache (iOS keys it on the URL), and this short max-age lets a re-saved icon heal by itself.
ICON_MAX_AGE = "public, max-age=600"


def _icon(filename: str) -> FileResponse:
    """An icon from app/static, publicly cacheable for a few minutes."""
    return FileResponse(
        STATIC_DIR / filename, media_type="image/png", headers={"Cache-Control": ICON_MAX_AGE}
    )


@app.get("/logo.png", include_in_schema=False)
async def logo() -> FileResponse:
    """The app icon, used as the favicon."""
    return _icon("logo.png")


@app.get("/apple-touch-icon.png", include_in_schema=False)
async def apple_touch_icon() -> FileResponse:
    """What iOS asks for first when the page is saved to the Home Screen (180x180)."""
    return _icon("apple-touch-icon.png")


@app.get("/apple-touch-icon-120x120.png", include_in_schema=False)
async def apple_touch_icon_120() -> FileResponse:
    """The 120x120 slot iOS probes for the Home Screen."""
    return _icon("apple-touch-icon-120x120.png")


@app.get("/apple-touch-icon-152x152.png", include_in_schema=False)
async def apple_touch_icon_152() -> FileResponse:
    """The 152x152 slot iOS probes for the Home Screen."""
    return _icon("apple-touch-icon-152x152.png")


@app.get("/health")
@app.head("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Liveness probe: no database, no auth, no Supabase, so a monitor can poll it often and cheaply.

    HEAD is answered as well as GET because UptimeRobot's free plan polls with HEAD by default. The
    middleware's ``no-store`` keeps each probe out of any cache, so a keep-alive really reaches Render.
    """
    return {"status": "ok"}


@app.post(
    "/transactions/scan",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
)
async def scan_receipt(
    user_id: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(description="Receipt image: jpg, png or webp")],
    mode: Annotated[Mode, Form()] = "personal",
) -> Transaction:
    """Upload a receipt image, extract it with Claude, save the transaction for the caller."""
    media_type = (file.content_type or "").lower()
    if media_type not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type {media_type or 'unknown'!r}; use jpg, png or webp.",
        )

    image = await file.read(settings.max_upload_bytes + 1)
    if not image:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty upload.")
    if len(image) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File is larger than the {limit_mb} MB limit."
        )

    # Same bytes = same photo, so bail out before spending Storage space or a Claude call.
    image_hash = hashlib.sha256(image).hexdigest()
    scanned = db.find_by_image_hash(image_hash, user_id=user_id)
    if scanned is not None:
        raise _duplicate(scanned, "Already recorded.")

    # Claude first: an unreadable image must never leave a file in Storage.
    extraction = extractor.extract_from_image(image, media_type)

    # A screenshot of a bank or e-wallet screen is evidence of a transaction, not a document worth
    # keeping: we store what it said and drop the image. Only a photo of paper goes to Storage.
    source: Source = (
        "bank_screenshot" if extraction.document_kind == "bank_screenshot" else "receipt_scan"
    )
    receipt_path = None
    if source == "receipt_scan":
        # The owner's folder comes first: user_id/YYYY/MM/<uuid>.ext
        receipt_path = (
            f"{user_id}/{date.today():%Y/%m}/{uuid.uuid4().hex}{IMAGE_EXTENSIONS[media_type]}"
        )
        try:
            db.upload_receipt(receipt_path, image, media_type, user_id=user_id)
        except Exception as exc:  # any storage failure is an upstream problem, not a client error
            logger.exception("Receipt upload to Supabase Storage failed")
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Receipt upload failed: {exc}"
            ) from exc

    try:
        return _save(
            extraction,
            mode=mode,
            source=source,
            receipt_path=receipt_path,
            image_hash=image_hash,
            user_id=user_id,
        )
    except Exception:
        if receipt_path:  # a rejected duplicate or a failed insert leaves no orphan
            db.delete_receipt(receipt_path, user_id=user_id)
        raise


@app.post(
    "/transactions/text",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_text(payload: TextTransactionRequest, user_id: CurrentUser) -> Transaction:
    """Extract a transaction from a short text note, e.g. "makan tengah hari 12 ringgit"."""
    return _save(
        extractor.extract_from_text(payload.text), mode=payload.mode, source="text", user_id=user_id
    )


@app.post(
    "/transactions",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction(payload: TransactionCreate, user_id: CurrentUser) -> Transaction:
    """Save one transaction typed in by hand: no receipt, no Claude, no dedupe by default.

    `commitment_id` ties the row to the Pay flow's commitment (0004): it must be a commitment of the
    caller's — another owner's id is a 404, so a cross-owner link cannot be made — and it is data rather
    than a foreign key on purpose, so deleting a commitment never takes an expense (or a balance) with it.

    A Pay expense is a manual row, and a manual row is never deduped (a typed entry is deliberate), so
    the Pay flow gets its own guard: one bill, one expense, one month. Paying is two writes — the
    expense and the paid mark — and the mark is idempotent, but the expense in front of it was not: a
    Pay whose mark failed, retried, charged the same bill twice. The second attempt now answers 409
    with the row that is already there, and the UI carries on to mark the bill paid.
    """
    if payload.commitment_id is not None:
        if db.get_commitment(str(payload.commitment_id), user_id=user_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No commitment with that id.")
        # The month is the transaction's own, so a bill paid in a different month is a different bill.
        month = f"{payload.txn_date.year:04d}-{payload.txn_date.month:02d}"
        existing = db.find_pay_expense(
            str(payload.commitment_id), month, user_id=user_id
        )
        if existing is not None:
            raise _duplicate(existing, "Already recorded.")
    return _insert(payload.to_row(), user_id=user_id)


@app.get("/transactions", response_model=list[Transaction])
async def list_transactions(
    user_id: CurrentUser,
    month: Annotated[str, Query(description="Month to list, as YYYY-MM")],
    mode: Mode = "personal",
) -> list[Transaction]:
    """The caller's transactions in that month for that mode, newest first."""
    start, end = _month_bounds(month)
    return [
        Transaction.model_validate(row)
        for row in db.list_transactions(start, end, mode, user_id=user_id)
    ]


@app.get("/transactions/{transaction_id}", response_model=Transaction)
async def get_transaction(transaction_id: UUID, user_id: CurrentUser) -> Transaction:
    """One of the caller's transactions. Another user's id answers 404."""
    return Transaction.model_validate(_existing(transaction_id, user_id))


@app.patch("/transactions/{transaction_id}", response_model=Transaction)
async def update_transaction(
    transaction_id: UUID, payload: TransactionUpdate, user_id: CurrentUser
) -> Transaction:
    """Correct one of the caller's transactions by hand. A manual edit clears the needs-review flag."""
    row = _existing(transaction_id, user_id)
    patch = payload.changes()
    if not patch:
        return Transaction.model_validate(row)

    patch["raw_extraction"] = {**(row.get("raw_extraction") or {}), "needs_review": False}
    # The dedupe hash mirrors (txn_date, amount, merchant), so it has to follow edits.
    merged = {**row, **patch}
    patch["dedupe_hash"] = db.dedupe_hash(
        row.get("source") or "manual",
        date.fromisoformat(str(merged["txn_date"])),
        Decimal(str(merged["amount"])),
        merged.get("merchant"),
    )

    updated = db.update_transaction(str(transaction_id), patch, user_id=user_id)
    return Transaction.model_validate(updated or _existing(transaction_id, user_id))


@app.delete(
    "/transactions/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_transaction(transaction_id: UUID, user_id: CurrentUser) -> None:
    """Delete one of the caller's rows, and its receipt object if it has one."""
    row = _existing(transaction_id, user_id)
    receipt_path = db.owned_receipt_path(row.get("receipt_path"), user_id=user_id)
    if receipt_path:
        db.delete_receipt(receipt_path, user_id=user_id)
    elif row.get("receipt_path"):
        # The object sits outside this owner's folder, so it is not ours to remove. Leave it alone and say
        # so, but never let it block deleting the row.
        logger.warning("Leaving a receipt object in place: its path is outside the owner's folder")
    db.delete_transaction(str(transaction_id), user_id=user_id)


@app.get("/transactions/{transaction_id}/receipt-url", response_model=ReceiptUrl)
async def receipt_url(transaction_id: UUID, user_id: CurrentUser) -> ReceiptUrl:
    """Short-lived signed URL for one of the caller's private receipt images."""
    row = _existing(transaction_id, user_id)
    # A path outside the owner's folder is a migration leftover, not a receipt they can reach: it answers
    # exactly like a row with no photo rather than a 500.
    receipt_path = db.owned_receipt_path(row.get("receipt_path"), user_id=user_id)
    if not receipt_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This transaction has no receipt image.")
    url = db.create_receipt_url(receipt_path, RECEIPT_URL_TTL, user_id=user_id)
    return ReceiptUrl(url=url, expires_in=RECEIPT_URL_TTL)


@app.get("/summary", response_model=Summary)
async def summary(
    user_id: CurrentUser,
    month: Annotated[str, Query(description="Month to summarise, as YYYY-MM")],
    mode: Mode = "personal",
) -> Summary:
    """Total expense, total income and total per category for the caller in that month."""
    start, end = _month_bounds(month)
    return Summary.model_validate(
        db.summarize(start, end, mode, user_id=user_id) | {"month": month, "mode": mode}
    )


def _existing(transaction_id: UUID, user_id: UUID) -> dict[str, Any]:
    """The caller's row, or 404. Another owner's row is indistinguishable from a missing one."""
    row = db.get_transaction(str(transaction_id), user_id=user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No transaction with that id.")
    return row


# ---------------------------------------------------------------- money settings and commitments


@app.get("/finance/summary", response_model=FinanceSummary)
async def finance_summary(
    user_id: CurrentUser,
    month: Annotated[str, Query(description="Month to read, as YYYY-MM")],
    mode: Mode = "personal",
) -> FinanceSummary:
    """Balance, unpaid commitments, safe-to-spend and the remaining budget.

    Scope, stated because one figure does not match the others: `total_income`, `total_expense` and
    `current_balance` are all-time and take **every mode** into account — the balance is one real-world
    number. `unpaid_commitments`, the month's spend and `remaining_budget` are scoped to `mode`, the same
    rows Home is showing. `remaining_budget` is null when no budget is set (0), and it leaves the month's
    Pay-linked expenses out — a bill the month has already paid stops eating the budget, and the bills
    that are still due are what `unpaid_commitments` is for.

    Every figure is derived here; none of it is stored, so it cannot drift from the transactions.
    """
    checked = _month(month)
    settings_row = db.get_finance_settings(user_id=user_id) or {}
    opening = finance.money(settings_row.get("opening_balance"))
    budget = finance.money(settings_row.get("monthly_budget"))

    totals_rows = db.transaction_totals(user_id=user_id)
    income, expense = finance.totals(totals_rows)
    month_spend = finance.month_expense(totals_rows, checked, mode)
    month_commitment_spend = finance.month_commitment_expense(totals_rows, checked, mode)

    unpaid = finance.unpaid_commitments(
        db.list_commitments(user_id=user_id),
        db.list_commitment_payments(checked, user_id=user_id),
        month=checked,
    )

    return FinanceSummary(
        month=checked,
        mode=mode,
        opening_balance=opening,
        monthly_budget=budget,
        total_income=income,
        total_expense=expense,
        unpaid_commitments=unpaid,
        **finance.derive(
            opening_balance=opening,
            total_income=income,
            total_expense=expense,
            month_expense=month_spend,
            month_commitment_expense=month_commitment_spend,
            unpaid=unpaid,
            monthly_budget=budget,
        ),
    )


@app.get("/finance/settings", response_model=FinanceSettings)
async def get_finance_settings(user_id: CurrentUser) -> FinanceSettings:
    """The caller's opening balance and monthly budget, with the defaults when nothing is saved yet."""
    return _finance_settings(db.get_finance_settings(user_id=user_id), user_id)


@app.put("/finance/settings", response_model=FinanceSettings)
async def update_finance_settings(
    payload: FinanceSettingsUpdate, user_id: CurrentUser
) -> FinanceSettings:
    """Set the opening balance and/or the monthly budget. An omitted field keeps the value it had.

    `opening_balance` may be negative (an overdraft is a real balance); `monthly_budget` may not, and 0
    means "no budget", which is what makes `remaining_budget` come back as null rather than as a figure.
    """
    patch = payload.changes()
    if not patch:
        return _finance_settings(db.get_finance_settings(user_id=user_id), user_id)
    return FinanceSettings.model_validate(db.upsert_finance_settings(patch, user_id=user_id))


@app.get("/commitments", response_model=list[Commitment])
async def list_commitments(
    user_id: CurrentUser,
    month: Annotated[str, Query(description="Month whose paid marks to report, as YYYY-MM")],
) -> list[Commitment]:
    """The caller's commitments, active and inactive, each with `paid` for that month.

    `paid` is per month because a payment mark is per month: the same commitment is paid for October and
    unpaid for November. Inactive commitments are still listed, so Settings can switch one back on; they
    are simply left out of the unpaid total.
    """
    checked = _month(month)
    paid = finance.paid_commitment_ids(
        db.list_commitment_payments(checked, user_id=user_id), month=checked
    )
    return [
        Commitment.model_validate({**row, "paid": str(row["id"]) in paid})
        for row in db.list_commitments(user_id=user_id)
    ]


@app.post("/commitments", response_model=Commitment, status_code=status.HTTP_201_CREATED)
async def create_commitment(payload: CommitmentCreate, user_id: CurrentUser) -> Commitment:
    """Add one monthly commitment for the caller. A brand-new commitment is unpaid in every month."""
    row = db.insert_commitment(payload.to_row(), user_id=user_id)
    return Commitment.model_validate({**row, "paid": False})


@app.patch("/commitments/{commitment_id}", response_model=Commitment)
async def update_commitment(
    commitment_id: UUID,
    payload: CommitmentUpdate,
    user_id: CurrentUser,
    month: Annotated[
        str | None, Query(description="Month whose paid mark to echo back, as YYYY-MM")
    ] = None,
) -> Commitment:
    """Correct one of the caller's commitments. Another owner's id answers 404.

    `?month=` is optional and only decides what `paid` reports: without it `paid` is null, because a
    commitment has no single paid state — the mark belongs to a month.
    """
    row = db.get_commitment(str(commitment_id), user_id=user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No commitment with that id.")

    patch = payload.changes()
    updated = db.update_commitment(str(commitment_id), patch, user_id=user_id) if patch else row
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No commitment with that id.")

    paid: bool | None = None
    if month is not None:
        checked = _month(month)
        paid = str(commitment_id) in finance.paid_commitment_ids(
            db.list_commitment_payments(checked, user_id=user_id), month=checked
        )
    return Commitment.model_validate({**updated, "paid": paid})


@app.delete(
    "/commitments/{commitment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_commitment(commitment_id: UUID, user_id: CurrentUser) -> None:
    """Delete one of the caller's commitments, and its paid marks with it."""
    if not db.delete_commitment(str(commitment_id), user_id=user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No commitment with that id.")


@app.post("/commitments/{commitment_id}/paid", response_model=Commitment)
async def mark_commitment_paid(
    commitment_id: UUID, payload: CommitmentPayment, user_id: CurrentUser
) -> Commitment:
    """Mark a commitment paid for one month, so it stops counting as still due.

    Idempotent: marking the same month twice answers 200 with the same state, so a retried tap cannot
    double-subtract. The month is the one to mark, which is not always the month the transaction lands
    in — a bill paid on the 3rd for last month is marked for last month on purpose.
    """
    row = db.get_commitment(str(commitment_id), user_id=user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No commitment with that id.")
    db.mark_commitment_paid(str(commitment_id), payload.month, user_id=user_id)
    return Commitment.model_validate({**row, "paid": True})


@app.delete(
    "/commitments/{commitment_id}/paid",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def unmark_commitment_paid(
    commitment_id: UUID,
    user_id: CurrentUser,
    month: Annotated[str, Query(description="Month to unmark, as YYYY-MM")],
) -> None:
    """Remove the paid mark for one month: the undo for a mistaken tap. Idempotent."""
    checked = _month(month)
    if db.get_commitment(str(commitment_id), user_id=user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No commitment with that id.")
    db.unmark_commitment_paid(str(commitment_id), checked, user_id=user_id)


def _finance_settings(row: dict[str, Any] | None, user_id: UUID) -> FinanceSettings:
    """The caller's settings, or the defaults when they have never saved a row.

    The defaults live here rather than as an inserted row: a user who never opens Settings has no row,
    and that must read as "RM 0.00, no budget", not as an error or a 404.
    """
    if row is None:
        return FinanceSettings(
            user_id=str(user_id),
            opening_balance=Decimal("0"),
            monthly_budget=Decimal("0"),
            currency="MYR",
        )
    return FinanceSettings.model_validate(row)


def _month(month: str) -> str:
    """Validate YYYY-MM with the same rule (and the same 400) `/summary` uses, then hand it back."""
    _month_bounds(month)
    return month


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        return db.month_bounds(month)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _save(
    extraction: Extraction,
    *,
    mode: Mode,
    source: Source,
    user_id: UUID,
    receipt_path: str | None = None,
    image_hash: str | None = None,
) -> Transaction:
    """Turn an extraction into a row and store it, with every key a duplicate lookup should probe."""
    row = extraction.to_row(
        mode=mode, source=source, receipt_path=receipt_path, image_hash=image_hash
    )
    assert extraction.amount is not None  # to_row rejects an amount-less extraction
    return _insert(
        row,
        db.dedupe_hashes(
            source,
            extraction.txn_date,
            extraction.amount,
            extraction.merchant,
            reference=extraction.reference,
            txn_time=extraction.txn_time,
        ),
        user_id=user_id,
    )


def _insert(
    row: dict[str, Any], dedupe_keys: list[str] | None = None, *, user_id: UUID
) -> Transaction:
    """Insert a row for the caller, or answer 409 with the caller's row that already exists.

    Duplicate lookups are scoped to the owner, so the 409 body can only ever carry the caller's own row.
    Rows with no dedupe hash (text notes, hand-typed rows, merchant-less scans) always insert, so only
    scans can come back as duplicates. A bank screenshot without a reference number also probes the
    ten-minute windows either side of its own, which is what makes "within ten minutes" work when the
    two scans fall on opposite sides of a window boundary.
    """
    dedupe = row["dedupe_hash"]
    existing = db.find_by_dedupe_hash(dedupe, user_id=user_id) if dedupe else None
    if existing is None and dedupe_keys and len(dedupe_keys) > 1:
        existing = db.find_by_dedupe_hashes(dedupe_keys[1:], user_id=user_id)
    if existing is not None:
        raise _duplicate(existing, "Already recorded.")
    return Transaction.model_validate(db.insert_transaction(row, user_id=user_id))


def _duplicate(existing: dict[str, Any], message: str) -> HTTPException:
    """409 carrying the row that already exists, so the Shortcut can show it."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"error": "duplicate", "message": message, "transaction": existing},
    )
