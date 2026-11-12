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


# WCAG 2.1 contrast: normal text needs 4.5:1, large text and non-text UI need 3:1. These helpers read
# the real token values out of the served CSS, so a palette edit cannot silently reintroduce a failure.
HEX_COLOUR = re.compile(r"^#([0-9a-fA-F]{3,8})$")
RGB_COLOUR = re.compile(r"^rgba?\(([^)]+)\)$")


def parse_css_colour(value: str) -> tuple[tuple[float, float, float], float]:
    value = value.strip()
    match = HEX_COLOUR.match(value)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        if len(digits) in (6, 8):
            rgb = tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))
            alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
            return rgb, alpha
    match = RGB_COLOUR.match(value)
    if match:
        parts = [part.strip() for part in match.group(1).split(",")]
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return tuple(float(part) for part in parts[:3]), alpha
    raise AssertionError(f"unsupported CSS colour: {value!r}")


def composite(fg: tuple[tuple[float, float, float], float],
              bg: tuple[tuple[float, float, float], float]) -> tuple[float, float, float]:
    (red, green, blue), alpha = fg
    (back_red, back_green, back_blue), back_alpha = bg
    assert back_alpha == 1.0, "contrast tests only composite onto opaque backgrounds"
    return (
        red * alpha + back_red * (1 - alpha),
        green * alpha + back_green * (1 - alpha),
        blue * alpha + back_blue * (1 - alpha),
    )


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(fg: tuple[tuple[float, float, float], float],
                   bg: tuple[tuple[float, float, float], float]) -> float:
    foreground = composite(fg, bg)
    background = composite(bg, ((255.0, 255.0, 255.0), 1.0))
    first, second = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def theme_tokens(page: str) -> tuple[dict[str, str], dict[str, str]]:
    light = page[page.index(":root {"):page.index('[data-theme="dark"]')]
    dark = page[page.index('[data-theme="dark"]'):page.index("* { box-sizing")]
    pattern = re.compile(r"(--[\w-]+):\s*([^;]+);")
    return (
        {name: value.strip() for name, value in pattern.findall(light)},
        {name: value.strip() for name, value in pattern.findall(dark)},
    )


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

    assert ".auth-shell {\n    width: 100%; max-width: 440px; margin: auto;" in css, "the mobile shell"
    assert "max-width: 1040px;" in css, "the desktop shell"
    assert "grid-template-columns: minmax(0, 1fr) minmax(360px, 420px);" in css, "the two-column shell"
    assert "background: var(--card);" in css and "border-radius: var(--r-lg);" in css, "the form surface"
    assert ".auth-brand img { width: 32px; height: 32px; border-radius: 9px;" in css, "the brand mark"
    assert "font-size: 26px; font-weight: 700" in css, "the title"
    assert "margin: 0 0 8px" in css, "the gap under the title"
    assert "font-size: clamp(36px, 4vw, 58px);" in css, "the desktop lead headline"
    assert ".auth-visual { display: none; }" in css, "the motif is hidden on mobile"
    assert ".auth-visual { display: block; margin: 26px 0 4px; }" in css, "the motif is shown on desktop"
    assert "font-size: 12px; margin: 0 0 6px" in css, "the label and its 6px gap to the input"
    assert "height: 48px; min-height: 48px; border-radius: 12px; font-size: 16px" in css, "an input"
    assert ".auth-card .field + .form-label { margin-top: 14px; }" in css, "the 14px between fields"
    assert "height: 52px; min-height: 52px;" in css, "the primary button height"
    assert "border-radius: 26px; font-size: 16px; margin-top: 20px" in css, "the Sign in button"
    assert ".auth-card .auth-link {\n    width: auto; align-self: flex-start; min-height: 44px; margin-top: 8px;" in css, "Forgot / Create / Resend"
    assert ".auth-foot { font-size: 12px; color: var(--muted); line-height: 1.5; margin: 22px 0 0; text-align: left; }" in css, "the foot"
    assert "-webkit-line-clamp" not in css, "the foot must not truncate"
    # iOS must not zoom on focus: 16px is the floor for anything a finger can focus.
    assert "font-size: 16px" in css


