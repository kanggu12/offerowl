#!/bin/sh
# Install Offerowl for this user and open it. Each release carries this script with
# its own version written in, so the line below installs that release:
#
#   curl -fsSL https://github.com/kanggu12/offerowl/releases/download/vX.Y.Z/offerowl-X.Y.Z-linux-installer.sh | sh
#   curl -fsSL https://github.com/kanggu12/offerowl/releases/download/vX.Y.Z/offerowl-X.Y.Z-macos-installer.sh | sh
#
# Linux (x86-64): the one-file app as ~/.local/bin/offerowl (your files stay
# in ~/.local/share/offerowl, apart from it). macOS (Apple silicon or Intel): Offerowl.app in
# /Applications, or ~/Applications when that is not writable. Run again to update.
# OFFEROWL_INSTALL_ONLY=1 installs without opening it (a script, a check).
set -eu

repo="kanggu12/offerowl"
# The release this script installs, written in by scripts/installers.sh; empty
# in the repository, where it installs the latest release.
release=""

say() { printf '%s\n' "offerowl: $*"; }
fail() { printf '%s\n' "offerowl: $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || fail "curl is needed to download the app"

if [ -z "$release" ]; then
  # The latest release: the address its page redirects to ends in its tag.
  release=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$repo/releases/latest")
  release=${release##*/}
fi
case "$release" in
  v[0-9]*) ;;
  *) fail "no release found ($release)" ;;
esac
version=${release#v}
base="https://github.com/$repo/releases/download/$release"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

case "$(uname -s)" in
  Linux)
    case "$(uname -m)" in
      x86_64 | amd64) ;;
      *) fail "the app is built for Linux on x86-64; on $(uname -m), run it from the source (docs/INSTALL.md)" ;;
    esac
    bin="$HOME/.local/bin"
    say "downloading Offerowl $version"
    curl -fL --progress-bar -o "$tmp/app.tar.gz" "$base/offerowl-$version-linux-x64.tar.gz"
    tar -xzf "$tmp/app.tar.gz" -C "$tmp"
    mkdir -p "$bin"
    # beside the old one first, then in its place: a running app keeps its file until it stops
    cp "$tmp/offerowl" "$bin/.offerowl.new" && chmod 755 "$bin/.offerowl.new" && mv -f "$bin/.offerowl.new" "$bin/offerowl"
    say "installed: $bin/offerowl"
    case ":$PATH:" in
      *":$bin:"*) ;;
      *) say "add $bin to PATH to run it by name" ;;
    esac
    [ "${OFFEROWL_INSTALL_ONLY:-}" = "1" ] && exit 0
    say "opening the panel (Ctrl+C here stops it; run offerowl to open it again)"
    exec "$bin/offerowl" </dev/null  # the pipe this script came through is no input for the app
    ;;
  Darwin)
    case "$(uname -m)" in
      arm64) arch=arm64 ;;
      x86_64) arch=x64 ;;
      *) fail "no app for this Mac ($(uname -m))" ;;
    esac
    apps=/Applications
    [ -w "$apps" ] || { apps="$HOME/Applications"; mkdir -p "$apps"; }
    say "downloading Offerowl $version"
    curl -fL --progress-bar -o "$tmp/app.zip" "$base/offerowl-$version-macos-$arch.zip"
    rm -rf "$apps/Offerowl.app"
    ditto -x -k "$tmp/app.zip" "$apps"
    say "installed: $apps/Offerowl.app"
    [ "${OFFEROWL_INSTALL_ONLY:-}" = "1" ] && exit 0
    open "$apps/Offerowl.app"
    ;;
  *)
    fail "this installer is for Linux and macOS; on Windows, use the windows-installer.ps1 of the same release"
    ;;
esac
