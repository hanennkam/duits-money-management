"""The Uvicorn access log must never contain a Supabase `token_hash` or OAuth `code` value.

The unit cases drive the real filter and Uvicorn 0.54's real ``AccessFormatter``. The last
test starts the same command both startup paths use (``python -m uvicorn app.main:app``) and
reads its actual stdout, so the production wiring is exercised, not a detached string helper.
"""

from __future__ import annotations

import io
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from uvicorn.logging import AccessFormatter

import app.main  # noqa: F401 - importing the app installs the access-log filter
from app.logging_redaction import (
    ACCESS_LOGGER,
    RedactTokenHashFilter,
    install,
    redact_path,
    redact_query,
)

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "dummy-token-hash-5g"
CODE = "dummy-oauth-code-7f"


def access_logger() -> logging.Logger:
    return logging.getLogger(ACCESS_LOGGER)


def emit_access(path: str, method: str = "GET", status: int = 200) -> str:
    """Emit one record in Uvicorn 0.54's exact access shape and format it with its formatter."""
    logger = access_logger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        AccessFormatter(
            '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
        )
    )
    old_level = logger.level
    old_propagate = logger.propagate
    old_disabled = logger.disabled
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.disabled = False
    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1",
            method,
            path,
            "1.1",
            status,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate
        logger.disabled = old_disabled
    return stream.getvalue()


# ---------------------------------------------------------------- the real formatter

def test_token_hash_value_is_redacted_in_the_real_access_formatter() -> None:
    output = emit_access(f"/?token_hash={TOKEN}&type=signup")
    assert TOKEN not in output
    assert "token_hash=[REDACTED]" in output
    assert "type=signup" in output
    assert "GET" in output
    assert "200" in output


def test_oauth_code_is_redacted_in_the_real_access_formatter() -> None:
    output = emit_access(f"/?code={CODE}")
    assert CODE not in output
    assert "code=[REDACTED]" in output
    assert "GET" in output
    assert "200" in output


def test_oauth_code_is_redacted_with_unrelated_parameters_before_and_after() -> None:
    before = emit_access(f"/?foo=bar&code={CODE}")
    after = emit_access(f"/?code={CODE}&foo=bar")
    for output in (before, after):
        assert CODE not in output
        assert "code=[REDACTED]" in output
        assert "foo=bar" in output


def test_url_encoded_oauth_code_values_and_keys_are_redacted() -> None:
    encoded_value = emit_access("/?code=SEC%2BRET&foo=bar")
    assert "SEC%2BRET" not in encoded_value
    assert "SEC+RET" not in encoded_value
    assert "code=[REDACTED]" in encoded_value

    encoded_key = emit_access("/?co%64e=ENCODED-KEY&foo=bar")
    assert "ENCODED-KEY" not in encoded_key
    assert "[REDACTED]" in encoded_key


def test_multiple_sensitive_parameters_are_redacted_together() -> None:
    output = emit_access(f"/?code={CODE}&token_hash={TOKEN}&type=signup&utm=keep")
    assert CODE not in output
    assert TOKEN not in output
    assert output.count("[REDACTED]") == 2
    assert "type=signup" in output
    assert "utm=keep" in output


def test_repeated_token_hash_values_are_all_redacted() -> None:
    output = emit_access("/?token_hash=REPEAT-ONE&type=signup&token_hash=REPEAT-TWO")
    assert "REPEAT-ONE" not in output
    assert "REPEAT-TWO" not in output
    assert output.count("token_hash=[REDACTED]") == 2
    assert "type=signup" in output


def test_url_encoded_values_and_keys_cannot_bypass() -> None:
    encoded_value = emit_access("/?token_hash=SEC%2BRET&type=signup")
    assert "SEC%2BRET" not in encoded_value
    assert "SEC+RET" not in encoded_value
    assert "token_hash=[REDACTED]" in encoded_value

    encoded_key = emit_access("/?token%5Fhash=ENCODED-KEY&type=signup")
    assert "ENCODED-KEY" not in encoded_key
    assert "[REDACTED]" in encoded_key


def test_case_variants_and_encoded_case_are_redacted() -> None:
    output = emit_access(
        "/?TOKEN_HASH=CASE-ONE&Token_Hash=CASE-TWO"
        "&token%5Fhash=CASE-THREE&TOKEN%5fHASH=CASE-FOUR&type=signup&utm=keep"
    )
    for secret in ("CASE-ONE", "CASE-TWO", "CASE-THREE", "CASE-FOUR"):
        assert secret not in output
    assert output.count("[REDACTED]") == 4
    assert "type=signup" in output
    assert "utm=keep" in output


