#!/bin/sh
# Write the installers a release carries: scripts/install.sh and install.ps1 with the release they install written in,
# so each installs the release it came with and shows the command that fetches it. install.sh goes out twice, as the
# Linux and the macOS installer (the same script: it installs for the system it runs on); install.ps1 as the Windows one.
# The release workflow runs it with the tag and the folder to write to:
#
#   scripts/installers.sh v0.15.0 dist/installers
set -eu

release=$1
out=$2
root=$(cd "$(dirname "$0")/.." && pwd)  # the scripts are read from this repository, whatever folder it runs in

case "$release" in
  v[0-9]*) ;;
  *) echo "installers: not a release: $release" >&2; exit 1 ;;
esac
case "$release" in
  *[!A-Za-z0-9.+-]*) echo "installers: not a release: $release" >&2; exit 1 ;;  # anything else would end up inside the scripts' quotes
esac
version=${release#v}  # the address has the v; the files' names have the version without it

mkdir -p "$out"
sed -e "s/^release=\"\"\$/release=\"$release\"/" -e "s/vX\.Y\.Z/$release/g" -e "s/X\.Y\.Z/$version/g" \
  "$root/scripts/install.sh" >"$out/offerowl-$version-linux-installer.sh"
cp "$out/offerowl-$version-linux-installer.sh" "$out/offerowl-$version-macos-installer.sh"
sed -e "s/^  \$release = ''\$/  \$release = '$release'/" -e "s/vX\.Y\.Z/$release/g" -e "s/X\.Y\.Z/$version/g" \
  "$root/scripts/install.ps1" >"$out/offerowl-$version-windows-installer.ps1"
# Each must carry its release, or it would quietly install the latest one instead.
grep -q "^release=\"$release\"\$" "$out/offerowl-$version-linux-installer.sh"
grep -q "^  \$release = '$release'\$" "$out/offerowl-$version-windows-installer.ps1"
ls "$out"
