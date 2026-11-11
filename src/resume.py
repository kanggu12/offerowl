#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The commands that turn a profile into documents. Runs on the host. Typesetting runs in one of two renderers, chosen
with OFFEROWL_RENDERER: `container` (the default) runs LibreOffice and Chromium in the render container (render/run.sh);
`html` runs on the host with the Edge or Chrome already installed and needs no Docker (src/render_html, docs/ARCHITECTURE.md).
The AI backends are CLIs that live on the host.

People call these through the launcher (`./offerowl <command>`); `python3 src/resume.py <command>` still works.

  init <folder> [--force] [--dry-run]     copy the example profile and settings into <folder>
  ingest <folder or file>...              propose fact candidates from raw material (src/ingest.py; uses the AI backend)
  draft write|jd|translate|figures <profile.json> [...]   AI proposals as new profile files (src/draft.py)
  build <profile.json> [job.json]         resume (DOCX, PDF) and portfolio deck (PDF) in output/, then check them
  selftest [--if-changed]                 build the example end to end and check it
  llm [--list | --probe <backend>]        which AI backends exist and which one is in use
"""
import hashlib  # copy names for inputs outside the repository, and the self-test input fingerprint
import json  # settings files
import os  # a copy of the environment for one child process
import pathlib  # paths
import re  # make output names safe
import shutil  # copy the example, look for docker
import subprocess  # the container and the other scripts
import sys  # arguments, and the module search path

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
sys.path.insert(0, str(ROOT / "src"))  # sibling modules import the same way however this file was started
import llm  # noqa: E402  settings and the language of messages (needs the line above)

EXAMPLE = ROOT / "examples" / "sample_ko.json"  # the example profile (a fictional person)

# What the self-test expects of the example. The words are text of the Korean example profile, not messages.
RESUME_PAGES = 2  # the example resume is two pages: overview, core competencies, introduction and motivation included
DECK_SLIDES = 6  # cover, overview, three figure slides and the end slide
WANT = ["홍길동", "알파페이", "베타커머스", "승인 경로를 독립 배포 단위로", "정보처리기사", "Kubernetes",
        "개요", "대표 프로젝트", "핵심역량", "자기소개", "지원 동기", "주문 이벤트 파이프라인"]
DECK_WANT = ["홍길동", "경력 한눈에", "분리 전", "Argo CD 동기화", "Kafka", "END OF DOCUMENT", "주문 조회 캐시 도입"]
# The planted-defect check reads the document check's own wording. If src/check_documents.py changes or translates this
# message, change these two lines with it. The self-test runs that check with OFFEROWL_LANG=ko so the Korean text is stable.
PLANTED_MARKER = "과제가 빠졌다: 이력서에 없는 과제"  # "project missing: ..." the defect we planted
NO_STYLE_MARKER = "문체 묶음이 없다"  # "the style pack is missing": a different failure that must not pass for success


# ---------------------------------------------------------------- messages

# Everything this module prints for a person, in both languages. Placeholders are {names}; tests/cli checks that the
# two languages have the same keys and the same placeholders.
MSG = {
    "en": {
        "cmd_init": "Copy the example profile and settings into a folder to start from",
        "cmd_ingest": "Read your old resumes, reports and slides and propose fact candidates (uses the AI backend)",
        "cmd_draft": "Ask the AI backend for sentences, job-posting fit, a translation or figure ideas (uses the AI backend)",
        "cmd_build": "Build the resume and the portfolio deck from a profile, then check them (needs Docker, or Chrome or Edge)",
        "cmd_selftest": "Build the fictional example end to end and check it (needs Docker, or Chrome or Edge)",
        "cmd_llm": "Show which AI backend is in use and which ones are available",
        "usage_head": "Usage: {prog} <command> [options]",
        "commands": "Commands:",
        "unknown_command": "Unknown command: {name}. Run `{prog} --help` for the list.",
        "usage_init": ("Usage: offerowl init <folder> [--force] [--dry-run]\n"
                       "  Copies the example profile (profile.json) and a settings file (job.json) into <folder>.\n"
                       "  Files that already exist are kept unless you add --force.\n"
                       "  --dry-run only lists what would be written."),
        "usage_build": ("Usage: offerowl build <profile.json> [job.json]\n"
                        "  Builds the resume (DOCX, PDF) and the portfolio deck (PDF) into output/, then checks them.\n"
                        "  job.json holds the output name, language (ko or en), theme and the style pack."),
        "usage_selftest": ("Usage: offerowl selftest [--if-changed]\n"
                           "  Builds the fictional example end to end and checks it. --if-changed skips the run when the\n"
                           "  inputs have not changed since the last pass."),
        "need_docker": "Docker was not found. Typesetting runs in a container; install Docker and try again, or set OFFEROWL_RENDERER=html to typeset with Chrome or Edge.",
        "need_html": "The browser renderer (OFFEROWL_RENDERER=html) is missing on this PC: {what}.",
        "container_on_windows": "The container renderer starts render/run.sh, a shell script, which Windows cannot run: leave OFFEROWL_RENDERER unset or set it to html to typeset with Chrome or Edge, or run Offerowl inside WSL.",
        "part_browser": "Chrome or Edge",
        "part_node": "Node.js",
        "part_pillow": "Pillow for Python",
        "part_libs": "the typesetting libraries (OFFEROWL_NET=1 render/run.sh npm ci)",
        "part_fonts": "the font files",
        "bad_renderer": "OFFEROWL_RENDERER must be html or container, not {value}.",
        "file_missing": "File not found: {path}",
        "init_exists": "{folder} already has {files}. Add --force to overwrite.",
        "init_done": "Wrote {folder}/profile.json and job.json. Edit them, then run: offerowl build {folder}/profile.json {folder}/job.json",
        "init_dry": ("Dry run, nothing was written. These files would go into {folder}:\n"
                     "  {folder}/profile.json  the example profile (a fictional person)\n"
                     "  {folder}/job.json      settings of one build"),
        "build_failed": "Build failed:",
        "deck_failed": "Deck build failed:",
        "blind_deck_left": "The blind edition leaves out the portfolio you made: its pages cannot be covered.",
        "selftest_resume_fail": "Self-test: {pages} pages (expected {want}), missing {missing}  FAIL",
        "selftest_deck_fail": "Deck self-test: {pages} slides (expected {want}), missing text {missing}  FAIL",
        "selftest_check_fail": "Self-test: the example did not pass the document check  FAIL",
        "selftest_planted_fail": "Self-test: the check missed a planted defect (a project that is not in the resume)  FAIL",
        "selftest_ocr_fail": "Self-test: the scanned-PDF OCR test failed  FAIL",
        "selftest_pass": ("Self-test: example resume {pages} pages, deck {slides} slides, {words} words checked, "
                          "document check passed, planted defect caught, OCR  PASS"),
        "selftest_skip": "Self-test: the inputs are unchanged since the last pass, skipped",
    },
    "ko": {
        "cmd_init": "예제 프로필과 설정을 폴더에 복사한다(여기서부터 고쳐 쓴다)",
        "cmd_ingest": "예전 이력서, 보고서, 슬라이드에서 사실 후보를 뽑는다(AI 백엔드를 쓴다)",
        "cmd_draft": "AI 백엔드에 문장 초안, 공고 맞춤, 번역, 그림 제안을 맡긴다(AI 백엔드를 쓴다)",
        "cmd_build": "프로필로 이력서와 포트폴리오 덱을 만들고 검사한다(Docker, 또는 Chrome이나 Edge가 필요하다)",
        "cmd_selftest": "가상의 예제로 처음부터 끝까지 만들고 검사한다(Docker, 또는 Chrome이나 Edge가 필요하다)",
        "cmd_llm": "쓰이는 AI 백엔드와 쓸 수 있는 백엔드를 보인다",
        "usage_head": "쓰는 법: {prog} <명령> [옵션]",
        "commands": "명령:",
        "unknown_command": "모르는 명령: {name}. `{prog} --help`로 목록을 본다.",
        "usage_init": ("쓰는 법: offerowl init <폴더> [--force] [--dry-run]\n"
                       "  예제 프로필(profile.json)과 설정 파일(job.json)을 <폴더>에 복사한다.\n"
                       "  이미 있는 파일은 --force를 붙이지 않으면 덮어쓰지 않는다.\n"
                       "  --dry-run은 쓸 파일을 보이기만 한다."),
        "usage_build": ("쓰는 법: offerowl build <profile.json> [job.json]\n"
                        "  이력서(DOCX, PDF)와 포트폴리오 덱(PDF)을 output/ 에 만들고 검사한다.\n"
                        "  job.json에는 산출물 이름, 언어(ko 또는 en), 색 묶음, 문체 묶음을 적는다."),
        "usage_selftest": ("쓰는 법: offerowl selftest [--if-changed]\n"
                           "  가상의 예제로 처음부터 끝까지 만들고 검사한다. --if-changed는 지난 통과 뒤\n"
                           "  입력이 그대로면 건너뛴다."),
        "need_docker": "Docker를 찾지 못했다. 조판은 컨테이너에서 돈다. Docker를 설치한 뒤 다시 하거나, OFFEROWL_RENDERER=html을 설정해 Chrome이나 Edge로 조판한다.",
        "need_html": "브라우저 조판(OFFEROWL_RENDERER=html)에 필요한 것이 이 PC에 없다: {what}",
        "container_on_windows": "컨테이너 조판은 셸 스크립트 render/run.sh로 시작하는데, Windows는 그것을 실행하지 못한다. OFFEROWL_RENDERER를 비우거나 html로 두어 Chrome이나 Edge로 조판하거나, WSL 안에서 Offerowl을 실행한다.",
        "part_browser": "Chrome 또는 Edge",
        "part_node": "Node.js(자바스크립트 실행기)",
        "part_pillow": "Python용 Pillow",
        "part_libs": "조판 라이브러리(OFFEROWL_NET=1 render/run.sh npm ci)",
        "part_fonts": "글꼴 파일",
        "bad_renderer": "OFFEROWL_RENDERER는 html 또는 container여야 한다. 지금 값: {value}",
        "file_missing": "파일이 없다: {path}",
        "init_exists": "이미 있는 파일({folder}): {files}. 덮어쓰려면 --force를 붙인다.",
        "init_done": "{folder}/profile.json, job.json을 만들었다. 고친 뒤: offerowl build {folder}/profile.json {folder}/job.json",
        "init_dry": ("시험 실행이라 아무것도 쓰지 않았다. 쓸 파일({folder}):\n"
                     "  {folder}/profile.json  예제 프로필(가상의 사람)\n"
                     "  {folder}/job.json      한 번 만들 때의 설정"),
        "build_failed": "빌드 실패:",
        "deck_failed": "덱 빌드 실패:",
        "blind_deck_left": "블라인드판에는 직접 만든 포트폴리오를 넣지 않는다. 그 쪽들은 가릴 수 없다.",
        "selftest_resume_fail": "자체 시험: 쪽 {pages}({want} 이어야), 빠진 것 {missing}  실패",
        "selftest_deck_fail": "덱 자체 시험: 쪽 {pages}({want} 이어야), 빠진 글 {missing}  실패",
        "selftest_check_fail": "자체 시험: 예제가 문서 검사를 통과하지 못했다  실패",
        "selftest_planted_fail": "자체 시험: 심은 결함(빠진 과제)을 검사가 못 잡았다  실패",
        "selftest_ocr_fail": "자체 시험: 스캔 PDF OCR 시험 실패  실패",
        "selftest_pass": ("자체 시험: 예제 이력서 {pages}쪽, 덱 {slides}장, 확인 낱말 {words}개, "
                          "문서 검사 통과, 심은 결함 잡음, OCR  통과"),
        "selftest_skip": "자체 시험: 입력이 지난 통과 뒤 그대로라 건너뜀",
    },
}


def t(key: str, **kw) -> str:
    """A message of this module in the current language"""
    return llm.message(MSG, key, **kw)


# ---------------------------------------------------------------- running things

RENDERERS = ("container", "html")  # the two ways to typeset: the render container, or the PC's own browser


_BROWSER_OK = []  # the answer of browser_can_typeset, once it is known: it looks for a browser and for fonts


def browser_can_typeset() -> bool:
    """Can the html renderer run on this PC? Asked once per run, and only on a PC with no Docker."""
    if not _BROWSER_OK:  # the first time
        try:  # a broken probe must not stop the message about what to install
            _BROWSER_OK.append(bool(html_renderer().doctor()["html"]["ok"]))  # its own report
        except Exception:  # noqa: BLE001  whatever went wrong, the browser is not usable
            _BROWSER_OK.append(False)  # the message about Docker follows
    return _BROWSER_OK[0]


def renderer() -> str:
    """The renderer in use: OFFEROWL_RENDERER; when unset, the container where Docker is here, else the PC's browser where it can
    typeset, so a PC with no Docker just works. On Windows it is the browser, Docker or not: the container is started by
    render/run.sh, a shell script Windows cannot run. An unknown value stops with a message instead of falling back, so a typo
    never silently picks the other renderer"""
    value = llm.setting("RENDERER", "").strip().lower()  # an empty value means no choice was made
    if not value:  # no choice: what this PC can run
        if sys.platform == "win32" and not in_container():  # Windows: the browser, and its own message when something is missing
            return "html"
        return "container" if in_container() or shutil.which("docker") or not browser_can_typeset() else "html"  # with neither, the message about Docker says what to do
    if value not in RENDERERS:
        raise SystemExit(t("bad_renderer", value=value))
    return value


def in_container() -> bool:
    """Inside the render container the tools are called directly, without render/run.sh"""
    return pathlib.Path("/.dockerenv").exists()


def local() -> bool:
    """True when the typesetting tools run in this process's own system: inside the container, or with the html renderer"""
    return in_container() or renderer() == "html"