def test_the_auth_lead_copy_tracks_each_view(client: TestClient) -> None:
    """The editorial panel names each auth state without changing the functional form title."""
    page = client.get("/").text
    assert 'id="authLeadTitle"' in page and 'id="authLeadCopy"' in page
    view = function_body(page, "function setAuthView(view, note)")
    for copy in (
        'signin: { title: "Welcome back.", copy: "Pick up where you left off. Your financial clarity starts here." }',
        'signup: { title: "A better relationship with money starts here.", copy: "Create your account and start seeing your money more clearly." }',
        'forgot: { title: "Let\'s get you back in.", copy: "Enter your email and we\'ll send you a secure recovery link." }',
        'confirmation: { title: "Check your inbox.", copy: "Confirm your email before signing in." }',
        'setpassword: { title: "Choose a new password.", copy: "Set a new password to secure your account." }',
        '"link-signup": { title: "Confirm your email.", copy: "One tap verifies this address and finishes activating your Duits account." }',
        '"link-recovery": { title: "Reset your password.", copy: "Verify this link, then choose a new password." }',
        '"link-invite": { title: "You\'re invited.", copy: "Accept the invitation, then choose a password." }',
        'expired: { title: "This link can\'t be used.", copy: "Request a new confirmation email or reset your password below." }',
    ):
        assert copy in view, copy
    assert "var lead = leads[view] || leads.signin;" in view
    assert '$("authLeadTitle").textContent = lead.title;' in view
    assert '$("authLeadCopy").textContent = lead.copy;' in view


def test_the_auth_google_block_is_present_but_dark_until_provider_config(client: TestClient) -> None:
    """Google is presented first; the PKCE client flow exists behind a disabled configuration flag."""
    page = client.get("/").text
    assert 'id="authGoogleBlock"' in page
    assert 'id="authGoogle"' in page
    assert 'id="authGoogleNote"' in page
    assert 'id="authEmailDivider"' in page
    assert '<button class="auth-google" id="authGoogle" type="button" disabled aria-describedby="authGoogleNote">' in page
    assert "or continue with email" in page
    assert "Google sign-in isn't available yet. Continue with email." in page

    view = function_body(page, "function setAuthView(view, note)")
    assert 'var showGoogle = view === "signin" || view === "signup";' in view
    assert "updateGoogleAvailability();" in view
    assert '$("authGoogleBlock").hidden = !showGoogle;' in view
    assert '$("authEmailDivider").hidden = !showGoogle;' in view

    # The client implementation exists, but the provider is not configured: the button stays disabled.
    assert "var GOOGLE_OAUTH_CONFIGURED = false;" in page
    assert "function googleOAuthAvailable()" in page
    assert "if (!GOOGLE_OAUTH_CONFIGURED) return GOOGLE_UNAVAILABLE_NOTE;" in page
    assert '$("authGoogle").addEventListener("click", startGoogleSignIn);' in page
    assert '$("welcomeGoogle").addEventListener("click", startGoogleSignIn);' in page
    assert "function startGoogleSignIn()" in page
    assert "if (googleInFlight) return;" in page
    assert 'setAuthBusy(button, true, "Connecting\\u2026");' in page
    assert "function finishOAuthSignIn()" in page
    assert 'oauthFlow.begin(window.location.search, window.location.hash);' in page
    assert "await restoreSession(link, oauth);" in page
    assert 'if (oauth.kind === "ready")' in page

    # The welcome and auth notes share one message source.
    assert 'var GOOGLE_UNAVAILABLE_NOTE = "Google sign-in isn\'t available yet. Continue with email.";' in page
    assert "function googleAvailabilityNote()" in page
    assert "note.textContent = text;" in page


def test_google_oauth_pkce_core_is_s256_and_single_use(client: TestClient) -> None:
    """The Google flow is real PKCE: Google provider, basic scopes, S256, one stored verifier."""
    page = client.get("/").text
    oauth = page[page.index("/* ---------- oauth pkce core"):page.index("/* ---------- end oauth pkce core")]

    assert 'var OAUTH_PROVIDER = "google";' in oauth
    assert 'var OAUTH_SCOPES = "openid";' in oauth
    assert '["code_challenge_method", "s256"]' in oauth
    assert '["code_challenge", challenge]' in oauth
    assert '"/auth/v1/token?grant_type=pkce"' in oauth
    assert "auth_code: current.code" in oauth
    assert "code_verifier: current.verifier" in oauth
    assert "OAUTH_FLOW_KEY" in oauth
    assert "sessionStorage" in page
    assert "storageRemove();" in oauth
    assert "deps.cleanUrl();" in oauth
    assert "plain" not in oauth, "PKCE must never fall back to plain"
    assert "client_secret" not in oauth
    assert "access_token" not in oauth
    assert "refresh_token" not in oauth
    assert "linkIdentity" not in page, "no custom account-linking mechanism"

    assert '"error_code"' in page
    assert '"sb"' in page
    assert 'if (errorCode === "signup_disabled")' in page
    assert 'case "signup_disabled":' in page
    assert "Google registration isn't available right now." in page

    start = function_body(page, "async function start()")
    assert start.index("oauthFlow.begin(") < start.index("authLink.begin("), (
        "the OAuth callback must be claimed before the email-link parser"
    )
    restore = function_body(page, "async function restoreSession(link, oauth)")
    assert 'if (oauth.kind === "ready")' in restore
    assert "await finishOAuthSignIn();" in restore
    assert "existingOAuth" in restore, "a bad OAuth callback must preserve a valid session"
    finish = function_body(page, "async function finishOAuthSignIn()")
    assert "await oauthFlow.verify();" in finish
    assert "await afterSignIn(result.session, result.isNewUser === true);" in finish
    signout = function_body(page, "async function signOut()")
    assert "oauthFlow.cancel();" in signout


