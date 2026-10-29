#!/usr/bin/env bash

# Mistral Vibe fork installer.
#
# Installs this checkout (or a remote ref of the fork) as the `mistral-vibe`
# uv tool, replacing an existing uv installation of Vibe. The user config under
# ~/.vibe and the current project are left untouched.
#
# Typical use:
#   curl -fsSL https://raw.githubusercontent.com/Blackmanx/mistral-vibe/main/install.sh | bash
#
# From a checkout:
#   ./install.sh
#
# Overrides:
#   VIBE_REPO_URL   Git remote to clone      (default: the fork)
#   VIBE_REF        Branch/tag to install     (default: main)
#   VIBE_SRC_DIR    Managed checkout          (default: ~/.local/share/mistral-vibe-fork)
#   VIBE_PYTHON     Python for the tool env   (default: cpython-3.14+gil)
#   VIBE_SOURCE     Local path or git URL to install instead

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Bump together when updating uv (matches scripts/install.sh).
UV_INSTALLER_VERSION="0.11.26"
UV_INSTALLER_SHA256="92fa9085d24c214bb4445cc1da8c15ca9cca8cffb34726240fa08c5302e94ccc"

DEFAULT_REPO_URL="https://github.com/Blackmanx/mistral-vibe.git"
REPO_URL="${VIBE_REPO_URL:-$DEFAULT_REPO_URL}"
REF="${VIBE_REF:-main}"
PYTHON_SPEC="${VIBE_PYTHON:-cpython-3.14+gil}"
SOURCE_OVERRIDE="${VIBE_SOURCE:-}"
INSTALL_RUST=1
SOURCE=""
WORK_DIR=""
WHEEL=""

function error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

function info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

function success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

function warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

function usage() {
    cat <<'EOF'
Install the Mistral Vibe fork as the `mistral-vibe` uv tool.

Usage:
  install.sh [options]

Options:
  --source PATH|URL   Install this checkout or git URL instead of cloning.
  --repo URL          Git remote to clone (default: Blackmanx/mistral-vibe).
  --ref REF           Branch or tag to install (default: main).
  --python SPEC       Python for the tool environment (default: cpython-3.14+gil).
  --no-rust-install   Fail instead of installing Rust when cargo is missing.
  --clean             Remove the managed checkout before cloning.
  -h, --help          Show this help.

Environment:
  VIBE_SOURCE, VIBE_REPO_URL, VIBE_REF, VIBE_SRC_DIR, VIBE_PYTHON
EOF
}

function cleanup() {
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT

function check_platform() {
    case "$(uname -s)" in
        Linux|Darwin) ;;
        *)
            error "Unsupported platform: $(uname -s). Use Linux or macOS."
            exit 1
            ;;
    esac
}

function require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        error "$1 is required but was not found on PATH."
        exit 1
    fi
}

function sha256_of() {
    local file="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$file" | awk '{print $1}'
    else
        return 1
    fi
}

function install_uv() {
    info "Installing uv ${UV_INSTALLER_VERSION}..."
    require_command curl

    local installer="$WORK_DIR/uv-installer.sh"

    if ! curl -LsSf "https://astral.sh/uv/${UV_INSTALLER_VERSION}/install.sh" -o "$installer"; then
        error "Failed to download the uv installer."
        exit 1
    fi

    local actual
    if ! actual=$(sha256_of "$installer"); then
        error "No SHA-256 tool available to verify the uv installer."
        exit 1
    fi
    if [[ "$actual" != "$UV_INSTALLER_SHA256" ]]; then
        error "uv installer checksum mismatch; refusing to execute it."
        error "  expected: $UV_INSTALLER_SHA256"
        error "  actual:   $actual"
        exit 1
    fi

    if ! sh "$installer"; then
        error "Failed to install uv."
        exit 1
    fi

    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        error "uv was installed but is not on PATH. Add ~/.local/bin to PATH and retry."
        exit 1
    fi
    success "uv installed."
}

function ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        info "Using $(uv --version)"
        return
    fi
    install_uv
}

function ensure_rust() {
    if command -v cargo >/dev/null 2>&1; then
        info "Using $(cargo --version)"
        return
    fi
    if [[ "$INSTALL_RUST" -eq 0 ]]; then
        error "cargo is required to build this fork. Install Rust from https://rustup.rs and retry."
        exit 1
    fi

    info "Installing Rust with rustup (needed to build the fork)..."
    require_command curl
    local installer="$WORK_DIR/rustup.sh"
    if ! curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o "$installer"; then
        error "Failed to download rustup."
        exit 1
    fi
    if ! sh "$installer" -y --profile minimal; then
        error "Failed to install Rust."
        exit 1
    fi
    export PATH="$HOME/.cargo/bin:$PATH"
    if ! command -v cargo >/dev/null 2>&1; then
        error "Rust was installed but cargo is not on PATH. Add ~/.cargo/bin to PATH and retry."
        exit 1
    fi
    success "Rust installed."
}

