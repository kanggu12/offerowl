#!/usr/bin/env python3
"""A job's own materials (apps/api/materials.py) through the panel's server, on fictional files only: brought in as the
page sends them, listed with the job, handed back byte for byte, previewed by kind, copied to the Desktop, removed with an
undo, refused when their kind is not kept, kept under safe names, and left out of a backup's page pictures. A deck and a
Word file are printed by LibreOffice in the render container when its image is built here; the command that starts it is
checked without Docker.

    python3 -m unittest tests/app/test_materials.py -v
"""
import hashlib  # what came in against what comes back
import http.client  # an answer's own headers
import io  # zip files in memory
import json  # requests and answers
import os  # environment
import pathlib  # paths
import shutil  # temporary folders, and is Docker here
import subprocess  # is the render image built here
import sys  # the import path
import tempfile  # a data folder per class
import threading  # the server in the background
import unittest  # the runner
import urllib.error  # refused requests
import urllib.parse  # names and job ids in addresses
import urllib.request  # requests
import zipfile  # a backup, and the Office files written below
from unittest import mock  # a small cap, and the converter's command without Docker

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
from apps.api import materials as M  # noqa: E402  the module under test
from apps.panel import server  # noqa: E402  the panel (the page and the API)

POSTING = ROOT / "tests" / "app" / "fixtures" / "posting_ko.md"  # a fictional posting of a fictional company
NOTES_MD = """# 감마클라우드 면접 준비

감마클라우드는 **결제 플랫폼**을 운영하는 가상의 회사다. [채용 공고](https://example.com/jobs)

## 질문 목록

- 승인 경로를 나눈 이유
  - 배포 시간을 줄이려고
1. 장애 대응 순서

| 주제 | 준비 |
|---|---|
| 정산 | 끝냄 |

> 숫자는 근거에 있는 것만 말한다.

```python
if total == expected:
    print("ok")
```
"""  # a fictional study note with the parts a preview draws
SOLUTION = "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return seen[target - n], i\n        seen[n] = i\n"  # a fictional live-coding answer
PAGE = "<!doctype html><html><head><title>Brief</title><script>document.title = 'ran'</script><base href='https://example.com/'></head><body><h1>Gamma Cloud</h1><a href='https://example.com'>site</a></body></html>"  # a saved page with a script


