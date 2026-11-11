"""The talk's own words, written by the AI backend from the person's evidence (src/interview/talk.py calls write()).

Six kinds of call, each only when the talk has the part that needs it: the frame (the messages and each part's opening), why
this job, the story (the hardest problem in three slides), the lessons (and the person's own topics), the plan, and the script (what to say over each slide, with where to point, the line to
say when time runs short and the questions to expect). Every sentence cites evidence ids and faces the resume's checks
(src/write_resume.py: numbers, names and tools against the cited evidence, claims no stronger than the evidence, the style
pack's words); a failing sentence is sent back once with its reasons and dropped if it still fails. A slide that loses its words
falls back to what the documents already say.
"""
from __future__ import annotations

import json  # the ledger and the answers
import pathlib  # paths
import re  # names, numbers and keys
import sys  # the import path

SRC = pathlib.Path(__file__).resolve().parent.parent  # src/
if str(SRC) not in sys.path:  # write_resume, cover and llm import as top-level modules
    sys.path.insert(0, str(SRC))

import cover as C  # noqa: E402  posting lines, terms, names
import llm  # noqa: E402  the one way to a model
import write_resume as WR  # noqa: E402  the checking context, the draft and its repair round

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"  # talk_*.md
SYSTEM = ("You write the words of a job-interview talk from facts the person gave. Use only the facts in the evidence you cite. Never add "
          "numbers, tools, names, clients or results the evidence does not state, and never make the person's part larger than the evidence "
          "gives it. Answer with JSON only.")
LANG_NAME = {"ko": "Korean", "en": "English"}  # the talk's language in the prompts
UNIT = {"ko": "Korean characters", "en": "English words"}  # how a length is counted
SPOKEN = {"ko": "polite spoken Korean that ends in ~습니다 or ~입니다, short sentences, the person speaking as 저",
          "en": "plain spoken English in the first person, short sentences"}
SLIDE_STYLE = {"ko": "Slide text (titles, boxes, cards) in Korean ends like a portfolio's cards: with a noun or a nominal form (~함, ~음, ~구축), never ~습니다; a lede or a lead is a full sentence ending in ~습니다.",
               "en": "Slide text in English: titles and boxes as noun phrases, card texts and ledes as plain sentences."}
WORD_LABEL = {"ko": {"close": "하고 싶은 일", "gap": "채울 것", "mine": "제 몫"}, "en": {"close": "What I want to do", "gap": "To build", "mine": "My part"}}
LIMITS = {"ko": {"msg_title": 18, "msg_text": 60, "what": 50, "core": 40, "lead": 120, "head": 24, "ev_text": 40, "sub": 40, "lede": 80, "box": 16, "card": 90, "when": 10, "item": 50, "lesson": 130},
          "en": {"msg_title": 5, "msg_text": 16, "what": 14, "core": 12, "lead": 32, "head": 6, "ev_text": 10, "sub": 10, "lede": 22, "box": 4, "card": 24, "when": 4, "item": 14, "lesson": 34}}
PACE = {"ko": 215, "en": 135}  # the middle of a speakable pace: Korean characters or English words a minute


class Stopped(Exception):
    """The model could not be reached or stopped; the talk keeps the documents' own words."""


