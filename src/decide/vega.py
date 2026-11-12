# -*- coding: utf-8 -*-
"""Vega, the decision engine Laya's maker published after Laya, as a decision backend run on this PC.

Vega reads a state with a frozen language model (the reader: Qwen3.5-0.8B by default) and answers typed questions with
a small engine on top of it, so it reads Korean as well as its reader does. Every answer also says whether to trust
it: a conformal prediction set, an abstain flag, and a route, "auto" or "review". Unlike src/decide/laya.py, which
reads Laya's published files itself, this backend runs the maker's own package (vegaml, which comes with laya 0.4.23
or newer), so a person installs it: `pip install "laya>=0.4.23"`.

Nothing downloads unless a person runs `python3 src/decide/cli.py fetch vega` or sets OFFEROWL_VEGA_DOWNLOAD=1; the
files live in the Hugging Face cache, and the engine's repository is pinned to the revision that was measured.

Settings:
  OFFEROWL_VEGA_READER    the reader: empty for the default 0.8B, or what vegaml takes ("4b", a Hub repository, a folder)
  OFFEROWL_VEGA_DEVICE    cpu (default) or cuda
  OFFEROWL_VEGA_THREADS   CPU threads (default 4, as for Laya; the maker's advice of one thread for the Qwen3.5 readers
                          did not hold on the PC measured, where one thread took three times as long as eight for the
                          same 161 decisions, with the same answers)
  OFFEROWL_VEGA_DOWNLOAD  1 lets a missing reader or engine download once; without it only files on this PC are used
"""
import importlib.machinery  # find the maker's package without importing it
import os  # settings
import sys  # the import path, without this folder
import threading  # one load at a time when two callers ask together
import time  # load and decision times

ENGINE = ("nandakishorm/vega-U", "4d2050287982ca7a7bb0c22fd19a389f5f94474e")  # the engine's repository, at the revision measured
READERS = {"": "Qwen/Qwen3.5-0.8B", "4b": "Qwen/Qwen3.5-4B"}  # the readers of that repository this backend knows by name
NEEDS = ("laya", "vegaml", "torch", "transformers", "huggingface_hub")  # the packages a decision imports
_LOADED = {}  # reader name to (agent, load seconds), so a process loads each reader once
_LOCK = threading.Lock()  # one load at a time
HERE = os.path.dirname(os.path.abspath(__file__))  # src/decide: its laya.py is Offerowl's own and must never pass for the maker's


def outside_path() -> list:
    """The import path without this folder, where a top-level `laya` would be Offerowl's own laya.py."""
    return [p for p in sys.path if os.path.abspath(p or os.getcwd()) != HERE]


def setting(name: str, default: str = "") -> str:
    """OFFEROWL_<name>, else the default."""
    return os.environ.get("OFFEROWL_" + name, "").strip() or default


def reader() -> str:
    """The reader setting: "" for the default 0.8B."""
    return setting("VEGA_READER").lower() if setting("VEGA_READER").lower() in READERS else setting("VEGA_READER")


def name_of(r: str) -> str:
    """The reader's short name in a result's backend: vega:0.8b, vega:4b, or what was set."""
    return "0.8b" if not r else r


def missing_libs() -> list:
    """The packages that are not installed here, looked for outside this folder."""
    path = outside_path()  # never this folder's laya.py
    return [m for m in NEEDS if importlib.machinery.PathFinder.find_spec(m, path) is None]


def maker_laya():
    """The maker's laya package, imported with this folder off the path."""
    from decide import DecideUnavailable  # the shared failure
    have = sys.modules.get("laya")  # imported before, by whoever
    if have is not None and os.path.dirname(os.path.abspath(getattr(have, "__file__", None) or "")) == HERE:  # Offerowl's own file under that name
        raise DecideUnavailable("vega: `laya` in this process is src/decide/laya.py, not the maker's package")
    saved = sys.path[:]  # put back afterwards
    sys.path[:] = outside_path()  # the maker's package only
    try:
        import laya  # the maker's package
        return laya
    finally:
        sys.path[:] = saved


