"""Shared setup for the interview kit tests: the import path and the fictional example job."""
import pathlib  # paths
import shutil  # copies of the example
import sys  # the import path
import tempfile  # scratch folders

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
SRC = ROOT / "src"  # where the interview package and llm.py live
if str(SRC) not in sys.path:  # import interview.* and llm the way cli.py does
    sys.path.insert(0, str(SRC))  # at the front, so this checkout wins over an installed copy

# The tests call the commands' own main() and skip the entry point (cli.main), which makes the output UTF-8 before a command
# prints its Korean lines; done here instead, so a run with its output redirected on Windows (cp1252) reads the same.
from interview import cli as _cli  # noqa: E402  the path above is set
_cli.utf8_stdio()

EXAMPLE = ROOT / "examples" / "interview"  # the fictional workspace
JOB = EXAMPLE / "jobs" / "gamma-platform"  # its one job


def example_job(**kw):
    """The example job, read in place."""
    from interview.job import Job  # imported when first needed; the path above is already set
    return Job(JOB, **kw)  # the example job folder, with any overrides a test passes


def copy_workspace():
    """A temporary copy of the example workspace (for tests that change files); returns (tmp dir, job path)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-"))  # removed by the caller
    shutil.copytree(EXAMPLE, tmp / "interview")  # the workspace
    shutil.copy(ROOT / "examples" / "sample_ko.json", tmp / "sample_ko.json")  # the profile the kit points to (../sample_ko.json)
    return tmp, tmp / "interview" / "jobs" / "gamma-platform"  # the job inside the copy, where tests plant defects