def test_auth_autocomplete_and_password_hints_follow_the_view(client: TestClient) -> None:
    """Sign-in uses current-password; sign-up and set-password use new-password and a neutral hint."""
    page = client.get("/").text
    assert 'id="authPasswordHint"' in page and "Choose a secure password." in page
    assert 'id="authPassword2Hint"' in page and "Use the same password." in page
    assert 'id="authPassword" type="password" autocomplete="current-password"' in page
    assert 'id="authPassword2" type="password" autocomplete="new-password"' in page
    assert 'id="authEmail" type="email" autocomplete="username"' in page
    assert 'placeholder="you@example.com"' in page
    assert 'placeholder="Your password"' in page
    assert 'placeholder="Repeat your password"' in page

    view = function_body(page, "function setAuthView(view, note)")
    assert "var creatingPassword = signup || settingPassword;" in view
    assert '$("authEmail").autocomplete = view === "signin" ? "username" : "email";' in view
    assert '$("authPassword").autocomplete = creatingPassword ? "new-password" : "current-password";' in view
    assert '$("authPasswordHint").hidden = !creatingPassword;' in view
    assert '$("authPassword2Hint").hidden = !creatingPassword;' in view
    assert '$("authPassword2").hidden = !creatingPassword;' in view
    assert '$("authPassword2Label").hidden = !creatingPassword;' in view

    # The exact Supabase policy is not exposed by the staging settings endpoint; do not invent one.
    hint_start = page.index('id="authPasswordHint"')
    hint = page[hint_start:hint_start + 120]
    assert "8" not in hint and "eight" not in hint.lower()


def test_auth_password_toggles_are_accessible_and_reset_per_view(client: TestClient) -> None:
    """Both password fields get independent, labelled toggles that reset on every view change."""
    page = client.get("/").text
    assert 'id="authPasswordToggle"' in page
    assert 'id="authPassword2Toggle"' in page
    assert 'aria-label="Show password" aria-pressed="false" aria-controls="authPassword"' in page
    assert 'aria-label="Show confirm password" aria-pressed="false" aria-controls="authPassword2"' in page
    assert 'wirePasswordToggle("authPassword", "authPasswordToggle", "Show password", "Hide password");' in page
    assert 'wirePasswordToggle("authPassword2", "authPassword2Toggle", "Show confirm password", "Hide confirm password");' in page
    assert 'input.type = visible ? "text" : "password";' in page
    assert 'button.setAttribute("aria-pressed", visible ? "true" : "false");' in page
    assert 'button.setAttribute("aria-label", visible ? hideLabel : showLabel);' in page

    view = function_body(page, "function setAuthView(view, note)")
    assert 'resetPasswordVisibility($("authPassword"), $("authPasswordToggle"), "Show password");' in view
    assert 'resetPasswordVisibility($("authPassword2"), $("authPassword2Toggle"), "Show confirm password");' in view
    assert '$("authPasswordToggle").hidden = $("authPassword").hidden;' in view
    assert '$("authPassword2Toggle").hidden = $("authPassword2").hidden;' in view