def prompt(name: str, **kw) -> str:
    """A talk prompt with its {{key}} placeholders filled."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in kw.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text.strip()


def keys_in(v, allowed: set) -> list:
    """The slide keys a model answer names, kept only when the talk has them."""
    return [k for k in dict.fromkeys(str(x).strip() for x in C.as_list(v)) if k in allowed]


class Writer:
    """One run of the talk's words: the checking context, the draft of every text, the calls made."""

    def __init__(self, *, job, brief: dict, info: dict, posting: dict | None, slides: list, talk: dict, backend, log):
        self.job, self.brief, self.info, self.slides, self.talk, self.log = job, brief, info, slides, talk, log  # the run's inputs
        self.lang = brief["lang"]  # the talk's one language
        self.backend = backend  # None: OFFEROWL_LLM decides
        led = job.profile_path  # the confirmed facts: what every sentence is held against
        if not led or not pathlib.Path(led).is_file():
            raise Stopped("no profile to hold the talk's words against")
        self.ledger = json.loads(pathlib.Path(led).read_text(encoding="utf-8"))
        hints = [str(job.workspace)] if job.workspace else []  # a workspace's own style packs
        try:
            self.style = WR.load_style(job.kit.get("style") or None, hints)  # the kit's pack, else the default
        except SystemExit:  # a kit naming a pack the resume loader cannot read: the default pack
            self.style = WR.load_style(None, hints)
        post_path = job.in_job(job.kit.get("posting", "posting.md"))
        self.posting_text = post_path.read_text(encoding="utf-8") if post_path and post_path.is_file() else ""
        self.post = WR.posting_of(self.posting_text)  # company, role, overview, lines
        self.items = (posting or {}).get("items") or []  # the posting's lines with their kinds
        notes = []  # the person's own research on the company
        for f in sorted((job.dir / "research").glob("*.md")) if (job.dir / "research").is_dir() else []:
            notes.append(f.read_text(encoding="utf-8")[:4000])
        self.company_notes = ((self.post or {}).get("overview", "") + "\n" + "\n".join(notes)).strip()[:8000]
        if self.post is not None:  # the company's words may stand in why and the plan
            self.post = {**self.post, "overview": self.company_notes}
        self.ctx = WR.Ctx(self.ledger, self.style, self.post)  # the units in both languages, the vocabularies, the glossary
        self.dr = WR.Draft(self.ctx, (self.lang,))  # every text and its checks
        self.U = self.ctx.U[self.lang]  # the evidence in the talk's language
        self.keys = {s["key"] for s in slides}  # the slides a text may name
        self.pids = self.page_projects()  # slide key -> the ledger projects it shows
        self.calls = 0  # model calls made
        self.answers = []  # every answer as the model wrote it

    # ----- the model -----

    def ask(self, task: str, text: str, required: tuple) -> dict:
        """One call; an answer in the wrong shape counts as none."""
        self.calls += 1
        try:
            out = llm.run(task, text, system=SYSTEM, want_json=True, required=required, backend=self.backend, timeout=900)
        except llm.LLMUnavailable as e:  # no backend, or it stopped
            raise Stopped(str(e))
        except ValueError:  # it answered, but never in the right shape
            out = None
        self.answers.append({"task": task, "answer": out})
        return out if isinstance(out, dict) else {}

    # ----- evidence -----

    def page_projects(self) -> dict:
        """Each portfolio page of the talk with the ledger projects it shows: by title, else by the words they share."""
        meta = self.U.get("meta") or {}  # pid -> {org, title, period}
        out = {}
        for s in self.slides:
            if s["kind"] != "page":
                continue
            t = re.sub(r"[\W_]+", "", (s.get("title") or "")).lower()
            hit = [pid for pid, m in meta.items() if t and (re.sub(r"[\W_]+", "", m.get("title", "")).lower() in (t,) or
                                                       (len(t) >= 6 and t in re.sub(r"[\W_]+", "", m.get("title", "")).lower()) or
                                                       (len(re.sub(r"[\W_]+", "", m.get("title", ""))) >= 6 and re.sub(r"[\W_]+", "", m.get("title", "")).lower() in t))]
            if not hit:  # titles that differ: the project whose blocks share the most terms with the page
                q = set(C.terms((s.get("title") or "") + " " + (s.get("tag") or "")))
                best = sorted(((len(q & set(C.terms(" ".join(self.U["index"][b]["text"] for b in self.U["proj"].get(pid, [])[:6])))), pid) for pid in self.U["proj"]), reverse=True)
                hit = [best[0][1]] if best and best[0][0] >= 2 else []
            out[s["key"]] = hit
        return out

    def listing(self, pids, limit: int = 12, extra=()) -> str:
        """The evidence lines of some projects (their head, then their blocks) and some loose units."""
        out, seen = [], set()
        for pid in pids:
            if pid in seen or pid not in self.U["proj"]:
                continue
            seen.add(pid)
            out.append(f"\n{pid}: {self.U['heads'].get(pid, pid)}")
            out += ["  " + WR.unit_line(self.U, b) for b in self.U["proj"][pid][:limit]]
        loose = [u["id"] for u in self.U["units"] if u["kind"] in ("role", "skills", "education", "section") or WR.CITABLE_LOOSE.match(u["id"])]
        out += [WR.unit_line(self.U, u) for u in list(dict.fromkeys(list(extra) + loose)) if u in self.U["index"]]
        return "\n".join(out).strip()

    def shown_pids(self) -> list:
        """The ledger projects the talk's pages show, in the talk's order."""
        return list(dict.fromkeys(p for s in self.slides if s["kind"] == "page" for p in self.pids.get(s["key"], [])))

    def common(self) -> dict:
        """What every prompt shares."""
        return {"language": LANG_NAME[self.lang], "request": self.brief.get("request") or ", ".join(t["title"] for t in self.brief["topics"]),
                "minutes": self.brief["minutes"], "rules": WR.rules_text(self.style), "target": WR.target_text(self.post, overview=True),
                "style_line": SLIDE_STYLE[self.lang], **{k: f"{v} {UNIT[self.lang]}" for k, v in LIMITS[self.lang].items()}}

    def slide_lines(self, kinds=None) -> str:
        """The talk's slides as the prompts list them."""
        rows = []
        for s in self.slides:
            if kinds and s["kind"] not in kinds:
                continue
            rows.append(f"{s['key']} | {s['part'] + 1} | {s['kind']} | {s.get('title') or s.get('name') or ''} | {s.get('tag') or s.get('period') or ''}")
        return "\n".join(rows)

    # ----- checking -----

    def add(self, at: str, kind: str, text, ev=(), names=None, marks=(0, 0), frame=False) -> dict:
        """Register one text and check it; returns its entry (its 'gone' flag says whether it survived)."""
        obj = {self.lang: " ".join(str(text or "").split()), "ev": list(ev or []), "names": names or {}}
        return self.dr.add(at, kind, obj, marks=marks, frame=frame)[self.lang]

    def style_only(self, at: str, text) -> dict:
        """A text that states no fact of the person: where to point, a question an interviewer asks, a sentence that leads to the
        next slide. Only the style pack's words; one with a number or a name in it is a fact after all, and goes through the full
        check. Every other text, a label included, rests on the evidence of the part it belongs to."""
        t = " ".join(str(text or "").split())
        if re.search(r"\d", t) or any(C.name_like(p, ini) for p, ini in C.name_parts(t)):  # a number or a name: it must rest on evidence
            return self.add(at, "about", t)
        e = {"at": at, "kind": "style", "lang": self.lang, "text": t, "ev": [], "names": {}, "frame": True, "limit": None, "marks": (0, 0), "round": "draft",
             "issues": WR.style_issues(t, self.lang, "about", self.style) if t else [WR.issue("empty")]}
        self.dr.texts.append(e)
        return e

    @staticmethod
    def ok(e) -> str:
        """A text that survived, else ''."""
        return e["text"] if e and not e.get("gone") and e.get("text") else ""

    # ----- the calls -----

    def frame(self) -> dict:
        """The three messages and each part's what, core and lead."""
        parts = "\n".join(f"{i + 1} | {t['title']} | {', '.join(t['kinds'])}" for i, t in enumerate(self.brief["topics"]))
        got = self.ask("talk-frame", prompt("talk_frame", **self.common(), parts=parts, slides=self.slide_lines(),
                                            evidence=self.listing(self.shown_pids(), 6)), ("messages",))
        out = {"messages": [], "parts": {}}
        for i, m in enumerate([m for m in C.as_list(got.get("messages")) if isinstance(m, dict)][:3]):
            ev = WR.ids_of(m)
            out["messages"].append({"title": self.add(f"messages.{i}.title", "title", m.get("title"), ev), "text": self.add(f"messages.{i}.text", "about", m.get("text"), ev),
                                    "keys": keys_in(m.get("slides"), self.keys)})
        for p in [p for p in C.as_list(got.get("parts")) if isinstance(p, dict)]:
            try:
                n = int(p.get("part")) - 1
            except (TypeError, ValueError):
                continue
            if not 0 <= n < len(self.brief["topics"]):
                continue
            ev = WR.ids_of(p)
            future = any(k in ("motivation", "plan") for k in self.brief["topics"][n]["kinds"])  # a wish needs no evidence
            out["parts"][n] = {k: self.add(f"parts.{n}.{k}", "motivation" if future else ("title" if k != "lead" else "about"), p.get(k), ev, frame=future and not ev)
                               for k in ("what", "core", "lead") if p.get(k)}
        return out

    def why(self) -> dict:
        """Why this job: the person's reasons from their record and the posting's own words."""
        got = self.ask("talk-why", prompt("talk_why", **self.common(), posting="\n".join(f"{i + 1} | {it['kind']} | {it['text']}" for i, it in enumerate(self.items[:30])) or "(none)",
                                          company=self.company_notes or "(none)", evidence=self.listing(self.shown_pids(), 8)), ("why",))
        w = got.get("why") if isinstance(got.get("why"), dict) else {}
        if not w:
            return {}
        return {"lede": self.add("why.lede", "motivation", w.get("lede"), WR.ids_of(w), frame=not WR.ids_of(w)),
                "cards": [{"title": self.add(f"why.card.{i}.title", "motivation", c.get("title"), WR.ids_of(c), frame=not WR.ids_of(c)), "text": self.add(f"why.card.{i}.text", "motivation", c.get("text"), WR.ids_of(c), frame=not WR.ids_of(c))}
                          for i, c in enumerate([c for c in C.as_list(w.get("cards")) if isinstance(c, dict)][:3])],
                "close": self.add("why.close", "motivation", w.get("close"), [], frame=True)}

    def duties(self) -> list:
        """The posting's duty lines, else its first lines."""
        return [it for it in self.items if it["kind"] == "duty"] or self.items

    def story(self) -> dict:
        """The hardest problem in three slides."""
        page = next((s for s in self.slides if s["kind"] == "page" and any(x["kind"] == "problem" and x["part"] == s["part"] for x in self.slides)), None)
        pids = self.pids.get(page["key"], []) if page else []
        if not pids:  # no project to tell
            return {}
        head = self.U["heads"].get(pids[0], pids[0])
        got = self.ask("talk-story", prompt("talk_story", **self.common(), project=head, evidence=self.listing(pids, 40)), ("problem", "approach", "result"))
        out = {}
        for k in ("problem", "approach", "result"):
            x = got.get(k) if isinstance(got.get(k), dict) else {}
            if not x:
                continue
            ev = WR.ids_of(x)
            s = {"title": self.add(f"{k}.title", "title", x.get("title"), ev), "sub": self.add(f"{k}.sub", "title", x.get("sub"), ev),
                 "lede": self.add(f"{k}.lede", "about", x.get("lede"), ev, marks=(0, 1)),
                 "cards": [{"title": self.add(f"{k}.card.{i}.title", "title", c.get("title"), WR.ids_of(c) or ev), "text": self.add(f"{k}.card.{i}.text", "about", c.get("text"), WR.ids_of(c) or ev)}
                           for i, c in enumerate([c for c in C.as_list(x.get("cards")) if isinstance(c, dict)][:4])]}
            if k == "problem":
                s["sides"] = [{"title": self.add(f"problem.side.{i}.title", "title", d.get("title"), ev),
                               "items": [{"title": self.add(f"problem.side.{i}.{j}.t", "title", b.get("title"), ev), "sub": self.add(f"problem.side.{i}.{j}.s", "title", b.get("sub"), ev) if b.get("sub") else None}
                                         for j, b in enumerate([b for b in C.as_list(d.get("items")) if isinstance(b, dict)][:4])]}
                              for i, d in enumerate([d for d in C.as_list(x.get("sides")) if isinstance(d, dict)][:2])]
                s["question"] = self.add("problem.question", "about", x.get("question"), ev) if x.get("question") else None
                sc = x.get("scope") if isinstance(x.get("scope"), dict) else {"text": x.get("scope"), "ev": ev}
                s["scope"] = self.add("problem.scope", "about", sc.get("text"), WR.ids_of(sc) or ev) if sc.get("text") else None
            if k == "approach":
                s["steps"] = [{"title": self.add(f"approach.step.{i}.t", "title", b.get("title"), ev), "sub": self.add(f"approach.step.{i}.s", "title", b.get("sub"), ev) if b.get("sub") else None}
                              for i, b in enumerate([b for b in C.as_list(x.get("steps")) if isinstance(b, dict)][:5])]
            out[k] = s
        out["_page"] = page["key"] if page else None
        return out

    def lessons(self, want_lessons: bool, custom: list) -> dict:
        """What the work taught, and the person's own topics."""
        if not want_lessons and not custom:
            return {}
        what, shape = [], {}
        L = LIMITS[self.lang]
        if want_lessons:
            what.append(f'- "lessons": four to six principles the work taught, each from a real event in the evidence: {{"title": the principle as a short sentence (at most {L["lede"]} {UNIT[self.lang]}), '
                        f'"text": two sentences: what happened and what the person changed after it (at most {L["lesson"]} {UNIT[self.lang]}), "learned": the tools or practices it taught, in a few words, '
                        '"slides": the keys of the slides of that work, "ev"}. Spread them over the person\'s jobs; no two from the same event.')
            shape["lessons"] = [{"title": "...", "text": "...", "learned": "...", "slides": ["key"], "ev": ["id"]}]
        for n, title in custom:
            what.append(f'- "points": for the part "{title}" (number {n}), {{"part": {n}, "lede": one or two sentences, "cards": three or four cards {{"title", "text", "ev"}}, "ev"}}.')
            shape["points"] = [{"part": n, "lede": "...", "cards": [{"title": "...", "text": "...", "ev": ["id"]}], "ev": ["id"]}]
        got = self.ask("talk-lessons", prompt("talk_lessons", **self.common(), points_intro=", and the person's own topics" if custom else "", asks="\n".join(what),
                                              slides="\n".join(f"{s['key']} | {s.get('title', '')} | {s.get('period', '')}" for s in self.slides if s["kind"] == "page"),
                                              evidence=self.listing(self.shown_pids(), 10), shape=json.dumps(shape, ensure_ascii=False)), tuple(shape))
        out = {}
        if want_lessons:
            out["lessons"] = [{"title": self.add(f"lessons.{i}.title", "title", x.get("title"), WR.ids_of(x)), "text": self.add(f"lessons.{i}.text", "about", x.get("text"), WR.ids_of(x)),
                               "learned": self.add(f"lessons.{i}.learned", "title", x.get("learned"), WR.ids_of(x)) if x.get("learned") else None,
                               "keys": keys_in(x.get("slides"), self.keys)}
                              for i, x in enumerate([x for x in C.as_list(got.get("lessons")) if isinstance(x, dict)][:6])]
        out["points"] = {}
        for x in [x for x in C.as_list(got.get("points")) if isinstance(x, dict)]:
            try:
                n = int(x.get("part")) - 1
            except (TypeError, ValueError):
                continue
            out["points"][n] = {"lede": self.add(f"points.{n}.lede", "about", x.get("lede"), WR.ids_of(x)),
                                "cards": [{"title": self.add(f"points.{n}.{i}.t", "title", c.get("title"), WR.ids_of(c) or WR.ids_of(x)), "text": self.add(f"points.{n}.{i}.x", "about", c.get("text"), WR.ids_of(c))}
                                          for i, c in enumerate([c for c in C.as_list(x.get("cards")) if isinstance(c, dict)][:4])]}
        return out

    def plan(self) -> dict:
        """The career plan in three phases."""
        got = self.ask("talk-plan", prompt("talk_plan", **self.common(), company=self.company_notes or "(none)",
                                           evidence=self.listing(self.shown_pids(), 4)), ("plan",))
        p = got.get("plan") if isinstance(got.get("plan"), dict) else {}
        if not p:
            return {}
        ev = WR.ids_of(p)
        wish = lambda at, t: self.add(at, "motivation", t, [], frame=True) if t else None  # noqa: E731  an intention: the posting's and the company's words, no evidence needed
        return {"lede": wish("plan.lede", p.get("lede")), "gaps": wish("plan.gaps", p.get("gaps")), "ev": ev,
                "phases": [{"when": self.style_only(f"plan.{i}.when", x.get("when")) if not re.search(r"\d", str(x.get("when") or "")) else self.style_kept(f"plan.{i}.when", x.get("when")),
                            "title": wish(f"plan.{i}.title", x.get("title")), "basis": wish(f"plan.{i}.basis", x.get("basis")),
                            "items": [wish(f"plan.{i}.item.{j}", t) for j, t in enumerate(C.as_list(x.get("items"))[:4])],
                            "output": wish(f"plan.{i}.output", x.get("output")), "metric": wish(f"plan.{i}.metric", x.get("metric")),
                            "box": {"title": wish(f"plan.{i}.box", (x.get("box") or {}).get("title")) if isinstance(x.get("box"), dict) else None,
                                    "items": [wish(f"plan.{i}.box.{j}", t) for j, t in enumerate(C.as_list((x.get("box") or {}).get("items"))[:3])] if isinstance(x.get("box"), dict) else []}}
                           for i, x in enumerate([x for x in C.as_list(p.get("phases")) if isinstance(x, dict)][:3])]}

    def style_kept(self, at: str, text) -> dict:
        """A time span of a plan ('the first 3 months'): its number is a span, not a fact of the person; only the style pack's words."""
        t = " ".join(str(text or "").split())
        e = {"at": at, "kind": "style", "lang": self.lang, "text": t, "ev": [], "names": {}, "frame": True, "limit": None, "marks": (0, 0), "round": "draft",
             "issues": WR.style_issues(t, self.lang, "about", self.style) if t else [WR.issue("empty")]}
        self.dr.texts.append(e)
        return e

    def script(self, slides: list) -> dict:
        """What to say over each slide, in calls of about a dozen slides."""
        out = {}
        for start in range(0, len(slides), 12):
            chunk = slides[start:start + 12]
            rows, pids = [], []
            for s in chunk:
                words = round(s["seconds"] / 60 * PACE[self.lang] * (0.85 if s["kind"] in ("page", "problem", "approach", "result") else 1.0))  # a slide pointed at takes fewer words
                rows.append(f"{s['key']} | {s['seconds']} | about {words} {UNIT[self.lang]} | {describe(s)}")
                pids += self.pids.get(s["key"], [])
            pids += [i.split("#")[0] for s in chunk for i in s.get("_ev", []) if "#" in i]  # the projects the slide's own words cite
            got = self.ask("talk-script", prompt("talk_script", **self.common(), spoken=SPOKEN[self.lang], slides="\n".join(rows),
                                                 evidence=self.listing(list(dict.fromkeys(pids)) or self.shown_pids(), 12)), ("slides",))
            for x in [x for x in C.as_list(got.get("slides")) if isinstance(x, dict)]:
                k = str(x.get("key") or "")
                if k not in {s["key"] for s in chunk}:
                    continue
                lines = []
                for j, l in enumerate([l for l in C.as_list(x.get("lines")) if isinstance(l, dict)][:12]):
                    ev = WR.ids_of(l)
                    lines.append(self.add(f"script.{k}.{j}", "about", l.get("text"), ev) if ev else self.style_only(f"script.{k}.{j}", l.get("text")))
                out[k] = {"lines": lines, "cue": self.style_only(f"script.{k}.cue", x.get("cue")) if x.get("cue") else None,
                          "short": self.add(f"script.{k}.short", "about", x.get("short"), [i for l in C.as_list(x.get("lines")) if isinstance(l, dict) for i in WR.ids_of(l)]) if x.get("short") else None,
                          "questions": [{"q": self.style_only(f"script.{k}.q{j}", q.get("q")), "a": self.add(f"script.{k}.a{j}", "about", q.get("a"), WR.ids_of(q)) if WR.ids_of(q) else self.style_only(f"script.{k}.a{j}", q.get("a"))}
                                        for j, q in enumerate([q for q in C.as_list(x.get("questions")) if isinstance(q, dict)][:2])]}
        return out

    def settle(self) -> None:
        """One repair round for every failing text, then what still fails is dropped."""
        failing = self.dr.failing()
        if failing:
            self.dr.repair(lambda task, text, required: self.ask(task, text, required))
        self.dr.settle()


