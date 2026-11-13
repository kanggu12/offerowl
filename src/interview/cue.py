"""Printable cue cards: one scene per card, the English lines with the key phrase highlighted, the translation small.

The search view serves them at /cue (?ids=A1,B2 or ?sec=A,B; ?roles=scenes,deep); the browser's print dialog makes the
paper copy. `cue` writes the same page to a file, and `cue --pdf` prints it to PDF with Playwright's Chromium.

    python3 src/interview/cli.py cue --job <dir> [--ids A1,A2] [--sec A,B] [--pdf]

A card holds the scene's title, then each exchange: the interviewer's line in small grey type, my line at full size
(' // ' starts a new line, ' / ' shows as a faint breath mark, **stress** in bold, the ==key phrase== on the yellow
highlighter, Korean stage notes in grey italics) and its 해석 under it in small type. Cards are cut along their
dashed edges; a card never splits between columns or pages unless it is longer than a page.
"""
import html  # escaping
import json  # the record
import re  # marks

from interview import check, corpus, i18n  # scenes; items; strings

# The print key, wired by a script of its own: a page under a script policy (src/interview/server.py page_policy) runs no
# handler written into an attribute, and the cards and the deck carry no other script.
PRINT_KEY = '<button type="button" id="print">{label}</button>'
PRINT_SCRIPT = '<script>document.getElementById("print").addEventListener("click", function () { print(); });</script>'

MAX_CARDS = 400  # the most cards one page holds (a whole kit prints in parts)


def _unref(kit):  # the kit's cross-reference patterns are JavaScript syntax, which Python reads the same way here
    """A function that removes the writer's cross-references, as the search view does."""
    pats = []  # the patterns that compile in Python
    for p in kit.get("strip") or []:  # each pattern of the kit
        try:
            pats.append(re.compile(p))  # most JavaScript patterns are valid Python patterns
        except re.error:  # one that is not is skipped, not fatal
            continue

    def unref(s):  # applied to every title and line
        t = s or ""  # None reads as empty
        for q in pats:  # every pattern in turn
            t = q.sub("", t)  # the cross-reference removed
        return t
    return unref


def line_html(text):
    """One spoken line as HTML: breaths, sentence ends, stress, the key phrase and stage notes."""
    h = html.escape(text or "", quote=False)  # escaped first; the marks below are plain characters
    h = re.sub(r"==(.+?)==", r'<mark class="hl">\1</mark>', h)  # the key phrase on the highlighter
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)  # stressed words in bold
    h = re.sub(r"`([^`]+)`", r"<code>\1</code>", h)  # commands and file names
    h = re.sub(r"\(([^()<>]*[가-힣][^()<>]*)\)", r'<span class="dir">(\1)</span>', h)  # Korean stage notes are not spoken
    h = re.sub(r"\s+//\s+", "<br>", h)  # a sentence ends: a new line
    h = re.sub(r"\s+//\s*$", "", h)  # a mark at the very end
    return re.sub(r"\s/\s", ' <span class="br">/</span> ', h)  # a breath: a faint slash


def scene_cards(job, ids=None, sections=None, roles=("scenes",)):
    """[(item, [(speaker, english, translation)])] of the chosen scenes, in file order."""
    want = {i.strip() for i in ids.split(",") if i.strip()} if ids else None  # named ids
    secs = {s.strip().upper() for s in sections.split(",") if s.strip()} if sections else None  # section letters
    _, scenes = check.load_scenes(job, drafts=want is not None)  # every scene with its dialogue; a practice session's own scripts by id, drafts among them
    out = []  # cards
    for it, dialogue, _ in scenes:  # file order
        if want is not None:  # named ids win over the other filters
            if it["id"] not in want:  # not one of them
                continue
        elif it.get("role") not in roles or (secs and it["id"][:1] not in secs):  # the role and section filters
            continue
        pairs = []  # (speaker, english, translation)
        for who, txt, _ in dialogue:  # in file order
            if who == "해석" and pairs and not pairs[-1][2]:  # the translation of the line above
                pairs[-1] = (pairs[-1][0], pairs[-1][1], txt)  # attached to it
            elif who in ("면접관", "나"):  # an English line
                pairs.append((who, txt, ""))  # its translation follows
        if pairs:  # a scene with lines
            out.append((it, pairs))
        if len(out) >= MAX_CARDS:  # one printable page at most
            break
    return out


