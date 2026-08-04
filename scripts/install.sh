#!/usr/bin/env bash
set -euo pipefail

VERSION="latest"
ASSUME_YES=0
FORCE=0
ALLOW_DOWNGRADE=0
CLI_ONLY=0
SKILL_ONLY=0
NO_PATH=0
INSTALL_ROOT=""
CODEX_HOME_VALUE=""
REPOSITORY_URL="${STACKMARSHAL_REPOSITORY_URL:-https://github.com/Soph1yzzz/stackmarshal.git}"
RELEASE_BASE_PREFIX="${STACKMARSHAL_RELEASE_BASE_PREFIX:-https://github.com/Soph1yzzz/stackmarshal/releases/download}"

usage() {
    cat <<'EOF'
Usage: install.sh [options]

  --version vMAJOR.MINOR.PATCH  Install a specific stable version (default: latest)
  --yes                         Accept dependency and PATH prompts
  --force                       Back up and replace an unmanaged/modified Skill
  --allow-downgrade             Explicitly permit installing an older version
  --cli-only                    Install only the isolated CLI
  --skill-only                  Install only the Codex Skill
  --no-path                     Do not modify shell PATH configuration
  --install-root PATH           Override the managed application directory
  --codex-home PATH             Override CODEX_HOME
EOF
}

while (($#)); do
    case "$1" in
        --version) VERSION="${2:?--version requires a value}"; shift 2 ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --force) FORCE=1; shift ;;
        --allow-downgrade) ALLOW_DOWNGRADE=1; shift ;;
        --cli-only) CLI_ONLY=1; shift ;;
        --skill-only) SKILL_ONLY=1; shift ;;
        --no-path) NO_PATH=1; shift ;;
        --install-root) INSTALL_ROOT="${2:?--install-root requires a value}"; shift 2 ;;
        --codex-home) CODEX_HOME_VALUE="${2:?--codex-home requires a value}"; shift 2 ;;
        --repository-url) REPOSITORY_URL="${2:?--repository-url requires a value}"; shift 2 ;;
        --release-base-prefix) RELEASE_BASE_PREFIX="${2:?--release-base-prefix requires a value}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

if ((CLI_ONLY && SKILL_ONLY)); then
    printf '%s\n' '--cli-only and --skill-only cannot be combined.' >&2
    exit 2
fi

confirm_action() {
    local message=$1 answer
    if ((ASSUME_YES)); then
        return 0
    fi
    if [[ ! -r /dev/tty ]]; then
        return 1
    fi
    printf '%s [y/N] ' "$message" >/dev/tty
    IFS= read -r answer </dev/tty || return 1
    [[ ${answer,,} == "y" || ${answer,,} == "yes" ]]
}

run_admin() {
    if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        "$@"
    elif sudo_exe=$(type -P sudo 2>/dev/null); then
        "$sudo_exe" "$@"
    else
        printf 'Administrator privileges are required to install %s.\n' "$1" >&2
        return 1
    fi
}

install_git() {
    local system
    system=$(uname -s)
    case "$system" in
        Darwin)
            if brew_exe=$(type -P brew 2>/dev/null); then
                "$brew_exe" install git
            else
                xcode-select --install || true
                printf '%s\n' 'macOS opened the Command Line Tools installer. Finish it, then rerun StackMarshal installation.' >&2
                return 1
            fi
            ;;
        Linux)
            if apt_get=$(type -P apt-get 2>/dev/null); then
                run_admin "$apt_get" update
                run_admin "$apt_get" install -y git
            elif dnf_exe=$(type -P dnf 2>/dev/null); then
                run_admin "$dnf_exe" install -y git
            elif yum_exe=$(type -P yum 2>/dev/null); then
                run_admin "$yum_exe" install -y git
            elif pacman_exe=$(type -P pacman 2>/dev/null); then
                run_admin "$pacman_exe" -S --needed --noconfirm git
            elif zypper_exe=$(type -P zypper 2>/dev/null); then
                run_admin "$zypper_exe" --non-interactive install git
            elif apk_exe=$(type -P apk 2>/dev/null); then
                run_admin "$apk_exe" add git
            else
                printf '%s\n' 'No supported package manager was found. Install Git and rerun the installer.' >&2
                return 1
            fi
            ;;
        *)
            printf 'Unsupported operating system for automatic Git installation: %s\n' "$system" >&2
            return 1
            ;;
    esac
}

ensure_git() {
    if GIT_EXE=$(type -P git 2>/dev/null); then
        return
    fi
    if ! confirm_action 'Git was not found. Install it using the operating-system package manager?'; then
        printf '%s\n' 'Git is required. Install Git and rerun this command.' >&2
        exit 1
    fi
    install_git
    hash -r
    if ! GIT_EXE=$(type -P git 2>/dev/null); then
        printf '%s\n' 'Git installation completed but git is still unavailable. Open a new shell and rerun the installer.' >&2
        exit 1
    fi
}

