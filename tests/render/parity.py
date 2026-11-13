#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parity gate of the browser renderer (docs/ARCHITECTURE.md): build the fictional examples with both renderers and compare
every page.

  python3 tests/render/parity.py [--container] [--typesetter-only] [--md FILE] [--keep]

For each example it builds the resume, the deck and (for the cover examples) the cover letter twice:
  - container: OFFEROWL_RENDERER=container, LibreOffice and Chromium in the render container (needs Docker);
  - html: OFFEROWL_RENDERER=html, the PC's own Chrome or Edge, no Docker.
Outputs get their own names (parity_ct_*, parity_html_*), so the usual outputs in output/ are never overwritten.
Without --container the container's PDFs of an earlier run with --container are reused.
--typesetter-only converts the container's own DOCX with the browser renderer instead of building it again on the host,
which separates the typesetter from the figure and DOCX writers.

The last line reads `parity: N documents, P pages, worst page X.XX% strict / Y.YY% within 1px, text same|differs`.
Exit code 0 when every document has the same page count and the same lines, else 1.
"""
import argparse  # command line
import json  # job files
import os  # environment of the builds
import pathlib  # paths
import shutil  # removing outputs
import subprocess  # the builds
import sys  # exit code

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository root
sys.path.insert(0, str(ROOT / "tests" / "render"))  # compare.py
sys.path.insert(0, str(ROOT / "src" / "render_html"))  # the renderer
import compare  # noqa: E402  page comparison
import render as R  # noqa: E402  DOCX to PDF in the browser

EX = ROOT / "examples"
# (name, profile, job file or None). The job's own "out" is replaced per renderer.
RESUMES = [
    ("sample_ko", EX / "sample_ko.json", None),
    ("sample_full_ko", EX / "sample_full_ko.json", EX / "job_full_ko.json"),
    ("sample_full_en", EX / "sample_full_en.json", EX / "job_full_en.json"),
    ("export_shape", ROOT / "tests" / "parts" / "fixtures" / "export_shape.json", None),
]
# (name, profile, cover file, job file): the example letters of docs/DOCUMENTS.md.
COVERS = [
    ("cover_ko", EX / "sample_ko.json", EX / "cover" / "cover_ko.json", EX / "cover" / "job_ko.json"),
    ("cover_en", EX / "sample_ko.json", EX / "cover" / "cover_en.json", EX / "cover" / "job_en.json"),
]
OUT = ROOT / "output"


def job_with(out: str, job: pathlib.Path | None, folder: pathlib.Path) -> pathlib.Path:
    """A copy of a job file whose output name is `out`"""
    cfg = json.loads(job.read_text(encoding="utf-8")) if job else {}
    cfg["out"] = out
    f = folder / f"{out}.job.json"
    f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return f


def env_for(renderer: str) -> dict:
    """The environment of a build with one renderer, under the CPU cap of run.sh"""
    return dict(os.environ, OFFEROWL_RENDERER=renderer, OFFEROWL_CPUS=os.environ.get("OFFEROWL_CPUS", "8"), PYTHONDONTWRITEBYTECODE="1")


def build_resume(renderer: str, profile: pathlib.Path, job: pathlib.Path) -> tuple[int, str]:
    """resume.py build with one renderer; returns (exit code, the last lines it printed)"""
    r = subprocess.run(["nice", "-n", "15", sys.executable, str(ROOT / "src" / "resume.py"), "build", str(profile), str(job)],
                       cwd=ROOT, capture_output=True, text=True, env=env_for(renderer))
    return r.returncode, (r.stdout + r.stderr).strip()[-600:]


def build_cover_container(profile, cover, job) -> tuple[int, str]:
    """cover.py build in the container (its own density loop)"""
    r = subprocess.run(["nice", "-n", "15", sys.executable, str(ROOT / "src" / "cover.py"), "build", str(profile), str(cover),
                        "--job", str(job), "--dest", str(OUT / "_parity_dest")],
                       cwd=ROOT, capture_output=True, text=True, env=env_for("container"))
    return r.returncode, (r.stdout + r.stderr).strip()[-600:]


def build_cover_html(profile, cover, job, out: str) -> tuple[int, str]:
    """The cover letter with the browser renderer: the same DOCX writer and the same density loop as cover.py build,
    through render.fit_pages (the hook cover.py takes for OFFEROWL_RENDERER=html)"""
    def write(level):  # the DOCX at one density level
        r = subprocess.run(["node", "src/cover_form.js", str(profile), str(cover), str(job), "--density", str(level)],
                           cwd=ROOT, capture_output=True, text=True, env=env_for("html"))
        return r.returncode, (r.stdout + r.stderr)[-600:]
    res = R.fit_pages(write, OUT / f"{out}.docx", OUT / f"{out}.pdf", max_pages=1)
    if "error" in res:
        return 1, res["error"]
    return 0, "density %d pages %s" % (res["level"], res["pages"])


def compare_pair(old: pathlib.Path, new: pathlib.Path) -> dict:
    """compare.compare() of two PDFs with a verdict"""
    r = compare.compare(str(old), str(new))
    pages = [p for p in r["pages"] if "only" not in p]
    same_text = r["pages_old"] == r["pages_new"] and all(p["lines_same"] == p["lines_old"] == p["lines_new"] for p in pages)
    return {"pages": (r["pages_old"], r["pages_new"]), "strict": [p["pixels"] for p in pages],
            "tolerant": [p["pixels_tolerant"] for p in pages], "text_same": same_text,
            "lines": (sum(p["lines_same"] for p in pages), sum(max(p["lines_old"], p["lines_new"]) for p in pages))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--container", action="store_true", help="build the container side too (needs Docker)")
    ap.add_argument("--typesetter-only", action="store_true", help="typeset the container's DOCX instead of rebuilding it")
    ap.add_argument("--md", help="write the result table here (Markdown)")
    ap.add_argument("--keep", action="store_true", help="keep the parity outputs in output/")
    a = ap.parse_args()
    tmp = OUT / "_parity_jobs"
    tmp.mkdir(parents=True, exist_ok=True)
    rows, ok = [], True
    if not a.container:  # earlier container outputs only stand for the inputs they were built from
        newest = max(f.stat().st_mtime for d in ("src", "examples") for f in (ROOT / d).rglob("*") if f.is_file() and "__pycache__" not in f.parts)
        old = [f.name for f in OUT.glob("parity_ct_*.pdf") if f.stat().st_mtime < newest]
        if old:  # a difference may then come from the changed inputs, not from the renderer
            print("warning: %d container outputs are older than the newest file under src/ or examples/; run with --container" % len(old))
    for name, profile, job in RESUMES:
        ct, ht = f"parity_ct_{name}", f"parity_html_{name}"
        if a.container:
            rc, log = build_resume("container", profile, job_with(ct, job, tmp))
            if rc:
                print(f"{name}: container build failed: {log}")
                ok = False
                continue
        if a.typesetter_only:  # the container's DOCX, typeset by the browser
            R.docx_to_pdf(OUT / f"{ct}.docx", OUT / f"{ht}.pdf")
            shutil.copy(OUT / f"{ct}_deck.pdf", OUT / f"{ht}_deck.pdf")  # the deck is HTML in both: nothing to separate
        else:
            rc, log = build_resume("html", profile, job_with(ht, job, tmp))
            if rc:
                print(f"{name}: html build failed: {log}")
                ok = False
                continue
        for kind, suf in (("resume", ""), ("deck", "_deck")):
            res = compare_pair(OUT / f"{ct}{suf}.pdf", OUT / f"{ht}{suf}.pdf")
            rows.append((name, kind, res))
    for name, profile, cover, job in COVERS:
        ct, ht = f"parity_ct_{name}", f"parity_html_{name}"
        if a.container:
            rc, log = build_cover_container(profile, cover, job_with(ct, job, tmp))
            if rc:
                print(f"{name}: container build failed: {log}")
                ok = False
                continue
        if a.typesetter_only:
            R.docx_to_pdf(OUT / f"{ct}.docx", OUT / f"{ht}.pdf")
        else:
            rc, log = build_cover_html(profile, cover, job_with(ht, job, tmp), ht)
            if rc:
                print(f"{name}: html build failed: {log}")
                ok = False
                continue
        rows.append((name, "cover", compare_pair(OUT / f"{ct}.pdf", OUT / f"{ht}.pdf")))
    lines = ["| Example | Document | Pages (container / html) | Lines the same | Worst page, strict | Worst page, within 1px | Per page, strict |",
             "|---|---|---|---|---|---|---|"]
    worst_s = worst_t = 0.0
    npages = 0
    for name, kind, r in rows:
        ok = ok and r["text_same"]
        worst_s, worst_t = max([worst_s] + r["strict"]), max([worst_t] + r["tolerant"])
        npages += r["pages"][1]
        lines.append("| %s | %s | %d / %d | %d / %d | %.2f%% | %.2f%% | %s |" % (
            name, kind, r["pages"][0], r["pages"][1], r["lines"][0], r["lines"][1], max(r["strict"] or [0]) * 100,
            max(r["tolerant"] or [0]) * 100, ", ".join("%.2f" % (x * 100) for x in r["strict"])))
    table = "\n".join(lines)
    print(table)
    if a.md:
        pathlib.Path(a.md).write_text(table + "\n", encoding="utf-8")
    if not a.keep:  # the parity outputs are not part of the usual output folder
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(OUT / "_parity_dest", ignore_errors=True)
    print("parity: %d documents, %d pages, worst page %.2f%% strict / %.2f%% within 1px, text %s"
          % (len(rows), npages, worst_s * 100, worst_t * 100, "same" if ok else "differs"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
