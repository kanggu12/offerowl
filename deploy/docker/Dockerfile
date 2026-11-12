# Offerowl app image: the panel, the engine, the interview view and the renderer in one container.
#
# The render image of ../../render/Dockerfile (used by render/run.sh) only holds the typesetting tools and gets the repository
# mounted into it. This image is the finished app: the same tools, plus the code, the typesetting libraries and a
# server that starts by itself. Build it from the repository root:
#
#   docker build -f deploy/docker/Dockerfile -t offerowl-app:local .
#
# or run it through deploy/docker/compose.yaml (docs/INSTALL.md).
FROM node:22-bookworm-slim

# The four tool layers below are copied word for word from ../../render/Dockerfile (tests/packaging checks that they stay the
# same). Identical layers come out of the build cache when the render image was built on this machine, and the
# typeset output of the container and of render/run.sh cannot drift apart.
# python3-pil lets check_documents.py measure the page images, python3-pikepdf tidies PDF metadata,
# poppler-utils reads and rasterises PDFs, the fonts keep the line breaks of a reader with Office, and LibreOffice turns
# the DOCX into a PDF.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pil \
        python3-pikepdf \
        poppler-utils \
        libreoffice-writer \
        fonts-nanum \
        fonts-texgyre \
        fonts-crosextra-carlito \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

# chromium prints the 16:9 portfolio from HTML to PDF and measures overflow on every slide.
RUN apt-get update && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/*

# tesseract reads scanned PDFs and images (Korean and English).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# libreoffice-impress opens PowerPoint files, so a deck among a job's materials can be shown page by page.
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

# tini is the first process of the container. A server that is process 1 ignores SIGTERM unless it installs a handler,
# so `docker stop` and a pod's shutdown would wait for the kill; tini passes the signal on and reaps the browser and
# LibreOffice processes a build leaves behind. Its own layer, so the layers above stay in the cache.
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# A fixed user id, not root. A new named volume takes over the owner of the folders below, and the Helm chart runs the
# pod as this same id. No home folder: HOME is /tmp (set below), which is a memory-backed folder when the root
# filesystem is read-only.
RUN groupadd --gid 10001 offerowl \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin offerowl

# The repository lives in /work, as in the render container: src/fonts.sh and src/ingest.py name that folder.
WORKDIR /work

# The typesetting libraries first. Only the package files are copied, so this layer is reused until a dependency
# changes. The build needs the network; the running container does not. --omit=dev leaves out what only developers use.
COPY package.json package-lock.json /work/
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force

# The code and its data. Dockerfile.dockerignore decides what is in the build context (an allow-list), so nothing
# else of the working folder (output, node_modules, tests, a workspace with your own files) can end up in the image.
COPY . /work/

# Everything below is set up as root and then handed to the app user:
# - /work/output is where the engine writes while it builds. It is the only place under /work the app may write to.
# - /data is the data folder: settings, the workspace and the logs (OFFEROWL_DATA_DIR). Compose and the chart mount a
#   volume here.
# - /usr/local/bin/offerowl and /usr/local/bin/offerowl-doctor let `docker exec <container> offerowl llm` and
#   `docker exec <container> offerowl-doctor` work.
# - /.dockerenv is the file the engine looks at to know it runs inside the render container (src/resume.py and
#   src/cover.py: in_container). Docker creates it itself, but Kubernetes with containerd does not, and without it the
#   engine would look for render/run.sh and Docker inside the container.
RUN mkdir -p /work/output /data \
    && chown 10001:10001 /work/output /data \
    && chmod 755 /work/deploy/docker/entrypoint.py /work/offerowl /work/src/doctor.py \
    && ln -s /work/offerowl /usr/local/bin/offerowl \
    && ln -s /work/src/doctor.py /usr/local/bin/offerowl-doctor \
    && touch /.dockerenv

# Settings of the image. All of them can be replaced with -e (compose.yaml and the chart do).
# - HOME is /tmp: LibreOffice, Chromium and fonts.sh write their profile and caches under the home folder.
# - OFFEROWL_PANEL_PORT is the port the panel listens on inside the container. The published port must have the same
#   number, because the panel answers only requests whose Host header names its own port.
# - OFFEROWL_DESKTOP is where "Export to Desktop" puts the PDFs: a folder inside the data volume, since a container has
#   no Desktop.
# - OFFEROWL_VERSION is the release this image is, for `offerowl-doctor` (an image has no package metadata to read).
# - No bytecode files (the root filesystem may be read-only) and no buffered output (logs show at once).
ENV HOME=/tmp \
    OFFEROWL_VERSION=0.9.0 \
    OFFEROWL_DATA_DIR=/data \
    OFFEROWL_PANEL_PORT=8797 \
    OFFEROWL_DESKTOP=/data/export \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Labels that registries and `docker inspect` show. The version is the one in deploy/python/offerowl/__init__.py
# (tests/packaging keeps them equal).
LABEL org.opencontainers.image.title="offerowl-app" \
      org.opencontainers.image.description="Offerowl: from one evidence-backed profile to a resume, a portfolio, a cover letter and an interview kit" \
      org.opencontainers.image.version="0.9.0"

# Run as the app user from here on.
USER 10001:10001

# The panel (8797). It serves the interview kit too, at /kit/<job>/.
EXPOSE 8797

# The panel answers /health with {"ok": true, "app": "offerowl"}. The check runs inside the container and asks
# 127.0.0.1, so the Host header is the one the panel accepts. 30 seconds of start period cover a slow first start.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python3", "-c", "import json,os,urllib.request as u; r=json.load(u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('OFFEROWL_PANEL_PORT','8797'), timeout=4)); raise SystemExit(0 if r.get('app')=='offerowl' else 1)"]

# tini first, then the entrypoint, which prepares the data folder and starts what the command asks for. The default
# command starts the panel; any other `offerowl` command (doctor, build, selftest, ...) runs the command line.
ENTRYPOINT ["tini", "--", "python3", "/work/deploy/docker/entrypoint.py"]
CMD ["panel"]
