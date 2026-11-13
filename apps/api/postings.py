"""A posting from a link: the page is fetched once, its text kept, and nothing else of it.

Only http and https addresses on the public internet are fetched (no address of this PC or its network, so a link
cannot reach the panel itself or a router): the name is asked once and the connection goes to the address that was
checked, every redirect is checked the same way, and the whole fetch has one time limit and a size cap. The page's text is taken from its HTML
with the standard library's parser: scripts, styles and navigation are left out, and list items stay list items, so
the posting's lines read as they do on screen.
"""
from __future__ import annotations

import html.parser  # the page's text
import http.client  # the connection to the address that was checked
import ipaddress  # private addresses
import socket  # the name's addresses
import ssl  # TLS to that address, checked against the link's name
import time  # the fetch's deadline
import urllib.parse  # the link's parts
import urllib.request  # the fetch through a proxy

MAX_BYTES = 2_000_000  # a posting page is never larger than this
TIMEOUT = 12  # seconds for the whole fetch
MAX_HOPS = 5  # redirects followed, each one checked like the link
SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "button", "iframe", "template"}  # never posting text
BLOCK = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "table", "ul", "ol", "dl", "dt", "dd", "main"}  # line breaks


class Text(html.parser.HTMLParser):
    """The visible text of a page, one line per block and "- " before each list item."""

    def __init__(self):
        super().__init__(convert_charrefs=True)  # &amp; becomes &
        self.out, self.skip, self.title = [], 0, ""  # the text pieces, how deep inside skipped tags, the page title
        self.in_title = False  # inside <title>

    def handle_starttag(self, tag, attrs):  # an element opens
        if tag in SKIP:  # its text is never the posting
            self.skip += 1  # deeper inside skipped content
        elif tag == "li":  # a list item
            self.out.append("\n- ")  # a line of its own, marked as a list item
        elif tag in BLOCK:  # a block
            self.out.append("\n")  # a new line
        if tag == "title":  # the page's title
            self.in_title = True  # its text is kept apart

    def handle_endtag(self, tag):  # an element closes
        if tag in SKIP and self.skip:  # leaving skipped content
            self.skip -= 1  # one level up
        elif tag in BLOCK or tag == "li":  # the end of a block
            self.out.append("\n")  # a new line
        if tag == "title":  # the title ends
            self.in_title = False  # back to the body

    def handle_data(self, data):  # text between tags
        if self.in_title:  # the title
            self.title += data  # kept apart
        elif not self.skip:  # visible text
            self.out.append(data)  # kept

    def text(self) -> str:
        """The collected text with blank runs squeezed."""
        lines = [" ".join(x.split()) for x in "".join(self.out).splitlines()]  # spaces squeezed per line
        out, blank = [], False  # lines, the last one was blank
        for ln in lines:  # each line
            if ln in ("", "-"):  # empty, or an empty list item
                if not blank and out:  # one blank line between blocks
                    out.append("")  # kept once
                blank = True  # remembered
            else:  # a line with words
                out.append(ln)  # kept
                blank = False  # reset
        return "\n".join(out).strip()  # the posting as text


def page_text(body: str) -> str:
    """The readable text of a saved page, as fetch() reads a linked one."""
    p = Text()  # the same reader
    p.feed(body)
    return p.text()


def addresses(host: str) -> list[str]:
    """Every address the name points to, asked once: the fetch connects to one of these and never asks again, so a name
    cannot answer with a public address for the check and this PC's for the connection (DNS rebinding)."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)  # OSError when the name does not resolve
    return list(dict.fromkeys(info[4][0].split("%")[0] for info in infos))  # in the system's order, without a zone index or repeats


def public_address(addr: str) -> bool:
    """True for an address on the public internet: not this PC, its network, a carrier's shared range (100.64.0.0/10, where
    some clouds keep their metadata service), a link-local or test range, nor such an address written as IPv6."""
    ip = ipaddress.ip_address(addr)  # ValueError for something that is no address
    ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:127.0.0.1 is 127.0.0.1
    return ip.is_global and not ip.is_multicast  # allocated for the public internet, one host


def public_host(host: str, addrs: list | None = None) -> bool:
    """True when every address the name points to (or the addresses already asked) is on the public internet."""
    try:
        addrs = addresses(host) if addrs is None else addrs  # asked now, unless the caller asked already
        return bool(addrs) and all(public_address(a) for a in addrs)  # one private address is enough to refuse
    except (OSError, ValueError):  # the name does not resolve, or an answer is no address
        return False  # nothing to fetch


def connect_checked(addrs: list, port: int, deadline: float) -> socket.socket:
    """A connection to the first of the checked addresses that answers, in the system's order, as socket.create_connection
    tries a name's addresses: a name that says IPv6 first still reaches a PC with no IPv6 route through its IPv4 address.
    No address is asked of the name again, and the tries share the fetch's deadline."""
    last = None  # why the last one failed
    for addr in addrs:  # every one of them was checked
        left = deadline - time.monotonic()  # the time the fetch has left
        if left <= 0:
            break
        try:
            return socket.create_connection((addr, port), min(left, TIMEOUT))
        except OSError as exc:  # refused, no route, no such family here: the next one
            last = exc
    raise last or OSError("no address answered")  # none did


