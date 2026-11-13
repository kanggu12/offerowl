"""The talk's speaker script as a page (A4, printable): every slide with its picture, its time and the running total, what
to say, where to point, the one line to say when time runs short and the questions to expect, then every question with its
answer notes. src/interview/talk.py writes it next to the deck; the kit's server shows it at /talk/script.
"""
from __future__ import annotations

import base64  # the slides' pictures, inside the page
import html as H  # escaping
import pathlib  # paths
import re  # the speech marks

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the engine's folder: its fonts
WORDS = {
    "ko": {"title": "{who} 발표 대본", "sub": "{when}{n}장, 대본 기준 약 {m}분(목표 {t}분).", "part": "부", "pages": "쪽", "time": "시간", "run": "누적",
           "point": "화면", "short": "줄일 때", "ask": "질문 대비", "qa": "예상 질문과 답의 근거", "late": "시간이 밀릴 때",
           "late_tip": "'줄일 때' 줄이 있는 장은 그 한 문장만 말합니다. 가장 어려웠던 문제의 장들은 줄이지 않습니다.",
           "speak": "말할 때", "speak_tip": "장을 읽지 말고 흐름만 기억합니다. 숫자와 이름은 장과 근거에 있는 것만 말합니다.",
           "draft": "초안", "draft_tip": "이 장의 말은 슬라이드의 글로 만든 초안입니다. 자기 말로 바꿔 쓰세요.",
           "pace": "말 속도가 시간과 맞지 않는 장: {pages}", "layout": "장 배치 결함: {n}건", "start": "시작", "end": "마무리", "page": "{n}쪽",
           "range": "{a}~{b}쪽", "deck_pdf": "발표 자료 PDF", "script_pdf": "대본 PDF", "none": "아직 만든 발표가 없습니다. 패널의 면접 탭에서 발표 자료를 만드세요."},
    "en": {"title": "{who}, talk script", "sub": "{when}{n} slides, about {m} minutes as scripted (target {t}).", "part": "Part", "pages": "Slides", "time": "Time",
           "run": "Total", "point": "Point at", "short": "If late", "ask": "Expect", "qa": "Questions to expect, with what backs the answer", "late": "When time runs short",
           "late_tip": "On a slide with an 'If late' line, say that one line. The slides of the hardest problem are never cut.",
           "speak": "When you speak", "speak_tip": "Do not read the slide; keep the flow in mind. Say only the numbers and names the slides and the evidence hold.",
           "draft": "Draft", "draft_tip": "These words come from the slide itself. Say them in your own words.",
           "pace": "Slides whose words do not fit their time: {pages}", "layout": "Layout defects: {n}", "start": "Opening", "end": "Close", "page": "p.{n}",
           "range": "pp.{a}-{b}", "deck_pdf": "Slides (PDF)", "script_pdf": "Script (PDF)", "none": "No talk yet. Make one on the panel's Interview tab."},
}


def clock(sec: int) -> str:
    """Seconds as m:ss."""
    sec = int(sec or 0)
    return f"{sec // 60}:{sec % 60:02d}"


def rich(text: str) -> str:
    """A line with its **stress** in bold and its ==key phrase== marked, everything else escaped."""
    s = H.escape(str(text or ""))
    s = re.sub(r"==(.+?)==", r"<mark>\1</mark>", s)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def pictures(folder: pathlib.Path) -> list:
    """The slides' pictures (folder/thumbs), one per slide in its order: slide-10 after slide-9."""
    return sorted((folder / "thumbs").glob("slide*.png"), key=lambda f: int(re.sub(r"\D", "", f.stem) or 0))


