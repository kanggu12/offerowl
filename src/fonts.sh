#!/usr/bin/env bash
# Registers the fonts in the repository's fonts/ folder (Pretendard, SIL OFL) as user fonts of the container.
# A container starts fresh every time, so this runs once before each LibreOffice conversion. The render commands
# (resume.py, cover.py) call it first, and so does the start command of the UI container.
mkdir -p "$HOME/.fonts" && cp /work/fonts/*.ttf "$HOME/.fonts/" && fc-cache -f "$HOME/.fonts" >/dev/null
