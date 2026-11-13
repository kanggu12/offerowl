"""Prints one version's section of CHANGELOG.md, which release.yml publishes as that release's notes.

    python3 .github/release_notes.py v0.1.0 [CHANGELOG.md]

Exits 1, saying what to add, when the changelog has no section for that version or the section is empty: a release is
not published without its notes, so the tag's run stops before anything is built. A pre-release tag (v0.1.0-rc.1) reads
its version's section, else the Unreleased one: a trial run before the release has notes to show.
"""
import re  # the section's heading
import sys  # arguments and the exit code
from pathlib import Path  # the changelog


def section(text: str, version: str) -> str | None:
    """The body under `## [version]`, up to the next `## [` heading or the link list at the end; None if absent."""
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]\n]+\]: |\Z)", text, re.S | re.M)  # from its heading to the next
    return match.group(1).strip() if match else None  # its words, without the blank lines around them


def main() -> int:
    version = sys.argv[1].removeprefix("v") if len(sys.argv) > 1 else ""  # the tag's name (v1.2.3) or the bare number
    path = Path(sys.argv[2] if len(sys.argv) > 2 else "CHANGELOG.md")  # the repository's changelog unless another is named
    text = path.read_text(encoding="utf-8")  # the changelog
    body = section(text, version) if version else None  # its notes
    if not body and "-" in version:  # a pre-release: its version's notes, else what is not released yet
        body = section(text, version.split("-", 1)[0]) or section(text, "Unreleased")
    if not body:  # no section, or an empty one: the release waits for its notes
        print(f"{path} has no notes for {version or '(no version)'}: add a '## [{version or 'x.y.z'}] - YYYY-MM-DD' section first", file=sys.stderr)
        return 1
    print(body)  # what the release page shows
    return 0


if __name__ == "__main__":
    sys.exit(main())
