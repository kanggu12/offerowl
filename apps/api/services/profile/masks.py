"""The blind edition's mask table: the person's own (the workspace's blind.json, never in the repository), else the shipped
one (src/blind.json), which covers nothing. What the panel shows of it, the table as kept, and a new one checked by
src/blind.py before it is kept, in one undo step."""
from __future__ import annotations

from ...core.workspace import read_json, write_json  # files


def blind_view(api) -> dict:
    """What the panel shows of the mask table of the blind edition: whether it is the person's own (else Offerowl's, which
    covers nothing), how many patterns each of its lists holds, and its stamp (what an edition's bars were made with)."""
    import blind  # src/blind.py: the lists
    return {"own": api.tasks.blind_file() is not None, "counts": blind.counts(api.tasks.blind_table()),
            "stamp": api.tasks.blind_stamp()}  # which table it is: an edition made with another one says so


def blind_read(api) -> dict:
    """The mask table as kept: the person's own file, else the shipped one (src/blind.json), with the summary."""
    import blind  # src/blind.py: the shipped table's place
    f = api.tasks.blind_file()  # theirs, if any
    table = read_json(f if f else blind.DEFAULT, {})  # as it is on disk
    return {"table": table if isinstance(table, dict) else {}, **blind_view(api)}


def set_blind(api, req: dict) -> dict:
    """The person's own mask table for the blind edition, kept as the workspace's blind.json (never in the repository):
    {table} replaces it once it passes src/blind.py's checks (each pattern read alike by Python and JavaScript, colours
    and words of a sane shape and size), {table: null} takes it away, so the shipped table applies again. One undo step.
    Refused with blind_table, or blind_pattern:<list>:<n> for the first pattern that cannot be used. Returns the summary."""
    import blind  # src/blind.py: the checks
    if "table" not in req:  # a request that names no table changes nothing
        raise ValueError("blind_table")
    f = api.ws.path("blind.json")  # beside the profile and the jobs
    table = req["table"]  # the new table, or None
    if table is not None:  # a table to keep: checked first
        found = blind.problems(table)  # what stops it
        if found:  # the first one, in words the page can say
            where = found[0].split(":")  # list:n:why, or key:why
            raise ValueError(f"blind_pattern:{where[0]}:{where[1]}" if where[0] in blind.LISTS and where[1].isdigit() else "blind_table")
    with api.ws.change({"code": "undo_blind"}, ["blind.json"]):  # undo brings the old table back
        if table is None:  # taken away
            f.unlink(missing_ok=True)
        else:  # only the keys the table has: anything else in the file stays out of the workspace
            write_json(f, blind.kept(table))
    return blind_view(api)
