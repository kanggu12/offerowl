"""Search hit rate on a job's eval set, measured in the real page.

The eval set (eval_questions.json in the interview folder) lists questions the way an interviewer would ask them,
each with the ids that answer it: {"questions": [["Tell me about yourself", ["A1"]], ...]}. Each question is typed
into the page; a hit at rank one means the first card on the board is one of the ids, a hit in the top three means
one of the first three cards is. The ranking and the board layout both run in the page, so the page is the measure.
The verdict is the last line: "top-1 a/n, top-3 b/n".
"""
import asyncio  # Playwright's async API
import json  # the eval set and the results

from interview import browser, i18n  # the page under test; messages
from interview.job import read_json  # optional files

WAIT_MS = 1200  # after typing: the keyword draw comes after 80 ms, layout and a similarity answer within this


def questions(job, path=None):  # also used by the cards check for its sample searches
    """[(question, [ids])] from the job's eval set, or from another file of the same form (`eval --questions`)."""
    data = read_json(path or job.eval_path(), {}) or {}  # missing file: no questions
    return [(q, list(want)) for q, want in data.get("questions", [])]  # pairs of question and expected ids, the ids as a list


async def run(url, qs, size):  # the browser part of main
    """Type each question; return [(question, want, first three ids)]."""
    async_playwright = browser.playwright_or_none()  # optional dependency
    w, h = browser.parse_size(size)  # the board's layout depends on the window
    out = []  # one row per question
    async with async_playwright() as p:  # starts and stops Playwright's driver
        b = await p.chromium.launch()  # headless
        pg = await b.new_page(viewport={"width": w, "height": h})  # one page at the eval size, reused for every question
        await pg.goto(url, wait_until="networkidle")  # page, fonts and data
        for q, want in qs:  # every question in order
            await pg.fill("#q", q)  # one input event, like pasting the question
            await pg.wait_for_timeout(WAIT_MS)  # the draw (and a similarity answer, if the model is on)
            # the first three cards on the board, in board order
            ids = await pg.evaluate("() => [...document.querySelectorAll('article.card')].map(e => e.dataset.id).slice(0, 3)")
            out.append((q, want, ids))  # keep what was wanted beside what came
        await b.close()  # close the browser before the driver stops
    return out


def main(job, url=None, port=0, size="1920x1080", out=None, questions_file=None):  # the eval command's work
    """Print one line per question and the verdict; write eval.json to the output folder. Exit 1 below full marks.
    questions_file measures another set of the same form instead of the job's own, such as questions in other words."""
    qs = questions(job, questions_file)  # the eval set
    if not qs:  # nothing to measure
        print(i18n.t("eval_none", path=questions_file or job.eval_path()))  # say which file was expected
        return 2  # 2 means nothing to run, unlike 1 for misses
    if browser.playwright_or_none() is None:  # optional dependency missing
        print(i18n.t("need_playwright"))  # say how to install it
        return 2  # 2 means could not run
    with browser.served(job, url, port) as u:  # the page under test
        rows = asyncio.run(run(u, qs, size))  # type every question while the page is served
    top1 = top3 = 0  # hit counts
    for q, want, ids in rows:  # score each question
        hit1, hit3 = bool(ids) and ids[0] in want, any(i in want for i in ids)  # rank one, top three
        top1 += hit1  # a bool adds as 0 or 1
        top3 += hit3  # top-three hits, counted the same way
        print(i18n.t("eval_line", mark="O" if hit1 else ("~" if hit3 else "X"), q=q, want=want, got=ids))  # O first card right, ~ in the top three, X missed
    res = job.out_dir(out) / "eval.json"  # the record, next to the other outputs
    res.write_text(json.dumps({"size": size, "top1": top1, "top3": top3, "n": len(rows),  # the counts and every row, so runs can be compared
                               # every row as wanted and got; Korean stays readable in the file
                               "rows": [{"q": q, "want": w, "got": g} for q, w, g in rows]}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(i18n.t("eval_summary", top1=top1, top3=top3, n=len(rows)))  # the verdict line
    return 0 if top1 == top3 == len(rows) else 1  # 0 only at full marks, so scripts can gate on it
