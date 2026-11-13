"""pytest's start for every test under tests/: the agent's call log goes to a temporary file of this run, not the engine's
own output/_llm/calls.jsonl, which the stand-in agent's calls would otherwise fill (sizes only, but they are not this PC's
calls). In unittest runs, tests/app/test_panel.py does the same for the panel's tests, and CI sets OFFEROWL_LLM_LOG for every job."""
import atexit  # the temporary folder goes when the run ends
import os  # the environment src/llm.py reads
import shutil  # the folder, removed
import sys  # a module already loaded
import tempfile  # the run's own place

_dir = tempfile.mkdtemp(prefix="offerowl-tests-log-")  # this run's
atexit.register(shutil.rmtree, _dir, True)  # gone afterwards, whatever happened
os.environ.setdefault("OFFEROWL_LLM_LOG", os.path.join(_dir, "calls.jsonl"))  # read by src/llm.py when it is first imported
if "llm" in sys.modules:  # imported before this file ran: point it there too
    from pathlib import Path  # its type
    sys.modules["llm"].LOG = Path(os.environ["OFFEROWL_LLM_LOG"])
