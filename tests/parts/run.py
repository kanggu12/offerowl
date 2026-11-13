#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parts test: builds the fictional full example (examples/sample_full_ko.json, sample_full_en.json with the chapter
deck) and the ledger-form fixture, then checks that every part docs/DOCUMENTS.md lists is there and nothing leaks.

  python3 tests/parts/run.py            build (heavy: LibreOffice and Chromium in the render container) and check
  python3 tests/parts/run.py --no-build check the outputs already in output/

Checks per build:
  - the loader unit tests (tests/parts/loader_test.js) and the layout choices (tests/parts/form_choices_test.js)
  - the document check passes on the build (src/check_documents.py: missing roles and projects, page cap, footer, overflow)
  - no raw markup or empty values in the PDF text ('==', '**', 'undefined', 'NaN', '[object', 'null', '\\n')
  - resume parts: tenure and total, evidence after competencies, structured sections, logos and figures embedded in the DOCX
  - deck parts: slide count, contents, chapter dividers, side rail, project meta line, journey, one figure per template type,
    no probe defects (one-word last lines are warnings), nothing cut from a figure
Prints one line per failed check and ends with 'parts tests: N passed, M failed'.
"""
import json  # probe and cut files
import pathlib  # paths
import re  # text checks
import subprocess  # builds and tools
import sys  # arguments
import zipfile  # DOCX media count

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
OUT = ROOT / "output"  # build outputs
PASS, FAIL = [0], [0]  # counters (lists so the helpers can change them)


def ok(name, cond, detail=""):
    """Count one check and print it when it fails"""
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))


def text_of(pdf):
    """PDF text layer (host pdftotext, or the container's when the host has none)"""
    try:
        return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        return subprocess.run([str(ROOT / "render" / "run.sh"), "pdftotext", str(pdf.relative_to(ROOT)), "-"], cwd=ROOT, capture_output=True, text=True).stdout


def build(profile, job):
    """resume.py build: resume and deck plus the document check. Returns (return code, last line)"""
    r = subprocess.run(["nice", "-n", "15", sys.executable, str(ROOT / "src" / "resume.py"), "build", profile] + ([job] if job else []),
                       cwd=ROOT, capture_output=True, text=True)
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode, lines[-1] if lines else ""


RAW = [("==", r"=="), ("**", r"\*\*"), ("undefined", r"\bundefined\b"), ("NaN", r"\bNaN\b"), ("[object", r"\[object"),
       ("null", r"\bnull\b"), ("literal \\n", r"\\n")]  # markup or empty values that must never reach a document


def no_raw(name, text):
    """No raw markup in a document's text layer"""
    for label, pat in RAW:
        m = re.search(pat, text)
        ok(f"{name}: no raw '{label}'", not m, (text[max(0, m.start() - 30):m.end() + 30].replace("\n", " ") if m else ""))


def docx_media(docx):
    """Number of images embedded in a DOCX (logo tiles and figures)"""
    with zipfile.ZipFile(docx) as z:
        return sum(1 for n in z.namelist() if n.startswith("word/media/"))


def deck_checks(name, out, want_slides, words):
    """Deck structure and the browser probe"""
    pdf, html = OUT / f"{out}_deck.pdf", OUT / f"{out}_deck.html"
    ok(f"{name}: deck built", pdf.exists() and html.exists())
    if not html.exists():
        return
    h = html.read_text(encoding="utf-8")
    probe = json.loads((OUT / f"{out}_deck.probe.json").read_text(encoding="utf-8"))["slides"]
    ok(f"{name}: {want_slides} slides", len(probe) == want_slides, f"{len(probe)} slides")
    for part, pat in (("contents", r'class="toc2"'), ("chapter dividers", r'class="slide chapter"'), ("side rail", r'<nav class="rail'),
                      ("project meta line", r'class="pmeta"'), ("scale chips", r'class="chips"'), ("journey", r'class="journey"'),
                      ("stat tiles", r'class="proof"'), ("logo plates", r'class="logos"')):
        ok(f"{name}: deck has {part}", re.search(pat, h) is not None)
    t = text_of(pdf)
    for w in words:  # one word from each figure template proves it was drawn
        ok(f"{name}: deck shows '{w}'", w in t)
    no_raw(f"{name} deck", t)
    defects = [f"{s['n']}: {i}" for s in probe for i in s["issues"] if "one-word last line" not in i] + \
              [f"{s['n']}: {i['kind']} {i['msg']}" for s in probe for i in s.get("svg", [])]
    ok(f"{name}: no deck defects", not defects, "; ".join(defects[:5]))
    cut = json.loads((OUT / f"{out}_deck.cut.json").read_text(encoding="utf-8"))
    ok(f"{name}: nothing cut from figures", not cut, "; ".join(cut[:3]))


def main():
    r = subprocess.run(["node", str(ROOT / "tests" / "parts" / "plain_test.js")], capture_output=True, text=True)  # the plain resume
    ok("plain resume tests", r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])  # its summary line, or what failed
    r = subprocess.run(["node", str(ROOT / "tests" / "parts" / "form_choices_test.js")], capture_output=True, text=True)  # the plain look and the older footer
    ok("form choices tests", r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])  # its summary line, or what failed
    r = subprocess.run(["node", str(ROOT / "tests" / "parts" / "loader_test.js")], capture_output=True, text=True)
    ok("loader unit tests", r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:])
    def lum(h):  # a colour's relative luminance
        return sum(w * ((c / 255) / 12.92 if c / 255 <= 0.03928 else (((c / 255) + 0.055) / 1.055) ** 2.4) for w, c in zip((0.2126, 0.7152, 0.0722), (int(h[i:i + 2], 16) for i in (0, 2, 4))))
    contrast = lambda a, b: (max(lum(a), lum(b)) + 0.05) / (min(lum(a), lum(b)) + 0.05)  # noqa: E731  WCAG's ratio
    for name, t in json.loads((ROOT / "src" / "themes.json").read_text(encoding="utf-8")).items():  # every colour set
        if name.startswith("_"):  # its comment
            continue  # not a set
        ok(f"colour set {name}: its name band reads", contrast(t["nameFill"], t["nameText"]) >= 4.5, f"{contrast(t['nameFill'], t['nameText']):.1f}")  # the name on its band
        ok(f"colour set {name}: a table head reads", contrast(t["head"], t["headText"]) >= 4.5, f"{contrast(t['head'], t['headText']):.1f}")  # a table's head
        ok(f"colour set {name}: a heading reads on paper", contrast(t["sec"], "FFFFFF") >= 4.5, f"{contrast(t['sec'], 'FFFFFF'):.1f}")  # a section's title
    builds = [("ko", "examples/sample_full_ko.json", "examples/job_full_ko.json", "sample_full_ko"),
              ("en", "examples/sample_full_en.json", "examples/job_full_en.json", "sample_full_en"),
              ("export shape", "tests/parts/fixtures/export_shape.json", None, "export_shape")]
    for form in ("compact", "table"):  # the other forms, on the full example in both languages
        for lang in ("ko", "en"):  # each edition
            job = OUT / f"form_{form}_{lang}.job.json"  # its settings, written here
            job.parent.mkdir(parents=True, exist_ok=True)  # output/ may be new
            job.write_text(json.dumps({**json.loads((ROOT / f"examples/job_full_{lang}.json").read_text(encoding="utf-8")), "out": f"form_{form}_{lang}", "form": form, "maxPages": 4}), encoding="utf-8")  # the example's job, in this form
            builds.append((f"{form} {lang}", f"examples/sample_full_{lang}.json", str(job.relative_to(ROOT)), f"form_{form}_{lang}"))  # checked like the others
    for name, prof, job, out in builds:
        if "--no-build" not in sys.argv:
            rc, last = build(prof, job)
            ok(f"{name}: build and document check", rc == 0, last)
        pdf, docx = OUT / f"{out}.pdf", OUT / f"{out}.docx"
        ok(f"{name}: resume built", pdf.exists() and docx.exists())
        if not pdf.exists():
            continue
        t = text_of(pdf)
        no_raw(f"{name} resume", t)
        if name == "export shape":  # the ledger form reaches the plain fields
            for w in ("홍길동", "가상전자(Example Electronics)", "플랫폼팀 / 선임", "2년 2개월", "총경력 3년 10개월", "가상 자격 1급"):
                ok(f"{name}: resume shows '{w}'", w in t)
            # The service row is drawn in the timeline figure, not in the text layer
            ok(f"{name}: timeline figure drawn", (OUT / "_figures" / f"{out}_timeline.png").exists())
            ok(f"{name}: ledger notes stay out", "원장 메모" not in t and "example.com/news" not in t)
            continue
        if name.split()[0] in ("compact", "table"):  # another form: its own parts, and what it leaves out
            form, edition = name.split()  # which form, which edition
            profile = json.loads((ROOT / prof).read_text(encoding="utf-8"))  # the example
            flat = re.sub(r"\s+", " ", t)  # the text on one line
            for r in profile["roles"]:  # every employer
                ok(f"{name}: shows {r['org']}", r["org"] in flat)  # nothing dropped: the document check holds its projects too
            words = {"ko": ("보유기술", "학력사항", "기타사항", "상세경력사항"), "en": ("Technical Skills", "Education", "Credentials", "Professional Experience")}[edition]  # the parts every form prints
            for w in words:  # each part
                ok(f"{name}: has '{w}'", w in flat)  # by its heading
            if form == "compact":  # one column
                ok(f"{name}: no table, no picture", docx_media(docx) == 0 and b"<w:tbl>" not in zipfile.ZipFile(docx).read("word/document.xml"), f"{docx_media(docx)} pictures")  # what a program reads best
                ok(f"{name}: no overview cards", ("지향 직무" if edition == "ko" else "Target role").lower() not in flat.lower())  # left to the detailed form
            else:  # tables
                ok(f"{name}: has its title", ("이력서" if edition == "ko" else "Resume") in flat.replace(" ", ""))  # the document's name, spaced out in Korean
                ok(f"{name}: tables are there", b"<w:tbl>" in zipfile.ZipFile(docx).read("word/document.xml"))  # as the form says
            continue  # the deck is checked once, under the detailed form
        words = {"ko": ["총경력", "재직", "(승인 재설계)", "(주문 이벤트, 조회 캐시)", "기타사항", "발표", "행사 이름은 가상의 예제 값", "자기소개", "지원 동기", "공과대학"],
                 "en": ["total", "Tenure", "(Authorization redesign)", "(Order events, Lookup cache)", "Credentials", "Talks", "Event names are example values", "About Me", "Motivation", "College of Engineering"]}[name]
        for w in words:
            ok(f"{name}: resume shows '{w}'", w in re.sub(r"\s+", " ", t))
        ok(f"{name}: tenure per role", re.search(r"\d+년 \d+개월|\d+ yrs? \d+ mos?|\d+년|\d+ yrs?", t) is not None)
        ok(f"{name}: logos and figures embedded", docx_media(docx) >= 6, f"{docx_media(docx)} images")
        deck_checks(name, out, 13, {"ko": ["분리 전", "검토와 병합", "자동", "도입 후", "공개 출시", "API 서버", "Kafka"],
                                    "en": ["Before the split", "Review, merge", "Automated", "After", "Public launch", "API servers", "Kafka"]}[name])
    print(f"parts tests: {PASS[0]} passed, {FAIL[0]} failed")
    return 1 if FAIL[0] else 0


if __name__ == "__main__":
    sys.exit(main())
