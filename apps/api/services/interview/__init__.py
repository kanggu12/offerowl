"""The interview service: each application's interview kit (its question map, the scripts the agent drafts and the person
keeps, the kit's own pages served at the panel's /kit/<job>/) and the presentation interview's talk (its brief, deck and
script). The kit's engine is src/interview; this service keeps a job's kit and runs it in this process.

Owns: jobs/<job>/interview/ (the kit's settings and the person's scripts and notes, the talk's brief) and
out/interview/<job>/ (what the kit's maker writes: the map, the drafted scripts, the deck, the talk).

    routes.py     its endpoints: each path or pattern with its handler (the gateway gathers them)
    studio.py     the board the Interview tab draws, how far a kit answers its likely questions, scenes brought in, a kit
                  carried from another application, and the kit's files as the Library opens them
    task_kit.py   Tasks' part: the kit servers, the kit made and refreshed, the scripts written, the talk made and delivered

Offers: has_kit, kit_stamp and kit_coverage (whether a job has a kit, when its map was made, how far it answers its
questions); add_scenes (scenes brought in); kit_file, library_files and drop_outputs (the kit's files in the Library and
the Trash); Kits, the part of the tasks that adds interview_available, kit_url, kit_view, kit_deck, let_kit_go,
ensure_kit, _draft_scenes, english_names, the talk's (talk_folder, talk_brief, save_talk_brief, talk_state, talk_script,
talk_slide, make_talk, deliver_talk) and write_scripts to the runner.
"""
from .studio import add_scenes, drop_outputs, has_kit, kit_coverage, kit_file, kit_stamp, library_files  # noqa: F401  the kit's files, its stamp and coverage, scenes brought in
from .task_kit import Kits  # noqa: F401  the interview's part of the tasks
from .routes import GET as GET_ROUTES, POST as POST_ROUTES, UPLOADS as UPLOAD_ROUTES  # noqa: F401  its endpoints, which the gateway gathers
