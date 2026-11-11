"""Card defects in the real page, one card at a time, and the page's fit at several window sizes.

For every item (or the ids given) the item's id is searched, which shows that card first, and the card is measured:
  - overflow: text clipped by the card's box;
  - raw marks: speech marks (**, ==, ' // ') left visible as characters;
  - empty fields, dialogue lines without their name tag;
  - Korean lines without their 해석 note box, an interviewer-only scene;
  - another card shown first.
The verdict line per size is "W H cards N with problems M". With --sizes the contents screen and three searches are
also opened at four window sizes in both themes, counting clipped cards and page scroll (every number should be 0).
"""
import asyncio  # Playwright's async API
import json  # the record

from interview import browser, evalset, i18n  # the page under test, the eval questions, messages

SIZES = ("2560x1300", "1440x900")  # a 4K screen at 150% scaling (3840x2160) and a laptop
FOUR = ((2560, 1300), (1920, 1080), (1440, 900), (1280, 720))  # window sizes for --sizes
WAIT_MS = 120  # an id search draws at once; this covers the layout

# Runs in the page against the first card after searching an id; returns the facts the checks need.
PROBE = """(id) => {
  const c = document.querySelector('#cards .card'); if (!c) return {id, err: 'no card'};
  const out = {id, shown: c.dataset.id};
  out.overflow = c.scrollHeight > c.clientHeight + 1 || c.scrollWidth > c.clientWidth + 1;   // clipped text
  const cl = c.cloneNode(true); cl.querySelectorAll('code, pre').forEach(x => x.remove());    // code may hold == or //
  document.body.appendChild(cl); const txt = cl.innerText; cl.remove();
  out.raw = /\\*\\*|==|\\s\\/\\/\\s|\\/\\/\\s*$/m.test(txt.replace(/https?:\\/\\/\\S+/g, ''));          // speech marks that were not rendered
  out.me = c.querySelectorAll('.fld.en.me').length; out.iv = c.querySelectorAll('.fld.en.iv').length;
  out.tr = c.querySelectorAll('.fld.tr').length; out.note = !!c.querySelector('.ko-note');
  out.empty = [...c.querySelectorAll('.fld p')].filter(p => !p.textContent.replace(/\\s/g, '').length).length;
  out.nolab = [...c.querySelectorAll('.fld.en.me, .fld.en.iv')].filter(f => !f.querySelector('.lab')).length;
  return out; }"""


def problems(r, want):  # shared by every window size
    """The defects one probe found, as (code, slots) pairs; i18n turns them into text."""
    if r.get("err"):  # the page drew no card at all
        return [("no_card", {})]  # nothing else can be measured without a card
    prob = []  # what is wrong with this card
    if r["shown"] != want:  # an id search should put the searched card first
        prob.append(("first_card", {"id": r["shown"]}))  # name the card that came first instead
    if r["overflow"]:  # text runs past the card's box
        prob.append(("overflow", {}))  # clipped text is hidden from the reader
    if r["raw"]:  # markup characters survived rendering
        prob.append(("raw_marks", {}))  # the reader would see the marks as plain characters
    if r["empty"]:  # fields with no visible text
        prob.append(("empty_fields", {"n": r["empty"]}))  # how many, so the fix is easy to find
    if r["nolab"]:  # dialogue lines missing their 면접관 or 나 tag
        prob.append(("no_tag", {"n": r["nolab"]}))  # count the untagged lines
    if r["tr"] and not r["note"]:  # Korean lines need the 해석 note box
        prob.append(("no_note", {}))  # the translation has nowhere to show
    if r["iv"] and not r["me"]:  # only interviewer lines and no answer
        prob.append(("iv_only", {}))  # flag the missing answer
    return prob


async def one_size(b, url, w, h, ids):  # one browser page per window size
    """Every card at one window size (dark theme, the denser one); returns (ids checked, [(id, problems)])."""
    pg = await b.new_page(viewport={"width": w, "height": h}, color_scheme="dark")  # a fresh page at this size; the dark theme is the denser one
    await pg.goto(url, wait_until="networkidle")  # page, fonts and data
    ids = ids or await pg.evaluate("() => ITEMS.map(it => it.id)")  # every item the page knows
    bad = []  # cards with defects
    for i in ids:  # one id search per card
        await pg.fill("#q", i)  # an id search shows that card first
        await pg.keyboard.press("Enter")  # draw now
        await pg.wait_for_timeout(WAIT_MS)  # let the layout settle before measuring
        prob = problems(await pg.evaluate(PROBE, i), i)  # measure the first card in the page, judge it here
        if prob:  # only cards with defects are listed
            bad.append((i, prob))  # keep the id with its defects
    await pg.close()  # free the page before returning
    return ids, bad  # the ids also tell how many cards were checked