def pdf_bytes(pages: list) -> bytes:
    """A small PDF of one line of text per page (Helvetica, which every reader has), as tests/render/test_pdftools.py writes them."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]  # catalog, page tree, font
    kids = []  # the page objects
    for text in pages:  # each page: its content, then the page that points at it
        stream = f"BT /F1 14 Tf 1 0 0 1 72 760 Tm ({text}) Tj ET"  # one line near the top
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {len(objects)} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(len(objects))
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"  # A4 pages
    out, offsets = "%PDF-1.4\n", []  # the file, and where each object starts
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out)  # the table of offsets
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    return (out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode("latin-1")


CT = "http://schemas.openxmlformats.org/package/2006/content-types"  # the parts list of an Office file
REL = "http://schemas.openxmlformats.org/package/2006/relationships"  # how its parts point at each other
OFFICE_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"  # the kinds of those pointers
PML = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'  # every part's first line
TREE = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'  # an empty shape tree's head


def rels(*items) -> str:
    """A relationships part: (kind, target) in order, as rId1, rId2 ..."""
    return HEAD + f'<Relationships xmlns="{REL}">' + "".join(f'<Relationship Id="rId{i}" Type="{OFFICE_R}/{k}" Target="{t}"/>' for i, (k, t) in enumerate(items, 1)) + "</Relationships>"


def docx_bytes(text: str) -> bytes:
    """The smallest Word file LibreOffice opens: one paragraph."""
    b = io.BytesIO()  # in memory
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:  # an Office file is a zip of parts
        z.writestr("[Content_Types].xml", HEAD + f'<Types xmlns="{CT}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", rels(("officeDocument", "word/document.xml")))
        z.writestr("word/document.xml", HEAD + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return b.getvalue()


def pptx_bytes(titles: list) -> bytes:
    """A small 16:9 deck LibreOffice opens: a master, a blank layout, a theme and one text box per slide."""
    pml = "application/vnd.openxmlformats-officedocument.presentationml"  # the parts' types
    colors = "".join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k, v in (("dk1", "000000"), ("lt1", "FFFFFF"), ("dk2", "1F1F1F"), ("lt2", "EEEEEE"),
                     ("accent1", "1B2E4B"), ("accent2", "2F6EBA"), ("accent3", "888888"), ("accent4", "AAAAAA"), ("accent5", "CCCCCC"),
                     ("accent6", "DDDDDD"), ("hlink", "0000FF"), ("folHlink", "800080")))  # the twelve colours a theme names
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'  # the one fill the styles repeat
    theme = (HEAD + f'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="t"><a:themeElements><a:clrScheme name="t">{colors}</a:clrScheme>'
             '<a:fontScheme name="t"><a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Arial"/>'
             f'<a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="t"><a:fillStyleLst>{fill * 3}</a:fillStyleLst><a:lnStyleLst>'
             + f'<a:ln w="9525">{fill}</a:ln>' * 3 + "</a:lnStyleLst><a:effectStyleLst>" + "<a:effectStyle><a:effectLst/></a:effectStyle>" * 3
             + f"</a:effectStyleLst><a:bgFillStyleLst>{fill * 3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>")
    b = io.BytesIO()  # in memory
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:  # every part the deck needs
        parts = [("/ppt/presentation.xml", f"{pml}.presentation.main+xml"), ("/ppt/slideMasters/slideMaster1.xml", f"{pml}.slideMaster+xml"),
                 ("/ppt/slideLayouts/slideLayout1.xml", f"{pml}.slideLayout+xml"), ("/ppt/theme/theme1.xml", "application/vnd.openxmlformats-officedocument.theme+xml")]
        parts += [(f"/ppt/slides/slide{i}.xml", f"{pml}.slide+xml") for i in range(1, len(titles) + 1)]  # one part per slide
        z.writestr("[Content_Types].xml", HEAD + f'<Types xmlns="{CT}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>' + "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in parts) + "</Types>")
        z.writestr("_rels/.rels", rels(("officeDocument", "ppt/presentation.xml")))
        z.writestr("ppt/presentation.xml", HEAD + f'<p:presentation {PML}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
                   + "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 2}"/>' for i in range(1, len(titles) + 1))
                   + '</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels", rels(("slideMaster", "slideMasters/slideMaster1.xml"), ("theme", "theme/theme1.xml"),
                                                           *[("slide", f"slides/slide{i}.xml") for i in range(1, len(titles) + 1)]))
        z.writestr("ppt/slideMasters/slideMaster1.xml", HEAD + f'<p:sldMaster {PML}><p:cSld><p:spTree>{TREE}</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" '
                   'tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" '
                   'folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>')
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", rels(("slideLayout", "../slideLayouts/slideLayout1.xml"), ("theme", "../theme/theme1.xml")))
        z.writestr("ppt/slideLayouts/slideLayout1.xml", HEAD + f'<p:sldLayout {PML} type="blank"><p:cSld name="Blank"><p:spTree>{TREE}</p:spTree></p:cSld>'
                   "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>")
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", rels(("slideMaster", "../slideMasters/slideMaster1.xml")))
        z.writestr("ppt/theme/theme1.xml", theme)
        for i, title in enumerate(titles, 1):  # each slide: one text box
            box = (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="838200" y="838200"/>'
                   '<a:ext cx="10515600" cy="1325563"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>'
                   f'<a:p><a:r><a:rPr lang="en-US" sz="4000"/><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>')
            z.writestr(f"ppt/slides/slide{i}.xml", HEAD + f"<p:sld {PML}><p:cSld><p:spTree>{TREE}{box}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>")
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", rels(("slideLayout", "../slideLayouts/slideLayout1.xml")))
    return b.getvalue()


def render_image_built() -> bool:
    """The render image of this Dockerfile is on this PC (render/run.sh would build it first, which a test does not do)."""
    if not shutil.which("docker"):  # no Docker at all
        return False
    tag = hashlib.md5((ROOT / "render" / "Dockerfile").read_bytes()).hexdigest()[:12]  # render/run.sh's own naming
    return subprocess.run(["docker", "image", "inspect", f"offerowl-render:{tag}"], capture_output=True).returncode == 0  # found or not


class Server(unittest.TestCase):
    """One panel server, one workspace and one fictional job per class, with exports to a Desktop of its own."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-materials-"))  # the data folder and the Desktop
        cls.env = mock.patch.dict(os.environ, {"OFFEROWL_DESKTOP": str(cls.tmp / "Desktop"), "OFFEROWL_PANEL_BACKEND": "none"})  # no agent is ever asked
        cls.env.start()  # for the whole class
        os.environ.pop("OFFEROWL_PANEL_AGENT", None)  # a stand-in class run earlier must not count
        cls.srv = server.serve(0, data=cls.tmp / "data")  # a free port
        cls.port = cls.srv.server_address[1]  # the port it got
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()  # it answers while the tests run
        cls.api = cls.srv.RequestHandlerClass.panel  # the running API, for its folders
        cls.job = cls.post(cls, "/api/v1/jobs", {"company": "감마클라우드", "posting": POSTING.read_text(encoding="utf-8")})["job"]  # a fictional job
        cls.folder = cls.tmp / "data" / "workspace" / "jobs" / cls.job / "materials"  # where its materials are kept

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()  # serve_forever returns
        cls.srv.server_close()  # the port is free again
        cls.env.stop()  # the environment as it was
        shutil.rmtree(cls.tmp, ignore_errors=True)  # every trace goes

    def url(self, path: str) -> str:
        """The server's address for a path."""
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str):
        """A read whose answer is JSON."""
        with urllib.request.urlopen(self.url(path), timeout=60) as r:  # a hung server fails the test
            return json.loads(r.read())

    def raw(self, path: str) -> tuple[int, dict, bytes]:
        """A read as bytes: (status, headers, body), a refusal included."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)  # the headers as sent
        c.request("GET", path)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()  # headers by lower-case name; two of one name: the last

    def post(self, path: str, body: dict, expect: int = 200) -> dict:
        """A JSON write as the page makes it."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # the answer and the new state
                assert r.status == expect, r.status  # a 200 where a refusal was expected fails
                return json.loads(r.read())
        except urllib.error.HTTPError as e:  # a refusal
            body = e.read()
            assert e.code == expect, (e.code, body[:300])  # the answer is shown when the code is wrong
            return json.loads(body or b"{}")

    def send(self, name: str, data: bytes, job: str | None = None) -> tuple[int, dict]:
        """A file sent as the page sends it: its raw bytes, its name in X-File-Name, the job in the query."""
        req = urllib.request.Request(self.url(f"/api/v1/jobs/materials?job={urllib.parse.quote(job or self.job)}"), data=data, method="POST",
                                     headers={"Content-Type": "application/octet-stream", "X-File-Name": urllib.parse.quote(name)})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # kept
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:  # refused
            return e.code, json.loads(e.read() or b"{}")

    def add(self, name: str, data: bytes) -> dict:
        """A file that must be kept: its record."""
        code, out = self.send(name, data)
        self.assertEqual(200, code, out)
        return out["material"]

    def listed(self) -> list:
        """The job's materials as the page gets them with the job."""
        return next(j for j in self.get("/api/v1/state")["jobs"] if j["id"] == self.job)["materials"]

    def base(self, mid: str) -> str:
        """The address of one material."""
        return f"/api/v1/jobs/{urllib.parse.quote(self.job)}/materials/{mid}"


