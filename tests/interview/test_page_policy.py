"""The kit's pages run only the scripts they were built with. The panel serves them on its own address (/kit/<job>/), where a
script could call every route of the panel, and they draw scenes the agent writes from postings: a script or a handler that
a mistake of escaping let in must not run. Each page names its own scripts by hash (src/interview/server.py page_policy); the
page data has no "<" at all, so a scene cannot end or bend its block ("<!--<script"); the print keys carry no handler in an
attribute. In a headless Chromium where Playwright is installed, the pages also work under their policy and refuse what is
put into them.

    python3 -m unittest tests/interview/test_page_policy.py -v
"""
import base64  # a script's hash
import hashlib  # that hash
import json  # the page's data
import os  # the language of the page
import pathlib  # paths
import re  # the page's scripts
import shutil  # temporary folders, removed
import sys  # the import path
import tempfile  # the vector cache
import threading  # the server beside the test
import unittest
import unittest.mock  # the page's language, for the test
import urllib.request  # the pages with their headers

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # helpers.py
import helpers  # noqa: E402  the import path and the example workspace
from interview import i18n, server  # noqa: E402  the kit's server and its strings
from interview.job import Job  # noqa: E402

try:  # the browser driver, when it is installed
    from playwright.sync_api import sync_playwright
except ImportError:  # no Playwright here: the checks without a browser still run
    sync_playwright = None


def start(case, job):
    """The kit's server for a job on a free port, stopped after the test. Returns its base URL."""
    case.addCleanup(i18n.use)  # the language follows the environment again afterwards
    with unittest.mock.patch.dict(os.environ, {"OFFEROWL_LANG": "ko"}):  # the example's language
        i18n.use("ko")
    cache = tempfile.mkdtemp(prefix="offerowl-iv-vectors-")  # never in the repository
    case.addCleanup(shutil.rmtree, cache, True)
    srv, _ = server.make_server(job, port=0, cache_dir=cache)  # keyword search only
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    case.addCleanup(srv.server_close)
    case.addCleanup(srv.shutdown)
    return f"http://127.0.0.1:{srv.server_address[1]}"


def bend(job_dir, words):
    """One more scene at the end of the example's scene file, its key line holding these words."""
    qa = job_dir / "interview" / "qa.md"  # a file the kit names among its sources
    qa.write_text(qa.read_text(encoding="utf-8") + f"\n## Z. Bent\n\n### Z1. Bent / Bent\n\n**핵심** {words}\n\n**면접관** Q?\n**나** A.\n", encoding="utf-8")


def get(url):
    """(headers, body) of a page."""
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.headers, r.read().decode("utf-8")


class PolicyTest(unittest.TestCase):
    """What the server sends, with no browser."""

    def test_each_page_names_its_own_scripts_and_no_other(self):
        base = start(self, helpers.example_job())
        for path in ("/", "/cue", "/deck"):
            headers, body = get(base + path)
            policy = headers.get("Content-Security-Policy") or ""
            src = next(p for p in policy.split(";") if p.strip().startswith("script-src"))
            self.assertNotIn("unsafe-inline", src, path)  # no script that is not named runs
            scripts = re.findall(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script\b[^>]*>", body, re.S | re.I)  # the page's own
            self.assertTrue(scripts, path)
            for s in scripts:  # each one named by its hash, as the browser computes it
                digest = base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()
                self.assertIn(f"'sha256-{digest}'", src, path)
            self.assertIsNone(re.search(r"\son[a-z]+\s*=", body.split("<script", 1)[0]), path)  # no handler in an attribute
            self.assertEqual("nosniff", headers.get("X-Content-Type-Options"), path)
        self.assertNotIn("Python", headers.get("Server") or "")  # the server says no build of Python

    def test_a_scene_cannot_bend_the_data_block(self):
        tmp, job_dir = helpers.copy_workspace()
        self.addCleanup(shutil.rmtree, tmp, True)
        bend(job_dir, "<!--<script> and </script> in a line")  # a scene with what a parser would take as markup
        base = start(self, Job(job_dir))
        _, body = get(base + "/")
        block = body.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]  # the data, whole
        self.assertNotIn("<", block)  # nothing in it can end or bend the block
        data = json.loads(block)  # and it reads back
        self.assertIn("<!--<script>", json.dumps(data, ensure_ascii=False))  # the scene's words, as written


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class BrowserTest(unittest.TestCase):
    """The pages in a headless Chromium, under the policy they are sent with."""

    def test_the_pages_work_and_refuse_what_is_put_into_them(self):
        tmp, job_dir = helpers.copy_workspace()
        self.addCleanup(shutil.rmtree, tmp, True)
        bend(job_dir, "<!--<script> 멱등")
        base = start(self, Job(job_dir))
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()  # headless: no window on the screen
            except Exception as exc:  # noqa: BLE001  Playwright without its Chromium
                self.skipTest(f"no Chromium for Playwright: {exc}")
            try:
                self.check_pages(browser, base)
            finally:
                browser.close()  # before Playwright itself stops

    def check_pages(self, browser, base):  # the checks, in the order a person would use the pages
        page = browser.new_page()
        errors = []  # a policy refusal is a console error
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/")
        page.wait_for_function("typeof DATA === 'object' && DATA !== null && document.querySelectorAll('#cards > *').length > 0", timeout=20000)
        page.fill("#q", "멱등")  # a search, as a person types it
        page.wait_for_timeout(600)
        self.assertGreater(page.eval_on_selector_all("#cards > *", "els => els.length"), 0)  # the page searches under its policy
        self.assertEqual([], errors)  # and nothing of its own was refused
        # what a mistake of escaping could let in: a handler in markup, and a script added at run time
        page.evaluate("""() => {
            document.body.insertAdjacentHTML('beforeend', '<img src="x:" onerror="window.__ran = 1">');
            const s = document.createElement('script'); s.textContent = 'window.__ran2 = 1'; document.body.append(s);
        }""")
        page.wait_for_timeout(500)
        self.assertEqual([None, None], page.evaluate("() => [window.__ran || null, window.__ran2 || null]"))  # neither ran
        self.assertTrue(errors)  # the browser said why
        for path in ("/cue", "/deck"):  # the printable pages: their print key works without a handler in an attribute
            errors.clear()
            page.goto(base + path)
            page.evaluate("() => { window.print = () => { window.__printed = 1; }; }")  # the dialog, stood in for
            page.click("#print")
            self.assertEqual(1, page.evaluate("() => window.__printed || 0"), path)
            self.assertEqual([], errors, path)


if __name__ == "__main__":
    unittest.main()