CSS = """
@font-face { font-family: "Pretendard Variable"; src: url("fonts/PretendardVariable.woff2") format("woff2-variations"); font-weight: 45 920; }
:root { --ink: #1d1c1d; --ink-2: #3f3e3f; --off: #767676; --rule: #bbbabb; --hl: rgba(240, 186, 20, .9); --red: #e8453f; --chip: #0366ab; }
* { box-sizing: border-box; }
html { background: #f2f2f3; }
body { margin: 0; padding: 18px; color: var(--ink); font: 400 10.5pt/1.5 "Pretendard Variable", Pretendard, "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
  word-break: keep-all; overflow-wrap: break-word; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.bar { display: flex; align-items: center; gap: 12px; max-width: 210mm; margin: 0 auto 14px; font-size: 10pt; color: var(--ink-2); }
.bar h1 { margin: 0; font-size: 13pt; font-weight: 750; }
.bar .n { color: var(--off); }
.bar button { margin-left: auto; height: 32px; padding: 0 14px; border: 1px solid rgba(0, 0, 0, .14); border-radius: 5px; cursor: pointer;
  background: linear-gradient(#fff, rgba(255, 255, 255, .6)); box-shadow: 1px 2px 3px rgba(0, 0, 0, .18), inset 0 1px 0 #fff; font: inherit; font-weight: 650; }
.sheet { max-width: 210mm; margin: 0 auto; column-count: 2; column-gap: 6mm; }
.cue { break-inside: avoid; margin: 0 0 6mm; padding: 4mm 4.5mm 3.5mm; background: #fff; border: 1px dashed var(--rule); border-radius: 2px; }
.cue h2 { display: flex; gap: 6px; align-items: baseline; margin: 0 0 1.5mm; padding-bottom: 1.5mm; border-bottom: 1.5px solid var(--rule); font-size: 10.5pt; line-height: 1.35; font-weight: 720; }
.cue h2 .id { flex: none; padding: 0 5px; border-radius: 2px; font-size: 9pt; color: var(--chip); background: rgba(3, 102, 171, .12); }
.cue h2 .ko { display: block; font-size: 8pt; font-weight: 500; color: var(--off); }
.cue .q { margin: 2mm 0 .6mm; font-size: 8.5pt; line-height: 1.4; color: var(--off); }
.cue .q::before { content: attr(data-who) " "; font-weight: 700; }
.cue .a { margin: 0; font-size: 10.5pt; line-height: 1.5; font-weight: 500; }
.cue .tr { margin: .6mm 0 0; font-size: 7.5pt; line-height: 1.45; color: var(--off); }
.cue b { font-weight: 750; }
.cue mark.hl { color: inherit; padding: 0 .1em; background: linear-gradient(180deg, transparent 58%, var(--hl) 58%); font-weight: 750; }
.cue .br { color: var(--off); font-weight: 400; }   /* a breath mark, as the deck and the search view draw it (4.5:1 on the card) */
.cue .dir { color: var(--off); font-style: italic; font-size: .9em; }
.cue code { font: 500 .92em/1 "JetBrains Mono", Consolas, monospace; }
.empty { max-width: 210mm; margin: 40px auto; color: var(--off); }
@page { size: A4; margin: 10mm; }
@media print { html, body { background: #fff; padding: 0; } .bar { display: none; } .sheet { max-width: none; } }
@media (max-width: 720px) { body { padding: 10px; } .sheet { column-count: 1; } }
"""


