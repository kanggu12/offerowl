# Changelog

What changed in each release of Offerowl. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/). Each release's section here is its release notes. Security
fixes come first in a release.

## [Unreleased]

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

[Unreleased]: https://github.com/kanggu12/offerowl/compare/v0.6.2...HEAD
[0.6.2]: https://github.com/kanggu12/offerowl/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/kanggu12/offerowl/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/kanggu12/offerowl/releases/tag/v0.6.0
