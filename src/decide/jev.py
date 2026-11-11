# -*- coding: utf-8 -*-
"""The Jev backend: a hosted decision model, reached through a gateway key. Off unless switched on.

Jev has no published weights, so every decision it makes sends the decision's input (posting lines, evidence,
sentences) to the gateway and the model's maker. That breaks Offerowl's local-first default, so this backend needs
two settings, and the panel and the command line say where the inputs go:

  OFFEROWL_JEV_KEY    the gateway key (an OpenRouter key, or a key of the maker's own endpoint)
  OFFEROWL_JEV_SEND   1 means "send decision inputs off this PC"; without it nothing is sent
  OFFEROWL_JEV_URL    the gateway's address (default https://openrouter.ai/api; the maker's own is https://api.typesafe.ai)
  OFFEROWL_JEV_MODEL  the model name (default typesafe/jev-1.14 on OpenRouter; jev-latest on the maker's endpoint)

The request is the System One shape the gateway documents (POST <url>/v1/systemone with a state and typed questions);
the answer carries one typed answer per question with its probabilities. This client was written from that
documentation and tested against a local stand-in only: no key was available, so it has never talked to Jev itself.
"""
import json  # request and answer
import os  # settings
import time  # time per decision
import urllib.error  # HTTP errors
import urllib.parse  # the host name for the notice
import urllib.request  # the request

LEAVES_PC = True  # the one fact the panel must show next to this backend
DEFAULT_URL = "https://openrouter.ai/api"  # a gateway that serves Jev
DEFAULT_MODEL = "typesafe/jev-1.14"  # the gateway's name for the current release
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


def systemone(state, questions: dict, timeout: int = 60) -> dict:
    """One System One request: {"model", "state", "questions"} in, {"answers": {...}} out."""
    from decide import DecideUnavailable  # the shared failure
    st = status()  # the switches, checked on every call
    if not st["ready"]:  # nothing leaves this PC without both
        raise DecideUnavailable(f"jev: {st['why']}")
    body = {"model": setting("JEV_MODEL", DEFAULT_MODEL), "state": [state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)],
            "questions": questions}  # the state as a list of strings, as the gateway documents it
    req = urllib.request.Request(setting("JEV_URL", DEFAULT_URL).rstrip("/") + "/v1/systemone", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + setting("JEV_KEY")})  # the key as a bearer token
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # send and wait
            return json.loads(r.read())
    except urllib.error.HTTPError as e:  # the gateway refused: a bad key, a bad question, no credit
        raise DecideUnavailable(f"jev: HTTP {e.code}: {e.read()[:200]!r}")
    except (OSError, ValueError) as e:  # no network, a timeout, an answer that is not JSON
        raise DecideUnavailable(f"jev: {type(e).__name__}: {e}")


def decide(task: str, items: list, **_) -> list:
    """Jev's decision for each item: the same question and state as Laya's, one request per item. A coverage item
    sends all its evidence in one state, since Jev reads long states."""
    from decide import DecideUnavailable, result  # the shared shape
    from decide.laya import question  # the same question in the same typed shape
    q = question(task)  # choice over the task's labels
    out = []  # decisions in order
    for it in items:  # one request per item
        fields = {k: it[k] for k in it if k in ("text", "line", "evidence", "claim", "a", "b")}  # only the task's fields leave this PC
        t0 = time.time()  # the decision's time, network included
        ans = (systemone(fields if task != "line_kind" else it["text"], {"decision": q}).get("answers") or {}).get("decision") or {}  # the one answer
        label = ans.get("choice")  # the chosen option
        if label is None:  # the answer did not have the documented shape
            raise DecideUnavailable(f"jev: no choice in the answer for {task}")
        probs = {k: float(v) for k, v in (ans.get("probabilities") or {}).items()}  # each option's probability
        out.append(result(task, label, probs or None, "jev", (time.time() - t0) * 1000))
    return out
