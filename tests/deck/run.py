#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deck tests: the figure library, two figures per slide, the two-slide spread, and chapters that are not companies.

  python3 tests/deck/run.py             unit tests, then build the decks (heavy: Chromium in the render container) and check them
  python3 tests/deck/run.py --no-build  unit tests and the checks of decks already in output/
  python3 tests/deck/run.py --unit      unit tests only (node and python, no container, no model)

What it builds (deck only: figures, deck HTML, Chromium print and probe; no LibreOffice):
  - the figure gallery (tests/deck/gallery.js): every template in light and dark, at the main and the side size, Korean and English;
  - the full fixture: the fictional examples/sample_full_<lang>.json with a research chapter, a project over two slides and two
    figures on the project slides, written to output/_deckw/ at test time.
Checks: the browser probe finds no defect (one-word last lines are warnings, as in the document check), nothing was cut from a figure,
the slide counts, the spread's page marks and page range, the research chapter's divider and timeline, figures per project slide,
card marks, and no raw markup in the PDF text.
Prints one line per failed check and ends with 'deck tests: N passed, M failed'.
"""
import json  # probe, cut and fixture files
import pathlib  # paths
import re  # text checks
import subprocess  # node, the container, pdftotext
import sys  # arguments

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
OUT = ROOT / "output"  # build outputs (git ignores it)
FIX = OUT / "_deckw"  # fixtures written at test time
PASS, FAIL = [0], [0]  # counters (lists so the helpers can change them)


def ok(name, cond, detail=""):
    """Count one check and print it when it fails"""
    if cond:  # a pass
        PASS[0] += 1  # is only counted
    else:
        FAIL[0] += 1  # a failure is counted
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))  # and printed with its detail


def sh(args: list, **kw) -> subprocess.CompletedProcess:
    """A command inside the render container (render/run.sh mounts the repository at /work), niced on the host"""
    # Niced so a build never starves the desktop; output captured for the checks
    return subprocess.run(["nice", "-n", "15", str(ROOT / "render" / "run.sh")] + args, cwd=ROOT, capture_output=True, text=True, **kw)


# Inside the container: draw the figures (timelines, logo tiles), the deck HTML, print it, open it again for the probe.
# File names arrive as positional arguments ($1...), never spliced into the script (the rule resume.py follows)
CHROME = "chromium --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars --virtual-time-budget=30000 "
# Fonts; then figures and deck from a profile (exit 3, 4) or the gallery (exit 4); the PDF; the DOM for the probe, removed after
DECK = ('bash src/fonts.sh >/dev/null 2>&1; '
        'if [ -n "$1" ]; then python3 src/overview_figures.py "$1" "$3" "$4" >/dev/null || exit 3; node src/deck_slides.js "$1" "$2" >/dev/null || exit 4; '
        'else node tests/deck/gallery.js "$4" "$3" >/dev/null || exit 4; fi; '
        + CHROME + '--user-data-dir=/tmp/chr --no-pdf-header-footer --print-to-pdf="output/$3_deck.pdf" "output/$3_deck.html" 2>/dev/null && '
        + CHROME + '--user-data-dir=/tmp/chr2 --window-size=1400,900 --dump-dom "output/$3_deck.html" 2>/dev/null > "output/$3_deck.dom" && '
        'python3 src/probe_extract.py "output/$3_deck.dom" "output/$3_deck.probe.json"; rc=$?; rm -f "output/$3_deck.dom"; exit $rc')


def build(profile: str, job: str, out: str, lang: str) -> str:
    """Build one deck; an empty profile builds the gallery. Returns the last line of the build's output ('' when it went well)"""
    for suf in ("_deck.pdf", "_deck.probe.json", "_deck.html"):  # old outputs must not pass for new ones
        (OUT / f"{out}{suf}").unlink(missing_ok=True)  # a failed build then shows as missing files
    r = sh(["bash", "-c", DECK, "_", profile, job, out, lang])  # the names arrive as $1 to $4 ($0 is a placeholder)
    return "" if r.returncode == 0 else ((r.stdout + r.stderr).strip().splitlines() or [f"exit {r.returncode}"])[-1]  # the last output line says why it failed


