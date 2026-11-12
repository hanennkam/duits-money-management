"""Run the Node behavioural tests for the Google OAuth PKCE core.

The core lives inside the served page, so these tests extract it and drive it under Node with
deterministic crypto, storage, navigation and request doubles. They prove the client-side PKCE and
callback state machine, not real Google authentication.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "oauth_pkce_test.mjs"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed; OAuth PKCE behaviour is unproven here")
def test_oauth_pkce_core_behaviour() -> None:
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "0 failed" in result.stdout, result.stdout
