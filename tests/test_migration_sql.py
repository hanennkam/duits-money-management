"""The SQL a cutover depends on: a verify script must REPORT a missing object, never raise on it.

Postgres resolves a relation name while it PARSES a statement, before any `case` or `to_regclass(...)` guard is
evaluated. A verify script is one statement, so a direct `select ... from public.<maybe missing>` raises 42P01
instead of printing the row that says MISSING. That is not theoretical: it is what
`migrations/staging/verify_after_0003.sql` did on staging on 2026-10-18 — row 17 raised
`relation "public.migration_0003_saved_rows" does not exist` although its guard says "absent", and row 15 was the
same trap one state away (`MISSING (0003 is not applied ...)`, which is also the post-rollback state of
`docs/migration-runbook.md` §10 step 5). The bug has no syntax-level symptom, so this pins the rule: in these
files, an object that may legitimately be absent is named only inside a string, which is read at run time.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# file -> every object that file must be able to report as MISSING, with why it may be absent in a state the file
# is meant to run in. Each name here must appear only inside a string.
LAZILY_READ = {
    "migrations/staging/verify_after_0003.sql": {
        "public.migration_0003_saved_rows": "created by the 0003 DOWN file: absent after a normal 0003 up",
        "public.user_finance_settings": "absent on a pre-0003 project and after the rollback (runbook §10 step 5)",
        "public.monthly_commitments": "same as user_finance_settings",
        "public.commitment_payments": "same as user_finance_settings",
    },
    "migrations/staging/verify_after_down.sql": {
        "public.migration_0002_saved_constraints": "0002's down drops it, and this file runs after that",
        "public.api_tokens": "0002's down drops it, and this file runs after that",
    },
}


def parsed_text(sql: str) -> str:
    """What Postgres actually resolves relation names in: the text with literals and `--` comments removed.

    A name inside a string is read when the statement *runs* (`to_regclass('public.x')`,
    `query_to_xml('...')`); a name in a comment is not read at all. Both are invisible to the parser, so both are
    blanked here and whatever is left is exactly the code position this test forbids the names from occupying.
    (These files use no block comments; none are handled.)
    """
    out: list[str] = []
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = len(sql) if newline == -1 else newline
            out.append(" ")
        elif sql[index] == "'":
            index += 1
            while index < len(sql):
                if sql[index] != "'":
                    index += 1
                elif sql.startswith("''", index):  # an escaped quote inside the literal
                    index += 2
                else:
                    index += 1
                    break
            out.append("''")
        else:
            out.append(sql[index])
            index += 1
    return "".join(out)


def test_verify_scripts_never_name_a_maybe_missing_relation_in_code() -> None:
    for relative, objects in LAZILY_READ.items():
        code = parsed_text((REPO / relative).read_text())
        for name, why in objects.items():
            assert name not in code, (
                f"{relative} names {name} outside a string literal ({why}), so the statement fails to parse "
                "with 42P01 before its to_regclass guard can answer MISSING. Read it at run time instead: "
                "to_regclass(...), or query_to_xml('select count(*) as c from " + name + "', false, true, '') "
                "inside xpath('//c/text()', ...) with a coalesce for the empty case."
            )