def test_auth_loading_states_are_scoped_and_restored(client: TestClient) -> None:
    """Submit and resend have separate in-flight guards, busy labels and restoration paths."""
    page = client.get("/").text
    assert 'id="authNote" role="status" aria-live="polite"' in page
    assert "var authSubmitInFlight = false;" in page
    assert "var authResendInFlight = false;" in page
    assert "var authSubmitBusyToken = 0;" in page
    assert "var authResendBusyToken = 0;" in page
    assert "if (authSubmitInFlight) return;" in page
    assert "if (authResendInFlight) return;" in page
    assert '"Signing in\\u2026"' in page
    assert '"Creating account\\u2026"' in page
    assert '"Sending reset link\\u2026"' in page
    assert '"Saving password\\u2026"' in page
    assert '"Verifying\\u2026"' in page
    assert 'setAuthBusy(button, true, "Sending\\u2026");' in page
    assert "var submitToken = ++authSubmitBusyToken;" in page
    assert "var resendToken = ++authResendBusyToken;" in page
    assert "if (submitToken === authSubmitBusyToken)" in page
    assert "if (resendToken === authResendBusyToken)" in page
    assert "authSubmitInFlight = false;" in page
    assert "authResendInFlight = false;" in page
    assert "setAuthBusy(button, false, authSubmitLabel(authView));" in page
    assert "setAuthBusy(button, false, authResendLabel(authView));" in page
    assert 'button.setAttribute("aria-busy", "true");' in page
    assert 'button.removeAttribute("aria-busy");' in page
    assert 'button.setAttribute("aria-disabled", "true");' in page
    assert 'button.removeAttribute("aria-disabled");' in page

    view = function_body(page, "function setAuthView(view, note)")
    assert "authSubmitBusyToken += 1;" in view
    assert "authResendBusyToken += 1;" in view
    assert "authSubmitInFlight = false;" in view
    assert "authResendInFlight = false;" in view
    assert 'setAuthBusy($("authSubmit"), false, authSubmitLabel(view));' in view
    assert 'setAuthBusy($("authResend"), false, authResendLabel(view));' in view


def test_auth_focus_moves_to_the_view_title_and_semantics(client: TestClient) -> None:
    """The gate is a main landmark; a view change focuses its title, never an input."""
    page = client.get("/").text
    assert '<div class="auth" id="authScreen" hidden role="main" aria-labelledby="authTitle">' in page
    assert 'id="authTitle" tabindex="-1"' in page
    assert "function focusAuthTitle()" in page
    assert "if (!screen || screen.hidden || !title) return;" in page
    assert "focusWithoutScroll(title);" in page

    view = function_body(page, "function setAuthView(view, note)")
    assert "var viewChanged = view !== authView;" in view
    assert "if (viewChanged) {" in view
    assert "resetAuthScroll();" in view
    assert "focusAuthTitle();" in view
    show = function_body(page, "function showAuth(view, note)")
    assert "resetAuthScroll();" in show
    assert "focusAuthTitle();" in show

    assert "function syncGateInert()" in page
    assert 'app.setAttribute("inert", "")' in page
    assert 'app.setAttribute("aria-hidden", "true")' in page
    assert 'app.removeAttribute("inert")' in page
    assert 'app.removeAttribute("aria-hidden")' in page
    for signature in (
        "function showWelcome()",
        "function showAuth(view, note)",
        "function hideAuth()",
        "function showOptionalOnboarding()",
        "function hideOptionalOnboarding()",
    ):
        assert "syncGateInert();" in function_body(page, signature), signature

    assert "function focusAfterAuth()" in page
    assert 'onboardingTitle.setAttribute("tabindex", "-1");' in page
    assert 'var screen = $("screen-" + state.screen) || $("screen-home");' in page
    assert 'title.setAttribute("tabindex", "-1");' in page
    assert 'app.hasAttribute("inert")' in page
    for signature in (
        "function hideAuth()",
        "function showOptionalOnboarding()",
        "function hideOptionalOnboarding()",
    ):
        assert "focusAfterAuth();" in function_body(page, signature), signature


def test_auth_focus_visible_and_reduced_motion_styles(client: TestClient) -> None:
    """Interactive auth controls keep a consistent focus ring; Reduce Motion removes transitions."""
    page = client.get("/").text
    auth_css = page[page.index("/* ---------- sign in ---------- */"):page.index("/* ---------- first-visit welcome ---------- */")]
    assert ".auth button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }" in auth_css
    assert ".auth-title:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }" in auth_css
    assert ".field:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }" in page
    assert "@media (prefers-reduced-motion: reduce) {" in auth_css
    # This selector must out-specify the global `button:not(.tab):not(.tab-add)` press transition.
    assert ".auth button:not(.tab):not(.tab-add), .auth .field { transition: none; }" in auth_css
    assert 'behavior: reducedMotion() ? "auto" : "smooth"' in page
    assert "function reducedMotion()" in page