def sh(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a typesetting or measuring tool. With the container renderer it goes through render/run.sh, because LibreOffice and
    the fonts live in the container. With the html renderer (and inside the container) it runs here; `python3` is then
    this Python, since Windows has no python3 command"""
    if local():
        full = [sys.executable] + cmd[1:] if cmd[:1] == ["python3"] else cmd
        env = dict(env or os.environ, PYTHONDONTWRITEBYTECODE="1")  # no .pyc files in the repository, as run.sh does
    elif sys.platform == "win32":  # OFFEROWL_RENDERER=container on Windows: run.sh cannot start here
        raise SystemExit(t("container_on_windows"))
    else:
        full = [str(ROOT / "render" / "run.sh")] + cmd
    return subprocess.run(full, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def docker_missing() -> bool:
    """True when typesetting would need Docker and it is not installed (inside the container the tools are already
    there, and the html renderer needs no Docker)"""
    return not local() and shutil.which("docker") is None


def html_renderer():
    """src/render_html/render.py, loaded under a private name (its siblings browser and fonts have common names)"""
    import importlib.util  # a module from a file, under the name chosen here
    if "offerowl_render" not in sys.modules:
        spec = importlib.util.spec_from_file_location("offerowl_render", ROOT / "src" / "render_html" / "render.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["offerowl_render"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["offerowl_render"]


def html_missing() -> list[str]:
    """What the html renderer lacks on this PC (a browser, Node.js, Pillow, fonts), empty when it can run"""
    if renderer() != "html":
        return []
    return html_renderer().doctor()["html"]["needs"]


def missing_words(needs: list[str]) -> str:
    """The missing parts in plain words of the message language"""
    words = {"browser": t("part_browser"), "node": t("part_node"), "pillow": t("part_pillow"), "node_modules": t("part_libs")}
    return ", ".join(words.get(n, t("part_fonts") if n.startswith("fonts:") else n) for n in needs)


def renderers() -> dict:
    """What each renderer needs on this PC and whether it can run: the report behind `offerowl doctor`"""
    report = html_renderer().doctor()
    report["in_use"] = renderer()
    return report


def node() -> str:
    """The Node.js command for the DOCX and deck writers on the host"""
    return shutil.which("node") or "node"


def rel(p: str) -> str:
    """The container mounts the repository at /work, so paths go over as repository-relative, written with / on every system
    (a staged profile names its logos with them, and Windows would write \\). A file outside the repository is copied into
    output/_inputs/ first: init creates a starter in any folder, and build must not refuse it for being outside the
    repository. Moving files is not left to the user"""
    path = pathlib.Path(p).resolve()
    try:
        return path.relative_to(ROOT).as_posix()  # already inside the repository
    except ValueError:
        # A short hash of the full path keeps two files with the same name apart.
        dst = ROOT / "output" / "_inputs" / (hashlib.sha1(str(path).encode()).hexdigest()[:8] + "_" + re.sub(r"[^\w가-힣.-]", "_", path.name))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dst)
        if path.suffix == ".json":  # a profile names its logo pictures by path: they go where the container sees them too
            stage_logos(path, dst)
        return dst.relative_to(ROOT).as_posix()


def stage_logos(src: pathlib.Path, dst: pathlib.Path) -> None:
    """A staged profile's logo pictures (companies, schools, projects), copied into output/_inputs/ beside it with their paths
    rewritten, so the typesetting finds them wherever it runs. A path is read as written, then from the profile's own folder."""
    try:
        prof = json.loads(dst.read_text(encoding="utf-8"))  # the staged copy
    except (OSError, ValueError):  # not JSON: nothing to do
        return
    if not isinstance(prof, dict) or not str(prof.get("schema", "")).startswith("resume-profile"):  # only a profile
        return
    changed = False
    holders = list(prof.get("roles") or []) + list(prof.get("education") or [])  # roles and schools
    holders += [p for r in prof.get("roles") or [] if isinstance(r, dict) for p in r.get("projects") or []]  # and projects
    for h in holders:
        lg = h.get("logo") if isinstance(h, dict) else None
        if not isinstance(lg, str) or not lg:  # a monogram, or none
            continue
        f = next((x for x in (pathlib.Path(lg), src.parent / lg) if x.is_file()), None)  # the picture as written, else beside the profile
        if f is None:  # nothing to copy: the typesetting leaves that row without a logo, as before
            continue
        h["logo"] = rel(str(f))  # repository-relative, inside output/_inputs/ when it lives elsewhere
        changed = True
    if changed:
        dst.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")


def out_name(profile: str, cfg: dict, suffix: str = "") -> str:
    """Name of the outputs: letters, digits, Hangul, - and _ only. Path and shell characters are replaced so that nothing is
    written outside output/ and no command can slip in (the server applies the same rule)"""
    return re.sub(r"[^\w가-힣-]", "_", cfg.get("out") or pathlib.Path(profile).stem)[:60] + suffix


def load_cfg(cfg: str | None) -> dict:
    """Read the settings file; no file means empty settings"""
    return json.loads(pathlib.Path(cfg).read_text(encoding="utf-8")) if cfg else {}


def job_file(profile: str, cfg: str | None) -> tuple:
    """(output name, settings path inside the repository). The output name is always written into the settings it hands over:
    a profile outside the repository is copied under a new name, and without this the typesetter would write files under a
    different name from the one we look for. The settings used are written to output/_inputs/<name>.job.json"""
    c = load_cfg(cfg)
    out = out_name(profile, c)
    c["out"] = out
    f = ROOT / "output" / "_inputs" / f"{out}.job.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    return out, f.relative_to(ROOT).as_posix()  # / on every system, as rel() writes it


# Shell snippets that run inside the container. File names are never spliced into the string; they arrive as positional
# arguments ($1, $2, $3). So a command placed in the settings' "out" cannot run, and a file name with a space is not
# split in two.
FONTS = "bash src/fonts.sh >/dev/null 2>&1; "  # register the fonts first or LibreOffice typesets with other fonts
CHROME = "chromium --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars --virtual-time-budget=30000 "


def build(profile: str, cfg: str | None = None, env: dict | None = None) -> pathlib.Path:
    """Make the resume DOCX from the profile and convert it to PDF; returns the PDF path. The old output is deleted first
    so that a failure cannot hide behind a file from an earlier run. env: the environment of this build's steps (the panel
    gives each edition its own, so a blind edition's switches never reach another one), else this process's"""
    if renderer() == "html":  # the PC's own browser instead of LibreOffice
        return build_html(profile, cfg, env)
    out, job = job_file(profile, cfg)
    pdf = ROOT / "output" / f"{out}.pdf"
    pdf.unlink(missing_ok=True)
    c = load_cfg(cfg)
    # Draw the overview figures (timeline, hierarchy) first (src/overview_figures.py); the theme name goes in as OFFEROWL_FIG_THEME.
    script = (FONTS + 'OFFEROWL_FIG_THEME="$5" python3 src/overview_figures.py "$1" "$3" "$4" "$2" >/dev/null && '
              'node src/resume_form.js "$1" "$2" && soffice --headless --convert-to pdf --outdir output "output/$3.docx" >/dev/null')
    r = sh(["bash", "-c", script, "_", rel(profile), job, out, c.get("lang") or "ko", c.get("theme") or "navy"], env)  # run.sh hands the blind switches on
    if r.returncode != 0 or not pdf.exists():
        raise SystemExit(t("build_failed") + "\n" + r.stdout[-1500:] + r.stderr[-1500:])
    stamp_meta(pdf, profile, cfg, "resume", env)  # its title and author
    return pdf


def docx_to_pdf(docx: pathlib.Path) -> pathlib.Path:
    """A Word file the person made, as a PDF: LibreOffice in the renderer's toolchain (the container, or this PC's). The
    output goes to output/ under the staged file's name; the old one is removed first."""
    src = rel(str(docx))  # staged where the toolchain reads it (output/_inputs in the container)
    out = ROOT / "output" / (pathlib.Path(src).stem + ".pdf")  # where LibreOffice writes it
    out.unlink(missing_ok=True)  # an old file must not pass for a new one
    if local():  # the PC's own LibreOffice
        soffice = shutil.which("soffice") or shutil.which("libreoffice")  # its command
        if not soffice:
            raise SystemExit(t("build_failed") + "\nLibreOffice")
        r = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(ROOT / "output"), str(ROOT / src)], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    else:
        r = sh(["bash", "-c", FONTS + 'soffice --headless --convert-to pdf --outdir output "$1" >/dev/null', "_", src])  # in the container
    if r.returncode != 0 or not out.exists():
        raise SystemExit(t("build_failed") + "\n" + (r.stdout or "")[-800:] + (r.stderr or "")[-800:])
    return out


