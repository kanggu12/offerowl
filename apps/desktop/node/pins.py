"""The Node.js release the one-file app carries: which archive to download for this system, and the SHA-256 it must have.

    python3 apps/desktop/node/pins.py                    show the pins and the key of this system
    python3 apps/desktop/node/pins.py --update 22.24.0   write another release's checksums into pins.json

The checksums in pins.json come from the release's SHASUMS256.txt on nodejs.org, which the Node.js release team signs
(SHASUMS256.txt.asc). `--update` copies them from that file over HTTPS; verify the signature with gpg against the keys
in https://github.com/nodejs/release-keys before committing the change.

This file uses only the standard library and imports nothing from its package, so it runs as a script and as a module.
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import argparse  # the command line
import json  # pins.json
import platform  # the machine name
import re  # checksum lines and archive names
import sys  # the running system
import urllib.request  # SHASUMS256.txt for --update
from pathlib import Path  # paths

PINS_FILE = Path(__file__).with_name("pins.json")  # next to this file, in the repository and in the package
ARCHIVE_ENDINGS = (".tar.xz", ".tar.gz", ".zip")  # the three archive kinds nodejs.org publishes for the supported systems


class UnsupportedSystem(ValueError):
    """No Node.js release is pinned for the system the build runs on."""


def load(path: Path = PINS_FILE) -> dict:  # one reader for the build, the tests and --update
    """pins.json as a dict."""
    return json.loads(path.read_text(encoding="utf-8"))  # UTF-8 on every system, whatever the locale says


def system_key(plat: str | None = None, machine: str | None = None) -> str:  # the names nodejs.org uses for its downloads
    """The pin key of a system, such as `linux-x64`, `darwin-arm64` or `win-x64`. With no arguments: this system."""
    plat = (plat or sys.platform).lower()  # win32, darwin or linux
    machine = (machine or platform.machine()).lower()  # x86_64, AMD64, arm64, aarch64
    system = "win" if plat.startswith("win") else "darwin" if plat == "darwin" else "linux" if plat.startswith("linux") else plat  # nodejs.org's operating system names
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)  # one name per architecture, whatever the OS calls it
    return f"{system}-{arch}"  # the key used in pins.json


def archive_folder(archive: str) -> str:  # the folder every nodejs.org archive holds its files in
    """`node-v22.1.0-linux-x64.tar.xz` holds everything in `node-v22.1.0-linux-x64/`."""
    for ending in ARCHIVE_ENDINGS:  # whichever kind this is
        if archive.endswith(ending):  # the ending to cut off
            return archive[: -len(ending)]  # the archive's name without it
    raise ValueError(f"not a Node.js archive name: {archive}")  # a pin that names something else is a mistake in pins.json


def entry(pins: dict, key: str | None = None) -> dict:  # everything the build needs about one download
    """The download for one system with its templates filled in: version, key, archive, url, folder, binary, license
    (the member names inside the archive) and sha256."""
    key = key or system_key()  # this system unless the caller names another
    node = pins["node"]  # the Node.js part of the pins
    row = node["platforms"].get(key)  # this system's pin
    if row is None:  # no pin: the build must stop here, not pick another system's file
        raise UnsupportedSystem(f"no Node.js is pinned for {key}; pinned systems: {', '.join(sorted(node['platforms']))}. "
                                "Add the system to apps/desktop/node/pins.json (python3 apps/desktop/node/pins.py --update <version>).")
    version = node["version"]  # one version for every system
    archive = row["archive"].format(version=version)  # node-v22.x.y-linux-x64.tar.xz
    folder = archive_folder(archive)  # the folder inside it
    return {"version": version, "key": key, "archive": archive, "sha256": row["sha256"].lower(),  # lower case, as sha256sum prints it
            "url": node["url"].format(version=version, archive=archive),  # where the build downloads it
            "folder": folder, "binary": f"{folder}/{row['binary']}", "license": f"{folder}/LICENSE"}  # the two members the build keeps


def parse_shasums(text: str) -> dict:  # SHASUMS256.txt has one `<sha256>  <file name>` line per download
    """{file name: sha256} from the text of a SHASUMS256.txt."""
    found = {}  # file name to digest
    for line in text.splitlines():  # each line of the file
        m = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(\S+)", line.strip())  # the digest, blanks, an optional binary-mode star, the name
        if m:  # lines that are not checksums (there are none today) are skipped
            found[m.group(2)] = m.group(1).lower()  # one digest per file
    return found


def update(version: str, text: str | None = None, path: Path = PINS_FILE) -> dict:  # for the maintainer, once per Node.js release
    """Write the checksums of Node.js `version` into pins.json for every pinned system. `text` is the release's
    SHASUMS256.txt (downloaded from nodejs.org when it is None). Returns the new pins."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):  # a release number, not a branch name such as latest-v22.x
        raise ValueError(f"not a release number: {version}")  # an exact version is what makes the build repeatable
    if text is None:  # the normal case: ask nodejs.org
        with urllib.request.urlopen(f"https://nodejs.org/dist/v{version}/SHASUMS256.txt", timeout=60) as r:  # HTTPS, so the list arrives unaltered
            text = r.read().decode("utf-8")  # plain ASCII
    sums = parse_shasums(text)  # file name to digest
    pins = load(path)  # the current pins keep their layout and their about text
    pins["node"]["version"] = version  # the new release
    for key, row in pins["node"]["platforms"].items():  # every pinned system
        name = row["archive"].format(version=version)  # its archive in the new release
        if name not in sums:  # a release without this download cannot be pinned for this system
            raise ValueError(f"v{version} has no {name} in its SHASUMS256.txt (pin {key})")  # nothing is written
        row["sha256"] = sums[name]  # the digest the build will insist on
    path.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")  # same layout as before, one trailing newline
    return pins


def main(argv: list[str] | None = None) -> int:  # the command line of this file
    ap = argparse.ArgumentParser(description="Show or update the Node.js release pinned for the one-file app.")  # what --help says
    ap.add_argument("--update", metavar="VERSION", help="pin another release, for example 22.24.0 (needs the network)")  # the one write
    args = ap.parse_args(argv)  # exits with a usage line on bad options
    if args.update:  # a maintainer moves the pin
        update(args.update)  # rewrites pins.json
    pins = load()  # shown after an update too, so the result is on screen
    print(f"Node.js {pins['node']['version']}; this system is {system_key()}")  # the release and the key of this system
    for key in sorted(pins["node"]["platforms"]):  # every pinned system
        e = entry(pins, key)  # with the templates filled in
        print(f"  {key:13} {e['archive']}  sha256 {e['sha256']}")  # the file and the digest the build checks
    return 0  # shown, or updated


if __name__ == "__main__":  # run as a script
    raise SystemExit(main())  # the return value becomes the exit code
