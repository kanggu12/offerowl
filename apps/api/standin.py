"""A stand-in for the agent, for the tests and the desktop app's --check: it answers Offerowl's own prompts with fixed
rules and never calls a model.

It answers through the real code path of src/llm.py, in either of two ways:
- as an OpenAI-compatible server (llm.py's `openai-compat` backend):  python3 standin.py serve <port>
- as the `claude` CLI (llm.py's `claude-code` backend), when a test puts a script named `claude` that runs
  `python3 standin.py claude "$@"` first on PATH. It also answers `claude auth status --json` with a fictional account.

The answers:
- fact extraction (src/ingest.py): one fact per line of the text; a line "Kind: org | period | title | statement" gives
  that kind (Role, Project, Education, Skill, Certificate), any other line is an "other" fact. Every quote is the line
  itself, so each fact rests on the text.
- posting analysis (src/draft.py task_jd): the skill groups whose names appear in the posting, the projects whose title
  words appear in it first.
- a sentence rewritten from its evidence (the canvas's "Regenerate from the evidence"): the evidence's first sentence,
  so the new words rest on the evidence by construction.
- the resume draft (src/write_resume.py): each text is an evidence unit's own words, and the English says only that the
  work was done as recorded, so it claims nothing the evidence must back.
- the deck's figures (src/figure_draft.py): a pipeline per project for the main slot and the side, its steps the evidence's own words.
- the profile's translation (src/draft.py task_translate): each Korean word becomes "word".
- the probe of llm.py: {"ok": true}.
"""
from __future__ import annotations

import http.server  # the OpenAI-compatible front end
import json  # prompts and answers
import re  # reading the prompts
import sys  # the CLI front end
import threading  # serving from a test
from pathlib import Path  # where src/ is

_SRC = str(Path(__file__).resolve().parents[2] / "src")  # src/ownport.py, which serve() binds with
if _SRC not in sys.path:  # run as a program (python3 apps/api/standin.py serve), the package's own start (apps/api/__init__.py) never ran
    sys.path.insert(0, _SRC)  # so src/ is found as it is for an import

ACCOUNT = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "email": "gildong@example.com",  # fictional, never a real account
           "subscriptionType": "pro"}  # a fictional account, the shape `claude auth status --json` prints
KINDS = {"role": "role", "경력": "role", "project": "project", "과제": "project", "education": "education", "학력": "education",  # Korean and English labels of the fixture lines
         "skill": "skill", "기술": "skill", "certificate": "certificate", "자격": "certificate"}  # line labels to fact kinds


def facts(text: str) -> dict:
    """One grounded fact per line of the text between <<< and >>>."""
    m = re.search(r"<<<\n(.*?)\n>>>", text, re.S)  # the file's text inside the prompt
    out = []  # the facts
    for line in (m.group(1) if m else "").splitlines():  # each line
        line = line.strip()  # no edge spaces
        if len(line) < 6 or line.startswith("#"):  # headings and blanks carry no fact
            continue  # nothing to say about such a line
        head, _, rest = line.partition(":")  # "Project: org | period | title | statement"
        parts = [p.strip() for p in rest.split("|")] if "|" in rest else []  # the labelled fields
        kind = KINDS.get(head.strip().lower()) if parts else None  # the label's kind
        if kind and len(parts) >= 3:  # a labelled line
            org, period, title = parts[0], parts[1], parts[2]  # its fields
            statement = parts[3] if len(parts) > 3 else title  # what was done
            out.append({"kind": kind, "org": org, "period": period, "title": title, "statement": statement, "quote": line[:199]})  # a labelled fact, quoted whole
        else:  # any other line is a plain fact
            out.append({"kind": "other", "org": "", "period": "", "title": line[:40], "statement": line, "quote": line[:199]})  # an unlabelled line is still a fact, quoted whole
    return {"facts": out[:40]}  # a bounded answer


