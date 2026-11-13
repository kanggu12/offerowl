"""An application's own edition started from another edition's words. A person who keeps the sentences they last wrote as
an edition of their own (a named edition, which never goes on the board), or who applies again to work like an earlier
application's, starts the new application's resume from those words and rewrites them for its posting on the canvas.

    GET  /api/v1/editions?job=<id>        the editions with words of their own, the named editions first (routes.py)
    POST /api/v1/jobs/own/copy            {job, from, replace}: the job's own edition started from another's
    offerowl edition list [<job>]         the same list from a shell (main below: the same routes, in this process)
    offerowl edition start <job> --from <edition> [--replace]

An own edition is a workspace of its own in the job's folder (jobs/<job>/own/: own.json, form.json, its facts and its
profile; task_own.py reads it). The copy takes the source's files as they are now, builds the profile and its evidence map
again from them with the person's details as they are now (OwnFacts.rebuild), and records in own.json where it came from.
It is one undo step, which takes back the edition it replaced too. The documents brought in as files (own/files/) are never
copied: each one stands for one application's document. The target's own stay with it, and the answer names them.
"""
from __future__ import annotations

import argparse  # the command line
import json  # own.json and the answers printed
import sys  # the streams the command line prints to
from pathlib import Path  # paths

if __package__ in (None, ""):  # started as a file: make the relative imports work
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root, which holds apps/
    __package__ = "apps.api"  # noqa: A001  the package this file belongs to
    __import__("apps.api")  # the package itself

from .facts import FACT_FILES, OwnFacts  # noqa: E402  the fact files, and an edition's own facts
from .workspace import Workspace, dump_json, today, write_text  # noqa: E402  files, JSON as the workspace writes it, the day, safe writes

GENERAL = "-general"  # the edition with no job: the profile itself (app.py has the same name)
# Every file an own edition is made of, relative to its folder (jobs/<job>/own/): what it is and how it is laid out, then
# its facts. The copy and the undo step cover all of them, so a file the source lacks never stays from the edition before.
OWN_FILES = ("own.json", "form.json", *FACT_FILES)
DERIVED = ("profile/profile.json", "profile/evidence.json")  # built again from the rest, never copied: the person's details may have changed
LANGS = ("ko", "en")  # the editions a job has


def put_files(dest: Path, texts: dict) -> None:
    """An own edition's files replaced by these texts (relative path -> text), in an order in which a reader of the state,
    which takes no lock, never finds the job without an edition between two files: what the new edition lacks goes first
    (never the profile it prints, which is written or built again last), then each new file whole, the profile and its
    evidence map last. The caller holds the undo step (Workspace.change) that names every file of OWN_FILES."""
    for rel in OWN_FILES:  # a file the edition before has and this one lacks never stays behind
        if rel not in texts and rel not in DERIVED:  # the printed profile stays until its successor is written
            (dest / rel).unlink(missing_ok=True)
    for rel in sorted(texts, key=lambda r: r in DERIVED):  # the facts first, what is built from them last
        write_text(dest / rel, texts[rel])  # each one whole (a rename): never half a file


def name_of(api, jid: str) -> str:
    """An edition's name as the panel says it: a named edition's own, an application's company and role, else its id."""
    st = api.ws.job(jid) or {}  # its card
    if st.get("kind") == "edition":  # a named edition
        return str(st.get("name") or st.get("role") or jid)  # the name it was given
    return ", ".join(str(x) for x in (st.get("company"), st.get("role")) if x) or jid  # as the board's card names it


def row(api, st: dict) -> dict:
    """One edition with words of its own, as the list shows it: its id, name and kind, its languages, the day its words came
    (or were started), the edition they were started from, and whether it was submitted."""
    jid = st["id"]  # its folder name
    meta = api.tasks.own_meta(jid)  # own.json
    src = meta.get("from") if isinstance(meta.get("from"), dict) else None  # where it was started from, when it was
    return {"job": jid, "name": name_of(api, jid), "kind": "edition" if st.get("kind") == "edition" else "job",  # named edition or application
            "langs": [x for x in (meta.get("langs") or []) if x in LANGS], "at": str(meta.get("at") or ""),  # its languages, its day
            "from": {"job": str(src.get("job") or ""), "name": str(src.get("name") or "")} if src else None,  # its own origin
            "locked": bool(st.get("locked")), "created": str(st.get("created") or ""), "seq": st.get("seq") if isinstance(st.get("seq"), int) else 0}  # for the order


