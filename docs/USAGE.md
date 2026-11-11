# Using Offerowl on the command line

One command, `./offerowl`, runs everything. From one profile file (JSON) it builds a resume (DOCX, PDF) and a 16:9
portfolio deck (PDF), and it can ask an AI agent for fact candidates and first drafts. Typesetting and every check run in
a container, or with the PC's own browser, and never call a model.

`./offerowl --help` lists every command in plain words. `./offerowl <command> --help` explains one.

## What you need

- Docker, or the PC's own Chrome or Edge; [Typesetting](INSTALL.md#what-you-need) says which is used when and what each
  needs.
- Python 3.10 or newer on the host.
- bash, for the container (`render/run.sh`). On Windows, run each command as `python offerowl <command>`; it typesets with
  the browser.
- For the AI steps, one of: Claude Code signed in, the Codex CLI (`codex login`), or a local model server (Ollama, vLLM,
  LM Studio). Without any of them the typesetting and the checks work as usual; the AI steps stop with a clear message
  and you fill in the facts yourself.

## First time

```bash
OFFEROWL_NET=1 render/run.sh npm ci     # the typesetting libraries; the only step that needs the network
./offerowl selftest                     # build the fictional example end to end and check it
```

The first `render/run.sh` builds the container image, which takes several minutes. The self-test then typesets the example
resume and deck, runs the checks, plants a defect to see that the check catches it, and reads a scanned page with OCR.
It ends with one line that says PASS or FAIL. `./offerowl selftest --if-changed` skips the run when nothing it depends on
has changed since the last pass.

## The usual order of work

```bash
./offerowl init ~/my-application          # copy the example profile and settings; edit them from here
./offerowl ingest ~/my-material/          # (optional) fact candidates from old resumes, reports and slides; uses the AI backend
python3 src/ui/server.py                  # (optional) the review screen, at the address it prints: accept, drop and edit candidates
./offerowl draft write ~/my-application/profile.json   # (optional) first sentences, written to profile.draft.json
./offerowl draft jd ~/my-application/profile.json posting.txt     # (optional) what the posting stresses: skills first, competencies to move back, project order
./offerowl draft translate ~/my-application/profile.json          # (optional) the English profile, written to profile.en.json
python3 src/figure_draft.py propose ~/my-application/profile.json   # (optional) the deck's figures from the evidence, written to profile.figures.json
./offerowl build ~/my-application/profile.json ~/my-application/job.json   # resume and deck into output/, then the checks
```