def posting(text: str) -> dict:
    """The posting analysis: skill groups named in the posting, projects ordered by the posting's words."""
    jd = re.search(r"Job description:\n<<<\n(.*?)\n>>>", text, re.S)  # the posting
    jd_low = (jd.group(1) if jd else "").lower()  # for matching
    cats = json.loads(re.search(r"Skill categories: (\[.*?\])\n", text).group(1)) if "Skill categories: [" in text else []  # the names the task listed
    comps = json.loads(re.search(r"Competencies: (\[.*?\])\n", text).group(1)) if "Competencies: [" in text else []  # the strengths the task listed
    projs = re.findall(r"^- ([^:\n]+): (.*)$", text, re.M)  # "- id: title"
    focus = [c for c in cats if c.lower() in jd_low] or cats[:2]  # named groups first, else the first two
    score = lambda t: sum(1 for w in re.findall(r"[\w가-힣]{2,}", t.lower()) if w in jd_low)  # title words in the posting
    order = [pid for pid, title in sorted(projs, key=lambda p: -score(p[1]))]  # most matching first (stable)
    return {"skillsFocus": focus, "competencyWeak": [], "projectOrder": order, "_comps": len(comps)}


def units(prompt: str) -> list[tuple[str, str]]:
    """The evidence a resume draft's prompt lists: (id, text), in order. Rows of numbers and labels are left out: they say little alone."""
    part = prompt.partition("Evidence (id, then text):")[2].partition("Return JSON only")[0]  # the listing
    rows = re.findall(r"^\s*\[([^\]\n]+)\] (.+)$", part, re.M)  # [id] text
    return [(i, t.strip()) for i, t in rows if " : " not in t and not i.startswith("role:") and len(t) >= 12]  # sentences only


def said(unit: str, n: int = 90) -> str:
    """A sentence from a unit's own words: its first clause, so it rests on the evidence by construction."""
    return re.split(r"(?<=[.。])\s", unit)[0].rstrip(".").strip()[:n].strip()  # the first sentence, bounded


def part(unit_id: str, unit: str, mark: bool = False) -> dict:
    """One text in both languages. The English says nothing the evidence must back: it claims no number, name or tool."""
    ko = said(unit)  # the unit's own words
    if mark:  # the part asks for one highlighted phrase
        words = ko.split()  # the phrase is its last words
        ko = " ".join(words[:-2] + ["==" + " ".join(words[-2:]) + "=="]) if len(words) > 2 else "==" + ko + "=="  # marked
    return {"ko": ko, "en": ("Worked on this as ==the record describes==" if mark else "Worked on this as the record describes"), "ev": [unit_id], "names": {}}  # with its id


def write_parts(prompt: str) -> dict:
    """The resume draft (src/write_resume.py): every text is an evidence unit's own words, so it passes the checks by construction."""
    shape = prompt.partition("Return JSON only")[2]  # the answer's shape names the stage
    rows = units(prompt)  # the evidence
    if '{"roles"' in shape:  # the work-history items
        out = []  # one per role
        for head, body in re.findall(r"^## (\S+)\n(.*?)(?=^## |\Z)", prompt.partition("Evidence (id, then text):")[2], re.M | re.S):  # each role's listing
            items = []  # one per project
            for pid in re.findall(r"^([\w-]+): ", body, re.M):  # each project
                own = [(i, t) for i, t in rows if i.startswith(pid + "#")][:3]  # its blocks
                if own:  # something to say
                    title = said(own[0][1], 28)  # its own words
                    items.append({"project": pid, "title": {"ko": title, "en": "Project work"}, "short": {"ko": title[:14].strip(), "en": "Project"},  # both names
                                  "sentences": [{"part": k, **part(i, t, k == "result")} for k, (i, t) in zip(("scope", "decision", "result"), own)]})  # the sentences
            out.append({"key": head, "items": items})  # the role
        return {"roles": out}
    if '{"headline"' in shape:  # the top of the resume
        first = rows[:6] or [("", "")]  # the first blocks
        pids = list(dict.fromkeys(i.split("#")[0] for i, _ in rows if "#" in i))[:3]  # the projects it names
        cards = [{"key": k, **part(*first[n % len(first)])} for n, k in enumerate(("target", "strength", "scale", "domain"))]  # four cards
        lights = [{"project": pid, "title": {"ko": said(next(t for i, t in rows if i.startswith(pid + "#")), 28), "en": "Project work"},  # a card per project
                   "rows": [{"key": k, **part(*own[n % len(own)], k == "result")} for n, k in enumerate(("challenge", "action", "result"))]}   # each slot its own block, as a writer would
                  for pid in pids for own in [[(i, t) for i, t in rows if i.startswith(pid + "#")]]]
        return {"headline": part(*first[0]), "intro": part(*first[1 % len(first)], True), "cards": cards, "highlights": lights}
    if '{"stats"' in shape:  # the deck's opening slides
        short = lambda i, t, n: {"ko": said(t, n), "en": "Worked on this as recorded", "ev": [i], "names": {}}  # noqa: E731  a line short enough for the cover
        tiles = [{"value": {"ko": said(t, 8), "en": "Result"}, **short(i, t, 28)} for i, t in rows[:4]]  # four tiles from the first blocks
        cols = [{"title": {"ko": said(t, 10), "en": "Focus"}, **short(i, t, 40)} for i, t in rows[4:8]]  # four columns from the next ones
        path = [{"role": i.split(":", 1)[1], "phase": {"ko": "경력", "en": "Work"}, "key": {"ko": said(t, 20), "en": "As recorded"}, **short(i, t, 20)} for i, t in re.findall(r"^\s*\[?(role:[\w-]+)\]?:? (.+)$", prompt, re.M)]  # a station per role, from its head
        return {"stats": tiles, "focus": cols, "journey": path}  # no contents or glance line: they are optional
    if '{"competencies"' in shape:  # the strengths
        return {"competencies": [{"name": {"ko": said(t, 16), "en": "Strength"}, **part(i, t)} for i, t in rows[:4]]}
    if '{"about"' in shape:  # the about-me and the motivation
        first = rows[:4] or [("", "")]  # the first blocks
        return {"about": [{"title": {"ko": said(first[0][1], 16), "en": "How I work"}, "sentences": [part(i, t) for i, t in first[:2]]}], "motivation": [part(*first[-1])]}
    return {"parts": []}  # a repair: what failed stays failed, and the draft drops it


