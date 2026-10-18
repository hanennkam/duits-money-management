"""The staging fixtures carry real keys: nothing pytest prints may ever show one.

On 2026-10-19 a failing staging test rendered the fixture dicts (service key, publishable key, test
password) into a pasted traceback; the keys were rotated (docs/migration-runbook.md §10 step 3). The
wrapper is conftest.py's `Secret` (applied by `redact_secrets`, used by the staging `env` and `service`
fixtures), and the needles here are dummies that exist only to be searched for.

The direct test covers repr/str and that the values themselves still work. The subprocess test is the
end-to-end proof on the two rendering paths that leaked: pytest's dict-comparison explanation (which walks
a dict's ITEMS and reprs each value separately — the very reason a redacting dict subclass is not enough)
and the locals list under -l. Both probe tests fail by design; the control holds a plain str and MUST
leak, and the wrapped one must fail cleanly — because without that control a clean output would prove
nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import REDACTED_VALUE, Secret, redact_secrets

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

NEEDLES = {
    "PROBE_SERVICE": "probe-service-key-7f3a91c2",
    "PROBE_PUBLISHABLE": "probe-publishable-c24d05e8",
    "PROBE_PASSWORD": "probe-password-e81b7c4d",
}

# The needles reach the probe through its environment, so they never appear in the probe's source: a long
# traceback prints source lines, and a needle there would make this check pass for the wrong reason. The
# service needle is shared with the control on purpose — it is the one value this test expects to see.
PROBE_SOURCE = '''\
import os
import sys

sys.path.insert(0, {tests_dir!r})
sys.path.insert(0, {repo!r})

from conftest import redact_secrets

PLAIN = {{"SUPABASE_SERVICE_KEY": os.environ["PROBE_SERVICE"]}}
HIDDEN = redact_secrets({{
    "SUPABASE_SERVICE_KEY": os.environ["PROBE_SERVICE"],
    "SUPABASE_PUBLISHABLE_KEY": os.environ["PROBE_PUBLISHABLE"],
    "STAGING_TEST_PASSWORD": os.environ["PROBE_PASSWORD"],
    "SUPABASE_URL": "https://staging-ref.supabase.co",
}})


def test_a_plain_str_is_the_leaking_control() -> None:
    value = dict(PLAIN)   # a real local, so -l renders it too
    assert value == {{}}


def test_a_wrapped_value_must_not_leak() -> None:
    local = dict(HIDDEN)  # a real local, so -l renders it through repr()
    assert HIDDEN == {{}}
'''


def test_secret_hides_the_value_from_repr_and_str_but_keeps_it_working() -> None:
    settings = redact_secrets({
        "SUPABASE_URL": "https://staging-ref.supabase.co",
        "SUPABASE_SERVICE_KEY": NEEDLES["PROBE_SERVICE"],
        "SUPABASE_PUBLISHABLE_KEY": NEEDLES["PROBE_PUBLISHABLE"],
        "STAGING_TEST_PASSWORD": NEEDLES["PROBE_PASSWORD"],
        "STAGING_USER_A_ID": "00000000-0000-0000-0000-000000000001",
    })
    for needle in NEEDLES.values():
        assert needle not in repr(settings), needle
        assert needle not in str(settings), needle
    assert settings["SUPABASE_URL"] in repr(settings)                     # non-secrets stay readable
    assert settings["STAGING_USER_A_ID"] in str(settings)
    assert REDACTED_VALUE in repr(settings)
    assert isinstance(settings["SUPABASE_SERVICE_KEY"], Secret)

    service_key = settings["SUPABASE_SERVICE_KEY"]
    assert service_key == NEEDLES["PROBE_SERVICE"]                        # the value itself is untouched
    assert hash(service_key) == hash(NEEDLES["PROBE_SERVICE"])
    assert f"Bearer {service_key}" == f"Bearer {NEEDLES['PROBE_SERVICE']}"  # what a header carries
    assert not isinstance(settings["SUPABASE_URL"], Secret)

    assert settings == {                                                  # equality with a plain dict
        "SUPABASE_URL": "https://staging-ref.supabase.co",
        "SUPABASE_SERVICE_KEY": NEEDLES["PROBE_SERVICE"],
        "SUPABASE_PUBLISHABLE_KEY": NEEDLES["PROBE_PUBLISHABLE"],
        "STAGING_TEST_PASSWORD": NEEDLES["PROBE_PASSWORD"],
        "STAGING_USER_A_ID": "00000000-0000-0000-0000-000000000001",
    }
    assert list(settings) == [                                            # iteration order untouched
        "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_PUBLISHABLE_KEY",
        "STAGING_TEST_PASSWORD", "STAGING_USER_A_ID",
    ]
    assert redact_secrets({"ordinary": "value"}) == {"ordinary": "value"}


def test_pytest_output_never_carries_a_fixture_secret(tmp_path: Path) -> None:
    probe = tmp_path / "test_probe.py"
    probe.write_text(PROBE_SOURCE.format(tests_dir=str(TESTS), repo=str(REPO)))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-q", "-l", "--tb=long", "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, **NEEDLES, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        cwd=tmp_path,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0 and "2 failed" in output, f"the probe did not run as designed:\n{output}"
    assert NEEDLES["PROBE_SERVICE"] in output, "control: the plain str must leak, or this check proves nothing"
    for needle in (NEEDLES["PROBE_PUBLISHABLE"], NEEDLES["PROBE_PASSWORD"]):
        assert needle not in output, f"a Secret leaked: {needle}"
