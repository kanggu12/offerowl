"""The build-time half of the one-file app's Node.js support (runtime.py is the half that runs inside the app).

apps/desktop/build.py calls build_runtime(), which:

1. downloads the pinned Node.js archive for the system the build runs on (pins.json) and refuses it unless its SHA-256
   is the pinned one;
2. takes the one program out of it (node, or node.exe) and the licence, and packs them as node.xz, with a manifest that
   says what was packed, so the app can check what it unpacks;
3. installs the production libraries of package.json with npm ci in a scratch folder, removes what the DOCX and deck
   writers never load (prune.json), and loads every library once with the packed Node.js.

The result is two folders for PyInstaller: `runtime/` (manifest.json, node.xz, NODE-LICENSE) and `node_modules/`.

    python3 apps/desktop/node/bundle.py --work build   # the same steps by hand, for a look at the result
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import argparse  # the command line of this file
import fnmatch  # the file name patterns of prune.json
import hashlib  # SHA-256 of the archive and of the program
import json  # manifest.json, prune.json
import lzma  # node.xz
import os  # directory walks
import re  # the code scan for icon names
import shutil  # copies and removals
import subprocess  # npm and the packed Node.js
import sys  # the exit code of a standalone start
import tarfile  # .tar.xz and .tar.gz archives
import time  # the pause between download attempts
import urllib.error  # a failed download
import urllib.request  # the download
import zipfile  # .zip archives
from pathlib import Path  # paths

try:  # imported as desktop.node.bundle by build.py and the tests
    from . import pins as P  # the pinned release
except ImportError:  # started as a script: the folder of this file is on the path instead
    import pins as P  # type: ignore[no-redef]

HERE = Path(__file__).resolve().parent  # apps/desktop/node
FORMAT = 1  # the manifest's layout; runtime.py refuses a manifest of another layout
XZ_PRESET = 6  # level 6 is within 1% of level 9 on the Node.js program and needs a seventh of the memory (measured)
CHUNK = 1 << 20  # the size of one read or write when streaming a large file
PACKED = "node.xz"  # the program, compressed
LICENSE = "NODE-LICENSE"  # Node.js's licence file, kept beside the program in the app and in the data folder


class BuildError(RuntimeError):
    """A step of the bundle failed; the message says which one and what to do."""


def say_nothing(_text: str) -> None:  # the default for callers that want no progress lines
    """A progress sink that prints nothing (the tests pass this)."""


def sha256_file(path: Path) -> str:  # the digest of a large file without reading it all into memory
    """SHA-256 of a file, as lower-case hex."""
    h = hashlib.sha256()  # the running digest
    with open(path, "rb") as f:  # binary, so nothing is translated
        for block in iter(lambda: f.read(CHUNK), b""):  # one block at a time
            h.update(block)  # added to the digest
    return h.hexdigest()  # what sha256sum prints


# ---------------------------------------------------------------- the Node.js program


def download(url: str, dest: Path, opener=None, attempts: int = 3, say=say_nothing, pause: float = 2.0) -> str:  # a flaky network must not fail a release build
    """Download `url` to `dest` and return its SHA-256. The file is written under another name and renamed when it is
    complete, so an interrupted download never looks like a finished one. `opener(url)` stands in for the network."""
    opener = opener or (lambda u: urllib.request.urlopen(u, timeout=60))  # HTTPS with a time limit, so a stalled server fails the attempt
    part = dest.with_name(dest.name + ".part")  # where the bytes go until they are all there
    last = None  # the error of the last attempt
    for attempt in range(1, attempts + 1):  # a few tries
        try:  # the network can fail at any point
            h = hashlib.sha256()  # digest of what arrives
            dest.parent.mkdir(parents=True, exist_ok=True)  # the cache folder may not exist yet
            with opener(url) as r, open(part, "wb") as f:  # the response and the file
                for block in iter(lambda: r.read(CHUNK), b""):  # until the server is done
                    h.update(block)  # digest while writing, so the file is read once
                    f.write(block)  # stored
            os.replace(part, dest)  # complete: now it has its name
            return h.hexdigest()  # the caller compares it with the pin
        except (OSError, urllib.error.URLError) as exc:  # includes timeouts and connection resets
            last = exc  # reported if every attempt fails
            part.unlink(missing_ok=True)  # no half file stays
            say(f"download of {url} failed ({exc}); attempt {attempt} of {attempts}")  # the build log shows the retries
            if attempt < attempts:  # no pause after the last attempt
                time.sleep(pause * attempt)  # a longer pause each time
    raise BuildError(f"could not download {url}: {last}")  # all attempts failed


def fetch_archive(entry: dict, cache: Path, opener=None, say=say_nothing, pause: float = 2.0) -> Path:  # the only way a Node.js archive enters the build
    """The pinned archive in the cache folder, downloaded when it is missing and always checked against the pinned
    SHA-256. A cached file with another digest is deleted and fetched again; a download with another digest is deleted
    and refused."""
    dest = cache / entry["archive"]  # the archive's place in the cache
    if dest.is_file():  # an earlier build left it
        if sha256_file(dest) == entry["sha256"]:  # still the pinned file
            say(f"using the cached {entry['archive']}")  # nothing to download
            return dest  # verified just now
        say(f"the cached {entry['archive']} does not match its pin; fetching it again")  # damaged or replaced
        dest.unlink()  # it must not be used
    say(f"downloading {entry['url']}")  # the build log shows what is fetched
    digest = download(entry["url"], dest, opener=opener, say=say, pause=pause)  # the bytes and their digest
    if digest != entry["sha256"]:  # not the file the pin names: a bad mirror, a proxy, or a changed release
        dest.unlink(missing_ok=True)  # it must never be used by a later build
        raise BuildError(f"{entry['archive']} has SHA-256 {digest}, but pins.json pins {entry['sha256']}. "
                         "Nothing from this download was used.")  # the build stops here
    say(f"verified {entry['archive']} (sha256 {digest[:16]}...)")  # the digest matches the pin
    return dest  # safe to read


def extract_members(archive: Path, wanted: dict) -> None:  # reads only the named members, so nothing else can reach the disk
    """Write the archive members named in `wanted` ({member name: destination file}) and nothing else. Every member
    must be there."""
    done = set()  # the members written so far
    if archive.name.endswith(".zip"):  # Windows archives
        with zipfile.ZipFile(archive) as zf:  # the central directory is read at once
            for name, dest in wanted.items():  # each member asked for
                try:  # a missing member raises KeyError
                    src = zf.open(name)  # a stream of the member's bytes
                except KeyError:  # the archive is not laid out as pins.json says
                    continue  # reported below with the others
                with src, open(dest, "wb") as out:  # copied in blocks
                    shutil.copyfileobj(src, out, CHUNK)  # a large file never sits in memory whole
                done.add(name)  # written
    else:  # tar.xz and tar.gz: read as a stream, in the archive's own order
        with tarfile.open(archive, "r:*") as tf:  # the compression is detected
            for member in tf:  # each entry once
                dest = wanted.get(member.name)  # only the named ones are of interest
                if dest is None or not member.isfile():  # other files, folders and links are skipped
                    continue  # never written
                src = tf.extractfile(member)  # a stream of the member's bytes
                if src is None:  # not readable as a file
                    continue  # reported below
                with src, open(dest, "wb") as out:  # copied in blocks
                    shutil.copyfileobj(src, out, CHUNK)  # a large file never sits in memory whole
                done.add(member.name)  # written
                if done == set(wanted):  # everything asked for is out
                    break  # the rest of a 30 MB archive need not be decompressed
    missing = sorted(set(wanted) - done)  # members that were not found
    if missing:  # the pins describe an archive this one is not
        raise BuildError(f"{archive.name} lacks {', '.join(missing)}")  # nothing half-built is used


def decompress(packed: Path, dest: Path) -> tuple[str, int]:  # the inverse of the packing below
    """Unpack an xz file to `dest`; returns (SHA-256, size) of what came out."""
    h, size = hashlib.sha256(), 0  # digest and byte count of the output
    with lzma.open(packed, "rb") as src, open(dest, "wb") as out:  # xz checks its own integrity while reading
        for block in iter(lambda: src.read(CHUNK), b""):  # one block at a time
            h.update(block)  # digest of the program
            size += len(block)  # its size
            out.write(block)  # written
    return h.hexdigest(), size  # compared with what was recorded at packing time


def pack_node(entry: dict, archive: Path, cache: Path, out: Path, say=say_nothing) -> tuple[dict, Path]:  # one program, compressed
    """Take node (or node.exe) and the licence out of the verified archive and write `out`/node.xz, `out`/NODE-LICENSE and
    `out`/manifest.json. Returns (the manifest, the path of the unpacked program, which the library check runs).
    The compressed program is kept in the cache with the digest it had when it was taken out of the verified archive,
    so a second build does not compress again; it is unpacked and compared with that digest each time before use."""
    program = "node.exe" if entry["binary"].endswith(".exe") else "node"  # the name the program has once unpacked
    stem = f"{entry['folder']}.{entry['sha256'][:16]}.p{XZ_PRESET}"  # one cache entry per archive and compression level
    packed, meta_file, lic = cache / f"{stem}.xz", cache / f"{stem}.json", cache / f"{entry['folder']}.LICENSE"  # what the cache holds
    plain = cache / "program" / program  # the unpacked program, made again on every build
    plain.parent.mkdir(parents=True, exist_ok=True)  # the folder for it
    meta = None  # the digest and size recorded when the program left the archive
    if packed.is_file() and meta_file.is_file() and lic.is_file():  # an earlier build left all three
        recorded = json.loads(meta_file.read_text(encoding="utf-8"))  # what it recorded
        if decompress(packed, plain) == (recorded["sha256"], recorded["size"]):  # the packed file still gives the same program
            meta = recorded  # trusted again
            say(f"using the cached {packed.name}")  # nothing to compress
    if meta is None:  # a first build, or a damaged cache
        say(f"unpacking {program} from {archive.name}")  # the build log shows the slow steps
        for stale in (packed, meta_file):  # neither may outlive a failure below
            stale.unlink(missing_ok=True)  # removed
        extract_members(archive, {entry["binary"]: plain, entry["license"]: lic})  # only these two members
        meta = {"sha256": sha256_file(plain), "size": plain.stat().st_size}  # recorded while the program is known to come from the verified archive
        say(f"compressing {program} ({meta['size'] // (1 << 20)} MiB) with xz level {XZ_PRESET}")  # about a minute for the Linux program
        part = packed.with_name(packed.name + ".part")  # complete or absent, never half
        with open(plain, "rb") as src, lzma.open(part, "wb", format=lzma.FORMAT_XZ, check=lzma.CHECK_SHA256, preset=XZ_PRESET) as dst:  # xz with a checksum inside
            shutil.copyfileobj(src, dst, CHUNK)  # streamed, so the 120 MB program never sits in memory twice
        os.replace(part, packed)  # complete now
        meta_file.write_text(json.dumps(meta), encoding="utf-8")  # written last: its presence says the packed file is whole
    if os.name == "posix":  # a program needs its execute bits, and a file written by Python has none
        os.chmod(plain, 0o755)  # the library check below runs it
    out.mkdir(parents=True, exist_ok=True)  # the folder PyInstaller will bundle
    shutil.copyfile(packed, out / PACKED)  # the compressed program
    shutil.copyfile(lic, out / LICENSE)  # Node.js's licence travels with its program
    manifest = {"format": FORMAT, "node": {  # what runtime.py checks against
        "version": entry["version"], "system": entry["key"], "program": program,  # which release, for which system, under which name
        "size": meta["size"], "sha256": meta["sha256"],  # the unpacked program's size and digest
        "packed": PACKED, "license": LICENSE,  # the two files beside the manifest
        "archive": entry["archive"], "archive_sha256": entry["sha256"], "source": entry["url"]}}  # where it came from, for anyone who wants to compare
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")  # read by runtime.py at every start
    return manifest, plain  # the unpacked program is used for the library check


# ---------------------------------------------------------------- the libraries


def load_policy(path: Path = HERE / "prune.json") -> dict:  # what to leave out of node_modules
    """prune.json as a dict."""
    return json.loads(path.read_text(encoding="utf-8"))  # UTF-8 whatever the locale says


def stage_libs(root: Path, stage: Path, say=say_nothing, npm: str | None = None) -> Path:  # a clean install, from the lock file
    """Install the production libraries of package.json into `stage`/node_modules with npm ci, which installs exactly
    what package-lock.json says and nothing else. Returns the node_modules folder."""
    shutil.rmtree(stage, ignore_errors=True)  # no earlier install is mixed in
    stage.mkdir(parents=True)  # a fresh scratch folder
    for name in ("package.json", "package-lock.json"):  # the two files npm ci reads
        shutil.copyfile(root / name, stage / name)  # copied, so the repository's own node_modules is never touched
    npm = npm or shutil.which("npm")  # npm comes with Node.js; on Windows this finds npm.cmd
    if not npm:  # the build machine has no Node.js
        raise BuildError("npm was not found. Install Node.js (npm comes with it) to build the app: it fetches the libraries.")  # the fix
    say("npm ci --omit=dev")  # the build log shows the command
    r = subprocess.run([npm, "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund", "--loglevel=error"],  # no dev packages, no install scripts, no network chatter
                       cwd=stage, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if r.returncode != 0 or not (stage / "node_modules").is_dir():  # npm failed or installed nothing
        raise BuildError("npm ci failed:\n" + (r.stdout + r.stderr)[-2000:])  # its own words
    return stage / "node_modules"  # what gets pruned and bundled


def tree_size(tree: Path) -> tuple[int, int]:  # for the build log: how much the pruning took away
    """(file count, bytes) of everything under `tree`, links counted as files."""
    files = size = 0  # the totals
    for folder, _dirs, names in os.walk(tree):  # every folder
        for n in names:  # every file in it
            files += 1  # counted
            try:  # a dangling link has no target but has a size of its own
                size += (Path(folder) / n).lstat().st_size  # the file itself, not what a link points at
            except OSError:  # vanished while walking
                pass  # counted as nothing
    return files, size  # the totals


def icon_names(src: Path) -> set:  # the lucide icons the engine can ask for
    """The lucide icon names that the engine's JavaScript names: the targets of its ALIAS table, the literal names given
    to icon(), svgIcon() and lucide(), and the `icon:` option of a diagram box (through ALIAS, as ICON does). A name
    built at run time cannot be found this way; none exists today."""
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(src.rglob("*.js"))]  # every script of the engine
    alias = {}  # old icon name to lucide name
    for t in texts:  # the table lives in one file
        m = re.search(r"\bALIAS\s*=\s*\{(.*?)\}\s*;", t, re.S)  # const ALIAS = { server: "server", ... };
        if m:  # found
            alias.update(re.findall(r"([\w$]+)\s*:\s*[\"']([\w-]+)[\"']", m.group(1)))  # key: "value" pairs
    names = set(alias.values())  # every shortcut the engine defines stays usable
    for t in texts:  # the places that name an icon
        names.update(re.findall(r"\b(?:icon|svgIcon|lucide)\(\s*[\"'`]([a-z0-9-]+)[\"'`]", t))  # icon("server", ...)
        names.update(alias.get(k, k) for k in re.findall(r"\bicon\s*:\s*[\"'`]([\w-]+)[\"'`]", t))  # { icon: "db" }
        names.update(alias.get(k, k) for k in re.findall(r"\bICON\.([A-Za-z_$][\w$]*)", t))  # ICON.db(...)
        names.update(alias.get(k, k) for k in re.findall(r"\bICON\[\s*[\"']([\w-]+)[\"']\s*\]", t))  # ICON["db"](...)
    return names  # a set of lucide file names without the .svg


def _remove(path: Path) -> None:  # one removal for files, links and folders
    if path.is_dir() and not path.is_symlink():  # a real folder
        shutil.rmtree(path, ignore_errors=True)  # with everything in it
    else:  # a file or a link
        path.unlink(missing_ok=True)  # gone


def package_roots(tree: Path) -> list:  # every installed package
    """The folders of the installed packages directly under `tree`: tree/name and tree/@scope/name."""
    roots = []  # found packages
    for d in sorted(os.listdir(tree)):  # the entries of node_modules
        if d.startswith("."):  # .bin and npm's hidden lock file are not packages
            continue  # skipped
        if d.startswith("@"):  # a scope holds packages one level down
            roots += [tree / d / sub for sub in sorted(os.listdir(tree / d)) if (tree / d / sub).is_dir()]  # its packages
        elif (tree / d).is_dir():  # a plain package
            roots.append(tree / d)  # itself
    return roots


def prune_libs(tree: Path, policy: dict, src: Path, say=say_nothing) -> dict:  # the prune list at work
    """Remove from `tree` what prune.json lists. Returns {"before": [files, bytes], "after": [files, bytes], "icons":
    [names kept], "stale": [rules that matched nothing]}."""
    before = tree_size(tree)  # for the build log
    stale = []  # rules whose target is no longer there: the package changed and the list is out of date
    for name in policy["drop_packages"]:  # packages that hold types only, or whole scopes of them
        _remove(tree / name)  # gone with everything in it
    spec = policy.get("icons")  # which package holds the icons, and what else of it stays
    icons = []  # the lucide icons that stay
    if spec and (tree / spec["package"]).is_dir():  # the icon package is installed
        pkg = tree / spec["package"]  # its folder
        icons = sorted(icon_names(src))  # the names the engine uses
        missing = [n for n in icons if not (pkg / "icons" / f"{n}.svg").is_file()]  # names the code uses and the package lacks
        if missing:  # a typo or a renamed icon: the deck would fail on it
            raise BuildError(f"the engine names lucide icons that {spec['package']} does not have: {', '.join(missing)}")  # stop here
        keep = {pkg / "icons" / f"{n}.svg" for n in icons} | {pkg / f for f in spec["keep_files"]}  # the files that stay
        for folder, _dirs, names in os.walk(pkg):  # every file of the package
            for n in names:  # each file
                if Path(folder) / n not in keep:  # not an icon in use, not the licence
                    _remove(Path(folder) / n)  # gone
    keep_names = [k.lower() for k in policy["keep_files"]]  # licence files and package.json always stay
    for root in package_roots(tree):  # every installed package
        if spec and root.name == spec["package"]:  # the icon package was handled above
            continue  # nothing more to take from it
        for rule in policy["drop_in"].get(root.name, []):  # the package's own list
            target = root / rule  # a file or a folder inside the package
            if target.exists() or target.is_symlink():  # still there
                _remove(target)  # gone
            else:  # a rule for something the package no longer has
                stale.append(f"{root.name}/{rule}")  # reported, not fatal
    for folder, dirs, names in os.walk(tree, topdown=True):  # the rules that apply to every package
        for d in list(dirs):  # folders first, so a dropped folder is not walked
            if d in policy["drop_dirs"] or d.startswith("."):  # tests, docs, examples, hidden folders such as .bin
                _remove(Path(folder) / d)  # gone with everything in it
                dirs.remove(d)  # and not entered
        for n in names:  # then the files
            p = Path(folder) / n  # its path
            keep = any(fnmatch.fnmatch(n.lower(), k) for k in keep_names)  # licence files and package.json
            if p.is_symlink() or (not keep and any(fnmatch.fnmatch(n.lower(), g) for g in policy["drop_files"])):  # links (only .bin had any) and the listed kinds
                _remove(p)  # gone
    for folder, _dirs, _names in os.walk(tree, topdown=False):  # bottom up, so a folder whose folders just went is seen empty
        if Path(folder) != tree and not os.listdir(folder):  # an emptied folder (listed now: the walk's own lists are older)
            os.rmdir(folder)  # removed, so nothing hollow is bundled
    after = tree_size(tree)  # what is left
    say(f"node_modules: {before[0]} files, {before[1] / 1e6:.1f} MB before; {after[0]} files, {after[1] / 1e6:.1f} MB after; {len(icons)} lucide icons")  # the build log
    return {"before": list(before), "after": list(after), "icons": icons, "stale": stale}  # for the log and the tests


def check_libs(stage: Path, node: Path, names: list, say=say_nothing) -> None:  # the pruned tree must still load
    """Load every library once with the packed Node.js from the folder that holds node_modules. A library the pruning
    broke fails here, in the build, and not at the person's first click."""
    code = "for (const n of process.argv.slice(1)) require(n)"  # node -e puts the extra arguments after argv[0]
    r = subprocess.run([str(node), "-e", code, *names], cwd=stage, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)  # the program that will ship
    if r.returncode != 0:  # one of the libraries did not load
        raise BuildError(f"the pruned libraries do not load with Node.js: {(r.stderr or r.stdout)[-1500:]}")  # node's own error
    say(f"loaded {', '.join(names)} with the packed Node.js")  # the build log