def translate(prompt: str) -> dict:
    """The profile's translation (src/draft.py task_translate): each Korean word becomes "word", so numbers, Latin names and
    the shape of a table survive, and nothing new is claimed."""
    m = re.search(r"Fields \(JSON object id -> Korean\):\n(\{.*?\})\n", prompt, re.S)  # the fields asked for
    fields = json.loads(m.group(1)) if m else {}  # id -> Korean
    return {"t": {k: re.sub(r"[가-힣]+", "word", v) for k, v in fields.items()}}  # every id answered


def figures(prompt: str) -> dict:
    """The deck's figures (src/figure_draft.py): one pipeline per project whose steps are its evidence's own first words, with no number."""
    pair = "Write every shown text as a pair" in prompt  # two languages
    out = []  # one per project
    for pid, body in re.findall(r"^### Project (\S+?): .*?\nEvidence:\n<<<\n(.*?)\n>>>", prompt, re.M | re.S):  # each project asked about
        words = []  # the steps
        for line in body.splitlines():  # the evidence's lines
            picked = [w for w in re.findall(r"[가-힣]{2,}", line)][:2]  # plain Korean words: no number, no name of a tool
            if len(picked) == 2 and " ".join(picked) not in words:  # a step
                words.append(" ".join(picked))  # kept
        steps = [[{"ko": w, "en": ("First", "Next", "Last")[k]} if pair else w] for k, w in enumerate(words[:3])]  # at most three
        if len(steps) >= 3:  # a real sequence
            cap = {"ko": "**단계** 근거의 낱말", "en": "**Steps** from the record"} if pair else "**Steps** from the record"  # the caption
            fig = {"type": "pipeline", "caption": cap, "steps": steps}  # three steps fit the main frame and the side column alike
            out.append({"id": pid, "why": "its evidence", "pages": [{"page": 0, "main": fig, "side": dict(fig)}]})  # a page with a main figure keeps it and takes the side one
    return {"projects": out}  # the shape the step asks for


