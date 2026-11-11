"""The interview kit at the panel's own address (apps/api/web.py kit_proxy, apps/api/tasks.py kit_url): each job's kit
comes from a server of its own, so two jobs opened in turn each get their own page; the start route answers for the job
asked; an unknown job and a malformed body are refused before anything reaches a kit; the kit's pages carry the panel's
frame and connection policy. No model is called.

    python3 -m unittest tests/app/test_kit_proxy.py -v
"""
import pathlib  # paths
import socket  # a request no client library would send
import sys  # the import path
import unittest  # the runner
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
