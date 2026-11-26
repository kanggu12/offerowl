"""The documents service: the resume, the portfolio deck and the cover letter of every edition (a job's, the general one's,
a named one's). The canvas draws them with each sentence's evidence; the agent drafts their words; the typesetting makes
their PDFs and holds them to the checks; the depth review says what each item leaves out; the export puts them on the
Desktop, and the lock freezes what was sent. An application's own edition (one the person wrote, or one started from
another edition's words) and the files the person made for it live here too.

Owns: in each job's folder draft.json and draft.record.json (the draft), resume/<lang>/ (each edition's files, its checks
and its baseline), cover files, own/ (an own edition), submitted/ (the copies that went out), depth.<lang>.json and its
acts, live/ (the live canvas's working folder), and the card of a named edition (a job record of kind "edition", never
on the board); and in the workspace deck/ (the person's own deck source) and out/desk_portfolio.json (the portfolio kept
on the Desktop).

    routes.py        its endpoints: each path or pattern with its handler (the gateway gathers them)
    documents.py     the canvas's resume and letter models, a sentence's edit and lock, the resume's text for the kit, the
                     editions as the page draws them and whether each is stale, an edition's printed files and record
    drafts.py        a job's drafted resume: where it is, how it lays over the facts' profile, its locks and figures
    editions.py      own and named editions: started from another edition's words (and `offerowl edition`), brought in
                     whole, a file the person made for one
    depth.py         the depth review and what the person does with each finding (and `offerowl depth`)
    delivery.py      the Desktop and the file manager, the Word and PowerPoint copies, the portfolio kept on the Desktop
    task_build.py    Tasks' part: the engine, an edition's build, its checks and pictures, the cover letter, the live pages
    task_write.py    Tasks' part: the resume's draft, the figures, the depth review's task, regenerating, tailoring
    task_own.py      Tasks' part: an own edition read, and the files that stand for its documents
    task_export.py   Tasks' part: the export, the copies that went out, the lock
    task_compare.py  Tasks' part: what an edition is held against (its other language, its deck, its twin, its baseline)

Offers: THEMES, FORMS, DECK_STYLES and LIVE (the choices, and the live canvas's folder a backup leaves out); resume_text
(the resume's text the interview kit asks about); load_draft, draft_links and draft_link (a draft and the sentences it
wrote); desktop_dir, made_day, safe_name, free_name and keep_portfolio (the Desktop and the names files take there);
general_view, editions_view, job_builds, desk_view and stale (the editions as the state carries them); PRINTED,
printed_file and build_record (an edition's printed files and its build's record); sent_file and keep_sent_file (a copy
that went out); own_edition, add_edition, keep_own_file and OWN_FORM_KEYS (own and named editions); and the parts of the
tasks: Builds, Drafting, OwnEdition, Exports and Comparisons, which add build_dir, render_lock, english_for,
drafted_english, own_dir, own_langs, own_info, forget_own, facts_for, person_name, export_name (the name an edition's file takes
on the Desktop), export, lock, forget_live, _build,
_write, _figures, _previews, _clean_engine and the rest to the runner.
"""
from .delivery import desk_view, desktop_dir, free_name, keep_portfolio, made_day, safe_name  # noqa: F401  the Desktop
from .documents import PRINTED, build_record, editions_view, general_view, job_builds, printed_file, resume_text, stale  # noqa: F401  the editions as the page draws them, their printed files and records, the kit's resume
from .drafts import link_for as draft_link, links_of as draft_links, load as load_draft  # noqa: F401  a draft and its sentences
from .editions import add_edition, keep_own_file, own_edition  # noqa: F401  own and named editions, a file made for one
from .task_build import DECK_STYLES, FORMS, LIVE, THEMES, Builds  # noqa: F401  the choices, the live folder, the build
from .task_compare import Comparisons  # noqa: F401  what an edition is held against
from .task_export import Exports, keep_sent_file, sent_file  # noqa: F401  the export, the lock, a copy that went out
from .task_own import OWN_FORM_KEYS, OwnEdition  # noqa: F401  an own edition
from .task_write import Drafting  # noqa: F401  the drafted words
from .routes import GET as GET_ROUTES, POST as POST_ROUTES, UPLOADS as UPLOAD_ROUTES  # noqa: F401  its endpoints, which the gateway gathers