class KeptAsTheyCame(Server):
    """A file comes in, is listed, comes back byte for byte, and leaves the list with an undo that brings it back."""

    def test_upload_list_and_fetch_byte_for_byte(self):
        pdf = pdf_bytes(["Gamma Cloud platform notes", "Second page"])  # a fictional explainer printed to PDF
        given = {"감마 설명 자료.pdf": pdf, "면접 준비.md": NOTES_MD.encode("utf-8"), "two_sum.py": SOLUTION.encode("utf-8"),
                 "덱.pptx": pptx_bytes(["Gamma platform"]), "답변.docx": docx_bytes("지원 동기")}  # five kinds, two of them Office files
        recs = {name: self.add(name, data) for name, data in given.items()}  # each sent as the page sends it
        for name, data in given.items():  # each one
            rec = recs[name]
            self.assertEqual(hashlib.sha256(data).hexdigest(), rec["sha256"])  # the index holds the hash of what came in
            self.assertEqual(len(data), rec["size"])  # and its size
            self.assertEqual(name, rec["name"])  # and the name it came with
            status, headers, body = self.raw(self.base(rec["id"]))  # handed back
            self.assertEqual(200, status)
            self.assertEqual(rec["sha256"], hashlib.sha256(body).hexdigest())  # byte for byte
            self.assertEqual(data, (self.folder / name).read_bytes())  # kept on disk under its own name, unchanged
            self.assertIn("filename*=UTF-8''" + urllib.parse.quote(name, safe=""), headers["content-disposition"])  # saved under its own name
        self.assertEqual("application/pdf", self.raw(self.base(recs["감마 설명 자료.pdf"]["id"]))[1]["content-type"])  # each with its type
        self.assertEqual("text/markdown; charset=utf-8", self.raw(self.base(recs["면접 준비.md"]["id"]))[1]["content-type"])  # text says how to read it
        self.assertTrue(self.raw(self.base(recs["덱.pptx"]["id"]))[1]["content-type"].endswith("presentationml.presentation"))
        listed = self.listed()  # with the job, as the page gets it on every poll
        self.assertEqual(listed, self.get(f"/api/v1/jobs/{urllib.parse.quote(self.job)}/materials")["materials"])  # the same list on its own
        mine = [m for m in listed if m["id"] in {r["id"] for r in recs.values()}]  # this test's files (the class shares one job)
        self.assertEqual([recs[n]["id"] for n in given], [m["id"] for m in mine])  # in the order they came
        self.assertEqual({"id", "title", "name", "kind", "size", "added", "sha256"}, set(mine[0]))  # the page never gets the folder's names
        self.assertEqual(["pdf", "md", "py", "pptx", "docx"], [m["kind"] for m in mine])  # each kind by its extension
        self.assertEqual(["감마 설명 자료", "면접 준비", "two_sum", "덱", "답변"], [m["title"] for m in mine])  # listed under the names they came with

    def test_remove_then_undo_brings_it_back(self):
        rec = self.add("회사 정리.md", "# 감마클라우드\n\n가상의 회사.\n".encode("utf-8"))  # a fictional brief
        self.post("/api/v1/jobs/materials/remove", {"job": self.job, "id": rec["id"]})  # off the list
        self.assertNotIn(rec["id"], [m["id"] for m in self.listed()])  # gone from the job
        self.assertEqual(404, self.raw(self.base(rec["id"]))[0])  # and from its address
        self.assertTrue((self.folder / "회사 정리.md").is_file())  # the file never left the folder
        steps = self.get("/api/v1/history")["steps"]  # the undo steps
        self.assertEqual({"code": "undo_remove_job_material", "title": "회사 정리"}, steps[0]["label"])  # the newest says what it takes back
        later = self.add("나중.txt", "나중에 넣은 메모".encode("utf-8"))  # a file added after the removal
        self.post("/api/v1/undo", {})  # the removal taken back
        ids = [m["id"] for m in self.listed()]  # the list now
        self.assertIn(rec["id"], ids)  # back
        self.assertIn(later["id"], ids)  # and the file added after it stays: an undo never drops a later file
        self.assertEqual(rec["sha256"], hashlib.sha256(self.raw(self.base(rec["id"]))[2]).hexdigest())  # byte for byte
        r = self.post("/api/v1/jobs/materials/remove", {"job": self.job, "id": "m999"}, expect=400)  # a stale page
        self.assertEqual("material", r["what"])  # refused by name

    def test_a_kind_not_kept_is_refused(self):
        before = sorted(p.name for p in self.folder.iterdir()) if self.folder.is_dir() else []  # the folder as it is
        for name in ("setup.exe", "notes", "archive.zip", "page.htm"):  # not on the list (.htm too: the list names .html; a .jpeg is kept as a .jpg, see Names)
            code, out = self.send(name, b"fictional bytes")
            self.assertEqual((400, "material_kind"), (code, out.get("error")), name)  # said why
        after = sorted(p.name for p in self.folder.iterdir()) if self.folder.is_dir() else []
        self.assertEqual(before, after)  # nothing was written
        for job in ("no-such-job", "-general", "../x"):  # no such job, the general edition (it has no interview), an id no folder has
            code, out = self.send("notes.md", b"x", job=job)
            self.assertEqual((400, "job"), (code, out.get("error")), job)
        code, out = self.send("notes.md", b"")  # nothing in it
        self.assertEqual((400, "empty"), (code, out.get("error")))
        with mock.patch.object(M, "MAX_BYTES", 10):  # a small cap, read when the upload comes
            code, out = self.send("big.md", b"x" * 11)  # over it
        self.assertEqual((413, "too_large"), (code, out.get("error")))  # refused before it is read

    def test_names_are_made_safe_and_a_taken_name_gets_a_number(self):
        plain = "# 메모\n".encode("utf-8")  # the same fictional note under several names
        hostile = self.add('..\\..\\C:\\x\\a<b>:"q"|z?*.md', plain)  # folders of both systems and characters a disk refuses
        self.assertEqual('a<b>:"q"|z?*', hostile["title"])  # listed under the name it came with, without its folders
        names = sorted(p.name for p in self.folder.iterdir() if p.is_file())  # what is on disk
        self.assertIn("a_b___q__z__.md", names)  # every refused character made an underscore, no folder left in it
        for n in names:  # nothing a backup's restore or Windows refuses
            self.assertNotRegex(n, r'[<>:"/\\|?*\x00-\x1f]')
        self.add("../../etc/passwd.md", plain)  # a path aimed above the job
        self.assertTrue((self.folder / "passwd.md").is_file())  # kept inside the job's folder, under its last part
        self.assertFalse((self.folder.parent.parent / "etc").exists())  # nothing landed outside
        self.assertEqual("CON", self.add("CON.md", plain)["title"])  # a device name of Windows is listed as it came
        self.assertTrue((self.folder / "_CON.md").is_file())  # and kept with a mark, so Windows can hold it
        first, second, third = (self.add("면접 노트.md", plain) for _ in range(3))  # the same name three times
        self.assertEqual(["면접 노트", "면접 노트 (2)", "면접 노트 (3)"], [first["title"], second["title"], third["title"]])  # a twin says which one it is
        self.assertTrue((self.folder / "면접 노트 (3).md").is_file())  # under the same number on disk
        self.add("notes.md", plain)  # a name in small letters
        self.assertEqual("NOTES (2)", self.add("NOTES.MD", plain)["title"])  # the same name in capitals is one name to Windows and macOS
        long = self.add("가" * 120 + ".md", plain)  # a name longer than a disk takes
        kept = next(r for r in M.records(self.api.ws, self.job) if r["id"] == long["id"])["file"]  # its name on disk
        self.assertLessEqual(len(kept.encode("utf-8")), 180)  # cut to fit, with room for a number
        self.assertTrue(kept.endswith(".md"))  # its kind kept
        longer = self.add("study notes " * 25 + ".md", plain)  # 300 characters: longer than a list shows
        self.assertTrue(longer["name"].endswith(".md") and len(longer["name"]) <= 200)  # shortened before its extension, never cut through it
        out = self.post("/api/v1/jobs/materials/export", {"job": self.job, "id": longer["id"]})["exported"][0]  # and it still goes to the Desktop
        self.assertTrue(out.endswith(".md"))  # as the kind it is

    def test_export_to_the_desktop_reads_back(self):
        data = pdf_bytes(["Gamma Cloud"])  # a fictional document
        rec = self.add("감마 회사 소개.pdf", data)
        out = self.post("/api/v1/jobs/materials/export", {"job": self.job, "id": rec["id"]})  # Save to the Desktop
        self.assertEqual(["감마 회사 소개.pdf"], out["exported"])  # under the name it came with
        desk = self.tmp / "Desktop"  # the class's own Desktop
        self.assertEqual(data, (desk / "감마 회사 소개.pdf").read_bytes())  # byte for byte
        again = self.post("/api/v1/jobs/materials/export", {"job": self.job, "id": rec["id"]})["exported"][0]  # a second copy
        self.assertEqual("감마 회사 소개 (2).pdf", again)  # never over the first
        (self.folder / "감마 회사 소개.pdf").write_bytes(data + b"%changed")  # the kept file changed by hand
        r = self.post("/api/v1/jobs/materials/export", {"job": self.job, "id": rec["id"]}, expect=400)  # not what the person added
        self.assertEqual("material_changed", r["what"])  # said, and nothing copied
        self.assertEqual(2, len([p for p in desk.iterdir() if p.name.startswith("감마 회사 소개")]))
        (self.folder / "감마 회사 소개.pdf").write_bytes(data)  # as it was, for the class

    def test_a_backup_holds_the_files_and_not_their_pictures(self):
        rec = self.add("백업 확인.pdf", pdf_bytes(["Backup check"]))  # a fictional page
        preview = self.get(self.base(rec["id"]) + "/preview")  # its pictures are made
        if "missing" in preview:  # no PDF reader here: nothing to leave out
            self.skipTest("no PDF reader on this PC to draw the pages")
        with zipfile.ZipFile(io.BytesIO(self.raw("/api/v1/workspace/backup")[2])) as z:  # the file a browser saves
            names = z.namelist()
        self.assertIn(f"jobs/{self.job}/materials/백업 확인.pdf", names)  # the person's file
        self.assertIn(f"jobs/{self.job}/materials/index.json", names)  # and its list
        self.assertFalse([n for n in names if "/.preview/" in n])  # the pictures are made again when they are looked at


