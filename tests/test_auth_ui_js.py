"""Run the Node behavioural tests for the auth UI helpers.

The helpers live inside the served page, so the harness extracts them and drives them under Node.
They are skipped when Node is not installed; the static auth tests still pin the page contract.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "auth_ui_test.mjs"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed; auth UI behaviour is unproven here")
def test_auth_ui_helper_behaviour() -> None:
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "0 failed" in result.stdout, result.stdout
