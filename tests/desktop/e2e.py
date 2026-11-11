#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The one-file app, end to end, on a PC with no Docker, no Node.js, no Python and no poppler: start the built file in a
clean environment with a temporary home, make the example person's resume, deck and cover letter through the panel's HTTP
API the way the panel does, stop it, start it again, and keep the files.

  python3 tests/desktop/e2e.py --app dist/Offerowl-linux-x64 --out <folder>
  python3 tests/desktop/e2e.py --app dist/Offerowl-linux-x64 --out <folder> --poppler   # with poppler on the PATH too
  python3 tests/desktop/e2e.py compare --run <folder> --repo <checkout with node_modules> # the container build of the same inputs

What it checks, each printed as `ok`, `FAIL` or `note` (the last line is `e2e: N checks, M failed`):
  - the environment has no docker, no node, no python and no poppler on PATH, and the app still starts;
  - the first start unpacks Node.js into the data folder, the second start does not;
  - the resume, the deck and the cover letter are typeset (PDF files, page counts, page pictures);
  - the app reads an old PDF, as it must to take a person's files;
  - the app's temporary folder is gone after it stops.
The cover letter is drafted by a small stand-in model server that answers from the example letter, so no real model is
called. `compare` builds the same profile and settings with the render container and compares page counts and text.
"""
import argparse  # the command line
import json  # API bodies and the report
import os  # environment, paths
import pathlib  # paths
import re  # the cover prompts
import shutil  # copies, which
import signal  # stopping the app
import socket  # a free port
import subprocess  # the app, poppler, the container build
import sys  # exit code
import tempfile  # the temporary home
import threading  # the stand-in model server
import time  # waiting
import urllib.error  # API refusals
import urllib.parse  # job ids in paths
import urllib.request  # the API

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps.api.standin is imported from here
RESULTS: list = []  # (name, ok, detail) of every check


def check(name: str, ok: bool, detail: str = "") -> bool:  # one line per check, printed at once so a hang leaves what was done
    RESULTS.append((name, bool(ok), detail))
    print(("ok   " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)
    return bool(ok)


def note(text: str) -> None:  # information that is not a pass or a fail
    print("note " + text, flush=True)


def free_port() -> int:  # the app must not collide with a panel that is running
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- the clean environment


def tools_folder(tmp: pathlib.Path, poppler: bool) -> pathlib.Path:
    """A folder that is the whole PATH of the app: Chrome and (when poppler is True) poppler's three programs, as links.
    No docker, no node, no python."""
    d = tmp / "tools"
    d.mkdir()
    chrome = next((p for p in ("/opt/google/chrome/chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser") if os.path.isfile(p)), None)
    if chrome:  # the browser the renderer finds by its name on PATH
        (d / "google-chrome").symlink_to(chrome)
    if poppler:  # the programs the page pictures and the checks use
        for name in ("pdftoppm", "pdftotext", "pdfinfo"):
            found = shutil.which(name)
            if found:
                (d / name).symlink_to(found)
    return d


def clean_env(home: pathlib.Path, tools: pathlib.Path, tmp: pathlib.Path) -> dict:
    """The app's whole environment: a temporary home, a PATH of one folder, a private temporary folder, no model."""
    (tmp / "tmp").mkdir(exist_ok=True)
    return {"HOME": str(home), "PATH": str(tools), "LANG": "C.UTF-8", "TMPDIR": str(tmp / "tmp"), "USER": "tester",
            "OFFEROWL_PANEL_BACKEND": "none", "OFFEROWL_LANG": "en"}


# ---------------------------------------------------------------- the API, as the panel calls it


class Api:
    """Reads and writes against the panel's address, with the headers the page sends."""

    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no proxy for a local address

    def get(self, path: str, raw: bool = False, timeout: float = 30):
        with self.opener.open(self.base + path, timeout=timeout) as r:
            body = r.read()
            return body if raw else json.loads(body)

    def post(self, path: str, body: dict, timeout: float = 120):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Origin": self.base})
        with self.opener.open(req, timeout=timeout) as r:
            return json.loads(r.read())

    def wait(self, key: str, timeout: float = 300) -> dict:
        """The task's record once it ends, polled the way the page polls the state."""
        end = time.time() + timeout
        while time.time() < end:
            task = self.get("/api/v1/state")["tasks"].get(key) or {}
            if task.get("state") in ("done", "error"):
                return task
            time.sleep(0.3)
        return {"state": "timeout"}