def test_unrelated_parameters_are_preserved() -> None:
    output = emit_access(
        f"/?token_hash={TOKEN}&type=signup&utm=abc&not_token_hash=keep"
    )
    assert TOKEN not in output
    assert "type=signup" in output
    assert "utm=abc" in output
    assert "not_token_hash=keep" in output


def test_requests_without_token_hash_keep_normal_logging() -> None:
    output = emit_access("/?type=signup&utm=abc")
    assert "/?type=signup&utm=abc" in output
    assert "[REDACTED]" not in output


def test_method_and_status_remain_observable() -> None:
    output = emit_access(f"/?token_hash={TOKEN}", method="POST", status=201)
    assert "POST" in output
    assert "201" in output
    assert TOKEN not in output


# ---------------------------------------------------------------- the filter itself

def test_the_filter_is_installed_on_the_uvicorn_access_logger() -> None:
    assert any(
        isinstance(existing, RedactTokenHashFilter)
        for existing in access_logger().filters
    )


def test_install_is_idempotent() -> None:
    install()
    install()
    assert (
        sum(
            isinstance(existing, RedactTokenHashFilter)
            for existing in access_logger().filters
        )
        == 1
    )


def test_original_scope_is_never_modified() -> None:
    original = f"token_hash={TOKEN}&type=signup".encode()
    scope = {"path": "/", "query_string": original}
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "message", (), None
    )
    record.scope = scope
    RedactTokenHashFilter().filter(record)

    assert scope["query_string"] == original, "the request's own scope must not change"
    assert TOKEN.encode() not in record.scope["query_string"]
    assert b"token_hash=[REDACTED]" in record.scope["query_string"]


def test_filter_does_not_assume_the_path_argument_position() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s",
        ("GET", f"/?token_hash={TOKEN}", 200),
        None,
    )
    RedactTokenHashFilter().filter(record)
    assert TOKEN not in str(record.args)
    assert "[REDACTED]" in str(record.args)


def test_malformed_and_bare_parameters_are_safe() -> None:
    assert (
        redact_path("/?token_hash=%ZZ&type=signup")
        == "/?token_hash=[REDACTED]&type=signup"
    )
    assert redact_path("/?token_hash") == "/?token_hash=[REDACTED]"
    assert redact_path("/health") == "/health"
    assert redact_query("") == ""


def test_query_order_and_unrelated_values_are_kept_verbatim() -> None:
    assert (
        redact_query(f"a=1&token_hash={TOKEN}&b=2&token_hash={TOKEN}2")
        == "a=1&token_hash=[REDACTED]&b=2&token_hash=[REDACTED]"
    )


def test_redact_query_matches_case_variants_and_keeps_unrelated_values() -> None:
    assert (
        redact_query(
            "TOKEN_HASH=A&Token_Hash=B&token%5Fhash=C&TOKEN%5fHASH=D"
            "&type=signup&not_token_hash=keep"
        )
        == "TOKEN_HASH=[REDACTED]&Token_Hash=[REDACTED]&token%5Fhash=[REDACTED]"
        "&TOKEN%5fHASH=[REDACTED]&type=signup&not_token_hash=keep"
    )


# ---------------------------------------------------------------- real Uvicorn process

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _dummy_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "API_KEY": "dummy-api-key",
            "SUPABASE_URL": "https://dummy.supabase.co",
            "SUPABASE_SERVICE_KEY": "dummy-service-key",
            "SUPABASE_PUBLISHABLE_KEY": "dummy-publishable-key",
            "ANTHROPIC_API_KEY": "dummy-anthropic-key",
            "ENVIRONMENT": "production",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )
    return env


def test_real_uvicorn_access_log_redacts_the_token() -> None:
    """Start the command both Docker and ctl.sh use and read its actual output."""
    port = _free_port()
    with tempfile.TemporaryDirectory() as cwd:
        # A temporary working directory means app/config.py's load_dotenv() cannot pick up
        # the repo's .env; every required value above is a dummy.
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "info",
            ],
            cwd=cwd,
            env=_dummy_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(0.2)
            else:
                pytest.fail("uvicorn did not become ready")

            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/?token_hash={TOKEN}&type=signup",
                timeout=5,
            ) as response:
                assert response.status == 200
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/?code={CODE}&foo=bar",
                timeout=5,
            ) as response:
                assert response.status == 200
        finally:
            process.terminate()
            try:
                output, _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate(timeout=5)

    assert TOKEN not in output, "the token hash must never reach the access log"
    assert CODE not in output, "the OAuth code must never reach the access log"
    assert "token_hash=[REDACTED]" in output
    assert "code=[REDACTED]" in output
    assert "GET /?token_hash=[REDACTED]&type=signup" in output
    assert "GET /?code=[REDACTED]&foo=bar" in output
    assert "200" in output
