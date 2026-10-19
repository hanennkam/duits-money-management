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


def function_body(page: str, signature: str) -> str:
    """One whole function, braces balanced, so a pin cannot go stale from a fixed-width slice.

    Reading a function as `page[index:index + 1400]` rots the moment the body grows: the assertion that
    names something near the end starts failing while nothing about the behaviour changed. Counting braces
    from the signature's own `{` gives the body whatever its length (these bodies contain no braces inside
    string literals or regexes).
    """
    start = page.index(signature)
    depth = 0
    for index in range(page.index("{", start), len(page)):
        if page[index] == "{":
            depth += 1
        elif page[index] == "}":
            depth -= 1
            if depth == 0:
                return page[start:index + 1]
    raise AssertionError("unterminated function: " + signature)


# ---------------------------------------------------------------- the sign-in settings

def test_the_page_carries_the_publishable_key_and_never_the_service_key(client: TestClient) -> None:
    page = client.get("/").text
    assert "pk_test_dummy" in page, "the publishable key must be injected for sign-in"
    assert SERVICE_KEY not in page, "the service key must never reach the page"
    assert "{{AUTH_CONFIG}}" not in page, "the config placeholder must be filled in"
    assert "X-API-Key" not in page, "the page must authenticate with a Bearer token, not the API key"
    assert "apiKey" not in page, "the old localStorage API key slot is gone"


def test_the_sign_in_screen_is_keyboard_safe(client: TestClient) -> None:
    """The screen is centred, sits ~45% down, and still scrolls and keeps its top reachable.

    Two traps are pinned here. The static viewport height is what iOS breaks, so the box is dvh-based.
    And a centred flex item taller than its box overflows off the *top*, where it can never be scrolled
    back into view: `safe center` aligns to the start instead. Geometry is measured in the browser.
    """
    page = client.get("/").text
    css = page[page.index("/* ---------- sign in ---------- */"):page.index(".field, .chip, .btn-primary")]

    assert "min-height: 100dvh" in css, "the box must follow the dynamic viewport"
    # Checked as declarations: the comment above deliberately names the unit it is warning about.
    assert "min-height: 100vh" not in css and "height: 100vh" not in css
    assert "max(var(--sat), 24px) 24px calc(max(var(--sab), 24px) + 10vh)" in css, (
        "the taller bottom padding is what puts the block at 45%")
    assert "position: fixed; inset: 0; z-index: 40;" in css
    assert "overflow-y: auto" in css, "the column scrolls when the keyboard eats the height"
    assert "@container" not in css, "a container query cannot see the keyboard"
    # Centred, but safely: without `safe` the title would be pushed above the box and become unreachable.
    assert "justify-content: center;" in css
    assert "justify-content: safe center;" in css
    assert "align-items: center;" in css
    assert "margin: auto;" in css, "auto margins fall back to 0 instead of overflowing off the top"


def test_the_sign_in_screen_sizes(client: TestClient) -> None:
    """Every size and gap the design asks for, on the sign-in, reset and set-password views alike."""
    page = client.get("/").text
    css = page[page.index("/* ---------- sign in ---------- */"):page.index(".field, .chip, .btn-primary")]

    assert "max-width: 340px" in css, "the inner column"
    assert "width: 72px; height: 72px; border-radius: 16px" in css, "the logo"
    assert "margin-bottom: 16px" in css, "the gap under the logo"
    assert "font-size: 24px; font-weight: 700" in css, "the title"
    assert "margin: 0 0 20px" in css, "the gap under the title"
    assert "font-size: 12px; margin: 0 0 6px" in css, "the label and its 6px gap to the input"
    assert "height: 48px; min-height: 48px; border-radius: 12px; font-size: 16px" in css, "an input"
    assert ".auth-card .field + .form-label { margin-top: 14px; }" in css, "the 14px between fields"
    assert "border-radius: 24px; font-size: 17px; margin-top: 18px" in css, "the Sign in button"
    assert ".auth-card .btn-ghost {\n    width: 100%; font-size: 15px; margin-top: 14px;" in css, "Forgot / Back"
    assert "font-size: 13px; color: var(--text-2)" in css and "margin: 20px 0 0" in css, "the invite note"
    assert "-webkit-line-clamp: 2" in css, "the note is capped at two lines"
    # iOS must not zoom on focus: 16px is the floor for anything a finger can focus.
    assert "font-size: 16px" in css


def test_the_sign_in_fields_are_typed_for_a_phone_keyboard(client: TestClient) -> None:
    page = client.get("/").text
    assert 'id="authEmail" type="email" autocomplete="username"' in page
    assert 'id="authPassword" type="password" autocomplete="current-password"' in page
    assert page.count('enterkeyhint="next"') == 1, "only the email field promises Next"
    assert page.count('enterkeyhint="go"') == 2, "the two password fields promise Go"
    for field in ("authEmail", "authPassword", "authPassword2"):
        block = page[page.index('id="' + field + '"') - 40:page.index('id="' + field + '"') + 260]
        assert 'autocapitalize="off"' in block, field
        assert 'autocorrect="off"' in block, field
        assert 'spellcheck="false"' in block, field
    # 16px is the iOS zoom threshold and maximum-scale=1 is the belt for it. The fields inherit the
    # 17px body, which is over the floor; nothing may set them smaller.
    assert 'maximum-scale=1' in page
    assert not re.search(r"\.(field|auth-card input)[^{]*\{[^}]*font-size:\s*(1[0-5]|[0-9])px", page)