class Pinned(http.client.HTTPConnection):
    """An HTTP connection to the addresses that were checked, whatever the name would resolve to now."""

    def __init__(self, host: str, port, addrs: list, deadline: float):
        super().__init__(host, port, timeout=TIMEOUT)  # the Host header keeps the name
        self.addrs, self.deadline = addrs, deadline  # where the connection may go, and until when

    def connect(self):
        self.sock = connect_checked(self.addrs, self.port, self.deadline)  # a checked address, no new lookup


class PinnedTLS(http.client.HTTPSConnection):
    """The same over TLS: the certificate is checked against the name, the connection goes to a checked address."""

    def __init__(self, host: str, port, addrs: list, deadline: float):
        super().__init__(host, port, timeout=TIMEOUT, context=ssl.create_default_context())  # the system's trust and hostname check
        self.addrs, self.deadline = addrs, deadline

    def connect(self):
        sock = connect_checked(self.addrs, self.port, self.deadline)  # a checked address
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # SNI and the certificate's name: the link's


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Through a proxy: a redirect is a new link, so each hop is checked like the first (the proxy resolves the name)."""

    def __init__(self, allow_local: bool):
        self.allow_local = allow_local  # only the tests fetch from this PC

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlsplit(newurl)  # where it leads
        if u.scheme not in ("http", "https") or not u.hostname or (not self.allow_local and not public_host(u.hostname)):  # the rule of fetch()
            raise ValueError("bad_link")  # refused, before anything is sent there
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # the usual redirect


def read_capped(r, deadline: float, sock=None) -> bytes:
    """The body, up to MAX_BYTES + 1 bytes, read before the deadline: a server that sends one byte at a time cannot hold the
    fetch past it. `sock` is the connection's socket, whose wait for each read is cut to the time left."""
    chunks, size = [], 0  # what came, how much
    while size <= MAX_BYTES:  # one byte over the cap is enough to know
        left = deadline - time.monotonic()  # the time the fetch has left
        if left <= 0:  # too slow
            raise ValueError("unreachable")
        if sock is not None:  # each read waits no longer than what is left
            sock.settimeout(min(left, TIMEOUT))
        read = getattr(r, "read1", None) or r.read  # read1: what has come, without waiting for a full chunk
        chunk = read(min(65536, MAX_BYTES + 1 - size))
        if not chunk:  # the end of the body
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def via_proxy(scheme: str, host: str) -> bool:
    """A proxy of the person's settings (HTTP_PROXY, HTTPS_PROXY) carries this link."""
    return scheme in urllib.request.getproxies() and not urllib.request.proxy_bypass(host)


