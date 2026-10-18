"""The app icon: served publicly at every name iOS probes, opaque, and cache-busted.

The PNGs are inspected with the standard library (the IHDR chunk is 13 fixed bytes) so the tests
need no image dependency: what matters is that the files carry no alpha channel — iOS paints
transparency black on the Home Screen — that each is the square size its slot expects, and that the
page asks for them with a version query, because iOS keys its cached Home Screen icon on the URL.
"""

from __future__ import annotations

import re
import struct
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
    assert '$("addKeypad").hidden = view !== "manual";' in page
    assert '$("saveAddBtn").hidden = view !== "manual";' in page


def test_the_chooser_is_a_compact_two_card_grid(client: TestClient) -> None:
    """Two square cards side by side on a sheet that hugs them, until a flow is chosen.

    The chooser used to be two thin full-width rows at the top of a full-height sheet, which left most
    of the sheet blank. What markup and CSS can pin down here: the grid is two columns with a 12px gap,
    each card is one button carrying a badge, a bold label and a wrapping sub-label and no chevron
    (there is nowhere to go sideways), the rows that do open something keep theirs, and the sheet is
    compact only while the chooser is up — never a size container in that state, because `contain: size`
    would collapse an auto-height box.
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
    assert '$("addSheet").classList.toggle("is-compact", view === "chooser");' in page


def test_each_flow_returns_to_the_chooser_and_cancel_leaves_the_sheet(client: TestClient) -> None:
    """Back is inside each flow; Cancel stays in the header and still closes the sheet from every view."""
    page = client.get("/").text
    assert 'id="addBackManual"' in page and 'id="addBackAi"' in page, "one Back per flow"
    assert page.count('addEventListener("click", reverseAddView)') == 2, "both Backs are wired"
    assert 'addEventListener("click", function () { showAddView("manual"); })' in page
    assert 'addEventListener("click", function () { showAddView("ai"); })' in page
    assert 'id="closeAddBtn"' in page
    assert '$("closeAddBtn").addEventListener("click", closeAddSheet);' in page
    assert page.count('isOutsideTap(event, $("') == 4, "the scrim still closes the sheet"
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
    assert "if (sheet.scrollTop > 0) return;" in page
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
    assert page.count("isOutsideTap(event, $(") == 4, "all four overlays must use the guard"


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


# ---------------------------------------------------------------- money: the card, the sheet, the settings

def test_home_carries_a_safe_to_spend_card_above_the_hero(client: TestClient) -> None:
    """The balance minus the commitments still due, above "Spent this month", from one extra read.

    What the served page can pin: the markup and its order, the single Promise.all that now carries a
    third call with the same month+mode query, the one state that colours the amount (negative, in the
    shared --danger), and the setup message a user with nothing saved sees instead of a figure.
    """
    page = client.get("/").text
    assert 'id="safeCard"' in page
    assert page.index('id="safeCard"') < page.index('class="card hero-card"'), "the card sits above the hero"
    assert ">Safe to spend<" in page
    for element in ('id="safeAmount"', 'id="safeMeta"', 'id="safeDetailsBtn"'):
        assert element in page, element
    home = page[page.index("async function loadHome("):page.index("// Re-read only the money figures")]
    assert home.count("await Promise.all(") == 1, "the read rides in the one existing batch"
    assert 'api("/finance/summary" + monthQuery())' in home
    assert "renderSafeCard(loaded[2]);" in home
    # the amount is the only coloured thing, and only when it is negative
    assert 'classList.toggle("neg", !setup && amount < 0)' in page
    assert ".safe-amount.neg { color: var(--danger); }" in page
    # money() drops the sign, so the card has to put the minus back itself
    assert '(amount < 0 ? "\\u2212" : "") + money(Math.abs(amount))' in page
    # nothing saved yet: the card asks for the opening balance instead of showing a meaningless total
    assert "Set your opening balance" in page
    assert "function hasMoneySettings(summary)" in page
    # Details opens the month's commitments, and the setup state offers a way to Settings
    assert 'addEventListener("click", openCommitSheet)' in page
    assert "function showMoneySettings()" in page


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


def test_the_commitments_sheet_reads_the_month_and_toggles_paid(client: TestClient) -> None:
    """The list is per month, the paid mark is two-way, and the add form posts the three API fields."""
    page = client.get("/").text
    # /commitments requires a month, and the sheet sends the one being viewed
    assert 'api("/commitments?month=" + encodeURIComponent(month))' in page
    # a row: the name (user data, escaped), the amount and the due day
    assert "escapeHtml(row.name)" in page
    assert 'escapeHtml(money(row.amount)) + " \\u00b7 due "' in page
    assert "escapeHtml(ordinal(row.day_of_month))" in page
    assert "function ordinal(day)" in page
    # the toggle is two-way: POST marks, DELETE unmarks, both for the viewed month
    assert 'data-commit-paid="' in page and 'aria-pressed="' in page
    assert '"/paid?month=" +' in page and 'method: "DELETE"' in page
    assert "body: JSON.stringify({ month: state.month })" in page
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
    assert page.count('addEventListener("click", openCommitSheet)') == 2


def test_the_commitment_form_keeps_the_16px_floor(client: TestClient) -> None:
    """Its three fields reuse .add-field (16px) and both numbers ask for the right phone keyboard."""
    page = client.get("/").text
    form = page[page.index('<div class="commit-form">'):page.index('<div class="overlay" id="addOverlay"')]
    assert form.count('class="add-field"') == 3
    assert 'id="commitAmount" type="text" inputmode="decimal"' in form
    assert 'id="commitDay" type="text" inputmode="numeric"' in form


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