def fixture(lang: str) -> tuple:
    """The full fixture: the fictional sample_full example plus a research chapter, a two-slide project and second figures.
    Returns (profile path, job path) relative to the repository (the container sees /work)"""
    prof = json.loads((ROOT / "examples" / f"sample_full_{lang}.json").read_text(encoding="utf-8"))  # the fictional example profile
    gal = json.loads((ROOT / "tests" / "deck" / "fixtures" / "gallery.json").read_text(encoding="utf-8"))[lang]  # the gallery's figures supply the extra ones
    proj = {p["id"]: p for r in prof["roles"] for p in r["projects"]}  # the example's projects by id
    marked = lambda cards: [list(c[:2]) + [i + 1] for i, c in enumerate(cards)]  # number every card (figure parts carry the same numbers)
    a1 = proj["alpha-1"]  # one main multi-panel figure and a side metric, cards numbered like the panels
    a1["figure"], a1["figures"], a1["cards"] = gal["panels"], [gal["metric"]], marked(a1["cards"])  # the cards numbered to match the panels' marks
    a2 = proj["alpha-2"]  # a project over two slides: the path and its scripts first, the platform's parts and its rollout second
    a2["pages"] = [{"figure": a2.pop("figure"), "figures": a2.pop("figures"), "cards": a2.pop("cards")},  # page one: the project's own figures and cards
                   {"lede": a2["summary"], "figure": gal["tree"], "figures": [gal["timeline"]],  # page two: a tree with a timeline beside it
                    # Page two's cards, worded from the two figures' own captions and labels
                    "cards": [[gal["tree"]["caption"].split("**")[1], gal["tree"]["root"][1]], [gal["timeline"]["caption"].split("**")[1], gal["timeline"]["phases"][1][0]]]}]
    proj["alpha-3"]["figures"] = [gal["gantt"]]  # too wide for the side: it joins the matrix as a second panel
    proj["beta-2"]["figures"] = [gal["columns"]]  # the cache with its response times on the side
    proj["gamma-1"]["figures"] = [gal["rack"]]  # replaces the cluster squares with the rack layout
    # A slide without cards whose two figures are both composites, as a drawing step can leave them: their panels join one frame, never nest
    proj["beta-1"]["figure"], proj["beta-1"]["figures"] = {**gal["panels"], "panels": gal["panels"]["panels"][1:]}, [{**gal["panels"], "panels": gal["panels"]["panels"][2:]}]
    ko = lang == "ko"  # the edition picks every text below
    prof["chapters"] = [{  # a chapter that is not a company: research done during the degree, its study bar dark on the timeline
        "key": "research", "kind": "research", "name": "연구" if ko else "Research", "enName": "Research",  # the key names its timeline and logo files
        "title": "연구원" if ko else "Research assistant", "start": "2016.03", "end": "2018.12", "place": "서울" if ko else "Seoul",  # the role, the period and the place
        # The funder fills the divider's meta line; timeline names the education entry whose bar turns dark
        "funder": "가상 연구재단" if ko else "Example Research Foundation", "timeline": "ganada", "logo": {"text": "R", "color": "#2F6EBA"},
        # The chapter's lead line under its title
        "lead": ("가상의 연구실에서 센서망 프로토콜과 경로 계획을 연구했습니다." if ko else "In a fictional lab I studied sensor network protocols and path planning."),
        "stack": [["통신" if ko else "Networks", ["MAC", "NS-2"]], ["도구" if ko else "Tools", ["Python", "C#"]]],  # the divider's stack rows
        # One project over the research period
        "projects": [{"id": "research-1", "title": "센서망 MAC 연구" if ko else "Sensor network MAC research", "period": "2016.03 ~ 2018.12",
                      "tagline": "깨어나는 주기를 교통량에 맞춤" if ko else "Wake cycles that follow traffic",  # the grey line after the title
                      # The project header's role and context
                      "role": "연구원" if ko else "Research assistant", "context": "가상 연구실" if ko else "A fictional lab", "stack": "NS-2, Python",
                      # The lede under the header
                      "lede": ("교통량이 늘면 센서가 더 자주 깨어나는 주기 규칙을 설계했습니다." if ko else "I designed a wake-cycle rule that wakes sensors more often as traffic grows."),
                      "figure": gal["architecture"], "figures": [gal["trend"]],  # a main and a side figure
                      # Two cards, numbered 1 and 2
                      "cards": [["주기 규칙" if ko else "The cycle rule", "교통량에 따라 다음 주기를 정함" if ko else "The next cycle follows the traffic", 1],
                                # The second card closes the chapter
                                ["시뮬레이터 비교" if ko else "Simulator comparison", "같은 조건에서 기존 규칙과 비교" if ko else "Compared with the old rule under the same conditions", 2]]}]}]
    FIX.mkdir(parents=True, exist_ok=True)  # output/_deckw, made on first use
    pf, jf = FIX / f"deck_full_{lang}.json", FIX / f"deck_full_{lang}.job.json"  # the profile and the job file of this edition
    pf.write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding="utf-8")  # written fresh on every run
    jf.write_text(json.dumps({"out": f"deckw_full_{lang}", "lang": lang, "deck": "chapters"}), encoding="utf-8")  # the chapter layout, under its own output name
    return str(pf.relative_to(ROOT)), str(jf.relative_to(ROOT))  # relative, since the container mounts the repository elsewhere