def listing(api, target: str | None = None) -> dict:
    """The editions with words of their own that a job's edition can start from: the named editions first (where a person
    keeps the sentences they last wrote), then the applications, each group with the newest words first. The target is left
    out, and described under "target": its languages, its own things (task_own.own_info) and whether it was submitted."""
    rows = []  # one per edition with words
    for st in api.ws.editions() + api.ws.jobs():  # named editions and applications, none in the Trash
        if st.get("id") == target:  # an edition never starts from itself
            continue
        with api.gone_meanwhile(st["id"]):  # deleted for good while this was read: left out
            if api.tasks.own_dir(st["id"]) is not None and api.tasks.own_langs(st["id"]):  # words of its own, in a language
                rows.append(row(api, st))
    rows.sort(key=lambda r: (r["at"], r["created"], r["seq"]), reverse=True)  # the newest words first
    rows.sort(key=lambda r: r["kind"] != "edition")  # then, keeping that order, the named editions before the applications
    out = {"editions": [{k: v for k, v in r.items() if k not in ("created", "seq")} for r in rows]}  # without what only sorted them
    if target:  # what the edition to start has now, for the words before a replace
        st = api.ws.job(target) or {}  # its card
        out["target"] = {"job": target, "name": name_of(api, target), "kind": "edition" if st.get("kind") == "edition" else "job",
                         "langs": api.tasks.own_langs(target), "own": api.tasks.own_info(target), "locked": bool(st.get("locked"))}
    return out


def copy(api, req: dict) -> dict:
    """Start the own edition of a job (or a named edition) from another edition's words: {job, from, replace}. Refused with
    job (no such job, or the general edition, which is the profile itself), from (no such edition to start from), locked (the
    job was submitted), same_edition, no_edition (the source has no words of its own: it prints the profile, or files brought
    in) and own_exists (the job has its own edition already, and replace was not asked). One undo step. Returns the job, the
    source, the languages, whether an edition was replaced, and the files brought in for the job, which still stand for their
    documents."""
    jid = api.need_job(req)  # the edition to start: a job or a named edition, not in the Trash
    if jid == GENERAL:  # the general edition is the profile itself: nothing to copy into
        raise ValueError("job")
    try:  # the edition to start from, checked like any job
        src = api.need_job({"job": req.get("from")})
    except ValueError as exc:  # not there, or in the Trash: said apart from the job's own refusal
        raise ValueError("from") from exc
    if src == jid:  # an edition never starts from itself
        raise ValueError("same_edition")
    replace = req.get("replace") is True  # only an explicit yes replaces the words the job has
    t = api.tasks  # the own editions' readers
    with api.ws.lock:  # the checks and the copy in one go: no other write changes either edition meanwhile
        if (api.ws.job(jid) or {}).get("locked"):  # submitted: its documents stay as they went
            raise ValueError("locked")
        sd = t.own_dir(src)  # the source's own edition, if it has one
        langs = [x for x in t.own_langs(src) if x in LANGS] if sd else []  # its languages
        if sd is None or not langs:  # no words of its own: it prints the profile, or files the person brought in
            raise ValueError("no_edition")
        replaced = t.own_dir(jid) is not None  # the job has words of its own already
        if replaced and not replace:  # never replaced unasked: the page says what would go first
            raise ValueError("own_exists")
        texts = {rel: (sd / rel).read_text(encoding="utf-8") for rel in OWN_FILES if rel not in DERIVED and (sd / rel).is_file()}  # the source as it is now
        meta = json.loads(texts.pop("own.json", "") or "{}")  # what it says of itself
        meta = meta if isinstance(meta, dict) else {}  # a broken own.json says nothing
        dest = api.ws.job_dir(jid) / "own"  # the job's own edition's folder
        label = {"code": "undo_own_copy", "company": name_of(api, jid)}  # the undo key's words: the job it changed (never the source's name: a deletion for good blanks the job's own)
        texts["own.json"] = dump_json({**meta, "langs": langs, "at": today(),  # its languages, and the day it was started
                                       "from": {"job": src, "name": name_of(api, src)}})  # where it came from: the panel says "Started from" it
        with api.ws.change(label, [f"jobs/{jid}/own/{rel}" for rel in OWN_FILES]):  # one undo step: every file of the edition, as it is before
            put_files(dest, texts)  # the source's words, layout and record in place of the edition before, if any
            t.forget_own(jid)  # nothing read from the edition before
            OwnFacts(Workspace(dest), api.facts).rebuild()  # its profile and evidence map, with the person's details as they are now
        t.forget_own(jid)  # read afresh from here on
        files = t.own_files(jid)  # the documents brought in for the job: they still stand for what would be typeset
    return {"job": jid, "from": src, "langs": langs, "replaced": replaced, "files": files}


