"""Run the Node behavioural tests for the auth-link core.

The core lives inside the served page, so these tests extract it and drive it under Node. They are
skipped when Node is not installed: the Python suite still pins the page contract, and the harness is
the only place the verification behaviour itself is executed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "auth_link_test.mjs"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed; auth-link behaviour is unproven here")
def test_auth_link_core_behaviour() -> None:
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "0 failed" in result.stdout, result.stdout
