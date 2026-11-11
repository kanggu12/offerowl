# Offerowl render toolchain: typesets the documents and measures them.
# Everything runs in here so the host stays clean. render/run.sh tags the image offerowl-render:<md5 of this file>, so an
# edited Dockerfile builds a new image instead of silently reusing a stale one.
FROM node:22-bookworm-slim

# python3-pil lets check_documents.py measure the page images.
# python3-pikepdf tidies the metadata (title, author) of PDFs that are handed out; no script in this repository calls it yet.
# fonts-crosextra-carlito is metric compatible with the Calibri that documents may ask for, so the container breaks lines
# where a reader with Office would see them. Without a metric match LibreOffice rewraps lines, and a check that looks
# for a literal string fails on the break rather than on the content.
# fonts-texgyre has the Palatino-style faces that src/layout.js asks for.
# default-jre is deliberately absent: docx to pdf conversion produces byte-identical text without it, and it costs
# about 200 MB.
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

# chromium prints the 16:9 portfolio (src/portfolio/) from HTML to PDF and measures overflow on every slide. Resumes still
# go through LibreOffice. Kept as its own layer so the LibreOffice layer above stays cached.
RUN apt-get update && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/*

# tesseract reads scanned PDFs and images for src/ingest.py (Korean and English). Its own layer at the end, so the LibreOffice
# and chromium layers above stay cached and the typeset output does not change.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# libreoffice-impress opens PowerPoint files, so a deck among a job's materials can be shown page by page
# (apps/api/materials.py prints it to PDF here, as Writer prints a Word file). Its own layer at the end, so the layers
# above stay cached.
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