async def size_checks(b, url, queries):  # the --sizes pass
    """The contents screen and three searches at four sizes and both themes; returns rows and the problem count."""
    rows, bad = [], 0  # one row per size and theme
    for w, h in FOUR:  # each window size
        for theme in ("dark", "light"):  # both themes, each measured rather than assumed alike
            pg = await b.new_page(viewport={"width": w, "height": h}, color_scheme=theme)  # a fresh page at this size and theme
            await pg.goto(url, wait_until="networkidle")  # wait for page, fonts and data, as above
            await pg.evaluate(f"() => {{ document.documentElement.dataset.theme = '{theme}'; }}")  # force the theme the page would pick
            await pg.wait_for_timeout(400)  # let the restyle and the layout finish
            # the contents screen: does the card area scroll, and does the page itself scroll
            toc = await pg.evaluate("() => { const c = document.querySelector('#cards'); return {scroll: c.scrollHeight > c.clientHeight + 1, doc: document.documentElement.scrollHeight - innerHeight}; }")
            res = []  # (clipped cards, page overflow in px) per query
            for q in queries:  # each sample search
                await pg.fill("#q", q)  # type the search
                await pg.keyboard.press("Enter")  # draw at once instead of after the typing delay
                await pg.wait_for_timeout(700)  # longer than an id search: more cards to lay out
                # cards whose text is clipped by their box
                over = await pg.evaluate("() => [...document.querySelectorAll('#cards .card')].filter(c => c.scrollHeight > c.clientHeight + 1 || c.scrollWidth > c.clientWidth + 1).length")
                doc = await pg.evaluate("() => document.documentElement.scrollHeight - innerHeight")  # how far the page scrolls past the window; should be 0
                res.append((over, doc))  # keep both numbers for this search
            bad += int(toc["scroll"]) + int(toc["doc"] > 0) + sum(1 for o, d in res if o or d > 0)  # every number should be 0
            rows.append((w, h, theme, toc["scroll"], toc["doc"], res))  # one row for the record
            # progress as each size and theme finishes, since the pass is slow
            print(i18n.t("sizes_line", w=w, h=h, theme=theme, toc=toc["scroll"], doc=toc["doc"], res=res), flush=True)
            await pg.close()  # free the page before the next one
    return rows, bad


async def run(url, sizes, ids, with_sizes, queries):  # the browser part of main
    """All sizes at once in one browser (one page each)."""
    async_playwright = browser.playwright_or_none()  # optional dependency
    async with async_playwright() as p:  # starts and stops Playwright's driver
        b = await p.chromium.launch()  # headless
        results = await asyncio.gather(*(one_size(b, url, w, h, ids) for w, h in sizes))  # sizes in parallel
        extra = await size_checks(b, url, queries) if with_sizes else None  # the slower size pass only when asked
        await b.close()  # close the browser before the driver stops
    return results, extra


def main(job, sizes=None, ids=None, url=None, port=0, with_sizes=False, out=None):  # the cards command's work
    """Print the verdict line per size (and the size checks); write cards.json. Exit 1 when any card has a problem."""
    if browser.playwright_or_none() is None:  # optional dependency missing
        print(i18n.t("need_playwright"))  # say how to install it
        return 2  # 2 means could not run, unlike 1 for defects found
    dims = [browser.parse_size(s) for s in (sizes or SIZES)]  # window sizes to check
    only = [x.strip() for x in ids.split(",") if x.strip()] if ids else None  # a subset: the cards that changed
    qs = [q for q, _ in evalset.questions(job)]  # three searches for the size checks: from the eval set
    queries = job.kit.get("size_queries") or (qs[:1] + qs[len(qs) // 2:len(qs) // 2 + 1] + qs[-1:] if qs else ["A1"])  # first, middle, last
    with browser.served(job, url, port) as u:  # the page under test
        results, extra = asyncio.run(run(u, dims, only, with_sizes, queries))  # run the async checks while the page is served
    total = 0  # cards with problems over all sizes
    record = {"sizes": [], "size_checks": None}  # what goes into cards.json
    for (w, h), (checked, bad) in zip(dims, results):  # each size with its results, in the order asked
        total += len(bad)  # count defects over all sizes
        # the record keeps defect codes only; the words come from i18n when printed
        record["sizes"].append({"w": w, "h": h, "cards": len(checked), "bad": [{"id": i, "problems": [c for c, _ in p]} for i, p in bad]})
        for i, p in bad[:40]:  # the first ones, enough to start fixing
            print("  ", i, "; ".join(i18n.reason(c, **s) for c, s in p))  # the id and its defects in words
        print(i18n.t("cards_summary", w=w, h=h, cards=len(checked), bad=len(bad)), flush=True)  # the verdict line, after its details
    if extra is not None:  # only after --sizes
        rows, nbad = extra  # unpack the size pass
        record["size_checks"] = {"rows": rows, "problems": nbad}  # keep it in the record
        print(i18n.t("sizes_summary", bad=nbad))  # the size pass verdict
        total += nbad  # its problems also fail the run
    # save the record beside the other outputs, for comparing runs
    (job.out_dir(out) / "cards.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if total == 0 else 1  # 0 only when nothing is wrong at any size
