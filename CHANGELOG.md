# Changelog

What changed in each release of Offerowl. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/). Each release's section here is its release notes. Security
fixes come first in a release.

## [Unreleased]

## [0.9.1] - 2026-11-13

What three independent reviews of 0.9.0 found: the panel outside the interview tab, the interview tab, and the code.

### Fixed

- A question an interview round asked was tied to a script that only shared a word with it ("Why did you apply?" to a
  script about applying elsewhere), or to none ("Why this role?" is all stop words to the coverage rules). The script whose title is the question's now answers it; words in common with another script make it an answer
  only in part, which the round's key offers to write again. A draft answering it shows as a draft, never as a finished
  script, and the map counts the agent's draft scripts. The script key's hover shows the script's title.
- Practice and the interview deck did not see a round's questions until the question map was made again: they read them
  from the rounds as they are, as the board does. In a deck that follows the kit's file order, the round's questions come
  right after the greeting (each script once), and a draft's hidden source line no longer shows in its notes.
- "2.0 버전에서 바뀐 점은?" lost its "2." as a list mark, and "CI?" or "왜요?" were dropped as too short.
- The day several applications were added on was offered for clearing when they were added by hand, their true preparing
  days among them: only a day that a later step's earlier day disproves counts now. A round with more than 30 questions
  without a script is written 30 at a time instead of refused. "1시간 30분" in a round's notes is 90 minutes, and "10분 전
  입장" is no length. A round of today that ended leaves Make's "Next" line, today's rounds say "오늘", and the time left of
  one going on is green there too; two rounds of one application today no longer draw the page again every 15 seconds.
- The board showed the day an application was added as its stage's day when the stage had none: it shows none.
  The timeline names the applications with no day instead of leaving them out without a word, puts one application's
  steps of a day in one chip, the later step first, and its line no longer runs through the names on a phone.