class App:
    """The built file, started with the clean environment."""

    def __init__(self, exe: pathlib.Path, env: dict, home: pathlib.Path, port: int, log: pathlib.Path):
        self.exe, self.env, self.home, self.port, self.log = exe, env, home, port, log
        self.proc = None
        self.started = 0.0

    def start(self) -> float:
        """Start it and wait for /health; returns the seconds that took."""
        out = open(self.log, "ab")
        self.started = time.time()
        self.proc = subprocess.Popen([str(self.exe), "--no-browser", "--no-tray", "--port", str(self.port)], env=self.env, cwd=self.home,
                                     stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        end = time.time() + 180
        while time.time() < end and self.proc.poll() is None:
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if json.loads(r.read()).get("ok"):
                        return time.time() - self.started
            except (OSError, ValueError):
                time.sleep(0.2)
        raise RuntimeError("the app did not answer /health")

    def stop(self) -> float:
        """SIGTERM, as a logout or a service manager sends it; returns the seconds until the process was gone."""
        t = time.time()
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        return time.time() - t


# ---------------------------------------------------------------- the stand-in model for the cover letter


def cover_stub():
    """A model server that answers the cover letter's calls from the example letter, so the panel's cover step runs with
    no real model: the plan falls back to word matching, and the draft is the example's sentences, placed by paragraph kind."""
    from apps.api import standin  # the OpenAI-compatible stand-in of the tests and the app check
    letter = json.loads((ROOT / "examples" / "cover" / "cover_ko.json").read_text(encoding="utf-8"))
    pools = {}  # example sentences by paragraph kind, in the letter's order
    for p in letter["paragraphs"]:
        pools.setdefault(p["kind"], []).append(p["sentences"])
    used = {}  # how many paragraphs of a kind were handed out
    usual = standin.answer  # the stand-in's own rules, kept before the line below replaces them

    def answer(prompt: str) -> str:
        if prompt.startswith("You write the body of a cover letter"):  # cover-draft
            paras = []
            for m in re.finditer(r"^(\w+) \((opening|motivation|duties|closing)\):", prompt, re.M):
                kind = m.group(2)
                i = used.get(kind, 0)
                used[kind] = i + 1
                options = pools.get(kind) or [[]]
                paras.append({"id": m.group(1), "sentences": [dict(s, duties=[]) for s in options[i % len(options)]]})
            return json.dumps({"paragraphs": paras}, ensure_ascii=False)
        if prompt.startswith("You rewrite") or "cover_repair" in prompt or prompt.startswith("Some sentences"):  # cover-repair
            return json.dumps({"paragraphs": []})
        return usual(prompt)  # the other calls: the usual stand-in rules ('error' for what it does not know, so the plan uses words)
    standin.answer = answer  # the handler looks the function up in its module at each call
    return standin.serve(0)


# ---------------------------------------------------------------- the run


def pdf_pages(path: pathlib.Path) -> int:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else -1


def run(args) -> int:
    exe = pathlib.Path(args.app).resolve()
    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-e2e-"))  # the private world of the app: home, tools, temporary folder
    home = tmp / "home"
    home.mkdir()
    tools = tools_folder(tmp, poppler=args.poppler)
    env = clean_env(home, tools, tmp)
    check("the PATH holds no docker, node or python", not any(shutil.which(n, path=str(tools)) for n in ("docker", "node", "python3", "python")), str(sorted(p.name for p in tools.iterdir())))
    check("poppler is on the PATH only when asked for", bool(shutil.which("pdftotext", path=str(tools))) == bool(args.poppler))
    check("the app is one file", exe.is_file(), f"{exe.stat().st_size / 1e6:.1f} MB")
    port = free_port()
    app = App(exe, env, home, port, out / "app-stdout.log")
    data = home / ".local" / "share" / "offerowl"  # the default data folder under the temporary home
    stub = None
    try:
        first = app.start()
        check("the first start answers /health", True, f"{first:.1f} s with the unpack")
        node_dir = data / "runtime"
        found = sorted(p.name for p in node_dir.glob("node-*")) if node_dir.is_dir() else []
        check("the first start unpacked Node.js into the data folder", len(found) == 1 and (node_dir / found[0] / "node").is_file(), ", ".join(found))
        api = Api(port)
        # 1. the first run's main path: the example person, all facts kept
        api.post("/api/v1/example", {})
        check("the example is read", api.wait("ingest", 60).get("state") == "done")
        api.post("/api/v1/facts/keep-all", {})
        state = api.get("/api/v1/state")
        check("nothing stops a resume", state["problems"] == [], str(state["problems"]))
        # 2. a job from the fictional posting
        posting = (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")
        job = api.post("/api/v1/jobs", {"company": "델타페이", "role": "백엔드 플랫폼 엔지니어", "posting": posting})["job"]
        check("the posting is analysed", api.wait(f"analyze:{job}", 60).get("state") == "done")
        jq = urllib.parse.quote(job)
        # 3. the resume and the deck: "Make PDFs"
        t0 = time.time()
        api.post("/api/v1/jobs/build", {"job": job, "lang": "ko", "theme": "navy", "maxPages": 3, "cover": False})
        task = api.wait(f"build:{job}", 300)
        took = time.time() - t0
        note(f"Make PDFs (resume and deck) took {took:.1f} s: {json.dumps(task, ensure_ascii=False)[:400]}")
        check("Make PDFs ends done", task.get("state") == "done", json.dumps(task, ensure_ascii=False)[:300])
        res = task.get("result") or {}
        check("the resume is 2 pages", res.get("pages") == 2, str(res.get("pages")))
        check("the deck is 6 slides", res.get("slides") == 6, str(res.get("slides")))
        check("the checks found no defect", res.get("issues") == 0, str(res.get("issues")))
        # the deck's tab: its slides as they will print, drawn by the Node.js this app carries
        live = api.get(f"/api/v1/jobs/{jq}/deck/ko", timeout=120)  # the page the canvas's frame shows
        check("the live deck has its slides", live.get("slides") == 6 and "file://" not in live.get("html", ""), str({k: v for k, v in live.items() if k != "html"})[:200])
        api.post("/api/v1/settings", {"form": "table", "deck_style": "clean"})  # another form and the light deck, typeset by this app's own Node.js and the browser
        api.post("/api/v1/jobs/build", {"job": job, "lang": "ko", "theme": "wine", "maxPages": 3, "cover": False})  # made again
        other = api.wait(f"build:{job}", 300)  # until it ends
        check("the table form and the light deck in wine are made", other.get("state") == "done" and (other.get("result") or {}).get("issues") == 0, json.dumps(other, ensure_ascii=False)[:300])
        api.post("/api/v1/settings", {"form": "compact", "deck_style": "classic"})  # one column
        api.post("/api/v1/jobs/build", {"job": job, "lang": "ko", "theme": "navy", "maxPages": 3, "cover": False})  # made again
        other = api.wait(f"build:{job}", 300)  # until it ends
        check("the one-column form is made", other.get("state") == "done" and (other.get("result") or {}).get("issues") == 0, json.dumps(other, ensure_ascii=False)[:300])
        api.post("/api/v1/settings", {"form": "detailed"})  # as it was
        api.post("/api/v1/jobs/build", {"job": job, "lang": "ko", "theme": "navy", "maxPages": 3, "cover": False})  # for what follows
        api.wait(f"build:{job}", 300)  # until it ends
        plain = api.get(f"/api/v1/jobs/{jq}/files/ko/resume.txt", raw=True).decode("utf-8")  # the words for a job site that reads a file by itself
        check("the plain resume has the name and a project", "홍길동" in plain and "Kafka" in plain, plain[:120])
        for name in ("resume.pdf", "deck.pdf"):
            try:
                data_bytes = api.get(f"/api/v1/jobs/{jq}/files/ko/{name}", raw=True)
                (out / name).write_bytes(data_bytes)
                check(f"{name} comes through the API", data_bytes[:5] == b"%PDF-", f"{len(data_bytes) // 1024} KiB, {pdf_pages(out / name)} pages")
            except urllib.error.URLError as exc:
                check(f"{name} comes through the API", False, str(exc))
        for name in ("preview/r-1.png", "preview/d-1.png"):
            try:
                png = api.get(f"/api/v1/jobs/{jq}/files/ko/{name}", raw=True)
                (out / name.replace("/", "-")).write_bytes(png)
                check(f"{name} comes through the API", png[:4] == b"\x89PNG", f"{len(png) // 1024} KiB")
            except urllib.error.URLError as exc:
                check(f"{name} comes through the API", False, str(exc))
        # An old PDF, as a person's files are: the app must read it with what it carries
        read = subprocess.run([str(exe), str(ROOT / "tests" / "desktop" / "fixtures" / "read_pdf.py"), str(out / "resume.pdf")], env=env, cwd=home, capture_output=True, text=True, encoding="utf-8", timeout=120)
        check("the app reads a PDF's text, with no poppler when none is there", read.returncode == 0 and "홍길동" in read.stdout and ("pdfium" in read.stdout or args.poppler), (read.stdout + read.stderr).strip()[:200])
        # 4. the cover letter: written by tailoring, as the panel's button does, with the stand-in model, and typeset by the app.
        # Make PDFs alone asks no agent, so it typesets a letter only once one is written
        stub = cover_stub()
        api.post("/api/v1/settings", {"backend": "openai-compat", "llm_url": f"http://127.0.0.1:{stub.server_address[1]}", "llm_model": "standin"})
        t0 = time.time()
        api.post("/api/v1/jobs/tailor", {"job": job, "lang": "ko", "theme": "navy", "maxPages": 3, "cover": True, "typeset": True})
        task = api.wait(f"tailor:{job}", 600)
        note(f"Tailoring with the cover letter took {time.time() - t0:.1f} s: {json.dumps(task, ensure_ascii=False)[:400]}")
        check("tailoring wrote and typeset the letter", (task.get("parts") or {}).get("cover") == "done", json.dumps(task.get("parts"), ensure_ascii=False))
        edition = next((j for j in api.get("/api/v1/state")["jobs"] if j["id"] == job), {})
        note("the job's edition: " + json.dumps(edition.get("editions") or edition.get("edition") or {}, ensure_ascii=False)[:500])
        try:
            letter = api.get(f"/api/v1/jobs/{jq}/files/ko/cover.pdf", raw=True)
            (out / "cover.pdf").write_bytes(letter)
            check("cover.pdf comes through the API", letter[:5] == b"%PDF-", f"{len(letter) // 1024} KiB, {pdf_pages(out / 'cover.pdf')} pages")
            check("the cover letter is one page", pdf_pages(out / "cover.pdf") == 1)
        except urllib.error.URLError as exc:
            check("cover.pdf comes through the API", False, str(exc))
        # 5. keep the inputs the container build needs, and the app's own log
        edition_dir = data / "workspace" / "jobs" / job / "resume" / "ko"
        for name in ("profile.json", "job.json", "build.json"):
            if (edition_dir / name).is_file():
                shutil.copyfile(edition_dir / name, out / name)
        cdir = edition_dir / "cover"
        for name in ("cover.json", "job.json", "plan.json", "check.json"):
            if (cdir / name).is_file():
                shutil.copyfile(cdir / name, out / f"cover-{name}")
        shutil.copyfile(pathlib.Path(__file__).resolve().parents[2] / "examples" / "cover" / "posting_ko.md", out / "posting.md")
    finally:
        if stub:
            stub.shutdown()
        stopped = app.stop()
    check("the app stops on SIGTERM", app.proc.poll() is not None, f"{stopped:.1f} s")
    leftovers = [p.name for p in (tmp / "tmp").iterdir()]
    check("the app's temporary folder is gone after it stops", not [n for n in leftovers if n.startswith("_MEI")], str(leftovers))
    if (data / "logs" / "app.log").is_file():
        shutil.copyfile(data / "logs" / "app.log", out / "app.log")
        shutil.copyfile(data / "logs" / "panel.log", out / "panel.log") if (data / "logs" / "panel.log").is_file() else None
    log_text = (data / "logs" / "app.log").read_text(encoding="utf-8") if (data / "logs" / "app.log").is_file() else ""
    check("the first start logged the unpack", "unpacking Node.js" in log_text)
    # 6. the second start: Node.js is there, nothing is unpacked
    app2 = App(exe, env, home, free_port(), out / "app-stdout.log")
    try:
        second = app2.start()
        check("the second start answers /health", True, f"{second:.1f} s, the first took {first:.1f} s")
        log2 = (data / "logs" / "app.log").read_text(encoding="utf-8")
        starts = [i for i in range(len(log2)) if log2.startswith("unpacking Node.js", i)]
        check("the second start did not unpack again", len(starts) == 1, f"{len(starts)} unpack lines in the log")
    finally:
        app2.stop()
    runtime_size = sum(f.stat().st_size for f in (data / "runtime").rglob("*") if f.is_file()) if (data / "runtime").is_dir() else 0
    note(f"the data folder's runtime/ holds {runtime_size / 1e6:.1f} MB")
    (out / "e2e.json").write_text(json.dumps({"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in RESULTS], "first_start_s": first,
                                              "second_start_s": second, "runtime_mb": round(runtime_size / 1e6, 1), "app_mb": round(exe.stat().st_size / 1e6, 1)},
                                             ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    print(f"e2e: {len(RESULTS)} checks, {len(failed)} failed")
    return 1 if failed else 0


# ---------------------------------------------------------------- the container build of the same inputs


def compare(args) -> int:
    """Build the profile and settings of a run with the render container, and compare each PDF with the app's."""
    run_dir = pathlib.Path(args.run).resolve()
    repo = pathlib.Path(args.repo).resolve()
    pairs = []  # (name, container pdf, app pdf)
    env = {**os.environ, "OFFEROWL_RENDERER": "container", "OFFEROWL_LANG": "en", "OFFEROWL_CPUS": "6", "OFFEROWL_LLM": "none"}
    prof, job = run_dir / "profile.json", run_dir / "job.json"
    name = json.loads(job.read_text(encoding="utf-8"))["out"]
    r = subprocess.run(["nice", "-n", "15", sys.executable, "src/resume.py", "build", str(prof), str(job)], cwd=repo, env=env, capture_output=True, text=True, timeout=900)
    note("container resume build: " + (r.stdout + r.stderr).strip().splitlines()[-1][:200] if (r.stdout + r.stderr).strip() else "container resume build: no output")
    pairs += [("resume", repo / "output" / f"{name}.pdf", run_dir / "resume.pdf"), ("deck", repo / "output" / f"{name}_deck.pdf", run_dir / "deck.pdf")]
    if (run_dir / "cover-cover.json").is_file():
        r = subprocess.run(["nice", "-n", "15", sys.executable, "src/cover.py", "build", str(prof), str(run_dir / "cover-cover.json"), "--job", str(run_dir / "cover-job.json"),
                            "--dest", str(repo / "output" / "_cmp_cover")], cwd=repo, env=env, capture_output=True, text=True, timeout=900)
        note("container cover build: " + ((r.stdout + r.stderr).strip().splitlines() or ["no output"])[-1][:200])
        pairs.append(("cover", repo / "output" / "_cmp_cover" / "cover-cover.pdf", run_dir / "cover.pdf"))  # --dest names the copy after the cover file
    rows = []
    for label, old, new in pairs:
        if not old.is_file() or not new.is_file():
            check(f"{label}: both PDFs exist", False, f"container {old.is_file()}, app {new.is_file()}")
            continue
        shutil.copyfile(old, run_dir / f"container-{label}.pdf")
        c = subprocess.run([sys.executable, str(ROOT / "tests" / "render" / "compare.py"), str(old), str(new), "--diff", "--json", str(run_dir / f"compare-{label}.json")],
                           capture_output=True, text=True, timeout=600)
        last = (c.stdout.strip().splitlines() or [""])[-1]
        res = json.loads((run_dir / f"compare-{label}.json").read_text(encoding="utf-8")) if (run_dir / f"compare-{label}.json").is_file() else {}
        # the text layers, line by line, as pdftotext prints them
        t_old = subprocess.run(["pdftotext", "-layout", str(old), "-"], capture_output=True, text=True).stdout
        t_new = subprocess.run(["pdftotext", "-layout", str(new), "-"], capture_output=True, text=True).stdout
        norm = lambda t: sorted(" ".join(line.split()) for line in t.splitlines() if line.strip())
        same_lines = norm(t_old) == norm(t_new)
        rows.append({"document": label, "pages_container": pdf_pages(old), "pages_app": pdf_pages(new), "compare": last, "same_lines": same_lines})
        check(f"{label}: same page count", pdf_pages(old) == pdf_pages(new), f"container {pdf_pages(old)}, app {pdf_pages(new)}")
        check(f"{label}: same text lines", same_lines, last)
    (run_dir / "compare.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [r for r in RESULTS if not r[1]]
    print(f"compare: {len(RESULTS)} checks, {len(failed)} failed")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", default="run", choices=("run", "compare"))
    ap.add_argument("--app", help="the built file (run)")
    ap.add_argument("--out", help="folder for the PDFs, pictures, logs and e2e.json (run)")
    ap.add_argument("--poppler", action="store_true", help="put poppler on the PATH too, as some PCs have it (run)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary home (run)")
    ap.add_argument("--run", help="a folder written by `run` (compare)")
    ap.add_argument("--repo", help="a checkout with node_modules, where the container builds (compare)")
    args = ap.parse_args()
    return run(args) if args.mode == "run" else compare(args)


if __name__ == "__main__":
    sys.exit(main())
