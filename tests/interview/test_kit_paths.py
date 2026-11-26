"""What a kit may read. kit.json can arrive with a restored backup, so the panel's kits (Job(confined=True)) read nothing
outside the workspace: not an absolute path, not one that climbs out with "..", not "~", not a link that leads out. A
source out there would be shown on the panel's own address, and a material read into the agent's prompts. The command
line's own kits are the person's, and keep naming files beside the workspace (the example's profile is ../sample_ko.json)."""
import json  # the kit file
import os  # links
import pathlib  # paths
import shutil  # the copy, removed
import sys  # the import path
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # helpers.py
import helpers  # noqa: E402  the import path and the example workspace
from interview import corpus  # noqa: E402  what the search view reads
from interview.job import Job  # noqa: E402  the kit's job folder


class ConfinedKit(unittest.TestCase):
    def setUp(self):
        self.tmp, self.job = helpers.copy_workspace()  # tmp/interview is the workspace; tmp/sample_ko.json lies beside it
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.outside = self.tmp / "outside"  # a folder of the same disk, out of the workspace
        self.outside.mkdir()
        (self.outside / "secret.md").write_text("### Q9. Outside\n\n- **핵심**: OUTSIDE-SECRET\n", encoding="utf-8")  # a scene file out there
        (self.outside / "secret.json").write_text('{"name": "OUTSIDE-SECRET"}', encoding="utf-8")
        kit_path = self.job / "interview" / "kit.json"  # as a backup would bring it
        kit = json.loads(kit_path.read_text(encoding="utf-8"))
        kit["sources"] = kit["sources"] + [{"file": str(self.outside / "secret.md"), "label": "a", "prefix": "X", "role": "scenes"},  # absolute
                                           {"file": "../../../../outside/secret.md", "label": "b", "prefix": "Y", "role": "scenes"}]  # climbing out
        kit["materials"] = ["../../../outside/*"]  # a job-relative pattern that climbs out
        kit["resume"] = "../../../outside/secret.md"  # a submitted document out there
        kit["alts"] = str(self.outside / "secret.json")  # the phrasings file out there
        kit_path.write_text(json.dumps(kit, ensure_ascii=False), encoding="utf-8")

    def test_the_panels_kit_reads_nothing_outside_the_workspace(self):
        job = Job(self.job, confined=True)  # as the panel reads it
        paths = [str(p) for p, _, _, _ in job.sources()]  # every source the search view reads
        self.assertFalse([p for p in paths if "outside" in p], paths)  # neither the absolute one nor the climbing one
        self.assertTrue(paths)  # the kit's own scenes are still read
        self.assertFalse([f for f in job.material_files() if "outside" in str(f)])  # nothing out there goes into a prompt
        self.assertIsNone(job.submitted("resume"))  # the named document is out of reach: none, never another file
        self.assertIsNone(job.alts_path())  # and so is the phrasings file
        self.assertIsNone(job.profile_path)  # the example's ../sample_ko.json lies outside the workspace too
        items, alts = corpus.load(job)  # what the search view and practice read
        self.assertNotIn("OUTSIDE-SECRET", json.dumps([items, alts], ensure_ascii=False))

    def test_a_link_out_of_the_workspace_is_refused_too(self):
        link = self.job / "interview" / "linked.md"  # a scene file inside that leads out
        try:
            os.symlink(self.outside / "secret.md", link)
        except (OSError, NotImplementedError):  # a system that refuses links (Windows without the right)
            self.skipTest("no symbolic links here")
        job = Job(self.job, confined=True)
        self.assertIsNone(job.in_interview("linked.md"))  # followed, it is outside

    def test_the_command_lines_kit_still_reads_files_beside_the_workspace(self):
        job = Job(self.job)  # the person's own kit, as `src/interview/cli.py` reads it
        self.assertEqual(self.tmp / "sample_ko.json", job.profile_path)  # ../sample_ko.json, as the example names it
        self.assertTrue([p for p, _, _, _ in job.sources() if "outside" in str(p)])  # it names them, so it reads them

    def test_paths_inside_the_workspace_still_work(self):
        job = Job(self.job, confined=True)
        self.assertEqual(job.workspace / "stories.md", job.stories_path)  # the workspace's own file
        self.assertTrue(job.in_job("interview/kit.json").is_file())  # the job's own



class PdfTextMemory(unittest.TestCase):
    """The text of a PDF is converted once per change of the file, and only the texts read last are kept: a panel runs for
    days, and every kit's PDFs, and every change of them, stayed in memory (D4-11)."""

    def setUp(self):
        import tempfile  # a folder of the test's own
        from unittest import mock  # the PDF reader, stood in for
        import pdftools  # src/pdftools.py: what converts a PDF
        from interview import job as J  # the cache under test
        self.J = J
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-pdftext-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.read = []  # the files converted
        for p in (mock.patch.object(pdftools, "reader", return_value="stand-in"),  # no reader needed
                  mock.patch.object(pdftools, "text", side_effect=lambda p, layout=True: self.read.append(p.name) or p.name),  # each conversion counted
                  mock.patch.object(J, "_PDF", J._PDF.__class__())):  # an empty cache of the same kind
            p.start()
            self.addCleanup(p.stop)

    def test_the_texts_read_last_are_kept_and_no_more(self):
        files = [self.tmp / f"doc-{i}.pdf" for i in range(self.J.PDF_KEEP + 8)]  # more PDFs than are kept
        for f in files:
            f.write_bytes(b"%PDF-1.4")
            self.assertEqual(f.name, self.J.read_text(f))
        self.assertEqual(self.J.PDF_KEEP, len(self.J._PDF))  # bounded (it kept every one)
        self.J.read_text(files[-1])  # the last one, read again: from memory
        self.assertEqual(len(files), len(self.read))
        self.J.read_text(files[0])  # the first went long ago: converted again
        self.assertEqual(len(files) + 1, len(self.read))
        files[-1].write_bytes(b"%PDF-1.4 changed")  # a file changed: its old text is never read again
        self.J.read_text(files[-1])
        self.assertEqual(1, sum(1 for k in self.J._PDF if k[0] == str(files[-1].resolve())))  # one text per file and layout


if __name__ == "__main__":
    unittest.main()
