"""The app icon: served publicly at every name iOS probes, opaque, and cache-busted.

The PNGs are inspected with the standard library (the IHDR chunk is 13 fixed bytes) so the tests
need no image dependency: what matters is that the files carry no alpha channel — iOS paints
transparency black on the Home Screen — that each is the square size its slot expects, and that the
page asks for them with a version query, because iOS keys its cached Home Screen icon on the URL.
"""

from __future__ import annotations

import re
import struct
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ALPHA_FREE_COLOUR_TYPES = {0, 2, 3}  # greyscale, truecolour, palette — none carry an alpha channel

# url -> (file, pixel size) for every name iOS or Safari asks for.
ICONS = {
    "/apple-touch-icon.png": ("apple-touch-icon.png", 180),
    "/apple-touch-icon-152x152.png": ("apple-touch-icon-152x152.png", 152),
    "/apple-touch-icon-120x120.png": ("apple-touch-icon-120x120.png", 120),
    "/logo.png": ("logo.png", 180),
}


def test_every_icon_is_public_and_short_lived(client: TestClient) -> None:
    for url, (_, _size) in ICONS.items():
        response = client.get(url)                       # no X-API-Key: the page's own icons
        assert response.status_code == 200, url
        assert response.headers["content-type"] == "image/png", url
        assert response.headers["X-Content-Type-Options"] == "nosniff", url
        assert response.headers["Referrer-Policy"] == "no-referrer", url

        cache = response.headers["Cache-Control"]
        assert cache == "public, max-age=600", url        # short, never immutable
        assert "immutable" not in cache and "no-store" not in cache, url

        assert response.content == (STATIC_DIR / ICONS[url][0]).read_bytes(), url


def test_the_add_sheet_has_one_save_and_no_pill(client: TestClient) -> None:
    """The header Save is the only Save again, and it still cannot double-post."""
    page = client.get("/").text
    # the pill is gone from the markup and from the stylesheet
    assert "addSaveBtn" not in page, "the thumb-reach Save pill is back"
    assert "add-save" not in page
    assert page.count('addEventListener("click", saveAdd)') == 1, "one Save, wired once"
    # and it is still the one state: disabled until there is an amount
    assert page.count('$("saveAddBtn").disabled = !(Number(addAmount) > 0);') == 1
    # the double-submit guard and its in-flight relabel are untouched
    assert "if (addSaving) return;" in page
    assert 'button.textContent = "Saving' in page
    # the height steps are back to the two the sheet was tuned with before the pill,
    # so the amount font and the keys get their full height back on a tall phone
    assert "@container (max-height: 640px)" in page
    assert "@container (max-height: 560px)" in page
    assert "@container (max-height: 780px)" not in page
    assert "@container (max-height: 650px)" not in page


def opening_tag(page: str, marker: str) -> str:
    """The opening tag that carries `marker`, up to its first '>'.

    A string harness can only read what the served markup says, so this is how a test asks an element
    about its own attributes — whether the form starts hidden, for one — rather than about the script
    that will move it later.
    """
    start = page.index(marker)
    return page[start:page.index(">", start) + 1]


def test_the_add_sheet_opens_on_a_two_option_chooser(client: TestClient) -> None:
    """The "+" lands on Manual or AI first, with no field, keypad or picker on screen until then.

    The sheet used to open straight onto the keypad, with Smart Entry always above it. It now opens on a
    chooser and every open resets to it. What a test can pin down is: both options exist, the two flows
    and the keypad start hidden, Save is not offered before there is anything to save, and opening the
    sheet asks for the chooser.
    """
    page = client.get("/").text
    assert 'id="screen-chooser"' in page
    assert ">Manual<" in page and ">AI<" in page
    # nothing to type into or tap a key on before the choice is made
    assert "hidden" in opening_tag(page, '<section id="screen-add"')
    assert "hidden" in opening_tag(page, '<section id="screen-ai"')
    assert "hidden" in opening_tag(page, 'id="addKeypad"')
    assert "hidden" in opening_tag(page, 'id="saveAddBtn"')
    # every open asks for the chooser, Back asks for it too, and nothing else picks a view
    assert page.count('showAddView("chooser")') == 2
    opened = page[page.index("function openAddSheet("):page.index("function closeAddSheet(")]
    assert 'showAddView("chooser")' in opened, "a fresh sheet must start on the chooser"
    assert "function showAddView(view)" in page
    assert '$("manualBody").scrollTop = 0;' in page, "Manual opens at its top"
    assert "revealAddChip();                 // a prefill paints" in page, "the chosen chip reveals with its view"
    assert '$("saveAddBtn").hidden = view !== "manual";' in page


def test_the_chooser_is_a_compact_two_card_grid(client: TestClient) -> None:
    """Two square cards side by side on a sheet that hugs them, until a flow is chosen.

    The chooser used to be two thin full-width rows at the top of a full-height sheet, which left most
    of the sheet blank. What markup and CSS can pin down here: the grid is two columns with a 12px gap,
    each card is one button carrying a badge, a bold label and a wrapping sub-label and no chevron
    (there is nowhere to go sideways), the rows that do open something keep theirs, and the sheet is
    compact while the chooser or the AI view is up — never a size container in that state, because
    `contain: size` would collapse an auto-height box.
    """
    page = client.get("/").text
    assert ".chooser-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px;" in page
    for card in ('<button class="chooser-card" id="chooseManualBtn" type="button">',
                 '<button class="chooser-card" id="chooseAiBtn" type="button">'):
        assert card in page, card
    assert page.count('class="chooser-badge"') == 2, "one icon badge per card"
    assert "<span class=\"chooser-sub\">Amount, merchant &amp; category</span>" in page
    assert "<span class=\"chooser-sub\">Typed note or receipt photo</span>" in page
    chooser = page[page.index('<section id="screen-chooser">'):page.index('<section id="screen-add"')]
    assert "add-row-chev" not in chooser, "the cards are the tap target; no chevron"
    assert "add-row-chev" in page, "the rows that do open something keep theirs"
    # the sub-label wraps rather than ellipsising: it is the one control that starts every entry
    sub = page[page.index(".chooser-sub {"):page.index("}", page.index(".chooser-sub {"))]
    assert "ellipsis" not in sub and "nowrap" not in sub, "the sub-label must wrap, not clip"
    assert "#addSheet.is-compact {" in page
    compact = page[page.index("#addSheet.is-compact {"):page.index("#addSheet.is-compact #screen-chooser")]
    assert "height: auto" in compact and "container-type: normal" in compact
    assert "padding-bottom: calc(16px + var(--sab))" in compact, "the cards clear the home indicator"
    assert '$("addSheet").classList.toggle("is-compact", view !== "manual");' in page


def test_each_flow_returns_to_the_chooser_and_cancel_leaves_the_sheet(client: TestClient) -> None:
    """Back is inside each flow; Cancel stays in the header and still closes the sheet from every view."""
    page = client.get("/").text
    assert 'id="addBackManual"' in page and 'id="addBackAi"' in page, "one Back per flow"
    assert page.count('addEventListener("click", reverseAddView)') == 2, "both Backs are wired"
    assert 'addEventListener("click", function () { showAddView("manual"); })' in page
    assert 'addEventListener("click", function () { showAddView("ai"); })' in page
    assert 'id="closeAddBtn"' in page
    assert '$("closeAddBtn").addEventListener("click", closeAddSheet);' in page
    # Two sheets were added with the balance breakdown (the breakdown itself and the one-field anchor),
    # and the What's New sheet with them, so the guard now appears on seven overlays; each still closes
    # its own sheet.
    assert page.count('isOutsideTap(event, $("') == 7, "the scrim still closes the sheet"
    # Back takes the keyboard with it, or the chooser returns under a keyboard with nothing to type into
    back = page[page.index("function reverseAddView("):page.index("function reverseAddView(") + 400]
    assert "active.blur()" in back


def test_the_chooser_moved_the_entry_point_and_not_the_submission(client: TestClient) -> None:
    """Both flows post exactly what they posted before: same endpoints, same fields, same payload keys."""
    page = client.get("/").text
    for call in ('api("/transactions", {', 'api("/transactions/text", {', 'api("/transactions/scan", {'):
        assert call in page, call
    assert "body: JSON.stringify({ text: text, mode: addMode })" in page
    assert 'form.append("mode", addMode);' in page
    # the fields and rows each flow submits from still exist: they moved view, not shape
    for element in ('id="textInput"', 'id="textBtn"', 'id="scanBtn"', 'id="addMerchant"',
                    'id="addNote"', 'id="addDate"', 'id="keypadGrid"', 'id="addChips"'):
        assert element in page, element


def test_every_add_sheet_field_keeps_the_16px_ios_floor(client: TestClient) -> None:
    """iOS zooms the whole page when a focused control is under 16px, and this sheet never resizes.

    The chooser's own controls are two buttons, which iOS does not zoom for, so this is the floor over
    the fields the two flows share: the Smart Entry text field, the merchant and note inputs, and the
    invisible date input over the pill.
    """
    page = client.get("/").text
    assert ".add-field {" in page and ".add-date-input {" in page
    assert not re.search(r"\.(add-field|add-date-input)[^{]*\{[^}]*font-size:\s*(1[0-5]|[0-9])px", page), (
        "a sheet field is under the 16px iOS zoom threshold"
    )
    # and the same floor for anything else the CSS sizes by control type
    assert not re.search(r"(input|select|textarea)[^{]{0,60}\{[^}]*font-size:\s*(1[0-5]|[0-9])px", page), (
        "a control is under the 16px iOS zoom threshold"
    )


def test_the_detail_sheet_swipes_and_keeps_its_old_edit_buttons(client: TestClient) -> None:
    """The swipe surfaces and the scroll gate stay; edit mode is back to its plain row of buttons."""
    page = client.get("/").text
    surfaces = page[page.index("var DRAG_SURFACES"):page.index("var DRAG_BLOCKERS")]
    for surface in (".kv", ".card-title", ".sheet-title", ".sheet-amount", ".sheet"):
        assert surface in surfaces, surface + " must be able to start a swipe"
    # the gate: a sheet that scrolls keeps its own gesture until it is back at the top
    assert "if (sheet.scrollTop > 0 || scrolledInside(sheet)) return;" in page
    assert "function scrolledInside(sheet)" in page
    assert '$("txnSheet").scrollTop = 0;' in page, "a fresh or closed sheet must start at the top"
    # the surfaces the browser must not treat as a pan
    assert "#txnSheet .kv, #txnSheet .card-title { touch-action: none; }" in page
    # and the touch default is refused on those surfaces, which is what stops the pointercancel
    assert 'sheet.addEventListener("touchstart", function (event) {' in page
    assert "{ passive: false }" in page
    # edit mode's buttons are the plain pair again, with no footer pill
    assert '<div class="sheet-actions"><button class="btn-primary" id="saveBtn" type="button">Save</button>' in page
    assert '<button class="btn-ghost" id="cancelEditBtn" type="button">Cancel</button></div>' in page
    assert "sheet-foot" not in page
    assert "save-changes" not in page
    assert "sheet-cancel-edit" not in page


