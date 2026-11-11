# Third-party notices

Offerowl's own code is under the MIT License ([LICENSE](../LICENSE)). It uses the components below. The fonts are kept in this
repository with their licenses. The typesetting libraries are installed from `package-lock.json`, and the desktop app carries a pruned
copy of them.

## Fonts

| Font | License | Where |
|:---|:---|:---|
| Pretendard | SIL Open Font License 1.1 | `fonts/`, `src/interview/fonts/`, in the documents and the panel, and embedded in the Word files the export writes (the license allows a font inside a document) |
| JetBrains Mono | SIL Open Font License 1.1 | `src/interview/fonts/`, in the interview view |

The wordmark's letters are outlines of Pretendard (SIL Open Font License 1.1).

## Typesetting libraries (`package-lock.json`)

| Component | Version | License |
|:---|:---:|:---|
| core-util-is | 1.0.3 | MIT |
| docx | 9.7.1 | MIT |
| hash.js | 1.1.7 | MIT |
| immediate | 3.0.6 | MIT |
| inherits | 2.0.4 | ISC |
| isarray | 1.0.0 | MIT |
| jszip | 3.10.1 | (MIT OR GPL-3.0-or-later) |
| lie | 3.3.0 | MIT |
| lucide-static | 1.48.0 | ISC |
| minimalistic-assert | 1.0.1 | ISC |
| nanoid | 5.1.16 | MIT |
| opentype.js | 1.3.4 | MIT |
| pako | 1.0.11 | (MIT AND Zlib) |
| process-nextick-args | 2.0.1 | MIT |
| readable-stream | 2.3.8 | MIT |
| safe-buffer | 5.1.2 | MIT |
| sax | 1.6.1 | BlueOak-1.0.0 |
| setimmediate | 1.0.5 | MIT |
| string.prototype.codepointat | 0.2.1 | MIT |
| string_decoder | 1.1.1 | MIT |
| tiny-inflate | 1.0.3 | MIT |
| util-deprecate | 1.0.2 | MIT |
| xml | 1.0.1 | MIT |
| xml-js | 1.6.11 | MIT |

Only `docx`, `lucide-static` and `opentype.js` are asked for directly; the others come with them. `@types/node` and `undici-types` come
with `docx` and are left out of the app.

### Notices kept in a README

`hash.js` and `isarray` carry their MIT notice in their README rather than in a licence file, and the desktop app does not
ship READMEs, so the notices are quoted here, in the file every copy of Offerowl carries.

hash.js:

```text
Copyright Fedor Indutny, 2014.

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the
following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
```

isarray:

```text
Copyright (c) 2013 Julian Gruber <julian@juliangruber.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## In the desktop app

| Component | Version | License | Source |
|:---|:---:|:---|:---|
| Node.js | 22.23.4 | MIT, and the licenses in its own `LICENSE` file, which the app keeps beside the program | https://nodejs.org |
| CPython | as built | PSF License | https://www.python.org |
| PyInstaller's bootloader | as built | GPL 2.0 with the bootloader exception, which allows this use | https://pyinstaller.org |
| Pillow | pinned in `apps/desktop/requirements-build.txt` | MIT-CMU | https://python-pillow.org |
| pystray | pinned in `apps/desktop/requirements-build.txt` | LGPL 3.0 | https://github.com/moses-palmer/pystray (its source; to use another version, build the app from a checkout with that version installed: `python apps/desktop/build.py`, or run Offerowl from the checkout itself) |
| six | comes with pystray | MIT | https://github.com/benjaminp/six |
| python-xlib, on Linux | comes with pystray | LGPL 2.1 or later | https://github.com/python-xlib/python-xlib |
| pypdfium2, with PDFium | pinned in `apps/desktop/requirements-build.txt` | Apache 2.0 or BSD-3-Clause; PDFium is BSD-3-Clause and Apache 2.0 | https://github.com/pypdfium2-team/pypdfium2 |

## In the container images

The images add the packages of Debian's `node:22-bookworm-slim` base and these, each under its own license: tini (MIT), LibreOffice Writer and Impress (MPL 2.0),
Chromium (BSD-3-Clause and others), Poppler (GPL 2.0 or 3.0), Tesseract OCR (Apache 2.0), Pillow, pikepdf (MPL 2.0), and the Nanum,
TeX Gyre and Carlito fonts (SIL Open Font License 1.1, GUST Font License). Offerowl starts these programs and does not link to them.

## Programs it can use, which you install yourself

| Program | Why | License |
|:---|:---|:---|
| Claude Code, Codex | An AI backend, through your own sign-in | their makers' terms |
| Ollama, vLLM, LM Studio | An AI backend on your own hardware | their own |
| Google Chrome, Microsoft Edge, Chromium | Printing PDFs with no Docker | their own |
| Playwright | The interview page checks | Apache 2.0 |
| faster-whisper | A transcript in practice mode | MIT |
| Laya | Optional, only for measuring decision models ([DECISIONS.md](DECISIONS.md)) | Apache 2.0 |

Licenses are summarized here for convenience. The license that comes with each component is the one that applies.
