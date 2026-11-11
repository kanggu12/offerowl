"""The search view's server on a free port: the page, its strings, the health check, the Host guard, the optional model."""
import importlib.util  # is numpy there
import json  # API answers
import os  # the language setting
import shutil  # clean up
import tempfile  # the vector cache
import threading  # the server beside the test
import unittest  # the test runner
import unittest.mock  # a pinned language setting
import urllib.error  # refused requests
import urllib.request  # requests

import helpers  # the import path and the example
from interview import i18n, server  # strings; the server


class ServerTest(unittest.TestCase):  # the server over real HTTP on localhost
    def start(self, **kw):
        """A server for the example on a free port, stopped after the test."""
        self.addCleanup(i18n.use)  # afterwards the language follows the environment again
        with unittest.mock.patch.dict(os.environ, {"OFFEROWL_LANG": "ko"}):  # CI sets en; this test reads the Korean page
            i18n.use("ko")  # the example's language
        cache = tempfile.mkdtemp(prefix="offerowl-iv-vectors-")  # the vector cache never goes into the repository
        self.addCleanup(shutil.rmtree, cache, True)  # remove the cache after the test, ignoring errors
        srv, index = server.make_server(helpers.example_job(), port=0, cache_dir=cache, **kw)  # port 0 lets the system pick a free port
        th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)  # serve beside the test; a short poll makes shutdown quick
        th.start()  # start answering requests
        self.addCleanup(srv.server_close)  # cleanups run in reverse, so this closes the socket after shutdown
        self.addCleanup(srv.shutdown)  # stop the serve loop first
        return f"http://127.0.0.1:{srv.server_address[1]}", index  # the base URL on the chosen port, and the search index

    def get(self, url, host=None):
        """(status, body) of a GET."""
        req = urllib.request.Request(url, headers={"Host": host} if host else {})  # an optional Host header, to test the guard
        try:
            with urllib.request.urlopen(req, timeout=10) as r:  # a timeout, so a stuck server fails the test instead of hanging it
                return r.status, r.read().decode("utf-8", errors="replace")  # fonts are bytes; only the status matters for them
        except urllib.error.HTTPError as e:  # error statuses arrive as exceptions
            return e.code, ""  # the status is all those tests check

    def test_page_and_health(self):
        """The page carries every item, the kit's settings and the strings; the model switch is hidden by default."""
        base, index = self.start()  # no embedder: keyword search only
        code, html = self.get(base + "/")  # the page
        self.assertEqual(code, 200)  # the page is served
        self.assertNotIn("{{", html)  # every string slot filled
        self.assertIn("<title>면접 대본 검색</title>", html)  # the page title comes from the Korean strings
        self.assertIn('placeholder="들은 질문을 그대로 입력하세요 (예: 자기소개, 멱등 키, why Gamma Cloud, R1)"', html)  # the kit's examples fill the search box placeholder
        self.assertIn('aria-pressed="false" hidden>', html)  # keyword search only
        # the item data embedded in the page, with escaped script closers restored
        data = json.loads(html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0].replace("<\\/", "</"))
        self.assertEqual(len(data["items"]), 18)  # every scene and story is on the page
        self.assertEqual(data["kit"]["fallback"], "K1")  # kit settings reach the page
        self.assertEqual(data["kit"]["sections"]["R"], "알파페이")  # so do the section tab names
        self.assertIn(["감마클라우드", "gamma"], data["syn"])  # the job's synonyms after the built-in ones
        self.assertFalse(data["model"])  # the page knows no model is set up
        self.assertNotIn("path", data["items"][0])  # local paths stay on the server
        code, body = self.get(base + "/api/health")  # the health check
        h = json.loads(body)  # its JSON answer
        self.assertEqual((code, h["items"], h["state"]), (200, 18, "none"))  # up, with every item, and no model at all

    def test_host_guard_and_fonts(self):
        """Another Host name is refused; only the two font files are served."""
        base, _ = self.start()  # a plain server
        port = base.rsplit(":", 1)[1]  # its port, to build a foreign Host header
        self.assertEqual(self.get(base + "/", host=f"example.invalid:{port}")[0], 403)  # a request for another host name is refused
        self.assertEqual(self.get(base + "/fonts/PretendardVariable.woff2")[0], 200)  # a bundled font is served
        self.assertEqual(self.get(base + "/fonts/../server.py")[0], 404)  # a path that climbs out of the fonts folder is not

    def test_inside_the_panel_the_kit_leaves_the_look_and_the_keys_to_it(self):
        """Inside the Offerowl panel (?embed=1) the kit's deck draws no desk and no bar, and its search view hides the look
        switch and the Practice key, which the panel has itself; opened on its own, the deck keeps its bar."""
        base, _ = self.start()  # a plain server
        code, inside = self.get(base + "/deck?lang=ko&embed=1")  # as the panel's frame asks for it
        self.assertEqual(code, 200)
        self.assertIn('class="embedded"', inside)  # the deck knows it is inside the panel
        code, alone = self.get(base + "/deck?lang=ko")  # opened in a tab of its own
        self.assertEqual(code, 200)
        self.assertNotIn('class="embedded"', alone)  # the plain page, with its print key
        code, page = self.get(base + "/")  # the search view: embedding is read in the page itself (?embed=1)
        self.assertIn("html.embedded :is(#theme, #practiceBtn) { display: none; }", page)  # the two keys that would disagree with the panel

    @unittest.skipIf(importlib.util.find_spec("numpy") is None, "numpy is not installed: the optional model path needs it")
    def test_optional_model_path_with_a_stand_in(self):
        """With a stand-in embedder the switch shows, /api/dense answers after switch-on, and is 503 when off."""
        def embed(text):  # a bag of letters: enough to rank "kafka" questions first
            v = [0.0] * 26  # one count per Latin letter
            for c in text.lower():  # case does not matter
                if "a" <= c <= "z":  # only Latin letters count
                    v[ord(c) - 97] += 1.0  # count this letter in its slot
            return v

        base, _ = self.start(embedder=embed)  # the optional model path, with the stand-in instead of a real model
        code, html = self.get(base + "/")  # the page again
        self.assertIn('aria-pressed="false">', html)  # the switch is there
        self.assertEqual(self.get(base + "/api/dense?q=kafka")[0], 503)  # off until switched on
        req = urllib.request.Request(base + "/api/model/on", method="POST", data=b"")  # switch the model on, as the page's button does
        with urllib.request.urlopen(req, timeout=10) as r:  # send it
            self.assertIn(json.loads(r.read())["state"], ("loading", "on"))  # the switch answers at once, still loading or already on
        for _ in range(100):  # the stand-in loads at once; the vectors follow
            code, body = self.get(base + "/api/dense?q=kafka%20event%20pipeline")  # a query the letter counts should rank Kafka scenes for
            if code == 200:  # the vectors are built
                break
            threading.Event().wait(0.05)  # wait a moment before asking again
        self.assertEqual(code, 200)  # the model path answered within the wait
        scores = json.loads(body)["scores"]  # one row per item
        self.assertEqual(len(scores), 18)  # every item gets a score
        self.assertTrue(all(len(s) == 4 for s in scores))  # id, score, view label, view text

    def test_started_as_a_script_with_the_panel_settings(self):
        """python3 src/interview/server.py with OFFEROWL_WORKSPACE, OFFEROWL_JOB and OFFEROWL_PORT serves that job."""
        import socket  # a free port
        import subprocess  # the server as its own process, as the panel starts it
        import sys  # this Python
        with socket.socket() as s:  # ask the system for a free port, then free it for the server
            s.bind(("127.0.0.1", 0))  # port 0: the system picks one
            port = s.getsockname()[1]  # the port it picked
        env = {**os.environ, "OFFEROWL_WORKSPACE": str(helpers.EXAMPLE), "OFFEROWL_JOB": "gamma-platform",
               "OFFEROWL_PORT": str(port), "PYTHONDONTWRITEBYTECODE": "1"}  # the panel's three settings
        p = subprocess.Popen([sys.executable, str(helpers.SRC / "interview" / "server.py")], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # started the way the panel starts it
        self.addCleanup(p.wait, 10)  # reap it after the kill below
        self.addCleanup(p.kill)  # never leave it running
        code, body = 0, ""  # nothing heard yet
        for _ in range(100):  # up to ten seconds for it to come up
            try:
                code, body = self.get(f"http://127.0.0.1:{port}/api/health")  # the health check the panel's probe would see
                break  # it answered
            except OSError:  # not listening yet
                threading.Event().wait(0.1)  # a short pause before the next try
        self.assertEqual(code, 200)  # it answers on the port the panel named
        self.assertEqual(json.loads(body)["items"], 18)  # and serves the job the panel named


if __name__ == "__main__":  # the file can also run on its own
    unittest.main()