def script_data(result: dict, folder: pathlib.Path) -> dict:
    """The talk's script as data: what the printed script holds, for the page below and for the Offerowl panel, which draws it
    with its own parts. Every line is as written (its **stress** and ==key phrase== are drawn by the reader); a slide's
    picture is named by its place among pictures(folder); the words are the talk's own language's."""
    brief = result["brief"]
    lang = brief["lang"]
    W = WORDS[lang]
    accent = str((brief.get("theme") or {}).get("accent") or "")  # the company's accent marks order, else the deck's navy
    accent = accent if re.fullmatch(r"#[0-9a-fA-F]{6}", accent) else "#1B2E4B"  # only a colour: a planted talk.json must not reach the style
    num = lambda v: int(v) if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()) else 0  # noqa: E731  a page or a time, as a number only
    slides = result["slides"]
    pics = pictures(folder)  # one per slide
    total = sum(num(s.get("seconds")) for s in slides)
    when = (brief.get("when") + ", ") if brief.get("when") else ""
    who = " ".join(x for x in (result.get("company"), ) if x) or (slides[0].get("name") if slides else "")
    parts, run = [], 0  # the parts' table
    groups = [(W["start"], [s for s in slides if s["kind"] in ("cover", "agenda")])]
    for i, p in enumerate(result.get("parts") or []):
        groups.append((f"{p['no']} {p['title']}", [s for s in slides if s["part"] == i and s["kind"] not in ("cover", "agenda", "end")]))
    groups.append((W["end"], [s for s in slides if s["kind"] == "end"]))
    for name, mine in groups:
        if not mine:
            continue
        sec = sum(num(s.get("seconds")) for s in mine)
        run += sec
        a, b = num(mine[0].get("page")), num(mine[-1].get("page"))
        parts.append({"name": name, "pages": W["page"].format(n=a) if a == b else W["range"].format(a=a, b=b), "time": clock(sec), "run": clock(run)})
    out, run, qa = [], 0, []
    for i, s in enumerate(slides):
        run += num(s.get("seconds"))
        sc = s.get("script") or {}
        out.append({"page": num(s.get("page")), "title": str(s.get("title") or s.get("name") or ""),  # a divider is named by its part
                    "time": clock(num(s.get("seconds"))), "run": clock(run), "picture": i < len(pics),  # its time, the running total, whether it has a picture
                    "cue": str(sc.get("cue") or ""), "lines": [str(x or "") for x in sc.get("lines") or []], "short": str(sc.get("short") or ""),  # where to point, what to say, the line when late
                    "ask": [str(q["q"] or "") for q in sc.get("questions") or []], "draft": bool(sc.get("rule"))})  # empty values print nothing, as rich() prints them  # the questions to expect; words made from the slide itself
        qa += [{"q": str(q["q"]), "a": str(q.get("a") or ""), "page": num(s.get("page"))} for q in sc.get("questions") or [] if isinstance(q, dict) and q.get("q")]
    checks = result.get("checks") or {}
    notes = []
    if checks.get("pace"):
        notes.append(W["pace"].format(pages=", ".join(str(num(x.get("page"))) for x in checks["pace"])))
    lay = sum(len(x.get("issues") or []) for x in checks.get("layout") or [])
    if lay:
        notes.append(W["layout"].format(n=lay))
    return {"lang": lang, "accent": accent, "title": W["title"].format(who=who).strip(" ,"),
            "sub": W["sub"].format(when=when, n=len(slides), m=round(total / 60), t=brief["minutes"]), "notes": notes, "parts": parts, "slides": out, "qa": qa,
            "words": {k: W[k] for k in ("part", "pages", "time", "run", "point", "short", "ask", "qa", "late", "late_tip", "speak", "speak_tip", "draft", "draft_tip", "page")}}


