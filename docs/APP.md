# The panel and the desktop app

Offerowl's panel is the product: a local web page for people who never open a terminal. The desktop app starts it,
opens it in the browser and keeps it running. Everything the panel does goes through Offerowl's one HTTP API
([The HTTP API](ARCHITECTURE.md#the-http-api)); the page never runs a command. The [user guide](README.md) walks through the panel with pictures; this
page is the reference.

## Start it

| What | Command | Address |
|---|---|---|
| The panel, from a checkout | `python3 apps/panel/server.py --open` (or `./offerowl panel --open`) | opened by `--open`, or later by `offerowl open` |
| The desktop app, from a checkout | `python3 apps/desktop/app.py` | the same panel, opened for you, with an icon in the notification area |
| The desktop app, built | `Offerowl.exe` (Windows), `Offerowl.app` (macOS), `Offerowl` (Linux) | the same |
| The API alone, or one call | `python3 -m apps.api serve`, `python3 -m apps.api get /api/v1/state` | [The HTTP API](ARCHITECTURE.md#the-http-api) |
| The fact review screen alone | `python3 src/ui/server.py` | the profile view, at the address it prints |

The panel needs Python 3.10 or newer and nothing else to run. The built app carries its own Python. Typeset PDFs ("Make
PDFs") print with the PC's Chrome or Edge in the built app; from a checkout they render in the render container through
`render/run.sh` where Docker is there (on Windows always with the PC's browser), else with the PC's browser, and
`OFFEROWL_RENDERER` picks one by hand. The live
canvas needs neither.

Options of `apps/panel/server.py`:

- `--port N`: another port on 127.0.0.1 (default 8797, also `OFFEROWL_PANEL_PORT`). A port another program or panel holds
  stops the start with a line that says so, before the workspace is opened ([Safety](ARCHITECTURE.md#safety)).
- `--workspace DIR`: another workspace folder. Without it the workspace
  is the data folder's `workspace/`.
- `--open`: open the panel in the browser.

The panel serves each job's interview kit at its own address, `/kit/<job>/` (the kit's own search page), `/kit/<job>/deck`, `/kit/<job>/cue` and `/kit/<job>/talk` (the talk's script and its two PDFs), and its similarity and practice API under `/kit/<job>/api/`, so one address holds everything: the interview tab draws its parts itself and reads the kit there, the print keys open its printable pages, and each job's kit runs on a free port of its own inside the panel (the last four kept), so two tabs on two jobs never swap one kit under the other. The desktop app takes `--no-browser`,
`--no-tray`, `--port N` and `--check`.

## The data folder

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\Offerowl` |
| macOS | `~/Library/Application Support/Offerowl` |
| Linux | `$XDG_DATA_HOME/offerowl`, or `~/.local/share/offerowl` |

`OFFEROWL_DATA_DIR` names another one. It holds:

- `settings.json`: the language, the theme and the agent.
- `workspace/`: the person's files, with the layout of [Your workspace](ARCHITECTURE.md#your-workspace):
  - `profile/profile.json` is built from the confirmed facts, and `profile/evidence.json` says which facts each part
    of it rests on. `profile/details.json` holds the person's own fields. `profile/base.json` holds an imported
    profile. `profile/removed-photo-<day>-<time>.*` is a photo that was removed, each under a name of its own, waiting in
    the Trash.
  - `sources/` holds the material and `candidates.json`, `review.json` (kept or dropped), `edits.json` and
    `locks.json` (locked sentences). `sources/removed/<id>.json` holds what a removed file took along (its facts, the
    imported profile it was, the example's details), so the Trash can put it back after later changes too.
  - `jobs/<job>/` holds `posting.md`, `plan.json` (the posting analysis), `status.json` (the card, its dates and its
    reminders), `resume/<lang>/` (the last edition: PDFs, DOCX, pages, checks, and `cover/` with the letter's draft),
    `interview/` (the kit: `kit.json`, the resume's text, the scene files), `materials/` (the files brought in for its
    interview, `index.json` with each one's name, kind, size, day and SHA-256 (one deleted for good leaves only its id),
    `removed.json` and `removed_at.json` (what was removed, and when: the day and the hour), and `.preview/` with page pictures, which a
    backup leaves out) and `submitted/<time>/`: exact copies and `hashes.json`, written by "Lock when submitted".
  - `out/interview/<job>/` holds the kit's question map, the questions the agent expects and its draft scripts, which join the search view at once.
  - `.history/` holds the undo steps (50 at most).
  - `.gone/` holds a job's folder for a moment while it is deleted for good; what a stopped deletion leaves there goes at the
    next start. A backup leaves it out.
  - Beside the workspace, a restore leaves `workspace-before-restore-<day>-<time>/`: the workspace as it was. The Trash
    lists these folders and deletes them.
- `logs/`. Each log is capped with one older file kept: `panel.log` (2 MB), `app.log` (2 MB) and
  `server-console.log` (2 MB).
- `app.lock`: one copy of the app at a time.

## Make

The panel opens on Make: first the resume's head (the name, or "Add your name"; where the applications stand; the next date;
the latest documents), then a band that follows the files to the documents with the workspace's own numbers, each a
key to the view it lives in: the files added (not removed), the facts kept with their quotes, the sentences of the document in
view with the count of those without evidence in red, and the PDFs made across the jobs, the named editions and the general
one. Under the band, every application still going (a dozen at most) stands as a note with "Docs" and "Interview", beside
"See the board". Under them, three columns read from left to right.

1. **Add your sources**: drop files or a folder anywhere on the page, choose them, or paste a path in the box **Paste a path instead** opens (Windows' `C:\...`, a
   `\\wsl.localhost\...` path, or a Linux one; under WSL the server maps them). A folder is walked with its subfolders, past
   hidden folders, code folders such as `node_modules`, the system's own folders (`AppData`, `Library`, `Program Files` and the
   like), Office lock files and kinds the readers do not know. It reads up to 80 files of 60 MB each, documents first, then
   notes, then pictures, and stops looking after 4,000 files. A posting's link or text may go in its own box. Under them, the files read and the facts each gave.
2. **Grounded writing**: the agent's panel (below) and the run's steps: find the files, read them, sort the career facts, find the name and
   contact, read the posting, write the resume, make the English edition, draw the figures, answer the form's questions when the
   posting lists them, make the PDFs, write interview scripts and save to the Desktop; without a posting, the steps that need one
   are left out. A step that fails leaves the
   others to run; **Stop** ends the run after the step in progress, checked between every step and between the pieces the agent
   reads, and the run then says Stopped. What was read waits in the profile, unkept.
3. **Finished documents**: a tile per PDF with its first page, in Korean and English, and for a posting the cover letter and the
   interview scripts; the files copied to the Desktop and a key to open that folder; a line for anything that went wrong.
   Only the editions this run made are copied and shown: an English edition that failed this time never stands in with an
   older one.
   When a PDF waits for a name or an email the files do not write, the result asks for it and makes the PDFs again.
   With no run in this session, the column lists the documents made most recently, seven rows at most, one per edition and
   language with its date, and a key to the rest in the Library; a click opens that edition in Documents.

The run is `apps/api/autopilot.py`, one task (`autopilot`) whose steps are the panel's own tasks, so a run makes exactly
what the buttons would. Files or a posting sent while a run goes wait and run right after it, from the facts already kept;
several sent meanwhile are read together, and Stop drops what waited. A job a run adds is not put in view, so an edit in
progress stays on its own job. Each
finished run is kept in `out/runs.json` and listed. The name, email and phone go to "Your details" only where it is
empty: the email and phone by their shape, the one the starts of the files write most (never a clone address, a robot's
address or a picture's name), the name from one small question to the agent, kept only when the files write it. "Try an
example" leaves first when the person's own files come, with its facts and the details it filled in.
Under WSL the Desktop is the Windows one, and the folder opens in Explorer.

The scripted first look, "Try an example" with the agent off, reaches the example's resume in about two seconds
(tests/app/walk.py prints the time); a dropped example file reaches its PDFs on the Desktop in about ten
(`tools/measure.py --only firstrun`).

## The agent's panel

The agent in use with a lamp and one switch; its sign-in, with the account and the plan as the CLI reports them; the model
the last call ran on and the effort named; and the day's requests: how many, their median time, the mean wait for the first
token and the tokens a second, the tokens they read and wrote, a bar per recent request with its first-token wait marked inside
it, the dollar sum the CLI reports and the failures with the last one's code, each as
[the agent card](ARCHITECTURE.md#the-agent-card-and-the-days-calls) defines it. The figures are read from `src/llm.py`'s call
log, which the panel and the app keep with the data (`logs/calls.jsonl` in the data folder; the command line's is
`output/_llm/calls.jsonl`, and `OFFEROWL_LLM_LOG` names another). It keeps sizes, times, tokens and the model of each call
and never its text; Claude Code is asked for its JSON result to know them. Offerowl never opens a CLI's login files. The
panel stands in the middle of Make, and the agent's lamp in the bar opens it from any view.

## The other views

- **The bar**: the wordmark with Offerowl's version beside it, the views (Make, Profile, Applications, Documents, Insights,
  Library, with a count where one asks for attention), the job in view on Documents, the run's lamp while a run goes, the
  agent's lamp, Undo and Settings (the setup guide, theme, motion, language, the agent, the workspace folder, backup and restore,
  and the version again at its foot).
- **Setup guide** (`setup.js`): four steps over the page, the AI agent, the typesetting, the look and a first start. Each
  step draws its state as the panel draws it elsewhere (the agent's lamp and keys, the typesetting's error and its fix, the
  menu's language and theme), so a state the panel learns to say is said here with it. It opens by itself once in a
  browser (`offerowl-setup-seen` in its storage) while the workspace holds no files and no facts, never while the browser
  refuses storage (it would come back with every page), and from the top of Settings. The sheet hangs from a fixed line
  and keeps one height on a wide window, so the steps and the keys at its foot stay under the pointer.
- **Canvas**: the view itself. On Documents it shows the document as it will print.
- **Inspector** (beside Documents only; the other views use the width themselves): Evidence, Fit, Style, Theme and History.

Where the window is too narrow for one row, the views go down to a row of their own and the wordmark, the lamps, Undo
and Settings keep the first, whatever the language. Below 1100 pixels the inspector becomes a
drawer ("Inspector" in the view's head). Below 860 pixels (a phone) the six views stand two by two under the wordmark, the bar
scrolls away with the page, the applications in progress on Make slide sideways on one row, the inspector opens as a sheet from below, and the resume's pages keep their printed layout,
scaled down to the width (a pinch enlarges them).

### Profile

- **Your details**: name, email, the English name, phone, the headline and the introduction, saved as you type (one
  undo step per field and pause), and the resume's photo in a 3:4 cell (a JPEG or a PNG by its bytes, kept as
  `profile/photo.*`; "On the resume" takes it off without removing it, and "Remove" puts it in the Trash, its note holding
  Undo). They stay on this PC.
- **Your files**: drop them or choose them, or try the example person. Each file shows its reading state and how many
  facts it gave, and "Remove" takes it and its facts out at once; its note holds Undo, and the Trash puts both back later.
  A key under the list says how many files wait in the Trash. The panel says that the text of each file goes to the
  agent, and that a profile file is read without it.
- **Facts**, on a sheet with the kind of each fact in a column of its own: To confirm, Kept, Dropped or All; per fact
  its title, company and period, what it says, and the source's own words with the file they came from; Keep, Edit and
  Drop. "Keep the remaining N" keeps the rest at once. "Add a fact" takes a fact in the person's own words, which is
  its own evidence. Only kept facts reach the profile.

### Documents: the live canvas

- The resume is drawn from `GET /api/v1/documents/resume`: A4 sheets, the parts in the order src/resume_form.js prints
  them (header, headline, introduction, overview with key projects, career summary, education, core competencies,
  skills, experience, the other lists, about me, motivation), in the theme's colours. On a wide screen two pages sit
  side by side.
- A margin column with a thin rule runs beside each page. It names each section in the app's language (a list of another
  kind, such as certificates, by its own heading) and marks a part with a
  sentence without evidence ("No evidence", with a red dot) or a locked sentence.
- With an agent on and no draft yet, "Rewrite with the agent" ("Write the resume" while the page is empty) stands in the head with the other keys, its hover saying what it sends. The draft
  is kept with the job (`apps/api/drafts.py`), or as the general edition with no job in view, and a job with no draft of its own uses the
  general one, which a band over its page offers to write for the job. If a fact changes afterwards, a band offers to write it again, and
  sentences that rested on that fact are marked.
- Tabs: Resume, Cover letter (drawn from the letter's draft, every sentence with its evidence units), Portfolio deck. With an agent on, the deck's
  tab offers "Draw the figures" once the resume is written, and says what it sends. The tab shows the slides as they will print,
  without a PDF: the deck's own page in a frame that runs no script, made again when the profile, the draft or the colours change.
  "Typeset PDF" shows the PDF's own pages once "Make PDFs" made them.
- With no job in view, "Make PDFs" makes a general edition: the same build, kept in the folder `jobs/-general/`, which is no job on
  the board. Named general editions (one for headhunters, one per target role) sit beside it under General editions in the bar's
  picker, and never on the board.
- An edition you brought in says so beside its actions: "As you wrote it" for a resume you wrote and brought in, which prints as
  written and offers no writing; "Your own file" for a document file you made, which shows its own pages and is exported as it is.
- **Blind edition** ("블라인드판"), a switch beside "Make PDFs", makes the edition in view again with the names of your table under
  bars of their width, a red band on page one and a label in every footer ([docs/USAGE.md](USAGE.md#a-blind-edition)), and shows
  the typeset pages. A band above them says that they are the blind edition, what it left out (your own portfolio file; your own
  resume file gives way to the typeset one; the cover letter's tab says the letter is left out), that your table covers nothing
  yet, or that it changed since. The switch stays as you set it when the PDFs are made again, and a resume brought in as a blind
  edition starts blind. The live canvas keeps your words as they are, for editing. "Export to Desktop" reads the blind PDFs first
  and refuses them while a covered name shows; the files are named with "블라인드" or "Blind".
- **Export to Desktop** copies the checked PDFs under readable names, never over another file. Two switches of the Style tab add
  files made from them at that moment (`apps/api/delivery.py`):
  - the Word and text files: the resume's and the cover letter's Word files are made ready for Word (`src/docx_word.py`): Pretendard's
    regular and bold faces go inside, obfuscated as ECMA-376 asks, every text line gets the exact height LibreOffice gave it (Word
    reads the typesetting's unnamed line rule otherwise, and sets a single line of Pretendard at 1.55 of its size where LibreOffice
    sets 1.19), and the title and the author are the PDF's. A Word file you brought in goes as it came;
  - the portfolio as a PowerPoint file, beside its PDF under the same name (`src/deck_pptx.py`): one slide per page, each the page as a
    picture at 192 dpi, every web and mail link of the page a transparent rectangle that a click in the slide show follows, the page's
    words as the picture's description, the PDF's title and author.

  Where this PC reaches Word or PowerPoint (Windows, and WSL through Windows' PowerShell), each file is opened there first, unseen and
  read-only (`src/office_check.py`): Word must lay the Word file out on as many pages as its PDF, and PowerPoint must give one slide
  per page. A file that fails, or that the program does not open, stays home; the PDFs go, and the toast names why. On other systems
  nothing is opened and nothing is said.
- **The latest portfolio kept on the Desktop**, a third switch, copies the general edition's deck PDF there after every make of it
  that passes its checks, one file per language ("홍길동 포트폴리오.pdf", "Gildong Hong Portfolio.pdf"), and turned on it copies an
  edition that passed already. It replaces only the copy it wrote, recognised by the hash it recorded in the workspace's
  `out/desk_portfolio.json`; a file of that name it did not write, or its copy after you changed it, is never touched, and the copy
  takes the next free name. A blind edition is never copied. While the switch is on, Export to Desktop names that copy instead of
  writing a second one.
- A submitted application's export gives its frozen copies byte for byte, Word files included, as they were frozen: the lock keeps the
  build's own Word file, and the Word-ready copy made from it is the same bytes each time.
- With a job in view the resume follows its plan: the skill groups the job needs lead, its strengths step back and
  its projects come in its order.

### Evidence on click

- Every sentence is a key. A click (or Enter) opens its evidence in the inspector: the source's own words in a note
  box with the sentence's words on the highlighter, the company and project it belongs to, and the name of the file it
  came from. The person's own words ("Your details") say so.
- Each resume sentence ends in the numbers of the evidence it rests on, small and not printed, numbered in the order the
  document first cites each fact or passage; a number's hover shows the first passage's words, and the inspector's passages
  carry the same numbers. With no sentence selected the inspector lists the resume's source files, in the order they are first
  cited, with how many sentences rest on each, and last how many rest only on what you typed.
- **Edit**, or a double click or F2 on the sentence to type over it where it stands (Enter saves, Esc puts it back): new words go into the
  fact the sentence rests on, or into the draft that wrote it (one undo step). They are checked at once with
  src/factcheck.py: a number, a tool, a counted word or a company that the evidence does not hold, or a claim stronger
  than the evidence ("led" where it says "helped"), marks the sentence.
- **Regenerate from the evidence**: the agent writes new words from that evidence alone, and they are used only when
  they pass the same checks. The inspector says that the evidence is sent.
- **Shorter**, **Plainer**, **Result first**: one press rewrites the sentence in that direction from the same evidence
  (`POST /api/v1/sentences/regenerate` with `way` set to `shorter`, `plainer` or `result`); the new words are kept only when they
  pass the same checks.
- **Lock**: a locked sentence cannot be edited, regenerated or rewritten until it is unlocked, and a new draft keeps its words.
- A sentence without evidence has a red wave under it, the toolbar counts it, a band offers "Show the first one", and
  the export and the lock are refused until it is fixed.

### Applications

An application is one job with everything it asks for, in tabs: Fit, Documents, Application questions, Interview and
Progress. The list of applications stands beside the one open; **Board** shows every application by stage and **Timeline**
every dated step.

- One box takes the posting's text or its link (the page is fetched once and only its text is kept). The company, the role
  and any application questions the posting lists are read from it.
- **Fit**, worked out on this PC by words with src/cover.py's plan: a score out of 100 beside the application's name, the
  ratings as a choice that shows one kind at a time, then each line of the posting as a row under its section, with its
  rating and how many sources cover it. A row opens on that evidence (quote, project, file) and the tools the line names
  that the profile never shows. The gaps are listed under the lines.
- **Make this job's documents**, beside its name, and **Documents**, the tab of its parts: the run of Make for this job (no posting step): the resume written and ordered for it, the
  English edition, the figures, the cover letter, the PDFs on the Desktop and the first interview scripts. Each part shows its own state.
- **Application questions** (`apps/api/answers.py`): the form's questions with their limits (characters with spaces, or
  words), read from the posting, pasted as the form shows them, or read from a screenshot, a PDF or a saved page; a limit is
  picked from a list. Each answer is written by the agent from the kept facts ranked for that question (BM25) and the posting, with the facts
  it used, then checked: length (over the limit, or under 60% of it), a number, name or tool the cited facts do not hold, the
  style pack. One that fails is written once more with the reasons; what still fails keeps its problems on screen. An edit is
  checked the same way. Copy one, copy all, or save them as one text file (never while one has a problem); a run for the job
  answers them as its own step.

### An application's interview

- The tab's five parts: **Search the scripts** (where the tab opens), **Interview deck**, **Practice**, **Question map and
  scripts** and **Presentation**. Every part is drawn by the panel itself, in its own menu, theme and layout, with its keys,
  fields, cards and lamps (`kit.js` for the search, `interview.js` for the deck, practice and the talk's script); no page of
  the kit's is framed in the tab. With no kit yet the tab offers "Make the question map" (no model) and "Prepare a presentation".
- **Search the scripts**: the contents first, every section a sheet of paper with its scripts' titles, folded into one row
  each when the window is small; a key per section above it; a box for the question as the interviewer asks it. The answers
  come up on a board of columns, a long script across several, with the answers in reading order beside it, and a vertical
  wheel turns the board a screen at a time; on a phone or a narrow column they run down one column and the sections become
  one row to swipe. Both, KO and EN choose the scripts' language (Alt+1 to Alt+3 while the keyboard is in the view, where
  they take the place of the panel's own Alt+1 and on); the settings key sets the type size and
  the column width. The ranking is the kit's own (the same lines of code as its page, `tests/packaging/test_kit_engine.py`):
  keywords with Korean stemming and synonym groups, and with `OFFEROWL_SEARCH_MODEL` set a similarity switch for bge-m3
  ([INTERVIEW.md](INTERVIEW.md#the-search-view-serve)), which asks before it turns off. The view stays as it is while you
  use it: a poll of the panel, a window dragged wider or a visit to another part keeps the question typed and the board
  where it stood. **Wide view** gives the tab the whole width (the list of applications comes back with the back key) and
  **Open in a window** opens the panel on the scripts alone (`/?job=<id>&show=scripts`).
- **Interview deck**: the deck as it prints, in the panel's parts, a tab per part and one part on the page at a time: who it
  is for with its figures, then the posting line by line with the script that answers each line and a lamp for how well (a
  script's key opens its part and goes to it, or to the search view when the deck does not print it), each part's scripts
  with the question as the interviewer asks it, the dialogue beside its translation, the notes and the other questions it
  answers, and for an English interview the lines that ask again and buy time. The tabs stay under the bar while a part
  scrolls, and a part ends with the next one's key. "Interview deck to print" opens the 16:9 pages to print ([the interview deck](INTERVIEW.md#the-interview-deck)).
- The question board, on **Question map and scripts**: the question map by category (posting lines, resume lines, portfolio
  pages, terms, behavioral, company, opening, scenarios, technical questions), each question with a lamp for whether a script
  answers it.
- The scripts, listed beside the one read: the key line, the dialogue in English first with the interviewer dimmed, then its
  translation as one note under the dialogue (never line by line between the spoken lines), and the speech
  marks drawn as the interview view draws them (a faint slash for a breath, a new line for a sentence end, stress in
  bold, the key phrase on the highlighter).
- **Practice**, also the tab's main key: a mock interview in the panel ([practice mode](INTERVIEW.md#practice-mode)). Choose the
  number of questions and their kinds, and whether the agent asks; then each question large, with Record (the microphone
  only between Record and Stop, written down when a speech model is installed) or a typed answer; the feedback as rows
  (length against the script, long pauses, fillers, what departs from your facts, the key phrase), the follow-up, and the
  script itself as the search view draws it; at the end the session's summary, kept with the earlier ones, and its scripts
  as cue cards to print. A session waits through a visit to another part; leaving the part stops the microphone.
- "Cue cards to print" and "Interview deck to print" open the kit's printable pages; the API serves the kit for the job in
  its own process, at the panel's `/kit/<job>/`, and the parts above read it there. A submitted application still gets its
  scripts written: they go to the kit's own folder, and the submitted copies stay as they went.
- **Presentation**, the tab's fourth part: what the interviewers asked for (the topics, one a line in their order, the minutes,
  the day, the format and their words), kept with **Save the brief**, and **Make the talk**, which makes the deck from the job's
  portfolio and the talk's own slides, and the script to say over it ([the talk](INTERVIEW.md#the-talk)). The script is drawn
  in the part itself: the parts' times, then each slide's picture beside its time, the running total and its words (where
  to point, what to say, the one line when time runs short, the questions to expect), then the questions with what backs
  each answer; beside it the keys to the slides and the script as PDFs and **Save to the Desktop**. It needs no question map.
- "Add scenes you wrote" takes scene files in the kit's markdown into the job's kit folder (`POST /api/v1/interview/scenes`):
  a file with no scene is refused, a name already there gets a number, and files named `deep…`, `terms…` or `notes…` keep
  those roles in kit.json.
- **Your materials** (`apps/api/materials.py`), under the scripts: files prepared for the job with other tools, kept byte for
  byte with their SHA-256: PDF, PowerPoint, Word, Markdown, HTML, text, Python, PNG and JPG, 50 MB each at most; any other kind is
  refused with `material_kind`. Drop them on the part (a folder is walked) or choose them. A name loses the characters a disk
  refuses, and a name already there gets a number. A row (name, kind, size, the day it came) opens on its preview: the page
  pictures of a PDF (the first 60 pages), and of a deck or a Word file once LibreOffice has printed it; a note as headings,
  paragraphs, lists, tables and code, every word set as text; a saved page in a frame with a sandbox and its scripts taken out;
  code and text as written, in their encoding. LibreOffice runs where the typesetting runs: in the render container, inside the
  app image, or the PC's own under the browser renderer. Where there is none, the row says so. **Open the file** answers it
  with its type and name, a web page with a sandbox policy; **Save to the Desktop** copies it under its own name and reads it
  back against its hash; **Remove** takes it off the list in one undo step, and the file stays in the folder until it is
  deleted for good from the Trash. Nothing of them goes to the agent, and the interview kit does not read them.

### Progress, the board and the timeline

- An application's Progress tab: its stage (one of four, chosen in place), every reached stage's day in a field of its own
  (a card added after it was sent keeps its real days), at the result how it ended (offer, rejected, withdrawn, or closed when
  the opening ended with no decision; a result
  written in your own words through the API shows under them and presses the key it reads as), its next step saved as you
  type, its interview rounds and its reminders.
- Interview rounds: after each call or interview, its kind (recruiter call, first, second, third or final interview, coding
  test, assignment, culture fit), its day and time, the questions asked (one a line) and how it went. A round ahead shows on
  Make under "Next", the nearest first; every round is on the timeline, and a recorded round counts as an interview reached
  in Insights whatever the card's column. The agent keeps them with the MCP tool `log_round`. A stage's lamp is unlit before the application is sent and lit while it is on its way; at the result only an offer
  is green.
- The board (Applications, Board): four columns (preparing, submitted, interview, result). Drag a card, or use its "Move to" key,
  which names the next column; a card's name opens its application. Each card has its next step, saved as you type.
- Links: an address written in a next step, a round's notes, a reminder, the timeline or a file's preview is a link that
  opens in a new tab (`noopener`, `noreferrer`), named for its service (Google Meet, Zoom, Microsoft Teams, Webex,
  Calendly, Cal.com, Google Calendar) or its site, the whole address on hover; on a key that holds the words (a card's
  next step) the links stand beside it (`core.js` `linked`).
- A timeline of every dated step and reminder, newest first.
- Days and times read one way across the panel: 2026-11-09, 11-09 on a card or an axis, 19:00. The day and time fields
  show them so, whatever the browser's own pattern, and the calendar or clock key beside one opens the browser's own; a day
  typed as 2026.11.9, 2026/11/09, 20261109 or 2026년 11월 9일 is read and shown back as 2026-11-09.
- Reminders: a day (and a time) and a few words on a job. An application that reached its result has none due. Due ones
  show in a band and in the navigation's count; with
  the person's permission the browser shows them as notifications on this PC; "Add them to your calendar" saves an
  iCalendar file. `GET /api/v1/reminders/due` lets the desktop app show them too.

### Insights

The whole search on one screen (`insights.js`, numbers from `GET /api/v1/insights`). At the top a persona strip: the
headline, the profile's own summary cards, the competencies, and the three areas the postings ask for that are met
best and least. Then six numbers (applications and how many are open, the share that reached an interview, the average
fit and the best, the facts kept, the career's length, the middle wait from submission to interview) and the figures:
the progress funnel with where the cards stand now and how the ended ones ended; the moves per week (submissions and
interviews); a strengths and gaps map, where each dot is an area, placed by how many requirement lines ask for it and
how much of them is met (a ring is an area of any trade, such as communication); every area's lines met, in part and
not met, with the facts that back it; the unmet lines of the areas asked most, with the fit of every posting on one
strip; each open application's readiness (its fit, its interview map's coverage, its form answers, its next step); and
the career's spans with the facts by kind. A requirement line is sorted into an area by its words, the same words
that sort the facts; the profile's skill groups add their tools to the area their group's name belongs to, and a line
about the hiring itself (how to apply, the rounds) is left out. Colour carries one meaning each: a stage's colour, or
met (teal), in part (neutral) and not met (red), checked with the dataviz palette validator in both themes; every mark
answers a hover with its numbers. Four figures to a row on a wide screen, three on a laptop, two on a tablet, one on a
phone, and the figures are drawn for the width they get.

### The command bar

**Ask the AI**, a prompt floating at the window's bottom right with its key at its end (on a phone or a tablet, a frosted
bar along the foot of the screen), or Ctrl+K (Cmd+K), opens a sheet flush with the window's right edge, from the top bar
to the window's foot, where you write to the agent as you would in Claude Code or Codex: an interview's result to record, a
posting to make a resume for, a question about your applications. With no agent that can use the tools (Claude Code or
Codex, on and signed in) the sheet says so before anything is typed, with a key to the agent's panel. The
agent runs once, in an empty scratch folder, with Offerowl's MCP server pointed at the panel the ask came through
(`apps/api/ask.py`): Claude Code with `--strict-mcp-config` and no built-in tools, or Codex with that server as the only
one for the run (Codex keeps its own read-only shell; it has no switch to turn it off). Whatever it does goes through the
same routes and checks as the panel's keys. It fetches a posting from a link only when that link is in your own words in
the bar, and it is told that what it reads (postings, files, documents) is material, never instructions. A local model
cannot act through tools, and the bar says so; an ask that
times out or fails is said in the panel's words, and words not sent stay in the box. The answer comes back with the
tools that ran; the last 30 asks are kept in `ask/history.json` and read with `GET /api/v1/ask` (`POST /api/v1/ask {text}`
starts one). The bin key in the bar's head empties that history after asking (`POST /api/v1/ask/clear`); what the agent
did stays, and undo takes it back as before.

### Library

Every file brought in or made, in one table (`library.js`, the list from `GET /api/v1/library`): the profile's files and
photo; each application's posting, materials and form questions; the PDFs of every edition and language; the copies
that went out; the interview kits. Filter by kind, by owner or by name; 14 rows to a page. Each row opens its file,
copies it to the Desktop or removes it through the routes the list names for it (`POST /api/v1/library/export` for most
copies), in three fixed places so a key stands in the same column on every row. Backup,
restore and the workspace folder are at the top.

**Removing and the Trash.** Removing never asks first. A file of the profile, the photo, an application, a named edition or
an application's file waits in the Trash, and the note that says it was removed holds **Undo**, which takes back that change
only (the write's answer names its own undo step; if another change came after it, the note says so and nothing is undone).
A reminder or an interview round has no place in the Trash: its note's Undo, or the bar's, brings it back. The Library's
**Trash** key, last of the kinds, lists what was removed, newest first, with the day each went (`GET /api/v1/removed`,
`apps/api/removed.py`). **Put back** brings one back where it was, in one undo step; a file of the profile comes back with
its facts as they were decided, or, when they cannot come back whole (another imported profile took its place), unread,
with a key in its note to read it again. **Delete for good** and **Empty the trash** ask first on the panel's own sheet,
which says what goes and what stays: the thing's files and records, the facts read from it and its copies in the undo
history go, so no undo can bring them back; documents and drafts already made from a file's facts, the details it filled
in, copies on the Desktop, backups saved before and the command bar's history stay. Deleting a file of the profile or an
application waits while a task runs (a reading could bring facts back, a build write into its folder), and an application or
an edition in the Trash takes no work at all (no analysis, build or edit) until it is put back. Every removed photo is kept
under a name of its own, so removing a second one never deletes the first. The folders a
backup's restore kept beside the workspace are listed under the Trash too, each to delete on its own. Where things were
removed, a quiet key says how many wait in the Trash: under the profile's files, and beside the applications' title.

### Inspector

- **Evidence**: the selected sentence, as above; with nothing selected, the counts (sentences, edited, locked,
  without evidence).
- **Fit**: the score, counts and gaps of the job in view, "See every line" and "Make this job's documents".
- **Style**: the writing rules (Offerowl's own, or a style pack the person added), the blind edition's table (yours or
  Offerowl's, which covers nothing; how many patterns it covers, covers whole and never lets show; "Use your own table" picks a
  JSON file, which is checked and kept in the workspace, and "Use Offerowl's own" takes it away), the document language, the page
  limit (two to seven), what tailoring makes (the cover letter, the PDFs), whether the Desktop gets Word and text files too and
  the portfolio as a PowerPoint file too, and whether the latest portfolio is kept on the Desktop, with the names it keeps there.
- **Theme**: the resume's form (detailed, one column, tables), the deck's look (classic, light), the colour of both (navy, teal, grey, wine, forest, slate), and the
  app's light, dark or automatic look.
- **History**: every change, newest first. A click asks first on the panel's own sheet (there is no redo), then undoes it
  and everything after it.

### Everywhere

- Korean and English, light and dark: in Settings; the browser keeps the choice.
- Autosave and undo: every change is saved at once, and "Saved" says so. Undo (the bar, Ctrl+Z outside a field, or the
  History tab) takes back the last change; a removal's note holds an Undo key of its own for that change alone.
- Questions before what cannot be taken back (deleting for good, emptying the Trash, restoring a backup, undoing from the
  History tab, emptying the command bar's history) come on the panel's own sheet, never the browser's: its title says what happens, its lines what stays,
  and the safe key holds the keyboard, so Enter, Esc or a click beside it says no.
- No file paths or commands on screen. Files are named by the name the person gave them.
- Errors say what happened and have one fix button, for example "No agent is turned on, so the agent could not do
  this." with "Turn on the agent".
- Every action that sends something to the agent says so in orange ("Goes to the agent"); the rest say "Stays on this
  PC" in blue.

## The design system

**The desk at night.** Offerowl is someone working late at a desk on a resume and the interviews ahead, and the boxes
themselves carry it, as frosted glass: every card is a milky pane with the frost's fine grain under the same desk lamp,
brighter at its lit top left corner and thinner toward the bottom right, with a bright rim, a one-pixel light along its
top and one soft shadow under it (half white over a 20 px blur, half a dark slate in the dark look). Nothing is carved
into the desk or raised off it, and there is no grid. The desk is a cool pale grey (a deep slate in the dark look) with a
paper grain, the lamp's warmth spreading from the top left and the night's blue gathering in the far corner, so every
pane has light to frost.
The top bar is such a pane across the window at every scroll: the views are a track in it, the view in use a key
standing in the track, and what scrolls under the bar is frosted past reading. The boards that lie on it (the notes in
progress on Make, the board's stages) are trays of thinner frosted glass, the desk's light between their notes, and a
note's paper keeps it from behind its words; Make's three columns are their heads and cards, with no panel round them. A note is paper: one
even tint with a soft sheen, its folded corner the paper's lighter back, its keys and initials outlines drawn on it,
its shadow following the fold. After dark on this PC (20:00 to 06:00, `data-hour`
set by core.js) the lamp burns brighter. The colours come from the logo: the owl's blue on the main key (its white
brows in the dark theme), its eyes' yellow where the keyboard is, on the view in use and for selected text; the
logo's eyes in the bar glow while something is being made (`data-working`). No picture or character is drawn. The light falls on the page and never fills
a surface with colour. A rainbow rim marks what goes to the AI agent and nothing else: the Ask the AI box and the sheet's box,
and the places that take the files the agent reads (Make's and the profile's drop zones, the box for paths); every other
field shows the focus colour while in use. Keys are flat panes of the same glass with a hairline rim, as Sidenote's
keys are: no light along their top and no shadow, brighter under the pointer and a shade deeper when held; the main key
is a flat fill of the owl's blue, a key whose work goes to the agent a pale orange, one that keeps or turns a thing on
green, a move on the board its stage's colour, a removal red words. Fields are flat panes with their rim. No box stands inside another: a choice of a few is its
words in a row, the one chosen in the ink with the line of the view in use under it (as the bar's views and every tab);
a badge is its dot and its words; a count is its number; Make's three steps are each one pane with its head inside and
its parts divided by a hairline; an application's tabs hold no panes; a quote is a line beside its words; the command
bar opens as a sheet beside the page, as the settings do. A note (the toast) is frosted
glass in the top bar, in the room between the views and the keys (two lines at most there, else over the views, which
step aside while it shows), with a mark of its kind before its words and its key as words in the link colour: done
(green), held back (amber), failed (red) or word of something (blue). On a phone it is a band across the top of the screen, and the bar's row under it steps aside.


`apps/panel/static/tokens.css` holds the base tokens and `components.css` builds the parts from them: keys, lamps (a
dot and a word), toggles, chips, segmented choices, tabs, fields, cards, the note box, the drop zone, bands and the
toast. `skin.css` lays the look over both, as CONTRIBUTING.md describes it: a lit desk, hairline rims, square corners,
flat keys coloured by what they do, stage badges of a pale fill and a strong word, frosted glass for what holds
controls and opaque surfaces for what is read. `combo.js` draws every dropdown (a key and a list of the panel's own, by
mouse and keyboard) and leaves the `<select>` hidden in place, so the views read its value and its `change` as before.
`viz.js` draws the figures: a bar of parts with its legend (the applications by stage, the posting's lines by rating,
the facts by kind, a kind of question by how much a script answers it) and the fit's score on its bar. Make's
applications in progress are sticky notes (a square of paper in its stage's colour, its bottom right corner folded up),
and so are the Board's cards; an application's interview tab draws the kit's contents, search, script cards, deck, practice
and talk script with these same parts.

- Rows and columns line up. Keys, fields, menus and segmented choices are one height (34 pixels; 28 for the small
  keys inside cards) and share a middle when they stand in one line. Cards that share a row end together: Make's three
  columns take the rows of one grid (CSS subgrid), so the cards of a row start and end at the same lines, and a card's
  foot line (its figures, its keys) sits on its foot. The run's documents stand a row per language and a column per
  document. The tracker's stages, the interview board's columns and its script cards do the same. The layout audit
  measures it (`align` in tests/app/audit.js).
- Motion (`motion.js`) says what changed, once: a view fades in as a whole when it opens, a finished step's lamp lights
  with a little weight, the run's bar goes on to its new length, a run's documents rise tile by tile, the agent's
  figures count to their values, a switch's knob travels, the open job's bookmark drops, a menu opens. Nothing moves at rest, and nothing loops but a lamp at work, whose pulse goes on through a redraw. The
  page draws itself again on every poll, so each motion is played with the Web Animations API after a draw, and only
  when what it shows is new. Motion is on by default; the menu's Motion turns it off, or **Auto** follows the system's
  request for less.
- Everything works with the keyboard: Tab order follows the page, arrows move between the inspector's tabs, Enter or
  Space opens a sentence's evidence, Escape closes what is open, Alt+1 to Alt+6 open the views, Ctrl+K (Cmd+K) opens the
  command bar, Ctrl+Z undoes.
- Screen readers get names for the panes, the tabs, every key with an icon, the lamps and the state of each sentence;
  a skip link leads to the document.
- Contrast is measured in both looks (tests/app/audit.js): 4.5:1 for text, 3:1 for large text.
- Layouts run from a 390-pixel phone to a 2560-pixel screen.

## Safety

The panel and its API follow the rules in [Safety](ARCHITECTURE.md#safety).

## Tests

```bash
python3 -m unittest tests/app/test_panel.py -v       # the API on the fictional example (seconds)
python3 tests/app/walk.py --out <folder> [--render]  # the browser walk with screenshots and the layout audit
python3 apps/desktop/app.py --check                  # the desktop app's own check
```

- `test_autopilot.py`: a folder and a posting give every document; a posting alone tailors what is kept; a posting sent
  during a run follows it; the name and contact from the files, and a name the person typed stays; one edition's PDFs again;
  a folder with nothing readable, no agent, and a stop; Windows paths and the WSL Desktop.
- `test_delivery.py`, with Word and PowerPoint stood in for: the Word file made ready for Word and kept home when Word gives it other
  pages or does not open it, a broken one kept home and the person's own sent as it came; the deck as a PowerPoint file beside its
  PDF, kept home when its slides are not the pages; a failure after it taking every copy back; a submitted edition's frozen Word file
  sent byte for byte; the portfolio kept on the Desktop: off unless asked, copied at once when turned on and after a make that passes,
  its own copy replaced and nothing else (a file it did not write, its copy changed by the person), a new name taking its old copy
  away, never after failed checks or a blind make, and named by the export instead of copied twice.
- `test_removed.py`: the Trash on a fresh workspace with fictional data: a profile file, a job and a job's file that each
  carry words found nowhere else are removed, listed with their day, and deleted for good, after which no file under the
  data folder holds those words, the undo steps included, while undo still works; a file of the profile put back whole after
  later changes, a job and a named edition put back, the photo put back with the one added since going aside; a note's Undo
  that never takes back a later change; ids never given twice; the asides listed and deleted by their own name only (never
  a link or another folder); deleting refused while a task runs and for anything still listed; the command bar's history
  emptied.
- `test_materials.py`: a job's materials brought in as the page sends them, listed with the job, handed back byte for byte,
  refused by kind, size and job, kept under safe names with a number for a twin, removed and brought back by undo (a file added
  after the removal stays), copied to the Desktop and read back, left out of a backup's pictures, and previewed by kind; a deck
  and a Word file are printed in the render container where its image is built (skipped elsewhere), and the converter's command
  is checked without Docker.
- `test_mcp.py`: the MCP server of `offerowl mcp` against a real panel on the fictional example: the protocol over stdio through
  the launcher, every reading tool, tailoring, the kit and its search, board moves and reminders, read-only mode, the
  address check, and the error a missing panel gives ([MCP.md](MCP.md)).
- `test_interview_views.py`: what the interview tab's own parts read, on the fictional example: every script with its words
  in the panel's language, the deck's scripts in the printed deck's order, the talk's script and its slides' pictures (by
  their place only), a 304 for an unchanged view or deck, and a 404 that says so for a job with no kit or no talk.
- `test_panel.py`, with the agent off or the stand-in, and no model: the onboarding record; the resume model and its schema;
  the evidence of a sentence (file and quote); an edit with a number the evidence does not hold (marked, export
  refused, undone); locks and the history; a job's fit and its schema; tailoring (resume done, cover letter needs the
  agent, interview kit done); the interview board; a posting from a link on a local page, and links that are refused;
  the tracker, reminders, the timeline and the calendar file; the stand-in reading notes, analyzing the posting and
  regenerating a sentence through src/llm.py; the safety rules; the in-process client; the schemas against the
  examples and against planted problems; the Korean table.
- `walk.py` drives Chromium. It times the first look (the make view, then the example person's resume), then measures
  every state (Make with the example, the resume, a selected sentence, an edit and an
  unsupported sentence, the profile, a fact being edited and one being typed in, the job form, the fit, the tailored job, the resume for
  the job, the cover letter without an agent, the typeset view without a PDF, the interview board and its scripts, the
  kit's contents and a question's answers, its deck, practice's setup, a question and its feedback, the presentation's
  script, the job's materials with a note open,
  the tracker's board and timeline, the Library and its Trash with the question before deleting for good and a removal's
  note with its Undo key (then one put back and one deleted through the keys), each inspector tab, the menu, the agent on
  through the stand-in, the agent's panel, the
  setup guide's four steps the first time and its agent step from the menu, and a
  whole run from a dropped file: Make while it runs and when it is done) at 2560x1440,
  1440x900 and 390x844, light and dark, Korean and English, with `tests/app/audit.js`:
  - overflow: text outside its box, text cut by a box that does not scroll, a word broken across lines (a compound word
    may break after its hyphen, as English is set), the page wider than the window;
  - truncated: text cut short with an ellipsis;
  - overlap: two lines of text on top of each other (text under a fixed layer that is opaque, or frosted past reading
    with half a fill over a blur of 12 px or more, is hidden, not overlapping; under clear glass it counts);
  - markup: `==`, `**`, tags, entities, `{name}`, `undefined`, `NaN` or `null` on screen;
  - paths: a file path, a command or a setting name on screen;
  - contrast: text under 4.5:1 (3:1 when large) against what is behind it, glass composited over the desk;
  - align: keys and fields side by side in one line that differ in height or sit off each other's middle, tiles of one row
    that end apart, and Make's columns whose heads or first cards leave one line;
  - center: a one-line key whose words or sign sit more than a pixel off its middle, up or down, and across when its
    contents are centred. The words' middle is their body from the font's own measure (Hangul syllables, or the
    capital's height for Latin letters and figures), not the text's box, which holds the font's whole ascent and descent.

  The audit first runs on a page with one planted defect of each kind and stops when it misses one. The last lines
  read `first run: N s from the page to the example's resume (backend none)` and
  `walk: N states x 12 views, overflow 0, truncated 0, overlap 0, markup 0, paths 0, contrast 0, align 0, center 0`. It keeps
  `report.json` and one screenshot per view in the output folder.
- `--check` starts the server with the stand-in agent (`OFFEROWL_PANEL_AGENT=standin`) on a free port. It fetches
  `/health` and the page, adds a small text file, lets the stand-in read it through src/ingest.py, and stops. It prints
  `ok`, or one `FAIL` line per problem.

## The one-file build

`apps/desktop/build.py` builds with PyInstaller `--onefile` and has the panel, the API, the schemas, the engine (src/), the
example, the fonts and the icon inside. It also carries Node.js, the release and checksums pinned in
`apps/desktop/node/pins.json`, and the pruned typesetting libraries; the app unpacks Node.js once into the data folder. Then
the build runs the result with `--check`, which also makes the example's resume, deck and cover letter, and fails when the
check fails. `--no-runtime` leaves Node.js and the libraries out, for a quicker build that cannot make documents.
`tests/desktop/e2e.py` runs the built file on a PATH with no Docker, Node.js or Python, through the panel's API, and its
`compare` mode checks each PDF against the container's. The modules are loaded from files at run time, so the build reads their
imports and bundles every standard-library module they use. A Windows build needs Windows. Build each system's file
on that system, by hand or in CI:

```bash
python -m pip install -r apps/desktop/requirements-build.txt
python apps/desktop/build.py          # dist/Offerowl(.exe) and dist/Offerowl-<system>-<machine>(.exe, or .zip with Offerowl.app on macOS)
```

In CI, `.github/workflows/desktop.yml` does the same on Windows, macOS (Apple silicon and Intel) and Linux, with no
model (`OFFEROWL_LLM=none`): it installs the build tools, runs the panel's tests, builds the file and starts it with
`--check`, runs the end-to-end test on Linux, and keeps the files with the run. A version tag attaches them to the GitHub release (`release.yml`).

## Known limits

- The live canvas and the typeset PDF are two drawings. The PDF is the authority, and the canvas follows its layout.
- The canvas edits Korean sentences of a Korean profile; an English edition of it is made by translating again.
- The panel's language follows the browser until one is chosen in Settings.