def scene(prompt: str) -> dict:
    """An interview scene (src/interview/draft.py): a general way of working in the present tense, which claims nothing of the person."""
    m = re.search(r"^Planned question: (.+)$", prompt, re.M)  # the question it answers
    q = m.group(1).strip() if m else "What do you do first?"  # as asked
    return {"title_ko": "질문", "title_en": q[:90], "key": "기록부터 봅니다", "caution": "",  # the card's head
            "lines": [["면접관", q], ["해석", "이 질문에 어떻게 답하시겠어요?"],  # the question and its translation
                      ["나", "In general, / I read the **logs** first, / and then I check ==what changed last==."], ["해석", "일반적으로 저는 기록을 먼저 읽고, 그다음 마지막으로 바뀐 것을 확인합니다."]]}  # the answer and its translation


def expected() -> dict:
    """The expected questions of a job (src/interview/plan.py anticipate): one of each kind, the same for every job."""
    return {"questions": [{"kind": "scenario", "en": "A service stops answering at night. What do you do?", "ko": "밤에 서비스가 응답을 멈춥니다. 어떻게 하시겠어요?"},
                          {"kind": "technical", "en": "How do you read a slow request in the logs?", "ko": "느린 요청을 기록에서 어떻게 읽나요?"}]}  # both kinds


def talk(prompt: str) -> dict:
    """The talk's words (src/interview/talk_write.py): every text is an evidence unit's own words with its id, so it passes the
    checks by construction; the slides it names are the first ones the prompt lists."""
    rows = units(prompt) or [("", "")]  # the evidence
    keys = re.findall(r"^([\w-]+) \| ", prompt.partition("The slides")[2].partition("Evidence (id, then text):")[0], re.M)  # the slides' keys, in order
    pages = [k for k in keys if re.match(r"pf\d+$", k)] or keys[:1]  # the portfolio's pages first
    pick = lambda n: rows[n % len(rows)]  # noqa: E731  the n-th unit, round and round
    line = lambda n, k=60: {"text": said(pick(n)[1], k), "ev": [pick(n)[0]], "slides": pages[n % len(pages):n % len(pages) + 1] if pages else []}  # noqa: E731
    if "framing words of a talk" in prompt:  # the messages and the parts
        parts = re.findall(r"^(\d+) \| ", prompt.partition("The parts")[2].partition("The slides")[0], re.M)
        return {"messages": [{"title": said(pick(i)[1], 14), **line(i)} for i in range(3)],
                "parts": [{"part": int(n), "what": said(pick(i)[1], 40), "core": said(pick(i + 1)[1], 30), "lead": said(pick(i + 2)[1], 90), "ev": [pick(i)[0], pick(i + 1)[0], pick(i + 2)[0]]} for i, n in enumerate(parts)]}
    if "says why the person wants this job" in prompt:  # why this job
        return {"why": {"lede": said(pick(0)[1], 60), "ev": [pick(0)[0]],
                        "cards": [{"title": "경험", "text": said(pick(i)[1], 70), "ev": [pick(i)[0]]} for i in range(3)], "close": ""}}
    if "tell the hardest problem" in prompt:  # the story in three slides
        part = lambda i: {"title": "경과", "sub": said(pick(i)[1], 30), "lede": said(pick(i)[1], 60), "ev": [pick(i)[0]],  # noqa: E731
                          "cards": [{"title": "경과", "text": said(pick(i + j)[1], 80), "ev": [pick(i + j)[0]]} for j in range(3)]}
        box = lambda i: {"title": ["기존 구조", "새 요구", "제약", "측정", "합의", "결과"][i % 6], "sub": ""}  # noqa: E731  a box that names nothing the evidence must back
        return {"problem": {**part(0), "sides": [{"title": "현재", "items": [box(0), box(2)]}, {"title": "요구", "items": [box(1), box(3)]}],
                            "question": said(pick(6)[1], 60), "scope": {"text": said(pick(7)[1], 70), "ev": [pick(7)[0]]}},
                "approach": {**part(3), "steps": [box(3 + j) for j in range(3)]}, "result": part(6)}
    if "what the person's work taught them" in prompt:  # the lessons and any topic of the person's own
        out = {"lessons": [{"title": said(pick(i)[1], 30), "text": said(pick(i)[1], 110), "learned": "", "slides": line(i)["slides"], "ev": [pick(i)[0]]} for i in range(4)]}
        own = re.findall(r'"part": (\d+), "lede"', prompt.partition("What to write:")[2].partition("Return JSON only")[0])
        if own:
            out["points"] = [{"part": int(n), "lede": said(pick(0)[1], 80), "ev": [pick(0)[0]], "cards": [{"title": "요점", "text": said(pick(j)[1], 70), "ev": [pick(j)[0]]} for j in range(3)]} for n in own]
        return out
    if "the career plan slide of a job-interview talk" in prompt:  # the plan: intentions in plain words that name nothing
        phase = lambda w: {"when": w, "title": "익히기", "basis": "", "items": ["업무 흐름 익히기", "기존 문서 읽기", "팀과 기준 맞추기"], "output": "정리한 문서", "metric": "", "box": {"title": "", "items": []}}  # noqa: E731
        return {"plan": {"lede": "", "phases": [phase("처음"), phase("다음"), phase("그 뒤")], "gaps": "", "ev": []}}
    if "says over each slide of a talk" in prompt:  # the script
        listed = re.findall(r"^([\w-]+) \| (\d+) \| ", prompt.partition("The slides (key")[2].partition("Evidence (id, then text):")[0], re.M)
        return {"slides": [{"key": k, "lines": [{"text": said(pick(i + j)[1], 90), "ev": [pick(i + j)[0]]} for j in range(2)], "cue": "", "short": "", "questions": []}
                           for i, (k, _) in enumerate(listed)]}
    return {}