# ---------------------------------------------------------------- the command line: offerowl edition

# The command's messages, in both languages (tests/cli/test_messages.py checks the keys and their placeholders).
MSG = {
    "en": {
        "about": "Start an application's own edition from another edition's words, and list the editions that have words of their own.",
        "help_list": "the editions with words of their own, named editions first",
        "help_start": "start JOB's own edition from another edition's words",
        "help_job_list": "leave this job out, and say what it has (its id or its name)",
        "help_job": "the job or named edition to start: its id as `list` prints it (a named edition's without its leading dash), or its name",
        "help_from": "the edition to start from: its id or its name (an id that starts with a dash goes as --from=ID)",
        "help_replace": "replace the words JOB has already (one undo in the panel brings them back)",
        "help_data": "the data folder (default: the app's)",
        "help_json": "print the API's answer as JSON",
        "head_list": "Editions with words of their own (named editions first, the newest first):",
        "none": "No edition has words of its own yet. Bring one in, or write one in the panel.",
        "line": "  {job}  {name}  [{langs}]  words of {at}",
        "line_from": "  {job}  {name}  [{langs}]  words of {at}, started from {src}",
        "kind_edition": "named edition",
        "kind_job": "application",
        "target_plain": "{name}: prints your general resume.",
        "target_own": "{name}: its own edition [{langs}], words of {at}; facts rewritten: {edited}, sentences locked: {locked}.",
        "target_from": "It was started from {src}.",
        "target_files": "Files brought in for it, which stand for their documents: {files}.",
        "target_locked": "It was submitted and locked: its documents stay as they went.",
        "done": "{name} now starts from {src} [{langs}]. One undo in the panel takes it back.",
        "done_replaced": "Its own edition before was replaced. One undo in the panel brings it back.",
        "done_files": "The files brought in for it stay, and still stand for their documents: {files}.",
        "no_job": "There is no job or named edition {job}, or it is in the Trash. `offerowl edition list` names them.",
        "no_from": "There is no edition {src}, or it is in the Trash. `offerowl edition list` names them.",
        "locked": "{job} was submitted and locked: its documents stay as they went.",
        "same": "An edition cannot start from itself.",
        "no_words": "{src} has no words of its own to start from: it prints your profile, or files you brought in.",
        "exists": "{job} has its own edition already. Add --replace to replace it: one undo in the panel brings it back.",
        "refused": "Refused: {what}",
    },
    "ko": {
        "about": "다른 판의 문장으로 지원의 판을 시작하고, 자기 문장이 있는 판을 나열한다.",
        "help_list": "자기 문장이 있는 판, 범용판 먼저",
        "help_start": "JOB의 판을 다른 판의 문장으로 시작한다",
        "help_job_list": "이 지원은 빼고, 이 지원이 가진 것을 말한다(id나 이름)",
        "help_job": "시작할 지원이나 범용판: `list`가 찍는 id(범용판은 앞의 - 없이도 된다)나 이름",
        "help_from": "바탕이 되는 판: id나 이름(-로 시작하는 id는 --from=ID 꼴로)",
        "help_replace": "JOB에 이미 있는 문장을 바꾼다(패널에서 되돌리기 한 번이면 돌아온다)",
        "help_data": "데이터 폴더(정하지 않으면 앱의 폴더)",
        "help_json": "API의 답을 JSON으로 찍는다",
        "head_list": "자기 문장이 있는 판(범용판 먼저, 최신 순):",
        "none": "자기 문장이 있는 판이 아직 없다. 판을 들여오거나 패널에서 쓴다.",
        "line": "  {job}  {name}  [{langs}]  {at} 문장",
        "line_from": "  {job}  {name}  [{langs}]  {at} 문장, {src}에서 시작함",
        "kind_edition": "범용판",
        "kind_job": "지원",
        "target_plain": "{name}: 범용 이력서를 그대로 찍는다.",
        "target_own": "{name}: 자기 판 [{langs}], {at} 문장, 고친 사실 {edited}개, 잠근 문장 {locked}개.",
        "target_from": "{src}에서 시작한 판이다.",
        "target_files": "들여온 파일이 그 서류를 대신한다: {files}.",
        "target_locked": "제출하고 잠근 지원이라 서류를 낸 그대로 둔다.",
        "done": "{name}의 판을 {src}에서 시작했다 [{langs}]. 패널에서 되돌리기 한 번이면 돌아간다.",
        "done_replaced": "전에 있던 자기 판은 바뀌었다. 패널에서 되돌리기 한 번이면 돌아온다.",
        "done_files": "들여온 파일은 그대로 두고, 여전히 그 서류를 대신한다: {files}.",
        "no_job": "지원이나 범용판을 찾지 못했다(없거나 휴지통에 있다): {job}. `offerowl edition list`로 이름을 본다.",
        "no_from": "시작할 판을 찾지 못했다(없거나 휴지통에 있다): {src}. `offerowl edition list`로 이름을 본다.",
        "locked": "제출하고 잠근 지원이라 서류를 낸 그대로 둔다: {job}",
        "same": "판은 자기 자신에서 시작할 수 없다.",
        "no_words": "시작할 자기 문장이 없는 판이다. 프로필이나 들여온 파일을 찍는다: {src}",
        "exists": "이미 자기 판이 있다: {job}. 바꾸려면 --replace를 붙인다. 패널에서 되돌리기 한 번이면 돌아온다.",
        "refused": "거절됨: {what}",
    },
}


