#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The browser renderer: DOCX or HTML to PDF with the Edge or Chrome already on the PC, no Docker, no LibreOffice.

  python3 src/render_html/render.py docx <in.docx> <out.pdf>     a resume or a cover letter written by src/layout.js
  python3 src/render_html/render.py html <in.html> <out.pdf>     a page that sets its own @page size (the deck)
  python3 src/render_html/render.py doctor                       what this PC has for each renderer

src/resume.py chooses between this renderer and the container with OFFEROWL_RENDERER (html or container).
"""
import importlib.util  # the sibling modules under private names
import json  # the doctor report
import os  # environment
import pathlib  # paths
import re  # the page count of a PDF
import shutil  # node and docker on PATH
import subprocess  # node's version
import sys  # command line
import tempfile  # the HTML page between the DOCX and the PDF
import time  # timings

HERE = pathlib.Path(__file__).resolve().parent  # src/render_html
ROOT = HERE.parent.parent  # the repository root


def sibling(name: str):
    """A module of this folder, loaded under a private name (offerowl_<name>): the names browser, fonts and render are
    common, and a module of the same name elsewhere on the path (src/interview has a browser.py) must never stand in"""
    key = "offerowl_" + name
    if key not in sys.modules:  # load each module once
        spec = importlib.util.spec_from_file_location(key, HERE / (name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod  # registered before it runs, as an import would
        spec.loader.exec_module(mod)
    return sys.modules[key]


browser = sibling("browser")  # finding and driving the browser
docx2html = sibling("docx2html")  # DOCX to HTML
fonts = sibling("fonts")  # font files


def pdf_pages(pdf: str | pathlib.Path) -> int | None:
    """The page count of a PDF from its page tree, without poppler (the browser writes the tree as plain objects)"""
    raw = pathlib.Path(pdf).read_bytes()
    counts = [int(m.group(1)) for m in re.finditer(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", raw)]
    counts += [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", raw)]
    return max(counts) if counts else None


def docx_to_pdf(docx: str | pathlib.Path, pdf: str | pathlib.Path, exe: str | None = None, keep_html: bool = False) -> dict:
    """Typeset one DOCX of layout.js into a PDF. Returns {"pdf", "pages", "seconds", "browser", "html"}.
    The HTML page lives in a temporary folder and goes away after printing unless keep_html (then it sits next to the PDF)"""
    t0 = time.time()
    pdf = pathlib.Path(pdf)
    tmp = tempfile.mkdtemp(prefix="offerowl-page-")  # the page between the DOCX and the PDF
    try:
        page = pathlib.Path(tmp) / (pdf.stem + ".html")
        docx2html.convert(docx, page, title=pdf.stem)
        res = browser.print_pdf(page, pdf, browser=exe)
        if keep_html:  # for looking at the page in a browser
            shutil.copy(page, pdf.with_suffix(".print.html"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"pdf": str(pdf), "pages": pdf_pages(pdf), "seconds": round(time.time() - t0, 2), "browser": res["browser"],
            "html": str(pdf.with_suffix(".print.html")) if keep_html else None}


def fit_pages(write, docx: str | pathlib.Path, pdf: str | pathlib.Path, max_pages: int = 1, levels=(0, 1, 2)) -> dict:
    """Write and typeset a document at tighter and tighter spacing until it fits max_pages, as `cover.py build` does in
    the container. write(level) writes the DOCX at that level and returns (exit code, log). Returns the last result of
    docx_to_pdf() with "level" added, or {"error": log, "level": level} when the writer fails"""
    res = {}
    for level in levels:
        rc, log = write(level)
        if rc != 0:
            return {"error": log, "level": level}
        res = docx_to_pdf(docx, pdf)
        res["level"] = level
        if res["pages"] is not None and res["pages"] <= max_pages:
            break
    return res


def html_to_pdf(page: str | pathlib.Path, pdf: str | pathlib.Path, exe: str | None = None) -> dict:
    """Print a page that sets its own size (the deck's @page rule). Returns {"pdf", "pages", "seconds", "browser"}"""
    t0 = time.time()
    res = browser.print_pdf(page, pdf, browser=exe)
    return {"pdf": str(pdf), "pages": pdf_pages(pdf), "seconds": round(time.time() - t0, 2), "browser": res["browser"]}


def dump_dom(page: str | pathlib.Path, exe: str | None = None) -> str:
    """The page's DOM after its scripts ran, at the window size the deck's probe expects (1400 x 900)"""
    return browser.dump_dom(page, browser=exe, width=1400, height=900)


NODE_LEAST = 22  # the oldest Node.js the DOCX and deck writers are tested on (docs/INSTALL.md)


def doctor() -> dict:
    """What this PC can run. For each renderer: {"ok", "needs": [what is missing], "found": {...}}.
    html needs a browser (Edge, Chrome, Chromium or Playwright's Chromium), Node.js for the DOCX and deck writers,
    Pillow for the figures and the font files; container needs Docker"""
    found = browser.candidates()
    b = found[0] if found else None
    node = shutil.which("node")
    node_v = ""
    if node:
        try:
            node_v = subprocess.run([node, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            node_v = ""
    try:
        import PIL  # noqa: F401  the figure writer draws with Pillow
        pil = True
    except ImportError:
        pil = False
    missing_fonts = fonts.missing(["Pretendard"])  # the family of the resume, the cover letter and the deck
    major = re.match(r"v?(\d+)", node_v or "")  # the major version of the Node.js found
    node_ok = bool(node) and (not major or int(major.group(1)) >= NODE_LEAST)  # an older one fails on the writers' syntax, so it counts as missing
    html_needs = ([] if b else ["browser"]) + ([] if node_ok else ["node"]) + ([] if pil else ["pillow"]) + \
                 (["fonts:" + ",".join(missing_fonts)] if missing_fonts else []) + \
                 ([] if (ROOT / "node_modules" / "docx").is_dir() else ["node_modules"])
    docker = shutil.which("docker")
    in_container = pathlib.Path("/.dockerenv").exists() and shutil.which("soffice") is not None  # one of Offerowl's images (src/resume.py's rule)
    return {
        "html": {"ok": not html_needs, "needs": html_needs,
                 "found": {"browser": b["path"] if b else None, "kind": b["kind"] if b else None,
                           "version": browser.version(b["path"]) if b else "", "node": node, "node_version": node_v,
                           "pillow": pil, "browsers": [c["path"] for c in found]}},
        "container": {"ok": bool(docker) or in_container, "needs": [] if (docker or in_container) else ["docker"],
                      "found": {"docker": docker, "inside": in_container}},
    }


def main(argv: list[str]) -> int:
    if argv[:1] == ["doctor"]:
        print(json.dumps(doctor(), indent=1, ensure_ascii=False))
        return 0
    if len(argv) == 3 and argv[0] in ("docx", "html"):
        res = docx_to_pdf(argv[1], argv[2], keep_html=os.environ.get("OFFEROWL_KEEP_HTML") == "1") if argv[0] == "docx" \
            else html_to_pdf(argv[1], argv[2])
        print(json.dumps(res, ensure_ascii=False))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