def answer(prompt: str) -> str:
    """The stand-in's reply to one of Offerowl's prompts, as the text a model would write."""
    if "job-interview talk" in prompt or "a talk one person gives in a job interview" in prompt or "a talk in a job interview" in prompt:  # src/interview/talk_write.py
        return json.dumps(talk(prompt), ensure_ascii=False)  # the talk's words from the evidence
    if "You write one interview scene" in prompt:  # src/interview/draft.py
        return json.dumps(scene(prompt), ensure_ascii=False)  # one script
    if "You check one interview scene" in prompt:  # src/interview/draft.py, the second reading
        return json.dumps({"problems": []})  # the stand-in's scenes claim nothing of the person
    if "preparing to interview a candidate" in prompt:  # src/interview/plan.py anticipate
        return json.dumps(expected(), ensure_ascii=False)  # the expected questions
    if "Translate each Korean resume field" in prompt:  # src/draft.py task_translate
        return json.dumps(translate(prompt), ensure_ascii=False)  # every field, word for word
    if "Some numbers in these projects can be shown as a chart" in prompt:  # src/figure_draft.py, the measured step
        return json.dumps({"projects": []})  # no chart: the stand-in claims no number of its own
    if "Propose figure data for portfolio slides" in prompt:  # src/figure_draft.py
        return json.dumps(figures(prompt), ensure_ascii=False)  # one figure per project
    if "Evidence (id, then text):" in prompt:  # src/write_resume.py
        return json.dumps(write_parts(prompt), ensure_ascii=False)  # every part from the evidence's own words
    if "Whose documents are these?" in prompt:  # apps/api/autopilot.py, the contact step
        m = re.search(r"^\s*(?:이름\s*[:：]\s*)?([가-힣]{2,4})\s*$", prompt.partition("<<<")[2], re.M)  # a line that is a Korean name alone
        return json.dumps({"name": m.group(1) if m else "", "name_en": ""}, ensure_ascii=False)  # "" when the text writes none
    if "List every career fact in this text" in prompt:  # src/ingest.py
        return json.dumps(facts(prompt), ensure_ascii=False)
    if "Pick what this job needs" in prompt:  # src/draft.py task_jd
        out = posting(prompt)  # the analysis
        out.pop("_comps", None)  # only the keys the task asks for
        return json.dumps(out, ensure_ascii=False)
    if "You write one answer to a job application's question" in prompt:  # apps/api/answers.py
        m = re.search(r"^Limit: (\d+) (\w+)", prompt, re.M)  # the question's limit and how the form counts it
        limit, by_words = (int(m.group(1)), m.group(2) == "words") if m else (300, False)
        size = (lambda x: len(x.split())) if by_words else len  # noqa: E731  words or characters
        rows = re.findall(r"^\[([^\]]+)\] (.+)$", prompt.partition("each after its id in brackets:")[2], re.M)  # the facts, with their ids
        words, cites = "", []  # the answer, and what it rests on
        for fid, text in rows:  # the facts' own words, in the order given, until the limit is nearly used
            body = text.partition(": ")[2] or text  # without the company and title in front
            if size((words + " " + body).strip()) > limit:  # full
                break
            words, cites = (words + " " + body).strip(), cites + [fid]
        return json.dumps({"answer": words, "cites": cites}, ensure_ascii=False)  # grounded by construction
    if "Rewrite this resume sentence" in prompt:  # the canvas's regenerate (apps/api/tasks.py _regen)
        ev = re.search(r"Evidence:\n<<<\n(.*?)\n>>>", prompt, re.S)  # the evidence block
        first = re.split(r"(?<=[.!?다])\s+", (ev.group(1) if ev else "").strip().splitlines()[0] if ev and ev.group(1).strip() else "")[0]  # its first sentence
        return json.dumps({"text": first.replace("==", "")}, ensure_ascii=False)  # grounded by construction
    if '{"ok": true}' in prompt:  # llm.py --probe
        return '{"ok": true}'
    return json.dumps({"error": "the stand-in does not know this task"})  # anything else fails its key check