def describe(s: dict) -> str:
    """A slide's content in one line for the script prompt: its title and its words."""
    parts = [s.get("title") or s.get("name") or "", s.get("sub") or s.get("tag") or ""]
    for k in ("lede", "lead", "headline"):
        if s.get(k):
            parts.append(str(s[k]))
    for c in (s.get("cards") or [])[:4]:
        parts.append(f"{c.get('title', '')}: {c.get('text', '')}")
    for x in (s.get("items") or [])[:6]:
        if isinstance(x, dict):
            parts.append(f"{x.get('title', '')}: {x.get('text', '')}")
    for p in (s.get("pillars") or [])[:4]:
        parts.append(f"{p.get('title', '')}: {p.get('text', '')}")
    for r in (s.get("rows") or [])[:6]:
        if isinstance(r, dict):
            parts.append(f"{r.get('head') or r.get('area') or r.get('title', '')}")
    for ph in (s.get("phases") or [])[:3]:
        parts.append(f"{ph.get('when', '')} {ph.get('title', '')}")
    if s["kind"] == "page":
        parts.append(f"(the person's portfolio page: {s.get('period', '')})")
    text = " / ".join(re.sub(r"\s+", " ", str(p)).strip() for p in parts if str(p).strip())
    return text[:700] + ("…" if len(text) > 700 else "")