def stamp_meta(pdf: pathlib.Path, profile: str, cfg: str | None, kind: str, env: dict | None = None) -> None:
    """The PDF's own title and the person's name as its author (src/pdfmeta.py). A browser leaves the page's file name
    as the title (owl_1a2b3c4d_ko), which is what a recruiter sees in the window's bar. A blind edition (env's
    OFFEROWL_BLIND) leaves out of both what its table covers, and its title says it is the blind edition."""
    import pdfmeta  # src/pdfmeta.py: an incremental update, no library
    try:
        person = json.loads(pathlib.Path(profile).read_text(encoding="utf-8")).get("person") or {}  # whose document
    except (OSError, ValueError):  # no profile to read: the file keeps what it has
        return
    lang = load_cfg(cfg).get("lang") or "ko"  # the edition's language
    raw = str(person.get("name") or "").strip()  # a ledger may write '홍 길 동 (Gil-Dong Hong)'
    m = re.match(r"^(.*?)\s*\(([A-Za-z][A-Za-z .,'-]+)\)$", raw)  # the Latin name in brackets
    ko, en = (m.group(1).strip(), m.group(2).strip()) if m else (raw, "")
    if re.fullmatch(r"[가-힣](\s[가-힣])+", ko):  # spaced syllables joined, as profile_loader.js cleanName does
        ko = ko.replace(" ", "")
    name = str((person.get("name_en") or en if lang == "en" else None) or ko or "").strip()  # the name as the edition writes it
    if not name:  # nothing to write
        return
    word = {"resume": ("이력서", "Resume"), "deck": ("포트폴리오", "Portfolio"), "cover": ("자기소개서", "Cover Letter")}[kind][lang == "en"]  # the document's kind
    import blind  # src/blind.py: a blind edition's table
    if blind.on(env):  # a blind edition: no covered word in its title or author, where no bar can stand
        table = blind.load(env)  # the table it was made with
        pdfmeta.stamp(pdf, blind.title(f"{name} {word}", table, lang), blind.plain(name, table) or table["footer"][lang])  # its label stands for a covered name
        return
    pdfmeta.stamp(pdf, f"{name} {word}", name)  # False for a file with cross-reference streams: it keeps its own