def test_auth_contrast_tokens_meet_wcag_aa(client: TestClient) -> None:
    """The light/dark auth palette meets WCAG AA without changing typography or layout.

    Method: read the served CSS variables, composite any alpha over the opaque background, then apply
    the WCAG 2.1 relative-luminance formula. Normal text needs 4.5:1; large text and non-text UI/focus
    indicators need 3:1. The four previously failing samples are labels, the Google note, and the primary
    button text in both themes.
    """
    page = client.get("/").text
    light, dark = theme_tokens(page)

    def ratio(tokens: dict[str, str], fg: str, bg: str) -> float:
        return contrast_ratio(parse_css_colour(tokens[fg]), parse_css_colour(tokens[bg]))

    for tokens, name in ((light, "light"), (dark, "dark")):
        assert ratio(tokens, "--muted", "--bg") >= 4.5, f"{name}: muted text on the page"
        assert ratio(tokens, "--muted", "--card") >= 4.5, f"{name}: muted text on a card"
        assert ratio(tokens, "--accent", "--bg") >= 4.5, f"{name}: accent text on the page"
        assert ratio(tokens, "--accent", "--card") >= 4.5, f"{name}: accent text on a card"
        assert ratio(tokens, "--on-accent", "--accent-fill") >= 4.5, f"{name}: primary button text"
        assert ratio(tokens, "--accent", "--bg") >= 3.0, f"{name}: focus ring on the page"
        assert ratio(tokens, "--accent", "--card") >= 3.0, f"{name}: focus ring on a card"
        assert ratio(tokens, "--accent-fill", "--bg") >= 3.0, f"{name}: filled control on the page"
        assert ratio(tokens, "--accent-fill", "--card") >= 3.0, f"{name}: filled control on a card"

    # The tested tokens are the ones the four affected elements actually use.
    assert re.search(r"\.form-label \{[^}]*color: var\(--muted\);", page)
    assert re.search(r"\.auth-google-note \{[^}]*color: var\(--muted\);", page)
    assert re.search(r"\.btn-primary \{[^}]*background: var\(--accent-fill\); color: var\(--on-accent\);", page)


def test_auth_loading_and_disabled_states_keep_text_readable(client: TestClient) -> None:
    """Busy auth controls keep full-opacity text; the disabled Google note remains readable.

    The busy label changes, so dimming the whole button is unnecessary and was what pushed white-on-blue
    below 4.5:1. The Google button itself is an inactive control (WCAG exempt), but its explanatory note
    is not, so the note is covered by the muted-token test above.
    """
    page = client.get("/").text
    auth_css = page[page.index("/* ---------- sign in ---------- */"):page.index("/* ---------- first-visit welcome ---------- */")]

    busy_rule = re.search(r'\.auth button\[aria-disabled="true"\]\s*\{([^}]*)\}', auth_css)
    assert busy_rule is not None
    assert "opacity" not in busy_rule.group(1), "loading must not dim the whole button"
    assert "cursor: progress" in busy_rule.group(1)
    assert '.auth .btn-primary[aria-busy="true"] { opacity: 1; }' in auth_css
    assert '.auth-card .auth-link[aria-busy="true"] { color: var(--muted); }' in auth_css
    assert ".auth-google[disabled] { opacity: .7; cursor: not-allowed; }" in page

    # Typography and layout are unchanged by the colour-only remediation.
    assert re.search(r"\.auth-card \.form-label \{[^}]*font-size: 12px;", page)
    assert re.search(r"\.auth-google-note \{[^}]*font-size: 12px;", page)
    assert re.search(r"\.auth-submit \{[^}]*font-size: 16px;", page)
    assert "height: 52px; min-height: 52px;" in page


def test_auth_ids_labels_and_aria_controls_are_consistent(client: TestClient) -> None:
    """No duplicate IDs, every auth label points at a field, and toggles control their inputs."""
    page = client.get("/").text
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids)), "duplicate IDs in the page"

    auth = page[page.index('<div class="auth" id="authScreen"'):page.index('<div class="onboarding"')]
    for field in ("authEmail", "authPassword", "authPassword2"):
        assert f'<label class="form-label" for="{field}"' in auth
        assert f'id="{field}"' in auth
    for toggle, target in (("authPasswordToggle", "authPassword"), ("authPassword2Toggle", "authPassword2")):
        assert f'id="{toggle}"' in auth
        assert f'aria-controls="{target}"' in auth
    assert 'aria-labelledby="authTitle"' in auth