def build_runtime(root: Path, work: Path, say=print, key: str | None = None, opener=None) -> dict:  # build.py's one call
    """Everything build.py bundles: {"runtime": folder, "node_modules": folder, "manifest": dict, "report": dict}.
    `work` keeps a cache of the verified archive and the compressed program (`work`/node-cache), so a second build is fast."""
    pins = P.load()  # the pinned release
    entry = P.entry(pins, key)  # this system's download
    cache = work / "node-cache"  # survives from build to build, and CI can cache it
    cache.mkdir(parents=True, exist_ok=True)  # the first build creates it
    archive = fetch_archive(entry, cache, opener=opener, say=say)  # verified against the pin
    out = work / "runtime"  # the folder PyInstaller bundles as runtime/
    shutil.rmtree(out, ignore_errors=True)  # no file of an earlier build stays in it
    manifest, program = pack_node(entry, archive, cache, out, say=say)  # node.xz, the licence, the manifest
    policy = load_policy()  # the prune list
    tree = stage_libs(root, work / "node-stage", say=say)  # npm ci, production only
    report = prune_libs(tree, policy, root / "src", say=say)  # the prune list at work
    packages = json.loads((root / "package.json").read_text(encoding="utf-8")).get("dependencies", {})  # the libraries the writers ask for
    check_libs(tree.parent, program, [d for d in packages if d != (policy.get("icons") or {}).get("package")], say=say)  # they must load with the program that ships
    return {"runtime": out, "node_modules": tree, "manifest": manifest, "report": report}  # handed to PyInstaller


def main(argv: list[str] | None = None) -> int:  # the same steps by hand
    ap = argparse.ArgumentParser(description="Fetch, verify, pack and prune what the one-file app carries of Node.js.")  # what --help says
    ap.add_argument("--work", default="build", help="folder for the cache and the results (default: build)")  # where things land
    ap.add_argument("--root", default=str(HERE.parents[2]), help="the repository (default: this checkout)")  # where package.json is
    args = ap.parse_args(argv)  # exits with a usage line on bad options
    out = build_runtime(Path(args.root), Path(args.work).resolve())  # the whole bundle
    print(json.dumps({"runtime": str(out["runtime"]), "node_modules": str(out["node_modules"]), "node": out["manifest"]["node"]}, indent=2))  # where to look
    return 0  # built


if __name__ == "__main__":  # run as a script
    sys.exit(main())  # the return value becomes the exit code
