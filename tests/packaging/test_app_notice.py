"""The desktop app's notice of a problem (apps/desktop/app.py notice_page, tell): a page of Offerowl's own look in the browser,
where the windowless Windows app showed the system's grey message box. Checked with the standard library: the page is made
in a temporary data folder, and the browser is never opened (its opening is caught and recorded)."""
import importlib.util  # the app, by its file
import os  # the language and the data folder
import pathlib  # paths
import tempfile  # a data folder of the test's own
import unittest  # the runner
from unittest import mock  # the browser's opening, caught

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
SPEC = importlib.util.spec_from_file_location("offerowl_desktop_app", ROOT / "apps" / "desktop" / "app.py")  # not on the import path
APP = importlib.util.module_from_spec(SPEC)  # the module
SPEC.loader.exec_module(APP)  # read once


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()  # the data folder, removed after the test
        self.addCleanup(self.tmp.cleanup)  # even after a failure
        env = {"OFFEROWL_DATA_DIR": self.tmp.name, "OFFEROWL_LANG": "", "LANG": "en_US.UTF-8", "LC_ALL": "", "LC_MESSAGES": ""}  # English by the locale (no fixed language), this folder
        patcher = mock.patch.dict(os.environ, env)  # put back after the test
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(APP.SHOW.update, {"browser": APP.SHOW["browser"]})  # the rule as it was

    def test_the_page_sets_every_word_as_text_and_fetches_nothing(self):
        page = APP.notice_page("Offerowl could not start", "The server <b>did not</b> start.", "OSError: <port> & more")
        self.assertIn("&lt;b&gt;did not&lt;/b&gt;", page)  # the words as text
        self.assertIn("OSError: &lt;port&gt; &amp; more", page)  # the log's end too, in its block
        self.assertNotIn("<b>did not</b>", page)  # never as markup
        for fetch in ("<script", "<link", "src=\"http", "url(http", "@import"):  # one file: nothing is asked of a network or a script
            self.assertNotIn(fetch, page)
        self.assertIn("prefers-color-scheme: dark", page)  # light or dark as the system is
        self.assertIn(pathlib.Path(self.tmp.name, "logs").as_uri(), page)  # its key goes to the logs folder

    def test_the_page_carries_the_wordmark_and_the_persons_language(self):
        with mock.patch.dict(os.environ, {"LANG": "ko_KR.UTF-8"}):
            page = APP.notice_page(APP.t("Offerowl could not start"), APP.t("Offerowl stopped"))
        self.assertIn('lang="ko"', page)
        self.assertIn("Offerowl을 시작하지 못했습니다", page)  # the title in Korean
        self.assertIn("로그 폴더 열기", page)  # and its key
        if (ROOT / "docs" / "assets" / "logo-light.svg").is_file():  # the wordmark, both themes, inside the page
            self.assertEqual(2, page.count("<svg"))

    def test_a_problem_opens_its_page_in_the_browser(self):
        APP.SHOW["browser"] = True  # a person's own start
        with mock.patch.object(APP.webbrowser, "open", return_value=True) as opened:
            APP.tell("Another program is using the port Offerowl needs (8798).", title="Offerowl could not start")
        page = pathlib.Path(self.tmp.name, "logs", "problem.html")  # beside the logs it points to
        self.assertTrue(page.is_file())
        opened.assert_called_once_with(page.as_uri())  # that page, once
        self.assertIn("(8798)", page.read_text(encoding="utf-8"))

    def test_a_run_without_the_browser_only_logs(self):
        APP.SHOW["browser"] = False  # --no-browser: a test's run, a service
        with mock.patch.object(APP.webbrowser, "open") as opened:
            APP.tell("The Offerowl server did not start. The end of its log:", detail="the end")
        opened.assert_not_called()  # no window
        self.assertFalse(pathlib.Path(self.tmp.name, "logs", "problem.html").exists())  # and no page


if __name__ == "__main__":
    unittest.main()
