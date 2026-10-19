"""The SQL a cutover depends on: a verify script must REPORT a missing object, never raise on it.

Postgres resolves a relation name while it PARSES a statement, before any `case` or `to_regclass(...)` guard is
evaluated. A verify script is one statement, so a direct `select ... from public.<maybe missing>` raises 42P01
instead of printing the row that says MISSING. That is not theoretical: it is what
`migrations/staging/verify_after_0003.sql` did on staging on 2026-10-18 — row 17 raised
`relation "public.migration_0003_saved_rows" does not exist` although its guard says "absent", and row 15 was the
same trap one state away (`MISSING (0003 is not applied ...)`, which is also the post-rollback state of
`docs/migration-runbook.md` §10 step 5). The bug has no syntax-level symptom, so this pins the rule: in these
files, an object that may legitimately be absent is named only inside a string, which is read at run time. The
second rule pinned here is about names Postgres rejects outright: every custom-GUC name in the SQL files
(`app.…`) must read as dot-separated identifiers, or `set_config` raises 42602 before anything else runs.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Every *.sql in the repo (schema.sql and scripts/audit_queries.sql included): the same rule is worth
# pinning everywhere, and none of the files is allowed to name an invalid setting.
SQL_FILES = sorted(path for path in REPO.rglob("*.sql") if ".venv" not in path.parts)

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


# The GUC names a file hands to set_config/current_setting. Postgres validates the NAME of a custom
# parameter before the SQL around it runs: it must be two or more identifiers separated by dots, each
# segment [A-Za-z_][A-Za-z0-9_$]* — `set_config('app.0003_tables_present', ...)` raised 42602 on staging on
# 2026-10-19 for exactly that reason (digits cannot lead a segment, runbook §10 step 4). In the SQL files
# every `app.` mention IS a GUC name — a call argument, the example inside a raise message, or a comment
# about the same — so scanning every mention covers all three without having to parse calls.
APP_GUC_NAME = re.compile(r"\bapp\.[A-Za-z0-9_$]+(?:\.[A-Za-z0-9_$]+)*")
SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def test_every_app_guc_name_is_a_valid_custom_parameter_name() -> None:
    for path in SQL_FILES:
        sql = path.read_text()
        for match in APP_GUC_NAME.finditer(sql):
            name = match.group(0)
            line = sql[: match.start()].count("\n") + 1
            parts = name.split(".")
            assert len(parts) >= 2, f"{path}:{line}: {name} needs two or more dot-separated segments"
            for part in parts:
                assert SQL_IDENTIFIER.fullmatch(part), (
                    f"{path}:{line}: {name} raises 42602 invalid configuration parameter name — "
                    f"segment {part!r} is not a simple identifier"
                )


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


def test_the_view_only_appends_columns_after_0003s_order() -> None:
    """CREATE OR REPLACE VIEW may add columns only at the END: a new one in the middle is 42P16 on staging.

    0003's view ends with row_count, so commitment_expense comes after it, in both the 0004 migration and
    schema.sql, and the five outputs keep 0003's order ahead of it. Pinned here so a tidy-up cannot move it.
    """
    order = ["as month", "as total_income", "as total_expense", "as row_count", "as commitment_expense"]
    for name in ("migrations/0004_commitment_link.up.sql", "schema.sql"):
        text = (REPO / name).read_text(encoding="utf-8")
        block = text[text.index("create or replace view public.transaction_totals"):]
        block = block[:block.index("group by")]
        positions = [block.index(part) for part in order]
        assert positions == sorted(positions), f"{name}: outputs out of order"
