"""The served page: sign-in config, the Content-Security-Policy, and the escaping that keeps user data safe.

The session now lives in browser storage, so an injection in the page would be worth an access token. These
tests pin the two things that stand in the way: a strict CSP with a per-response nonce, and every user-data
field reaching innerHTML through escapeHtml.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from conftest import SETTINGS

SERVICE_KEY = SETTINGS.supabase_service_key
PAGE_SCRIPT = re.compile(r"<script nonce=\"([^\"]+)\">(.*?)</script>", re.S)
PAGE_STYLE = re.compile(r"<style nonce=\"([^\"]+)\">(.*?)</style>", re.S)


def csp_parts(client: TestClient) -> tuple[str, dict[str, str]]:
    policy = client.get("/").headers["Content-Security-Policy"]
    directives = {}
    for part in policy.split(";"):
        bits = part.strip().split(" ", 1)
        directives[bits[0]] = bits[1] if len(bits) > 1 else ""
    return policy, directives


# ---------------------------------------------------------------- the sign-in settings

def test_the_page_carries_the_publishable_key_and_never_the_service_key(client: TestClient) -> None:
    page = client.get("/").text
    assert "pk_test_dummy" in page, "the publishable key must be injected for sign-in"
    assert SERVICE_KEY not in page, "the service key must never reach the page"
    assert "{{AUTH_CONFIG}}" not in page, "the config placeholder must be filled in"
    assert "X-API-Key" not in page, "the page must authenticate with a Bearer token, not the API key"
    assert "apiKey" not in page, "the old localStorage API key slot is gone"


def test_the_sign_in_screen_is_present_in_the_page(client: TestClient) -> None:
    page = client.get("/").text
    for element in (
        'id="authScreen"', 'id="authEmail"', 'id="authPassword"', 'id="authPassword2"',
        'id="authSubmit"', 'id="authForgot"', 'id="authBack"', 'id="accountEmail"', 'id="signOutBtn"',
    ):
        assert element in page, element + " is missing"
    # There is no sign-up: accounts arrive by invite.
    assert "Sign up" not in page and "sign up" not in page
    assert "Duits is invite only" in page


def test_the_settings_key_card_is_an_account_card(client: TestClient) -> None:
    page = client.get("/").text
    assert "id=\"changeKeyBtn\"" not in page, "the API key row must be gone"
    assert ">API key<" not in page and ">Security<" not in page
    assert ">Account<" in page and ">Sign out<" in page


# ---------------------------------------------------------------- how the page signs in

def test_sign_in_uses_the_rest_auth_endpoints_not_a_sdk(client: TestClient) -> None:
    """No SDK and no CDN: the page calls Supabase Auth over fetch, so the file stays self-contained."""
    page = client.get("/").text
    for endpoint in (
        "/auth/v1/token?grant_type=password",
        "grant_type=refresh_token",
        "/auth/v1/recover",
        "/auth/v1/user",
        "/auth/v1/logout",
    ):
        assert endpoint in page, endpoint + " is missing"
    assert "supabase-js" not in page and "createClient" not in page
    assert "esm.sh" not in page and "unpkg" not in page and "jsdelivr" not in page
    assert "<script src=" not in page, "no external script may be loaded"


def test_refreshes_are_serialised_so_only_one_runs_at_a_time(client: TestClient) -> None:
    page = client.get("/").text
    assert "var refreshInFlight = null;" in page
    assert page.count("if (refreshInFlight) return refreshInFlight;") == 1
    assert "refreshInFlight = null;" in page


def test_a_401_refreshes_once_then_returns_to_the_sign_in_screen(client: TestClient) -> None:
    page = client.get("/").text
    assert 'if (response.status !== 401) return response;' in page
    assert "var fresh = await refreshSession(session);" in page
    assert 'showAuth("signin", "Your session has expired. Sign in again to continue.");' in page


def test_sign_out_clears_the_session_and_the_cached_rows(client: TestClient) -> None:
    page = client.get("/").text
    assert "function clearCaches()" in page
    assert "state.rows = [];" in page and "state.summary = null;" in page
    # Clearing the state is not enough: a list is only re-rendered when its own tab loads, so the previous
    # user's rows would stay on screen. The rendered lists are cleared too.
    body = page[page.index("function clearCaches()"):page.index("function clearCaches()") + 900]
    for node in ("txnList", "categoryList", "txnGroups", "insightDonut", "insightHighlights"):
        assert node in body, f"clearCaches must empty {node}"
    assert '"RM 0.00"' in body, "the hero total must be reset"
    signout = page[page.index("async function signOut()"):page.index("async function signOut()") + 700]
    assert "writeSession(null);" in signout and "clearCaches();" in signout


def test_signing_in_reloads_every_data_screen(client: TestClient) -> None:
    """Only reloading the active tab leaves Home's list stale, showing the previous user's rows."""
    body = page = client.get("/").text
    block = body[body.index("async function afterSignIn("):body.index("async function afterSignIn(") + 700]
    assert "clearCaches();" in block
    assert "Promise.all([loadHome(), loadTransactions(), loadInsights()])" in block
    assert "reloadScreen()" not in block, "the active tab alone is not enough"


def test_tokens_are_never_put_in_a_url_or_a_log(client: TestClient) -> None:
    page = client.get("/").text
    assert "?token=" not in page and "access_token=" not in page.replace("params.access_token", "")
    # The invite/recovery link carries one in the hash: it is read once and the address bar is rewritten.
    assert "history.replaceState(null, \"\", window.location.pathname + window.location.search);" in page
    assert "console.log" not in page, "nothing may be logged: the page holds live tokens"


# ---------------------------------------------------------------- content security policy

def test_the_csp_is_strict_and_is_per_response(client: TestClient) -> None:
    policy, directives = csp_parts(client)

    assert directives["default-src"] == "'self'"
    assert directives["script-src"].startswith("'self' 'nonce-"), policy
    assert "unsafe-inline" not in directives["script-src"], "injected scripts must not run"
    assert "unsafe-eval" not in policy
    assert directives["object-src"] == "'none'"
    assert directives["base-uri"] == "'none'"
    assert directives["form-action"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert directives["connect-src"] == f"'self' {SETTINGS.supabase_url}"
    assert directives["img-src"] == f"'self' blob: {SETTINGS.supabase_url}"


def test_every_script_and_style_block_carries_the_nonce_of_this_response(client: TestClient) -> None:
    response = client.get("/")
    policy = response.headers["Content-Security-Policy"]
    page = response.text

    scripts = PAGE_SCRIPT.findall(page)
    styles = PAGE_STYLE.findall(page)
    assert len(scripts) == 2, "the pre-paint script and the main script"
    assert len(styles) == 2, "the two style blocks"
    nonces = {match[0] for match in scripts + styles}
    assert len(nonces) == 1, "one nonce per response"
    nonce = nonces.pop()
    assert f"'nonce-{nonce}'" in policy
    assert "<script>" not in page and "<style>" not in page, "every block must be nonced"


def test_the_nonce_changes_between_requests(client: TestClient) -> None:
    first = client.get("/")
    second = client.get("/")
    assert PAGE_SCRIPT.search(first.text).group(1) != PAGE_SCRIPT.search(second.text).group(1)


# ---------------------------------------------------------------- user data never reaches innerHTML raw

# Every field that comes from a row and can hold what a user typed, and the escapeHtml call the template
# must use for it. A raw concatenation of any of these is an injection into a page that now holds a token.
ESCAPED_FIELDS = {
    "merchant": [r"escapeHtml\(name\)", r"escapeHtml\(transaction\.merchant", r"escapeHtml\(row\.merchant"],
    "item name": [r"escapeHtml\(item\.name\)"],
    "category": [r"escapeHtml\(capitalise\(row\.category", r"escapeHtml\(capitalise\(entry\.name"],
    "amount": [r"escapeHtml\(money\(row\.amount\)\)", r"escapeHtml\(money\(transaction\.amount\)\)"],
    "dates and ids": [r"escapeHtml\(isoDate\(row\.txn_date\)\)", r"escapeHtml\(row\.id\)"],
    "labels": [r"escapeHtml\(label\)", r"escapeHtml\(sub\)", r"escapeHtml\(value\)"],
}


def test_every_user_field_is_escaped_where_it_is_rendered(client: TestClient) -> None:
    page = client.get("/").text
    for name, patterns in ESCAPED_FIELDS.items():
        for pattern in patterns:
            assert re.search(pattern, page), f"{name}: no escapeHtml for /{pattern}/"


def test_no_user_field_is_concatenated_into_html_unescaped(client: TestClient) -> None:
    page = client.get("/").text
    for raw in (
        "+ row.merchant", "+ transaction.merchant", "+ item.name", "+ entry.label",
        "+ row.note", "+ row.category", "+ group.date", "+ row.txn_date", "+ row.amount",
    ):
        assert raw not in page, f"{raw} reaches the page without escapeHtml"


def test_colours_enter_style_attributes_only_from_constant_maps(client: TestClient) -> None:
    """The `--cat:` custom property lands in a style attribute, so its value must never be user data.

    It is only ever `categoryColour(...)`, which returns a hex from a fixed map (or the fixed fallback), or
    a `colour` variable that was assigned exactly that.
    """
    page = client.get("/").text
    assert "CATEGORY_COLOURS[category] || CATEGORY_COLOURS.other" in page, "the map is the only source"
    for source in set(re.findall(r"--cat:' \+ (\w+)", page)):
        assert source in ("colour", "categoryColour"), f"--cat: is built from {source}"
    assert len(re.findall(r"=\s*categoryColour\(", page)) >= 3
