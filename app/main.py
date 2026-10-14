"""Duits expense tracker — Phase 1 API.

One job per endpoint: take a receipt image or a text note, extract a transaction
with Claude, store it in Supabase. Built to be called from Apple Shortcuts.
"""

from __future__ import annotations

import hashlib
import logging
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
from fastapi.responses import FileResponse, JSONResponse

from app import db, extractor
from app.auth import require_api_key
from app.config import Settings, get_settings, is_production
from app.models import (
    Extraction,
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

# API responses that must never be cached by a proxy, browser or CDN.
NO_STORE_PREFIXES = ("/transactions", "/summary")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail fast: a container with missing configuration must not start serving."""
    settings = get_settings()  # raises with the missing NAME(s), never the values
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

PROTECTED = [Depends(require_api_key)]


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


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """The mobile-first UI. Public, but every API call it makes needs X-API-Key."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. No auth, so Shortcuts can check the tunnel quickly."""
    return {"status": "ok"}


@app.post(
    "/transactions/scan",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
    dependencies=PROTECTED,
)
async def scan_receipt(
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(description="Receipt image: jpg, png or webp")],
    mode: Annotated[Mode, Form()] = "personal",
) -> Transaction:
    """Upload a receipt image, extract it with Claude, save the transaction."""
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
    scanned = db.find_by_image_hash(image_hash)
    if scanned is not None:
        raise _duplicate(scanned, "This receipt has already been scanned.")

    # Claude first: an unreadable receipt must never leave an image in Storage.
    extraction = extractor.extract_from_image(image, media_type)

    receipt_path = f"{date.today():%Y/%m}/{uuid.uuid4().hex}{IMAGE_EXTENSIONS[media_type]}"
    try:
        db.upload_receipt(receipt_path, image, media_type)
    except Exception as exc:  # any storage failure is an upstream problem, not a client error
        logger.exception("Receipt upload to Supabase Storage failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Receipt upload failed: {exc}"
        ) from exc

    try:
        return _save(
            extraction,
            mode=mode,
            source="receipt_scan",
            receipt_path=receipt_path,
            image_hash=image_hash,
        )
    except Exception:
        db.delete_receipt(receipt_path)  # a rejected duplicate or a failed insert leaves no orphan
        raise


@app.post(
    "/transactions/text",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
    dependencies=PROTECTED,
)
async def create_from_text(payload: TextTransactionRequest) -> Transaction:
    """Extract a transaction from a short text note, e.g. "makan tengah hari 12 ringgit"."""
    return _save(extractor.extract_from_text(payload.text), mode=payload.mode, source="text")


@app.post(
    "/transactions",
    response_model=Transaction,
    status_code=status.HTTP_201_CREATED,
    dependencies=PROTECTED,
)
async def create_transaction(payload: TransactionCreate) -> Transaction:
    """Save one transaction typed in by hand: no receipt, no Claude, no dedupe by default."""
    return _insert(payload.to_row())


@app.get("/transactions", response_model=list[Transaction], dependencies=PROTECTED)
async def list_transactions(
    month: Annotated[str, Query(description="Month to list, as YYYY-MM")],
    mode: Mode = "personal",
) -> list[Transaction]:
    """Transactions in that month for that mode, newest first."""
    start, end = _month_bounds(month)
    return [Transaction.model_validate(row) for row in db.list_transactions(start, end, mode)]


@app.get("/transactions/{transaction_id}", response_model=Transaction, dependencies=PROTECTED)
async def get_transaction(transaction_id: UUID) -> Transaction:
    """One transaction."""
    return Transaction.model_validate(_existing(transaction_id))


@app.patch("/transactions/{transaction_id}", response_model=Transaction, dependencies=PROTECTED)
async def update_transaction(transaction_id: UUID, payload: TransactionUpdate) -> Transaction:
    """Correct a transaction by hand. A manual edit clears the needs-review flag."""
    row = _existing(transaction_id)
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

    updated = db.update_transaction(str(transaction_id), patch)
    return Transaction.model_validate(updated or _existing(transaction_id))


@app.delete(
    "/transactions/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=PROTECTED,
)
async def delete_transaction(transaction_id: UUID) -> None:
    """Delete the row, and its receipt object if it has one."""
    row = _existing(transaction_id)
    receipt_path = row.get("receipt_path")
    if receipt_path:
        db.delete_receipt(receipt_path)
    db.delete_transaction(str(transaction_id))


@app.get(
    "/transactions/{transaction_id}/receipt-url", response_model=ReceiptUrl, dependencies=PROTECTED
)
async def receipt_url(transaction_id: UUID) -> ReceiptUrl:
    """Short-lived signed URL for the private receipt image."""
    row = _existing(transaction_id)
    receipt_path = row.get("receipt_path")
    if not receipt_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This transaction has no receipt image.")
    return ReceiptUrl(url=db.create_receipt_url(receipt_path, RECEIPT_URL_TTL), expires_in=RECEIPT_URL_TTL)


@app.get("/summary", response_model=Summary, dependencies=PROTECTED)
async def summary(
    month: Annotated[str, Query(description="Month to summarise, as YYYY-MM")],
    mode: Mode = "personal",
) -> Summary:
    """Total expense, total income and total per category for that month."""
    start, end = _month_bounds(month)
    return Summary.model_validate(db.summarize(start, end, mode) | {"month": month, "mode": mode})


def _existing(transaction_id: UUID) -> dict[str, Any]:
    row = db.get_transaction(str(transaction_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No transaction with that id.")
    return row


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
    receipt_path: str | None = None,
    image_hash: str | None = None,
) -> Transaction:
    """Turn an extraction into a row and store it."""
    return _insert(
        extraction.to_row(
            mode=mode, source=source, receipt_path=receipt_path, image_hash=image_hash
        )
    )


def _insert(row: dict[str, Any]) -> Transaction:
    """Insert a row, or answer 409 with the row that already exists.

    Rows with no dedupe hash (text notes, hand-typed rows, merchant-less receipts) always
    insert, so only receipt scans can ever come back as duplicates.
    """
    dedupe = row["dedupe_hash"]
    existing = db.find_by_dedupe_hash(dedupe) if dedupe else None
    if existing is not None:
        raise _duplicate(existing, "This transaction is already recorded.")
    return Transaction.model_validate(db.insert_transaction(row))


def _duplicate(existing: dict[str, Any], message: str) -> HTTPException:
    """409 carrying the row that already exists, so the Shortcut can show it."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"error": "duplicate", "message": message, "transaction": existing},
    )
