# Offerowl for AI agents (MCP)

`offerowl mcp` is a Model Context Protocol server on stdio. An agent such as Claude Code starts it, and it drives the
panel that already runs on this PC through the [HTTP API](ARCHITECTURE.md#the-http-api). The panel stays the one
program that keeps your workspace and runs the tasks: a task an agent starts keeps running when the agent goes, and
you see the same jobs and documents in the panel.

The agent could also call the API with `curl`. The server adds three things: typed tools the agent finds by itself,
the headers the API's [safety rules](APP.md#safety) ask for, and shorter answers (a document as its sentences in print
order, a deck as the words of its slides, no whole state after each write).

## Add it

Start the panel first (the app, `offerowl panel`, or the container). Then, from the checkout:

```bash
claude mcp add offerowl -- "$PWD/offerowl" mcp
```

With the Python package, `offerowl` is on PATH: `claude mcp add offerowl -- offerowl mcp`. On Windows the
command is `python C:\path\to\offerowl mcp`. `claude mcp add --scope user offerowl -- ...` has it in every project; the
option goes before `--`.

| Option | What it does |
|:---|:---|
| `--url http://127.0.0.1:N` | The panel's address. Without it: `OFFEROWL_MCP_URL`, else 127.0.0.1 on `OFFEROWL_PANEL_PORT`, else port 8797. Only 127.0.0.1 and localhost are accepted |
| `--read-only` | Offer only the tools that read: nothing is written or started |

For example, a panel on port 9000 that the agent may only read:
`claude mcp add offerowl -- "$PWD/offerowl" mcp --url http://127.0.0.1:9000 --read-only`.

## The tools

