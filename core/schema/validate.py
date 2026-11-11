"""A small JSON Schema validator for Offerowl's own schemas, with the standard library only (the panel and the desktop
app carry no third-party packages).

It reads the subset of draft 2020-12 that core/schema uses: type, enum, const, properties, required,
additionalProperties, items, prefixItems, minItems, maxItems, minLength, maxLength, pattern, minimum, maximum,
anyOf, oneOf, allOf, not, $ref (inside one file, "#/$defs/name", or to a sibling file, "job.schema.json#/$defs/x") and
$defs. Keywords it does not know are ignored, as the standard says.

    from core.schema import validate
    errors = validate.check("profile", data)        # [] when the data fits, else one line per problem
    validate.check_file("job", path)                # the same for a file on disk

    python3 core/schema/validate.py profile examples/sample_ko.json   # prints "ok" or the problems
"""
from __future__ import annotations  # hints like `dict | None` also load on older Pythons

import json  # the schemas and the data are JSON
import posixpath  # $ref paths between schema files, with forward slashes on every system
import re  # the pattern keyword
import sys  # the command line
from pathlib import Path  # schema files

HERE = Path(__file__).resolve().parent  # core/schema
NAMES = {  # the schema each name means, so callers never spell a file name
    "profile": "profile.schema.json",  # resume-profile/0.1
    "job": "job.schema.json",  # a job's status.json
    "plan": "job.schema.json#/$defs/plan",  # a job's plan.json (the posting analysis)
    "fit": "job.schema.json#/$defs/fit",  # the fit of a job, as the API answers it
    "resume": "documents/resume.schema.json",  # the resume as the canvas draws it
    "cover": "documents/cover.schema.json",  # the cover letter (src/cover.py's cover.json)
    "interview": "documents/interview.schema.json",  # the interview studio's board
    "edition": "documents/edition.schema.json",  # one made edition (build.json)
}
_cache: dict[str, dict] = {}  # schema files read once per process
MAX_ERRORS = 50  # a broken file stops being listed after this many lines


def load(ref: str) -> tuple[dict, str]:
    """A schema by file and fragment ("job.schema.json#/$defs/plan"). Returns (schema, file it lives in)."""
    file, _, frag = ref.partition("#")  # the file and the pointer inside it
    if file not in _cache:  # first use of this file
        _cache[file] = json.loads((HERE / file).read_text(encoding="utf-8"))  # parsed once
    node = _cache[file]  # start at the file's root
    for part in [p for p in frag.split("/") if p]:  # walk the pointer ("/$defs/plan")
        node = node[part.replace("~1", "/").replace("~0", "~")]  # JSON Pointer escapes
    return node, file  # the schema and its file, for refs inside it


def resolve(ref: str, file: str) -> tuple[dict, str]:
    """A $ref as written in `file`: "#/..." inside the same file, else a file relative to it, with its fragment."""
    if ref.startswith("#"):  # inside the same file
        return load(file + ref)  # the file name with the pointer
    target, _, frag = ref.partition("#")  # another file and maybe a pointer
    name = posixpath.normpath(posixpath.join(posixpath.dirname(file), target))  # relative to the referring file
    return load(name + ("#" + frag if frag else ""))  # that file's root or the pointed part


def _type_ok(value, want: str) -> bool:
    """One JSON type name against a Python value (a bool is not a number in JSON Schema)."""
    if want == "object":  # a JSON object
        return isinstance(value, dict)  # only dicts
    if want == "array":  # a JSON array
        return isinstance(value, list)  # only lists
    if want == "string":  # a JSON string
        return isinstance(value, str)  # only str
    if want == "integer":  # a whole number
        return isinstance(value, int) and not isinstance(value, bool)  # True is not 1 here
    if want == "number":  # any number
        return isinstance(value, (int, float)) and not isinstance(value, bool)  # True is not a number here
    if want == "boolean":  # true or false
        return isinstance(value, bool)  # only bools
    if want == "null":  # null
        return value is None  # only None
    return True  # an unknown type name constrains nothing