class Previews(Server):
    """What the page shows of each kind: page pictures, blocks of a note, the words of code, a frame that runs nothing."""

    def test_a_pdf_shows_its_pages(self):
        import pdftools  # src/pdftools.py: the readers this PC has
        if not pdftools.reader() and not render_image_built():  # neither a reader here nor the container to draw the pages in
            self.skipTest("no PDF reader (poppler or pypdfium2) and no render image on this PC")
        rec = self.add("설명 자료.pdf", pdf_bytes(["Page one of the fictional deck", "Page two", "Page three"]))  # three A4 pages
        got = self.get(self.base(rec["id"]) + "/preview")  # what the page shows
        self.assertEqual({"kind": "pdf", "view": "pages", "pages": 3, "of": 3, "more": False, "wide": False}, got)  # every page, upright
        status, headers, body = self.raw(self.base(rec["id"]) + "/pages/1.png")  # the first picture
        self.assertEqual((200, "image/png"), (status, headers["content-type"]))
        self.assertEqual(b"\x89PNG", body[:4])  # a picture
        self.assertEqual(404, self.raw(self.base(rec["id"]) + "/pages/4.png")[0])  # past its last page
        self.assertEqual(got, self.get(self.base(rec["id"]) + "/preview"))  # made once, the same answer after
        with mock.patch.object(M, "PREVIEW_PAGES", 2):  # a long document shows its start
            longer = self.add("긴 자료.pdf", pdf_bytes(["One", "Two", "Three"]))
            self.assertEqual({"pages": 2, "of": 3, "more": True}, {k: v for k, v in self.get(self.base(longer["id"]) + "/preview").items() if k in ("pages", "of", "more")})

    def test_markdown_shows_as_blocks_of_plain_words(self):
        rec = self.add("면접 준비.md", NOTES_MD.encode("utf-8"))  # a fictional study note
        got = self.get(self.base(rec["id"]) + "/preview")
        self.assertEqual(("blocks", False), (got["view"], got["cut"]))  # whole
        blocks = got["blocks"]
        self.assertEqual({"t": "h", "n": 1, "text": "감마클라우드 면접 준비"}, blocks[0])  # the title
        self.assertEqual("감마클라우드는 결제 플랫폼을 운영하는 가상의 회사다. 채용 공고 (https://example.com/jobs)", blocks[1]["text"])  # no marks, a link by its words and its address
        self.assertEqual([("승인 경로를 나눈 이유", "", 0), ("배포 시간을 줄이려고", "", 1), ("장애 대응 순서", "1.", 0)],
                         [(b["text"], b["mark"], b["depth"]) for b in blocks if b["t"] == "li"])  # bullets, a nested one, a numbered one
        self.assertEqual([(["주제", "준비"], True), (["정산", "끝냄"], False)], [(b["cells"], b.get("head", False)) for b in blocks if b["t"] == "row"])  # a table, its head marked
        self.assertIn({"t": "quote", "text": "숫자는 근거에 있는 것만 말한다."}, blocks)  # a quote
        self.assertEqual('if total == expected:\n    print("ok")', next(b for b in blocks if b["t"] == "code")["text"])  # code as written
        for b in blocks:  # nothing of it is HTML or a mark
            self.assertNotRegex(b.get("text", "") if b["t"] != "code" else "", r"\*\*|<[a-z]|\]\(")

    def test_code_and_text_show_as_written_in_their_encoding(self):
        rec = self.add("two_sum.py", SOLUTION.encode("utf-8"))  # a fictional solution
        self.assertEqual({"kind": "py", "view": "text", "text": SOLUTION, "cut": False}, self.get(self.base(rec["id"]) + "/preview"))  # every character
        korean = "감마클라우드 1차 면접 메모\n질문: 정산 지연을 어떻게 줄였나요?\n"  # a fictional note
        old = self.add("메모.txt", korean.encode("cp949"))  # saved by an older Korean Windows editor
        self.assertEqual(korean, self.get(self.base(old["id"]) + "/preview")["text"])  # read in its own encoding
        self.assertEqual("text/plain; charset=euc-kr", self.raw(self.base(old["id"]))[1]["content-type"])  # and a browser told so
        with mock.patch.object(M, "TEXT_BYTES", 10):  # a long log shows its start
            got = self.get(self.base(self.add("긴 메모.txt", "가나다라마바사".encode("utf-8"))["id"]) + "/preview")
        self.assertEqual(("가나다", True), (got["text"], got["cut"]))  # whole characters only, and said to be cut

    def test_a_saved_page_runs_nothing(self):
        rec = self.add("brief.html", PAGE.encode("utf-8"))  # a fictional saved page with a script
        got = self.get(self.base(rec["id"]) + "/preview")
        self.assertEqual("frame", got["view"])  # shown in a frame
        self.assertNotIn("<script", got["html"])  # its script taken out (the frame's sandbox runs none either)
        self.assertNotIn("<base", got["html"])  # its links keep no address of their own
        self.assertIn("<h1>Gamma Cloud</h1>", got["html"])  # the page itself
        status, headers, body = self.raw(self.base(rec["id"]))  # the file itself, at the panel's address
        self.assertEqual(PAGE.encode("utf-8"), body)  # byte for byte
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)  # every policy header, not the last one
        c.request("GET", self.base(rec["id"]))
        policies = c.getresponse().msg.get_all("Content-Security-Policy")
        self.assertIn("sandbox", policies)  # opened alone it runs nothing at the panel's address
        self.assertTrue(any("default-src 'self'" in p for p in policies))  # and the panel's own policy still applies
        with mock.patch.object(M, "HTML_BYTES", 10):  # a page too large for a frame
            self.assertEqual({"kind": "html", "missing": "too_large"}, self.get(self.base(rec["id"]) + "/preview"))

    def test_a_picture_is_its_own_preview(self):
        png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000005" "0001e221bc330000000049454e44ae426082")  # a one-pixel PNG
        rec = self.add("화이트보드.png", png)
        self.assertEqual({"kind": "png", "view": "image"}, self.get(self.base(rec["id"]) + "/preview"))  # the page shows the file itself
        self.assertEqual("image/png", self.raw(self.base(rec["id"]))[1]["content-type"])