def page(job, ids=None, sections=None, roles=("scenes",), lang=None):
    """The cue card page as one HTML string."""
    strings = i18n.page(lang)  # the page's language
    labels = strings.get("labels", {})  # speaker names in that language
    unref = _unref(job.kit)  # the writer's cross-references are removed, as on the search view
    cards = scene_cards(job, ids, sections, roles)  # the chosen scenes
    body = []  # card HTML
    for it, pairs in cards:  # one card per scene
        title = html.escape(unref(it.get("ten") or it.get("tko") or it["id"]).replace("**", "").replace("==", ""))  # the English title, or the Korean one
        sub = html.escape(unref(it.get("tko") or "").replace("**", "").replace("==", "")) if it.get("ten") else ""  # the Korean title under it
        rows = []  # the exchanges
        for who, en, ko in pairs:  # each line with its translation
            if who == "면접관":  # the interviewer: small and grey, a cue for what is being asked
                rows.append(f'<p class="q" data-who="{html.escape(labels.get("면접관", "면접관"))}">{line_html(unref(en))}</p>')
            else:  # my line: the main text, with the translation small under it
                rows.append(f'<p class="a">{line_html(unref(en))}</p>' + (f'<p class="tr">{line_html(unref(ko))}</p>' if ko else ""))
        body.append(f'<article class="cue" data-id="{html.escape(it["id"])}"><h2><span class="id">{html.escape(it["id"])}</span>'
                    f'<span>{title}{f"<span class=ko>{sub}</span>" if sub else ""}</span></h2>{"".join(rows)}</article>')
    count = strings["cue_count"].format(n=len(cards))  # how many cards the page holds
    sheet = f'<main class="sheet">{"".join(body)}</main>' if body else f'<p class="empty">{html.escape(strings["cue_empty"])}</p>'  # the cards, or why there are none
    return (f'<!doctype html><html lang="{strings["lang"]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(strings["cue_title"])}</title><style>{CSS}</style></head><body>'
            f'<div class="bar"><h1>{html.escape(strings["cue_title"])}</h1><span class="n">{html.escape(count)}</span>'
            f'{PRINT_KEY.format(label=html.escape(strings["cue_print"]))}</div>{sheet}{PRINT_SCRIPT}</body></html>')


def main(job, ids=None, sections=None, roles="scenes", out=None, pdf=False):
    """Write cue_cards.html (and cue_cards.pdf with --pdf) to the output folder."""
    roles = tuple(r.strip() for r in (roles or "scenes").split(",") if r.strip())  # which kinds of item get cards
    text = page(job, ids, sections, roles)  # the page
    d = job.out_dir(out)  # the output folder
    f = d / "cue_cards.html"  # the file a browser prints
    f.write_text(text, encoding="utf-8")  # written in one go
    n = text.count('<article class="cue"')  # how many cards it holds
    print(i18n.t("cue_written", n=n, out=f))  # where it went
    if pdf:  # print it with the browser engine
        from interview import browser  # Playwright, optional
        pw = browser.playwright_or_none()  # installed?
        if pw is None:  # no browser engine
            print(i18n.t("need_playwright"))  # how to get it
            return 2
        import asyncio  # Playwright's async API

        async def to_pdf():  # one page, printed with the page's own @page rules
            async with pw() as p:  # the driver
                b = await p.chromium.launch()  # headless
                pg = await b.new_page()  # one page
                await pg.goto(f.as_uri(), wait_until="load")  # the written file
                await pg.pdf(path=str(d / "cue_cards.pdf"), prefer_css_page_size=True, print_background=True)  # A4 from @page
                await b.close()  # done
        asyncio.run(to_pdf())  # run it
        print(i18n.t("cue_written", n=n, out=d / "cue_cards.pdf"))  # the PDF too
    (d / "cue_cards.json").write_text(json.dumps({"cards": n, "ids": ids, "sections": sections, "roles": list(roles)}) + "\n", encoding="utf-8")  # what was printed
    return 0
