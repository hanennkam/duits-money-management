"""`migrate_receipts.py` classifies receipt paths before it moves anything.

Two shapes must be recognised and one must not. The first is the original legacy form; the second is
residue from a `down`/`up` cycle, which reassigns rows without moving the objects back and leaves an
object under the *old* owner's folder. The failure mode this pins: the re-homed path must drop the foreign
prefix rather than stack under the new owner.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from scripts.migrate_receipts import OWNER_PREFIXED, receipt_rest  # noqa: E402

OWNER = "67a4cc95-a77a-4f1b-a12a-048db5324c1f"
OTHER = "40d50fe5-b5bc-4785-9e54-37e46884664a"


def test_the_legacy_form_is_its_own_rest() -> None:
    assert receipt_rest("2026/10/abc.jpg", OWNER) == "2026/10/abc.jpg"


def test_a_foreign_owner_prefix_is_stripped_not_stacked() -> None:
    """The bug this guards: `<other>/2026/10/x.jpg` must become `<owner>/2026/10/x.jpg`.

    Appending the whole old path would give `<owner>/<other>/2026/10/x.jpg`, which is not what the
    app reads back and not where anything else expects the object.
    """
    assert receipt_rest(f"{OTHER}/2026/10/abc.jpg", OWNER) == "2026/10/abc.jpg"


def test_a_path_already_under_the_owner_is_left_alone() -> None:
    assert receipt_rest(f"{OWNER}/2026/10/abc.jpg", OWNER) is None


def test_shapes_it_cannot_understand_are_refused_not_guessed() -> None:
    # not a UUID prefix: the tool cannot know what that folder means
    assert receipt_rest("someone-else/2026/10/x.jpg", OWNER) is None
    # a bare file name, or a nesting it was never written for
    assert receipt_rest("x.jpg", OWNER) is None
    assert receipt_rest("2026/x.jpg", OWNER) is None
    assert receipt_rest(f"{OTHER}/sub/2026/10/abc.jpg", OWNER) is None
    assert receipt_rest("", OWNER) is None


def test_the_owner_prefix_pattern_is_a_uuid() -> None:
    assert OWNER_PREFIXED.match(f"{OTHER}/2026/10/a.jpg")
    assert not OWNER_PREFIXED.match("someone-else/2026/10/a.jpg")