test_python() {
    local candidate=$1
    "$candidate" -I -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1
}

find_python() {
    local candidate candidate_path
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if candidate_path=$(type -P "$candidate" 2>/dev/null) && test_python "$candidate_path"; then
            PYTHON_EXE=$("$candidate_path" -I -c 'import os,sys; print(os.path.realpath(sys.executable))')
            return 0
        fi
    done
    return 1
}

install_python() {
    local system
    system=$(uname -s)
    case "$system" in
        Darwin)
            if brew_exe=$(type -P brew 2>/dev/null); then
                "$brew_exe" install python@3.13
            else
                printf '%s\n' 'Homebrew is unavailable. Install Python 3.11+ from python.org and rerun the installer.' >&2
                return 1
            fi
            ;;
        Linux)
            if apt_get=$(type -P apt-get 2>/dev/null); then
                run_admin "$apt_get" update
                apt_cache=$(type -P apt-cache 2>/dev/null || true)
                if [[ -n $apt_cache ]] && "$apt_cache" show python3.11 >/dev/null 2>&1; then
                    run_admin "$apt_get" install -y python3.11 python3.11-venv
                else
                    run_admin "$apt_get" install -y python3 python3-venv
                fi
            elif dnf_exe=$(type -P dnf 2>/dev/null); then
                run_admin "$dnf_exe" install -y python3
            elif yum_exe=$(type -P yum 2>/dev/null); then
                run_admin "$yum_exe" install -y python3
            elif pacman_exe=$(type -P pacman 2>/dev/null); then
                run_admin "$pacman_exe" -S --needed --noconfirm python
            elif zypper_exe=$(type -P zypper 2>/dev/null); then
                run_admin "$zypper_exe" --non-interactive install python311
            elif apk_exe=$(type -P apk 2>/dev/null); then
                run_admin "$apk_exe" add python3
            else
                printf '%s\n' 'No supported package manager was found. Install Python 3.11+ and rerun the installer.' >&2
                return 1
            fi
            ;;
        *)
            printf 'Unsupported operating system for automatic Python installation: %s\n' "$system" >&2
            return 1
            ;;
    esac
}

ensure_python() {
    if find_python; then
        return
    fi
    if ! confirm_action 'Python 3.11 or newer was not found. Install it using the operating-system package manager?'; then
        printf '%s\n' 'Python 3.11 or newer is required. Install it and rerun this command.' >&2
        exit 1
    fi
    install_python
    hash -r
    if ! find_python; then
        printf '%s\n' 'The installed Python is missing or older than 3.11. Install Python 3.11+ and rerun the installer.' >&2
        exit 1
    fi
}

test_venv_support() {
    local temporary
    temporary=$(mktemp -d "${TMPDIR:-/tmp}/stackmarshal-venv-check.XXXXXXXX")
    if "$PYTHON_EXE" -I -m venv "$temporary/venv" >/dev/null 2>&1; then
        rm -rf -- "$temporary"
        return 0
    fi
    rm -rf -- "$temporary"
    return 1
}

install_venv_component() {
    local version package
    version=$("$PYTHON_EXE" -I -c 'import sys; print(sys.version_info[0],sys.version_info[1],sep=chr(46))')
    if apt_get=$(type -P apt-get 2>/dev/null); then
        run_admin "$apt_get" update
        package="python${version}-venv"
        apt_cache=$(type -P apt-cache 2>/dev/null || true)
        if [[ -n $apt_cache ]] && "$apt_cache" show "$package" >/dev/null 2>&1; then
            run_admin "$apt_get" install -y "$package"
        else
            run_admin "$apt_get" install -y python3-venv
        fi
    elif dnf_exe=$(type -P dnf 2>/dev/null); then
        run_admin "$dnf_exe" install -y python3-pip
    elif yum_exe=$(type -P yum 2>/dev/null); then
        run_admin "$yum_exe" install -y python3-pip
    elif zypper_exe=$(type -P zypper 2>/dev/null); then
        run_admin "$zypper_exe" --non-interactive install "python${version/./}-pip"
    elif apk_exe=$(type -P apk 2>/dev/null); then
        run_admin "$apk_exe" add py3-pip
    else
        printf '%s\n' 'The selected Python cannot create virtual environments. Install its venv/ensurepip component and rerun.' >&2
        return 1
    fi
}

ensure_venv_support() {
    if test_venv_support; then
        return
    fi
    if ! confirm_action 'The selected Python cannot create virtual environments. Install its venv component?'; then
        printf '%s\n' 'Python venv support is required. Install it and rerun this command.' >&2
        exit 1
    fi
    install_venv_component
    if ! test_venv_support; then
        printf '%s\n' 'The Python venv component is still unavailable. Install it manually and rerun the installer.' >&2
        exit 1
    fi
}