def test_the_icons_are_documented_nowhere_as_api(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert not [path for path in ICONS if path in paths]


def test_the_page_is_never_stored(client: TestClient) -> None:
    """The page carries the icon links and all the CSS/JS inline, so a cached copy is a stale app."""
    home = client.get("/")
    assert home.headers["Cache-Control"] == "no-store"
    assert "max-age" not in home.headers["Cache-Control"]


DEPLOYED_SHA = "8f39d7e4b1c2a09e6d5f4a3b2c1d0e9f8a7b6c5d"


def test_the_build_row_shows_the_deployed_commit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """On Render, GET / carries the short SHA in both places the Build row reads it, and stays uncached."""
    monkeypatch.setenv("RENDER_GIT_COMMIT", DEPLOYED_SHA)
    response = client.get("/")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert "{{BUILD}}" not in page
    assert page.count("8f39d7e · fullscreen") == 2  # the default span and the BUILD constant


def test_the_build_row_is_dev_without_render(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local runs have no RENDER_GIT_COMMIT, so the row says dev; anything but a full SHA is never injected."""
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    response = client.get("/")
    assert response.headers["Cache-Control"] == "no-store"
    assert "{{BUILD}}" not in response.text
    assert response.text.count("dev · fullscreen") == 2

    monkeypatch.setenv("RENDER_GIT_COMMIT", "<script>alert(1)</script>")
    assert "dev · fullscreen" in client.get("/").text
    assert "<script>alert(1)" not in client.get("/").text


def test_the_sheet_tap_guards_are_target_based(client: TestClient) -> None:
    """A tap must be dismissed only when it IS the scrim, never by re-querying a detached node.

    Tapping a category chip redraws the chips row, and tapping Edit or Delete replaces the sheet's body,
    which detaches the element the click's target points at. A guard written as
    `event.target.closest(".sheet")` then finds no ancestor on that detached node, decides the tap was
    outside, and closes the sheet — which is what broke the chips and the edit/delete buttons on the
    phone. The guard must ask whether the target is the scrim layer (or the overlay itself).
    """
    page = client.get("/").text
    assert "function isOutsideTap(event, overlay)" in page
    assert 'return event.target === overlay || (!!scrim && event.target === scrim);' in page
    assert '!event.target.closest(".sheet")' not in page, "the detached-node guard is back"
    # Both sheets added with the balance breakdown use the guard too, by overlay and not by re-query:
    # the breakdown's own content is replaced on every render, so a detached-node guard would fail there.
    assert 'if (isOutsideTap(event, $("balanceOverlay"))) closeBalanceSheet();' in page
    assert 'if (isOutsideTap(event, $("moneyFieldOverlay"))) closeMoneyField();' in page
    assert 'if (isOutsideTap(event, $("whatsNewOverlay"))) closeWhatsNew();' in page
    assert page.count("isOutsideTap(event, $(") == 7, "all seven overlays must use the guard"


def test_the_drag_waits_for_the_threshold_before_capturing(client: TestClient) -> None:
    """setPointerCapture on pointerdown moves the tap's click event to the sheet.

    A capture taken on pointerdown makes the sheet the target of the pointerup, so the synthesised click
    lands on the sheet instead of the button that was tapped, and the button's handler never runs. It
    must be taken only once the drag is real — after the >8px mostly-vertical threshold — and the drag
    must only be able to start on an allowed surface.
    """
    page = client.get("/").text
    body = page[page.index("function attachSheetDrag"):page.index("function openRowFrom")]
    threshold = body.index("dy < DRAG_START_PX")
    capture = body.index("sheet.setPointerCapture(event.pointerId)")
    assert threshold < capture, "capture must come after the drag is claimed"
    # the function itself must consult both lists
    assert body.index("closest(DRAG_SURFACES)") < body.index("closest(DRAG_BLOCKERS)")
    # the allow list is a short list of surfaces...
    surfaces = page[page.index("var DRAG_SURFACES"):page.index("var DRAG_BLOCKERS")]
    for surface in (".sheet-grab", ".sheet-head", ".add-amount", ".sheet-title", ".sheet"):
        assert surface in surfaces, surface + " must be a drag surface"
    # ...and the deny list still removes everything with a gesture of its own
    blockers = page[page.index("var DRAG_BLOCKERS"):page.index("var DRAG_START_PX")]
    for blocked in (".cat-chip", ".key", ".chip-scroll", ".add-rows", ".smart-card", "button",
                    "input"):
        assert blocked in blockers, blocked + " must stay blocked"


@pytest.mark.parametrize(
    "url, filename, size", [(url, name, size) for url, (name, size) in sorted(ICONS.items())]
)
def test_the_icon_files_are_opaque_and_square(url: str, filename: str, size: int) -> None:
    raw = (STATIC_DIR / filename).read_bytes()
    assert raw.startswith(PNG_SIGNATURE), url

    width, height, depth, colour_type = struct.unpack(">IIBB", raw[16:26])
    assert (width, height) == (size, size), url
    assert width == height, f"{url} must be square so iOS rounds it, not distorts it"
    assert depth == 8, url
    assert colour_type in ALPHA_FREE_COLOUR_TYPES, (
        f"{url} must have no alpha channel, or iOS draws the transparent parts black"
    )
    assert len(raw) < 150_000, url


def test_the_icon_links_are_versioned(client: TestClient) -> None:
    page = client.get("/").text
    links = re.findall(r'<link rel="(?:apple-touch-icon|icon)"[^>]*href="([^"]+)"', page)

    assert len(links) == len(ICONS)
    for href in links:
        assert re.search(r"\?v=\d+$", href), (
            f"{href} needs a ?v= query: iOS keys its cached Home Screen icon on the URL"
        )
    # and every versioned URL the page asks for is really served
    for href in links:
        assert client.get(href).status_code == 200, href


# ---------------------------------------------------------------- money: the hero, the sheet, the settings

def test_home_is_a_balance_hero_with_a_safe_to_spend_pill(client: TestClient) -> None:
    """The all-time balance, the safe-to-spend pill under it, and the one target that explains them.

    What the served page can pin: the balance is /finance/summary's current_balance (never a total the
    page works out itself), it is the largest figure on the screen, the whole figure area is one real
    button with an accessible name (>=44px) that opens the breakdown sheet, the one state that colours a
    figure is a negative safe-to-spend in the shared --danger, and with no opening balance the card asks
    for the one figure it cannot know instead of showing a number that would read as one.
    """
    page = client.get("/").text
    assert 'id="balanceCard"' in page and "Set your balance" in page
    assert 'class="hero-amount hero-balance" id="balanceAmount"' in page
    # the balance comes from the reply, and money() drops the sign so signedMoney puts the minus back
    assert "var balance = Number(summary.current_balance) || 0;" in page
    assert '$("balanceAmount").textContent = signedMoney(balance);' in page
    assert "function signedMoney(value)" in page
    assert '(number < 0 ? "\\u2212" : "") + money(Math.abs(number))' in page
    # The month is named once, by the picker in the shared header. The hero used to repeat it as a pill;
    # a second "Oct 2026" one line under the first read as a duplicate, so the hero has none.
    hero = page[page.index('id="balanceCard"'):page.index('id="budgetCard"')]
    assert "js-month-label" not in hero, "the header is the only place the month is named"
    assert "hero-top" not in page
    # The balance keeps the heaviest weight, but its own size is the one that was measured to keep
    # "RM 2,470.00" on one line at 375px (238.33px of 306px available) and 390px. It is a block so
    # the wallet label cannot take width from the figure, and nowrap is the belt.
    assert ".hero-amount {\n    font-size: 40px; font-weight: 800" in page
    assert ".hero-balance { display: block; font-size: 40px; white-space: nowrap; }" in page
    assert 'fitText($("balanceAmount"), 40, 22);' in page
    # The word "Balance" is now a wallet icon plus the visible small "all modes"; the icon carries the
    # accessible name, and the button's own name is repainted with the figure it shows.
    assert 'id="balanceTap" type="button" aria-label="Balance, all modes. How this is calculated"' in page
    assert 'class="hero-balance-mark" role="img" aria-label="Balance, all modes"' in page
    assert '<span class="hero-balance-unit">all modes</span>' in page
    assert ">all modes<" in page, "the visible label must stay, not only the aria-label"
    assert 'class="hero-balance-icon"' in page
    tap = page[page.index(".hero-tap {"):page.index("}", page.index(".hero-tap {"))]
    assert "min-height: 44px" in tap
    assert '$("balanceTap").setAttribute("aria-label", "Balance, all modes, " + signedMoney(balance)' in page
    # ...and the pill is inside it, so it is a span, not a second target
    assert '<span class="safe-pill" id="safePill">' in page
    assert 'id="safeDetailsBtn"' not in page
    assert 'class="safe-pill-chev"' in page
    for element in ('id="safeAmount"', 'id="safeMeta"'):
        assert element in page, element
    assert ".safe-pill-amount.neg { color: var(--danger); }" in page
    assert '$("safeAmount").classList.toggle("neg", safe < 0);' in page
    # No opening balance yet: the card asks for it, and the figure area is not on screen at all.
    assert 'id="balanceNotSet"' in page and 'id="setBalanceBtn"' in page
    assert "Tell us how much money you have right now. We keep track from there." in page
    assert "function openingIsSet(summary)" in page
    assert '$("balanceNotSet").hidden = set;' in page
    assert '$("balanceTap").hidden = !set;' in page
    # The anchor's own maths, which is what the sheet asks for: the export is not reachable from here, so
    # tests/test_static.py mirrors it in integer cents (see test_the_anchor_maths_is_integer_cents).
    assert "function toCents(value)" in page and "function openingFor(typed, income, expense)" in page
    # the commitments sheet keeps its second way in from Settings
    assert "function showMoneySettings()" in page
    assert 'addEventListener("click", openCommitSheet)' in page


def mirror_cents(text: str) -> int:
    """The page's toCents(): a typed money string to integer cents.

    Mirrors `parseMoneyInput` (commas and spaces are noise, a leading minus is a real sign) and then the
    page's `Math.round(value * 100)`. Decimal, not float: the whole point of the cents step is that 0.1 +
    0.2 cannot come out as 0.30000000000000004.
    """
    cleaned = re.sub(r"[,\s]", "", text)
    if not re.fullmatch(r"-?\d+(\.\d{0,2})?", cleaned):
        return 0          # what the page does with unreadable input: 0, said out loud in the preview line
    return int((Decimal(cleaned) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mirror_opening(typed: str, income: str, expense: str) -> Decimal:
    """The page's openingFor(): typed - income + expense, all three in integer cents."""
    cents = mirror_cents(typed) - mirror_cents(income) + mirror_cents(expense)
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def test_the_anchor_maths_is_integer_cents(client: TestClient) -> None:
    """A Python mirror of the page's anchor arithmetic — the JS itself is neither exported nor run here.

    The anchor sheet asks for the money the owner has right now and stores the opening balance that makes
    it true (`opening = typed - income + expense`), because the API derives the balance from the opening
    balance plus the all-time totals. What this test pins is the contract: integer cents, so 0.1 + 0.2
    cannot drift; a negative typed figure stays negative; and the answer is a 2-decimal figure. The mirror
    is kept honest by the three string pins — change the page's formula and this test fails even though the
    arithmetic it mirrors still passes. What it does NOT prove is that the JS computes it the same way;
    only running the page does that (see the harness measurement in the report).
    """
    page = client.get("/").text
    assert "Math.round(number * 100)" in page
    assert "(toCents(typed) - toCents(income) + toCents(expense)) / 100" in page
    assert page.count("openingFor(typed, summary.total_income, summary.total_expense)") == 2, (
        "the preview and the save must run the same conversion, or what is stored is not what was shown"
    )

    # What was typed is what the balance becomes: 1250 with 1200 in and 800 out is an opening of 850 —
    # the figure the harness measured, where the card then read RM 1,250.00.
    assert mirror_opening("1250.00", "1200.00", "800.00") == Decimal("850.00")
    # Comma and space tolerant, because parseMoneyInput is.
    assert mirror_opening("1,250", "1,200", "800") == Decimal("850.00")
    assert mirror_opening(" 1,250 ", "1200.00", "800.00") == Decimal("850.00")
    # A negative typed figure is a real overdraft, not a typo to be dropped.
    assert mirror_opening("-80", "1200.00", "800.00") == Decimal("-480.00")
    # The cents the harness measured for the drift case: 0.10 typed, 1200 in, 800 out.
    assert mirror_opening("0.10", "1200.00", "800.00") == Decimal("-399.90")
    # 0.1 + 0.2 in cents is 0.30 typed with 0.10 in and 0.20 out: an opening of 0.40, exact.
    assert mirror_opening("0.30", "0.10", "0.20") == Decimal("0.40")
    # Why the cents step is not decoration: in floats neither of these is true. (0.30 - 0.10 happens to
    # land back on 0.20 in double precision, so the drift is shown on the two that do not.)
    assert 0.1 + 0.2 != 0.3
    assert 0.30 - 0.10 != 0.20
    assert mirror_opening("0.30", "0.10", "0.00") == Decimal("0.20")
    # Large: 12,345,678.90 typed, 2,345,678.90 in, 1,000,000.00 out.
    assert mirror_opening("12345678.90", "2345678.90", "1000000.00") == Decimal("11000000.00")
    # Exactly zero, the edge case: saved as computed, never nudged. The reply's zero is also what "not set
    # yet" looks like, so the card goes back to asking for the balance — honest, and one tap to redo.
    assert mirror_opening("0.00", "1200.00", "1200.00") == Decimal("0.00")
    assert mirror_opening("12345678.90", "12345678.90", "0.00") == Decimal("0.00")
    # Unreadable input counts as 0 in toCents (the field itself refuses to save it, with its own message).
    assert mirror_cents("") == 0 and mirror_cents("abc") == 0 and mirror_cents("1.234") == 0


def test_the_breakdown_sheet_and_the_one_field_sheet_are_registered(client: TestClient) -> None:
    """Two more sheets, same parts as the rest: scrim, grab, drag, outside-tap guard and a close.

    The breakdown is the balance area's destination, and the one-field sheet is shared by the anchor and
    the budget offer. Both are overlays, so both must be registered rather than hand-rolled — and the
    anchor's field must clear the 16px floor, or iOS zooms the page on focus.
    """
    page = client.get("/").text
    for overlay, sheet in (("balanceOverlay", "balanceSheet"), ("moneyFieldOverlay", "moneyFieldSheet")):
        start = page.index('id="' + overlay + '"')
        block = page[start:start + 400]
        assert '<div class="scrim" aria-hidden="true"></div>' in block, overlay
        assert 'id="' + sheet + '"' in block, overlay
        assert 'openOverlay($("' + overlay + '"))' in page, overlay
        assert 'attachSheetDrag("' + sheet + '", "' + overlay + '"' in page, overlay
        assert 'isOutsideTap(event, $("' + overlay + '"))' in page, overlay
    # The balance area is the breakdown's way in, and the not-set button is the anchor's.
    assert '$("balanceTap").addEventListener("click", openBalanceSheet);' in page
    assert '$("setBalanceBtn").addEventListener("click", function () { openMoneyField("balance"); });' in page
    assert '$("setBudgetBtn").addEventListener("click", function () { openMoneyField("budget"); });' in page
    # One field, one save: the same sheet, told which setting it is setting.
    assert '$("moneyFieldSaveBtn").addEventListener("click", function () { saveMoneyField(this); });' in page
    assert "var moneyFieldTarget = " in page
    assert "body.monthly_budget = typed;" in page
    assert "body.opening_balance = openingFor(" in page
    # the 16px floor, stated on the selector that wins (a bare .money-field-input loses to .field later on)
    assert ".sheet .money-field-input { font-size: 16px; }" in page
    assert ".field {\n    width: 100%; min-height: 44px;" in page
    # the breakdown is built from the reply: the six rows of the calculation, in order
    assert "function renderBalanceRows()" in page
    # the bills row is built first, as a variable; the order that matters is the one that is painted
    painted = page[page.index('$("balanceRows").innerHTML ='):page.index("function openBalanceSheet()")]
    labels = ["Starting balance", "+ Income", "\\u2212 Expenses", "= Balance",
              "bills", "= Safe to spend", "balance-note"]
    positions = [painted.index(label) for label in labels]
    assert positions == sorted(positions), "the rows keep the order of the calculation"
    assert 'id="balanceMoneyBtn"' in page and "Settings &middot; Money<" in page


def test_the_calculation_sheet_is_the_short_list_and_a_pencil(client: TestClient) -> None:
    """Six rows, one line about the budget, and a pencil for the anchor; the long note is gone.

    The sheet says what the balance is made of. The all-months and all-modes arithmetic is still true,
    but it now lives in the balance card's own label ("all modes"), not in a paragraph under the rows.
    """
    page = client.get("/").text
    sheet = page[page.index('<div class="overlay" id="balanceOverlay"'):page.index('<div class="overlay" id="moneyFieldOverlay"')]
    # the markup carries no prose: the rows are rendered from the reply
    assert "These totals include every month" not in page
    assert "(all months, all modes)" not in page
    assert "differ from the monthly cards on Home" not in page
    # The one sentence the sheet keeps is the budget's, and it must be the CURRENT rule:
    # remaining_budget = budget - (month_expense - month_commitment_expense) (app/finance.py). The
    # old wording said the budget used "this mode's spending + unpaid bills", which is the formula
    # that was thrown out with 0004 — and it was not even in the app's language.
    assert ('<p class="balance-note">Budget counts spending in this mode for the month, '
            'less the bills you have already paid.</p>') in page
    assert "guna perbelanjaan" not in page, "the stale note is gone"
    # the pencil is the anchor's control: an icon-only button with a name and a 44px target
    assert ('<button class="balance-edit" id="editBalanceBtn" type="button" aria-label="Edit my balance">'
            in page)
    assert ">Edit my balance<" not in page, "the text link is replaced by the pencil"
    assert "Edit my balance" not in sheet.replace('aria-label="Edit my balance"', ""), "no visible text left"
    edit_css = page[page.index(".balance-edit {"):page.index("}", page.index(".balance-edit {"))]
    assert "width: 44px; height: 44px;" in edit_css
    assert 'data-bills="1"' in page and 'id="balanceBillsBtn"' in page
    # the pencil opens the one-field sheet, and Settings · Money is still the text link
    assert 'event.target.closest("[data-bills], #editBalanceBtn, #balanceMoneyBtn")' in page
    assert 'if (hit.id === "editBalanceBtn") { openMoneyField("balance"); return; }' in page


def test_the_money_icons_are_named_by_their_labels_or_by_aria_label(client: TestClient) -> None:
    """Each money icon sits beside its visible text, so it is decorative and says nothing twice.

    The one icon with no text beside it is the pencil, and it is the one that carries an aria-label.
    Every icon is stroked in currentColor, so none adds a colour of its own.
    """
    page = client.get("/").text
    # Income (up arrow) and Expenses (down arrow): each icon is inside its own stat label, before the text
    for path, text in (("M12 19V5", "Income</span>"),
                       ("M12 5v14", "Expenses</span>")):
        label = page.index('<span class="stat-label"><svg class="money-icon"')
        assert path in page[label:page.index(text)], text
    assert page.count('<span class="stat-label"><svg class="money-icon" viewBox="0 0 24 24"') == 2
    # Budget (gauge) beside both budget titles
    assert page.count('class="money-icon budget-icon"') == 2
    # Commitments (calendar) in the Settings row, and beside the bills label on the sheet
    settings_row = page[page.index('id="commitmentsBtn"'):page.index('id="commitmentsValue"')]
    assert '<rect x="3.5" y="5" width="17" height="15.5" rx="3.5"/>' in settings_row
    assert 'aria-hidden="true"' in settings_row
    assert "Commitments</span>" in settings_row
    assert "Bills due this month" in page and "BILLS_ICON" in page
    # Every paired icon is hidden from assistive tech, because its label is the name.
    # The pencil is the one icon with no text beside it, so it is the one control that carries a name.
    assert page.count('aria-hidden="true" focusable="false"') >= 6
    assert page.count('aria-label="Edit my balance"') == 1
    assert "BILLS_ICON = '<svg class=\"money-icon\"" in page


def test_the_month_is_split_into_two_half_cards(client: TestClient) -> None:
    """"Spent this month" and its Net cell are gone: the month is Income and Expenses, side by side.

    Both read the existing /summary for the viewed month and mode — the balance above them is all-time
    and every mode, so the two must not be confused with it.
    """
    page = client.get("/").text
    assert "Spent this month" not in page
    assert 'id="totalSpent"' not in page and 'id="netTotal"' not in page and 'id="heroSplit"' not in page
    assert 'id="itemsPill"' not in page
    assert 'class="stat-row"' in page
    assert page.count('class="card stat-card"') == 2
    # The labels are the two words. The month is named once, by the picker in the header, so a
    # "this month" on each card is not needed, and it used to wrap one label and not the other.
    assert 'class="stat-label"><svg class="money-icon"' in page
    assert 'Income</span>' in page and 'Expenses</span>' in page
    assert "Income &middot; this month" not in page
    assert "Expenses &middot; this month" not in page
    for element in ('id="incomeTotal"', 'id="expenseTotal"'):
        assert element in page, element
    # half width each, and the income figure carries the green token
    stat = page[page.index(".stat-card {"):page.index("}", page.index(".stat-card {"))]
    assert "flex: 1 1 0" in stat
    assert 'class="stat-amount in" id="incomeTotal"' in page
    assert ".stat-amount.in { color: var(--green); }" in page
    # both from the one /summary, and money() drops the sign so Expenses puts its own minus back
    assert '$("incomeTotal").textContent = "+" + money(Number(summary.total_income) || 0);' in page
    assert '$("expenseTotal").textContent = "\\u2212" + money(Number(summary.total_expense) || 0);' in page
    # Half a phone is a narrow box and a month can reach five figures: the figure steps its own font down
    # until it fits, so it never clips and never spills over the card.
    assert "function fitText(el, max, min)" in page
    assert "while (size > min && el.scrollWidth > el.clientWidth)" in page
    for call in ('fitText($("incomeTotal"), 19, 14);', 'fitText($("expenseTotal"), 19, 14);',
                 'fitText($("safeAmount"), 17, 12);'):
        assert call in page, call
    # The old setup pill was sized by its own class, so a paint had to clear the inline size the previous
    # one left. That class is gone: the pill only ever shows a real figure now, so it is always fitted.
    assert ".safe-pill.is-setup" not in page
    assert "if (setup) $(\"safeAmount\").style.fontSize" not in page


def test_the_budget_card_only_appears_with_a_budget_in_the_current_month(client: TestClient) -> None:
    """Three states in one slot, and never a fourth: bar, offer, or nothing.

    The bar is the used share — budget minus what is left, clamped — and it is a real progressbar, so a
    screen reader hears the same percentage the card prints. Over budget is said in words, not colour.
    With no budget the same slot offers to set one (dashed, so it cannot be mistaken for a figure); in a
    month that is not the current one it does neither, because a budget is a live thing.
    """
    page = client.get("/").text
    assert '<div class="card budget-card" id="budgetCard" hidden>' in page
    assert ">Monthly budget limit<" in page
    for element in ('id="budgetPct"', 'id="budgetLeft"', 'id="budgetDays"', 'id="budgetFill"'):
        assert element in page, element
    # the progressbar contract
    bar = page[page.index('id="budgetBar"'):page.index('id="budgetFill"')]
    assert 'role="progressbar"' in bar and 'aria-valuemin="0"' in bar and 'aria-valuemax="100"' in bar
    assert 'aria-valuenow="0"' in bar and "aria-label=" in bar
    assert '$("budgetBar").setAttribute("aria-valuenow", String(pct));' in page
    # Branch one: any month that is not the one we are in shows neither card.
    assert "if (state.month !== currentMonth()) { hideBudget(); return; }" in page
    # Branch two: no budget set offers one, and the offer is dashed so it reads as an invitation.
    assert "if (!(budget > 0)) { hideBudget(); paintBudgetPrompt(); return; }" in page
    assert "function paintBudgetPrompt()" in page
    assert '<div class="card budget-card budget-prompt" id="budgetPromptCard" hidden>' in page
    assert ">Set a monthly budget (optional)<" in page
    assert 'id="setBudgetBtn"' in page
    prompt = page[page.index(".budget-prompt {"):page.index("}", page.index(".budget-prompt {"))]
    assert "border-style: dashed" in prompt
    # Branch three: set but unreadable claims nothing at all rather than guessing.
    assert "if (remaining == null) { hideBudget(); return; }" in page
    # hidden and reset in one place, so neither card holds the last month's bar
    assert "function hideBudget()" in page
    hide = page[page.index("function hideBudget()"):page.index("function paintFinanceError()")]
    assert '$("budgetCard").hidden = true;' in hide
    assert '$("budgetPromptCard").hidden = true;' in hide
    # used share, clamped; over budget still sayable
    assert "Math.round(Math.min(Math.max((budget - left) / budget, 0), 1) * 100)" in page
    assert '$("budgetPct").textContent = pct + "% of " + money(budget);' in page
    assert '.bar-fill.over { background: var(--danger); }' in page
    assert '.budget-left.over { color: var(--danger); font-weight: 600; }' in page
    assert 'money(Math.abs(left)) + " over budget"' in page
    assert 'money(left) + " left to spend"' in page
    # days remaining is computed here, in the month being viewed
    assert "function daysLeftLabel()" in page
    assert "daysInMonth(state.month) - Number(localIso(new Date()).slice(8, 10))" in page
    assert '" day remaining" : " days remaining"' in page
    # The budget cards no longer carry the "separate from your balance" line: it moved into the budget
    # sheet, the one place a limit is typed, as the small note under its question.
    budget_cards = page[page.index('id="budgetCard"'):page.index('<div class="section-head">')]
    assert "Monthly limit, separate from your balance." not in budget_cards
    assert page.count("Monthly limit, separate from your balance.") == 1
    assert 'budgetNote' not in page and ".budget-note" not in page
    sheet_note = page[page.index("function paintMoneyFieldNote()"):page.index("function paintMoneyFieldNote()") + 400]
    assert 'if (moneyFieldTarget === "budget") {' in sheet_note
    assert 'note.textContent = "Monthly limit, separate from your balance.";' in sheet_note


def test_the_budget_bar_steps_its_colour_at_half_and_at_four_fifths(client: TestClient) -> None:
    """Blue under half of the budget used, yellow (--caution) from 50% to 79%, red (--danger) from 80%.

    The percentage is the one the card shows, and the bar and the text take the same tone, so the
    colour can never say something the number does not. Both palettes define the yellow token.
    """
    page = client.get("/").text
    # the tokens: one new yellow, in both palettes, next to --amber
    light = page[page.index("  :root {"):page.index('[data-theme="dark"] {')]
    dark = page[page.index('[data-theme="dark"] {'):page.index("}", page.index('[data-theme="dark"] {'))]
    assert "--caution: #9a6700;" in light
    assert "--caution: #ffd60a;" in dark
    # the thresholds, read from the same pct that is drawn
    tone = page[page.index("function budgetTone(pct, left)"):page.index("function paintBudgetTone(")]
    assert 'if (left < 0 || pct >= 80) return "danger";' in tone
    assert 'return pct >= 50 ? "caution" : "";' in tone
    paint = page[page.index("var tone = budgetTone(pct, left);"):page.index("$(\"budgetLeft\").textContent")]
    assert 'paintBudgetTone("budgetFill", tone);' in paint and 'paintBudgetTone("budgetPct", tone);' in paint
    assert '$(id).classList.toggle("caution", tone === "caution");' in page
    assert '$(id).classList.toggle("danger", tone === "danger");' in page
    # the reset clears both, so a hidden card never keeps last month's colour
    hide = page[page.index("function hideBudget()"):page.index("function hideBudget()") + 500]
    assert 'paintBudgetTone("budgetFill", "");' in hide and 'paintBudgetTone("budgetPct", "");' in hide
    # the CSS: the bar and the text use the same tokens
    assert ".bar-fill.caution { background: var(--caution); }" in page
    assert ".bar-fill.danger { background: var(--danger); }" in page
    assert ".budget-pct.caution { color: var(--caution); }" in page
    assert ".budget-pct.danger { color: var(--danger); }" in page


def test_the_category_ring_is_gone_from_home_and_insights_keeps_it(client: TestClient) -> None:
    """The Home card is deleted; the breakdown it linked to is Insights' own, so nothing is orphaned.

    It was never a sheet: the whole card navigated to Insights, which renders the same categories from
    the same rows (donutSvg + insightCategoryList). Removing it leaves no dead end — and no dead code.
    """
    page = client.get("/").text
    assert 'id="categoryCard"' not in page and 'id="categoryList"' not in page
    home = page[page.index('id="screen-home"'):page.index('id="screen-transactions"')]
    assert "By category" not in home
    # Insights still has the donut, the list and the "show all" row
    assert '>Spending by category<' in page
    for element in ('id="insightDonut"', 'id="insightCats"'):
        assert element in page, element
    assert 'toggle: "insightCatToggle"' in page and "function categoryToggleHtml(" in page
    assert "function insightCategoryList(" in page
    assert "function donutSvg(" in page
    # the Home-only renderers and their CSS went with the card
    for gone in ("function renderHomeCategories(", "function homeCategoryGroups(",
                 "function legendRowHtml(", "HOME_DONUT_ROWS", ".cat-split", ".legend-row",
                 "donut-sm", "card-tap"):
        assert gone not in page, gone
    # Recent Transactions is untouched: three rows and the same See All
    assert "var HOME_LIST_ROWS = 3;" in page
    assert "visible.slice(0, HOME_LIST_ROWS)" in page
    assert 'id="seeAllBtn"' in page and ">See All<" in page


def test_a_failing_finance_read_never_blanks_home(client: TestClient) -> None:
    """The balance's own read is guarded, so a missing money table costs the balance and not the month.

    Seen for real: live is at schema 0002 while 2b reads /finance/summary, the reply was a 500
    (PGRST205, no user_finance_settings), the rejection took the whole Promise.all with it, and Home
    rendered an empty month and a server error while /transactions had answered 200 with rows.
    """
    page = client.get("/").text
    home = page[page.index("async function loadHome("):page.index("// Re-read only the money figures")]
    assert 'api("/finance/summary" + monthQuery()).catch(function () { return null; })' in home
    assert "if (loaded[2]) paintFinance(loaded[2]); else paintFinanceError();" in home
    # guarded per request: still one batch, and no second try of the same read
    assert home.count("await Promise.all(") == 1
    assert home.count("catch(function () { return null; })") == 1
    # "could not read it" must not read as "you have not set it up yet"
    assert '$("safeMeta").textContent = "Not available right now.";' in page
    # ...and the one action that fits is the one read that failed, so the retry row re-runs /finance/summary
    # and nothing else. The card keeps its shape but is not tappable: there is no breakdown to draw.
    assert '$("balanceNotSet").hidden = true;' in page
    assert '$("balanceTap").disabled = true;' in page
    assert '$("retryFinanceBtn").hidden = false;' in page
    assert '$("retryFinanceBtn").addEventListener("click", refreshFinanceCard);' in page
    assert '<button class="btn-link hero-retry" id="retryFinanceBtn" type="button" hidden>Try again</button>' in page
    # the budget card cannot be drawn from figures that never arrived
    error = page[page.index("function paintFinanceError()"):page.index("// One row shape")]
    assert "hideBudget();" in error
    # and the month's two cards say so too rather than claiming zero
    assert '$("incomeTotal").textContent = "\\u2014";' in home
    assert '$("expenseTotal").textContent = "\\u2014";' in home


def test_the_commitments_sheet_is_a_registered_overlay(client: TestClient) -> None:
    """A fourth sheet with the same parts as the other three: a scrim, a drag, a guard and a close."""
    page = client.get("/").text
    overlay = page[page.index('<div class="overlay" id="commitOverlay"'):]
    assert '<div class="scrim" aria-hidden="true"></div>' in overlay[:600]
    assert 'id="commitSheet"' in overlay[:600]
    assert 'openOverlay($("commitOverlay"))' in page
    assert 'attachSheetDrag("commitSheet", "commitOverlay", closeCommitSheet, false)' in page
    assert 'isOutsideTap(event, $("commitOverlay"))' in page
    # it precedes the Add overlay, so a Pay tap stacks the Add sheet on top of it and comes back
    assert page.index('id="commitOverlay"') < page.index('id="addOverlay"')
    # the dim is the sheet-strength scrim, and it is the only thing in this overlay that fades
    assert "#commitOverlay .scrim { background: var(--scrim-sheet); }" in page


def test_the_commitments_sheet_reads_the_month_and_offers_pay_only(client: TestClient) -> None:
    """The list is per month, Pay is the only action, and the add form posts the three API fields."""
    page = client.get("/").text
    # /commitments requires a month, and the sheet sends the one being viewed
    assert 'api("/commitments?month=" + encodeURIComponent(month))' in page
    # a row: the name (user data, escaped), the amount and the due day
    assert "escapeHtml(row.name)" in page
    assert 'escapeHtml(money(row.amount)) + " \\u00b7 due "' in page
    assert "escapeHtml(ordinal(row.day_of_month))" in page
    assert "function ordinal(day)" in page
    # There is no toggle: marking paid without a transaction, and any undo, have no UI path at all.
    assert "data-commit-paid=" not in page
    assert "toggleCommitmentPaid" not in page
    assert '"/paid?month=" +' not in page, "DELETE /commitments/.../paid must have no caller"
    assert "Marked unpaid." not in page
    # A paid bill paints a plain label and no Pay button; an unpaid one paints Pay.
    row_html = page[page.index("function commitmentRowHtml(row)"):page.index("// The one line under the title")]
    assert "var paid = !!row.paid;" in row_html
    assert '\'<span class="commit-paid is-on">Paid</span>\'' in row_html
    assert "data-commit-pay=" in row_html
    assert row_html.index("paid\n") < row_html.index("data-commit-pay="), "Pay lives in the unpaid branch"
    # the inline form posts exactly what the API takes, after checking all three
    add = page[page.index("async function addCommitment("):page.index("// One delegated handler")]
    assert "body: JSON.stringify({ name: name, amount: amount, day_of_month: day })" in add
    assert "amount <= 0" in add and "day >= 1 && day <= 31" in add
    for element in ('id="commitName"', 'id="commitAmount"', 'id="commitDay"', 'id="commitAddBtn"'):
        assert element in page, element
    # a pause is visible and has no Pay button, so the list never lies about what it can do
    assert ".commit-row.is-off .commit-name, .commit-row.is-off .commit-meta" in page
    assert "active ? \"\" : \" \\u00b7 paused\"" in page


def test_pay_is_an_add_sheet_save_and_the_mark_comes_after_it(client: TestClient) -> None:
    """Pay opens the Add sheet prefilled; the paid mark is a second call, made only once the save lands.

    The order is the whole point: a bill must never be marked paid because a POST /transactions failed.
    The month is captured at Pay time because the transaction may land in a different month.
    """
    page = client.get("/").text
    pay = page[page.index("function payCommitmentFlow(row)"):page.index("// The second half of Pay")]
    for field in ("merchant: row.name", "amount: row.amount", 'category: "bills"', 'type: "expense"'):
        assert field in pay, field
    assert "month: state.month" in pay, "the month must be captured when Pay is tapped"
    # A paid/paused row and a second tap while the Pay sheet is already open do nothing: one flow, one save.
    assert "if (row.paid || row.active === false) return;" in pay
    assert "if (payCommitment) return;" in pay
    # openAddSheet takes the prefill, and a plain open still starts on the chooser
    assert "function openAddSheet(prefill)" in page
    assert page.count('showAddView("chooser")') == 2
    opened = page[page.index("function openAddSheet("):page.index("// Pay hands the sheet")]
    assert 'if (prefill) { applyAddPrefill(prefill); showAddView("manual"); }' in opened
    prefill = page[page.index("function applyAddPrefill("):page.index("function closeAddSheet(")]
    assert 'addCategory = prefill.category || "bills";' in prefill
    assert "payCommitment = prefill.commitment || null;" in prefill
    # the mark follows the transaction POST, and a failure says which half failed
    save = page[page.index("async function saveAdd("):page.index("/* ---------- transaction sheet")]
    assert save.index('api("/transactions", {') < save.index("if (paying) await markCommitmentPaid(paying);")
    assert "var paying = payCommitment;" in save
    assert "Transaction saved, but marking it paid failed." in page
    # The mark itself still posts the month captured at Pay time, then repaints the list so the row
    # becomes the non-interactive Paid label.
    mark = page[page.index("async function markCommitmentPaid(paying)"):page.index("async function addCommitment(")]
    assert 'api("/commitments/" + encodeURIComponent(paying.id) + "/paid"' in mark
    assert "body: JSON.stringify({ month: paying.month })" in mark
    assert 'loadCommitments()' in mark


def test_a_pay_that_finds_the_bill_already_charged_carries_on_to_the_mark(
    client: TestClient,
) -> None:
    """A 409 on a Pay is not an error: the expense is there, so the flow goes on to the mark.

    Paying is two writes — the expense and the paid mark — and the guard on the server (one bill,
    one expense, one month) answers 409 with the row that is already saved. The user must not be
    shown a failure for a bill that is in fact already paid, so the 409 takes the same path as a
    successful save: the sheet closes, the mark is made, and the toast says what happened.
    """
    page = client.get("/").text
    save = page[page.index("async function saveAdd("):page.index("/* ---------- transaction sheet")]
    branch = save[save.index("if (duplicate && paying) {"):save.index("// Always say what went wrong")]
    assert "closeAddSheet();" in branch, "the sheet closes as a saved one does"
    assert "await markCommitmentPaid(paying);" in branch, "the mark is the half that is still missing"
    assert 'afterAdd(error.transaction, "Already recorded. Marked as paid.");' in branch
    # The row that is already there is the one the list repaints, so the row is flashed, not a ghost.
    assert "error.transaction" in branch
    # And no error card: the 409 for a Pay never reaches the notice.
    assert "showAddNotice" not in branch
    # The plain duplicate (a scan of the same receipt) still shows the card, as it always did.
    assert 'showAddNotice(duplicate ? resultCard(error.transaction, true)' in save


def test_settings_money_sits_above_account(client: TestClient) -> None:
    """Opening balance and budget save one field at a time; commitments opens the one sheet."""
    page = client.get("/").text
    assert 'id="moneySection"' in page
    assert page.index('id="moneySection"') < page.index(">Account<"), "Money sits above Account"
    for element in ('id="openingBalance"', 'id="monthlyBudget"', 'id="commitmentsBtn"',
                    'id="commitmentsValue"'):
        assert element in page, element
    # text + inputmode: a number input brings an iOS wheel and spinners this screen does not want
    for field in ("openingBalance", "monthlyBudget"):
        tag = opening_tag(page, 'id="' + field + '"')
        assert 'type="text"' in tag and 'inputmode="decimal"' in tag, field
    field = page[page.index(".setting-field {"):page.index("}", page.index(".setting-field {"))]
    assert "font-size: 16px" in field, "below 16px iOS zooms the page on focus"
    # saves on change, one field at a time, then re-reads the card
    assert 'addEventListener("change", function () { saveMoneySetting("opening"); })' in page
    assert 'addEventListener("change", function () { saveMoneySetting("budget"); })' in page
    assert 'body[field === "budget" ? "monthly_budget" : "opening_balance"] = parsed;' in page
    assert "refreshFinanceCard();" in page
    # currency is info-only, and it lives in Money now rather than About
    money = page[page.index('id="moneySection"'):page.index(">Account<")]
    assert ">Currency<" in money and ">MYR<" in money
    assert ">Currency<" not in page[page.index(">About<"):]
    # the card's Details and the Settings row open the same sheet
    assert 'addEventListener("click", openCommitSheet)' in page


def test_an_unreadable_month_is_never_painted_as_owing_nothing(client: TestClient) -> None:
    """A failed read must not be stated as a fact about the user's month.

    Live showed it: schema 0002 has no commitments tables, so GET /commitments answered 500, and the
    sheet read "October 2026 · nothing still due" over its own error card while Settings → Money read
    "None" — two claims about money that was never read.
    """
    page = client.get("/").text
    sub = page[page.index("function paintCommitSub()"):page.index("function renderCommitments()")]
    assert "if (commitError) {" in sub
    assert "could not be read" in sub
    assert "if (commitRows === null) {" in sub, "nothing read yet: claim nothing about what is due"
    assert "nothing still due" in sub, "the read answer is still the one that says it"
    setting = page[page.index("function paintCommitmentsSetting()"):page.index("/* ---------- settings: money")]
    assert 'if (commitError) { value.textContent = "Could not be read"; return; }' in setting
    assert "if (commitRows === null)" in setting
    assert 'value.textContent = active ? active + " monthly" : "None";' in setting


def test_the_commitment_form_keeps_the_16px_floor(client: TestClient) -> None:
    """Its three fields reuse .add-field (16px) and both numbers ask for the right phone keyboard."""
    page = client.get("/").text
    form = page[page.index('<div class="commit-form" id="commitForm" hidden>'):page.index('<div class="overlay" id="addOverlay"')]
    assert form.count('class="add-field"') == 3
    assert 'id="commitAmount" type="text" inputmode="decimal"' in form
    assert 'id="commitDay" type="text" inputmode="numeric"' in form


def test_add_commitment_is_a_button_and_the_form_opens_on_it(client: TestClient) -> None:
    """The form is closed until "+ Add commitment" is tapped; a second tap closes it again."""
    page = client.get("/").text
    assert 'id="commitNewBtn" type="button" aria-expanded="false"' in page
    assert 'aria-controls="commitForm">+ Add commitment</button>' in page
    assert '<div class="commit-form" id="commitForm" hidden>' in page
    assert ">Add a commitment<" not in page, "the old title is replaced by the button"
    # the button is delegated like the rest of the sheet, and toggles the hidden form
    assert "#commitNewBtn" in page[page.index("function handleCommitClick("):page.index("function handleCommitClick(") + 400]
    toggle = page[page.index("function toggleCommitForm(button)"):page.index("function handleCommitClick(")]
    assert '$("commitForm").hidden = !opening;' in toggle
    assert 'button.setAttribute("aria-expanded", opening ? "true" : "false");' in toggle
    # a 44px target, and its own rule so it is not a stretched add button
    assert ".commit-new { display: block; min-height: 44px;" in page


def test_the_day_column_fits_its_placeholder(client: TestClient) -> None:
    """"Day 1-31" is 63.25px at 16px; the 12px padding either side leaves 51px at 76px wide, so it was cut.

    The column is 96px: 71px of text room, enough for the placeholder with a margin.
    """
    page = client.get("/").text
    assert ".commit-form-row { display: grid; grid-template-columns: 1fr 96px auto; gap: 8px; }" in page
    assert 'placeholder="Day 1-31"' in page


def test_the_paid_label_centres_its_text_like_pay(client: TestClient) -> None:
    """The Paid label is a span: it must be a flex box, or its text sits 8.75px high at 375px.

    Measured in the harness (desktop DOM, row of 58px): text midline 1035.87 against box midline 1044.62.
    """
    page = client.get("/").text
    rule = page[page.index(".commit-paid, .commit-pay {"):page.index("}", page.index(".commit-paid, .commit-pay {"))]
    assert "display: inline-flex; align-items: center; justify-content: center;" in rule
    assert "height: 36px;" in rule


def test_the_new_controls_have_no_inline_handlers(client: TestClient) -> None:
    """The CSP has no 'unsafe-inline': an inline handler would not run, so none may exist."""
    page = client.get("/").text
    assert not re.search(r"\son(click|change|input|submit|pointerdown)\s*=", page)


def test_no_overlay_or_sheet_rule_carries_opacity(client: TestClient) -> None:
    """A sheet must never be tinted: opacity on it, or on an ancestor that animates, is a group opacity.

    The phone taught us this one. The dim belongs to .scrim, and the sheet animates transform only. This
    walks every rule whose *subject* is the overlay or the sheet itself — never a child of it — and
    refuses an opacity declaration there.
    """
    page = client.get("/").text
    css = page[page.index("<style"):page.index("</style>")]
    subject = re.compile(
        r"^[.#](overlay|sheet|addOverlay|addSheet|txnOverlay|txnSheet|monthOverlay|wheelSheet|"
        r"commitOverlay|commitSheet)(?:[.:\[]|$)"
    )
    checked = 0
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for selector in selectors.split(","):
            target = re.split(r"[ >+~]+", selector.strip())[-1]   # the subject: after the last combinator
            if not subject.match(target):
                continue
            checked += 1
            assert "opacity" not in body, f"{selector.strip()} carries opacity"
    assert checked >= 6, "the overlay and sheet rules were not found"


def test_smart_entry_is_one_row_until_it_is_opened(client: TestClient) -> None:
    """The AI view opens on a single Smart Entry row; the field and Add sit behind it, hidden until tapped.

    The row is the same .add-row Scan Receipt uses, so the two read as one list. Opening it shows the
    field and the existing Add button, and closing it hides them again. Every open of the sheet starts shut.
    """
    page = client.get("/").text
    row = page[page.index('<div class="smart-card" id="smartEntry">'):page.index('<div class="add-rows">')]
    assert '<button class="add-row" id="smartEntryBtn" type="button" aria-expanded="false"' in row
    assert 'aria-controls="smartEntryBody">' in row
    assert "Smart Entry</span>" in row
    assert 'class="add-row-chev"' in row, "the chevron says there is more behind the row"
    assert '<path d="M13 2.8 4.8 13.4h6.2L10.6 21.2l8.2-10.6h-6.2L13 2.8Z"/>' in row, "the bolt is the icon"
    # the body is hidden on the markup, and holds the field and the existing Add button
    body = row[row.index('<div class="smart-card-body" id="smartEntryBody" hidden>'):]
    assert 'id="textInput"' in body and 'id="textBtn"' in body
    assert "smart-card-head" not in page, "the old head row is gone"
    # the one-row shape is the same .add-row Scan Receipt uses, with an 80px minimum, and the body is a card
    assert ".smart-card-body { margin-top: 8px; padding: 14px; border-radius: 16px; background: var(--card-2); }" in page
    assert ".add-row {\n    width: 100%; min-height: 80px;" in page
    # the field and the Add button are touch targets: 44px, with the field still on 16px
    assert ".smart-card-row .add-field { flex: 1; min-width: 0; min-height: 44px; }" in page
    assert "min-width: 64px; min-height: 44px; padding: 0 18px; font-size: 16px;" in page
    # open and close: one function sets the button, the body and the caret, and a tap on the row calls it
    toggle = page[page.index("function setSmartEntryOpen(open)"):page.index("async function submitText()")]
    assert '$("smartEntryBody").hidden = !open;' in toggle
    assert 'button.setAttribute("aria-expanded", open ? "true" : "false");' in toggle
    assert 'button.classList.toggle("is-open", open);' in toggle
    assert 'if (open) focusWithoutScroll($("textInput"));' in toggle
    assert '$("smartEntryBtn").addEventListener("click", function () {' in page
    assert 'setSmartEntryOpen($("smartEntryBody").hidden);' in page
    # every open of the sheet starts with the row shut
    opened = page[page.index("function openAddSheet(prefill)"):page.index("// Pay hands the sheet")]
    assert "setSmartEntryOpen(false);" in opened


def test_the_income_and_expense_labels_are_the_two_words(client: TestClient) -> None:
    """Income and Expenses are the labels, with their icons; the month is named by the header picker."""
    page = client.get("/").text
    assert 'stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 19V5"/><path d="M6 11l6-6 6 6"/></svg>Income</span>' in page
    assert 'stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 5v14"/><path d="M6 13l6 6 6-6"/></svg>Expenses</span>' in page
    assert "this month</span>" not in page[page.index('<div class="stat-row">'):page.index('<div class="card budget-card"')]


def test_the_name_merchant_and_note_inputs_keep_autocomplete_off(client: TestClient) -> None:
    """The commitment name, the Merchant and the Note never offer a browser's remembered entries.

    The three already carried autocomplete="off" when this was checked, so this pins what is there and
    stops it from being dropped. It says nothing about how iOS treats the attribute on a phone.
    """
    page = client.get("/").text
    for element in ('id="commitName"', 'id="addMerchant"', 'id="addNote"'):
        tag = page[page.index(element) - 60:page.index(">", page.index(element)) + 1]
        assert 'autocomplete="off"' in tag, element


def test_the_manual_sheet_is_one_screen_with_a_four_row_card(client: TestClient) -> None:
    """Manual is one screen, top to bottom, in the reference order.

    Type and Back, the amount and its currency, the category row, then the four-row card: Merchant, Date,
    Mode and Note. The Details step is gone, and every field it held sits on this screen. Only the middle
    of the sheet can scroll; the keypad is the sheet's footer and never moves.
    """
    page = client.get("/").text
    assert "65dvh" not in page and "65%" not in page, "the sheet is full height now"
    assert "showManualStep" not in page and "manualStep" not in page, "the two steps are gone"
    assert "addDetailsPill" not in page and "addBackDetails" not in page
    manual = page[page.index('<section id="screen-add" hidden>'):page.index("<!-- 3. AI")]
    order = [manual.index(marker) for marker in (
        'id="addBackManual"', 'id="addTypeToggle"', 'id="addAmount"',
        'class="add-cat-head"', 'id="addChips"', 'class="add-card"')]
    assert order == sorted(order), "the rows must read top to bottom in the reference order"
    assert 'class="manual-body sheet-scroll" id="manualBody"' in manual
    assert 'class="add-caret"' in manual and ">Category<" in manual
    assert "Malaysian Ringgit" not in page and "add-currency" not in page, "the currency pill is gone"
    card = manual[manual.index('class="add-card"'):]
    for label in (">Merchant<", ">Date<", ">Mode<", ">Note<"):
        assert label in card, label
    for element in ('id="addMerchant"', 'id="addDate"', 'id="addModeToggle"', 'id="addNote"'):
        assert element in card, element
    assert "Scan Receipt" not in manual, "Scan Receipt stays in the AI view"
    assert 'data-add-mode="personal"' in manual and 'data-add-mode="business"' in manual
    # touch targets: the controls are 44px, and the inputs keep the 16px floor
    assert ".add-type .seg-btn { min-height: 44px; }" in page
    assert ".add-back-icon {\n    flex: none; width: 44px; height: 44px;" in page
    assert "min-height: 44px; padding: 0 16px 0 12px;" in page, "the category chips are 44px"
    assert "font: inherit; font-size: 16px; color: var(--text-2);" in page
    # Back sits beside the type control; the Details pill and its step are not in the markup any more
    back = manual[manual.index('class="add-back-icon"'):manual.index('id="addTypeToggle"')]
    assert "add-back-icon" in back and 'aria-label="Back to the chooser"' in back
    # the chip row is a momentum scroller with a hidden scrollbar, and the chosen chip is scrolled into
    # view with part of the previous chip showing (0 when it already fits the first screen)
    chips = page[page.index("  .chip-scroll {"):page.index("  .chip-scroll {") + 260]
    assert "overflow-x: auto" in chips and "-webkit-overflow-scrolling: touch" in chips
    assert "scrollbar-width: none" in chips
    assert "function revealAddChip() {" in page
    assert "revealAddChip();" in page[page.index("function paintAddChips()"):page.index("function revealAddChip()")]
    reveal = page[page.index("function revealAddChip()"):page.index("function paintAddToggle(")]
    assert 'row.scrollLeft = 0;' in reveal and "row.scrollLeft +=" in reveal
    # the Mode row keeps its height; its toggle is a rounded track whose selected segment paints a
    # pill inside the track, while every segment's tap box stays 44px
    row_rule = page[page.index("  .add-row-field {"):page.index("  .add-row-field {") + 160]
    assert "min-height: 44px" in row_rule, "the Mode row is at least 44px tall"
    mode_rule = page[page.index("  .add-mode {"):page.index("  .add-mode {") + 240]
    assert "height: 32px" in mode_rule, "the track reads 32px tall"
    assert "border-radius: 9999px" in mode_rule, "the Mode control is a rounded container"
    assert "background: var(--control)" in mode_rule, "the track uses the segmented-control fill"
    mode_btn = page[page.index("  .add-mode .seg-btn {"):page.index("  .add-mode .seg-btn::after {")]
    assert "min-height: 44px" in mode_btn, "each segment keeps the 44px tap floor"
    assert ".add-mode .seg-btn.is-active { background: none; box-shadow: none; }" in page
    assert (".add-mode .seg-btn.is-active::after { background: var(--seg-selected); "
            "box-shadow: var(--seg-shadow); }") in page, "the selected pill paints inside the track"
    # Merchant asks iOS for no underline suggestions, and stays a 16px text field
    merchant = manual[manual.index('id="addMerchant"') - 40:manual.index('id="addMerchant"') + 220]
    assert 'spellcheck="false"' in merchant and 'autocorrect="off"' in merchant
    assert 'autocapitalize="words"' in merchant and 'type="text"' in merchant
    # the keypad hides while Merchant or Note holds the caret, and only then
    keys = page[page.index("function updateKeypadVisibility()"):page.index("function keypadHtml()")]
    assert "$(\"addKeypad\").hidden = !(addView === \"manual\" && !manualFieldFocused);" in keys
    assert 'manualFieldFocused = true; updateKeypadVisibility();' in page
    assert 'manualFieldFocused = false; updateKeypadVisibility();' in page
    # the prefilled Pay sheet fills the merchant in the card, for the user to check
    prefill = page[page.index("function applyAddPrefill("):page.index("function closeAddSheet(")]
    assert '$("addMerchant").value = prefill.merchant || "";' in prefill
    # the sheet is still a registered overlay: it opens with openOverlay and swipes with attachSheetDrag
    assert 'openOverlay($("addOverlay"));' in page
    assert 'attachSheetDrag("addSheet", "addOverlay", closeAddSheet, false);' in page


def test_the_manual_save_sends_one_payload_whether_or_not_there_is_a_note(client: TestClient) -> None:
    """The note always travels under its key, as null when blank, so the payload's keys never change.

    A note is stored as raw_extraction.note by the API (there is no column for it). Nothing here adds a key
    or a shape: the eight keys below are the whole body with or without a note, and `commitment_id` is
    null unless the save is the Pay flow's (`paying` holds that link). The browser side of the
    same check is run on the harness, where the two bodies are captured and compared.
    """
    page = client.get("/").text
    save = page[page.index("async function saveAdd("):page.index("/* ---------- transaction sheet")]
    body = save[save.index("body: JSON.stringify({"):]
    body = body[:body.index("})")]
    keys = re.findall(r"^\s+(\w+):", body, flags=re.M)
    assert keys == [
        "amount", "txn_date", "merchant", "category", "type", "mode", "note", "commitment_id"
    ]
    assert 'note: $("addNote").value.trim() || null' in save
    assert 'commitment_id: paying ? paying.id : null' in save, "the Pay flow's link; none on a plain save"
    assert 'api("/transactions", {' in save and 'method: "POST"' in save
    # currency is not one of them and never was: the browser sends no currency key, the API stamps MYR
    # (models.TransactionCreate.to_row), so removing the sheet's currency pill changed no payload key.
    assert "currency" not in save


def test_view_all_and_the_category_sheet_are_gone(client: TestClient) -> None:
    """The CATEGORY row is a label alone: View All and the sheet it opened are removed, code and all."""
    page = client.get("/").text
    for gone in ("View All", "addCatViewAll", "catOverlay", "catSheet", "catList", "catDoneBtn",
                 "openCatSheet", "closeCatSheet", "paintCatList", "pickCategory", "cat-row-check"):
        assert gone not in page, gone + " is still in the page"
    head = page[page.index('class="add-cat-head"'):page.index('id="addChips"')]
    assert 'class="add-label">Category</span>' in head and "<button" not in head, "a label, not a link"


def test_the_chips_show_every_category_in_one_scrolling_row(client: TestClient) -> None:
    """The category row is one horizontal strip of the app's own categories, in their own order."""
    page = client.get("/").text
    assert "var CATEGORIES = [\"food\", \"transport\", \"groceries\", \"bills\", \"shopping\", \"health\"," in page
    chips = page[page.index("function paintAddChips()"):page.index("function paintAddToggle(")]
    assert "CATEGORIES.map(" in chips and "categoryIcon(category)" in chips
    assert 'class="cat-chip' in chips and "is-on" in chips
    strip = page[page.index("  .chip-scroll {\n"):page.index("  .chip-scroll {\n") + 300]
    assert "overflow-x: auto" in strip and "scrollbar-width: none" in strip, "one row, scrollbar hidden"
    assert ".cat-chip.is-on { background: var(--accent); color: var(--on-accent); }" in page


def test_the_keyboard_lifts_the_sheet_and_centres_the_focused_field(client: TestClient) -> None:
    """The sheet measures the keyboard from visualViewport, lifts by it, and centres the field in itself.

    iOS changes only the visual viewport when the keyboard opens, so the height is innerHeight minus the
    visual viewport (and whatever it scrolled by). The value goes into --kb, which lifts every sheet's
    bottom edge and clamps its max-height. The focused field is then centred by scrolling the sheet's own
    box, never the window. No fixed pixels are pinned: the height is whatever the phone reports.
    """
    page = client.get("/").text
    # the height is measured, kept in one place, and driven by two viewport events
    assert "window.visualViewport" in page
    assert "var lost = window.innerHeight - viewport.height - viewport.offsetTop;" in page
    assert 'viewport.addEventListener("resize", function () {' in page
    assert 'viewport.addEventListener("scroll", paintKeyboard);' in page
    assert "function paintKeyboard() {" in page
    assert 'document.documentElement.style.setProperty("--kb", keyboardInsetPx + "px");' in page
    # it resets when the sheet closes, and the close is the one choke point every sheet goes through
    assert "function resetKeyboard() {" in page
    assert 'document.documentElement.style.setProperty("--kb", "0px");' in page
    closing = page[page.index("function closeOverlay("):page.index("function closeOverlay(") + 300]
    assert "resetKeyboard();" in closing
    # --kb lifts the bottom edge and clamps the height, in dvh, for both fixed sheets
    assert "--kb: 0px;" in page
    assert "bottom: var(--kb);" in page
    assert "max-height: calc(100dvh - var(--sheet-top-gap) - var(--kb));" in page
    assert "padding: max(var(--sat), 12px) 12px calc(12px + var(--sab) + var(--kb));" in page
    assert "max-height: min(88dvh, calc(100dvh - max(var(--sat), 12px) - 12px - var(--sab) - var(--kb)));" in page
    # no static-viewport height is left in the sheet rules (the sign-in card's own 10vh shift is not one)
    regions = [
        page[page.index("/* ---------- add sheet: one screen"):page.index("/* ---------- results ----------")],
        page[page.index("/* ---------- sheet ---------- */"):page.index("/* ---------- commitments sheet")],
        page[page.index("/* ---------- sheets: how the balance"):page.index("/* ---------- category list")],
    ]
    for region in regions:
        plain = re.sub(r"/\*.*?\*/", "", region, flags=re.S)
        assert not re.search(r"\d+vh(?![\w-])", plain.replace("dvh", "D").replace("svh", "S").replace("lvh", "L")), (
            "a sheet height still follows the static viewport"
        )
    # the centring scrolls the sheet's own box only, after the keyboard has had time to settle
    centre = page[page.index("function centreFocusedField()"):page.index("function resetKeyboard()")]
    assert 'var scroller = field.closest(".sheet-scroll") || field.closest(".sheet");' in centre
    assert "scroller.scrollTop +=" in centre
    assert "window.scroll" not in centre and "documentElement.scrollTop" not in centre
    assert "centreTimer = setTimeout(centreFocusedField, 300);" in page
    # focus is the trigger, by delegation, and it still keeps the page from panning to "help"
    assert 'document.addEventListener("focusin", function (event) {' in page
    assert 'field.matches("input, textarea, select")' in page
    assert 'field.closest(".sheet")' in page
    assert 'field.classList.contains("add-date-input")' in page
    assert "function watchKeyboard() {" in page
    assert "field.focus({ preventScroll: true })" in page


def test_the_manual_amount_block_keeps_its_air(client: TestClient) -> None:
    """The amount block keeps 12-16px of air a side and the figure's size never follows the phone.

    What a test can pin: the block grows only up to 16px of air a side (96px at the 64px figure) with a
    56px floor, the figure is clamped 56-64px, the RM is a share of the figure (em), and the figure is
    shrunk by fitAddAmount() for a long value, which runs wherever the figure is painted and when Manual
    is shown (it measures 0 while hidden). The height the capped keypad leaves over is shared out between
    the blocks in .manual-body rather than pooled in one band, so the rows breathe.
    """
    page = client.get("/").text
    assert ".add-amount-block {\n    flex: 0 1 auto; min-height: 56px; max-height: 96px;" in page
    assert "justify-content: space-between;" in page[page.index("  .manual-body {"):page.index("  .manual-body::-webkit-scrollbar")], (
        "the spare height is spread between the blocks, not pooled in one band"
    )
    assert "justify-content: center; padding: 14px 0;" in page, "12-16px of air above and below the figure"
    amount = page[page.index(".add-amount {\n"):page.index(".add-amount-cur {")]
    assert "font-size: clamp(56px, 8dvh, 64px)" in amount, "the figure is 56-64px"
    assert "font-size: .38em" in page[page.index(".add-amount-cur {"):page.index(".add-amount-cur {") + 120]
    assert "function fitAddAmount()" in page
    paint = page[page.index("function paintAddAmount()"):page.index("function paintAddAmount()") + 220]
    assert "fitAddAmount();" in paint, "every paint of the figure refits it"
    show = page[page.index("function showAddView(view)"):page.index("function updateKeypadVisibility()")]
    assert "fitAddAmount();" in show, "Manual refits when it is shown"
    assert 'window.addEventListener("resize", fitAddAmount);' in page
    assert "@media (max-width: 360px) { .add-amount" not in page, "the narrow-phone size is the fit's job now"


def test_the_ai_option_boxes_are_tall_touch_targets(client: TestClient) -> None:
    """Both AI option boxes are at least 44px tall (80px here), and the sheet is content height.

    The sheet is compact for the chooser and the AI view alike, so its height follows what it holds; only
    Manual takes the full height. The title reads "Add with AI" so it no longer repeats the first row.
    """
    page = client.get("/").text
    rule = page[page.index("  .add-row {\n"):page.index("  .add-row {\n") + 200]
    height = int(re.search(r"min-height: (\d+)px", rule).group(1))
    assert height >= 44, "an AI option box is a touch target"
    for row in ('<button class="add-row" id="smartEntryBtn"', '<button class="add-row" id="scanBtn"'):
        assert row in page, row
    assert page.count('class="add-option-sub"') == 2, "one muted line under each option title"
    assert '"Add with AI"' in page and 'ai: "Add with AI"' in page
    assert "#addSheet.is-compact #screen-ai" in page, "the AI view hugs its content too"
    assert '$("addSheet").classList.toggle("is-compact", view !== "manual");' in page


def test_the_keypad_keys_are_a_fixed_58px(client: TestClient) -> None:
    """The Manual keypad sizes to its content: four rows of exactly 58px, nothing stretches.

    The height lives on the grid's row template and on the key itself, both a flat 58px — no minmax, no
    min-height, no flex-grow — so 4x58 + 3x8 = 256px of grid whatever the sheet's height is, and the
    panel has no max-height to fill. The digits are 28px medium, the gaps are 8px, and the panel keeps
    the card's 16px side inset so the outer keys line up with the rows above. On a short sheet the rows
    pin to 48px, still above the 44px tap floor. The keypad still hides while Merchant or Note holds the
    caret.
    """
    page = client.get("/").text
    grid = page[page.index("  #addKeypad .keypad-grid {\n"):page.index("  #addKeypad .key { height: 58px;")]
    assert "grid-template-rows: repeat(4, 58px)" in grid, "four fixed 58px rows"
    assert "grid-auto-rows: 58px" in grid, "any extra row is 58px too, never stretched"
    assert "gap: 8px" in grid, "8px between keys, both axes"
    assert "flex: none" in grid, "the grid never grows past its rows"
    assert "minmax" not in grid and "min-height" not in grid, "no flexible row sizing left"
    assert "#addKeypad .key { height: 58px; font-size: 28px; font-weight: 500; }" in page
    panel = page[page.index("  #addKeypad {"):page.index("  #addKeypad .keypad-grid {")]
    assert "padding: 2px 16px calc(2px + var(--sab))" in panel, "the keys share the card's 16px inset"
    assert "max-height" not in panel, "the panel has no cap to fill or stretch into"
    assert 'grid-template-rows: repeat(4, 48px)' in page, "a short sheet pins 48px rows"
    assert '$("addKeypad").hidden = !(addView === "manual" && !manualFieldFocused);' in page


def test_a_validation_error_names_the_field_it_is_about(client: TestClient) -> None:
    """A 422 from FastAPI carries `detail` as a list of { loc, msg }, and the page must read it.

    Before this, the list was skipped, so a rejected save showed "Something went wrong (422)." and hid the
    field. The message now names the last part of `loc` and says why, e.g. "commitment_id: Extra inputs
    are not permitted". Both the list and the string/object shapes stay read.
    """
    page = client.get("/").text
    start = page.index("async function toApiError(response) {")
    fn = page[start:page.index("\n  }\n", start) + 4]
    assert "Array.isArray(detail)" in fn, "FastAPI's 422 detail is a list"
    assert "loc[loc.length - 1]" in fn, "the field is the last part of loc"
    assert '(field ? field + ": " : "") + (first.msg || "")' in fn, "field, then why"
    assert 'typeof detail === "string"' in fn, "a plain string detail still reads"
    assert "!Array.isArray(detail)" not in fn, "the object branch no longer skips lists"


def test_the_whats_new_sheet_is_three_screens_with_a_dot_and_a_way_out(client: TestClient) -> None:
    """The sheet has three screens, a dot for each, and Skip and Next (then Got it) to leave it.

    The dots are painted from the same list the screens come from, so the count can never drift: the
    pin reads the list out of the page and asks for exactly as many dots as it holds screens.
    """
    page = client.get("/").text
    assert '<div class="overlay" id="whatsNewOverlay" aria-hidden="true">' in page
    assert '<div class="sheet whats-new-sheet" id="whatsNewSheet">' in page
    assert 'id="whatsNewSkipBtn"' in page and 'id="whatsNewNextBtn"' in page
    assert 'id="whatsNewDots"' in page and 'id="whatsNewBody"' in page
    # The screens live in one list, so the dots and the screens cannot disagree.
    block = page[page.index("var WHATS_NEW_SCREENS = ["):page.index("var whatsNewIndex = 0;")]
    assert block.count("title:") == 3, "three screens"
    assert 'class="whats-new-dot' in page
    assert '$("whatsNewNextBtn").textContent = last ? "Got it" : "Next";' in page
    # Every way out writes the version, so a user who dismisses it is never asked again.
    assert "function closeWhatsNew(fromOffset) {" in page
    assert "rememberWhatsNew();" in page
    assert '$("whatsNewSkipBtn").addEventListener("click", closeWhatsNew);' in page
    assert '$("whatsNewNextBtn").addEventListener("click", nextWhatsNew);' in page
    assert 'if (isOutsideTap(event, $("whatsNewOverlay"))) closeWhatsNew();' in page
    assert 'attachSheetDrag("whatsNewSheet", "whatsNewOverlay", closeWhatsNew, false);' in page


def test_the_whats_new_version_is_remembered_per_account(client: TestClient) -> None:
    """The stored version is keyed by the account, so a second account on one device still sees the card.

    The key is "whatsNew:<user id>:lastSeenVersion" and the id is the access token's `sub` claim —
    the same id the API scopes by (auth.users.id). Two accounts are two ids, so the first one reading
    the card cannot hide it from the second. There is no database and no migration: localStorage is
    the whole mechanism, and the value is only ever the version string.
    """
    page = client.get("/").text
    assert 'var WHATS_NEW_VERSION = "2026-10";' in page
    # The old key was shared by everyone on the device, so the second account never saw the card.
    assert '"duits.whatsnew"' not in page
    slot = page[page.index("function whatsNewSlot() {"):page.index("function userIdFromToken(")]
    assert 'return "whatsNew:" + (userId || "anonymous") + ":lastSeenVersion";' in slot
    assert "readSession()" in slot, "the key is built from the signed-in account"
    assert "userIdFromToken(session.access_token)" in slot
    # The id is the token's own `sub` claim, decoded the way the address already is.
    user = page[page.index("function userIdFromToken(token) {"):page.index("function whatsNewActionLabel(")]
    assert "JSON.parse(window.atob(payload)).sub" in user
    assert "String(token).split(\".\")[1]" in user
    # Both the read and the write go through the per-account key, and both are wrapped: storage can
    # fail (private mode), and a failed read means "not seen yet" while a failed write must not throw.
    seen = page[page.index("function whatsNewSeen() {"):page.index("function rememberWhatsNew() {")]
    assert "try {" in seen and "catch (error)" in seen, "the read is wrapped"
    assert "window.localStorage.getItem(whatsNewSlot()) === WHATS_NEW_VERSION" in seen
    remember = page[page.index("function rememberWhatsNew() {"):page.index("function paintWhatsNew() {")]
    assert "try {" in remember and "catch (error)" in remember, "the write is wrapped"
    assert "window.localStorage.setItem(whatsNewSlot(), WHATS_NEW_VERSION)" in remember
    # The sheet still waits for the user to be in, and never opens on a sign-in screen.
    show = page[page.index("function maybeShowWhatsNew() {"):page.index("// One row shape, shared by Home")]
    assert "if (!splashHidden)" in show, "the splash covers the app until it has faded"
    assert "if (!readSession()) return;" in show, "never on a sign-in screen"
    assert 'if ($("authScreen") && !$("authScreen").hidden) return;' in show
    assert 'if (state.screen !== "home") return;' in show
    # It is opened from the two places the user arrives at Home — a fresh sign-in and a restored
    # session — and from nowhere else.
    assert page.count("maybeShowWhatsNew();") == 2, "the two callers, and no third"
    assert "await Promise.all([loadHome(), loadTransactions(), loadInsights()]);" in page


def test_each_whats_new_screen_has_an_action_that_opens_the_sheet_that_exists(
    client: TestClient,
) -> None:
    """Each screen's button opens a sheet the app already has — no new screen is built for the card.

    Balance opens the one-field balance sheet, or the "How this is calculated" breakdown when a
    balance is already set; Commitments opens the commitments sheet with the add form ready; Monthly
    budget opens the one-field budget sheet. The card closes first, so the two sheets are never on
    screen together, and the way the app stacks one sheet on another does it in this order.
    """
    page = client.get("/").text
    block = page[page.index("var WHATS_NEW_SCREENS = ["):page.index("var whatsNewIndex = 0;")]
    assert block.count("action:") == 3, "every screen has an action"
    assert 'action: "balance"' in block
    assert 'action: "commitment"' in block
    assert 'action: "budget"' in block
    # The label, and the one that changes with the state: a balance that is already set has nothing
    # to ask for, so the breakdown is the useful thing.
    label = page[page.index("function whatsNewActionLabel(action) {"):page.index("function runWhatsNewAction()")]
    assert 'openingIsSet(financeSummary) ? "How this is calculated" : "Set my balance"' in label
    assert 'if (action === "commitment") return "Add a bill";' in label
    assert 'return "Set a budget";' in label
    # The action opens the sheets that exist, through their own openers.
    run = page[page.index("function runWhatsNewAction() {"):page.index("// Shown once per version")]
    assert "openMoneyField(\"balance\")" in run
    assert "openBalanceSheet()" in run
    assert "openCommitSheet()" in run
    assert "toggleCommitForm($(\"commitNewBtn\"))" in run, "the add form is open when the sheet is"
    assert "openMoneyField(\"budget\")" in run
    # The card closes before the other sheet opens, so the two are never on screen together.
    assert run.index("closeOverlay(") < run.index("openMoneyField(\"balance\")")
    assert "closeOverlay($(\"whatsNewOverlay\"), function () {" in run
    # The button lives in the body, which is re-rendered on every screen, so the body listens for it.
    assert '$("whatsNewBody").addEventListener("click", function (event) {' in page
    assert 'event.target.closest("#whatsNewActionBtn")' in page
    assert "if (hit) runWhatsNewAction();" in page
    # A 44px target, the app's own secondary button.
    assert 'class="btn-secondary whats-new-action"' in page
    assert "min-height: 44px" in page[page.index(".btn-secondary {"):page.index(".btn-secondary:active")]


def test_settings_has_a_row_that_opens_the_whats_new_card_again(client: TestClient) -> None:
    """Settings > About carries a "What's new" row that opens the card whenever the user wants it.

    The row opens the card even when the stored version says the user has read it: that is the
    difference between the one-shot nudge that appears by itself and a deliberate request. It must
    not write the version on the way in either.
    """
    page = client.get("/").text
    assert 'id="whatsNewBtn"' in page
    about = page[page.index('class="form-label settings-heading">About</h3>'):]
    about = about[:about.index("</div>\n      <p class=\"footnote\">Add to Home Screen")]
    assert 'id="whatsNewBtn"' in about, "the row is in the About section"
    assert "What&rsquo;s new" in about
    # It opens the card directly — not through the once-per-version path.
    assert '$("whatsNewBtn").addEventListener("click", function () { openWhatsNew(); });' in page
    open_call = page[page.index('function openWhatsNew() {'):page.index("// Every way out of the sheet")]
    assert "openOverlay($(\"whatsNewOverlay\"));" in open_call
    assert "rememberWhatsNew" not in open_call, "opening it does not mark the version as read"


def test_the_whats_new_copy_is_the_apps_own_rules(client: TestClient) -> None:
    """The copy states the rules the code computes, in words, in two short sentences per screen.

    Every sentence below is checked against app/finance.py and the UI: safe to spend is the balance
    less the bills still due, a paid bill leaves the budget bar, a paid mark cannot be undone from
    the app, and the bar's own colours are yellow from half used and red at a fifth left. The one
    worked example on screen 1 is a made-up balance and says so.
    """
    page = client.get("/").text
    block = page[page.index("var WHATS_NEW_SCREENS = ["):page.index("var whatsNewIndex = 0;")]
    # Two short sentences per screen: the copy is read at a glance, not studied.
    for screen in block.split("title:")[1:]:
        lines = screen[screen.index("lines: ["):screen.index("action:")]
        assert lines.count('",\n') + 1 == 2, "two sentences per screen"
    # The rules, as app/finance.py computes them.
    assert "Balance is your starting balance plus income, minus expenses." in block
    assert "If you had RM1,700, spent RM900 and had no unpaid bills, safe to spend would be RM800." in block
    assert "Safe to spend drops the bills you have not paid yet" in block
    # The Pay flow: the expense first, then the mark, and the mark is for the month.
    assert "Pay one to record the expense and mark the bill paid for the month." in block
    assert "Once a bill is paid it stays paid" in block
    # The budget screen, as the user asked for it.
    assert "Set a limit for daily spending like food and fuel." in block
    assert "Bills you pay through Duits don't count against it." in block
    assert "The bar turns yellow at half used, and red when 20% is left." in block
    # The bar's own colours, in the code the copy describes (budgetTone).
    assert 'if (left < 0 || pct >= 80) return "danger";' in page
    assert 'return pct >= 50 ? "caution" : "";' in page
    # The separate formula box is gone: one card, one set of sentences.
    assert "whats-new-formula" not in page
    assert "formula:" not in block


def test_the_whats_new_screens_are_cards_not_floating_text(client: TestClient) -> None:
    """Each screen is a card, the same recipe the rest of the app is built from.

    The sheet is white in the light theme, so bare text on it reads as floating text rather than as a
    screen. The card's own hairline and shadow are what separate it, and they are the app's `.card`.
    """
    page = client.get("/").text
    card = page[page.index("  .whats-new-screen {"):page.index("  .whats-new-screen h3 {")]
    assert "background: var(--card-2);" in card
    assert "border: .5px solid var(--line);" in card
    assert "border-radius: var(--r-md);" in card
    assert "box-shadow: var(--shadow);" in card
    assert "padding: 16px;" in card


def test_the_safe_to_spend_info_mark_asks_the_card_it_sits_on(client: TestClient) -> None:
    """The (i) beside "Safe to spend" is decoration inside the card's own button.

    The whole balance card is one button that opens the "How this is calculated" sheet, so the mark
    carries no name of its own and has no handler: a button inside a button is invalid, and a second
    control for the same sheet would be a target the app does not otherwise have.
    """
    page = client.get("/").text
    assert '<span class="safe-pill-info" aria-hidden="true">i</span>' in page
    assert 'id="balanceTap"' in page
    # It sits inside the button, between the label and the figure.
    pill = page[page.index('<span class="safe-pill" id="safePill">'):page.index('</span>', page.index('id="safeAmount"'))]
    assert "safe-pill-label" in pill and "safe-pill-info" in pill
    assert pill.index("safe-pill-label") < pill.index("safe-pill-info") < pill.index("safe-pill-amount")
    # No handler of its own, and no second way into the sheet.
    assert "safe-pill-info" not in page[page.index("function wire() {"):]
    assert '$("balanceTap").addEventListener("click", openBalanceSheet);' in page