def run_steps(steps: list, env: dict, fail_key: str) -> None:
    """Run the writer steps of the html renderer one after the other on this PC; stop at the first that fails"""
    for cmd in steps:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if r.returncode != 0:
            raise SystemExit(t(fail_key) + "\n" + r.stdout[-1500:] + r.stderr[-1500:])


def html_env(base: dict | None = None, **extra) -> dict:
    """The environment of the writer steps: the build's own (base) or this process's settings, no .pyc files in the repository"""
    return dict(os.environ if base is None else base, PYTHONDONTWRITEBYTECODE="1", **extra)


def build_html(profile: str, cfg: str | None = None, env: dict | None = None) -> pathlib.Path:
    """The html renderer's resume: the same figures and the same DOCX as the container (overview_figures.py,
    resume_form.js), then the DOCX is typeset by the PC's browser (src/render_html) instead of LibreOffice"""
    missing = html_missing()
    if missing:
        raise SystemExit(t("need_html", what=missing_words(missing)))
    out, job = job_file(profile, cfg)
    pdf, docx = ROOT / "output" / f"{out}.pdf", ROOT / "output" / f"{out}.docx"
    for f in (pdf, docx):  # an old file must not pass for a new one
        f.unlink(missing_ok=True)
    c = load_cfg(cfg)
    run_steps([[sys.executable, "src/overview_figures.py", rel(profile), out, c.get("lang") or "ko", job],  # timeline and hierarchy, with the edition's choices
               [node(), "src/resume_form.js", rel(profile), job]],                                 # the DOCX
              html_env(env, OFFEROWL_FIG_THEME=c.get("theme") or "navy"), "build_failed")
    R = html_renderer()
    try:
        R.docx_to_pdf(docx, pdf)
    except RuntimeError as e:  # no browser, or it made no PDF
        raise SystemExit(t("build_failed") + "\n" + str(e))
    stamp_meta(pdf, profile, cfg, "resume", env)  # its title and author, not the page's file name
    return pdf