resolve_version() {
    if [[ $VERSION != "latest" ]]; then
        if [[ ! $VERSION =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            printf 'Invalid version: %s\n' "$VERSION" >&2
            exit 2
        fi
        RESOLVED_TAG="v${VERSION#v}"
        return
    fi
    local refs
    refs=$("$GIT_EXE" ls-remote --tags --refs "$REPOSITORY_URL" 'refs/tags/v*') || {
        printf '%s\n' 'Could not query StackMarshal release tags.' >&2
        exit 1
    }
    RESOLVED_TAG=$(printf '%s\n' "$refs" | "$PYTHON_EXE" -I -c '
import re,sys
versions=[]
for line in sys.stdin:
    match=re.search(r"refs/tags/(v(\d+)\.(\d+)\.(\d+))$", line.strip())
    if match:
        versions.append(((int(match.group(2)),int(match.group(3)),int(match.group(4))),match.group(1)))
if not versions:
    raise SystemExit(1)
print(max(versions)[1])
') || {
        printf '%s\n' 'No stable StackMarshal release tag was found.' >&2
        exit 1
    }
}

download_file() {
    local url=$1 destination=$2
    "$PYTHON_EXE" -I - "$url" "$destination" <<'PY'
import pathlib,sys,urllib.parse,urllib.request
url,destination=sys.argv[1:]
loopback={"127.0.0.1","::1","localhost"}
def validate(value):
    parsed=urllib.parse.urlparse(value)
    if parsed.username or parsed.password or not parsed.hostname:
        raise SystemExit(f"Unsafe download URL: {value}")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in loopback):
        raise SystemExit(f"Unsafe download URL: {value}")
validate(url)
request=urllib.request.Request(url,headers={"User-Agent":"StackMarshal-Bootstrap/1"})
path=pathlib.Path(destination)
with urllib.request.urlopen(request,timeout=60) as source, path.open("wb") as output:
    validate(source.geturl())
    total=0
    while True:
        chunk=source.read(1024*1024)
        if not chunk:
            break
        total += len(chunk)
        if total > 4*1024*1024:
            raise SystemExit(f"Bootstrap download is too large: {url}")
        output.write(chunk)
if not path.is_file() or path.stat().st_size == 0:
    raise SystemExit(f"Downloaded file is empty: {url}")
PY
}

verify_installer() {
    local checksums=$1 installer=$2
    "$PYTHON_EXE" -I - "$checksums" "$installer" <<'PY'
import hashlib,hmac,pathlib,re,sys
checksums_path,installer_path=map(pathlib.Path,sys.argv[1:])
pattern=re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)$")
entries={}
for number,line in enumerate(checksums_path.read_text(encoding="utf-8").splitlines(),1):
    if not line:
        continue
    match=pattern.fullmatch(line.rstrip("\r"))
    if not match:
        raise SystemExit(f"Malformed SHA256SUMS line {number}")
    digest,name=match.groups()
    if name in entries:
        raise SystemExit(f"Duplicate checksum entry: {name}")
    entries[name]=digest
expected=entries.get("installer.py")
if expected is None:
    raise SystemExit("SHA256SUMS does not contain installer.py")
actual=hashlib.sha256(installer_path.read_bytes()).hexdigest()
if not hmac.compare_digest(actual,expected):
    raise SystemExit("Checksum mismatch for installer.py")
PY
}

ensure_git
ensure_python
ensure_venv_support
resolve_version
NORMALIZED_VERSION=${RESOLVED_TAG#v}
RELEASE_BASE="${RELEASE_BASE_PREFIX%/}/$RESOLVED_TAG"
TEMPORARY=$(mktemp -d "${TMPDIR:-/tmp}/stackmarshal-bootstrap.XXXXXXXX")
cleanup() {
    rm -rf -- "$TEMPORARY"
}
trap cleanup EXIT INT TERM

CHECKSUMS="$TEMPORARY/SHA256SUMS"
INSTALLER="$TEMPORARY/installer.py"
download_file "$RELEASE_BASE/SHA256SUMS" "$CHECKSUMS"
download_file "$RELEASE_BASE/installer.py" "$INSTALLER"
verify_installer "$CHECKSUMS" "$INSTALLER"

ARGS=(
    "$INSTALLER"
    --version "$NORMALIZED_VERSION"
    --release-base-url "$RELEASE_BASE"
    --repository-url "$REPOSITORY_URL"
)
((ASSUME_YES)) && ARGS+=(--yes)
((FORCE)) && ARGS+=(--force)
((ALLOW_DOWNGRADE)) && ARGS+=(--allow-downgrade)
((CLI_ONLY)) && ARGS+=(--cli-only)
((SKILL_ONLY)) && ARGS+=(--skill-only)
((NO_PATH)) && ARGS+=(--no-path)
[[ -n $INSTALL_ROOT ]] && ARGS+=(--install-root "$INSTALL_ROOT")
[[ -n $CODEX_HOME_VALUE ]] && ARGS+=(--codex-home "$CODEX_HOME_VALUE")

"$PYTHON_EXE" -I "${ARGS[@]}"
