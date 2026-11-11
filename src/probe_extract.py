# -*- coding: utf-8 -*-
"""Take the deck measurement (#probe-out, written by the PROBE script of portfolio/deck.js) out of a chromium
--dump-dom result and save it as .probe.json. resume.py (the deck) and the review screen server use it

  python3 src/probe_extract.py <dom file> <probe.json>
"""
import html  # decode HTML entities
import re  # find the measurement block
import sys  # command-line arguments


def extract(dom: str) -> str:
    """The measurement result as JSON text, taken from the DOM text. ValueError when there is none"""
    m = re.search(r'<pre id="probe-out">(.*?)</pre>', dom, re.S)
    if not m or not m.group(1).strip():
        raise ValueError("the measurement (#probe-out) is empty")
    return html.unescape(m.group(1))


if __name__ == "__main__":
    src, dst = sys.argv[1:3]
    open(dst, "w", encoding="utf-8").write(extract(open(src, encoding="utf-8").read()))