PREFIX = {"lessons": "lessons", "problem": "problem", "approach": "approach", "result": "result", "why": "why", "plan": "plan"}  # a text's place -> its slide


def content(W: Writer, slides: list, talk: dict) -> None:
    """The slides' own words: the calls the talk's parts need, one repair round, and what survived put into the slides."""
    kinds = {s["kind"] for s in slides}
    custom = [(i + 1, t["title"]) for i, t in enumerate(W.brief["topics"]) if "custom" in t["kinds"]]
    calls = 1 + ("why" in kinds) + ("problem" in kinds) + ("lessons" in kinds or bool(custom)) + ("plan" in kinds)
    W.log(f"talk: writing with the agent ({calls} calls for the slides, then the script)")
    got = {"frame": W.frame(), "why": W.why() if "why" in kinds else {}, "story": W.story() if "problem" in kinds else {},
           "lessons": W.lessons("lessons" in kinds, custom)}
    got["plan"] = W.plan() if "plan" in kinds else {}
    W.settle()  # one repair round for the slides' words
    apply(W, slides, talk, got)  # what survived, into the slides


def script(W: Writer, slides: list) -> None:
    """What to say over each slide (the slides' final words and times are known now), one repair round, into the slides."""
    for s in slides:  # the evidence each slide's own words cite, for the script's evidence
        head = PREFIX.get(s["kind"]) or (f"points.{s['part']}" if s["kind"] == "points" else None)
        s["_ev"] = list(dict.fromkeys(i for e in W.dr.texts if head and str(e["at"]).startswith(head + ".") and not e.get("gone") for i in e["ev"]))
    got = W.script(slides)
    W.settle()  # one repair round for the script
    for s in slides:
        x = got.get(s["key"])
        s.pop("_ev", None)
        if not x:  # the agent said nothing for it: the slide's own words stand in
            continue
        lines = [W.ok(e) for e in x["lines"] if W.ok(e)]
        if not lines:
            continue
        s["script"] = {"lines": lines, "cue": W.ok(x["cue"]) if x["cue"] else "", "short": W.ok(x["short"]) if x["short"] else "",
                       "questions": [{"q": W.ok(q["q"]), "a": W.ok(q["a"])} for q in x["questions"] if W.ok(q["q"])], "rule": False}