def text_of(pdf: pathlib.Path) -> str:
    """PDF text layer (host pdftotext, or the container's)"""
    try:  # the host's pdftotext first
        return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout  # the text to stdout
    except FileNotFoundError:  # not installed on the host
        return sh(["pdftotext", str(pdf.relative_to(ROOT)), "-"]).stdout  # the container has it


def slides_html(html: str) -> list:
    """Each slide's HTML (the deck writes one <section class="slide ..."> per slide)"""
    return re.findall(r'<section class="slide[^"]*"[\s\S]*?</section>', html)  # each section up to its own end


def deck_checks(name: str, out: str, want: int):
    """The browser probe and the cut list of one deck"""
    pdf, html, probe = OUT / f"{out}_deck.pdf", OUT / f"{out}_deck.html", OUT / f"{out}_deck.probe.json"  # the build's three outputs
    ok(f"{name}: deck built", pdf.exists() and html.exists() and probe.exists())  # all three must exist
    if not probe.exists():  # no probe
        return None  # means no further checks
    slides = json.loads(probe.read_text(encoding="utf-8"))["slides"]  # one record per slide
    ok(f"{name}: {want} slides", len(slides) == want, f"{len(slides)} slides")  # the expected count
    # Every issue except one-word last lines (warnings), then the figure findings
    defects = [f"{s['n']}: {i}" for s in slides for i in s["issues"] if "one-word last line" not in i] + \
              [f"{s['n']}: {i['kind']} {i['msg']}" for s in slides for i in s.get("svg", [])]  # the probe's findings inside figures
    ok(f"{name}: no deck defects", not defects, f"{len(defects)}: " + "; ".join(defects[:6]))  # the first six shown
    # A missing cut file counts as a failure
    cut = json.loads((OUT / f"{out}_deck.cut.json").read_text(encoding="utf-8")) if (OUT / f"{out}_deck.cut.json").exists() else ["no cut file"]
    ok(f"{name}: nothing cut from figures", not cut, "; ".join(cut[:4]))  # no figure text was shortened
    t = text_of(pdf)  # the PDF's text layer
    # Markup and broken values that must never reach the page
    for label, pat in (("==", r"=="), ("**", r"\*\*"), ("undefined", r"\bundefined\b"), ("NaN", r"\bNaN\b"), ("[object", r"\[object")):
        m = re.search(pat, t)  # the first hit
        ok(f"{name}: no raw '{label}'", not m, t[max(0, m.start() - 30):m.end() + 30].replace("\n", " ") if m else "")  # shown with 30 characters around it
    return {"slides": slides, "text": t, "html": html.read_text(encoding="utf-8")}  # for the full fixture's checks