class OfficeFiles(Server):
    """A deck and a Word file shown page by page: LibreOffice prints them in the render container. The test runs where the
    render image of this Dockerfile is built (render/run.sh builds it on first use; a test never does)."""

    def setUp(self):
        if not render_image_built():  # the reference toolchain is not here
            self.skipTest("the render image of render/Dockerfile is not built on this PC (Docker missing, or render/run.sh not run yet)")
        p = mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "container", "OFFEROWL_CPUS": os.environ.get("OFFEROWL_CPUS", "4")})  # the container, as with Docker by default
        p.start()
        self.addCleanup(p.stop)

    def test_a_deck_and_a_word_file_show_their_pages(self):
        deck = self.add("감마 플랫폼 소개.pptx", pptx_bytes(["Gamma platform", "Order service", "Latency work"]))  # a fictional three-slide deck
        got = self.get(self.base(deck["id"]) + "/preview")
        self.assertEqual({"kind": "pptx", "view": "pages", "pages": 3, "of": 3, "more": False, "wide": True}, got)  # three slides, 16:9
        self.assertEqual(b"\x89PNG", self.raw(self.base(deck["id"]) + "/pages/3.png")[2][:4])  # the last slide's picture
        word = self.add("지원 동기.docx", docx_bytes("감마클라우드에 지원하는 이유"))  # a fictional Word answer
        self.assertEqual({"kind": "docx", "view": "pages", "pages": 1, "of": 1, "more": False, "wide": False}, self.get(self.base(word["id"]) + "/preview"))
        self.assertFalse(list((ROOT / "output" / "_materials").glob("*")) if (ROOT / "output" / "_materials").is_dir() else [])  # no copy of a person's file stays in the engine's folder
        self.assertEqual(deck["sha256"], hashlib.sha256(self.raw(self.base(deck["id"]))[2]).hexdigest())  # the deck itself unchanged by its preview


