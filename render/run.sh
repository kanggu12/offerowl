#!/usr/bin/env bash
# Run one command inside the Offerowl render container (Node, LibreOffice, Chromium, Tesseract and the fonts).
# Everything that typesets or measures runs in there, so the host stays clean.
#   render/run.sh node src/resume_form.js profile.json job.json
#   render/run.sh python3 src/check_documents.py output/resume.pdf
#   render/run.sh soffice --headless --convert-to pdf --outdir output output/resume.docx
#
# Settings are environment variables.
#   OFFEROWL_NET=1       open the network (only `npm ci` needs it; everything else runs with the network closed)
#   OFFEROWL_CPUS=6      CPU cap of the container
#   OFFEROWL_MEM=4g      memory cap of the container
#   OFFEROWL_ASSETS=DIR  mount DIR read-only at /offerowl-assets (your own logos and screenshots); no mount when unset
#   OFFEROWL_THEME, OFFEROWL_THEME_FILE, OFFEROWL_FRESH, OFFEROWL_NOLOGOS, OFFEROWL_PROFILE, OFFEROWL_LANG,
#   OFFEROWL_RENDERER, OFFEROWL_BLIND, OFFEROWL_BLIND_LANG, OFFEROWL_BLIND_TABLE, OFFEROWL_PDF_READER
#                        handed on to the scripts inside the container (see docs/USAGE.md and docs/ARCHITECTURE.md);
#                        OFFEROWL_BLIND_TABLE names a file inside the repository, as the container sees it
# The container is the `container` renderer. The `html` renderer (OFFEROWL_RENDERER=html) typesets on the host with the
# PC's own Chrome or Edge and does not use this script; inside the container the same setting makes src/resume.py print
# with the container's Chromium instead of LibreOffice.
#   OFFEROWL_DRY_RUN=1   print the docker command, one word per line, and stop (the tests use it; Docker is not needed)
set -euo pipefail

# The repository root (this script sits in render/), wherever it is called from.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# setting NAME prints OFFEROWL_<NAME>, or nothing when it is unset.
setting() {
    local name="OFFEROWL_$1"
    printf '%s' "${!name-}"
}

# Tag the image by the content of the Dockerfile, so an edited Dockerfile builds a new image instead of silently
# reusing a stale one.
TAG="$(md5sum "$ROOT/render/Dockerfile" | cut -c1-12)"
IMAGE="offerowl-render:$TAG"

# Build the image when it is missing. A dry run never touches Docker.
if [ "${OFFEROWL_DRY_RUN:-0}" != "1" ] && ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "building $IMAGE" >&2
    docker build -q -t "$IMAGE" "$ROOT/render" >&2   # the recipe copies nothing in: its folder alone is the build's context
fi

# The network stays closed unless asked: typesetting needs none, and a closed network keeps a bad script from calling out.
NET=none
[ "$(setting NET)" = "1" ] && NET=bridge

# Your assets (logos, screenshots) are trademarks or screenshots that do not belong in git. They come in read-only,
# from the folder named by OFFEROWL_ASSETS, at /offerowl-assets (the path the deck script looks at). Without the setting
# nothing is mounted. A path that is not a folder is an error: Docker would quietly create it as an empty folder.
ASSETS=()
if [ -n "${OFFEROWL_ASSETS:-}" ]; then
    if [ ! -d "$OFFEROWL_ASSETS" ]; then
        echo "OFFEROWL_ASSETS=$OFFEROWL_ASSETS is not a folder" >&2
        exit 2
    fi
    ASSETS=(-v "$(cd "$OFFEROWL_ASSETS" && pwd):/offerowl-assets:ro")
fi

# Resource caps, so that the container never takes the whole PC. Printing a deck starts six Chromium runs, so two CPUs
# would be too few. Change the caps with OFFEROWL_CPUS and OFFEROWL_MEM.
CPUS="$(setting CPUS)"
CPUS="${CPUS:-6}"
# never more than Docker has: it refuses the run outright on a PC (or a Docker VM) with fewer CPUs than the cap
HAVE="$(docker info --format '{{.NCPU}}' 2>/dev/null || true)"
HAVE="${HAVE:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)}"
CPUS="$(awk -v want="$CPUS" -v have="$HAVE" 'BEGIN { print (want + 0 > have + 0 && have + 0 > 0) ? have : want }')"
MEM="$(setting MEM)"
MEM="${MEM:-4g}"

# Settings the scripts inside the container read. `docker run` only hands over the names it is given, so they are listed
# here. `${!name+x}` tells "set, even if empty" from "unset".
PASS=()
for v in THEME THEME_FILE FRESH NOLOGOS PROFILE LANG RENDERER BLIND BLIND_LANG BLIND_TABLE PDF_READER; do
    name="OFFEROWL_$v"
    if [ -n "${!name+x}" ]; then
        PASS+=(-e "$name=${!name}")
    fi
done

# The command. PYTHONDONTWRITEBYTECODE keeps .pyc files out of the repository: a file restored by git within the same
# second and byte size would make Python load the stale .pyc. The container name carries the PID, so concurrent runs
# never collide and `docker ps` shows whose it is. It runs as the person's own user, so the files it writes are theirs;
# the image lists only user 1000 (node), and LibreOffice finds no home for any other (a Mac's 501, a CI runner's 1001)
# and stops with "User installation could not be completed": UserInstallation gives it a profile folder in /tmp.
CMD=(docker run --rm
    --name "offerowl-render-$$"
    --network "$NET"
    --memory "$MEM" --cpus "$CPUS"
    -v "$ROOT:/work"
    ${ASSETS[@]+"${ASSETS[@]}"}
    -w /work
    -u "$(id -u):$(id -g)"
    -e HOME=/tmp
    -e UserInstallation=file:///tmp/offerowl-lo
    -e PYTHONDONTWRITEBYTECODE=1
    ${PASS[@]+"${PASS[@]}"}
    "$IMAGE" "$@")

if [ "${OFFEROWL_DRY_RUN:-0}" = "1" ]; then
    printf '%s\n' "${CMD[@]}"
    exit 0
fi
exec "${CMD[@]}"
