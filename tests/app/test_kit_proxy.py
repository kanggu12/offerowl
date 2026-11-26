"""The interview kit at the panel's own address (apps/api/web.py kit_proxy, apps/api/services/interview/task_kit.py kit_url): each job's kit
comes from a server of its own, so two jobs opened in turn each get their own page; the start route answers for the job
asked; an unknown job and a malformed body are refused before anything reaches a kit; the kit's pages carry the panel's
frame and connection policy. No model is called.

    python3 -m unittest tests/app/test_kit_proxy.py -v
"""
import http.client  # a request with a browser's navigation headers
import json  # the kit's health answer
import os  # the model's setting
import pathlib  # paths
import re  # the words of a page
import shutil  # the stand-in model folder, removed
import socket  # a request no client library would send
import sys  # the import path
import tempfile  # the stand-in model folder
import unittest  # the runner
import unittest.mock  # the setting, for one test
import urllib.error  # a refused read
import urllib.request  # reads with their headers

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "tests" / "app"))  # the shared test case
from test_panel import POSTING, PanelCase, q  # noqa: E402  one server and workspace per class, on the fictional example


class TestKitProxy(PanelCase):
    """Two jobs with a kit each, on one panel."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        case = cls("test_each_job_gets_its_own_kit")  # the shared helpers need an instance
        case.start_profile()  # the example's facts, kept
        cls.jobs = []  # (job id, company)
        for company in ("감마클라우드", "델타페이먼츠"):  # two fictional companies
            jid = case.post("/api/v1/jobs", {"company": company, "role": "백엔드 플랫폼 엔지니어", "posting": POSTING.read_text(encoding="utf-8")})["job"]
            case.post("/api/v1/interview/kit", {"job": jid, "lang": "ko"})  # its question map and kit files, no model
            cls.jobs.append((jid, company))

    def server_api(self):  # the panel's one API object, shared by its request threads
        return type(self).srv.RequestHandlerClass.panel

    def page(self, path):  # a read with its headers
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=60) as r:
            return r.status, r.headers, r.read()

    def test_each_job_gets_its_own_kit(self):
        for jid, _ in self.jobs + self.jobs[:1]:  # one, the other, then the first again: nothing swapped under it
            code, headers, body = self.page(f"/kit/{q(jid)}/")
            self.assertEqual(200, code)
            self.assertIn("text/html", headers.get("Content-Type", ""))
            self.assertIn("frame-ancestors 'self'", " ".join(headers.get_all("Content-Security-Policy") or []))   # framed by the panel only
            self.assertIn("script-src 'self' 'sha256-", " ".join(headers.get_all("Content-Security-Policy") or []))  # the kit's own scripts only, at the panel's address too
            code, _, _ = self.page(f"/kit/{q(jid)}/api/health")  # its own API, through the same address
            self.assertEqual(200, code)
        api = self.server_api()
        ports = {jid: srv.server_address[1] for jid, (srv, _) in api.tasks.kit_srvs.items()}  # the servers kept
        self.assertEqual({j for j, _ in self.jobs}, set(ports))  # one per job, both still up
        self.assertEqual(2, len(set(ports.values())))  # on ports of their own

    def test_a_kit_server_that_stopped_is_made_again(self):
        jid = self.jobs[0][0]
        self.assertEqual(200, self.page(f"/kit/{q(jid)}/api/health")[0])  # served
        api = self.server_api()
        srv, _ = api.tasks.kit_srvs[jid]  # its server
        srv.shutdown()  # its loop ends behind the panel's back (as a crashed loop would)
        srv.loop.join(5)
        self.assertFalse(srv.loop.is_alive())
        self.assertEqual(200, self.page(f"/kit/{q(jid)}/api/health")[0])  # the next open starts a new one
        self.assertIsNot(srv, api.tasks.kit_srvs[jid][0])  # not the stopped one
        srv.server_close()  # its port, freed

    def test_the_kit_takes_the_similarity_model_named_in_the_setting(self):
        """OFFEROWL_SEARCH_MODEL names the model's folder: the job's kit then has the model (off until its page's switch
        loads it) and the page shows the switch; a folder without the model's files gives no switch, and the log says why."""
        jid = self.jobs[1][0]
        api = self.server_api()

        def fresh():  # this job's kit server let go, so the next open makes one with the setting as it is now
            got = api.tasks.kit_srvs.pop(jid, None)
            if got:
                got[0].shutdown()
                got[0].loop.join(5)
                got[0].server_close()

        def health():
            return json.loads(self.page(f"/kit/{q(jid)}/api/health")[2])

        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-kit-model-"))  # a folder that only looks like the model's
        self.addCleanup(shutil.rmtree, tmp, True)
        self.addCleanup(fresh)  # the next test gets a kit without it
        fresh()
        with unittest.mock.patch.dict(os.environ, {"OFFEROWL_SEARCH_MODEL": str(tmp)}), self.assertLogs("offerowl.panel", "WARNING") as logs:
            self.assertIsNone(health()["model"])  # no files there: keywords only
            self.assertIn(" hidden>", self.page(f"/kit/{q(jid)}/")[2].decode("utf-8").split('id="engine"', 1)[1].split("</button>", 1)[0])  # no switch
        self.assertIn("tokenizer.json, onnx/model_int8.onnx", logs.output[0])  # said in the panel's log
        (tmp / "onnx").mkdir()
        for name in ("tokenizer.json", "onnx/model_int8.onnx"):  # stand-ins: nothing loads until the switch
            (tmp / name).write_bytes(b"")
        fresh()
        with unittest.mock.patch.dict(os.environ, {"OFFEROWL_SEARCH_MODEL": str(tmp)}):
            got = health()
            self.assertEqual(("bge-m3-int8", "off"), (got["model"], got["state"]))  # there, and off
            self.assertNotIn(" hidden>", self.page(f"/kit/{q(jid)}/")[2].decode("utf-8").split('id="engine"', 1)[1].split("</button>", 1)[0])  # the switch shows

    def test_a_kit_json_that_points_out_of_the_workspace_shows_nothing_from_there(self):
        # kit.json can come with a restored backup: a source it names outside the workspace must never reach the kit's page,
        # which the panel serves on its own address (the panel's kits are read confined, src/interview/job.py kept)
        import json  # the kit file
        import shutil  # the outside folder, removed
        import tempfile  # a folder out of the workspace
        out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-outside-"))
        self.addCleanup(shutil.rmtree, out, True)
        (out / "secret.md").write_text("## Z. Outside\n\n### Z1. Outside / Outside\n\n**핵심** OUTSIDE-SECRET-LINE\n\n"
                                       "**면접관** OUTSIDE-SECRET-LINE?\n**나** OUTSIDE-SECRET-LINE.\n", encoding="utf-8")  # a scene, as the kit reads one
        jid = self.jobs[0][0]
        api = self.server_api()
        kit_file = api.ws.job_dir(jid) / "interview" / "kit.json"
        kit = json.loads(kit_file.read_text(encoding="utf-8"))
        before = json.dumps(kit, ensure_ascii=False)  # put back afterwards
        self.addCleanup(kit_file.write_text, before, encoding="utf-8")
        kit["sources"] = [{"file": str(out / "secret.md"), "label": "x", "prefix": "Z", "role": "scenes"},  # absolute
                          {"file": __import__("os").path.relpath(out / "secret.md", kit_file.parent), "label": "y", "prefix": "Y", "role": "scenes"}]  # and climbing out with ".."
        kit_file.write_text(json.dumps(kit, ensure_ascii=False), encoding="utf-8")
        got = api.tasks.kit_srvs.get(jid)  # a server already serving it would keep its old index
        if got:
            got[0].shutdown()
            got[0].loop.join(5)
            got[0].server_close()
        code, _, body = self.page(f"/kit/{q(jid)}/")
        self.assertEqual(200, code)
        self.assertNotIn(b"OUTSIDE-SECRET-LINE", body)  # nothing of the file out there

    def test_a_person_opening_the_kit_s_address_lands_in_the_panel(self):
        """A browser's own navigation to /kit/<job>/ goes to the job's scripts in the panel's Interview tab; the printable pages
        and the API under it, and a fetch of the page itself, are served as before."""
        jid = self.jobs[0][0]
        nav = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}  # what a browser sends when a person opens an address
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        conn.request("GET", f"/kit/{q(jid)}/", headers=nav)
        r = conn.getresponse()
        r.read()
        self.assertEqual(302, r.status)
        self.assertEqual(f"/?job={q(jid)}&show=scripts", r.getheader("Location"))
        conn.request("GET", f"/kit/{q(jid)}/api/health", headers=nav)  # under it: the kit's own
        r = conn.getresponse()
        r.read()
        self.assertEqual(200, r.status)
        conn.close()
        self.assertEqual(200, self.page(f"/kit/{q(jid)}/")[0])  # not a navigation: the page
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        conn.request("GET", "/kit/no-such-job/", headers=nav)  # an application that is gone, opened by a person: the panel
        r = conn.getresponse()
        r.read()
        self.assertEqual((302, "/?job=no-such-job&show=scripts"), (r.status, r.getheader("Location")))   # the panel, which says it is gone
        conn.request("GET", f"/kit/{q(jid)}/?q={q('자기소개 해 주세요')}", headers=nav)  # an old search link's question goes with it (it was dropped)
        r = conn.getresponse()
        r.read()
        self.assertEqual((302, f"/?job={q(jid)}&show=scripts&q={q('자기소개 해 주세요')}"), (r.status, r.getheader("Location")))
        conn.close()

    def test_a_kit_page_that_is_not_there_is_a_page_of_the_panel(self):
        """A person opening a page of the kit that is not there (the talk's slides before the talk is made, an old link) gets a
        page of the panel's own: its theme, its face, its stylesheets and its words in the language chosen in the panel, the
        application's name in its title, a key back to its scripts. It mixed Korean and English on a page of its own colours."""
        jid, company = self.jobs[0]
        self.assertTrue(self.post("/api/v1/interview/start", {"job": jid})["started"])  # the kit runs: the kit itself answers 404
        nav = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        conn.request("GET", f"/kit/{q(jid)}/talk/deck.pdf", headers=nav)
        r = conn.getresponse()
        page = r.read().decode("utf-8")
        conn.close()
        self.assertEqual(404, r.status)
        for part in ("/static/theme.js", "/static/i18n.js", "/static/i18n/ko.js", "/static/tokens.css", "/static/skin.css", "/static/kitgone.js"):   # the panel's own
            self.assertIn(part, page)
        self.assertIn(f"<title>{company} · Offerowl</title>", page)  # whose kit, before the page's words are put in its language
        self.assertIn(f'href="/?job={q(jid)}&amp;show=scripts"', page)  # the way back
        self.assertIsNone(re.search(r"[가-힣]", page.replace(company, "")), page)  # one language in the page itself: the table gives the Korean
        self.assertNotIn("<style>", page)  # no colours of its own
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy") or "")  # the panel's policy
        words = (ROOT / "apps" / "panel" / "static" / "kitgone.js").read_text(encoding="utf-8")
        for w in re.findall(r'data-w="(\w+)"', page):  # every place of the page has its words in the script
            self.assertIn(f"{w}: t(", words)

    def test_the_start_route_answers_for_the_job(self):
        jid = self.jobs[1][0]
        self.assertTrue(self.post("/api/v1/interview/start", {"job": jid})["started"])
        self.assertIn(jid, self.server_api().tasks.kit_srvs)  # this job's own kit

    def test_refusals(self):
        for path in ("/kit/no-such-job/", "/kit/no-such-job/api/health", "/kit/NO%20SUCH%2F..%2Fjob/"):  # an application that is not there, and a name none can have
            with self.assertRaises(urllib.error.HTTPError, msg=path) as e:
                self.page(path)
            self.assertEqual(404, e.exception.code, path)
        code, _, _ = self.page(f"/kit/{q(self.jobs[0][0])}")  # no slash: sent on to the folder, where the page's relative links work
        self.assertEqual(200, code)
        jid = self.jobs[0][0]
        for length in ("-1", "many"):  # a length that would hold the thread, and one that is no number
            with socket.create_connection(("127.0.0.1", self.port), timeout=20) as s:
                s.sendall((f"POST /kit/{q(jid)}/api/practice/start HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                           f"Origin: http://127.0.0.1:{self.port}\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n"
                           "Connection: close\r\n\r\n").encode())
                status = s.recv(200).split(b"\r\n", 1)[0]
            self.assertIn(b" 400 ", status, length)  # refused at once, nothing passed to the kit


if __name__ == "__main__":
    unittest.main()