def script_html(result: dict, folder: pathlib.Path, served: bool = False, keys: bool = True) -> str:
    """The printable script of a talk (talk.json as make() writes it), with the slides' pictures from folder/thumbs. served: the
    page the kit's server shows (its own font file, and the keys to the two PDFs) rather than the one printed here."""
    d = script_data(result, folder)  # what it holds
    lang, accent, W = d["lang"], d["accent"], WORDS[d["lang"]]
    pics = pictures(folder)  # one per slide
    rows = [f"<tr><td>{H.escape(r['name'])}</td><td>{r['pages']}</td><td>{r['time']}</td><td>{r['run']}</td></tr>" for r in d["parts"]]
    blocks = []
    for i, s in enumerate(d["slides"]):
        img = f'<img src="data:image/png;base64,{base64.b64encode(pics[i].read_bytes()).decode()}" alt="">' if s["picture"] else '<div class="noimg"></div>'
        body = (f'<p class="pt"><i>{W["point"]}</i>{rich(s["cue"])}</p>' if s["cue"] else "") + \
            "".join(f"<p>{rich(x)}</p>" for x in s["lines"]) + \
            (f'<p class="sh"><i>{W["short"]}</i>{rich(s["short"])}</p>' if s["short"] else "") + \
            "".join(f'<p class="ak"><i>{W["ask"]}</i>{rich(q)}</p>' for q in s["ask"]) + \
            (f'<p class="dr"><i>{W["draft"]}</i>{W["draft_tip"]}</p>' if s["draft"] else "")
        blocks.append(f'<section class="b"><div class="l">{img}<div class="tm"><b>{s["time"]}</b><span>{W["run"]} {s["run"]}</span></div></div>'
                      f'<div class="r"><h2><i>{s["page"]}</i>{H.escape(s["title"])}</h2>{body}</div></section>')
    qa = [(q, q["page"]) for q in d["qa"]]
    notes = d["notes"]
    font = lambda w, f: ('@font-face { font-family: "Pretendard"; font-weight: 100 900; src: url("fonts/PretendardVariable.woff2") format("woff2"); }' if served  # noqa: E731
                         else f'@font-face {{ font-family: "Pretendard"; font-weight: {w}; src: url("{(ROOT / "fonts" / f).as_uri()}"); }}')  # the kit's font, or the deck's own files
    qa_html = "".join(f'<div class="q"><b>{rich(q["q"])}<span>{W["page"].format(n=pg)}</span></b><p>{rich(q.get("a", ""))}</p></div>' for q, pg in qa)
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{H.escape(d['title'])}</title><style>
{font(400, 'Pretendard-Regular.ttf')}
{font(700, 'Pretendard-Bold.ttf')}
@page {{ size: A4; margin: 13mm 13mm 14mm 13mm; }}
:root {{ --accent: {accent}; }}
body {{ font-family: "Pretendard", sans-serif; color: #151515; background: #ffffff; margin: 0; font-size: 10.4pt; line-height: 1.62;
  word-break: keep-all; overflow-wrap: break-word; }}
