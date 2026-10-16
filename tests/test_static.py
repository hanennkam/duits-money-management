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
    assert page.count("isOutsideTap(event, $(") == 3, "all three overlays must use the guard"


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