def build_deck_html(profile: str, cfg: str | None = None, env: dict | None = None) -> pathlib.Path:
    """The html renderer's deck: the same HTML as the container (deck_slides.js), printed and measured by the PC's browser"""
    missing = html_missing()
    if missing:
        raise SystemExit(t("need_html", what=missing_words(missing)))
    base, job = job_file(profile, cfg)
    out = base + "_deck"  # deck_slides.js appends _deck to the output name itself
    for suf in (".pdf", ".probe.json"):
        (ROOT / "output" / f"{out}{suf}").unlink(missing_ok=True)
    run_steps([deck_writer(rel(profile), job, out, env)], html_env(env), "deck_failed")  # the page, from the person's source or the profile
    R = html_renderer()
    import probe_extract  # noqa: E402  the deck's own measurement, read out of the DOM (src/ is on the path)
    page, pdf = ROOT / "output" / f"{out}.html", ROOT / "output" / f"{out}.pdf"
    try:
        R.html_to_pdf(page, pdf)
        (ROOT / "output" / f"{out}.probe.json").write_text(probe_extract.extract(R.dump_dom(page)), encoding="utf-8")
    except (RuntimeError, ValueError) as e:  # no browser, no PDF, or the page reported no measurement
        raise SystemExit(t("deck_failed") + "\n" + str(e))
    stamp_meta(pdf, profile, cfg, "deck", env)  # its title and author
    return pdf


def deck_source(env: dict | None = None) -> str | None:
    """The person's own deck source this build uses (OFFEROWL_DECK_SOURCE): a folder inside the repository, repository-relative,
    whose build.js writes the deck's page as src/deck_slides.js does (node build.js <profile> <job.json> <page name>, run in
    the engine's folder). None when the build names none, or the folder is not there: then the deck is drawn from the profile."""
    d = (env if env is not None else os.environ).get("OFFEROWL_DECK_SOURCE") or ""  # what the panel staged
    if not d or pathlib.Path(d).is_absolute() or ".." in pathlib.Path(d).parts:  # only a folder inside the repository
        return None
    return d if (ROOT / d / "build.js").is_file() else None  # its entry is there


def deck_writer(profile: str, job: str, page: str, env: dict | None = None) -> list:
    """The command that writes the deck's page output/<page>.html: the person's deck source when the build names one, else
    the deck drawn from the profile (deck_slides.js names its page itself, <out>_deck)."""
    src = deck_source(env)  # the person's own slides, if any
    return [node(), f"{src}/build.js", profile, job, page] if src else [node(), "src/deck_slides.js", profile, job]


def own_deck(profile: str, cfg: str | None) -> pathlib.Path | None:
    """The portfolio the person already made, when the profile names it for this language (deck.pdf: a path, or one per
    language): a deck that is better than one drawn from data is never replaced by one. None when it names none."""
    try:
        prof = json.loads(pathlib.Path(profile).read_text(encoding="utf-8"))  # the profile as the build reads it
    except (OSError, ValueError):  # no profile to read: the deck is drawn, and the drawing says what is wrong
        return None
    spec = (prof.get("deck") or {}).get("pdf") if isinstance(prof.get("deck"), dict) else None  # what it names, if anything
    lang = load_cfg(cfg).get("lang") or "ko"  # the edition's language
    path = spec.get(lang) if isinstance(spec, dict) else spec  # one per language, or one for both
    if not path:  # none for this language
        return None
    f = pathlib.Path(path) if pathlib.Path(path).is_absolute() else pathlib.Path(profile).resolve().parent / path
    if not f.is_file():
        raise SystemExit(t("deck_failed") + f"\n{f}")  # named but gone: never a silent fallback to a lesser deck
    return f