- The days table: an empty day is empty instead of "YYYY-MM-DD", the marks are said in a line over it (amber, dashed for
  the day the band's key clears), the band's sentence keeps its meaning, and the clear's note says what it cleared.
- The request sheet slid in again at every answer and showed a request twice while it ran; it is frosted like the
  settings' and the agent's sheets. Make's cards on a phone show the role (two cards of one company looked the same). The
  Trash tells copies of one file apart ("사본 10"). The photo's, a question's, an edition's and the requests' removal keys
  say what they do. A page of the Library holds a row more.
- A posting's "About you" (and "Your profile", "What you bring", "The ideal candidate", "Skills & experience") opens its
  requirements: their lines were read as duties.
- On a phone: the call's link on today's line, practice's count and kind keys, the deck's script keys and the kit's contents
  rows are 44 px; the "주의" label of a script is readable; the progress tab's note on days out of order says what follows
  from them.
- The release's image cache is kept in the registry, which the next tag's run can read (Actions' cache is per ref).

## [0.9.0] - 2026-11-13

What an interview round leaves behind now feeds the next one, the day of an interview has its own line, and an
application's days can be put right in one table.

### Security

- The public repository has Dependabot alerts and security updates, and CodeQL code scanning, on. What its first scan
  found is fixed: a saved page's preview, and the live deck's frame, remove a script whose end tag holds more
  (`</script foo>`) or is in capitals (the frames' sandbox ran none of it either); the kit's server answers a page's origin
  with its own list's value, and the panel's redirect to a kit escapes the id and the query again; the kit's font route makes
  a path only from its list of names.

### Added

- **The questions an interview asked lead the kit.** The questions written down under a round (one a line) are the
  question map's first kind, "Asked before": the interview deck shows them right after the greeting, practice asks them in
  the words they were asked in (the agent never rewords them), and the next scripts answer them first. A question asked
  again in a later round is one entry with both rounds, and its id comes from its words, so its draft stays its draft when
  lines are added above it.
- Under each round every question has a lamp and the key of the script that answers it, which opens that script in the
  scripts' search. The questions no script answers, or one only in part, get scripts of their own with one key: the agent
  writes them under a section of their own (L, or the first letter the kit leaves free), answering each as it was asked and
  going one step deeper. `POST /api/v1/interview/scripts` and the MCP tool `write_interview_scripts` take the map's `ids`.
- **Today's interview on its application.** A round of today shows on the application's head on every tab: its hour, the
  time left or how long it has been going on (kept current, its length read from its notes, such as "15:00~15:30"), the
  call's link and the scripts' search. Once it ends, the line offers to write down the questions asked. Make's "Next" line
  shows the time left for today's rounds too.
- **Every application's days in one table.** The timeline's "Edit the days" key opens a table of every application's stage
  days. When five or more applications were added on one day and carry that day as a stage's day (a list brought in at
  once stamps its day on every card), one key clears that day from all of them in one undo step
  (`POST /api/v1/tracker/clear_day`).
- The kit check names two sections with different titles under one letter (a section taken over from another kit), without
  failing: the scripts are sound, only their keys look alike.

### Fixed

- The kit's contents scrolled at common window sizes (1920 x 1080 with one kit, 1680 x 1050, 2560 x 1300 and others): the
  row of section keys above them was squeezed while the contents were fitted, so the largest groups were folded for a room
  21 px taller than the view had. The row keeps its height, and every size measured fits on one screen.
- A section that runs on into another column did not always say its name again at that column's top: when the widest
  columns have no room for the names, narrower columns, or one more folded group, make room.
- A stage's day later than a later step's day (a card moved on after it was sent or answered, the day of the move stamped
  on it) counted on the timeline and in the charts for every stage, not only for "preparing". It stays on the card, is left
  out of both, and the days table marks it.
- What CodeQL's first scan found: a slide's words read "&amp;lt;" as "<" (the entities were decoded twice); a quote in a
  picture's attribute value ended the attribute early; a long run of digits followed by a letter made the interview
  audit's name finder backtrack exponentially (22 digits took 0.15 s, each one more doubled it); a ledger's comment written
  inside another left "<!--" in its text.

## [0.8.1] - 2026-11-13

What a look at the whole panel, and at the interview tab's scripts and deck above all, found after 0.8.0, with the AI
prompt back where it was asked for.

### Fixed

- **Ask the AI** is a prompt floating at the window's bottom right again, as it was asked for, with its key at its end; 0.8.0
  had moved it into the top bar. A page's end scrolls clear of it, and the search view's board ends above it.
- The settings and the agent's panel stood 240 px short of a wide window's right edge: they dock at the window's edge, as
  the request sheet does.
- A toast now reads as Sidenote's note does: frosted glass at 42 %, one 38 px line in the top bar, the lead word in bold,
  and its key tinted with the note's colour.
- Words that named Claude Code alone name Claude Code or Codex (the request box, its empty sheet, reading your files).
  Practice named its interviewer by its setting (`claude-code`): it says "Claude Code", "Codex" or "Local model", and so does
  each session in its history. A request's steps are named in words ("Read the applications") instead of the tools' names.
- The interview deck on a phone ran 223 px off the screen: the deck fits, the posting's table puts each line's script under
  it, and the part keys slide in one row.
- The interview deck ran to tens of screens in one page (52,000 px at 2560, 101,000 on a phone): it is a tab per part with
  one part on the page, the tabs held under the bar as part of it while a part scrolls, each part ending with the next one's
  key. A tab says its part in a few words ("Phone screen" for "Phone screen: career, motive, terms"). A line names
  its speaker on the same line, as the printed deck does. A scene's dialogue runs on into the second column when it is the
  longer half, so the notes' column is not left half empty. A posting line shown with a term's entry is never marked as
  answered in full.
- The search view's long cards left inner columns half empty: a long translation runs on into the next column with its
  frame on both sides. With KO chosen, the Korean is the script itself at the body's size, not a grey note. A card uses
  two type sizes, the one chosen and nine tenths of it.
- A question in the search view drew all its answers before showing any: it draws the first two screens, then the rest.
  Cards are measured together and kept measured between questions (at 1440 x 900 the median wait fell from 747 to 433 ms).
- The sections' keys took three to five rows: they slide in one row, each in a few words, the reference files named by
  what they hold ("Your stories", "English phrases"). A section opened from its key shows its own scripts in their own
  order; an item number's board marks where the next section starts. The list beside the board says how many answers it
  had no room for. Each column width choice changes the board, the wide view takes the window's width, and on a phone the
  question box stays at the top while the answers scroll.
- Practice fills the tab's width, without the line about the microphone.
- The presentation's script said its draft note on every slide: it is said once at the top, with a tag on each such slide,
  and a slide's picture is at most 400 px wide.
- Undo from the History tab took back the listed steps even when a change came after the list was drawn, so the newest
  change went too: the page names the newest step it listed, and nothing is undone when another came first.
- A document asked for while the panel was busy or briefly unreachable stayed failed until the page was opened again: it
  is asked again after 2, 4 and up to 30 seconds. An upload refused because the panel was busy is sent again once, and
  the files that could not be added are named.
- A busy panel's refusal, a missing job and other refusals say what happened in words. Opening the general edition's
  card by its id returned an error page; it is a 404.
- An answer's length counted a character outside the basic plane twice; it counts characters as the form and the server
  do. Pressing a job's make key twice started two runs. A field's caret went to its start after a redraw.
- The Library's and the Trash's row keys were icons only: they say Open, Export, Remove, Put back and Delete for good.
  The Trash shows the hour a file went (several went on one day), and a page of either holds as many rows as the window.
- Two applications at one company are told apart by role in the timeline, the reminders, the "next" line and Insights.
- The wait from submission to interview took the upper of two middle values: it is their mean, with the number of waits.
- A long file name broke before its last letter: it wraps at its underscores. A cover letter you brought in said no
  letter was written; its evidence tab says it is your own file. The style tab says when the PDF on screen was made with
  another page limit. The Make view names the edition its sentence count is of.
- The fit's ratings read Met, In part and Not met, as Insights says them ("None" sat beside "1 source"). A submitted
  application's state read as a command in Korean ("제출하고 잠금"): it reads "제출본, 잠김", and its Make PDFs key is gone
  instead of greyed out. Guidance sentences on the fit, the materials, the rounds and the Trash gave way to the state
  they describe.
- The evidence quotes had an amber stripe at their side: a grey line, as a printed quote has.
- On a phone the four stages and the fit's four choices stay in one row each, in their order, and the day fields take the
  row (two to a row cut "YYYY-MM-DD"). The Library's Trash key takes its own row.
- The applications' page scrolled 96 px past a list that already fitted the window.
- A stop from outside (SIGTERM) right after the panel started ended once in a crash (SIGSEGV) on Python 3.12, after the
  panel had wound down cleanly: Python's own tear-down ran while a background thread was still at work. The panel now
  ends at once when it has wound down, its log and console flushed, as the panel and as the desktop app's server.
- The desktop app said that it could not start, or that its server kept stopping, in the system's grey message box: it
  says so on a page of Offerowl's own look in the browser, with the end of the log and a key to the logs folder. On macOS
  and Linux it said nothing outside the log.
- A toast on a phone stands in the bar's place at the top of the window, and the page runs under it once the bar has
  scrolled away: it was frosted too thinly to read over the words beneath, and now has the bar's own glass. A toast that
  came while a question was open showed under its dimmed backdrop; it shows above it.
- A request to the AI that ended with its sheet closed, or a run that made the documents while another view was open,
  ended without a word: a toast says so, with a key to the answer or to the run, as Sidenote's notes take one to the answer.

### Changed

- The CI uses `actions/checkout`, `actions/setup-python` and `actions/setup-node` v7 (Node 24).
- The lint pass checks the stylesheets too: a comment left open after a rule swallowed the rules under it without a
  word from any browser or test (it took a card's title and the deck's spacing during this release's work).
- `GET /api/v1/history` gives each step an `id`, and `POST /api/v1/history/undo` takes `newest`, the id of the step the
  page listed first ([ARCHITECTURE](docs/ARCHITECTURE.md)).

## [0.8.0] - 2026-11-12

The interview tab drawn by the panel itself; when many requests come at once, when the panel is stopped, when it crashes,
and what a load of the page costs; the interview kit's similarity search in the panel; one more decision model measured.

### Added

- An application's Interview tab draws every part in the panel's own menu, theme and layout, with its keys, fields, cards
  and lamps. It showed the kit's own pages in frames before, with their own bars, type and cards, which read as another
  program inside the panel.
  - **Search the scripts**: the contents with every section and its scripts' titles, a key per section, the question box,
    and the answers on a board of columns with the answers in reading order beside it; one column on a phone. The ranking
    is the kit's own code, the same lines as its page (`tests/packaging/test_kit_engine.py`), so a question finds the
    same script in both. KO, EN or both, the type size and the column width are kept per browser.
  - **Interview deck**: the printed deck's scripts in its order, in the panel's parts: who it is for with its figures, a
    key per part, the posting line by line with the script for each line and how well it answers, then each script with
    its dialogue beside the translation and the notes, and the lines that buy time. A script's key in the posting's table
    goes to it.
  - **Practice**, a part of its own and the tab's main key: the mock interview with its setup, the question, Record or a
    typed answer, the feedback as rows, the follow-up and the script as the search draws it, then the summary. It opened
    the kit's page in a new tab before. Leaving the part stops the microphone; the session waits for your return.
  - **Presentation**: the talk's script with each slide's picture beside its time and its words, then the questions to
    expect with what backs each answer.
  - **Wide view** gives the tab the whole width, and **Open in a window** opens the panel on one application's scripts
    (`/?job=<id>&show=scripts`).
- What those parts read, in the API: `GET /api/v1/jobs/<job>/interview/view` (every script with its words),
  `/interview/deck` (the deck as data, in the printed deck's order), `/talk/script` and `/talk/slides/<n>.png`. The two
  large ones come with an ETag, and the page asks again with the copy it holds, so an unchanged kit costs a 304 and no
  body.

- A stop from outside (SIGTERM or SIGHUP: `docker stop`, a pod's end, the desktop app's quit) ends the panel as Ctrl+C
  does: no new request is taken, the ones being answered finish (up to `OFFEROWL_STOP_GRACE` seconds, 5), the tasks still
  running are named in `logs/panel.log`, and the port is let go. It ended at once before, without a word in the log.
- A request no slot is free for is answered 503 `busy` with `Retry-After: 2`, and the page sends it again after the
  seconds asked, twice at most (it never reached the API, so nothing of it was done twice). It was closed unanswered after
  10 seconds before, and the page saw a network failure. `OFFEROWL_MAX_REQUESTS` sets the slots (4 to 1024, 64).
- A task that waits for another to finish (one model task and one rendering run at a time) says so on the page, "Waiting
  for the task before it to finish", and shows its own step again once it runs; it said "Starting" all along before.
- A fifth decision backend, `vega`: Vega, the engine Laya's maker published on 2026-11-05, run on this PC through the
  maker's own package, with its reader downloaded only on purpose (`python3 src/decide/cli.py fetch vega`) and its
  engine pinned to the revision measured. Measured on the same labelled sets in a container with no network: below
  Laya and far below the agent on every step, so, like Laya and Jev, no step of Offerowl takes it
  (`docs/DECISIONS.md`).
- `python3 src/interview/cli.py eval --questions FILE` measures the kit's search on another question set of the same
  form. `tests/decide/fixtures/kit_questions_reworded.json` asks about the example kit's cards in other words than
  theirs, 14 questions in English and 14 in Korean: the search puts the right card first for 16 of them with keywords
  alone and for 24 with the similarity model switched on. Laya and Vega, asked to pick the card or to reorder the
  search's first three, did worse than the search they were given (`tests/decide/kit_search.py`), so no decision
  model goes into the search.
- The panel's interview kit can use the similarity model. `OFFEROWL_SEARCH_MODEL=<bge-m3 folder>` names it once: the
  search view in an application's Interview tab and at `/kit/<job>/` then has the similarity switch, and `serve` takes
  the folder without `--model`. It could be switched on from `serve --model` only before, never in the panel. The 28
  reworded questions typed into the kit at the panel's address score the same 24 and 28 with the switch on.

### Fixed

- The interview kit's search inside the panel lost the question typed into it three seconds after it opened, and
  whenever the window was dragged wider or narrower: a document fetched for another view (Insights) and a new width each
  drew the application's page again, and the kit's frame with it. The tab now draws the search itself and keeps the
  view, its question and its board's place through any redraw of the page and a visit to another part.
- Practice's summary in English read "1 answers"; it reads "answers 1", as its other figures do.
- A kit's server read kit.json once, when it started: scripts added afterwards kept the role and section name it had
  then (a terms file listed as scenes) until the panel was started again. It reads kit.json again when it changes.
- A job whose interview folder held only a talk's brief counted as having a kit: its Interview tab showed an empty search
  view. A kit is its settings file now, for the board, the scripts and the deck alike.
- The talk of the general edition, which has no interview folder, ended the request with no answer; it reads as not made.
- Space on a key of the kit's search page moved the keyboard to the search box instead of pressing the key.
- A burst of connections was mostly dropped: the server let the system hold only 5 waiting connections, Python's own
  number, and the clients past them asked again a second, then 3, 7 and 15 seconds later. It holds 512. Measured with
  1,000 requests for the state at once: 100 timed out after 30 seconds before, all are answered within 7 seconds now;
  300 at once took 27 seconds before and take 3.
- The Jev decision backend read its answers in the shape of an earlier draft: it took the confidence from a
  probability per option, which the gateway's API reference marks optional, so an answer without them had none. It now
  keeps the confidence Jev states, says so when Jev declines a question, asks again when the gateway is busy (after the
  wait it names, three tries in all), sends each item as one object of readable fields, and records the version of
  the model that answered.

### Changed

- Turning the kit's similarity switch off asks on a sheet of the page, under the switch, with its two keys ("Turn off",
  "Keep it on"); it opened the browser's own confirm box. Escape, a click elsewhere and "Keep it on" leave the model
  loaded. In the panel the same switch asks with the panel's own question.
- The scripts beside the question map draw a stage note in Korean brackets in grey and a command in its own letters, as
  the kit's cards do; they showed both as plain words.
- The panel's page frames no address at all (`frame-src 'none'`): its previews of a deck or a saved web page are written
  into their frames, and the interview tab draws its parts itself.
- The command bar is **Ask the AI** ("AI에게 요청하기" in Korean, where it read "에이전트에게 맡기기"): a box in the top bar
  whose words say what it is for, its key (Ctrl K) at its end. It was a key in the page's bottom right corner, a 32-pixel
  mark with no words on windows narrower than 2,560 pixels; a phone or a tablet keeps the bar along the foot. Its sheet
  opens flush with the window's right edge, from the top bar to the window's foot; it stood at the page's edge before,
  apart from the window's on a wide screen. With no agent that can use the tools, the sheet says so before anything is
  typed, with a key to the agent's panel.
- On a phone the similarity switch sits beside the search box. Among the keys it pushed the last one onto a row of its
  own at 390 pixels and less.
- The page's own files (index.html, its scripts and styles) come with an ETag and `no-cache`, compressed for a browser
  that takes gzip: a load fetches 260 KB instead of 932, and a reload gets 304 with no body for each file it holds, where
  every load fetched them whole before. A changed file still comes again at once, so the page and its scripts stay in
  step. It counts on a phone, and with the panel behind an Ingress.
- The container started with compose comes back when it crashes (it exits with an error, an out-of-memory kill
  included), three times at most, so a fault that repeats stops instead of looping; one you stop stays stopped.
  `docs/ARCHITECTURE.md` (Load and stops) sets out what keeps the panel whole under load, at a stop and after a crash.

## [0.7.0] - 2026-11-12

Several people on one cluster, each with an Offerowl of their own.

### Added

- The chart's `tenants`: list people and one release runs an Offerowl for each, named `<release>-offerowl-<name>`. Each
  person has their own pod, Service, claim (`<release>-offerowl-<name>-data`), NetworkPolicy (no other pod may connect,
  another person's neither) and `helm test` pod, and with the Ingress their own host name (`ingress.tenantHost`, `{name}`
  replaced by theirs) behind their own login (their own annotations). A person's panel answers their host name only.
  Offerowl keeps one person's documents and has no login, so several people are several Offerowls, never one panel shared.
- A person's own `ai`, `resources`, `persistence`, `language`, `timezone`, `extraEnv` (added to the release's), `ingress`
  and scheduling fields replace the release's values for them alone, so one person can have more memory, a larger claim or
  a model server of their own.
- The people's pods are spread over the nodes (softly), so a node that is lost takes the fewest panels with it, and a heavy
  build stays inside its own person's limits.
- Settings that cannot work side by side are refused before anything is made, each with what to change: a name that is
  not a DNS label or is listed twice, a field that is not a person's own, a claim or a host name given to two people,
  `persistence.existingClaim` for the whole release (everyone would share it), a person with no host name when the Ingress
  is on, a name too long for the objects' names, and a person's AI settings that cannot work (named with the person).

### Changed

- Without `tenants` the chart renders exactly what it did, so a release that is one person's upgrades with nothing
  changed. A release that turns to tenants keeps its claim for its person's `existingClaim`.
- The chart's cluster test installs two people and checks that what one adds the other never sees, that each claim is
  bound at its own size, and that `helm test` passes for both.

## [0.6.2] - 2026-11-12

What a look at the interview tab's own pages inside the panel, at what the tests leave open, and at every Python from 3.10
to 3.15 found after 0.6.1.

### Security

- Pillow now opens a picture only as the kinds its path takes in: a photo as a JPEG or a PNG, a picture read for its words
  as a PNG, JPEG, TIFF, BMP or WebP, a logo as a PNG, JPEG, WebP, GIF, BMP or ICO. A file whose inside is any other kind
  Pillow knows is refused before a decoder reads it. On Python 3.10 the newest Pillow is 12.3.0, which carries advisories
  fixed only in 13.0.0 (13.0.0 needs Python 3.11); most of them are in decoders a photo, a screenshot or a logo never needs,
  which no file reaches now.

### Fixed

- The presentation's script split a Korean word across two lines, on its page and in the PDF printed from it: a line now
  breaks between words.
- Inside the panel the interview kit's search view had a look switch and a Practice key of its own beside the panel's
  (the switch could turn the frame dark in a light panel): the panel's keys are the only ones. Its keys and its choice of
  language stand one height in their row.
- Inside the panel the interview deck drew a grey desk and a bar with a second print key, light in the dark theme: its
  pages stand on the panel's own desk, as the documents' pages do, and the panel's key prints it.
- The breath marks (" / ") in the interview deck and on the cue cards were too faint to rehearse by (2.2:1): they read as
  the search view's do (5.1:1 and 4.5:1).
- The interview tab's frames had a box drawn round them inside the job's card; the presentation's script now stands as a
  sheet, edged as the documents' sheets are. A screen reader named the script's frame "Search the scripts".
- Before a presentation was made, its frame said so in dark words on the dark theme's desk.
- The desktop app kept each server's output pipe open after the server ended until the process object was collected;
  it closes when the output ends.
- The tracker's calendar file stamped its time with a call Python deprecated in 3.12; the same UTC time comes from the call
  that replaces it. A test loaded the launcher with a method Python 3.15 removed.
- Installed with pip inside a container that is not one of Offerowl's own images (a dev container, a CI job's, a plain
  Python image), the engine took itself for the app image and called LibreOffice, which was not there: no document could
  be made even with a browser at hand, the panel said the typesetting was ready, and the doctor said to build the app
  image again. Only a container that carries LibreOffice, as both of Offerowl's images do, counts as one of them, in the
  engine, the panel, the doctor, the cover letters and the reading of scans alike; any other is taken for a PC, and its
  browser typesets.

### Changed

- Python 3.13, 3.14 and 3.15 are named beside 3.10 to 3.12: the quick checks run on each of the six, and `pip install` is
  tried on each system with the oldest and the newest.
- The walk measures the interview tab's search view and deck (two more states), and its audit runs inside the kit's
  pages that the panel shows in frames as well.
- The tests close what they open (a test server's socket, a started program's pipes, the desktop app's log) and reap
  what they start; a scroll test waits for every page of the resume before it scrolls.

## [0.6.1] - 2026-11-12

What a check of every view, its keys and its code found after 0.6.0.

### Fixed

- A web address with words right after it, as Korean writes them ("https://zoom.us/j/123입니다"): the link took the words in
  and broke. An address now ends where an address's characters end; a stop or an unmatched closing bracket after it is
  left out, and two addresses written together are two links.
- A long meeting link in a next step, a result or a reminder was cut at 200 characters; each now holds 1,000.
- The Fit tab asked for the part of a posting with its duties when the reading found none, with nowhere to paste it: it
  now takes it and reads the posting again (`POST /api/v1/jobs/posting`, one undo step).
- An education fact read from a profile whose fields are written per language showed `{'ko': …, 'en': …}`: such a field
  reads as its Korean, else its English, the facts stored from an earlier reading included.
- The panel did not load in Safari before 16.4 (a pattern with a lookbehind).
- In the dark theme a switch that was on looked off; in the light theme the keys' rims and the panes' hairlines did not
  show on the glass.
- On a tablet the open command bar left the top of the page bright and began below where the bar had been: it rises
  from the foot, the whole page dimmed, as on a phone. The photo's keys lay over Your details, and the notes in progress
  of one row stood 4 px apart.
- On a phone the dates in a table of the command bar's answer broke across lines: they stay whole, and a wide table
  slides inside the answer.
- A note shown while the panel's tab was hidden could leave parts of the bar hidden after it went; a note could lie over
  a run's chip; the bar drawn again moved a note's room away from under it; on Windows a note stood a scroll bar's width
  off its place.
- In the timeline a link sat inside the step's key; it stands beside it.
- Without Docker, a browser that did not finish reading the portfolio deck ended the build as an unexpected failure
  (seen on a slow macOS runner). The read keeps the whole page a browser wrote out before it was stopped, as the print
  keeps its PDF, waits as long as the print does, and starts the browser once more after a stop; a second stop, or a
  browser that cannot start, is the deck's failure in words. The browser's throwaway profile no longer asks the macOS
  keychain or a desktop keyring for a key, where a dialog nobody answers would hold it.
- The drafting and autopilot tests removed their temporary folder while a job's analysis could still be running, and
  the analysis wrote part of it again: they wait for the panel's tasks to end first.

### Changed

- A note that names a change made carries its own Undo, as a removal's does (on a phone its band covers the bar's).
- Stack facts have a colour of their own (they had the red that means missing), Insights' career tile colours the kinds
  as Make and Profile do, and Make splits the facts by the kind as the person set it, as Profile does.
- An application's stage and fit stand on its name's line; the Fit tab says its counts once; a line not met says that its
  sources fall short; the cover letter's key reads "Write it" while none is made; an ended application's result is on
  its name's line.
- On a phone a choice's chosen word has a short line under it; on a phone or a touch screen a note's key, the key to
  write a result, the switches and the wordmark take a finger (44 px).
- Documents' two choices have a rule between them, and the page's top meets the inspector's. Insights keeps one 12 px
  rhythm, its persona's tags end each but the last with a dot, and "more on the board" starts on its list's edge. A
  citation's number is square, the Library's row keys are bare marks, and a company stays with its role in "Whose".
- Make's documents count says how many editions its languages add up to.
- A file's preview keeps a link's address (`[words](address)`), which the panel shows as a link, and an underscore in an
  address is no longer read as emphasis.
- The walk's audit: text inside a box that scrolls is cut only by that box, and a note over the bar's own words counts as
  an overlap.

## [0.6.0] - 2026-11-12

Offerowl in one release: your files in, the whole application out, every sentence citing them.

### Security

- The panel answers this PC only, and another site's page cannot set it to work: a read it starts is refused for the API
  and the interview kits.
- A posting's link reaches the public internet only: the name is asked once, the connection goes to the address that was
  checked, a carrier's shared range and IPv4 written as IPv6 are refused, every redirect is checked the same way, and one
  time limit covers the whole fetch.
- The interview kit's pages run only the scripts they were built with, named by their hashes in the page's policy, and a
  kit stays inside the workspace.
- The command bar's agent fetches only links written in your own words, and is told that postings and files are
  material, never instructions.
- At most 64 requests at once; a client that stops sending is let go after 120 seconds; a part of a `.docx` or `.pptx`
  that would inflate past 64 MB is left out; a backup is read from a file, not held whole in memory.
- Offerowl does not open Claude Code's settings file (it can hold keys): the effort it shows comes from
  `CLAUDE_CODE_EFFORT_LEVEL` alone.
- Pillow 13.0.0 (Python 3.11 and later) or 12.3.0 (Python 3.10) in the desktop app and the `tray` and `pdf` extras.

### Added

- The panel, as a desktop app for Windows, macOS and Linux, a Python package, a container and a Helm chart: Make,
  Profile, Applications, Documents, Insights and Library, in English and Korean, light and dark.
- Files and folders as the only input: PDF, Word, PowerPoint, text, photos of pages, a zip, LinkedIn's export, a
  posting's link, a screenshot of an application form with its questions and limits.
- Facts that keep the words of their source: a fact is kept only when its quote is found in its file, and you keep, edit
  or drop each one.
- Documents written from those facts alone: a Korean and an English resume, a portfolio deck, a cover letter, the form's
  answers and interview scripts, each sentence checked against the facts it cites and opening its source's words on a
  click. General editions, an edition per posting, blind editions, Word files and slides beside the PDFs.
- Applications as a list, a board and a timeline, with each line of a posting rated against your evidence, its
  interview rounds and days, the kit that prepares for each round (cue cards, a deck, a talk) and the PDFs you sent kept
  byte for byte.
- The command bar (Ctrl+K): a request in your own words, carried out by the agent through Offerowl's own tools only.
- Claude Code, Codex or a local model as the agent, or none at all; the agent sees only what the step in progress needs.
- An HTTP API for everything the panel does, an MCP server for agents, and a CLI for scripts and tests.
- Backups of the workspace that restore without deleting, a Trash that puts things back, and Undo in the bar.
- The look: the owl's desk under its lamp in frosted glass, with no grid and no box inside another. A bar across the
  top holds the views as words, the one in use underlined; keys are flat; a choice of a few and every tab are words
  with the chosen one underlined; a note shows in the bar with a mark of its kind (done, held back, failed, or word
  of something); the command bar opens as a sheet beside the page, and on a phone or a tablet its key is a bar along
  the foot, so nothing floats over a card.
- Links: an address in a next step, a round's notes, a reminder or a file you added (a meeting's, a booking page's)
  opens in a new tab, named for its service (Google Meet, Zoom, Teams, Calendly) or its site.

[Unreleased]: https://github.com/kanggu12/offerowl/compare/v0.9.1...HEAD
[0.9.1]: https://github.com/kanggu12/offerowl/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/kanggu12/offerowl/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/kanggu12/offerowl/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/kanggu12/offerowl/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/kanggu12/offerowl/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/kanggu12/offerowl/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/kanggu12/offerowl/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/kanggu12/offerowl/releases/tag/v0.6.0
