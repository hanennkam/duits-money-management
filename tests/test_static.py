"""The app icon: served publicly under both names browsers ask for, and safe for iOS.

The PNG is inspected with the standard library (the IHDR chunk is 13 fixed bytes) so the test
needs no image dependency: what matters is that the file has no alpha channel — iOS paints
transparency black on the Home Screen — and that it is the 180x180 iOS expects.
"""

from __future__ import annotations

import struct
from pathlib import Path

from fastapi.testclient import TestClient

ICON_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "logo.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ALPHA_FREE_COLOUR_TYPES = {0, 2, 3}  # greyscale, truecolour, palette — none carry an alpha channel


def test_the_icon_is_public_under_both_names(client: TestClient) -> None:
    logo = client.get("/logo.png")
    touch = client.get("/apple-touch-icon.png")

    for response in (logo, touch):
        assert response.status_code == 200            # no X-API-Key: the page's own icon must load
        assert response.headers["content-type"] == "image/png"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers.get("Cache-Control") != "no-store"   # static art may be cached

    assert logo.content == touch.content              # one file, two names
    assert logo.content == ICON_PATH.read_bytes()


def test_the_icon_is_documented_nowhere_as_api(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/logo.png" not in paths
    assert "/apple-touch-icon.png" not in paths


def test_the_icon_file_is_opaque_and_ios_sized() -> None:
    raw = ICON_PATH.read_bytes()
    assert raw.startswith(PNG_SIGNATURE)

    width, height, depth, colour_type = struct.unpack(">IIBB", raw[16:26])
    assert (width, height) == (180, 180)              # the size iOS asks for
    assert depth == 8
    assert colour_type in ALPHA_FREE_COLOUR_TYPES, (
        "the icon must have no alpha channel, or iOS draws the transparent parts black"
    )
    assert len(raw) < 150_000, "a 180x180 icon should not be hundreds of kilobytes"