function checkout_source() {
    local src_dir="${VIBE_SRC_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mistral-vibe-fork}"

    if [[ -n "$SOURCE_OVERRIDE" ]]; then
        case "$SOURCE_OVERRIDE" in
            *://*|git@*)
                REPO_URL="$SOURCE_OVERRIDE"
                ;;
            *)
                SOURCE=$(cd "$SOURCE_OVERRIDE" && pwd)
                if [[ ! -f "$SOURCE/pyproject.toml" ]]; then
                    error "No pyproject.toml in $SOURCE"
                    exit 1
                fi
                info "Installing local checkout: $SOURCE"
                return
                ;;
        esac
    fi

    # `curl | bash` has no script path. A checkout run does, and reuses itself.
    if [[ -z "$SOURCE_OVERRIDE" && -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
        local candidate
        candidate=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
        if [[ -f "$candidate/pyproject.toml" ]] &&
            grep -q 'name = "mistral-vibe"' "$candidate/pyproject.toml"; then
            SOURCE="$candidate"
            info "Installing this checkout: $SOURCE"
            return
        fi
    fi

    require_command git
    if [[ "$CLEAN" -eq 1 && -d "$src_dir" ]]; then
        info "Removing managed checkout $src_dir"
        rm -rf "$src_dir"
    fi

    if [[ -d "$src_dir/.git" ]]; then
        info "Updating managed checkout at $src_dir ($REF)..."
        git -C "$src_dir" fetch --depth 1 origin "$REF"
        git -C "$src_dir" checkout -q --detach FETCH_HEAD
        git -C "$src_dir" reset --hard -q FETCH_HEAD
    else
        info "Cloning $REPO_URL ($REF) into $src_dir..."
        mkdir -p "$(dirname "$src_dir")"
        git clone --depth 1 --branch "$REF" "$REPO_URL" "$src_dir"
    fi
    SOURCE="$src_dir"
}

function build_wheel() {
    local dist="$WORK_DIR/dist"
    mkdir -p "$dist"

    info "Building the wheel (compiles the Rust TUI and Harness; this can take a few minutes)..."
    (
        cd "$SOURCE"
        uv build --wheel --out-dir "$dist"
    )

    WHEEL=$(find "$dist" -maxdepth 1 -name '*.whl' -print -quit)
    if [[ -z "$WHEEL" || ! -f "$WHEEL" ]]; then
        error "The build did not produce a wheel."
        exit 1
    fi
}

function install_wheel() {
    info "Installing $WHEEL over the existing mistral-vibe tool..."
    if ! uv tool install --force --python "$PYTHON_SPEC" "$WHEEL"; then
        local base_python="${PYTHON_SPEC%%+*}"
        info "Python $PYTHON_SPEC is not available; installing $base_python..."
        uv python install "$base_python"
        uv tool install --force --python "$PYTHON_SPEC" "$WHEEL"
    fi
}

function report_installation() {
    local uv_bin_dir vibe_bin on_path
    uv_bin_dir=$(uv tool dir --bin)
    vibe_bin="$uv_bin_dir/vibe"

    if [[ ! -x "$vibe_bin" ]]; then
        error "The tool environment was installed but $vibe_bin is missing."
        exit 1
    fi

    "$vibe_bin" --version || {
        error "vibe was installed but did not start. Run '$vibe_bin --version' for details."
        exit 1
    }

    on_path=$(command -v vibe 2>/dev/null || true)
    echo
    if [[ -z "$on_path" ]]; then
        warning "vibe is installed at $vibe_bin but that directory is not on PATH."
        echo "Add it to your shell profile, then restart the terminal:"
        echo "  export PATH=\"$uv_bin_dir:\$PATH\""
    elif [[ "$on_path" != "$vibe_bin" ]]; then
        warning "A different vibe resolves first: $on_path"
        warning "This fork is installed at: $vibe_bin"
        echo "Put $uv_bin_dir before the other install in PATH, or remove the old one."
    else
        success "This fork is now the active vibe: $vibe_bin"
    fi

    echo
    echo "Your config and sessions under ~/.vibe were not touched."
    echo "Run: vibe"
}

function main() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --source)
                SOURCE_OVERRIDE="$2"
                shift 2
                ;;
            --repo)
                REPO_URL="$2"
                shift 2
                ;;
            --ref)
                REF="$2"
                shift 2
                ;;
            --python)
                PYTHON_SPEC="$2"
                shift 2
                ;;
            --no-rust-install)
                INSTALL_RUST=0
                shift
                ;;
            --clean)
                CLEAN=1
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                usage
                exit 2
                ;;
        esac
    done

    echo
    echo "Mistral Vibe fork installer"
    echo "==========================="
    echo

    check_platform
    WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/vibe-fork.XXXXXX")
    ensure_uv
    ensure_rust
    checkout_source
    build_wheel
    install_wheel
    report_installation
}

CLEAN="${CLEAN:-0}"
main "$@"