def t(key: str, **kw) -> str:
    """A message of this command in the current language (OFFEROWL_LANG, else the locale), as the launcher's own are."""
    import llm  # src/llm.py: the one lookup every message table goes through
    return llm.message(MSG, key, **kw)


def langs_words(langs) -> str:
    """An edition's languages as the command prints them: ko, en."""
    return ", ".join(x for x in langs or [] if x in LANGS) or "-"  # a dash for none


def say_target(info: dict) -> list[str]:
    """What a job's edition has now, as lines: words of its own (with where they started) or the general resume, and the
    files brought in for it."""
    own = info.get("own") or {}  # its own things, if any
    if info.get("langs"):  # words of its own
        lines = [t("target_own", name=info.get("name") or info.get("job"), langs=langs_words(info.get("langs")), at=own.get("at") or "-",
                   edited=own.get("edited") or 0, locked=own.get("locked") or 0)]
        if own.get("from"):  # it was started from another edition
            lines.append(t("target_from", src=own["from"].get("name") or own["from"].get("job")))
    else:  # it prints the general resume
        lines = [t("target_plain", name=info.get("name") or info.get("job"))]
    if own.get("files"):  # documents brought in for it
        lines.append(t("target_files", files=", ".join(own["files"])))
    if info.get("locked"):  # submitted: it is not started again
        lines.append(t("target_locked"))
    return lines


def resolve(api, word: str) -> str:
    """The id a word on the command line means: an id as `list` prints it; a named edition's id without its leading dash (a
    shell's option parser takes "-name" for an option); a named edition's own name; or an application's company, or its
    company and role as the board writes them, when one application alone has it. Anything else as typed: the API refuses it
    in its own words."""
    word = " ".join(str(word or "").split())  # one line, single spaces
    every = api.ws.editions() + api.ws.jobs()  # named editions and applications, none in the Trash
    ids = {st["id"] for st in every}  # every id there is
    if word in ids:  # an id, as typed
        return word
    if "-" + word in ids:  # a named edition's id without its dash
        return "-" + word
    low = word.casefold()  # names compared without case
    named = [st["id"] for st in every if st.get("kind") == "edition" and str(st.get("name") or "").casefold() == low]  # by a named edition's name
    if len(named) == 1:
        return named[0]
    apps = [st["id"] for st in every if st.get("kind") != "edition" and low in (str(st.get("company") or "").casefold(), name_of(api, st["id"]).casefold())]  # by an application's name
    return apps[0] if len(apps) == 1 else word  # only a name one application alone has


def refusal(code: str, job: str, src: str) -> str:
    """A refusal of the copy in words, by the code the API gave."""
    words = {"job": lambda: t("no_job", job=job), "from": lambda: t("no_from", src=src), "locked": lambda: t("locked", job=job),  # each code's own sentence
             "same_edition": lambda: t("same"), "no_edition": lambda: t("no_words", src=src), "own_exists": lambda: t("exists", job=job)}
    return words[code]() if code in words else t("refused", what=code)  # an unknown code as the API said it


