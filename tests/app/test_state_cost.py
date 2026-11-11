"""What the panel's poll costs, on the fictional example: the state carries the facts' counts and a stamp, not their rows;
it comes with an ETag (an unchanged poll is a 304 with no body) and gzip for a client that asks; the hashes, the profile's
language and the deck source's stamp are worked out once per change, not once per poll; the panel's photo is a small copy.

    python3 -m unittest tests/app/test_state_cost.py -v
"""
import gzip  # the compressed state, unpacked
import hashlib  # the rows' stamp, worked out as the API does
import io  # a picture in memory
import json  # answers
import os  # file times
import pathlib  # paths
import sys  # the import path
import tempfile  # a scratch folder for the hash tests
import time  # file times
import unittest  # the runner
import urllib.error  # a 304 is raised by urllib
import urllib.request  # requests with their own headers
from unittest import mock  # counting the calls a cache saves

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "tests" / "app"))  # the shared test case
from apps.api import photo as P  # noqa: E402  the small copy
from apps.api import tasks as T  # noqa: E402  the hashes and their memory
from test_panel import PanelCase  # noqa: E402  one server and workspace per class, on the fictional example

try:  # the small copy needs Pillow (an optional extra); its tests are skipped without it
    from PIL import Image  # noqa: E402
except ImportError:  # pragma: no cover
    Image = None


def old(path: pathlib.Path) -> None:
    """Make a file look written a minute ago, past the window in which a stamp is not trusted (tasks.RACY_NS)."""
    t = time.time() - 60  # a minute back
    os.utime(path, (t, t))  # its times


class TestStateOnTheWire(PanelCase):
    """The state's size, its ETag and its compression, as a browser and as a tool ask for it."""

    def fetch(self, headers=None, method="GET"):  # (status, headers, body) of the state, a 304 included
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/state", headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:  # a hung server fails the test
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:  # urllib raises on a 304
            return e.code, e.headers, e.read()

    def test_the_state_carries_counts_and_a_stamp_not_the_rows(self):
        self.start_profile()  # the example read: 31 facts to confirm
        st = self.get("/api/v1/state")  # as the page polls it
        self.assertEqual({"counts", "rev"}, set(st["facts"]))  # no rows in the poll
        self.assertEqual(31, st["facts"]["counts"]["found"])  # the counts are still there
        rows = self.get("/api/v1/facts")["rows"]  # the rows the profile view reads instead
        self.assertEqual(31, len(rows))
        stamp = hashlib.sha1(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]  # as the API works it out
        self.assertEqual(stamp, st["facts"]["rev"])  # the stamp names exactly those rows
        self.post("/api/v1/facts/decide", {"cid": rows[0]["cid"], "action": "edit", "fields": {"title": "Another title"}})  # one fact's words changed
        self.assertNotEqual(stamp, self.get("/api/v1/state")["facts"]["rev"])  # the stamp follows: the profile view reads the rows again

    def test_an_unchanged_poll_is_a_304_with_no_body(self):
        code, h, body = self.fetch()  # the first poll
        self.assertEqual(200, code)
        tag = h["ETag"]  # the state's tag
        self.assertTrue(tag.startswith('W/"'), tag)  # weak: the same tag compressed or not
        code, h2, body2 = self.fetch({"If-None-Match": tag})  # the next poll, nothing changed
        self.assertEqual(304, code)
        self.assertEqual(b"", body2)  # no body at all
        self.assertEqual(tag, h2["ETag"])  # the tag it holds
        self.assertEqual(304, self.fetch({"If-None-Match": f'"other", {tag}'})[0])  # one of several tags matches too
        self.post("/api/v1/onboarding", {"step": "files"})  # something changed
        code, h3, body3 = self.fetch({"If-None-Match": tag})  # the old tag
        self.assertEqual(200, code)  # the whole new state
        self.assertNotEqual(tag, h3["ETag"])  # under a new tag
        self.assertEqual("files", json.loads(body3)["onboarding"]["step"])  # with the change
        self.assertEqual(200, self.fetch({"If-None-Match": tag}, method="HEAD")[0])  # HEAD answers the same headers

    def test_gzip_only_for_a_client_that_asks(self):
        code, h, plain = self.fetch()  # a tool: urllib names no coding
        self.assertIsNone(h.get("Content-Encoding"))  # plain bytes
        json.loads(plain)  # readable as they are
        code, h, packed = self.fetch({"Accept-Encoding": "gzip, deflate, br"})  # as a browser asks
        self.assertEqual("gzip", h["Content-Encoding"])
        self.assertEqual("Accept-Encoding", h["Vary"])  # the bytes depend on the coding asked for
        self.assertEqual(len(packed), int(h["Content-Length"]))  # the length is the compressed one
        self.assertEqual(json.loads(plain), json.loads(gzip.decompress(packed)))  # the same state
        self.assertLess(len(packed), len(plain))  # smaller
        self.assertIsNone(self.fetch({"Accept-Encoding": "gzip;q=0, identity"})[1].get("Content-Encoding"))  # refused with q=0: plain
        self.assertEqual("gzip", self.fetch({"Accept-Encoding": "*"})[1].get("Content-Encoding"))  # any coding: gzip