def test_hidden_auth_controls_are_hidden_from_assistive_tech(client: TestClient) -> None:
    """Inactive fields and controls use the hidden attribute, not just visual CSS."""
    page = client.get("/").text
    for marker in (
        'id="authPassword2"',
        'id="authPassword2Toggle"',
        'id="authResend"',
        'id="authBack"',
        'id="authPasswordHint"',
        'id="authPassword2Hint"',
    ):
        start = page.index(marker)
        tag = page[start:page.index(">", start)]
        assert "hidden" in tag, marker
    assert 'id="authGoogle" type="button" disabled' in page


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
    """Focus reveal and reset are instant under Reduce Motion, smooth otherwise."""
    page = client.get("/").text
    assert "AUTH_REVEAL_DELAY_MS = 250" in page
    assert 'input.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" })' in page
    assert "function resetAuthScroll()" in page
    assert "document.activeElement !== input) return;" in page, "a stale timer must not scroll"
    # leaving the form (not moving between its fields) is what returns to the top
    assert 'if (!authFormHasFocus()) resetAuthScroll();' in page
    assert 'visualViewport.addEventListener("resize"' in page, "the keyboard can close without a blur"
    assert 'scroller.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" })' in page
    assert 'window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" })' in page


def test_the_sign_in_screen_is_present_in_the_page(client: TestClient) -> None:
    page = client.get("/").text
    for element in (
        'id="authScreen"', 'id="authEmail"', 'id="authPassword"', 'id="authPassword2"',
        'id="authSubmit"', 'id="authForgot"', 'id="authBack"', 'id="accountEmail"', 'id="signOutBtn"',
    ):
        assert element in page, element + " is missing"
    # Public registration replaces the old invite-only copy. Signup controls and validation
    # are covered by the dedicated public-onboarding static contract tests.
    assert "Duits is invite only" not in page


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
        "/auth/v1/verify",
        "/auth/v1/recover",
        "/auth/v1/resend",
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
    # GoTrue reads redirect_to from the query string (r.Form); a JSON body field is ignored for a JSON
    # request, which is what the old call silently did.
    assert '"/auth/v1/recover?redirect_to=" + encodeURIComponent(redirectTarget())' in page
    assert "redirect_to: redirectTarget()" not in page
    assert 'return window.location.origin + "/";' in page
    assert "window.location.origin + window.location.pathname" not in page


def test_recover_answers_with_one_generic_message(client: TestClient) -> None:
    """Sent or not, the answer is the same, so the form cannot be used to test which addresses exist."""
    page = client.get("/").text
    assert 'If that address has an account, a link is on its way.' in page
    submit = function_body(page, "async function submitAuth()")
    body = submit[submit.index('if (authView === "forgot")'):submit.index('if (authView === "setpassword")')]
    # Both outcomes share one call and one message: `sent.ok ? generic : generic`.
    assert body.count('setAuthView("forgot", sent.ok') == 1
    assert "sent.ok" in body and "authError(sent)" in body


def test_an_invite_sign_in_shows_the_real_address(client: TestClient) -> None:
    """Settings must name the account after a verified link, not "Not signed in".

    The session built from /verify takes the address from the response's user object, with the access
    token's own claims as a fallback. A blank address is never stored.
    """
    page = client.get("/").text
    assert "function emailFromToken(token)" in page
    mapper = function_body(page, "function sessionFromAuthBody(body, now, emailFromToken)")
    assert "(body.user && body.user.email)" in mapper
    assert "emailFromToken ? emailFromToken(body.access_token)" in mapper
    assert 'email: ""' not in page, "the link path must not store a blank address"
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
    assert "?token=" not in page
    assert "console.log" not in page, "nothing may be logged: the page holds live tokens"
    # Auth keys are removed from the query and fragment; unrelated parameters are preserved.
    assert "function removeAuthKeys(value)" in page
    assert 'window.history.replaceState(null, "", window.location.pathname +' in page
    # The token hash is held in memory only: no storage call may mention it. The OAuth PKCE verifier
    # is the one allowed sessionStorage record; it is never a session and never touches localStorage.
    oauth = page[page.index("/* ---------- oauth pkce core"):page.index("/* ---------- end oauth pkce core")]
    assert "duits.auth.oauth" in page and "sessionStorage" in page
    assert "localStorage" not in oauth
    for line in page.splitlines():
        if "token_hash" in line:
            assert "localStorage" not in line, f"token_hash must not touch storage: {line.strip()}"


def test_auth_links_are_read_from_the_query_and_stripped_before_any_request(client: TestClient) -> None:
    """The token is read from ?token_hash= and the address bar is rewritten before anything is sent."""
    page = client.get("/").text
    reader = function_body(page, "function readAuthLink(search, hash)")
    assert "hasOwn(AUTH_LINK_TYPES, type)" in reader, "own keys only; prototype keys never pass"
    assert "normalizeAuthLinkType(q.type)" in reader
    assert "q.token_hash" in reader
    assert "writeSession" not in reader, "reading a link must not create a session"

    begin = function_body(page, "function begin(search, hash)")
    assert "deps.cleanUrl()" in begin, "the URL is cleaned when the link is read"
    assert "deps.request(" not in begin, "no verification request may be sent on page load"
    assert "pending = { tokenHash: link.tokenHash, type: link.type };" in begin

    verify = function_body(page, "function verify()")
    assert "var body = { type: type, token_hash: pending.tokenHash };" in verify, "the documented payload"
    assert "redirect_to:" not in verify, "GoTrue rejects redirect_to with token_hash"
    assert "deps.writeSession(session)" in verify
    assert "pending = null;" in verify, "the token is single-use in memory"