- An AI suggestion never overwrites its input: each step writes a new profile next to the one it reads (`profile.draft.json`,
  `profile.jd.json`, `profile.en.json`), and `build` takes the one you name. `figure_draft.py propose` writes proposals only;
  `review` and `apply` put the accepted ones in a new profile, `profile.figs.json`
  ([Drafting figures](DOCUMENTS.md#drafting-figures-srcfigure_draftpy)).
- A suggestion that holds a number, a tool name or a category that the evidence does not hold is dropped by the rules, and
  the reason is written to `output/_draft/`.
- A check result has two kinds of finding. "Things to polish" (a lone word on a line, an almost empty last page) go away
  when you tighten the text. "Defects" (a missing project, overflow, a broken figure) have to be fixed.
- The fields of a profile are described in [The profile format](DOCUMENTS.md#the-profile-format). The example is `examples/sample_ko.json`.
- Ctrl+C stops the review screen. It listens on 127.0.0.1 only.

## Commands

| Command | What it does | Needs |
|---|---|---|
| `init <folder> [--force] [--dry-run]` | Copies the example profile and a settings file into `<folder>`. Existing files are kept unless you add `--force`; `--dry-run` only lists what would be written | nothing |
| `ingest <folder or file>...` | Reads PDF, DOCX, PPTX and images (OCR) and proposes fact candidates, each with a quote that must really be in the source | AI backend |
| `draft write\|check\|jd\|translate\|figures <profile.json>` | Asks the AI backend for sentences, job-posting fit, an English profile or figure data, each kept in a new file beside the profile; `check` holds a drafted profile against its evidence again, with no model. Every suggestion goes through the fact check | AI backend |
| `build <profile.json> [job.json]` | Builds the resume and the deck into `output/`, and the resume in plain words for job sites that read a file (`<out>_plain.docx`, `<out>_plain.txt`), then runs the document check | Docker, or Chrome or Edge ([What you need](#what-you-need)) |
| `cover ...` | Builds a cover letter from a profile and a job posting | see `offerowl cover --help` |
| `interview ...` | Prepares the interview kit: question map, scenes, audits, search view, cue cards, the interview deck and the talk ([INTERVIEW.md](INTERVIEW.md)) | see `offerowl interview --help` |
| `panel` | Opens the local web panel | see `offerowl panel --help` |
| `open [--port N]` | Brings up the panel that runs on this PC (the app, a container, a port-forward or `panel`) in your browser, and prints its address; on a computer with no screen the address is the way in | a running panel |
| `api serve\|get\|post\|add-file ...` | Serves Offerowl's HTTP API alone, or calls one endpoint from the shell ([The HTTP API](ARCHITECTURE.md#the-http-api)) | see `offerowl api --help` |
| `mcp [--url ...] [--read-only]` | Serves Offerowl's tools to an AI agent over MCP on stdio, driving the running panel ([MCP.md](MCP.md)) | a running panel |
| `import <resume.json> [-o profile.json]` | Reads a JSON Resume file into a new profile | nothing |
| `export <profile.json> [--lang ko\|en] [-o resume.json]` | Writes a profile as a JSON Resume file | nothing |
| `selftest [--if-changed]` | Builds the fictional example end to end and checks it | Docker, or Chrome or Edge ([What you need](#what-you-need)) |
| `llm [--list \| --probe <backend>]` | Shows which AI backend is in use and why; `--probe` makes one tiny test call | nothing |
| `doctor [--json] [--only ...]` | Checks what Offerowl needs on this PC and says what to do about what is missing | nothing |

`cover`, `interview`, `panel`, `api`, `mcp` and `doctor` are separate programs (`src/cover.py`, `src/interview/cli.py`,
`apps/panel/server.py`, `apps/api/__main__.py`, `apps/mcp/__main__.py`, `src/doctor.py`), and `import` and `export` are `src/write_jsonresume.py`.
The launcher passes your arguments and the exit code through. When a file is missing it prints "not installed", names
the file, and exits with code 3.

Exit codes: 0 means done. The launcher itself uses 2 for a wrong command line and 3 for a command that is not installed
yet. Every other code comes from the command (for example `init` returns 1 when it refuses to overwrite files).

`python3 src/resume.py <command>` still works and runs the same code as `init`, `ingest`, `draft`, `build`, `selftest` and
`llm`.

## The AI backend

One backend is used at a time, and every task uses it. There is no mixing of a local model and a cloud agent.

| Backend | What it is | Set it with |
|---|---|---|
| `claude-code` | The Claude Code CLI you are signed in to (`claude -p`). No API key | `OFFEROWL_LLM=claude-code` |
| `codex` | The Codex CLI (`codex exec`, after `codex login`). Without an install: `OFFEROWL_CODEX_CMD="npx -y @openai/codex"` | `OFFEROWL_LLM=codex` |
| `openai-compat` | A local server with an OpenAI-compatible address: Ollama, vLLM, LM Studio | `OFFEROWL_LLM=openai-compat OFFEROWL_LLM_URL=http://127.0.0.1:11434 OFFEROWL_LLM_MODEL=<model>` |
| `none` | No model. The AI steps stop and you fill in the facts yourself | `OFFEROWL_LLM=none` |

Without `OFFEROWL_LLM` the default order is: Claude Code if it is installed and signed in, else Codex if it is
installed, else `none`. A Claude Code that is installed but signed out is skipped. If the sign-in state cannot be read,
as with an older CLI, Claude Code is still used. A backend that you chose by name is never replaced by another when
it fails: you see the reason.

`./offerowl llm` shows the four backends, which one is in use and what chose it:

```
* claude-code    available  /usr/local/bin/claude  [signed in]
  codex          missing    codex CLI not found (OFFEROWL_CODEX_CMD can point to npx)
  openai-compat  missing    OFFEROWL_LLM_URL is not set
  none           available  no model; a person fills in the facts

In use: claude-code (default order: signed-in Claude Code, else Codex, else none)
```

Offerowl starts the CLI as you installed it and never opens its login files. To use an API key with Claude Code, set
`ANTHROPIC_API_KEY`, which the CLI reads by itself. The terms of your plan apply to what you send through it
([Anthropic's page](https://code.claude.com/docs/en/legal-and-compliance)).

What goes to the agent: the text of the files you give `ingest`, and for `draft` the profile text, the fact candidates and
the posting, in small pieces. With `none` nothing leaves the PC. Every call appends one line to `output/_llm/calls.jsonl` with the
backend, the task, the seconds and the character counts; the text itself is never written.

## Settings

Settings are environment variables.

| Setting | Meaning | Default |
|:---|:---|:---|
| `OFFEROWL_LLM` | Backend: `claude-code`, `codex`, `openai-compat`, `none` | default order above |
| `OFFEROWL_LLM_MODEL` | Model name for `codex` (`-m`) and `openai-compat` | the backend's own |
| `OFFEROWL_LLM_URL` | Address of the `openai-compat` server; the scheme and a trailing `/v1` are optional | none |
| `OFFEROWL_LLM_KEY` | Bearer key, only for servers that ask for one | none |
| `OFFEROWL_LLM_REASONING` | `reasoning_effort` sent to `openai-compat`; an empty value sends nothing | `none` |
| `OFFEROWL_CODEX_CMD` | How to start Codex, for example `npx -y @openai/codex` | `codex` on PATH |
| `OFFEROWL_CODEX_PROFILE` | A profile from the Codex config file | none |
| `OFFEROWL_CODEX_OSS` | `ollama` or `lmstudio`: Codex talks to a local model | none |
| `OFFEROWL_LANG` | Language of messages, `ko` or `en` | from the locale, else English |
| `OFFEROWL_NET` | `1` opens the container's network (only `npm ci` needs it) | closed |
| `OFFEROWL_CPUS` | CPU cap of the container, never more than Docker has | 6 |
| `OFFEROWL_MEM` | Memory cap of the container | 4g |
| `OFFEROWL_ASSETS` | A folder of private assets (logos, screenshots) mounted read-only at `/offerowl-assets` | no mount |
| `OFFEROWL_THEME` | Colour set for the scripts in the container | the script's own |
| `OFFEROWL_THEME_FILE` | A JSON file with your own colour sets | none |
| `OFFEROWL_UI_PORT` | Port of the review screen | 8798 |
| `OFFEROWL_DRY_RUN` | `1` makes `run.sh` print the docker command instead of running it | unset |
| `OFFEROWL_PDF_READER` | `pdfium` reads PDFs with PDFium even where poppler is installed | poppler when it is installed |
| `OFFEROWL_RENDERER` | `container` typesets in the render container, `html` with the PC's Chrome or Edge | `container` when Docker is there, else `html` when a browser can typeset; `html` on Windows outside WSL |
| `OFFEROWL_BLIND` | `1` makes a blind edition (below) | unset |
| `OFFEROWL_BLIND_LANG` | `en` for the band and the label of an English blind edition | `ko` |
| `OFFEROWL_BLIND_TABLE` | Your own table for the blind edition, a JSON file inside the repository (below) | `src/blind.json` |
| `OFFEROWL_OFFICE` | `0` never opens a Word or PowerPoint file in this PC's Office before it goes (below) | opened where Office is reachable |

The panel's own settings are with it: `OFFEROWL_PANEL_PORT` in [Start it](APP.md#start-it), `OFFEROWL_DATA_DIR` in
[The data folder](APP.md#the-data-folder) and `OFFEROWL_LLM_LOG` in [The agent's panel](APP.md#the-agents-panel); the
container's are in [INSTALL.md](INSTALL.md#2-a-container-docker-compose).

`render/run.sh` hands `OFFEROWL_THEME`, `OFFEROWL_THEME_FILE`, `OFFEROWL_RENDERER`, `OFFEROWL_PDF_READER` and
`OFFEROWL_BLIND` to the scripts in the container, along with `OFFEROWL_FRESH`, `OFFEROWL_NOLOGOS`, `OFFEROWL_PROFILE`,
`OFFEROWL_LANG`, `OFFEROWL_BLIND_LANG` and `OFFEROWL_BLIND_TABLE`.

Language: `OFFEROWL_LANG=ko ./offerowl --help` prints Korean. With no setting the locale decides (`ko_KR` gives Korean,
anything else English). Put the setting in your shell profile to keep it.

## The review screen and the assets

`python3 src/ui/server.py` starts the fact review screen and prints its address: the panel's profile view, with the fact
candidates `offerowl ingest` found added to it. It needs no packages and no container.

A folder of private assets (logos, screenshots) reaches the builds only when you name it: `OFFEROWL_ASSETS=<folder>` mounts
it read-only at `/offerowl-assets` in the render container.

## A blind edition

A blind edition is the same resume, and the deck Offerowl draws, with the names you choose covered by solid bars of their own width:
your contacts, client companies, scale figures and the like. A red band marks the first page of each, and a red label sits in every
footer. The words are covered, never replaced, and the photo is left out. In the panel it is a switch in Documents
([docs/APP.md](APP.md#documents-the-live-canvas)); on the command line it is `OFFEROWL_BLIND=1`:

```bash
OFFEROWL_BLIND=1 OFFEROWL_BLIND_TABLE=output/blind.json ./offerowl build profile.json job.json
```

The table says what to cover. `src/blind.json` ships empty, so it covers nothing; your own goes over it key by key:

```json
{
  "mask": ["Alphapay", "Beta ?Commerce", "gildong@example\\.com", "\\d+ GPUs"],
  "mask_whole": ["gildong@example\\.com"],
  "leak": ["Gamma Labs"],
  "contacts_unlink": ["Email"],
  "footer": {"ko": "블라인드 버전", "en": "Blind version"},
  "banner": {"ko": ["블라인드", "이름과 연락처를 가린 판"], "en": ["BLIND", "Name and contacts masked"]},
  "mask_fill": "8B1A1A",
  "mark_fill": "8B1A1A"
}
```

- `mask`: what is covered, as regular expressions read the way JavaScript reads them with no flags (`\w`, `\d` and `\b` are ASCII).
  A covered phrase keeps its spaces, so the bars break where the words do.
- `mask_whole`: values covered with their spaces by one bar, such as a mail address. Each must also match a `mask` pattern.
- `leak`: words that must never show in a blind edition. They are not covered; the export refuses the PDFs when one shows. Each is
  a word as written, not a pattern (`500+` is five hundred and more), and a word that starts with a Latin letter counts only on its
  own, so `NCI` is not found inside `COMPETENCIES`.
- `contacts_unlink`: contact labels whose link is taken off. A contact whose value or address a `mask` pattern covers loses its link
  too, since a bar hides the words and not the link.
- `footer`, `banner`, `mask_fill`, `mark_fill`: the label in each footer, the two parts of the page-one band, the bars' colour and
  the band's colour.

The panel keeps your table in the workspace (`blind.json`), never in the repository. Before it keeps one, it checks that each
pattern compiles and means the same in Python and in JavaScript (no named groups, inline flags, back references, `\A`, `\Z` or
`{,n}`), that none matches empty text, and that the colours and words have a sane shape and size. On the command line,
`python3 src/blind.py check table.json` runs the same check, and `OFFEROWL_BLIND_TABLE` names a file inside the repository, as the
container sees it (`output/` is ignored by git, so a table there never lands in a commit).

What a blind edition covers:

- the resume's text runs, its header and footer included, and the contacts' links;
- the deck Offerowl draws: its text, the text of its figures, the links of its contacts, and a band across the cover;
- the timeline and the hierarchy figure, which are pictures, so the bars are drawn when they are drawn;
- the PDF's title and author, which leave out what the table covers and say that it is the blind edition.

What it leaves out, because no bar can cover it, and says so in the panel: a document you made yourself (your own resume file gives
way to the resume typeset from your words; your own portfolio, the profile's `deck.pdf` included, is left out and never replaced by a
drawn one), the cover letter, which is written to one company by name, and the plain-words resume for job sites.

What it does not cover: logo tiles and monograms, and pictures you brought in, such as screenshots on the deck's slides. The logos
of a name you cover stay as they are.

Before a blind edition goes to the Desktop, its PDFs are read: when a `leak` word or a `mask` pattern shows in their text, the title
or author of any revision of the file, an outline entry or a link's address, nothing is exported and the panel says how many
showed. The files are named with the word for blind ("블라인드", "Blind"), and without your name or the edition's name when the table
covers it.

## Word and PowerPoint copies

The panel's export writes these beside the PDFs when its switches ask for them ([docs/APP.md](APP.md#documents-the-live-canvas)).
The same steps run on their own:

```bash
python3 src/docx_word.py output/sample_full_ko.docx resume.docx "홍길동 이력서" "홍길동"   # the resume's Word file, ready for Word
python3 src/deck_pptx.py output/sample_full_ko_deck.pdf portfolio.pptx                     # the deck as slides, one picture per page
python3 src/office_check.py word resume.docx                                               # pages=N in this PC's Word
python3 src/office_check.py powerpoint portfolio.pptx                                      # slides=N in this PC's PowerPoint
```

- `docx_word.py` embeds Pretendard's regular and bold faces (the SIL Open Font License 1.1 allows a font inside a document), makes
  every text line exact at the height LibreOffice gave it, and sets the title and the author. It reads the copy back and prints what
  is wrong, if anything.
- `deck_pptx.py` draws each page at 192 dpi (2560 x 1440 for the deck), keeps each web and mail link as a rectangle a click follows,
  and gives each picture its page's words as its description. Without a title and an author it takes the PDF's. It needs poppler or
  pypdfium2 to draw the pages.
- `office_check.py` opens the file in Word or PowerPoint, unseen and read-only, on Windows or from WSL, and quits the program when
  no other document is open in it. Elsewhere it says that Office is not reachable and exits with 3. `OFFEROWL_OFFICE=0` turns it off.

## Colours and style

- Colour sets are in `src/themes.json`. Add your own with `OFFEROWL_THEME_FILE=<json>` and name one in `job.json` as `theme`.
- A style pack lists the characters and patterns a document must not hold. `src/style/default.json` is empty. Make your own
  and name it in `job.json` as `style`; the fact check and the drafts both apply it.

## Tests

```bash
python3 tests/cli/lint.py                       # syntax and lint pass: Python, JSON, JavaScript, shell
python3 -m unittest discover -s tests/cli -v    # the command, settings, stand-in backends, run.sh, compose, messages
```

None of them starts a container or calls a model. They are the same commands `.github/workflows/ci.yml` runs, followed by the
self-test with `OFFEROWL_LLM=none`.