def blind_leaves_deck(profile: str, cfg: str | None, env: dict | None = None) -> bool:
    """A blind edition (env's OFFEROWL_BLIND) leaves out a portfolio the person made (the profile's deck.pdf): its pages are
    pictures of their own, which no bar can cover. True also when the profile names one that is gone: it is left out all
    the same, never replaced by a drawn deck"""
    import blind  # src/blind.py: the switch
    if not blind.on(env):  # an ordinary edition keeps the person's own portfolio
        return False
    if deck_source(env):  # the person's deck source covers its own words with the same table (its blind.js)
        return False
    try:
        return own_deck(profile, cfg) is not None  # the profile names one for this language
    except SystemExit:  # named but gone
        return True


def build_deck(profile: str, cfg: str | None = None, env: dict | None = None) -> pathlib.Path:
    """Make the portfolio deck HTML from the profile and print it to PDF with Chromium (src/deck_slides.js). The page is
    opened a second time so that the browser measures every slide; the result goes to .probe.json for the checks
    (src/probe_extract.py). Old outputs are deleted first. A profile that names the person's own portfolio PDF gets that
    deck, page for page, with its title and author and a measurement of what can be read from a PDF"""
    mine = None if deck_source(env) else own_deck(profile, cfg)  # a deck source is newer than any PDF it once made
    if mine:  # the person's own portfolio
        base, _ = job_file(profile, cfg)  # the output name the panel looks for
        pdf = ROOT / "output" / f"{base}_deck.pdf"  # where a drawn deck would land
        pdf.parent.mkdir(parents=True, exist_ok=True)  # output/ may not be there yet
        shutil.copyfile(mine, pdf)  # the person's own pages
        import pdftools  # its pages and their text
        n = pdftools.info(pdf)["pages"]
        slides = [{"n": i, "title": "", "issues": []} for i in range(1, n + 1)]  # a deck Offerowl did not draw: no layout measurement of its own
        (ROOT / "output" / f"{base}_deck.probe.json").write_text(json.dumps({"slides": slides, "own": True}), encoding="utf-8")
        stamp_meta(pdf, profile, cfg, "deck", env)  # its title and author
        return pdf  # nothing is drawn
    if renderer() == "html":  # the PC's own browser prints the same page
        return build_deck_html(profile, cfg, env)
    base, job = job_file(profile, cfg)
    out = base + "_deck"  # deck_slides.js appends _deck to the output name itself
    for suf in (".pdf", ".probe.json"):
        (ROOT / "output" / f"{out}{suf}").unlink(missing_ok=True)
    src = deck_source(env)  # the person's own slides, if any
    writer = f'node "{src}/build.js" "$1" "$2" "$3"' if src else 'node src/deck_slides.js "$1" "$2"'  # the page's writer
    script = (FONTS + writer + ' >/dev/null && '
              + CHROME + '--user-data-dir=/tmp/chr --no-pdf-header-footer --print-to-pdf="output/$3.pdf" "output/$3.html" 2>/dev/null && '
              + CHROME + '--user-data-dir=/tmp/chr2 --window-size=1400,900 --dump-dom "output/$3.html" 2>/dev/null > "output/$3.dom" && '
              + 'python3 src/probe_extract.py "output/$3.dom" "output/$3.probe.json"; rc=$?; rm -f "output/$3.dom"; exit $rc')
    r = sh(["bash", "-c", script, "_", rel(profile), job, out], env)  # run.sh hands the blind switches on
    pdf = ROOT / "output" / f"{out}.pdf"
    if r.returncode != 0 or not pdf.exists():
        raise SystemExit(t("deck_failed") + "\n" + r.stdout[-1500:] + r.stderr[-1500:])
    stamp_meta(pdf, profile, cfg, "deck", env)  # its title and author
    return pdf


def build_plain(profile: str, cfg: str | None = None) -> tuple:
    """The resume as plain words (src/resume_plain.js): a Word file with one column and a text file, for a job site that reads a
    file by itself or asks you to paste. Returns (docx, txt). It needs Node.js only, here or in the container"""
    out, job = job_file(profile, cfg)
    docx, txt = ROOT / "output" / f"{out}_plain.docx", ROOT / "output" / f"{out}_plain.txt"
    for f in (docx, txt):  # an old file must not pass for a new one
        f.unlink(missing_ok=True)
    r = sh(["node", "src/resume_plain.js", rel(profile), job])
    if r.returncode != 0 or not docx.exists():
        raise SystemExit(t("build_failed") + "\n" + r.stdout[-1500:] + r.stderr[-1500:])
    return docx, txt


def deck_page(profile: str, cfg: str | None = None, env: dict | None = None) -> pathlib.Path:
    """The deck's page as it will print, without printing it: the panel's live view. It needs no browser and no LibreOffice, so
    it runs on this PC when Node.js is here, even with the container renderer (whose image may not be built yet). env: the
    environment of its steps, else this process's"""
    out, job = job_file(profile, cfg)
    c = load_cfg(cfg)
    page = ROOT / "output" / f"{out}_deck.html"
    page.unlink(missing_ok=True)  # an old page must not pass for a new one
    lang, theme = c.get("lang") or "ko", c.get("theme") or "navy"
    if shutil.which("node"):  # the usual case
        # The timeline and the logo tiles first; without them the deck draws its plain timeline and no logos, so a failure stops nothing
        subprocess.run([sys.executable, "src/overview_figures.py", rel(profile), out, lang, job], cwd=ROOT, capture_output=True,
                       env=html_env(env, OFFEROWL_FIG_THEME=theme))
        run_steps([deck_writer(rel(profile), job, f"{out}_deck", env)], html_env(env), "deck_failed")  # from the person's source or the profile
        return page
    src = deck_source(env)  # the person's own slides, if any
    writer = f'node "{src}/build.js" "$1" "$2" "$3_deck"' if src else 'node src/deck_slides.js "$1" "$2"'  # the page's writer
    script = 'OFFEROWL_FIG_THEME="$5" python3 src/overview_figures.py "$1" "$3" "$4" "$2" >/dev/null; ' + writer + ' >/dev/null'  # in the container
    r = sh(["bash", "-c", script, "_", rel(profile), job, out, lang, theme], env)
    if r.returncode != 0 or not page.exists():
        raise SystemExit(t("deck_failed") + "\n" + r.stdout[-1500:] + r.stderr[-1500:])
    return page