class Handler(http.server.BaseHTTPRequestHandler):
    """/v1/chat/completions and /v1/models as an OpenAI-compatible server answers them."""

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")  # JSON reply
        self.send_response(code)  # status first
        self.send_header("Content-Type", "application/json")  # always JSON
        self.send_header("Content-Length", str(len(data)))  # so the client knows where the body ends
        self.end_headers()  # headers done
        self.wfile.write(data)  # the body

    def do_GET(self):  # noqa: N802  (http.server's names)
        if self.path.startswith("/v1/models"):  # llm.py's local server check
            return self._send(200, {"data": [{"id": "standin"}]})  # one model
        return self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)  # body length
        body = json.loads(self.rfile.read(n) or b"{}")  # the request
        msgs = body.get("messages") or []  # system and user
        prompt = "\n".join(str(m.get("content") or "") for m in msgs if m.get("role") == "user")  # the user's text
        return self._send(200, {"choices": [{"message": {"role": "assistant", "content": answer(prompt)}}]})

    def log_message(self, *_):  # quiet
        pass  # no request lines in the test output


def serve(port: int = 0) -> http.server.ThreadingHTTPServer:
    """Start the stand-in on 127.0.0.1 (a free port when 0) in a thread and return the server."""
    from ownport import Server  # src/ownport.py: the port held alone, on Windows too
    srv = Server(("127.0.0.1", port), Handler)  # loopback only
    threading.Thread(target=srv.serve_forever, daemon=True, name="standin").start()  # in the background
    return srv


def as_claude(argv: list) -> int:
    """The `claude` CLI as src/llm.py and apps/api/agent.py call it."""
    if argv[:2] == ["auth", "status"]:  # the agent card
        print(json.dumps(ACCOUNT))  # the agent card reads this
        return 0
    if argv[:2] == ["auth", "login"]:  # a sign-in from the panel: nothing to do
        return 0
    if "-p" in argv:  # one prompt on stdin, the answer on stdout
        prompt = sys.stdin.read()  # the prompt comes on stdin, as llm.py sends it
        text = answer(prompt)  # the answer's text
        if "json" in argv:  # --output-format json: the CLI's result object, with its usage
            print(json.dumps({"type": "result", "is_error": False, "result": text, "total_cost_usd": 0,
                              "usage": {"input_tokens": len(prompt) // 4, "output_tokens": len(text) // 4}, "modelUsage": {"claude-opus-5-5": {}}}, ensure_ascii=False))
        else:
            print(text)
        return 0
    return 1  # anything else is not a call Offerowl makes


if __name__ == "__main__":  # run as a program
    if sys.argv[1:2] == ["serve"]:  # python3 standin.py serve <port>
        srv = serve(int(sys.argv[2]) if len(sys.argv) > 2 else 0)  # a port to bind, or a free one
        print(srv.server_address[1], flush=True)  # the port, for whoever started it
        threading.Event().wait()  # until stopped
    elif sys.argv[1:2] == ["claude"]:  # python3 standin.py claude <args>
        raise SystemExit(as_claude(sys.argv[2:]))  # the CLI front end's exit code
    else:
        print(__doc__)  # how to use it
        raise SystemExit(1)  # an unknown command is a failure
