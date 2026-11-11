# Changelog

What changed in each release of Offerowl. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/). Each release's section here is its release notes. Security
fixes come first in a release.

## [Unreleased]

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

[Unreleased]: https://github.com/kanggu12/offerowl/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/kanggu12/offerowl/releases/tag/v0.6.0
