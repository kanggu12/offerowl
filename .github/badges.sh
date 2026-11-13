#!/bin/sh
# Write the README's badges into docs/assets/badges/: shields.io's static badges, kept as files. GitHub shows an image from
# another site through a proxy that gives up after about four seconds, so a badge asked for as the page is shown can show
# as a broken picture; a file in the repository is served without that proxy. Run it after the release's number is set in
# deploy/python/offerowl/__init__.py:
#
#   sh .github/badges.sh
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)   # the repository, wherever this is run from
cd "$root"
dir=docs/assets/badges                    # where the README finds them
mkdir -p "$dir"

# the one place the version is written
version=$(sed -n 's/^__version__ = "\([0-9][0-9.]*\)".*/\1/p' deploy/python/offerowl/__init__.py)
[ -n "$version" ] || { echo "deploy/python/offerowl/__init__.py names no version" >&2; exit 1; }

# badge NAME SPEC writes shields.io's static badge SPEC (label-message-color, spaces as %20, "|" as %7C) to NAME.svg,
# whole or not at all
badge() {
  tmp="$dir/$1.svg.tmp"
  curl -fsS --retry 3 --max-time 30 -o "$tmp" "https://img.shields.io/badge/$2.svg"
  # an error page in place of a badge must not replace the one there is
  grep -q '<svg' "$tmp" || { echo "shields.io sent no SVG for $1" >&2; rm -f "$tmp"; exit 1; }
  mv "$tmp" "$dir/$1.svg"
}

# the checks: what runs them, as a file like the rest. The live status badge of GitHub Actions answers only once the repository
# is public (before that its address is a 404, a broken picture), so the README links this one to the workflow it names
badge ci "CI-GitHub%20Actions-2088ff"
badge release "release-v$version-ea7233"
badge license "license-MIT-2a78d6"
badge runs-on "runs%20on-Windows%20%7C%20macOS%20%7C%20Linux-555"

# the README's alt text says the same, for a reader without images
sed -i -e "s/alt=\"Release v[0-9][0-9.]*\"/alt=\"Release v$version\"/" README.md
echo "wrote $dir: release v$version"