def test_verification_requires_an_explicit_tap(client: TestClient) -> None:
    page = client.get("/").text
    start = function_body(page, "async function start()")
    assert "authLink.begin(" in start, "the link is read at startup"
    assert "authLink.verify(" not in start, "boot must never verify a link"
    restore = function_body(page, "async function restoreSession(link, oauth)")
    assert "authLink.verify(" not in restore, "boot must never verify a link"
    submit = function_body(page, "async function submitAuth()")
    assert 'authView === "link-signup"' in submit
    assert "await verifyPendingLink();" in submit
    verify_link = function_body(page, "async function verifyPendingLink()")
    assert "await authLink.verify();" in verify_link
    assert "authGuard.begin()" in verify_link
    assert "authGuard.current(epoch)" in verify_link
    assert 'if (result.type === "signup")' in verify_link
    assert "await afterSignIn(result.session, true);" in verify_link
    assert "pendingAuthSession = result.session;" in verify_link
    assert 'setAuthView("setpassword"' in verify_link, "recovery and invite choose a password first"


def test_no_session_is_ever_adopted_from_a_fragment(client: TestClient) -> None:
    """The implicit-flow parser is gone: a fragment with tokens is reported, never stored."""
    page = client.get("/").text
    assert "parseAuthHash" not in page and "readAuthRedirect" not in page
    assert "params.access_token" not in page and "params.refresh_token" not in page
    reader = function_body(page, "function readAuthLink(search, hash)")
    assert 'return { kind: "invalid", reason: "legacy", clean: true };' in reader
    assert "h.access_token" in reader and "h.refresh_token" in reader
    assert "writeSession" not in reader


def test_malformed_auth_parameters_cannot_break_boot(client: TestClient) -> None:
    """A bad escape, a repeated key or a missing type is rejected, not thrown out of restoreSession."""
    page = client.get("/").text
    parser = function_body(page, "function parseQuery(value)")
    assert "decodeURIComponent(" in parser and "catch (error)" in parser
    assert "duplicates[key] = true" in parser
    reader = function_body(page, "function readAuthLink(search, hash)")
    assert "parseQuery(search)" in reader and "parseQuery(hash)" in reader
    assert "decodeURIComponent(" not in reader, "the reader must not decode unguarded"
    start = function_body(page, "async function start()")
    assert "authLink.begin(" in start


def test_expired_link_offers_a_new_confirmation_and_a_reset(client: TestClient) -> None:
    page = client.get("/").text
    view = function_body(page, "function setAuthView(view, note)")
    assert '"link-signup": "Confirm your email"' in view
    assert '"link-recovery": "Reset your password"' in view
    assert '"link-invite": "Accept your invitation"' in view
    assert "This link can't be used" in view
    resend_label = function_body(page, "function authResendLabel(view)")
    assert 'return view === "expired" ? "Send a new confirmation email" : "Resend confirmation email";' in resend_label
    assert "Send a password reset link" in view
    error = function_body(page, "function showLinkError(kind)")
    assert 'showAuth("expired"' in error
    assert 'setAuthView(authView, authLinkMessage(kind))' in error, "retryable failures keep the link screen"
    assert 'kind === "expired" || kind === "invalid" || kind === "legacy"' in error
    assert "ask the person who invited you to send a new one" in error, (
        "there is no invite resend endpoint; the inviter must issue a new invitation")
    # A network or 5xx failure is not in the dead-link list; it stays retryable.
    dead = error[error.index("if (kind === "):error.index("showAuth(")]
    assert '"network"' not in dead and '"server"' not in dead and '"rate"' not in dead


def test_a_bad_link_does_not_clear_a_valid_session(client: TestClient) -> None:
    """A stale or crafted link must not sign out a browser that already has a working session."""
    page = client.get("/").text
    restore = function_body(page, "async function restoreSession(link, oauth)")
    invalid = restore[restore.index('if (link.kind === "invalid")'):restore.index("var session = readSession();")]
    assert "writeSession(" not in invalid, "no link path may touch a valid stored session"
    assert "hideAuth();" in invalid, "the existing session keeps the app open"
    assert "reloadScreen();" in invalid