def full_checks(lang: str, res: dict):
    """What the full fixture must show: the spread, the research chapter, two figures per project slide, card marks"""
    if not res:  # the deck did not build
        return  # its failures are already counted
    t, html, name = re.sub(r"\s+", " ", res["text"]), res["html"], f"full {lang}"  # the text with whitespace collapsed
    secs = slides_html(html)  # each slide's HTML
    ok(f"{name}: spread pages marked", "(1/2)" in t and "(2/2)" in t)  # both pages of the two-slide project
    dash = "-" if lang == "en" else "~"  # the edition's range mark
    ok(f"{name}: spread page range in the chapter list", re.search(rf'class="pg">\d+{re.escape(dash)}\d+<', html) is not None)  # a page range such as 7-8 in the contents
    funder = "Funder" if lang == "en" else "연구 지원"  # the research kind's word for its partner
    ok(f"{name}: research chapter divider", any('class="slide chapter' in s and funder in s for s in secs))  # a divider slide that names the funder
    # The timeline drawn with the research chapter dark
    ok(f"{name}: research chapter timeline", (OUT / "_figures" / f"deckw_full_{lang}_timeline_ch_ch_research{'_en' if lang == 'en' else ''}.png").exists())
    ok(f"{name}: research chapter in the contents and rail", t.count("Research" if lang == "en" else "연구") >= 3)  # its name on the divider, the contents and the rail
    proj = [s for s in secs if 'class="pmeta"' in s]  # project slides
    count = lambda s0: sum(len(m.split("+")) if m.startswith("panels:") else 1 for m in re.findall(r'data-figure="([^"]+)"', s0))   # figures, panels one by one
    two = [s for s in proj if count(s) >= 2]  # slides showing two figures or more
    ok(f"{name}: project slides with two figures or a multi-panel figure", len(two) >= 6, f"{len(two)} of {len(proj)}")  # the fixture gives six or more such slides
    ok(f"{name}: card marks", sum(s.count('class="mk"') for s in proj) >= 5)  # number badges on the cards


def unit():
    """The fast tests: node figure tests and the drafting step with a stand-in backend"""
    r = subprocess.run(["node", str(ROOT / "tests" / "deck" / "figures_test.js")], capture_output=True, text=True)  # the node figure tests
    ok("figure unit tests", r.returncode == 0, (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1])  # their summary line, or the error
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "deck" / "test_figure_draft.py")], capture_output=True, text=True)  # the drafting tests with the stand-in
    ok("figure draft tests", r.returncode == 0, (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1])  # their summary line, or the error


def main() -> int:  # the exit code: 0 passed, 1 failed
    unit()  # the fast tests always run
    if "--unit" not in sys.argv:  # the deck checks unless --unit
        building = "--no-build" not in sys.argv  # --no-build checks decks already in output/
        for lang in ("ko", "en"):  # both editions
            if building:  # fresh builds first
                last = build("", "", f"deckw_gallery_{lang}", lang)  # the gallery (no profile)
                ok(f"gallery {lang}: build", not last, last)  # the build's last line on failure
                prof, job = fixture(lang)  # the full fixture written for this edition
                last = build(prof, job, f"deckw_full_{lang}", lang)  # the full deck
                ok(f"full {lang}: build", not last, last)  # the build's last line on failure
            # Two slides per template, light and dark
            n_gal = 2 * len(json.loads((ROOT / "tests" / "deck" / "fixtures" / "gallery.json").read_text(encoding="utf-8"))[lang])
            deck_checks(f"gallery {lang}", f"deckw_gallery_{lang}", n_gal)  # the probe and cut checks
            full_checks(lang, deck_checks(f"full {lang}", f"deckw_full_{lang}", 16))  # sixteen slides, then the fixture's own checks
            # The other colour sets and the light deck: the same slides, with every measure of the deck on them. Each set in one look, the two looks in turn
            for theme, look in (("teal", "classic"), ("mono", "clean"), ("wine", "clean"), ("forest", "classic"), ("slate", "clean")) if lang == "ko" else (("wine", "clean"), ("forest", "classic")):
                name = f"deckw_{theme}_{lang}"  # this build's output name
                prof2, job2 = fixture(lang)  # the same fixture
                jf = ROOT / job2  # its job file
                jf.write_text(json.dumps({**json.loads(jf.read_text(encoding="utf-8")), "out": name, "theme": theme, "deckStyle": look}), encoding="utf-8")  # another colour, and a look
                if building:  # a fresh build
                    last = build(prof2, job2, name, lang)  # the deck
                    ok(f"{theme} {look} {lang}: build", not last, last)  # its last line on failure
                deck_checks(f"{theme} {look} {lang}", name, 16)  # the probe and cut checks, contrast among them
                body = (OUT / f"{name}_deck.html").read_text(encoding="utf-8")  # the page
                body = body[body.index("<body"):]  # the slides, without the theme's own defaults
                ok(f"{theme} {look} {lang}: no figure stays navy", "#1B2E4B" not in body.upper(), str(body.upper().count("#1B2E4B")))  # the colour set reached every drawing
    print(f"deck tests: {PASS[0]} passed, {FAIL[0]} failed")  # the summary line
    return 1 if FAIL[0] else 0  # any failure fails the run


if __name__ == "__main__":  # run as a command
    sys.exit(main())  # main's return value is the exit code
