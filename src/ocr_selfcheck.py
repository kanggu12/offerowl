#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-check for OCR on scanned PDFs. Turns page 1 of the example resume into an image-only PDF and checks that
ingest.to_text (tesseract) can read it. resume.py selftest calls it inside the container, so it runs without any of
the regression test files

  python3 src/ocr_selfcheck.py output/sample_ko.pdf
"""
import pathlib  # file paths
import subprocess  # pdftoppm, pdftotext
import sys  # command-line arguments
import tempfile  # a temporary place for the image and the PDF

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # put src/ on the import path, so `import ingest` works from any folder
import ingest  # noqa: E402  the text converter, which includes OCR
import llm  # noqa: E402  the message helper and the language setting

MSG = {  # what this check says, in both languages with the same keys
    "en": {"layer": "OCR self-check: the test PDF still has a text layer  FAIL", "words": "OCR self-check: words {n}/{of}", "ok": "  PASS", "missed": ", not read: {words}  FAIL"},
    "ko": {"layer": "OCR 자체 확인: 시험 PDF 에 글자층이 남았다  실패", "words": "OCR 자체 확인: 낱말 {n}/{of}", "ok": "  통과", "missed": ", 못 읽음 {words}  실패"},
}

WANT = ("알파페이", "베타커머스", "Kubernetes", "대표 프로젝트")  # words that appear on page 1 of the example (the certificates are on page 2)


def t(key: str, **kw) -> str:
    """A message of this check in the person's language."""
    return llm.message(MSG, key, **kw)


def main() -> int:
    from PIL import Image  # used to save the image as a PDF
    src = pathlib.Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "200", "-f", "1", "-l", "1", "-png", str(src), f"{tmp}/s"], check=True)  # page 1 as an image
        pdf = pathlib.Path(tmp) / "scan.pdf"
        Image.open(next(pathlib.Path(tmp).glob("s*.png"))).convert("RGB").save(pdf)  # a PDF without a text layer
        if subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip():
            print(t("layer"))
            return 1
        text = ingest.to_text(pdf)  # with no text layer, the text can only come from OCR
    miss = [w for w in WANT if w not in text]
    print(t("words", n=len(WANT) - len(miss), of=len(WANT)) + (t("ok") if not miss else t("missed", words=miss)))
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
