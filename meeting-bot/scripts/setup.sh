#!/usr/bin/env bash
#
# One-shot local setup for the meeting bot.
#
#   ./scripts/setup.sh              full setup
#   ./scripts/setup.sh --login      only (re)do the Google sign-in
#   ./scripts/setup.sh --check      verify an existing setup, change nothing
#
# Everything here is idempotent: re-running skips what is already done.
#
# The Google sign-in step is interactive by necessity — a browser window opens
# and waits for you. Everything before it is unattended.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV="${VENV:-$PROJECT_ROOT/.venv}"
PY="$VENV/bin/python"
PROFILE_DIR="${PROFILE_DIR:-$PROJECT_ROOT/chrome_profile}"

MODE="all"
[[ "${1:-}" == "--login" ]] && MODE="login"
[[ "${1:-}" == "--check" ]] && MODE="check"

# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

if [[ -t 1 ]]; then
    BOLD=$'\e[1m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; DIM=$'\e[2m'; OFF=$'\e[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; DIM=""; OFF=""
fi

step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$OFF"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$OFF" "$1"; }
bad()  { printf '    %s✗%s %s\n' "$RED" "$OFF" "$1"; }
note() { printf '      %s%s%s\n' "$DIM" "$1" "$OFF"; }

FAILED=0

# --------------------------------------------------------------------------
# 1. Python environment
# --------------------------------------------------------------------------

setup_venv() {
    step "Python environment"

    if [[ ! -x "$PY" ]]; then
        python3 -m venv "$VENV"
        ok "created $VENV"
    else
        ok "using $VENV"
    fi

    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -e ".[dev]"
    ok "dependencies installed"
}

# --------------------------------------------------------------------------
# 2. Chromium
#
# The browser build is tied to the installed Playwright version. Mixing them
# fails at launch with "Executable doesn't exist", which surfaces as a failed
# join rather than a setup error — so install through Playwright itself and let
# it pick the matching build.
# --------------------------------------------------------------------------

setup_chromium() {
    step "Chromium (via Playwright)"

    local version
    version="$("$PY" -m pip show playwright 2>/dev/null | awk '/^Version:/{print $2}')"
    ok "playwright $version"

    # --with-deps needs root for the system libraries; fall back without it.
    if "$VENV/bin/playwright" install --with-deps chromium >/dev/null 2>&1; then
        ok "chromium installed (with system dependencies)"
    elif "$VENV/bin/playwright" install chromium >/dev/null 2>&1; then
        ok "chromium installed"
        note "system libraries not installed — if launch fails, run:"
        note "  sudo $VENV/bin/playwright install-deps chromium"
    else
        bad "chromium install failed"
        FAILED=1
    fi
}

# --------------------------------------------------------------------------
# 3. Configuration
# --------------------------------------------------------------------------

setup_env() {
    step "Configuration"

    if [[ -f .env ]]; then
        ok ".env present (left untouched)"
    else
        cp .env.example .env
        ok "created .env from .env.example"
        warn "set CW_UTILS_URL and PROJECT_ID before recording"
    fi

    # WEBSOCKET_URL pointing at this process is a leftover from the previous
    # architecture, which hosted its own Socket.IO server. This build is a
    # client only, so that address answers 404 and audio would buffer, then
    # drop, producing no recording and no error until the very end.
    if grep -qE '^WEBSOCKET_URL=https?://(localhost|127\.0\.0\.1)' .env 2>/dev/null; then
        warn "WEBSOCKET_URL points at this machine — there is no local audio service"
        note "for local testing set:  RECORDING_UPLOAD_TRANSPORT=direct"
        note "or point WEBSOCKET_URL at the deployed audio service"
    fi
}

# --------------------------------------------------------------------------
# 4. Google sign-in
#
# Without a profile the bot joins as a guest and a host must admit it. With one
# it joins as that account and is usually admitted automatically.
# --------------------------------------------------------------------------

setup_login() {
    step "Google sign-in"

    if [[ -d "$PROFILE_DIR" && -n "$(ls -A "$PROFILE_DIR" 2>/dev/null)" && "$MODE" != "login" ]]; then
        ok "profile already exists at $PROFILE_DIR"
        note "re-run with --login to sign in as a different account"
        return
    fi

    if [[ -z "${DISPLAY:-}" ]]; then
        bad "no DISPLAY — signing in needs a visible browser window"
        note "run this on a desktop session, or use X forwarding"
        FAILED=1
        return
    fi

    # A profile left locked by a killed browser stops Chromium starting at all.
    rm -f "$PROFILE_DIR"/Singleton* 2>/dev/null || true

    printf '    a browser window will open — sign in, then press Enter here\n'
    "$PY" scripts/create_auth_profile.py --profile-dir "$PROFILE_DIR"
}

# --------------------------------------------------------------------------
# 5. Verify
# --------------------------------------------------------------------------

check_all() {
    step "Verification"

    [[ -x "$PY" ]] && ok "virtualenv" || { bad "virtualenv missing"; FAILED=1; }

    if "$PY" -c "import fastapi, playwright, socketio, redis" 2>/dev/null; then
        ok "dependencies importable"
    else
        bad "dependencies missing — run without --check"
        FAILED=1
    fi

    # Ask Playwright for the path it will actually use, rather than guessing.
    if "$PY" - <<'PY' 2>/dev/null
import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    sys.exit(0 if __import__("pathlib").Path(p.chromium.executable_path).exists() else 1)
PY
    then
        ok "chromium executable present"
    else
        bad "chromium missing or version-mismatched"
        note "fix: $VENV/bin/playwright install chromium"
        FAILED=1
    fi

    [[ -f .env ]] && ok ".env present" || { bad ".env missing"; FAILED=1; }

    if [[ -d "$PROFILE_DIR" && -n "$(ls -A "$PROFILE_DIR" 2>/dev/null)" ]]; then
        ok "browser profile present — joins as the signed-in account"
    else
        warn "no browser profile — joins as a guest, so a host must admit the bot"
        note "fix: ./scripts/setup.sh --login"
    fi

    if command -v redis-cli >/dev/null && [[ "$(redis-cli ping 2>/dev/null)" == "PONG" ]]; then
        ok "redis reachable"
    else
        warn "redis not reachable — meeting history falls back to memory (meetings still run)"
    fi

    # Config is the authority on where things resolve to; ask it rather than assume.
    "$PY" - <<'PY' 2>/dev/null || true
import sys
sys.path.insert(0, ".")
from app.core.config import Settings
s = Settings()
print(f"      profile dir : {s.browser.profile_dir}")
print(f"      CW backend  : {'set' if s.cw_utils.enabled else 'NOT SET — recordings cannot be stored'}")
print(f"      project id  : {s.project.default_project_id or 'NOT SET — every join must pass projectId'}")
print(f"      transport   : {s.recording.upload_transport}")
PY
}

# --------------------------------------------------------------------------

case "$MODE" in
    login) setup_login ;;
    check) check_all ;;
    all)
        setup_venv
        setup_chromium
        setup_env
        setup_login
        check_all
        ;;
esac

if [[ "$FAILED" -eq 0 ]]; then
    step "Ready"
    printf '    start the server:  %smake run%s\n' "$BOLD" "$OFF"
    printf '    or:                %s.venv/bin/python -m app.main%s\n' "$BOLD" "$OFF"
    printf '    API docs:          http://localhost:5000/api/meet/docs\n'
else
    step "Setup incomplete — see the failures above"
    exit 1
fi
