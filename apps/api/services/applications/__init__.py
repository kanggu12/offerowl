"""The applications service: the jobs on the board and everything the person keeps for each application. A job's card
moves through the board's stages with its dates, rounds and reminders; its posting comes pasted or from a link and is
analyzed into the plan that orders a resume for it; its fit to the profile is worked out by words; the form's own questions
get answers within their limits; and the decks, notes and briefs the person brought in for its interview are kept as they
came (a job's materials).

Owns: jobs/<job>/status.json (the card: the core's job record, whose stage and dates only the board's rules change),
posting.md, plan.json, questions.json and materials/.

    routes.py         its endpoints: each path or pattern with its handler (the gateway gathers them)
    jobs.py           the jobs as the panel's keys change them (added, renamed, moved, a round or a reminder) and as the
                      page draws them, with their fits
    tracker.py        the board's rules: the days of the stages, the timeline, the reminders due, the rounds, the calendar
                      file, a card moved on when its documents went out
    postings.py       a posting from a link, fetched once and checked, and where a job's posting is kept
    fit.py            how the profile fits a posting, line by line, by words, and the fits cached per posting and profile
    answers.py        the form's questions read from a paste, a picture or a file, their answers written and checked
    materials.py      a job's own materials: kept byte for byte, listed, previewed, copied out and taken off
    task_analyze.py   Tasks' part: the posting analysis, and the plan it keeps
    task_answers.py   Tasks' part: the answers written by the agent, and their text file on the Desktop

Offers: add_job, board and questions_from_file (a job added, its card changed, its form's questions read from a file);
jobs_view, job_in_view, fit_of and due (the jobs, their fits and the reminders, as the state and the Insights read
them); Fits (one panel's fits, built by the composition root); stage_days (the days a card reached its stages);
mark_sent (the board's rule for a card whose documents went out); posting_file, plan_of and kept_questions (a job's
posting, its plan, its questions as kept); FILE_TYPES, TEXT_KINDS, ODD_CHARS, RESERVED_NAMES and decodes (a file answered
or named on the Desktop); material_records, removed_materials, material_removed_days, put_material_back, purge_material,
material_undo_edit, MATERIALS_LOCK and MATERIAL_PREVIEWS (a material in the Library, the Trash and a backup); Analyses
and AnswerTasks, the parts of the tasks that add analyze and _analyze, answers and _answers, export_answers and
posting_of to the runner.
"""
from .answers import kept_questions, questions_from_file  # noqa: F401  the questions as kept, and read from a file
from .fit import Fits  # noqa: F401  the fits of one panel
from .jobs import add_job, board, fit_of, job_in_view, jobs_view  # noqa: F401  the jobs
from .materials import KINDS as FILE_TYPES, LOCK as MATERIALS_LOCK, ODD as ODD_CHARS, PREVIEWS as MATERIAL_PREVIEWS  # noqa: F401  a material's file
from .materials import RESERVED as RESERVED_NAMES, TEXT as TEXT_KINDS, decodes  # noqa: F401
from .materials import purge as purge_material, put_back as put_material_back, records as material_records  # noqa: F401  a material in the Trash
from .materials import removed_days as material_removed_days, removed_records as removed_materials, undo_edit as material_undo_edit  # noqa: F401
from .postings import posting_file  # noqa: F401  where a job's posting is kept
from .task_analyze import Analyses, plan_of  # noqa: F401  the posting analysis
from .task_answers import AnswerTasks  # noqa: F401  the answers task
from .tracker import due, mark_sent, stage_days  # noqa: F401  the board's days, a card moved on when its documents went out, the reminders due
from .routes import GET as GET_ROUTES, POST as POST_ROUTES, UPLOADS as UPLOAD_ROUTES  # noqa: F401  its endpoints, which the gateway gathers
