"""Run the staging isolation tests against the STAGING project only.

Loads .env.staging into the environment before pytest imports the app, so every setting the app reads comes from
staging (the app's own .env loading never overrides a value that is already set). Refuses the live project.
Nothing is printed except pytest's output and the project ref check.

Usage:  ./.venv/bin/python scripts/run_staging_tests.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[1]
ENV_FILE = REPO / ".env.staging"
LIVE_PROJECT_REF = "viorpltdkpexswvofeul"
STAGING_PROJECT_REF = "tddigsmukmhkjrwiqdec"


def main() -> int:
    values = {key: value for key, value in dotenv_values(ENV_FILE).items() if value is not None}
    match = re.match(r"^https://([a-z0-9]{20})\.supabase\.co/?$", values.get("SUPABASE_URL", ""))
    ref = match.group(1) if match else None
    if ref == LIVE_PROJECT_REF:
        print("refused: .env.staging points at the live project", file=sys.stderr)
        return 2
    if ref != STAGING_PROJECT_REF:
        print("refused: .env.staging does not point at the staging project", file=sys.stderr)
        return 2

    os.environ.update(values)
    os.environ["DUITS_STAGING_TESTS"] = "1"
    os.chdir(REPO)

    import pytest

    # --tb=short, and never -l/--showlocals: a traceback must name the row that failed, not render the
    # fixtures — they carry the service key, the publishable key and the test password. Secret (tests/
    # conftest.py) hides a credential from repr(), but the long traceback styles print whole source
    # contexts, so short is the ceiling here.
    return int(pytest.main(["tests/staging", "-m", "staging", "-q", "--tb=short", "-p", "no:randomly"]))


if __name__ == "__main__":
    raise SystemExit(main())
