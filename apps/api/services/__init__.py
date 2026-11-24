"""Offerowl's services: the API split by what each part owns, all of them in one process (docs/ARCHITECTURE.md "The
services").

    profile/       the person's facts and their evidence, the photo, the sources and the details
    applications/  the jobs on the board: their postings, the fit, the form's questions and answers, a job's own materials
    documents/     the resume, the deck and the cover letter: drafts, editions, builds, the depth review, the export
    interview/     the interview kit and the talk
    agent/         the agent card, the command bar, the run from files to documents, and the stand-in agent of the tests
    library/       the Library, the Trash and the backup: everything listed, put back and saved, through the others
    insights/      the Insights view's numbers, read only

Each service is a package. Its routes.py holds its own endpoints (the gateway, apps/api/routes.py, gathers every table),
its modules hold its work, and its __init__ says what it does, the files it owns and the functions it offers the others,
which are the only names another service may import from it. A service never imports another service's module and
never reads another service's files: it asks the owner. apps/api/core is below them all and imports none of them
(tests/app/test_architecture.py keeps these rules).
"""