def present(r: str = "") -> bool:
    """Are the reader's engine file and the reader itself in the Hugging Face cache? Looks only, never downloads."""
    if r not in READERS:  # a repository or a folder of the person's own: vegaml checks it at load
        return True
    try:
        from huggingface_hub import try_to_load_from_cache  # a look into the cache, no network
    except ImportError:  # without the package nothing is present
        return False
    engine = "engine.safetensors" if not r else "Qwen3.5-4B/engine.safetensors"  # where the engine of that reader sits
    hits = [try_to_load_from_cache(ENGINE[0], engine, revision=ENGINE[1]), try_to_load_from_cache(READERS[r], "config.json")]
    return all(isinstance(h, str) for h in hits)  # a path for each; anything else means not cached


def status() -> dict:
    """Ready when the maker's package imports and the reader's files are on this PC."""
    libs = missing_libs()  # packages first: without them nothing else matters
    if libs:
        return {"ready": False, "why": f"needs {', '.join(libs)} (pip install \"laya>=0.4.23\")"}
    r = reader()  # the reader a decision would load
    if not present(r):  # not downloaded yet
        return {"ready": False, "why": f"reader {name_of(r)} is not on this PC; run `python3 src/decide/cli.py fetch vega`"}
    return {"ready": True, "why": ""}


def load(r: str, download: bool = False):
    """The agent for reader r, loaded once per process."""
    from decide import DecideUnavailable  # the shared failure
    with _LOCK:  # two callers never load twice
        if r in _LOADED:
            return _LOADED[r][0]
        libs = missing_libs()  # the maker's package and its runtime
        if libs:
            raise DecideUnavailable(f"vega needs {', '.join(libs)} (pip install \"laya>=0.4.23\")")
        allowed = download or setting("VEGA_DOWNLOAD") == "1"  # a download only when asked
        if not allowed and not present(r):  # say what to run instead of failing deep in the loader
            raise DecideUnavailable(f"vega reader {name_of(r)} is not on this PC; run `python3 src/decide/cli.py fetch vega`")
        import huggingface_hub.constants as hf  # the cache's own switch
        hf.HF_HUB_OFFLINE = not allowed  # files on this PC only: no update check leaves the PC either
        import torch  # the runtime vegaml uses
        torch.set_num_threads(max(1, int(setting("VEGA_THREADS", "4"))))  # before the reader loads
        laya = maker_laya()  # the maker's package, never this folder's laya.py
        t0 = time.time()  # load time
        try:
            agent = laya.Agent(vegaml=r or True, device=setting("VEGA_DEVICE", "cpu"),
                               revision=ENGINE[1] if r in READERS else None)  # pinned when the engine comes from the measured repository
        except Exception as e:  # noqa: BLE001  a missing file, a bad setting, a reader that will not load
            raise DecideUnavailable(f"vega reader {name_of(r)}: {type(e).__name__}: {str(e)[:300]}")
        _LOADED[r] = (agent, time.time() - t0)
        return agent


def fetch(r: str = "") -> float:
    """Download the reader and its engine on purpose; the seconds the load took."""
    load(r, download=True)  # the loader downloads what is missing
    return _LOADED[r][1]


def decide(task: str, items: list, reader_name: str | None = None, **_) -> list:
    """Vega's decision for each item: the question Laya gets and the item in one state, since Vega reads long states.
    The confidence is the chosen option's probability, as for Laya; the route, the abstain flag and the conformal set
    come along with each result."""
    from decide import DecideUnavailable, result  # the shared shape
    from decide.laya import question, whole_state  # the same question and readable field names
    r = reader() if reader_name is None else ("" if reader_name in ("", "0.8b") else reader_name)  # the reader to use
    agent = load(r)  # once per process
    q = question(task)  # choice over the task's labels
    out = []  # decisions in order
    for n, it in enumerate(items):  # one call per item
        t0 = time.time()  # the decision's time
        try:
            got = agent.predict(whole_state(task, it), {"decision": q})  # the one question about this item
        except Exception as e:  # noqa: BLE001  a state the reader cannot take
            raise DecideUnavailable(f"vega: {task} item {n + 1}: {type(e).__name__}: {str(e)[:300]}")
        ans = (got.get("answers") or {}).get("decision") or {}  # its answer
        label = ans.get("choice")  # the chosen option
        if label is None:  # not the shape the package documents
            raise DecideUnavailable(f"vega: no choice in the answer for {task} item {n + 1}")
        probs = {k: float(v) for k, v in (ans.get("probabilities") or {}).items()}  # each option's probability
        out.append(result(task, label, probs or None, f"vega:{name_of(r)}", (time.time() - t0) * 1000,
                          route=ans.get("route"), abstain=bool(ans.get("abstain")), prediction_set=ans.get("prediction_set")))
    return out