def test_focus_reveals_the_field_and_blur_returns_to_the_top(client: TestClient) -> None:
    """scrollIntoView on focus, ~250ms later; scroll back to the top when the keyboard goes away."""
    page = client.get("/").text
    assert "AUTH_REVEAL_DELAY_MS = 250" in page
    assert 'input.scrollIntoView({ block: "center", behavior: "smooth" })' in page
    assert "function resetAuthScroll()" in page
    assert "document.activeElement !== input) return;" in page, "a stale timer must not scroll"
    # leaving the form (not moving between its fields) is what returns to the top
    assert 'if (!authFormHasFocus()) resetAuthScroll();' in page
    assert 'visualViewport.addEventListener("resize"' in page, "the keyboard can close without a blur"
    assert 'window.scrollTo({ top: 0, behavior: "smooth" })' in page


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


def test_recover_sends_a_redirect_target_that_matches_the_allow_list(client: TestClient) -> None:
    """The recovery link has to come back to a URL that is allow-listed in the Supabase project.

    That is the origin plus "/", not the pathname: a page opened as /index.html would otherwise send a
    redirect_to that the allow-list rejects and the link would never land back on the app.
    """
    page = client.get("/").text
    assert 'redirect_to: redirectTarget()' in page, "the recover call must send redirect_to"
    assert 'return window.location.origin + "/";' in page
    assert "window.location.origin + window.location.pathname" not in page


def test_recover_answers_with_one_generic_message(client: TestClient) -> None:
    """Sent or not, the answer is the same, so the form cannot be used to test which addresses exist."""
    page = client.get("/").text
    assert 'If that address has an account, a link is on its way.' in page
    body = page[page.index('if (authView === "forgot")'):page.index('if (authView === "forgot")') + 700]
    # Both outcomes share one call and one message: `sent.ok ? generic : generic`.
    assert body.count('setAuthView("forgot", sent.ok') == 1
    assert "sent.ok" in body and "authError(sent)" in body


def test_an_invite_sign_in_shows_the_real_address(client: TestClient) -> None:
    """Settings must name the account after an invite or recovery link, not "Not signed in".

    The redirect path used to store the session with a blank address, which is what made Settings lie.
    The address now comes from the token's own claims, with a /auth/v1/user call as the fallback.
    """
    page = client.get("/").text
    assert "function emailFromToken(token)" in page
    assert "email: emailFromToken(params.access_token)" in page
    assert 'email: ""' not in page, "the redirect path must not store a blank address"
    assert "function hydrateEmail(session)" in page
    assert 'authRequest("GET", "/auth/v1/user", null, session.access_token)' in page
    # renderAccount still degrades to the label only when there genuinely is no address.
    assert '(session && session.email) || "Not signed in"' in page


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
    # user's rows would stay on screen. The rendered lists are cleared too. The body is taken whole — a
    # fixed-width slice used to sit here and it rotted as soon as the function grew (no behaviour changed).
    body = function_body(page, "function clearCaches()")
    for node in ("txnList", "txnGroups", "insightDonut", "insightHighlights"):
        assert node in body, f"clearCaches must empty {node}"
    # the previous user's money must go too: the balance, the month's two cards and the budget bar
    for node in ("balanceAmount", "incomeTotal", "expenseTotal", "safeAmount"):
        assert node in body, f"clearCaches must reset {node}"
    assert '"RM 0.00"' in body, "the Insights total must be reset"
    assert "hideBudget();" in body, "the budget bar is reset with its card"
    # The balance card's own three pieces of state go back to "nothing known yet" with the rest.
    for node in ("balanceNotSet", "balanceTap", "retryFinanceBtn"):
        assert node in body, f"clearCaches must reset {node}"
    assert '"Balance, Personal and Business"' in body, "the wallet's accessible name is reset with its figure"
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
    "commitment name": [r"escapeHtml\(row\.name\)"],
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
        "+ row.name",
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
    assert len(re.findall(r"categoryColour\(", page)) >= 3


def test_the_manual_sheet_and_its_note_ship_in_the_page_behind_the_gate(client: TestClient) -> None:
    """The page is one file, so the Manual sheet, the category list and the Note field ship with the gate.

    The sign-in card is a layer over the app, not a server split, so the same markup is served either way.
    Note is a plain text input under the 16px floor, and it goes out under the note key the API reads.
    """
    page = client.get("/").text
    for element in ('id="authScreen"', 'id="addOverlay"', 'id="addNote"'):
        assert element in page, element
    field = page[page.index('id="addNote"') - 120:page.index('id="addNote"') + 160]
    assert 'type="text"' in field and 'maxlength="500"' in field
    assert 'note: $("addNote").value.trim() || null' in page