def check(profile: str, cfg: str | None, pdf: pathlib.Path, deck: pathlib.Path | None) -> int:
    """Run the document check (src/check_documents.py) in the container. The settings' style (style pack) and maxPages
    (page limit) are handed over"""
    c = load_cfg(cfg)
    style = c.get("style") or "default"  # a shipped pack's name, or the path of the person's own
    if "/" in style or "\\" in style or style.endswith(".json"):  # a file: staged where the container sees it, as the panel does
        style = rel(style)
    cmd = ["python3", "src/check_documents.py", rel(profile), rel(str(pdf))] + ([rel(str(deck))] if deck else []) + \
          ["--style", style, "--max-pages", str(c.get("maxPages") or 3)]
    r = sh(cmd)
    print((r.stdout + r.stderr).strip())
    return r.returncode


# ---------------------------------------------------------------- self-test

# What the self-test depends on: everything under src/ (the typesetter, the modules it calls, the checks, the colour sets,
# the style packs), the example, the fonts, and the container recipe. If none of it changed, the last pass still holds.
# A folder is used and not a list of file names, because a list goes stale as soon as a file is added.
# Caches are left out: they change without the code changing.
SELFTEST_INPUTS = ["src", "examples", "fonts", "render/Dockerfile", "render/run.sh", "package-lock.json"]
SELFTEST_MARK = ROOT / "output" / ".selftest.json"  # the input hash of the last pass