def test_password_update_uses_the_verified_session_not_shared_storage(client: TestClient) -> None:
    """The credential is the session /verify returned, held in page memory; storage is not re-read."""
    page = client.get("/").text
    submit = function_body(page, "async function submitAuth()")
    block = submit[submit.index('if (authView === "setpassword")'):submit.index('if (authView === "confirmation"')]
    assert "var verified = pendingAuthSession;" in block
    assert "updatePasswordForSession(verified, password" in block
    assert "readSession()" not in block, "never re-read the shared session as the credential"
    assert 'authRequest("PUT", "/auth/v1/user"' not in block, "the PUT lives in the tested core helper"
    helper = function_body(page, "async function updatePasswordForSession(verified, password, deps)")
    assert "session.access_token" in helper
    assert "readSession" not in helper
    assert "deps.refresh(session)" in helper
    # The refresh uses the retained refresh token and rejects a different identity.
    refresh = function_body(page, "async function refreshVerifiedSession(verified)")
    assert "verified.refresh_token" in refresh
    assert "sameVerifiedEmail(verified.email, next.email)" in refresh
    assert "readSession()" not in refresh


def test_back_cancels_the_link_and_invalidates_late_responses(client: TestClient) -> None:
    page = client.get("/").text
    back = function_body(page, "function backFromAuth()")
    assert "authGuard.cancel();" in back
    assert "authLink.cancel();" in back
    assert "clearPendingAuth();" in back
    verify_link = function_body(page, "async function verifyPendingLink()")
    assert verify_link.index("await authLink.verify();") < verify_link.index("authGuard.current(epoch)")
    submit = function_body(page, "async function submitAuth()")
    block = submit[submit.index('if (authView === "setpassword")'):submit.index('if (authView === "confirmation"')]
    assert block.index("await updatePasswordForSession(") < block.index("authGuard.current(epoch)")
    assert "pendingAuthSession !== verified" in block
    # Sign-out also abandons any link flow.
    signout = function_body(page, "async function signOut()")
    assert "authGuard.cancel();" in signout and "authLink.cancel();" in signout


def test_type_email_is_normalized_to_signup(client: TestClient) -> None:
    page = client.get("/").text
    assert 'var AUTH_LINK_ALIASES = { email: "signup" };' in page
    reader = function_body(page, "function readAuthLink(search, hash)")
    assert "normalizeAuthLinkType(q.type)" in reader
    assert "hasOwn(AUTH_LINK_TYPES, type)" in reader
    helper = function_body(page, "function normalizeAuthLinkType(type)")
    assert "AUTH_LINK_ALIASES[type]" in helper


def test_query_only_tokens_are_cleaned_but_never_adopted(client: TestClient) -> None:
    page = client.get("/").text
    assert '["access_token", "refresh_token", "expires_at", "token_type", "sb"]' in page
    reader = function_body(page, "function readAuthLink(search, hash)")
    assert "AUTH_CLEAN_KEYS.some" in reader
    assert "writeSession" not in reader
    cleaner = function_body(page, "function removeAuthKeys(value)")
    assert "AUTH_CLEAN_KEYS.indexOf(key) === -1" in cleaner


def test_auth_link_cleanup_preserves_unrelated_parameters_and_fragments(client: TestClient) -> None:
    page = client.get("/").text
    cleaner = function_body(page, "function cleanAuthUrl()")
    assert "removeAuthKeys(window.location.search)" in cleaner
    assert "removeAuthKeys(window.location.hash)" in cleaner
    assert '(query ? "?" + query : "")' in cleaner
    assert '(hash ? "#" + hash : "")' in cleaner


def test_prototype_keys_are_not_auth_link_types(client: TestClient) -> None:
    page = client.get("/").text
    reader = function_body(page, "function readAuthLink(search, hash)")
    assert "hasOwn(AUTH_LINK_TYPES, type)" in reader
    helper = function_body(page, "function hasOwn(object, key)")
    assert "Object.prototype.hasOwnProperty.call(object, key)" in helper


def test_cancellation_and_concurrent_verification_exist_in_the_core(client: TestClient) -> None:
    page = client.get("/").text
    flow = function_body(page, "function createAuthLinkFlow(deps)")
    assert "function cancel()" in flow
    assert "generation += 1;" in flow
    assert 'if (inFlight) return { ok: false, kind: "busy" };' in flow
    assert 'if (mine !== generation) return { ok: false, kind: "cancelled" };' in flow


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
