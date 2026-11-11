# The documents

What Offerowl makes and how each document is put together: the parts of the resume and the deck, the editions you bring
in, the portfolio deck and its figures, cover letters, and the profile file every document is drawn from.

- [Resume and deck parts](#resume-and-deck-parts)
- [Editions you bring in](#editions-you-bring-in)
- [The portfolio deck](#the-portfolio-deck)
- [Cover letters](#cover-letters)
- [The profile format](#the-profile-format)

## Resume and deck parts

What the resume and the deck can draw, and which fields of the profile and the job each part reads. For the profile's
format, see [The profile format](#the-profile-format).

### The loader

One loader, `src/profile_loader.js`, reads the profile for the resume, the deck and the figures, so the three cannot disagree on
names, periods, tenure or logos. It reads two shapes of `resume-profile/0.1`:

- the fields described in [The profile format](#the-profile-format);
- the ledger form: `roles[].career` with `ko` and `en` halves, `education[]` and `service` with language halves,
  and `sections[].body_md` markdown.

Any text field may be a language pair `{ "ko": ..., "en": ... }`. A pair without the build language stops the build and names the
field. An explicit `null` in a pair means the field has no text in that language.

### Resume forms (`src/resume_form.js`, job setting `form`)

| Form | In the panel | Prints |
|:---|:---|:---|
| `detailed` | Detailed | the header, overview, career summary, education, competencies, skills, experience, other lists, about me, motivation |
| `compact` | One column | the name and one contact line, headline and intro, experience, skills, education and other lists, with no table, figure or logo |
| `table` | Tables | a personal table, then education, career, other lists, service and skills as tables, then experience, about me and motivation |

### Resume parts (`src/resume_form.js`)

| Part | Profile fields | Job fields |
|---|---|---|
| Header with info and location rows | `person.info`, `person.location`, `person.links`, `linkedin`, `scholar` | `photo` |
| Headline with a kept line break | `summary.headline` (a `\n` breaks the line) | |
| Overview timeline | roles, education, service; `education[].timeline: false` keeps an entry off; `summary.timeline.break` squeezes a study-only lead-in | |
| Overview cards, selected projects | `summary.cards`, `summary.highlights` | |
| Career summary with logos, place, department, role and tenure; total tenure in the title | `roles[].logo`, `place`, `dept`, `title`, `note`, `start`, `end` | `tenure: false`, `widths.career` |
| Education with logos and grey second lines | `education[].logo`, `school`, `sub`, `major`, `majorSub`, `degree`, `note` | `widths.education` |
| Hierarchy figure | `summary.layers` | |
| Core competencies with evidence projects | `competencies: [{ name, text, evidence: [project ids] }]` | `competencyWeak`, `competencyDrop` |
| Skills with JD layers | `skills` | `skillsFocus`, `skillsStrong`, `skillsHighlight`, `skillsEdit` |
| Company bands with logo, badge, tenure, department line and description | `roles[].badge`, `sub`, `desc`, `context` | `projectOrder` |
| Projects | `projects[].title`, `period`, `summary`; `resume: false` keeps a deck-only project out | |
| Other sections | `sections[]` with `items`, `lines` (`[main, org, date]`), `rows` and `head` with `align`, styled cells `{ t, bold, accent }`, `note`, `groups` of those, or a ledger `body_md` (tables and plain bullets only) | `sections` (titles to keep, in order) |
| About me with an optional quote box | `about: [[title, text], { quote, text }]` | |
| Motivation | `motivation` | `motivation` |

The Korean edition keeps a faint English label to the right of each section title; the English edition has none. The tables have
preset column widths per language, and `job.widths` overrides them.

### Figures and logo tiles (`src/overview_figures.py`)

- Timeline: labels inside a bar (bold name, regular note after two spaces, a
  sub line), above a short career bar, or beside it; shared boundary months stay on one row; an unfinished degree with `fadeTo`
  fades out; a study-only lead-in is squeezed behind a double wave. The axis runs from the first year to late in the last one,
  so the last year's tick and a label above the last bar fit; a label above a bar starts at the bar, or further left to stay inside
  the figure. An education entry with `timeline: false` stays in the table only. The deck gets a flatter variant (1184 px) and one
  chapter variant per role with that role dark.
- Hierarchy figure with ink-centred text.
- Logo tiles: an image is trimmed and placed on a white rounded tile with a light outline; a square image with transparent corners
  is taken as a finished tile; `{ "text": "AB", "color": "#2F6EBA" }` draws a monogram.

### Deck parts (`src/deck_slides.js`, `src/deck_structure.js`, `src/deck_figures.js`)

The default layout is a cover, a career overview, one slide per project with a figure, and an end. The job field
`"deck": "chapters"` turns on the chapter structure:

- cover with stat tiles (`summary.stats`), a career path strip (`roles[].journey: { phase, line, key }`) and focus columns
  (`summary.focus`); its headline may differ from the resume's (`summary.deckHeadline`);
- contents with chapter bars sized by slide count and every project with its tagline and page (`summary.contents` is the lede);
- career at a glance: flat timeline, hierarchy layers and two selected projects (`summary.glance`);
- a chapter divider per company: logo, number, name (`roles[].chapterName` for long names), role, period, location, clients
  (`roles[].clients`), lead (`roles[].lead`), the projects with pages, the core stack (`roles[].stack`) and the chapter timeline;
- project slides with a breadcrumb, a tagline, a client logo plate (`projects[].logo`), a role, context and stack line with scale
  chips (`projects[].role`, `context`, `stack`, `chips`), a lede (`lede`, else `summary`), and a body of figures and cards
  (`figure`, `figures`, `cards`); `deck: false` keeps a project off the deck;
- a side rail on every inner slide.

Figures come from a library of templates, listed in [The portfolio deck](#the-portfolio-deck). They are drawn with the deck's own drawing parts, so the deck
checks (overflow, overlap, arrows, small text, contrast) measure them. A second figure in the narrow right column is drawn on its
own smaller canvas.

### Tests of the parts

- `node tests/parts/loader_test.js`: the loader (tenure, periods, language pairs, ledger markdown, ledger-form profiles) and
  the figure templates' data checks and drawings.
- `python3 tests/parts/run.py`: builds the fictional full example in both languages with the chapter deck and a ledger-form
  fixture, then checks the document check, raw markup in the text layer, every part listed above, embedded images,
  deck structure, deck defects and cut figure text. `--no-build` checks existing outputs.
- The fictional examples are `examples/sample_full_ko.json`, `examples/sample_full_en.json` with `examples/job_full_ko.json` and
  `examples/job_full_en.json`; `tests/parts/fixtures/export_shape.json` is a fictional ledger-form profile.

## Editions you bring in

Offerowl also keeps the documents you made before you used it, so moving to it loses nothing.

- **Your own edition of a resume.** A resume you already wrote for one job, as a profile in the format below, is that job's own edition
  (`POST /api/v1/jobs/own`). Its words are its own facts, kept in the job's folder (`jobs/<job>/own/`) apart from your profile, and the job's
  PDFs print them as written, in the languages it came in. The person's name, email and phone stay your profile's. The layout choices it
  was made with come along per language (`form`: `plain`, `footerLabel`, `competencyFigure`, `photo`, `titleView`, `skillsFocus`,
  `skillsStrong`, `skillsHighlight`, `blind`), and the posting's own order does not reorder it.
- **Named general editions.** Editions with no posting, such as one for headhunters or one per target role
  (`POST /api/v1/editions`). They are kept like a job's, in a folder whose name starts with a dash, but never appear on the board.
  Documents lists them under General editions, beside the general edition made from your profile.
- **Your own file.** A resume or a cover letter as a PDF or a Word file, or a portfolio as a PDF, kept for one edition and language
  (`POST /api/v1/jobs/own-file`). Making the PDFs then uses it in place of the typeset document: a PDF as it is, a Word file through
  LibreOffice (the container's, or this PC's own with the browser renderer). It suits a form Offerowl does not typeset, such
  as a two-column resume or a full career record.
- **What you sent.** The files that went out with an application (`POST /api/v1/jobs/sent-file`) are kept as its submitted copies,
  byte for byte, the same way "Lock when submitted" keeps them, and the job counts as submitted.
- **Your own deck source.** A portfolio you wrote as code, slide by slide, lives in the workspace's `deck/` folder with its pictures,
  and every edition's deck is written from it, in Korean, in English and as a blind edition. Its entry is `deck/build.js`: Offerowl
  runs `node deck/build.js <profile.json> <job.json> <page name>` in the engine's folder, and the script writes
  `output/<page name>.html`, which is printed and measured like a deck Offerowl draws (an element `#probe-out` holds the
  measurement, as in `src/portfolio/deck.js`). The script reads the edition's language from `job.json` (`lang`) and the blind
  switches from the environment; `require(path.join(process.cwd(), "src", "blind"))` gives it the covering the resume uses, with
  your table. The folder is copied into the engine's folder for each build (so its scripts find the engine's libraries, in the
  container too) and taken away after. A job's own deck file still comes first. Changing a file of the source marks the editions
  whose decks it wrote stale; one made before there was a source stays as it was.

## The portfolio deck

The deck is a 16:9 portfolio built from the same profile as the resume. With the job setting `"deck": "chapters"`, which the panel sets once a
resume draft exists, it takes the chapter structure listed slide by slide, with the fields each slide reads, in
[Deck parts](#deck-parts-srcdeck_slidesjs-srcdeck_structurejs-srcdeck_figuresjs). A project may take several slides
([Spreads](#spreads)).

Two looks, with the same slides and sizes: the classic one with dark panels, and with `"deckStyle": "clean"` (**Light** in the panel) a light one
whose cover, chapter panels and last slide are paper. Any colour set recolours the figures too.

In the panel a project's slide comes from its drafted sentences: what the person was responsible for on top, what they did and what came of it
as cards. The cover's proof tiles, career path and focus columns and the lines over the contents and the career at a glance come from the same draft
([WRITING.md](WRITING.md)). **Draw the figures** then runs the figure drafting step on the projects the resume prints, and a figure whose arrows
cross is turned down before anyone sees it. Drawing again first takes out the figures the current checks turn down (`figure_draft.prune`), so
their places are asked for again.

A chapter is a company, or a chapter of another kind, such as research (see [Chapters that are not companies](#chapters-that-are-not-companies)).
The resume's layout, theme and drawing parts are shared (`src/portfolio/`).

### Figures on a project slide

A project's figures are `figure` plus `figures` (or, on a spread, each page's own). The deck places them like this:

| What the project has | Left column | Right column |
|---|---|---|
| figures and cards | the main figure, 760 x 570, in a 662 x 497 frame | a side figure, 470 wide, at the height the cards leave, then the cards |
| figures, no cards | what I did (`points`) | the figure, 700 x 488 |
| cards only | the cards in a grid | |

- **Packing.** A main figure shorter than about 60% of its frame shares the frame with the next figure, as two panels. A lone strip
  in a tall frame reads as empty.
- **The side figure.** The second figure goes to the right column when it is a side type (`pipeline`, `bars`, `metric`,
  `columns`, `trend`, `phases`, `cluster`) and draws there without losing any text. Otherwise it joins the main figure as a panel.
- **Three or four figures** become one main composite (`1+2` or `2x2`).
- **Simple types.** The template types `flow`, `compare` and `layers` are the simple ones. `compare` and `flow` join a composite as
  `metric` and `pipeline`. A `layers` figure that cannot be placed is reported, never dropped without a word.
- **Card numbers.** A card may carry a number, `[head, text, 1]` or `{ head, text, mark: 1 }`. A panel, a zone, a node or a
  before/after side with the same `mark` shows the same badge, so a reader can match a card to the part of the figure it explains.

### The figure library (`src/deck_figures.js`)

Every template draws from data with the deck's own drawing parts (`src/portfolio/draw.js`): measured text, boxes, and arrows
whose heads snap to the box they point at. Because of that, the browser probe measures them like hand-drawn
figures: overflow, overlap, arrows, small text and contrast. All templates draw into one coordinate system. That is what lets
`panels` hold several of them in one frame.

| Type | Use | Data |
|---|---|---|
| `panels` | The main figure of a slide: two to four figures, each on a white panel with a title, a badge and a closing note. Layouts `1+2`, `2+1`, `2`, `2v`, `3v`, `2x2`, `3` | `{ layout, panels: [{ title, mark, note, figure }] }` |
| `architecture` | Zones of nodes, left to right, with labelled links. Nodes may hold a grid of squares (GPUs, members) | `{ zones: [{ title, kind, nodes: [{ id, title, sub, kind, units, unitKinds, mark }] }], links: [[from, to, label, kind]] }` |
| `rack` | Racks of units under a switch fabric, the servers drawn as squares | `{ fabric: { label, items }, racks: [{ name, sub, units: [[label, kind, count]] }] }` |
| `timeline` | Phases in lanes and milestones on a date axis | `{ phases: [[name, start, end, note, kind]], milestones: [[label, date, kind]], tracks }` |
| `gantt` | Workstreams of tasks on a month axis, with milestones and today | `{ groups: [{ name, tasks: [[name, start, end, kind]] }], milestones, today }` |
| `metric` | Before and after values under stated conditions | `{ unit, beforeLabel, afterLabel, rows: [[name, before, after, condition]], conditions, delta }` |
| `columns` | Grouped vertical bars on a value axis | `{ unit, series, groups: [[label, v1, v2]], highlight }` |
| `trend` | Lines over ordered points, labelled at their ends | `{ unit, x, series: [[name, values, kind]] }` |
| `tree` | A root, its children, their items | `{ root: [title, sub], children: [[title, sub, kind, [[title, sub, kind]]]] }` |
| `matrix` | Rows against columns with marks or short text, column bands, a chosen column | `{ cols, rows: [[name, ...cells]], groups, highlight }` |
| `beforeAfter` | The old structure next to the new one, sides that may chain their items | `{ before: { title, items, flow, note }, after: {...}, change }` |
| `pipeline` | Steps in a row, a second row running back | `{ steps: [[title, sub, kind]], groups: [[label, from, to]] }` |
| `bars` | One value per row, with an axis | `{ unit, rows: [[label, value, kind]], highlight, note }` |
| `phases` | A few named periods on months | `{ rows: [[name, start, end, note]] }` |
| `cluster` | Counts of nodes per role as squares | `{ unit, groups: [[name, count, note, kind]] }` |

`CATALOG` in the same file says the same in one line per type. The drafting step puts it in its prompt.

**Kinds and legends.** Colour carries a meaning only with a word for it. A figure that uses a kind draws a legend of the kinds
it used, and a default look draws none. Rename a word with `legend: { mine: "Rebuilt by me" }`.

| Kind | Look | Korean | English |
|---|---|---|---|
| `mine` | blue outline | 맡은 부분 | My part |
| `key` | dark fill | 핵심 | Core |
| `old` | grey, dashed | 이전 | Before |
| `ext` | teal | 외부, 고객 | External |
| `data` | amber | 데이터, 저장 | Data |
| `plan` | dashed outline | 제안, 계획 | Proposed |
| `stop` | red | 막힘, 실패 | Stopped |
| `hl` | highlighter yellow | 근거 | Evidence |

**Schemes.** There are two schemes, `light` and `dark`, and both pass the deck's contrast check.
- `light` is the deck's own: the frame's paper shows behind the drawing.
- `dark` paints its own page and uses its own arrowheads, for pictures on dark pages (CONTRIBUTING.md asks for two copies of
  every picture). In code: `render(fig, W, H, cut, { lang, scheme })`.

**Heights.** A figure ends under its content (the SVG is trimmed), and a frame centers it. Inside `panels`, each row gets the
height its figures need. The search finds the least height at which no more is cut than at full height (a note that holds at any
height, such as a link crossing, does not count against a height), and the spare height is shared in proportion.

**Layout rules that keep text whole.**
- *pipeline*: up to five steps a row, then the steps snake back on a second row. A short frame, such as the side column, keeps up
  to six steps on one row of narrower boxes when every title word still fits. A band may start on any row.
- *architecture*: a node that several links reach on one side grows until each arrow has its own point, 10 px apart.
- *phases*: a note sits inside its bar, else on the side of the bar with more room.

**Nothing is lost quietly.** Text that does not fit its box is shortened with an ellipsis, and the cut is listed; a room too
narrow for one letter and the ellipsis shows nothing, and that is listed too. A figure taller than its frame is listed, and so are
a link label with no room, a link to an unknown node, a link crossing that no lane order removes, and a band that would sit across
the snake's turn. The document check counts every
note as a defect. `audit(svg)` is a static check of a drawing, with no browser: text outside the canvas, text over text, text
across a box edge, and text wider than its box. From the command line: `node src/deck_figures.js --audit fig.json [W H ko|en light|dark]`.

### Spreads

A project with `pages: [{ lede, figure, figures, cards }, ...]` takes one slide per page:
- each slide's title ends in `(1/2)`, `(2/2)`;
- the breadcrumb keeps one project number;
- the contents and the chapter list show the range, `9-10` (Korean `9~10`);
- the rail counts every page.

### Chapters that are not companies

A top-level `chapters` list adds chapters after the company chapters (research done during a degree, open source):

```json
"chapters": [{
  "key": "research", "kind": "research",
  "name": { "ko": "연구", "en": "Research" }, "enName": "Research",
  "title": { "ko": "연구원", "en": "Research assistant" }, "start": "2016.03", "end": "2018.12", "place": "Seoul",
  "funder": "Example Research Foundation", "timeline": "ganada", "logo": { "text": "R", "color": "#2F6EBA" },
  "lead": "...", "stack": [["Networks", ["MAC", "NS-2"]]],
  "projects": [{ "title": "...", "tagline": "...", "lede": "...", "figure": {}, "figures": [], "cards": [] }]
}]
```

- **Divider.** The divider shows the funder where a company divider shows its clients, labelled 연구 지원 or Funder (`kind:
  "opensource"` says 저장소 or Repository; `metaLabel` sets any word).
- **Timeline.** `timeline` names the education entry (or role) the chapter belongs to. `src/overview_figures.py` draws the
  chapter's timeline with that bar dark.
- **Logo.** `logo` is an image next to the profile or a monogram, drawn as a tile like the company logos.
- **Rail and contents.** The chapter takes a tab on the rail and a group in the contents.

The shared loader (`src/profile_loader.js`) does not carry `chapters`, so the deck and the figures read them from the profile
file with the loader's language rule (`pickDeep`).

### Drafting figures (`src/figure_draft.py`)

The drafting step proposes figure data for each deck project from its evidence. Nothing reaches the profile until a person
accepts it. `draft.py figures`, the older proposer that `offerowl draft figures` still runs, offers only one of three
simple types.

```bash
python3 src/figure_draft.py propose profile.json --max-calls 8      # writes profile.figures.json, every proposal with its checks
python3 src/figure_draft.py repair profile.figures.json profile.json # one more call for the flagged proposals, checked again
python3 src/figure_draft.py review profile.figures.json             # the list: proposal, slot, type, status, what was fitted, reasons
python3 src/figure_draft.py review profile.figures.json --accept all --reject 'p1#0.side'
python3 src/figure_draft.py apply profile.figures.json profile.json # writes profile.figs.json (never over the input)
```

- **Evidence.** A project's evidence is its own text, the text of the entries it names in `evidence: [ids]` (for example the
  ledger notes behind a deck project), and its chapter's facts. Both languages count. A short period such as `24.02` also counts
  as `2024.02`.
- **Calls.** The projects of one chapter share a call, up to three or four a call. `--max-calls` caps the calls, and a wrong
  answer is asked again only while the cap allows. The answer gives, per page, a main figure (usually `panels` with the card
  numbers) and a side figure. Every shown text is a `{ko, en}` pair when the profile has two languages.
- **The prompt.** Besides the catalog and the evidence, it gives each page's card heads and its side room, says which view suits
  which work (zones of a system, racks of a cluster, a hierarchy, options against criteria, a schedule, a change, measured numbers,
  and a pipeline only for a real sequence of steps), and what a panel of half the main frame holds.
- **Checks.** Every proposal is checked before anyone reviews it, and checked again on `apply` against the profile it is
  written into:
  - *shape*: the library's data check, and a side figure must be a side type;
  - *drawing*: the figure is drawn at its slot's size in every language, then the audit and the cut list are read;
  - *facts*: every value, count, date and number in a label, every Latin name in Korean text, every proper name in English text,
    and every Korean company name must be in that project's evidence (`src/factcheck.py`);
  - *style*: the style pack's banned characters and patterns.

  A proposal that fails any check cannot be accepted.
- **Side room.** A side figure is drawn at the room its page's cards leave, as the deck computes it
  (`node src/deck_slides.js --rooms profile.json ko`), with a number badge on every card, since `apply` numbers the cards that
  figure parts show and a badge narrows a card's head. A page whose cards fill the column gets no side figure.
- **Fit.** A proposal that fails only on layout gets lighter forms tried in turn. Notes are box subs, step notes, side notes,
  panel notes and link labels:
  - the notes of one panel, then of two, and so on, later panels first;
  - every note;
  - then panels from the end, with their notes and then without;
  - last, the first panel alone, with its notes and then without.

  The first form that passes every check stands in for the proposal. `fitted` says what was dropped, and `proposed` keeps the
  model's version. A lighter form never says more than the proposal.
- **Repair.** `repair` sends each flagged proposal back with its findings, its size and its evidence, in one call. The answers
  go through the same checks.
- **Card numbers.** On `apply`, a card whose number a figure part shows gets that number, so the badges pair up.
- **Tests.** The tests use a stand-in, `propose(..., ask=fn)`, or `--stand-in answers.json` on the command line.

### Tests of the deck

```bash
python3 tests/deck/run.py            # unit tests, then the gallery and the full fixture decks in the render container (heavy)
python3 tests/deck/run.py --no-build # the checks of decks already built
python3 tests/deck/run.py --unit     # node and python only
```

- **`tests/deck/figures_test.js`.** Every template is drawn in both languages and both schemes, at the main, wide and side sizes.
  The test checks:
  - the canvas and the label;
  - no NaN and no `undefined`;
  - a clean audit and nothing cut;
  - the dark page and its arrowheads, and the legends;
  - natural heights, and the badges in panels;
  - long text shortened and reported, and never wider than its room;
  - separate end points for links into one node, and a node that grows for them;
  - a band on the snake's second row, one row of steps in a short frame, a phase note before a late bar;
  - every data check, and the catalog.
- **`tests/deck/test_figure_draft.py`.** The drafting step with a stand-in model:
  - an invented value, an invented date, a name not in the evidence, an unknown type, a wide side figure and overlong text are
    each flagged;
  - flagged proposals cannot be accepted;
  - a crowded proposal stands in lighter, and the model's version is kept; notes go in growing sets of panels, link labels
    count as notes;
  - the prompt gives each page's side room;
  - repair sends the findings, and a repaired figure passes the same checks;
  - apply writes a new file, checks again and numbers the cards;
  - the call budget and batching hold, and the command line works end to end.
- **`tests/deck/run.py`.** It builds the figure gallery (`tests/deck/gallery.js`: every template, light and dark, main and side
  size, 30 slides per language). It also builds the full fixture: the fictional `examples/sample_full_<lang>.json` with a research
  chapter, a spread and second figures, 16 slides. Then it checks:
  - 0 probe defects and nothing cut;
  - the spread's marks and page range;
  - the research divider and its timeline;
  - at least six project slides with two figures or a composite;
  - card numbers, and no raw markup.


### What still falls short

- The library covers the common shapes (structure, flow, layout, time, numbers), not every picture a project needs. A map, a
  protocol timing diagram, a screenshot or a console view is still a job for a person.
- A template lays out what it is given; it does not choose the most telling view. That choice comes from the drafting step and
  the person reviewing it.
- `audit()` approximates the browser's measures. The browser probe in the deck build is the final word.
- **Density.** The fit step trades density for a clean drawing. It drops notes and panels rather than shrinking text below the
  deck's 10 px floor, and the drafting step chooses pipelines and before-and-after far more often than cluster grids, zoned
  architectures and measured charts.
- **Short figures.** A short main figure with nothing to pack beside it is centred in a tall frame, with paper above and
  below it.
- **Figures that find no place.** A figure that fits neither the side column nor the main composite is listed in
  `<out>_deck.left.json` and printed. It is not drawn, and the cut list (which the document check reads) stays clean. The review
  step's side-room check keeps this rare.

## Cover letters

A cover letter answers the lines of one job posting, in the posting's order, with facts from your profile. Four rules
hold for every letter, and `check` tests each of them:

- Every sentence points to the evidence it rests on, and the fact check drops any sentence with a number, a name or a
  tool that this evidence does not hold.
- The letter repeats no sentence of the resume built for the same job.
- It has no numbers unless the style pack allows them.
- It fits one page.

It shares the header and the prose paragraph of the resume (`src/layout.js`), so a letter and a resume of one
application read as one set.

### Try it

The example is a fictional person (`examples/sample_ko.json`) and two fictional postings, one Korean and one English.

```bash
# 1. the plan from the posting: its lines matched to evidence. --backend none uses word matching only
python3 src/cover.py plan examples/sample_ko.json examples/cover/posting_en.md --backend none -o output/cover_plan.json

# 2. the letter from the plan: needs a model. The shipped, reviewed plan and letter sit beside the postings
python3 src/cover.py draft examples/sample_ko.json examples/cover/plan_en.json -o output/cover.json --style examples/cover/style.json

# 3. the letter as DOCX and PDF (with the renderer in use, like the resume)
python3 src/cover.py build examples/sample_ko.json examples/cover/cover_en.json --job examples/cover/job_en.json --dest output/example

# 4. every check, with the PDF
python3 src/cover.py check examples/sample_ko.json examples/cover/cover_en.json --pdf output/example/cover_en.pdf --style examples/cover/style.json
```

Without `-o`, the files of a posting that sits in `jobs/<job>/` go to `jobs/<job>/cover/` (`plan.json`, `cover.json`,
`cover.docx`, `cover.pdf`), and those of any other posting go beside it.
`python3 src/cover.py run <profile> <posting> --dir <folder>` runs the four steps in a row. The last line of `check` is
the verdict, for example `cover check: PASS (10 passed, 0 not run)`. Messages follow `OFFEROWL_LANG` (`ko` or `en`).

### The four steps

#### plan

`plan <profile> <posting> [-o plan.json] [--lang ko|en] [--company X] [--role Y] [--allow NAME] [--no-motivation]`

`--company` and `--role` are needed only to correct the posting: left out, both are read from it.

1. **Reads the posting.** Sections are found by their headings (responsibilities, qualifications, preferred; the Korean
   equivalents too). Every item becomes a line with an id (`d1`.. duties, `q1`.. requirements, `p1`.. preferred) and an
   `order` that follows the posting. A posting the parser cannot read is handed to the model, and each line it returns
   must occur in the posting text.
2. **Matches each line to evidence** with one model call. The model sees the lines and an index of the profile (one row per
   project: where, when, title, opening words, key words) and answers per line: up to three entries, a strength
   (`strong`, `weak`, `none`), the tools the line names that the entries do not show, and a one-sentence basis. Every
   id is checked against the profile; a `strong` line with no existing entry becomes `none`; a tool named by the line and
   absent from the chosen entries takes the line down to `weak`, unless another entry names that tool, in which case that
   entry is added. Without a model, word matching (BM25 with a small English and Korean bridge) does the same job and the
   plan says so (`matched_by: "words"`).
3. **Marks the gaps.** A line rated `none` is not answered. A tool that the posting asks for and no entry of the profile
   names goes into `gap_terms`, and the letter may not claim it.
4. **Plans the paragraphs.** The model proposes groups of neighbouring lines (three to five paragraphs, about ten lines).
   The plan accepts them only if they are sound (known lines, no repeats, the posting's order kept) and otherwise groups
   neighbouring lines itself. When more than `max_lines` (12) lines are left, the strongest duties stay.

#### draft

`draft <profile> <plan.json> [-o cover.json] [--style pack] [--resume file] [--repairs 1] [--backend name] [--raw answers.json]`

The letter is an opening, an optional paragraph on why this team (it may use only what the posting says about the
company), one paragraph per planned group, and a closing. One model call writes all paragraphs as sentences with
evidence ids; every sentence goes through the fact check (below). If sentences were dropped, repeat the resume, or leave
a planned line unanswered, one more call rewrites only those paragraphs. Then the letter is cut to its budget. The prompt gives every
paragraph its own share of `max_words` (`max_chars` in Korean); while the letter is still over the whole budget, the
paragraph that is furthest over its share gives up the sentence that speaks least to its posting lines, as long as no planned
line loses its only answer and no paragraph is left empty. What still fails after that is listed in `unresolved`, and `check`
fails on it; a plan made from evidence that has since changed is listed there too (`stale`). `--raw` keeps what the
model wrote, before any check, for audit. The salutation and the closing line are not written by the model; the renderer
supplies them in the letter's language.

Without a model, `draft` writes an empty skeleton (`why_empty` tells why), lists the evidence of every paragraph under
`todo`, and exits with 2. Fill the sentences in by hand; `check` accepts hand-written letters.

#### build

`build <profile> <cover.json> [--job job.json] [--dest folder]`

Renders `output/<out>.docx` and `.pdf` with the renderer in use (the render container through `render/run.sh`, or the PC's
browser), using `src/cover_form.js` and the same
LibreOffice step as the resume. The renderer tries three spacing levels and stops at the first that fits one page;
if even the tightest does not, `build` says by how much to shorten the letter. Files outside the repository are copied to
`output/_inputs/` first, as `resume.py` does.

#### check

`check <profile> <cover.json> [--plan plan.json] [--pdf cover.pdf] [--resume file] [--style pack] [--json out.json]`

| Check | Passes when |
|---|---|
| evidence ids | every sentence cites existing ids; only framing sentences go without, and only in the opening, the motivation and the closing; the evidence the plan was made from is unchanged |
| fact check | no sentence has a number, a name, a tool or an organisation that its cited evidence lacks |
| no resume sentence repeated | no sentence copies the resume (below) |
| duties covered in order | every planned line is answered, in the posting's order, and no line rated `none` is answered |
| claim strength | no sentence gives the person a larger part than its cited evidence does ([Claim strength](WRITING.md#claim-strength)) |
| no claim beyond the profile | no tool of `gap_terms` appears in the letter |
| style pack | no banned character, pattern or word; no run-on sentence |
| length | within the word (English) or character (Korean) budget |
| one page | the PDF has one page (needs `--pdf`) |
| layout | the body clears the footer, no number is split from its unit (needs `--pdf`); lone words at paragraph ends are listed as polish |

A check that could not run is printed as `skip` and counted as "not run", never as passed.

### What the fact check looks at

For one sentence, against the text of the evidence it cites (a block id `alpha-1#3` cites that block, a project id
`alpha-1` cites the whole project; the words naming the company and the role come with every block):

- **Numbers.** With `numbers: forbid` (the default) any number is dropped: digits, `40%`, and counted amounts
  (`three`, `dozens`, `두 개`). With `numbers: evidence` a number must be one that the evidence states.
- **Names and tools, English letters.** A capitalised word inside a sentence, an upper-case word and a mixed-case word
  (`Kafka`, `AWS`, `gRPC`) must occur in the cited evidence, and so must any tool name of the profile (a single-word item of a skills row, or an
  unmistakable name such as `AWS` or `PostgreSQL`) wherever it stands, in lowercase or at the start of a sentence. Ordinary
  lowercase words need nothing. A tool written in Korean in the
  evidence counts for its English name (`리눅스` for `Linux`). The company, the role and the place from the posting are
  allowed.
- **Names and tools, Korean letters.** Every Latin word and every organisation name (`...은행`, `...페이`, `...랩스`)
  must occur in the cited evidence, or be the posting's company.
- **Names spelled in another language.** When the evidence says `알파페이` and the letter says `Alpha Pay`, the sentence
  declares it: `"names": {"Alpha Pay": "알파페이"}`. The declaration holds only if the source text occurs in the cited
  evidence.
- **Gap terms.** A tool listed in the plan's `gap_terms` is dropped wherever it appears.
- **Framing sentences.** A sentence with `"frame": true` cites nothing, may stand only in the opening, the motivation or
  the closing, and passes the same name and number rules with the posting's company and role as the only names.
- **Style pack.** Banned characters, patterns and words, and a length limit per sentence.

The repeat check measures the longest run of words (characters in Korean) that a sentence shares with the resume. A
sentence repeats the resume when the run reaches `repeat_run` (14 words), or when a run of at least `repeat_min`
(6 words) makes up `repeat_share` (60 percent) of the sentence. Reusing a phrase is normal; copying a sentence is not.
The resume is the PDF or text file given with `--resume`; without one, the text that the profile's resume prints
(summaries, competencies, introduction) stands in.

### Files

#### plan.json (`offerowl-cover-plan/0.1`)

| Key | Meaning |
|---|---|
| `lang` | letter language, `ko` or `en` (the posting's language unless given) |
| `posting` | `company`, `role`, `location`, `overview` (what the posting says about the company and the team), `sha` |
| `lines[]` | `id`, `order`, `kind` (`duty`, `requirement`, `preferred`), `section`, `text`, `strength` (`strong`, `weak`, `none`), `ev` (project, block or loose ids), `missing` (tools the line names that `ev` does not show), `basis`, `source` (`model`, `words`, `reviewed`), `use` (answered by a paragraph), `skipped` (why not) |
| `groups[]` | `id`, `lines`, `theme`: the body paragraphs, in the posting's order |
| `fit` | entries that represent the person for the whole posting; they feed the opening and the motivation |
| `gap_terms` | tools the posting asks for and the profile never names |
| `allow` | extra names the letter may use besides the company and the role |
| `motivation` | whether the letter has the "why this team" paragraph |
| `matched_by`, `notes`, `evidence_hash`, `style` | how it was made, what to know, a fingerprint of the evidence used, the style pack |

A plan is meant to be read and edited: change a strength, add an id to `ev`, move a line between groups or set
`use` by hand, then draft again. The lines use the vocabulary of the posting audit in the interview kit (strong, weak or
none), so one posting analysis can serve both.

#### cover.json (`offerowl-cover/0.1`)

| Key | Meaning |
|---|---|
| `lang`, `job` | language; `company`, `role`, and an optional `tagline` for the header |
| `signature`, `salutation`, `closing` | optional overrides; the renderer supplies the salutation and the closing in the letter's language |
| `paragraphs[]` | `id`, `kind` (`opening`, `motivation`, `duties`, `closing`), `duties` (line ids), `sentences[]` |
| `paragraphs[].sentences[]` | `text`, `ev` (evidence ids), `duties` (line ids answered), `frame`, `names` |
| `dropped[]` | sentences the fact check rejected, with the reasons |
| `unresolved[]` | what is still wrong after the repair round |
| `plan`, `stats`, `style` | the plan it answers, word and call counts, the style pack name |

Evidence ids: `alpha-1` is a project, `alpha-1#3` its third block (a bullet, a paragraph or a table row), `alpha#c1.2` a
block of the role's context section, `role:alpha` the role's header, and `summary#intro`, `summary#c1` (a card),
`summary#l3` (a row of the hierarchy figure), `competencies#2`, `about#1`, `skills#Platform`, `sections#1`, `education#1`
the loose parts of the profile.

#### job.json (render settings)

`out` (file name in `output/`), `lang`, `theme` (a colour set of `src/themes.json`), `tagline`, `person` (fields that replace
`profile.person` for this letter: `name`, `name_en`, `email`, `phone`, `links`, `location`, `tagline`), `photo` (as the
resume takes it), `density` (`0`, `1` or `2`; the build step raises it on its own).

#### Style pack

The same JSON as the resume's style pack (`src/style/<name>.json`, `<workspace>/style/<name>.json`, or a path), with
`banned_chars` and `banned_patterns` as there, and an optional `cover` object:

| Key | Default | Meaning |
|---|---|---|
| `numbers` | `forbid` | `forbid`, or `evidence` (a number must also stand in the cited evidence) |
| `banned_words` | none | words and phrases the letter may not use |
| `tone` | plain, first person | one line per language that the prompt carries |
| `max_words`, `max_chars` | 560 English words, 1900 Korean characters | length budget of the body |
| `sentence_words`, `sentence_chars` | 55, 140 | longest sentence |
| `repeat_run`, `repeat_min`, `repeat_share` | 14, 6, 0.6 (English); 40, 14 (Korean) | when a sentence counts as a copy of the resume |

`examples/cover/style.json` shows the file.

### What it cannot check

- Whether a sentence means what its evidence means. The fact check compares numbers, names and tools; a person reads the
  rest. The panel is meant to show each sentence with its evidence for that.
- Whether an English spelling is the right translation of a name. It checks that the source text exists in the cited
  evidence, not that the translation is good.
- Anything about the company beyond the posting. There is no research step; the motivation paragraph may only restate
  what the posting says.
- Framing sentences make no claim that the checker can see, so the check keeps them to the opening, the motivation and
  the closing (`frame_where`), and the prompt keeps the opening and the closing to one or two sentences.

### For the app

The command line is a thin layer over functions that a panel or an API can call: `cover.plan(profile, posting_text, ...)`,
`cover.draft(profile, plan, ...)`, `cover.build(profile_path, cover_path, job_path)` and
`cover.check_cover(profile, cover, ...)`, which returns `{ok, checks: [{key, status, detail, items}]}` with a stable `code` on
every item. The files above are the whole state, so each step can be repeated alone and a hand edit survives until the
next `draft`.

### Tests of the letter

```bash
python3 -m unittest discover -s tests/cover                         # no model, no container
OFFEROWL_RENDER_TESTS=1 python3 -m unittest discover -s tests/cover  # also renders both example letters (Docker)
```

The model tests replace `llm.run` with a stand-in that answers from a table, so the plan, the draft, the repair round and
the skeleton path run without a model.

## The profile format

The shape of the one file that holds a person's facts. The panel builds it from the facts you keep and keeps it in the data
folder ([Your workspace](ARCHITECTURE.md#your-workspace)); `offerowl init` copies an example to start one by hand.

A profile comes in two forms, and the loader (`src/profile_loader.js`) reads both.

- **Plain fields**, below: what a person or the panel writes. A resume can be built from these alone.
- **The ledger form**, in this table: a long record of every role and project with its evidence text, as a script of your own might
  export it from your notes. It holds facts rather than sentences, so `draft write` turns it into resume text ([WRITING.md](WRITING.md)).

| Key | Shape | Meaning |
|---|---|---|
| `schema` | string | `resume-profile/0.1` |
| `person` | object | `name` and `email` are required. `birth`, `phone`, `linkedin`, `scholar` are optional |
| `summary` | object | `intro`, `highlights`, `layers` (the summary paragraph, the representative cards, the layers of the overview figure) |
| `roles[]` | list | One company. `key`, `heading`, `period`, `career` (the period and the Korean and English names; null for a short career), `context[]` (context sections such as a business overview), `projects[]` |
| `roles[].projects[]` | list | One project. `id` (company key plus a number), `title`, `period`, `body_md` (the evidence text), `source` (the source file and line) |
| `education[]`, `service[]` | list | Education and military service (the period and the Korean and English names) |
| `skills[]` | list | `category`, `items[]`. The `skillsFocus` of an application edition uses these category names |
| `sections[]` | list | The remaining sections: papers, patents, awards, certificates, training, press, outside activities (`title`, `body_md`, `source`) |
| `confirmed[]` | list | Notes of facts the person confirmed (`title`, `body_md`): the interview kit's evidence reads them, and so does the check of a form answer you write |

Every body field carries a `source`. A claim that the LLM makes during extraction cannot get in without a `source` as its evidence either.

### Profile fields

These are the fields that `src/resume_form.js` (the resume) and `src/deck_slides.js` (the portfolio deck) read. The example is `examples/sample_ko.json` (a fictional person).

| Key | Shape |
|---|---|
| `person` | `name` and `email` are required. `name_en`, `phone`, `tagline`, `links[]` ([name, visible text, address]) |
| `summary` | `headline` (one line), `intro.{ko,en}` (paragraph) |
| `roles[]` | `org`, `title`, `dept`, `place`, `start`, `end` (null while still employed, an empty string or no field when unknown), `projects[]` |
| `roles[].projects[]` | `id`, `title`, `period`, `summary` (one or two sentences; `==phrase==` is the yellow highlight). For the portfolio: `points[]` (bullets on the left of the slide), `figure` (`{type:"flow", steps:[[title, description]]}`, `{type:"compare", unit, beforeLabel, afterLabel, rows:[[metric, before, after]]}`, `{type:"layers", rows:[[layer, content]]}`, each with an optional `caption`). A project with a figure takes one slide in the deck |
| `education[]` | `school`, `major`, `degree`, `start`, `end` (null while still enrolled, an empty string or no field when unknown) |
| `skills[]` | `category`, `items[]` |
| `sections[]` | `title`, `title_en`, `items[]` (lists such as certificates and awards) |
| `service` | (optional) `{label, start, end}`, one period such as military service. The third line of the overview timeline |
| `summary.cards` | (optional) `[[title, text], ...]`, an even number. The two-column cards of the overview (for example target roles, main fields, strengths, industry domains) |
| `summary.highlights` | (optional) `[{title, where, rows: [[row name, text], ...]}, ...]`, up to four. The representative project cards (problem, what was done, result). The portfolio cover card uses them too |
| `summary.layers` | (optional) `[[layer, technology, place], ...]`. The hierarchy figure of the core competencies |
| `competencies` | (optional) `[[head, text], ...]`. The core competency bullets. A name listed in `competencyWeak` of the settings goes to the back and one in `competencyDrop` is left out (an unknown name stops the build) |
| `about` | (optional) `[[title, paragraph or list of paragraphs], ...]`. The self-introduction band |
| `motivation` | (optional) The motivation paragraph (the `motivation` of the settings comes first) |

The English edition is built from the `<name>.en.json` that `python3 src/resume.py draft translate` makes, with the setting `lang: "en"` (the English name comes first).
The overview figures (timeline, hierarchy) are drawn by `src/overview_figures.py` before the build, at a fixed size, in the deck's font and colours.

Settings (job.json): `out`, `lang` (ko, en), `theme` (the name of a colour set), `form` (`detailed`, `compact` or `table`), `deckStyle` (`classic` or `clean`), `deck` (`"chapters"`: [Deck parts](#deck-parts-srcdeck_slidesjs-srcdeck_structurejs-srcdeck_figuresjs)), `skillsFocus` (the list of skill categories to put in the front layer), `skillsStrong` and `skillsHighlight` (skill names set in bold, and the few of them marked), `skillsEdit` (`{order, text, only}`: the skills table's rows reordered, rewritten or kept for this job), `competencyWeak`, `competencyDrop`, `projectOrder` (the order of project ids), `tenure`, `sections` and `widths` ([Resume parts](#resume-parts-srcresume_formjs)), `motivation`, `photo` (`{file, layout, w}`), `plain` (true: section titles with a rule only, no accent bar, no English section name, no rail or outer card border), `footerLabel` (the older footer: the name, then this word for the document kind), `competencyFigure` (false leaves the hierarchy figure out), `titleView` (`full` puts a role's long label on the timeline), `style` (the style pack `src/style/<name>.json`, default `default`), `maxPages` (the page limit of the resume, default 3). `python3 src/resume.py draft jd` proposes `skillsFocus`, `competencyWeak` and `projectOrder` from a job posting.
A profile in the ledger form holds evidence text (`body_md`) instead of sentences. The loader reads it too (see [Resume and deck parts](#resume-and-deck-parts)), but without the drafting step (`python3 src/draft.py write`, see [WRITING.md](WRITING.md)) the resume lists the ledger's project titles only.

Year and month are read as `2022.03`, `2022-03`, `2022/3`, `2022년 3월` or `2022`. An entry that cannot be read for a figure is left out of it and reported (the build continues).

Which AI backend runs: [The AI backend](USAGE.md#the-ai-backend). What it writes and the checks each text passes:
[The way of a sentence](ARCHITECTURE.md#the-way-of-a-sentence).