.hd {{ border-bottom: 2px solid #151515; padding-bottom: 6px; margin-bottom: 8px; }}
.hd h1 {{ font-size: 17pt; margin: 0; letter-spacing: -0.3px; }} .hd h1::before {{ content: ""; display: inline-block; width: 18px; height: 3px; background: var(--accent); vertical-align: middle; margin-right: 8px; }}
.hd div {{ font-size: 9.5pt; color: #5a5a5a; margin-top: 2px; }} .hd .warn {{ color: #8a4a12; }}
.top {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 10px; font-size: 9.2pt; }}
table {{ border-collapse: collapse; width: 100%; }} td, th {{ padding: 2px 6px; border-bottom: 1px solid #e1e1e1; text-align: left; }} th {{ color: #5a5a5a; font-weight: 700; }}
.tips {{ background: #f1f1f1; border-radius: 5px; padding: 6px 10px; }} .tips b {{ display: block; margin-bottom: 2px; }} .tips p {{ margin: 0 0 2px 0; }}
.b {{ display: grid; grid-template-columns: 62mm 1fr; gap: 10px; padding: 8px 0; border-top: 1px solid #d4d4d4; break-inside: avoid; }}
.l img, .noimg {{ width: 62mm; aspect-ratio: 16 / 9; border: 1px solid #c6c6c6; border-radius: 3px; display: block; }}
.tm {{ margin-top: 4px; font-size: 8.8pt; color: #5a5a5a; }} .tm b {{ color: #151515; font-size: 10pt; margin-right: 6px; }}
.r h2 {{ font-size: 11.5pt; margin: 0 0 3px 0; }} .r h2 i {{ font-style: normal; color: var(--accent); margin-right: 7px; }}
.r p {{ margin: 0 0 3px 0; }} .r p b {{ font-weight: 700; }} mark {{ background: #fff2a8; padding: 0 2px; }}
.r p.pt, .r p.sh, .r p.ak, .r p.dr {{ font-size: 9.3pt; line-height: 1.5; color: #434343; font-style: italic; }}
.r p.pt i, .r p.sh i, .r p.ak i, .r p.dr i {{ font-style: normal; font-weight: 700; font-size: 8.6pt; margin-right: 6px; padding: 0 5px; border-radius: 3px; background: #f1f1f1; color: #151515; }}
.r p.sh {{ margin-top: 4px; }} .r p.ak i {{ color: #8a4a12; }}
.qa {{ break-before: page; }} .qa h2 {{ font-size: 14pt; margin: 0 0 6px 0; padding-bottom: 4px; border-bottom: 2px solid #151515; }}
.q {{ padding: 6px 0; border-bottom: 1px solid #e1e1e1; break-inside: avoid; }} .q b {{ display: block; font-size: 10.8pt; }} .q b span {{ float: right; font-weight: 400; color: #5a5a5a; font-size: 9pt; }}
.q b::before {{ content: "Q "; color: var(--accent); }} .q p {{ margin: 2px 0 0 0; }}
@media screen {{ body {{ max-width: 920px; margin: 0 auto; padding: 18px 20px 40px; }} .keys {{ display: flex; gap: 8px; justify-content: flex-end; margin-bottom: 10px; }}
  .keys a {{ padding: 6px 12px; border: 1px solid #c6c6c6; border-radius: 4px; color: #151515; text-decoration: none; font-size: 10pt; }} .keys a:hover {{ background: #f1f1f1; }} }}
@media screen and (max-width: 720px) {{ .b {{ grid-template-columns: 1fr; }} .l img, .noimg {{ width: 100%; }} .top {{ grid-template-columns: 1fr; }} }}
@media print {{ .keys {{ display: none; }} }}
</style></head><body>
{f'<nav class="keys"><a href="talk/deck.pdf" target="_blank" rel="noopener">{W["deck_pdf"]}</a><a href="talk/script.pdf" target="_blank" rel="noopener">{W["script_pdf"]}</a></nav>' if served and keys else ''}
<div class="hd"><h1>{H.escape(d['title'])}</h1><div>{H.escape(d['sub'])}</div>
{''.join(f'<div class="warn">{H.escape(n)}</div>' for n in notes)}</div>
<div class="top"><table><tr><th>{W['part']}</th><th>{W['pages']}</th><th>{W['time']}</th><th>{W['run']}</th></tr>{''.join(rows)}</table>
<div class="tips"><b>{W['late']}</b><p>{W['late_tip']}</p><b style="margin-top:4px">{W['speak']}</b><p>{W['speak_tip']}</p></div></div>
{''.join(blocks)}
{f'<section class="qa"><h2>{W["qa"]}</h2>{qa_html}</section>' if qa_html else ''}
</body></html>"""


def print_script(page: pathlib.Path, pdf: pathlib.Path, env: dict | None = None) -> None:
    """Print the script page to PDF with the renderer in use (the PC's browser, or the container's Chromium)."""
    import sys
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    import resume as R  # noqa: E402  the renderer's helpers
    pdf.unlink(missing_ok=True)
    if R.renderer() == "html":  # the PC's own browser
        R.html_renderer().html_to_pdf(page, pdf)
        return
    tmp_page = ROOT / "output" / "_inputs" / (page.stem + "_" + str(abs(hash(str(page))))[:8] + ".html")  # inside the repository for the container
    tmp_page.parent.mkdir(parents=True, exist_ok=True)
    text = page.read_text(encoding="utf-8").replace((ROOT / "fonts").as_uri(), "../../fonts")  # the container sees the repository at /work
    tmp_page.write_text(text, encoding="utf-8")
    out = tmp_page.with_suffix(".pdf")
    r = R.sh(["bash", "-c", R.CHROME + '--user-data-dir=/tmp/chr --no-pdf-header-footer --print-to-pdf="$2" "$1" 2>/dev/null', "_",
              tmp_page.relative_to(ROOT).as_posix(), out.relative_to(ROOT).as_posix()], env)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("the script could not be printed:\n" + r.stdout[-800:] + r.stderr[-800:])
    pdf.write_bytes(out.read_bytes())
    tmp_page.unlink(missing_ok=True)
    out.unlink(missing_ok=True)


def served(folder: pathlib.Path, lang: str = "ko", keys: bool = True) -> str:
    """The page the kit's server shows at /talk: the script with the keys to the two PDFs, or a line saying there is none yet."""
    import json
    f = folder / "talk.json"
    try:
        result = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # not made yet, or being written
        W = WORDS["en" if lang == "en" else "ko"]
        return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{H.escape(W["title"].format(who="").strip(" ,"))}</title>'
                f'<style>body {{ font-family: sans-serif; margin: 0; padding: 40px; color: #151515; background: #ffffff; word-break: keep-all; }}</style>'
                f'</head><body><p>{H.escape(W["none"])}</p></body></html>')  # a sheet of its own: dark text never stands on the panel's dark desk
    return script_html(result, folder, served=True, keys=keys)