def fetch(url: str, allow_local: bool = False) -> dict:
    """{"text", "title", "url"} of a posting page. Raises ValueError with a code: bad_link, unreachable, too_large,
    not_text, empty. `allow_local` lets the tests fetch from a server on this PC."""
    u = urllib.parse.urlsplit(str(url or "").strip())  # the link's parts
    if u.scheme not in ("http", "https") or not u.hostname:  # only web links
        raise ValueError("bad_link")  # refused
    deadline = time.monotonic() + TIMEOUT  # the whole fetch, redirects and a slow body included
    if not allow_local and via_proxy(u.scheme, u.hostname):  # the proxy connects, so it resolves the name; the name is checked first
        if not public_host(u.hostname):
            raise ValueError("bad_link")
        status, ctype, charset, data = fetch_through_proxy(u, deadline)
    else:
        status, ctype, charset, data = fetch_direct(u, allow_local, deadline)
    if len(data) > MAX_BYTES:  # over the cap
        raise ValueError("too_large")  # refused
    try:
        body = data.decode(charset, errors="replace")  # text
    except LookupError:  # a charset Python does not know (a made-up or mistyped name): read as UTF-8, the web's usual one
        body = data.decode("utf-8", errors="replace")
    if ctype.startswith("text/plain"):  # already text
        text, title = body.strip(), ""  # as it is
    else:  # HTML
        p = Text()  # the parser
        p.feed(body)  # read
        text, title = p.text(), " ".join(p.title.split())  # its text and title
    if len(text) < 20:  # nothing worth reading (a page that needs scripts)
        raise ValueError("empty")  # the page says to paste the text instead
    return {"text": text[:40_000], "title": title[:200], "url": urllib.parse.urlunsplit(u)}  # bounded


def page_kind(headers) -> tuple[str, str]:
    """(content type, charset) of a page, refused unless it is text."""
    ctype = headers.get("Content-Type", "")  # what it says it is
    if not ctype.startswith(("text/html", "text/plain", "application/xhtml")):  # a PDF or an image
        raise ValueError("not_text")  # the page says to paste the text instead
    return ctype, headers.get_content_charset() or "utf-8"  # the page's encoding


def fetch_direct(u, allow_local: bool, deadline: float) -> tuple:
    """(status, type, charset, bytes) fetched without a proxy: each hop's name asked once, checked, and connected to at that
    very address; redirects followed by hand, each one checked like the link."""
    for _ in range(MAX_HOPS + 1):  # the link, then each redirect
        if u.scheme not in ("http", "https") or not u.hostname:  # a redirect to anything but a web link
            raise ValueError("bad_link")
        try:
            addrs = addresses(u.hostname)  # asked once for this hop
        except OSError as exc:  # no such name
            raise (ValueError("unreachable") if allow_local else ValueError("bad_link")) from exc
        if not allow_local and not public_host(u.hostname, addrs):  # this PC, its network, or a name that says so
            raise ValueError("bad_link")  # refused, before anything is sent there
        if deadline - time.monotonic() <= 0:  # the redirects used the time up
            raise ValueError("unreachable")
        port = u.port or (443 if u.scheme == "https" else 80)
        conn = (PinnedTLS if u.scheme == "https" else Pinned)(u.hostname, port, addrs, deadline)  # every checked address, in order
        try:
            conn.request("GET", (u.path or "/") + ("?" + u.query if u.query else ""),
                         headers={"User-Agent": "offerowl", "Accept": "text/html,text/plain"})  # one GET
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):  # a new link
                u = urllib.parse.urlsplit(urllib.parse.urljoin(urllib.parse.urlunsplit(u), r.getheader("Location")))
                continue  # checked at the top, like the first
            if r.status >= 400:  # not found, refused, a server error
                raise ValueError("unreachable")
            ctype, charset = page_kind(r.headers)
            return r.status, ctype, charset, read_capped(r, deadline, conn.sock)
        except ValueError:  # our own refusals
            raise
        except Exception as exc:  # unreachable, timed out, refused, a TLS problem
            raise ValueError("unreachable") from exc  # one code for all of them
        finally:
            conn.close()
    raise ValueError("unreachable")  # redirects without end


def fetch_through_proxy(u, deadline: float) -> tuple:
    """(status, type, charset, bytes) fetched through the person's proxy, every redirect checked (CheckedRedirect)."""
    req = urllib.request.Request(urllib.parse.urlunsplit(u), headers={"User-Agent": "offerowl", "Accept": "text/html,text/plain"})  # one GET
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(), CheckedRedirect(False))
    try:
        with opener.open(req, timeout=min(TIMEOUT, max(0.1, deadline - time.monotonic()))) as r:  # bounded in time
            ctype, charset = page_kind(r.headers)
            return r.status, ctype, charset, read_capped(r, deadline)
    except ValueError:  # our own refusals
        raise
    except Exception as exc:  # unreachable, timed out, refused, a TLS problem
        raise ValueError("unreachable") from exc