def main(argv: list | None = None) -> int:
    """`offerowl edition list [JOB]` and `offerowl edition start JOB --from EDITION [--replace]`. Exit 0 when done, 1 when the
    API refused (the reason on stderr), 2 for a wrong command line."""
    for stream in (sys.stdout, sys.stderr):  # Korean names print through any console or redirection
        if hasattr(stream, "reconfigure"):  # a text stream of this Python, not a test's replacement
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="offerowl edition", description=t("about"))  # named as the launcher calls it
    sub = ap.add_subparsers(dest="cmd", required=True)  # list or start
    ls = sub.add_parser("list", help=t("help_list"), description=t("help_list"))  # the editions to start from
    ls.add_argument("job", nargs="?", default="", help=t("help_job_list"))  # the job to leave out, said first
    st = sub.add_parser("start", help=t("help_start"), description=t("help_start"))  # the copy
    st.add_argument("job", help=t("help_job"))  # the edition to start
    st.add_argument("--from", dest="src", required=True, help=t("help_from"))  # the edition to start from
    st.add_argument("--replace", action="store_true", help=t("help_replace"))  # replace the words it has
    for p in (ls, st):  # both read the same data folder, and can print the API's own answer
        p.add_argument("--data", type=Path, default=None, help=t("help_data"))  # tests and other setups
        p.add_argument("--json", action="store_true", help=t("help_json"))  # for scripts
    a = ap.parse_args(argv)  # exits with 2 and a usage line on a wrong command line
    from .client import Client  # the API in this process, as `offerowl api` calls it
    c = Client(a.data)  # the same routes the panel calls
    job = resolve(c.api, a.job) if a.job else ""  # the id the words mean
    if a.cmd == "list":  # the editions to start from
        try:
            got = c.get("/api/v1/editions", **({"job": job} if job else {}))  # the list, without the job named
        except RuntimeError as exc:  # refused: the job named is not there
            print(refusal(str(json.loads(str(exc)).get("what") or ""), job, ""), file=sys.stderr)  # in words
            return 1
        if a.json:  # for a script
            print(json.dumps(got, ensure_ascii=False, indent=1))
            return 0
        for line in say_target(got["target"]) if got.get("target") else []:  # the job named first: what it has now
            print(line)
        print(t("head_list") if got["editions"] else t("none"))  # the list's head, or why it is empty
        for r in got["editions"]:  # one line each, its id first: what `start --from` takes
            kind = t("kind_edition") if r["kind"] == "edition" else t("kind_job")  # named edition or application
            name = f"{r['name']} ({kind})"  # its name and its kind
            if r.get("from"):  # started from another edition
                print(t("line_from", job=r["job"], name=name, langs=langs_words(r["langs"]), at=r["at"] or "-", src=r["from"]["name"] or r["from"]["job"]))
            else:
                print(t("line", job=r["job"], name=name, langs=langs_words(r["langs"]), at=r["at"] or "-"))
        return 0
    src = resolve(c.api, a.src)  # the id of the edition to start from
    try:  # start: the copy, through the route the panel's key calls
        got = c.post("/api/v1/jobs/own/copy", {"job": job, "from": src, "replace": a.replace})
    except RuntimeError as exc:  # refused, with the API's code
        code = str(json.loads(str(exc)).get("what") or "")  # the check that refused it
        if code == "own_exists":  # what a replace would take, said before the way to ask for it
            info = c.get("/api/v1/editions", job=job).get("target") or {}  # the job's edition as it is
            for line in say_target(info):
                print(line, file=sys.stderr)
        print(refusal(code, job, src), file=sys.stderr)  # why, in words
        return 1
    if a.json:  # for a script
        print(json.dumps(got, ensure_ascii=False, indent=1))
        return 0
    print(t("done", name=name_of(c.api, got["job"]), src=name_of(c.api, got["from"]), langs=langs_words(got["langs"])))  # what happened
    if got.get("replaced"):  # the words before are one undo away
        print(t("done_replaced"))
    if got.get("files"):  # the documents brought in still stand for theirs
        print(t("done_files", files=", ".join(got["files"])))
    return 0


if __name__ == "__main__":  # run as a module (the launcher) or a file
    raise SystemExit(main())  # main's answer is the exit code