def _errors(value, schema, file: str, where: str, out: list) -> None:
    """Add one line per problem of `value` against `schema` (found in `file`) to `out`."""
    if len(out) >= MAX_ERRORS or schema is True or schema == {}:  # enough lines, or a schema that allows anything
        return  # nothing more to say
    if schema is False:  # a schema that allows nothing
        out.append(f"{where}: not allowed here")  # e.g. an extra key under additionalProperties: false
        return  # no other keyword applies
    if "$ref" in schema:  # a reference: check against the schema it points to
        target, tfile = resolve(schema["$ref"], file)  # "#/$defs/x" here, or "../job.schema.json#/$defs/y" beside it
        _errors(value, target, tfile, where, out)  # the referenced schema decides first
    t = schema.get("type")  # one type name or a list of them
    if t is not None:  # the type keyword
        names = t if isinstance(t, list) else [t]  # always a list
        if not any(_type_ok(value, n) for n in names):  # none of the allowed types
            out.append(f"{where}: should be {' or '.join(names)}, found {type_name(value)}")  # the expected and the found type
            return  # the other keywords would only repeat the problem
    if "enum" in schema and value not in schema["enum"]:  # one of a fixed list
        out.append(f"{where}: should be one of {', '.join(json.dumps(x, ensure_ascii=False) for x in schema['enum'])}")  # the allowed values
    if "const" in schema and value != schema["const"]:  # exactly one value
        out.append(f"{where}: should be {json.dumps(schema['const'], ensure_ascii=False)}")  # the only allowed value
    if isinstance(value, str):  # string keywords
        if "minLength" in schema and len(value) < schema["minLength"]:  # too short
            out.append(f"{where}: shorter than {schema['minLength']} characters")  # names the limit
        if "maxLength" in schema and len(value) > schema["maxLength"]:  # too long
            out.append(f"{where}: longer than {schema['maxLength']} characters")  # names the limit
        if "pattern" in schema and not re.search(schema["pattern"], value):  # the shape of the text
            out.append(f"{where}: does not match {schema['pattern']}")  # names the pattern
    if isinstance(value, (int, float)) and not isinstance(value, bool):  # number keywords
        if "minimum" in schema and value < schema["minimum"]:  # too small
            out.append(f"{where}: below {schema['minimum']}")  # names the limit
        if "maximum" in schema and value > schema["maximum"]:  # too large
            out.append(f"{where}: above {schema['maximum']}")  # names the limit
    if isinstance(value, dict):  # object keywords
        for key in schema.get("required") or []:  # keys that must be there
            if key not in value:  # missing
                out.append(f"{where}: missing {key}")  # names the key
        props = schema.get("properties") or {}  # known keys
        for key, sub in props.items():  # each known key that is present
            if key in value:  # absent keys are the required keyword's business
                _errors(value[key], sub, file, f"{where}.{key}", out)  # checked against its own schema
        extra = schema.get("additionalProperties", True)  # what other keys may hold
        if extra is not True:  # only a limit needs a look at the other keys
            for key in value:  # every key of the object
                if key not in props:  # not a known one
                    _errors(value[key], extra, file, f"{where}.{key}", out)  # false refuses it, a schema checks it
    if isinstance(value, list):  # array keywords
        if "minItems" in schema and len(value) < schema["minItems"]:  # too few
            out.append(f"{where}: fewer than {schema['minItems']} items")  # names the limit
        if "maxItems" in schema and len(value) > schema["maxItems"]:  # too many
            out.append(f"{where}: more than {schema['maxItems']} items")  # names the limit
        lead = schema.get("prefixItems") or []  # schemas of the first items, by position
        for i, sub in enumerate(lead[:len(value)]):  # each leading item that is present
            _errors(value[i], sub, file, f"{where}[{i}]", out)  # by its position's schema
        if "items" in schema:  # the schema of every other item
            for i in range(len(lead), len(value)):  # the items after the leading ones
                _errors(value[i], schema["items"], file, f"{where}[{i}]", out)  # each one checked
    for sub in schema.get("allOf") or []:  # every one must hold
        _errors(value, sub, file, where, out)  # their problems add up
    if "anyOf" in schema:  # at least one must hold
        tries = [_collect(value, sub, file, where) for sub in schema["anyOf"]]  # each alternative's problems
        if all(tries):  # none held
            out.append(f"{where}: fits none of the allowed forms ({best(tries)})")  # the closest alternative's first problem
    if "oneOf" in schema:  # exactly one must hold
        tries = [_collect(value, sub, file, where) for sub in schema["oneOf"]]  # each alternative's problems
        held = sum(1 for x in tries if not x)  # how many held
        if held == 0:  # none
            out.append(f"{where}: fits none of the allowed forms ({best(tries)})")  # the closest alternative's first problem
        elif held > 1:  # more than one: the schema is ambiguous for this value
            out.append(f"{where}: fits more than one form")  # oneOf asks for exactly one
    if "not" in schema and not _collect(value, schema["not"], file, where):  # a form that must not hold
        out.append(f"{where}: has a form that is not allowed")  # the negated schema held


def _collect(value, schema, file: str, where: str) -> list:
    """The problems of one alternative, on a list of their own (anyOf and oneOf compare them)."""
    found: list = []  # a fresh list per alternative
    _errors(value, schema, file, where, found)  # the same rules
    return found  # empty when the alternative holds


def best(tries: list) -> str:
    """The first problem of the alternative with the fewest problems: the most useful hint."""
    return min(tries, key=len)[0] if tries else ""  # fewest problems first


def type_name(value) -> str:
    """The JSON type name of a Python value, for messages."""
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):  # most specific first
        if _type_ok(value, name):  # the first that fits
            return name  # its name
    return type(value).__name__  # not a JSON value at all


def check(name: str, data) -> list[str]:
    """Problems of `data` against the named schema (profile, job, plan, fit, resume, cover, interview, edition)."""
    ref = NAMES.get(name, name)  # a known name, else a file name given directly
    schema, file = load(ref)  # the schema and the file it lives in
    out: list = []  # one line per problem
    _errors(data, schema, file, "$", out)  # "$" is the root, as in JSON Path
    return out  # empty when the data fits


def check_file(name: str, path) -> list[str]:
    """The same for a JSON file on disk; a file that does not parse is one problem."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))  # the file's data
    except (OSError, ValueError) as exc:  # missing or not JSON
        return [f"$: not readable as JSON ({type(exc).__name__})"]  # one line, no traceback
    return check(name, data)  # the schema's problems


def main(argv: list | None = None) -> int:
    """python3 core/schema/validate.py NAME FILE...: "ok" per file that fits, else its problems. Exit 1 on any."""
    args = list(sys.argv[1:] if argv is None else argv)  # the name and the files
    if len(args) < 2 or args[0] not in NAMES:  # nothing to do
        print("usage: validate.py {" + ",".join(NAMES) + "} FILE...")  # the names it knows
        return 2  # a usage error
    bad = 0  # files with problems
    for f in args[1:]:  # each file named
        errs = check_file(args[0], f)  # its problems
        print(f"{f}: ok" if not errs else f"{f}:\n  " + "\n  ".join(errs))  # one line, or the problems indented
        bad += bool(errs)  # counted
    return 1 if bad else 0  # 0 only when every file fits


if __name__ == "__main__":  # run as a script
    raise SystemExit(main())  # main's answer is the exit code