def record(W: Writer) -> dict:
    """What the run cost and what the checks stopped, for the talk's record and the panel."""
    return {"calls": W.calls, "backend": W.backend or llm.setting("LLM", "") or "default", "texts": len(W.dr.texts),
            "dropped": [{"at": d["at"], "text": d["text"], "why": [WR.issue_text(i) for i in d["issues"] if i["code"] not in WR.POLISH_CODES][:3]} for d in W.dr.dropped]}


def apply(W: Writer, slides: list, talk: dict, got: dict) -> None:
    """Put the surviving words into the slides; a slide whose words were all dropped keeps what the documents said."""
    ok, lang = W.ok, W.lang
    L = WORD_LABEL[lang]
    by = {s["key"]: s for s in slides}
    fr = got.get("frame") or {}
    msgs = [{"title": ok(m["title"]), "text": ok(m["text"]), "keys": m["keys"]} for m in fr.get("messages", [])]
    talk["messages"] = [m for m in msgs if m["title"] and m["text"]]
    for n, p in (fr.get("parts") or {}).items():
        part = talk["parts"][n]
        for k in ("what", "core"):
            if k in p and ok(p[k]):
                part[k] = ok(p[k])
        ch = next((s for s in slides if s["kind"] == "chapter" and s["part"] == n), None)
        if ch is not None and "lead" in p and ok(p["lead"]):
            ch["lead"] = ok(p["lead"])
    po = {"why": got.get("why")} if got.get("why") else {}
    if po.get("why") and "why" in by:
        w, s = po["why"], by["why"]
        if ok(w["lede"]):
            s["lede"] = ok(w["lede"])
        s["cards"] = [{"title": ok(c["title"]), "text": ok(c["text"])} for c in w["cards"] if ok(c["title"]) and ok(c["text"])]
        if ok(w["close"]):
            s["foot"] = [L["close"], ok(w["close"])]
    st = got.get("story") or {}
    for k in ("problem", "approach", "result"):
        x = st.get(k)
        if not x or k not in by:
            continue
        cards = [{"title": ok(c["title"]), "text": ok(c["text"])} for c in x["cards"] if ok(c["title"]) and ok(c["text"])]
        if not cards and not ok(x["lede"]):
            continue
        s = by[k]
        s.update(title=ok(x["title"]) or s.get("title"), sub=ok(x["sub"]) or s.get("sub", ""), lede=ok(x["lede"]) or s.get("lede", ""), cards=cards or s.get("cards", []))
        if k == "problem":
            sides = [{"title": ok(d["title"]), "items": [{"title": ok(b["title"]), "sub": ok(b["sub"]) if b["sub"] else ""} for b in d["items"] if ok(b["title"])]} for d in x.get("sides", [])]
            sides = [d for d in sides if d["title"] and d["items"]]
            if len(sides) == 2:
                s["figure"] = {"type": "sides", "sides": sides, "question": ok(x["question"]) if x.get("question") else ""}
            if x.get("scope") and ok(x["scope"]):
                s["scope"] = [L["mine"], ok(x["scope"])]
        if k == "approach":
            steps = [{"title": ok(b["title"]), "sub": ok(b["sub"]) if b["sub"] else ""} for b in x.get("steps", []) if ok(b["title"])]
            if len(steps) >= 2:
                s["figure"] = {"type": "steps", "steps": steps}
    le = got.get("lessons") or {}
    if le.get("lessons") and "lessons" in by:
        items = []
        icons = ["radar", "bell", "git-branch", "shield-check", "route", "users"]
        for i, x in enumerate(le["lessons"]):
            if ok(x["title"]) and ok(x["text"]):
                src = next((by[k].get("title") for k in x["keys"] if k in by), "")
                items.append({"title": ok(x["title"]), "text": ok(x["text"]), "learned": ok(x["learned"]) if x["learned"] else "", "icon": icons[i % len(icons)], "source": src, "keys": x["keys"]})
        if items:
            by["lessons"].update(title=by["lessons"].get("title") or "", items=items)
    for n, x in (le.get("points") or {}).items():
        s = next((y for y in slides if y["kind"] == "points" and y["part"] == n), None)
        if s is None:
            continue
        cards = [{"title": ok(c["title"]), "text": ok(c["text"])} for c in x["cards"] if ok(c["title"]) and ok(c["text"])]
        if cards:
            s.update(title=s.get("title") or W.brief["topics"][n]["title"], lede=ok(x["lede"]), cards=cards)
    pl = got.get("plan") or {}
    if pl.get("phases") and "plan" in by:
        phases = []
        for x in pl["phases"]:
            items = [ok(i) for i in x["items"] if i and ok(i)]
            if not (ok(x["when"]) and ok(x["title"]) and items):
                continue
            phases.append({"when": ok(x["when"]), "title": ok(x["title"]), "basis": ok(x["basis"]) if x["basis"] else "", "items": items,
                           "output": ok(x["output"]) if x["output"] else "", "metric": ok(x["metric"]) if x["metric"] else "",
                           "box": {"title": ok(x["box"]["title"]) if x["box"]["title"] else "", "items": [ok(i) for i in x["box"]["items"] if i and ok(i)]}})
        if phases:
            by["plan"].update(lede=ok(pl["lede"]) if pl.get("lede") else "", phases=phases)
            if pl.get("gaps") and ok(pl["gaps"]):
                by["plan"]["foot"] = [L["gap"], ok(pl["gaps"])]