class Names(unittest.TestCase):
    def test_a_jpeg_is_a_picture_kept_as_jpg(self):
        self.assertEqual(("whiteboard", "jpg"), M.safe_name("whiteboard.jpeg"))  # a phone's photo
        self.assertEqual(("whiteboard", "jpg"), M.safe_name("whiteboard.JPG"))  # as before


class ConverterCommand(unittest.TestCase):
    """The command that prints a deck or a Word file, in each way the toolchain runs, checked without Docker or LibreOffice."""

    def command(self, local: bool, inside: bool, which: dict) -> tuple[list, str]:
        """(the command started, the answer) for a deck, with the renderer and the tools found stood in for."""
        import resume  # src/resume.py: the switches stood in for
        seen = []  # the commands started
        def fake_run(cmd, timeout):  # LibreOffice's stand-in: it writes the PDF where it was asked to
            seen.append((cmd, timeout))
            out = pathlib.Path(cmd[cmd.index("--outdir") + 1]) if "--outdir" in cmd else None  # this PC's soffice
            if out is None:  # the script: the folder is its first argument
                folder = cmd[-3]
                out = (ROOT / folder) if not os.path.isabs(folder) else pathlib.Path(folder)
            (out / "in.pdf").write_bytes(b"%PDF-1.4 stand-in")
            return 0, ""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(resume, "local", return_value=local), \
                mock.patch.object(resume, "in_container", return_value=inside), mock.patch.object(M.shutil, "which", side_effect=lambda n: which.get(n)), \
                mock.patch.object(M, "run", side_effect=fake_run):  # no Docker and no LibreOffice are started
            src = pathlib.Path(tmp) / "감마 덱.pptx"  # a person's file name with spaces and Hangul
            src.write_bytes(b"fictional")
            why = M.convert(src, pathlib.Path(tmp) / "doc.pdf")  # printed
            made = (pathlib.Path(tmp) / "doc.pdf").read_bytes() if (pathlib.Path(tmp) / "doc.pdf").is_file() else b""
        self.assertTrue(why or made.startswith(b"%PDF"))  # made, or said why not
        return [c for c, _ in seen], why

    def test_through_the_render_container(self):
        cmds, why = self.command(local=False, inside=False, which={"docker": "/usr/bin/docker"})  # Docker here: render/run.sh
        self.assertEqual("", why)  # made
        cmd = cmds[0]
        self.assertEqual(str(ROOT / "render" / "run.sh"), cmd[0])  # through the script that starts the container
        script = cmd[3]  # bash -c <script>
        self.assertIn("bash src/fonts.sh", script)  # the fonts first, as for a resume
        self.assertIn("timeout 180 soffice", script)  # never longer than three minutes
        self.assertIn("--convert-to pdf", script)
        self.assertTrue(cmd[5].startswith("output/_materials/") and cmd[6].endswith("/in.pptx"))  # a folder the container sees, a plain name
        self.assertNotIn("감마", " ".join(cmd))  # the person's file name never reaches a command line
        self.assertFalse(list((ROOT / "output" / "_materials").glob("*")) if (ROOT / "output" / "_materials").is_dir() else [])  # and its copy is gone again

    def test_inside_the_app_image_and_on_this_pc(self):
        cmds, why = self.command(local=True, inside=True, which={})  # the app image: LibreOffice is here
        self.assertEqual(("", "bash"), (why, cmds[0][0]))  # the same script, here
        cmds, why = self.command(local=True, inside=False, which={"soffice": "/opt/lo/soffice"})  # the browser renderer and this PC's LibreOffice
        self.assertEqual(("", "/opt/lo/soffice"), (why, cmds[0][0]))  # started as found
        self.assertTrue(any(a.startswith("-env:UserInstallation=file:") for a in cmds[0]))  # a profile of its own, so a LibreOffice open on the desktop is never in the way

    def test_no_tools_is_said(self):
        with mock.patch.object(M, "soffice_path", return_value=None):  # no LibreOffice anywhere on this PC
            self.assertEqual(([], "no_tools"), self.command(local=True, inside=False, which={}))  # the browser renderer, no LibreOffice
        self.assertEqual(([], "no_tools"), self.command(local=False, inside=False, which={}))  # the container renderer, no Docker

    def test_this_pcs_libreoffice_is_found_where_its_installer_puts_it(self):
        with tempfile.TemporaryDirectory() as tmp:  # a Program Files folder of its own
            exe = pathlib.Path(tmp) / "LibreOffice" / "program" / "soffice.exe"  # where the Windows installer puts it
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            with mock.patch.object(M.shutil, "which", return_value=None), mock.patch.dict(os.environ, {"ProgramFiles": tmp, "ProgramFiles(x86)": ""}):  # not on PATH, as Windows leaves it
                self.assertEqual(str(exe), M.soffice_path())  # found in its folder
            with mock.patch.object(M.shutil, "which", side_effect=lambda n: "/usr/bin/soffice" if n == "soffice" else None):  # on PATH
                self.assertEqual("/usr/bin/soffice", M.soffice_path())  # PATH comes first