| Tool | What it does | API |
|:---|:---|:---|
| `status` | The AI backend, the job in view, counts, tasks, what the profile lacks, reminders due | `GET /api/v1/state` |
| `list_jobs` | Every application's card: stage, dates, fit score, editions made | `GET /api/v1/jobs` |
| `get_job` | One card and the full posting | `GET /api/v1/jobs/<job>` |
| `job_fit` | The fit line by line, with evidence quotes (`quotes: false` for names only) | `GET /api/v1/jobs/<job>/fit` |
| `read_document` | The resume sentence by sentence (state, check issues, evidence), or the cover letter | `GET /api/v1/documents/resume`, `cover` |
| `document_file` | `resume.txt` as text; a PDF as its size and address | `GET /api/v1/jobs/<job>/files/<lang>/<file>` |
| `deck` | The portfolio deck: slide count and each slide's words (`html: true` adds the page) | `GET /api/v1/jobs/<job>/deck/<lang>` |
| `interview_board` | The question map with coverage, the script titles, the kit's addresses | `GET /api/v1/jobs/<job>/interview` |
| `interview_search` | Questions and whole scripts that hold the query's words, or those named in `ids` | the same, searched here |
| `form_answers` | A job's own form questions with their limits and the answers kept, their state and problems | `GET /api/v1/jobs/<job>` |
| `checks` | What the checks found in an edition's last PDFs, per language: the defects, the notes to polish, the pages changed since the copy that went out; for an application, a named edition or `-general` | `GET /api/v1/state`, `GET /api/v1/jobs` |
| `editions` | The editions with words of their own that a resume can start from, and what the job named has now | `GET /api/v1/editions` |
| `procedure` | The procedure an agent makes or strengthens an application in ([below](#the-procedure)) | the file itself |
| `depth_findings` | An edition's last depth review, thin units first: each project item and deck page with its verdict (strong, adequate, thin), what it leaves out, a rewrite that cites the evidence or a question, whether the finding is part of the gate, and its state | `GET /api/v1/jobs/<job>/depth` |
| `tracker` | The board's columns, the timeline and due reminders | `GET /api/v1/tracker` |
| `insights` | The Insights view's numbers: funnel, results, weeks, fits, areas of the postings, career, readiness | `GET /api/v1/insights` |
| `library` | Every file brought in or made, with the routes that open, copy or remove each | `GET /api/v1/library` |
| `task` | A task's state by its key, or all of them; `wait` waits up to 600 seconds | `GET /api/v1/state` |
| `start_edition` | An application's (or a named edition's) own edition started from another edition's words; `replace` once the person agreed | `POST /api/v1/jobs/own/copy` |
| `write_resume` | An edition's resume written from the evidence (`-general` for the general edition), the depth review as its last stage | `POST /api/v1/jobs/write` |
| `add_job` | A job from a pasted posting or a link; its analysis starts by words. With `OFFEROWL_MCP_LINKS` set (a JSON list; the panel's command bar sets it to the links in the person's words), only those links are fetched | `POST /api/v1/jobs` |
| `make_documents` | Resume, cover letter and interview kit together, with the AI backend | `POST /api/v1/jobs/tailor` |
| `build_pdfs` | The typeset PDFs | `POST /api/v1/jobs/build` |
| `export_documents` | The made files copied to the Desktop; refused while a sentence lacks evidence | `POST /api/v1/jobs/export` |
| `lock_submitted` | What an application sent, frozen once the person says it was submitted | `POST /api/v1/jobs/lock` |
| `make_interview_kit` | The interview question map now | `POST /api/v1/interview/kit` |
| `write_interview_scripts` | More scripts by the AI backend, the likeliest questions first, or the map's entries named in `ids` (an earlier round's questions without a script) | `POST /api/v1/interview/scripts` |
| `move_job` | A stage, its date or any stage's day (`dates`), the next step (a link it comes with kept whole) or the result; `advance` moves one column right | `POST /api/v1/tracker/edit`, `next` |
| `log_round` | Keep an interview round: its kind, day, the questions asked and notes; change or remove one | `POST /api/v1/tracker/round` |
| `depth_review` | The depth review of an edition now (task `depth:<job>`), with the AI backend or the checks that need none | `POST /api/v1/jobs/depth` |
| `answer_depth` | The person's answer to a finding's question, kept as a fact of that project, never printed by itself; a deck page that names no project takes `project` (one of `depth_findings`' `projects`, as the person says) | `POST /api/v1/jobs/depth/answer` |
| `apply_depth_rewrite` | A finding's rewrite in place of the sentence it replaces | `POST /api/v1/jobs/depth/apply` |
| `leave_depth_finding` | A finding left as it is, by the person's choice | `POST /api/v1/jobs/depth/leave` |
| `remember_rule` | One of the person's corrections kept as a row of their pack's claims (`retired`, `shared`, `proposal`) | `POST /api/v1/style/rule` |
| `add_fact` | A fact the person states, kept as typed with its own words as evidence; with `project`, one more line of that project's evidence | `POST /api/v1/facts/add` |
| `reminder` | Add a reminder, or mark one done or remove it | `POST /api/v1/reminders` |

A write tool that starts a task returns its key (`tailor:<job>`, `build:<job>`, `scripts:<job>`, `analyze:<job>`, `write:<job>`, `depth:<job>`);
`task` with `wait` says when it ends. A board move or a reminder is one undo step in the panel, as when you make it there. No tool
touches the Trash: deleting for good cannot be taken back, so it stays the person's, in the panel.
A refusal comes back as a tool error that carries the API's own answer, for example
`{"status": 400, "error": "bad_request", "what": "unsupported:2"}`.

## The procedure

The harness an agent works in when it makes or strengthens an application: gather the evidence, start the edition from
another edition's words, draft, the checks as gates, the depth review (each thin unit's missing parts are a gate, fixed from
the evidence or answered by the person; the rest are suggestions), the comparison with the copy that went out, the person's approval before export and lock, and each correction
the person makes kept as a rule of their pack, so it never comes back. Each step names its MCP tool, its API route and its
command line. It ships in three ways, for whichever agent drives Offerowl:

- the `procedure` tool returns it, and the server's instructions tell every MCP client to read it first;
- `apps/mcp/skills/offerowl-application/` is a Claude Code skill folder: copy it into `~/.claude/skills/` (or a project's
  `.claude/skills/`), and the agent picks the procedure by its description;
- `AGENTS.md` at the repository's root points Codex and the other agents that read it to the same file.

The server uses only Python's standard library and speaks MCP revisions 2024-11-05 to 2025-11-25. Its code is in
`apps/mcp/`, and `tests/app/test_mcp.py` runs every tool against a panel on the fictional example.