class TestHashMemory(unittest.TestCase):
    """file_hash and content_hash read a file once per version of it."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-hash-"))  # a scratch folder
        T._hash_cache.clear()  # no memory from another test

    def tearDown(self):
        import shutil  # only here
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_an_unchanged_file_is_read_once_and_a_changed_one_again(self):
        f = self.dir / "a.json"  # a JSON file, written as the workspace writes (a rename)
        T.write_json(f, {"a": 1})
        old(f)  # past the racy window
        first = T.file_hash(f), T.content_hash(f)  # read and remembered
        with mock.patch.object(pathlib.Path, "read_bytes", side_effect=AssertionError("read again")), \
             mock.patch.object(pathlib.Path, "read_text", side_effect=AssertionError("read again")):
            self.assertEqual(first, (T.file_hash(f), T.content_hash(f)))  # from memory: the file is not opened
        T.write_json(f, {"a": 2})  # the same size, a new version
        old(f)  # even with an old time: the rename gave it a new inode
        self.assertNotEqual(first, (T.file_hash(f), T.content_hash(f)))  # worked out again

    def test_a_file_written_just_now_is_never_remembered(self):
        f = self.dir / "b.bin"
        f.write_bytes(b"one")  # now: its stamp cannot be trusted yet
        self.assertEqual(T._file_hash(f), T.file_hash(f))
        self.assertEqual({}, T._hash_cache)  # nothing kept
        self.assertEqual("", T.file_hash(self.dir / "missing"))  # a missing file is still ""
        self.assertEqual("", T.content_hash(self.dir / "missing"))


class TestPollWork(PanelCase):
    """One state works out the profile's language and the deck source's stamp at most once, and later states not again."""

    def test_language_and_deck_stamp_once(self):
        self.start_profile()  # the example: a Korean profile
        api = self.srv.RequestHandlerClass.router.api  # the API object behind the server
        deck = api.ws.path("deck")  # a deck source, as a person keeps one
        deck.mkdir(parents=True, exist_ok=True)
        (deck / "build.js").write_text("// a deck\n", encoding="utf-8")
        for f in [api.ws.path("profile", "profile.json"), deck / "build.js"]:
            old(f)  # past the racy window, so they may be remembered
        api.tasks._lang = (None, "")  # nothing remembered yet
        self.assertEqual("ko", api.tasks.profile_lang())  # worked out once
        with mock.patch.object(api.facts, "profile", wraps=api.facts.profile) as prof, \
             mock.patch.object(type(api.tasks), "_deck_stamp_now", autospec=True, side_effect=T.Tasks._deck_stamp_now) as walk:
            st = api.state()  # one poll
            self.assertEqual("ko", st["profile_lang"])
            self.assertLessEqual(walk.call_count, 1)  # the deck folder is looked at once, not once per edition
            n = prof.call_count  # the reads of the profile the state itself makes
            self.assertEqual("ko", api.tasks.profile_lang())  # asked again
            self.assertEqual(n, prof.call_count)  # no read for the language: remembered while the file is unchanged
        with mock.patch.object(type(api.tasks), "_deck_stamp_now", autospec=True, side_effect=T.Tasks._deck_stamp_now) as walk:
            with api.tasks.one_read():  # one read of the state, as App.state opens it
                stamps = {api.tasks.deck_stamp() for _ in range(5)}  # once per edition
                with api.tasks.one_read():  # a nested read shares the memo
                    stamps.add(api.tasks.deck_stamp())
            self.assertEqual(1, walk.call_count)  # the folder looked at once
            self.assertEqual(1, len(stamps))  # one stamp, not empty: the source is there
            self.assertNotEqual({""}, stamps)
            api.tasks.deck_stamp()  # outside a read: the folder as it is now
            self.assertEqual(2, walk.call_count)
        api.facts.rebuild()  # the profile written again
        old(api.ws.path("profile", "profile.json"))
        with mock.patch.object(api.facts, "profile", wraps=api.facts.profile) as prof:
            self.assertEqual("ko", api.tasks.profile_lang())
            self.assertEqual(1, prof.call_count)  # a new file: read again


@unittest.skipIf(Image is None, "Pillow is not installed")
class TestPhotoThumbnail(PanelCase):
    """The panel's photo is a small copy; the kept file, which every document is made from, stays as it was."""

    def test_small_copy_and_the_original(self):
        buf = io.BytesIO()  # a plain 3:4 picture drawn here (no one's face)
        Image.new("RGB", (600, 800), (120, 150, 180)).save(buf, "PNG")
        png = buf.getvalue()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/photo", data=png, method="POST",
                                     headers={"Content-Type": "application/octet-stream", "X-File-Name": "photo.png"})
        urllib.request.urlopen(req, timeout=20).read()  # kept as the resume's photo
        ctype, small = self.raw_get("/api/v1/photo?v=1&w=240")  # what the panel draws
        self.assertEqual("image/jpeg", ctype)
        im = Image.open(io.BytesIO(small))
        self.assertEqual((240, 320), im.size)  # the width asked for, the shape kept
        self.assertLess(len(small), len(png))
        ctype, full = self.raw_get("/api/v1/photo")  # the photo itself
        self.assertEqual("image/png", ctype)
        self.assertEqual(Image.open(io.BytesIO(full)).size, (600, 800))  # untouched
        self.assertEqual((P.THUMB_MAX, P.THUMB_MAX * 4 // 3), Image.open(io.BytesIO(self.raw_get("/api/v1/photo?w=4000")[1])).size)  # a width past the cap: the cap
        self.assertEqual("image/png", self.raw_get("/api/v1/photo?w=x")[0])  # not a width: the photo itself

    def test_only_a_photo_s_two_kinds_reach_a_decoder(self):
        """A small copy is decoded from a JPEG or a PNG only: bytes of any other kind (a BMP here, as if a file held something
        other than its name says) reach none of Pillow's other decoders, and the original is sent as it is."""
        for kind in ("JPEG", "PNG"):  # the two kinds a photo is kept in
            buf = io.BytesIO()
            Image.new("RGB", (600, 800), (120, 150, 180)).save(buf, kind)
            self.assertIsNotNone(P._make_thumbnail(buf.getvalue(), 240), kind)  # a small copy
        buf = io.BytesIO()
        Image.new("RGB", (600, 800), (120, 150, 180)).save(buf, "BMP")  # a kind Pillow reads, but no photo is kept in
        self.assertIsNone(P._make_thumbnail(buf.getvalue(), 240))  # not decoded: the original goes as it is


if __name__ == "__main__":
    unittest.main()