def selftest_inputs_hash() -> str:
    """Fingerprint of the self-test inputs: file names and contents, and the id of the render image"""
    h = hashlib.sha256()
    tag = hashlib.md5((ROOT / "render" / "Dockerfile").read_bytes()).hexdigest()[:12]  # the same image naming rule as run.sh
    try:
        img = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", f"offerowl-render:{tag}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        image_id = img.stdout.strip()
    except FileNotFoundError:  # no Docker on this machine: the image cannot be part of the fingerprint
        image_id = ""
    h.update(image_id.encode())  # an image rebuilt from the same Dockerfile differs too
    if renderer() == "html":  # the browser renderer: another renderer, and a browser update can move lines
        B = html_renderer().browser  # the browser in use
        b = B.find()
        h.update(("html\0" + (b["path"] + "\0" + B.version(b["path"]) if b else "")).encode())
    for rel_path in SELFTEST_INPUTS:
        p = ROOT / rel_path
        files = sorted(x for x in p.rglob("*") if x.is_file() and "__pycache__" not in x.parts) if p.is_dir() else ([p] if p.exists() else [])
        for f in files:
            h.update(str(f.relative_to(ROOT)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def pdf_text(pdf) -> str:
    """A PDF's text: where the typesetting ran, since a host that uses the container may have no PDF reader of its own."""
    if local():  # the html renderer, or inside the container
        import pdftools  # with poppler or PDFium
        return pdftools.text(pdf)
    return sh(["pdftotext", rel(str(pdf)), "-"]).stdout  # the container's own poppler


def selftest() -> int:
    """The example end to end: the resume has the right page count, names and highlighted phrases in its text layer;
    the deck has the right slide count and text; the check passes the example and catches a planted defect; OCR reads a scan"""
    pdf = build(str(EXAMPLE))
    text = pdf_text(pdf)  # the text layer
    pages = text.count("\f")  # one form feed per page
    miss = [w for w in WANT if w not in text]
    figs = [ROOT / "output" / "_figures" / f"sample_ko_{k}.png" for k in ("timeline", "stack")]
    miss += [f.name for f in figs if not f.exists()]  # the figures the typesetter should have drawn
    if miss or pages != RESUME_PAGES:
        print(t("selftest_resume_fail", pages=pages, want=RESUME_PAGES, missing=miss))
        return 1
    # The deck: cover, overview, three figure slides, end slide. The three figure kinds (before and after, flow, hierarchy)
    # must have their words in the text layer.
    deck = build_deck(str(EXAMPLE))
    dt = pdf_text(deck)  # the deck's text layer
    dmiss, dpages = [w for w in DECK_WANT if w not in dt], dt.count("\f")
    if dmiss or dpages != DECK_SLIDES:
        print(t("selftest_deck_fail", pages=dpages, want=DECK_SLIDES, missing=dmiss))
        return 1
    # The document check passes the example ...
    if check(str(EXAMPLE), None, pdf, deck) != 0:
        print(t("selftest_check_fail"))
        return 1
    # ... and catches a planted defect: a project that exists in the profile but not in the resume.
    planted = ROOT / "output" / "_selftest_planted.json"  # next to the outputs, where the container can read it
    prof = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    prof["roles"][0]["projects"].append({"id": "x", "title": "이력서에 없는 과제", "summary": ""})
    planted.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
    caught = sh(["python3", "src/check_documents.py", rel(str(planted)), rel(str(pdf)), "--style", "default"],
                env=dict(os.environ, OFFEROWL_LANG="ko"))  # Korean pinned: the marker below is the Korean message
    planted.unlink()
    # Read the reason as well as the exit code, so that a different failure (say, a missing style pack) cannot pass for the catch.
    if caught.returncode == 0 or PLANTED_MARKER not in caught.stdout or NO_STYLE_MARKER in caught.stdout:
        print(t("selftest_planted_fail") + "\n" + caught.stdout)
        return 1
    # OCR of a scanned PDF (tesseract). It takes seven seconds, so it runs here and not in every regression run.
    r = sh(["python3", "src/ocr_selfcheck.py", rel(str(pdf))])  # needs no regression-test files, so it runs wherever the repository does
    if r.returncode != 0:
        print(t("selftest_ocr_fail") + "\n" + (r.stdout + r.stderr)[-800:])
        return 1
    print(t("selftest_pass", pages=RESUME_PAGES, slides=DECK_SLIDES, words=len(WANT) + len(DECK_WANT)))
    return 0


# ---------------------------------------------------------------- commands

def split_args(args: list[str]) -> tuple:
    """(positional arguments, --flags) of an argument list"""
    return [a for a in args if not a.startswith("--")], [a for a in args if a.startswith("--")]


def cmd_init(args: list[str]) -> int:
    """init <folder> [--force] [--dry-run]: start a workspace from the example. Existing files are kept without --force"""
    pos, flags = split_args(args)
    if len(pos) != 1 or set(flags) - {"--force", "--dry-run"}:  # exactly one folder, only the known flags
        print(t("usage_init"), file=sys.stderr)
        return 2
    d = pathlib.Path(pos[0])
    targets = [d / "profile.json", d / "job.json"]
    existing = [x.name for x in targets if x.exists()]
    if existing and "--force" not in flags:  # never overwrite somebody's edited profile by default
        print(t("init_exists", folder=d, files=", ".join(existing)), file=sys.stderr)
        return 1
    if "--dry-run" in flags:  # say what would happen and touch nothing, not even the folder
        print(t("init_dry", folder=d))
        return 0
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(EXAMPLE, targets[0])  # the example profile is the starting point of the edit
    targets[1].write_text(json.dumps({"out": "my_resume", "lang": "ko", "theme": "navy", "skillsFocus": None},
                                     ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(t("init_done", folder=d))
    return 0


def cmd_ingest(args: list[str]) -> int:
    """ingest <folder or file>...: fact candidates from raw material. The script reads the AI backend settings itself"""
    if "--help" in args or "-h" in args:  # the script prints its own usage when it gets no arguments
        subprocess.run([sys.executable, str(ROOT / "src" / "ingest.py")])
        return 0
    return subprocess.run([sys.executable, str(ROOT / "src" / "ingest.py")] + args).returncode


def cmd_draft(args: list[str]) -> int:
    """draft write|jd|translate|figures <profile.json> [...]: AI proposals as new files. The input profile is never overwritten"""
    if "--help" in args or "-h" in args:  # the script prints its own usage when it gets no arguments
        subprocess.run([sys.executable, str(ROOT / "src" / "draft.py")])
        return 0
    return subprocess.run([sys.executable, str(ROOT / "src" / "draft.py")] + args).returncode


def cmd_build(args: list[str]) -> int:
    """build <profile.json> [job.json]: resume and deck, then the document check"""
    pos, flags = split_args(args)
    if len(pos) not in (1, 2) or flags:
        print(t("usage_build"), file=sys.stderr)
        return 2
    for p in pos:  # a clear message here beats a traceback from deep inside the build
        if not pathlib.Path(p).is_file():
            print(t("file_missing", path=p), file=sys.stderr)
            return 2
    if docker_missing():
        print(t("need_docker"), file=sys.stderr)
        return 2
    cfg = pos[1] if len(pos) == 2 else None
    import blind  # src/blind.py: a blind edition leaves out what no bar can cover
    pdf = build(pos[0], cfg)  # the resume
    left = blind_leaves_deck(pos[0], cfg)  # a blind edition never carries the person's own portfolio
    deck = None if left else build_deck(pos[0], cfg)  # the deck, unless it is left out
    print(pdf)
    print(deck if deck else t("blind_deck_left"))  # its path, or why there is none
    if not blind.on():  # a blind edition has no plain words: a Word or text file cannot carry the bars
        for f in build_plain(pos[0], cfg):  # the same words for a job site that reads a file by itself
            print(f)
    return check(pos[0], cfg, pdf, deck)  # check right after building


def cmd_selftest(args: list[str]) -> int:
    """selftest [--if-changed]: the example end to end. Writes a stamp on success so that --if-changed can skip a repeat"""
    pos, flags = split_args(args)
    if pos or set(flags) - {"--if-changed"}:
        print(t("usage_selftest"), file=sys.stderr)
        return 2
    if docker_missing():
        print(t("need_docker"), file=sys.stderr)
        return 2
    key = selftest_inputs_hash()
    if "--if-changed" in flags and SELFTEST_MARK.exists() and json.loads(SELFTEST_MARK.read_text(encoding="utf-8")).get("inputs") == key:
        print(t("selftest_skip"))
        return 0
    rc = selftest()
    if rc == 0:  # a pass only: after a failure the next run must run again
        SELFTEST_MARK.parent.mkdir(parents=True, exist_ok=True)
        SELFTEST_MARK.write_text(json.dumps({"inputs": key}) + "\n", encoding="utf-8")
    return rc


def cmd_llm(args: list[str]) -> int:
    """llm [--list | --probe <backend>]: the AI backends"""
    return llm.main(args)


# command name to function. The launcher (./offerowl) builds its help from this table and adds its own entries.
COMMANDS = {"init": cmd_init, "ingest": cmd_ingest, "draft": cmd_draft, "build": cmd_build, "selftest": cmd_selftest, "llm": cmd_llm}
USAGE_KEYS = {"init": "usage_init", "build": "usage_build", "selftest": "usage_selftest"}  # commands with their own usage text; llm has llm.t("usage")


def usage(prog: str = "python3 src/resume.py") -> str:
    """The command list in plain words"""
    lines = [t("usage_head", prog=prog), "", t("commands")]
    lines += [f"  {name:10} {t('cmd_' + name)}" for name in COMMANDS]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)  # the launcher passes its own list
    if not a or a[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    name, rest = a[0], a[1:]
    if name not in COMMANDS:
        print(t("unknown_command", name=name, prog="python3 src/resume.py"), file=sys.stderr)
        return 2
    if ("--help" in rest or "-h" in rest) and name in USAGE_KEYS:  # per-command help, in the user's language
        print(t(USAGE_KEYS[name]))
        return 0
    return COMMANDS[name](rest)


if __name__ == "__main__":
    sys.exit(main())
