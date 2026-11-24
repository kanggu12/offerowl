"""The profile service: the person's facts and the profile built from them. The files the person brings in (the sources)
are read into fact candidates, each with the quote it rests on; the person keeps, drops or edits them, types their own,
and fills in their details; only the kept facts reach the profile, and every sentence the canvas draws keeps the
evidence it rests on. The photo, the person's own style packs and the blind edition's mask table are the profile's too.

Owns: profile/ (the profile built from the kept facts, its evidence map, the imported profile, the person's details, the
photo and the photos removed, the English profile), sources/ (the files brought in, the candidates, what was kept,
dropped and edited, the locks, what a removed source took along), style/ (the person's own style packs) and blind.json
(the person's own mask table).

    routes.py      its endpoints: each path or pattern with its handler (the gateway gathers them)
    facts.py       the candidates, what the person decided about them, and the profile and evidence map built from them
    actions.py     what the person does with the facts (keep, drop, edit, type one, keep all, the details) and what the
                   page draws of them
    evidence.py    the resume as the canvas draws it, with the evidence of every sentence, and the sentence rules
    sources.py     the sources: the example brought in and taken out, a source taken off, as the Library opens them and
                   the Trash lists, puts back and deletes them
    photo.py       the photo without what the camera wrote into it, kept and taken off, its small copy, the photos in the
                   Trash
    style.py       the writing rules: the packs to pick from, the person's own pack checked and kept, a correction kept
    masks.py       the blind edition's mask table: as kept, checked and saved
    task_facts.py  Tasks' part: the reading of files, the English profile, the kept facts as text, the profile's files a
                   document reads

Offers: Facts, OwnFacts, FACT_FILES, problems, text_of and clean_name (the facts, the profile and the person's name);
Resume, SECTION_NAMES, SECTION_LABELS, sentences, field_for, replaced, pick_lang and issue_codes (the canvas's model, its
section names and the sentence rules); keep_all, details, add_example and drop_example (the steps the autopilot takes as
the panel's keys do); facts_summary, draft_view, onboarding, materials_now, photo_state, blind_view and style_names (the
parts of the state); photo_file, set_photo, kept_photos, photo_back and purge_photo (the photo); set_blind (the mask
table); SOURCE_ID, source_file, removed_sources, source_back, purge_source and stale_translation (a source in the Library
and the Trash); FactTasks, the part of the tasks that adds ingest and _ingest, read_texts, unstick, translate and
_translate, profile_lang, english_profile, answer_facts, style_spec, blind_path, blind_file, blind_table, blind_stamp,
photo_paths, photo_for_build and _place_pictures to the runner.
"""
from .actions import details, draft_view, facts_summary, keep_all, onboarding  # noqa: F401  the person's actions on the facts, and the state's parts
from .evidence import EN_LABEL as SECTION_LABELS, WORDS as SECTION_NAMES, Resume, field_for, issue_codes, pick_lang, replaced, sentences  # noqa: F401  the canvas's model and the sentence rules
from .facts import FACT_FILES, Facts, OwnFacts, clean_name, problems, text_of  # noqa: F401  the facts and the profile
from .masks import blind_view, set_blind  # noqa: F401  the mask table
from .photo import kept_photos, photo_back, photo_file, photo_state, purge_photo, set_photo  # noqa: F401  the photo, kept, taken off and in the Trash
from .sources import SOURCE_ID, add_example, drop_example, materials_now, purge_source, removed_sources, source_back, source_file, stale_translation  # noqa: F401  the sources
from .style import style_names  # noqa: F401  the style packs to pick from
from .task_facts import FactTasks  # noqa: F401  the profile's part of the tasks
from .routes import GET as GET_ROUTES, POST as POST_ROUTES, UPLOADS as UPLOAD_ROUTES  # noqa: F401  its endpoints, which the gateway gathers