class Markdown(unittest.TestCase):
    """The markdown reader on its own: what a person's notes hold, as plain words."""

    def test_inline_marks_go_and_code_spans_stay(self):
        self.assertEqual("bold link (http://x) code == x and 2 * 3", M.inline("**bold** [link](http://x) `code == x` and 2 * 3"))  # code as written, a lone star kept, a link's address kept for the panel to link
        self.assertEqual("a b (https://x.org/a_b_c) and https://y.org/d_e_", M.inline("*a* [b](https://x.org/a_b_c) and https://y.org/d_e_"))  # an address's underscores are not emphasis
        self.assertEqual("a & b", M.inline("<b>a</b> &amp; b"))  # tags out, entities as characters
        self.assertEqual("*not italic*", M.inline(r"\*not italic\*"))  # an escape is the character itself

    def test_headings_written_under_a_line_and_an_open_fence(self):
        blocks = M.md_blocks("Title\n=====\n\nPart\n---\n\n```\nleft open\n")  # the other heading form, and a fence never closed
        self.assertEqual([{"t": "h", "n": 1, "text": "Title"}, {"t": "h", "n": 2, "text": "Part"}, {"t": "code", "text": "left open"}], blocks)


if __name__ == "__main__":  # run as a script
    unittest.main(verbosity=2)  # each test's name as it runs
