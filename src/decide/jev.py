# -*- coding: utf-8 -*-
"""The Jev backend: a hosted decision model, reached through a gateway key. Off unless switched on.

Jev has no published weights, so every decision it makes sends the decision's input (posting lines, evidence,
sentences) to the gateway and the model's maker. That breaks Offerowl's local-first default, so this backend needs
two settings, and the panel and the command line say where the inputs go:

  OFFEROWL_JEV_KEY    the gateway key (an OpenRouter key, or a key of the maker's own endpoint)
  OFFEROWL_JEV_SEND   1 means "send decision inputs off this PC"; without it nothing is sent
  OFFEROWL_JEV_URL    the gateway's address (default https://openrouter.ai/api; the maker's own is https://api.typesafe.ai)
  OFFEROWL_JEV_MODEL  the model name (default typesafe/jev-1.14 on OpenRouter; jev-latest on the maker's endpoint)

The request is the System One shape of the gateway's API reference: POST <url>/v1/systemone with the model, a state (a
plain string or a JSON object) and typed questions. A choice answer carries the choice, the model's own confidence and,
when the gateway gives them, a probability per option; a question the model declines comes back as a refusal. Checked
on 2026-11-12: the endpoint answers 401 without a key, and the gateway lists typesafe/jev-1.14 from TypeSafe. The client
is tested against a local stand-in that answers in the reference's shape; no key was available, so it has never talked
to Jev itself.
"""
import json  # request and answer
import os  # settings
import time  # time per decision, and the wait a busy gateway asks for
import urllib.error  # HTTP errors
import urllib.parse  # the host name for the notice
import urllib.request  # the request

LEAVES_PC = True  # the one fact the panel must show next to this backend
DEFAULT_URL = "https://openrouter.ai/api"  # a gateway that serves Jev
DEFAULT_MODEL = "typesafe/jev-1.14"  # the gateway's name for the current release
BUSY = (429, 502, 503, 529)  # the gateway or the model is busy: worth asking again after the wait it names
TRIES = 3  # one request and two more after a busy answer, so a long measurement does not stop at one rate limit
WAIT = (0.5, 10.0)  # the shortest and longest wait between tries, whatever Retry-After says
NOTICE = {  # what the panel and the command line say about this backend
    "en": "Decision inputs (posting lines, evidence, sentences) are sent to {host} when this backend is on.",
    "ko": "이 백엔드를 켜면 판단에 쓰는 글(공고 줄, 근거, 문장)이 {host}로 보내진다.",
}


def setting(name: str, default: str = "") -> str:
    """OFFEROWL_<name>, else the default."""
    return os.environ.get("OFFEROWL_" + name, "").strip() or default


def host() -> str:
    """The host the inputs would go to."""
    return urllib.parse.urlparse(setting("JEV_URL", DEFAULT_URL)).hostname or setting("JEV_URL", DEFAULT_URL)


def status(lang: str = "en") -> dict:
    """ready only with a key and the consent setting; the notice says where the inputs go either way."""
    key, send = bool(setting("JEV_KEY")), setting("JEV_SEND") == "1"  # the two switches
    why = "" if key and send else ("OFFEROWL_JEV_KEY is not set" if not key else "OFFEROWL_JEV_SEND=1 is not set")  # what is missing
    return {"ready": key and send, "why": why, "notice": NOTICE.get(lang, NOTICE["en"]).format(host=host()), "tested": False}


def wait_of(header) -> float:
    """The seconds a busy answer's Retry-After asks for, kept within WAIT; 2 when it names none or a date."""
    try:
        sec = float(header)  # Retry-After in seconds
    except (TypeError, ValueError):  # missing, or an HTTP date
        sec = 2.0
    return min(max(sec, WAIT[0]), WAIT[1])  # never a busy loop, never a long stall


def systemone(state, questions: dict, timeout: int = 60) -> dict:
    """One System One request: {"model", "state", "questions"} in, {"answers": {...}, "model", ...} out. A busy
    answer (rate limit, overload) is asked again after the wait it names, TRIES times in all."""
    from decide import DecideUnavailable  # the shared failure
    st = status()  # the switches, checked on every call
    if not st["ready"]:  # nothing leaves this PC without both
        raise DecideUnavailable(f"jev: {st['why']}")
    body = {"model": setting("JEV_MODEL", DEFAULT_MODEL), "state": state, "questions": questions}  # a string or an object, as the reference takes it
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")  # Korean as it is, in UTF-8
    url = setting("JEV_URL", DEFAULT_URL).rstrip("/") + "/v1/systemone"  # the System One endpoint of the gateway
    for attempt in range(TRIES):  # a busy gateway gets asked again
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                              "Authorization": "Bearer " + setting("JEV_KEY")})  # the key as a bearer token
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # send and wait
                return json.loads(r.read())
        except urllib.error.HTTPError as e:  # the gateway answered with an error
            said = e.read()[:200]  # its message, short
            if e.code in BUSY and attempt < TRIES - 1:  # busy: wait as asked, then again
                time.sleep(wait_of(e.headers.get("Retry-After") if e.headers else None))
                continue
            raise DecideUnavailable(f"jev: HTTP {e.code}: {said!r}")  # a bad key, a bad question, no credit, or busy to the end
        except (OSError, ValueError) as e:  # no network, a timeout, an answer that is not JSON
            raise DecideUnavailable(f"jev: {type(e).__name__}: {e}")
    raise DecideUnavailable("jev: no answer")  # not reached: the last try returns or raises


def decide(task: str, items: list, **_) -> list:
    """Jev's decision for each item: the question Laya gets, and the item in one state, since Jev reads long states;
    one request per item. The confidence is the one Jev states for its choice; the scores are its probabilities per
    option when the gateway gives them."""
    from decide import DecideUnavailable, result  # the shared shape
    from decide.laya import question, whole_state  # the same question and readable field names
    q = question(task)  # choice over the task's labels
    out = []  # decisions in order
    for n, it in enumerate(items):  # one request per item
        t0 = time.time()  # the decision's time, network included
        got = systemone(whole_state(task, it), {"decision": q})  # the one question about this item; only the task's fields leave the PC
        ans = (got.get("answers") or {}).get("decision") or {}  # its answer
        if ans.get("type") == "refusal":  # the model declined this question
            raise DecideUnavailable(f"jev: declined to answer {task} item {n + 1}")
        label = ans.get("choice")  # the chosen option
        if label is None:  # the answer did not have the documented shape
            raise DecideUnavailable(f"jev: no choice in the answer for {task} item {n + 1}")
        probs = {k: float(v) for k, v in (ans.get("probabilities") or {}).items()}  # each option's probability, when given
        one = result(task, label, probs or None, "jev", (time.time() - t0) * 1000, model=got.get("model"))  # the served version is kept
        if ans.get("confidence") is not None:  # the model's own confidence for its choice, which need not equal the choice's probability
            one["confidence"] = float(ans["confidence"])
        out.append(one)
    return out
