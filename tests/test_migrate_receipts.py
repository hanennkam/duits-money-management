"""`migrate_receipts.py` classifies receipt paths before it moves anything, and `main()`'s exit code is
what `docs/CUTOVER_RUNBOOK.md` reads.

Two shapes must be recognised and one must not. The first is the original legacy form; the second is
residue from a `down`/`up` cycle, which reassigns rows without moving the objects back and leaves an
object under the *old* owner's folder. The failure mode this pins: the re-homed path must drop the foreign
prefix rather than stack under the new owner. The exit codes the runbook's STOP depends on are pinned
here too: a shared object is a skip and exits 0, an unexpected format exits 1, a guard refusal exits 2
and must fire before any client is built.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import scripts.migrate_receipts as migrate_receipts  # noqa: E402
from scripts.migrate_receipts import OWNER_PREFIXED, receipt_rest  # noqa: E402

OWNER = "67a4cc95-a77a-4f1b-a12a-048db5324c1f"
OTHER = "40d50fe5-b5bc-4785-9e54-37e46884664a"


def run_main(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
             rows: list[dict], *, project_ref: str = "a" * 20,
             url_ref: str | None = None) -> tuple[int, str, str]:
    """`main()` over a stub client that never touches the network; returns (code, stdout, stderr).

    `project_ref` is what the runbook passes on the command line; `url_ref` is what the env file
    claims to point at. They differ only in the test that pins the guard.
    """
    tail = SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))
    query = SimpleNamespace(
        select=lambda *_: SimpleNamespace(
            not_=SimpleNamespace(is_=lambda *_: SimpleNamespace(
                order=lambda *_: SimpleNamespace(range=lambda *_: tail)
            ))
        )
    )
    client = SimpleNamespace(table=lambda *_: query)
    monkeypatch.setattr(migrate_receipts, "create_client", lambda *_a, **_k: client)
    monkeypatch.setattr(migrate_receipts, "dotenv_values", lambda _path: {
        "SUPABASE_URL": f"https://{url_ref or project_ref}.supabase.co", "SUPABASE_SERVICE_KEY": "k",
    })
    env = tmp_path / "env-that-is-never-read-because-dotenv-is-stubbed"
    code = migrate_receipts.main(["--env-file", str(env), "--project-ref", project_ref])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


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


# --- the exit codes the runbook's STOP depends on ---
# docs/CUTOVER_RUNBOOK.md treats `shared_object` as a note rather than a failure, and STOPs on a
# non-zero exit from the dry run. That only holds if `main()` returns what its comments say, so the
# three outcomes are pinned here: skip -> 0, unexpected format -> 1, guard refusal -> 2.


def test_a_shared_object_is_a_skip_and_exits_zero(capsys: pytest.CaptureFixture,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    """One object referenced by two rows must not fail the run: it is reported and left alone."""
    shared = f"{OTHER}/2026/10/shared.jpg"
    rows = [{"id": "r1", "user_id": OWNER, "receipt_path": shared},
            {"id": "r2", "user_id": OWNER, "receipt_path": shared}]
    code, out, _ = run_main(capsys, monkeypatch, tmp_path, rows)
    assert code == 0
    assert "shared_object: 2" in out
    assert "skipped (one object, two rows) — not an error" in out


def test_an_unexpected_format_exits_one(capsys: pytest.CaptureFixture,
                                        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A prefix that is not a UUID is a failure, because the tool will not guess at an owner."""
    rows = [{"id": "r1", "user_id": OWNER, "receipt_path": "someone-else/2026/10/x.jpg"}]
    code, out, _ = run_main(capsys, monkeypatch, tmp_path, rows)
    assert code == 1
    assert "unexpected_format: 1" in out


def test_a_refusal_exits_two_and_builds_no_client(capsys: pytest.CaptureFixture,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    """A guard hit must exit 2 without touching Supabase: the stub raises if a client were built."""
    def explode(*_a, **_k):
        raise AssertionError("create_client must not run when a guard refuses")

    monkeypatch.setattr(migrate_receipts, "create_client", explode)
    # the env file points at one project, the command line names another: the guard fires first
    code, _, err = run_main(capsys, monkeypatch, tmp_path, [], project_ref="b" * 20,
                            url_ref="a" * 20)
    assert code == 2
    assert "does not match --project-ref" in err
