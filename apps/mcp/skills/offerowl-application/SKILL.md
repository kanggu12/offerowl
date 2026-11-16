---
name: offerowl-application
description: Make or strengthen a job application's documents with Offerowl (resume, portfolio deck, cover letter), from the person's evidence, through Offerowl's MCP tools, API or command line. Use it when the person asks for a resume or a portfolio for a posting, a general edition, a stronger version of an existing one, or a final check before they send it.
---

# Making or strengthening an application with Offerowl

Offerowl keeps the person's facts and makes every document from them. You drive it; you never write a fact yourself. Each
step below has a gate: do not go on until it holds. Each names its call three ways: the MCP tool, the HTTP API route (the
panel's own, on 127.0.0.1) and the command line (`offerowl ...`, which runs the same routes in its own process).

Four rules hold at every step:

- **Evidence only.** A sentence says only what the person's evidence says. Never invent a difficulty, a reason, an
  alternative, a mechanism, a number, a tool or a client. When the evidence holds none, write less and ask the person.
- **The person's part as the evidence states it.** "Proposed", "with the team", "helped" stay. Circumstances are not
  achievements: no "the only developer", "alone", team sizes or join dates; show the work instead.
- **The person's own forms stand.** A job title with two positions or a gloss in parentheses, a phrase the person chose:
  keep it as it is. A form the person chose was a decision.
- **The person decides.** Ask before anything goes out, and keep each correction they make as a rule (step 8).

## 1. Where things stand

Read the state before you change anything: the AI backend in use, the applications, what the profile lacks.

| MCP | API | CLI |
|---|---|---|
| `status`, `list_jobs`, `get_job` | `GET /api/v1/state`, `GET /api/v1/jobs`, `GET /api/v1/jobs/<job>` | `offerowl api get /api/v1/state` |

Gate: you know the edition you work on: an application's id, a named edition's (it starts with a dash) or `-general`, and
its language (`ko` or `en`). On the command line a named edition's id goes without its dash, and the general edition is
`general`: a shell reads a leading dash as an option.

## 2. Gather the evidence

The person's files are read in the panel or by the command line; what the person tells you is kept as a fact in their own
words. A fact about a project already in the profile names that project, and becomes one more line of its evidence.

| MCP | API | CLI |
|---|---|---|
| `add_fact` (`project` names an existing project) | `POST /api/v1/facts/add` | `offerowl api add-file <file>`, `offerowl api post /api/v1/facts/add '{...}'` |

Gate: every fact you added is the person's statement or a file's words. Nothing comes from you.

## 3. The posting and the fit

For an application, add its posting and read the fit line by line: what is asked, what the evidence shows (strong, weak,
none), the gaps. A gap stays a gap: never write around it.

| MCP | API | CLI |
|---|---|---|
| `add_job`, `job_fit` | `POST /api/v1/jobs`, `GET /api/v1/jobs/<job>/fit` | `offerowl api post /api/v1/jobs '{"posting": "..."}'` |

Gate: you can name the lines the evidence answers, and the ones it does not.

## 4. Start the edition

Start from the words the person last polished, or from an earlier application like this one: never from nothing when such
an edition exists. Replacing an edition that has words of its own needs the person's yes; `editions` says what it holds.

| MCP | API | CLI |
|---|---|---|
| `editions`, `start_edition` | `GET /api/v1/editions?job=<job>`, `POST /api/v1/jobs/own/copy` | `offerowl edition list <job>`, `offerowl edition start <job> --from <edition>` |

Gate: the edition prints words the person stands behind, or it prints the general resume on purpose.

## 5. Draft

The AI backend writes each part from the evidence, every sentence citing what it rests on. The drafting run ends with
the depth review (step 7). For an application, `make_documents` also writes the cover letter and the interview kit.

| MCP | API | CLI |
|---|---|---|
| `write_resume`, `make_documents`, `task` (`wait`) | `POST /api/v1/jobs/write`, `POST /api/v1/jobs/tailor` | `offerowl api post /api/v1/jobs/write '{"job": "<job>"}'` |

Gate: `read_document` shows no sentence without evidence (`counts.unsupported` is 0).

## 6. The checks are gates

Make the PDFs and read what the checks found: the printed words (marks, editing notes, the person's banned wording), the
phrases fixed once (claims), the edition against the profile (periods, required words, core projects), the pages (fill,
gaps, bands), the two languages, the resume against its deck, a blind edition against its twin, and what changed since the
copy that went out. A defect keeps the PDFs home: fix each one at its source (a fact, a sentence, a rule), never by
cutting margins or merging items. Notes to polish are worth a look.

| MCP | API | CLI |
|---|---|---|
| `build_pdfs`, `task`, `checks` | `POST /api/v1/jobs/build`, `GET /api/v1/state` (`general`, `editions`), `GET /api/v1/jobs` (each edition's `builds`) | `offerowl api post /api/v1/jobs/build '{"job": "<job>"}'`, `offerowl baseline show <job>` |

Gate: no defect is left, and every changed page since the copy that went out is a change you meant.

## 7. The depth review: thin items are a gate, the rest suggestions

The review reads each printed project item and each deck page as an engineer who hires reads them. Each unit the agent read
has a verdict on three core parts: what made the work hard, the decision and the alternative it beat, and why the result
came about. A part counts only when the unit's own words state it.

- **thin** (two or three parts not stated): a gate. Each finding marked `gate` is fixed from the evidence or answered by the
  person before the edition goes out. Thin units come first in `depth_findings`.
- **adequate** (one part not stated) and **strong** (all three stated): their findings are suggestions. Offer them to the
  person; go on when they decline.

Every finding has one way on:

- a **rewrite** that cites the item's evidence and already passed the draft's checks: use it (`apply_depth_rewrite`) when it
  is right; or
- a **question** for the person: ask it, word for word if you like, and keep their answer (`answer_depth`). Their answer
  becomes evidence of that project, never a line of its own; then draft again or rewrite the item from it. A deck page that
  names no project (`needs_project`) needs the person to say which project it is about: pass it as `project`.

Leave a finding only when the person says so (`leave_depth_finding`): it stays left while the item's words stay the same.
Never answer a question yourself, and never fill a gate with words the evidence does not hold. A review never blocks an
export: you hold yourself to it.

| MCP | API | CLI |
|---|---|---|
| `depth_review`, `depth_findings`, `answer_depth`, `apply_depth_rewrite`, `leave_depth_finding` | `POST /api/v1/jobs/depth`, `GET /api/v1/jobs/<job>/depth`, `POST /api/v1/jobs/depth/answer`, `.../apply`, `.../leave` | `offerowl depth review <job>`, `offerowl depth show <job>`, `offerowl depth answer <job> <finding> "<words>"`, `offerowl depth apply <job> <finding>`, `offerowl depth leave <job> <finding>` |

Gate: no thin unit's gate is open (`now.gates` is 0: each finding marked `gate` is used, answered or left by the person),
the person has seen the suggestions, and a review made after the last change shows no new thin unit.

## 8. Keep each correction as a rule

When the person corrects a phrase ("that was the team's", "we only proposed it", "always say it this way"), keep it as a rule
of their writing rules, so no draft writes it again and every build holds every edition to it:

- `retired` `[old pattern, new words, why]`: a phrase taken out because it did not match the facts;
- `shared` `[topic pattern, phrase pattern, why]`: every general edition says the topic with this phrase;
- `proposal` `[topic pattern, word pattern, why]`: work that ended as a proposal says so.

Patterns are Python regular expressions. Read the rules in use first, so a rule is not kept twice.

| MCP | API | CLI |
|---|---|---|
| `remember_rule` | `GET /api/v1/style`, `POST /api/v1/style/rule` | `offerowl api get /api/v1/style`, `offerowl api post /api/v1/style/rule '{"list": "retired", "row": [...]}'` |

Gate: each correction of this session is a rule, and the next build's checks pass with it.

## 9. The person approves, then it goes out

Show the person the edition (the panel's Documents view, or `read_document` and `deck`), say what changed and what each
finding became, and wait for their yes. Export copies the checked PDFs to the Desktop; the lock freezes what was sent once
the person says it was submitted. Never lock on your own judgment.

| MCP | API | CLI |
|---|---|---|
| `export_documents`, `lock_submitted` | `POST /api/v1/jobs/export`, `POST /api/v1/jobs/lock` | `offerowl api post /api/v1/jobs/export '{"job": "<job>"}'` |

Gate: the person said yes to what went out. The export keeps its pages and words as the copy that went out: the next
review and the next build compare with it.
