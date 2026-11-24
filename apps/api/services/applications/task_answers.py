"""Tasks' part for an application's form answers (apps/api/tasks.py inherits it): the applications service's answers task."""
from __future__ import annotations

from .. import documents  # noqa: E402  the Desktop and the names files take there (the documents')
from ...core.workspace import read_json, write_json  # noqa: E402



class AnswerTasks:
    """An application's form answers: the agent's writing of them from the kept facts (the profile's answer_facts), and
    their file on the Desktop."""

    def posting_of(self, job_id: str | None) -> str:
        """A job's posting as pasted ("" for none): the answers' checks take its names as the company's own."""
        return self.ws.posting(job_id)[:20000] if job_id else ""  # the workspace's one reader of posting.md

    def answers(self, job_id: str, ids: list | None = None) -> bool:
        """The answers to a job's questions, written by the agent (task "answers:<job>"); only the ones named, else all."""
        return self.start(f"answers:{job_id}", self._answers, job_id, ids)  # one per job at a time

    def _answers(self, job_id: str, ids: list | None = None) -> None:
        import draft  # src/draft.py: the system instruction and the style pack
        import llm  # src/llm.py: the one door to a model
        from . import answers as A  # the writing and the checks
        key = f"answers:{job_id}"  # this task
        f = self.ws.job_dir(job_id) / "questions.json"  # the questions
        qs = read_json(f, {}).get("questions") or []  # as kept
        todo = [q for q in qs if not ids or q["id"] in ids]  # the ones asked for
        if not todo:  # nothing to write
            self._set(key, state="done", step="", result={"written": 0})
            return
        facts = self.answer_facts()  # what the answers may say
        if not facts:  # nothing kept yet
            self._set(key, state="error", error={"code": "no_roles"})  # the band says to keep facts first
            return
        jd = self.ws.job_dir(job_id) / "posting.md"  # the posting, for what the company asks for
        posting = jd.read_text(encoding="utf-8") if jd.is_file() else ""
        style = draft.style_pack(self.style_spec())  # the person's rules
        with self.turn(key, self.model_lock):  # one model task at a time, said on the page while it waits
            backend = self.backend()  # which agent
            if backend == "none":  # no agent: said plainly
                self._set(key, state="error", error={"code": "agent_unavailable"})
                return
            ask = lambda prompt: llm.run("panel-answer", prompt, system=draft.SYSTEM, want_json=True, required=("answer",), backend=backend, timeout=300)  # noqa: E731  one answer, one call
            for n, q in enumerate(todo, 1):  # each question in turn
                self._set(key, step="writing_answers", done=n - 1, total=len(todo))  # how far
                try:
                    new = A.write(q, posting, facts, style, ask)  # written and checked
                except llm.LLMUnavailable:  # the agent stopped: what was written stays
                    self._set(key, state="error", error={"code": "agent_stopped"})
                    return
                except ValueError:  # never the right form
                    new = {**q, "issues": ["agent_stopped"]}  # said on the question
                by_id = {x["id"]: x["text"] for x in facts}  # every kept fact, for a check against a changed limit
                with A.LOCK:  # the page writes here too
                    now = read_json(f, {}).get("questions") or []  # the file now: the person may have changed the questions meanwhile
                    qs = []  # the file with this answer
                    for x in now:  # each question as kept now
                        if x.get("id") != q["id"] or x.get("text") != q["text"]:  # another question, or this one deleted or reworded: the person's version
                            qs.append(x)
                        elif x.get("limit") == q["limit"] and x.get("unit") == q["unit"]:  # the question it was written for
                            qs.append(new)
                        else:  # the limit or the unit changed while it was written: the person's, and the answer checked against it
                            got = {**new, "limit": x.get("limit"), "unit": x.get("unit")}
                            qs.append({**got, "issues": A.problems(got, got["answer"], got.get("cites") or [], by_id, style, self.posting_of(job_id))})
                    write_json(f, {"questions": qs})  # saved after each answer
        self._set(key, state="done", step="", result={"written": len(todo)})  # the task's result

    def export_answers(self, job_id: str) -> list[str]:
        """The questions and their answers as one text file on the Desktop, when every answer passes its checks."""
        qs = read_json(self.ws.job_dir(job_id) / "questions.json", {}).get("questions") or []  # as kept
        done = [q for q in qs if q.get("answer")]  # the answered ones
        if not done:  # nothing to send
            return []
        import draft  # src/draft.py: the person's rules as chosen now
        from . import answers as A  # the counting and the checks
        by_id = {x["id"]: x["text"] for x in self.answer_facts(notes=True)}  # every kept fact, and the profile's notes
        style = draft.style_pack(self.style_spec())  # the rules as chosen now
        posting = self.posting_of(job_id)  # the names the posting gives
        blocking = lambda q: [i for i in A.problems(q, q["answer"], [], by_id, style, posting) if not i.startswith("too_short") and i != "markup"]  # noqa: E731  checked again: a limit, the facts or the rules may have changed; a short answer may still go
        if any(blocking(q) for q in done):  # one still to fix
            raise ValueError("answers_need_attention")
        st = self.ws.job(job_id) or {}  # the job
        ko = any(A.lang_of(q["text"]) == "ko" for q in done)  # the file's language
        who = self.person_name("ko" if ko else "en")  # the person's name, in that language
        word = "지원서 문항" if ko else "Application answers"  # the file's name word
        unit = lambda q: (" 자" if ko else " characters") if q["unit"] == "chars" else " words"  # noqa: E731  how the form counts
        body = "\n\n".join(f"{i}. {q['text']}\n({A.count(q['answer'], q['unit'])} / {q['limit']}{unit(q)})\n\n{q['answer']}" for i, q in enumerate(done, 1))  # numbered, each with its length
        # named as every file handed out is (apps/api/services/documents/delivery.py): the words joined by underscores with no space, the day the
        # answers were last written at the end (홍길동_감마_지원서_문항_20261120.txt), a name a file has already gets _2, _3
        day = documents.made_day({"at": max(str(q.get("at") or "") for q in done)})  # the latest answer's day, else today
        base = documents.safe_name(who, str(st.get("company") or st.get("role") or ""), word, day)  # no character Windows refuses
        dest = documents.desktop_dir()  # the Desktop
        dest.mkdir(parents=True, exist_ok=True)
        name = documents.free_name(dest, base, ".txt")  # never over another file
        (dest / name).write_text(body + "\n", encoding="utf-8")  # plain text, ready to paste
        return [name]
