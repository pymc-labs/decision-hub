#!/bin/sh
# Decision Hub CLI installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/pymc-labs/decision-hub/main/install.sh | sh
#
# Options (environment variables):
#   DHUB_NO_MODIFY_PATH=1  Skip PATH modifications
#   DHUB_INSTALL_UV=0      Skip uv installation even if missing
#
# This script:
#   1. Installs uv (https://docs.astral.sh/uv/) if not already present
#   2. Installs dhub-cli from PyPI via `uv tool install`
#   3. Ensures ~/.local/bin is on PATH (edits shell rc files if needed)
#
# Supports Linux (glibc/musl) and macOS (Intel/Apple Silicon).
# Requires: curl or wget, sh-compatible shell.

set -u

# --- Output helpers -------------------------------------------------------

_tty_bold=""
_tty_blue=""
_tty_green=""
_tty_red=""
_tty_yellow=""
_tty_reset=""

setup_colors() {
    if [ -t 1 ]; then
        _tty_bold="\033[1m"
        _tty_blue="\033[34m"
        _tty_green="\033[32m"
        _tty_red="\033[31m"
        _tty_yellow="\033[33m"
        _tty_reset="\033[0m"
    fi
}

info() {
    printf "${_tty_blue}${_tty_bold}==>${_tty_reset} ${_tty_bold}%s${_tty_reset}\n" "$1"
}

success() {
    printf "${_tty_green}${_tty_bold}==>${_tty_reset} ${_tty_bold}%s${_tty_reset}\n" "$1"
}

warn() {
    printf "${_tty_yellow}warning:${_tty_reset} %s\n" "$1" >&2
}

err() {
    printf "${_tty_red}error:${_tty_reset} %s\n" "$1" >&2
}

# --- Utility helpers -------------------------------------------------------

check_cmd() {
    command -v "$1" > /dev/null 2>&1
}

need_cmd() {
    if ! check_cmd "$1"; then
        err "required command not found: $1"
        exit 1
    fi
}

# --- PATH helpers -----------------------------------------------------------

# Resolve the uv tool bin directory.
# uv tool install places binaries in ~/.local/bin by default.
get_bin_dir() {
    if check_cmd uv; then
        _dir="$(uv tool dir --bin 2>/dev/null)" || true
        if [ -n "${_dir:-}" ] && [ -d "$_dir" ]; then
            printf '%s' "$_dir"
            return
        fi
    fi
    printf '%s' "$HOME/.local/bin"
}

# Check if a directory is already on PATH.
is_on_path() {
    case ":$PATH:" in
        *":$1:"*) return 0 ;;
        *)        return 1 ;;
    esac
}

# Add bin dir to shell rc files so it persists across sessions.
ensure_on_path() {
    _bin_dir="$1"

    if is_on_path "$_bin_dir"; then
        return 0
    fi

    if [ "${DHUB_NO_MODIFY_PATH:-0}" = "1" ]; then
        warn "$_bin_dir is not on PATH (skipping modification due to DHUB_NO_MODIFY_PATH=1)"
        return 0
    fi

    _line="export PATH=\"$_bin_dir:\$PATH\""
    _added=0

    for _rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if [ -f "$_rc" ]; then
            # Don't add if already present
            if grep -qF "$_bin_dir" "$_rc" 2>/dev/null; then
                continue
            fi
            printf '\n# Added by Decision Hub installer\n%s\n' "$_line" >> "$_rc"
            _added=1
        fi
    done

    # If no rc file existed, create .profile
    if [ "$_added" = "0" ]; then
        printf '# Added by Decision Hub installer\n%s\n' "$_line" >> "$HOME/.profile"
    fi

    # Also add to current session
    export PATH="$_bin_dir:$PATH"

    info "Added $_bin_dir to PATH in shell config"
}

# --- uv installation -------------------------------------------------------

install_uv() {
    if check_cmd uv; then
        info "uv is already installed ($(uv --version))"
        return 0
    fi

    if [ "${DHUB_INSTALL_UV:-1}" = "0" ]; then
        err "uv is not installed and DHUB_INSTALL_UV=0 was set"
        err "Install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    info "Installing uv (Python package manager)..."

    if check_cmd curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif check_cmd wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        err "curl or wget is required to install uv"
        exit 1
    fi

    # uv installer adds to ~/.local/bin or ~/.cargo/bin — make sure it's on PATH
    for _candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        if [ -x "$_candidate/uv" ]; then
            if ! is_on_path "$_candidate"; then
                export PATH="$_candidate:$PATH"
            fi
            break
        fi
    done

    if ! check_cmd uv; then
        err "uv installation failed — uv not found on PATH after install"
        err "Try installing uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    success "uv installed ($(uv --version))"
}

# --- dhub-cli installation --------------------------------------------------

install_dhub() {
    if check_cmd dhub; then
        _current_version="$(dhub --version 2>/dev/null || echo 'unknown')"
        info "Upgrading dhub-cli (current: $_current_version)..."
        uv tool install --upgrade dhub-cli
    else
        info "Installing dhub-cli from PyPI..."
        uv tool install dhub-cli
    fi

    if ! check_cmd dhub; then
        # Maybe the bin dir isn't on PATH yet
        _bin_dir="$(get_bin_dir)"
        if [ -x "$_bin_dir/dhub" ]; then
            export PATH="$_bin_dir:$PATH"
        fi
    fi

    if ! check_cmd dhub; then
        err "dhub-cli installation failed — 'dhub' command not found on PATH"
        exit 1
    fi

    success "dhub-cli installed ($(dhub --version 2>/dev/null || echo 'unknown'))"
}

# --- Main -------------------------------------------------------------------

main() {
    setup_colors

    printf "\n"
    printf "${_tty_bold}  Decision Hub CLI Installer${_tty_reset}\n"
    printf "  https://github.com/pymc-labs/decision-hub\n"
    printf "\n"

    need_cmd mkdir
    need_cmd chmod

    # Step 1: Ensure uv is available
    install_uv

    # Step 2: Install dhub-cli
    install_dhub

    # Step 3: Ensure bin directory is on PATH
    _bin_dir="$(get_bin_dir)"
    ensure_on_path "$_bin_dir"

    printf "\n"
    success "Installation complete!"
    printf "\n"
    printf "  Run ${_tty_bold}dhub login${_tty_reset} to get started.\n"
    printf "\n"

    if ! is_on_path "$_bin_dir"; then
        printf "  ${_tty_yellow}Restart your shell or run:${_tty_reset}\n"
        printf "    export PATH=\"%s:\$PATH\"\n" "$_bin_dir"
        printf "\n"
    fi
}

main "$@"
