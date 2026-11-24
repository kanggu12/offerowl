"""The services' boundaries (docs/ARCHITECTURE.md "The services"), read from the code without running it:

- a service imports another service only through its package (apps.api.services.<name>), never one of its modules;
- the core imports no service, and none of the API's hubs (app, tasks, routes, web, client);
- a service imports no hub either, but the in-process client inside a command line's main() (`offerowl edition`, `offerowl
  depth` call the gateway as the panel does);
- a service builds paths only into the files it owns: the literal start of ws.path(...), the name after job_dir(...) /,
  and the name after "jobs/<id>/" in an undo step's list of files; and it builds no path inside a folder another service
  names for it (another's build_dir(...) / "build.json"): it asks the owner for the file;
- each service package says in its docstring what it does, what it owns and what it offers, has a routes.py of its own,
  and exports no name that hides one of its own modules (a package's `fit` would hide its module fit.py);
- no two routes of all the tables match one path, so the order in which the gateway gathers them decides nothing.

Run: python3 -m unittest discover -s tests/app -p test_architecture.py
"""
import ast  # the imports and the paths, read without running the code
import sys  # the import path
import unittest  # the runner
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
API = ROOT / "apps" / "api"  # the API's package
SERVICES = API / "services"  # the services
HUBS = ("app", "tasks", "routes", "web", "client", "__main__")  # the API's own modules above the services
NAMES = sorted(p.name for p in SERVICES.iterdir() if (p / "__init__.py").is_file())  # every service
# What each service owns, as the paths it builds name it: the start of ws.path(...) (two parts under out/), and the name in a
# job's folder after job_dir(...) / or after "jobs/<id>/". The Library deletes whole jobs (their folder into the core's
# .gone/, their files out of the undo steps), and the documents read every edition's record under jobs/.
OWNS = {  # service: (its starts of ws.path, its names in a job's folder)
    "profile": ({"profile", "sources", "style", "blind.json"}, set()),  # the person's files; nothing in a job's folder
    "applications": (set(), {"posting.md", "plan.json", "questions.json", "materials"}),  # a job's posting, plan, questions, materials
    "documents": ({"deck", "jobs", "out/desk_portfolio.json"}, {"draft.json", "draft.record.json", "resume", "own", "submitted", "live", "depth.*"}),  # the editions
    "interview": ({"out/interview"}, {"interview"}),  # the kits
    "agent": ({"ask", "out/runs.json"}, set()),  # the command bar and the finished runs
    "library": ({".gone"}, {"*"}),  # a whole job, deleted for good
    "insights": (set(), set()),  # nothing: it only reads
}


def modules(folder: Path):
    """(dotted name, path, tree) of every module under a folder."""
    for f in sorted(folder.rglob("*.py")):  # in a stable order
        parts = list(f.relative_to(ROOT).with_suffix("").parts)  # apps, api, services, profile, facts
        if parts[-1] == "__init__":  # a package's own module is the package
            parts = parts[:-1]
        yield ".".join(parts), f, ast.parse(f.read_text(encoding="utf-8"), filename=str(f))  # parsed, never run


def package_of(name: str, path: Path) -> str:
    """The package a module's relative imports start from."""
    return name if path.name == "__init__.py" else name.rpartition(".")[0]  # a package is its own; a module is its folder's


def imports(name: str, path: Path, tree):
    """(line, imported module, the names taken from it, the function it is in) for every import of a module, relative ones
    resolved."""
    funcs = {}  # an import's node -> the function around it
    for fn in ast.walk(tree):  # outer functions first, so a nested import is named by the function that holds it all
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):  # everything inside it
                funcs.setdefault(id(n), fn.name)
    for node in ast.walk(tree):  # module level and inside functions alike: a lazy import counts too
        if isinstance(node, ast.Import):  # import a.b.c
            for a in node.names:
                yield node.lineno, a.name, [], funcs.get(id(node))
        elif isinstance(node, ast.ImportFrom):  # from x import y, from .. import y
            if node.level:  # relative: from the module's package, one level up per dot past the first
                base = package_of(name, path).split(".")  # where the dots count from
                base = base[:len(base) - (node.level - 1)]  # one package up for each dot past the first
                target = ".".join(base + ([node.module] if node.module else []))  # the module named, resolved
            else:  # absolute
                target = node.module or ""
            yield node.lineno, target, [a.name for a in node.names], funcs.get(id(node))


def is_module_of(service: str, name: str) -> bool:
    """Is `name` one of a service's own modules (a file or a sub-package of its folder)? Matched against the folder's names as
    written: a Mac's or Windows's disk finds Facts.py as facts.py, and so took the class Facts for the module facts."""
    folder = SERVICES / service  # the service's own folder
    own = {p.name for p in folder.iterdir()}  # its files and folders, spelt as on disk
    return f"{name}.py" in own or (name in own and (folder / name / "__init__.py").is_file())  # a module, or a sub-package


class Imports(unittest.TestCase):
    def test_a_service_imports_another_only_through_its_package(self):
        bad = []  # what breaks the rule, with its file and line
        for name, path, tree in modules(SERVICES):  # every module of every service
            mine = name.split(".")[3] if name.count(".") >= 3 else None  # apps.api.services.<mine>...
            for line, target, names, _ in imports(name, path, tree):
                parts = target.split(".")  # apps, api, services, <other>, <module>
                if parts[:3] != ["apps", "api", "services"] or len(parts) < 4 or parts[3] == mine:
                    continue  # not a service, or its own
                other = parts[3]  # the service it imports from
                if len(parts) > 4:  # one of the other service's modules, named outright
                    bad.append(f"{path.relative_to(ROOT)}:{line}: imports {target}")
                bad += [f"{path.relative_to(ROOT)}:{line}: imports {other}.{n}, a module of {other}"  # from ..other import a module
                        for n in names if len(parts) == 4 and is_module_of(other, n)]
            for line, target, names, _ in imports(name, path, tree):  # `from .. import <service>` takes the package itself
                if target == "apps.api.services":  # names taken from the services' own package: only services
                    bad += [f"{path.relative_to(ROOT)}:{line}: imports {n}, which is no service" for n in names if n not in NAMES]
        self.assertEqual([], bad)

    def test_the_core_imports_no_service_and_no_hub(self):
        bad = []  # what breaks the rule, with its file and line
        for name, path, tree in modules(API / "core"):  # every module of the core
            for line, target, names, _ in imports(name, path, tree):
                parts = target.split(".")  # apps, api, <what>
                if parts[:3] == ["apps", "api", "services"] or (parts[:2] == ["apps", "api"] and len(parts) > 2 and parts[2] in HUBS):
                    bad.append(f"{path.relative_to(ROOT)}:{line}: imports {target}" + (f" ({', '.join(names)})" if names else ""))  # what it takes from there
                if target == "apps.api":  # `from .. import x`
                    bad += [f"{path.relative_to(ROOT)}:{line}: imports {n}" for n in names if n in HUBS or n == "services"]
        self.assertEqual([], bad)

    def test_a_service_imports_no_hub_but_the_client_of_a_command_line(self):
        bad = []  # what breaks the rule, with its file and line
        for name, path, tree in modules(SERVICES):  # every module of every service
            for line, target, names, func in imports(name, path, tree):
                parts = target.split(".")  # apps, api, <what>
                hub = parts[2] if parts[:2] == ["apps", "api"] and len(parts) > 2 and parts[2] in HUBS else None  # from ...app import x
                hubs = [hub] if hub else [n for n in names if target == "apps.api" and n in HUBS]  # or from ... import app
                for h in hubs:  # each hub it imports
                    if not (h == "client" and func == "main"):  # the in-process client, for `offerowl edition` and `offerowl depth`
                        bad.append(f"{path.relative_to(ROOT)}:{line}: imports apps.api.{h}" + (f" in {func}()" if func else ""))
        self.assertEqual([], bad)


def literal(node):
    """A string literal's text, or None."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def owned(name: str, own: set) -> bool:
    """Is a file or folder name one of a service's own?"""
    return "*" in own or name in own or any(o.endswith(".*") and name.startswith(o[:-1]) for o in own)  # "depth.*": depth.ko.json and the like


class Files(unittest.TestCase):
    def test_a_service_builds_paths_only_into_its_own_files(self):
        self.assertEqual(sorted(OWNS), NAMES)  # every service is listed above, and only services
        bad = []  # what breaks the rule, with its file and line
        for service, (ws_own, job_own) in OWNS.items():  # each service against what it owns
            for name, path, tree in modules(SERVICES / service):  # every module of it
                where = lambda node: f"{path.relative_to(ROOT)}:{node.lineno}"  # noqa: E731
                for node in ast.walk(tree):  # every call, division and f-string in it
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "path" and node.args:
                        parts = [literal(a) for a in node.args]  # ws.path("profile", "photo.jpg") and the like
                        if parts[0] is None:  # a name computed, never a literal: nothing to read here
                            continue
                        top = parts[0] if parts[0] != "out" else f"out/{parts[1]}"  # out/ holds several services' files
                        if not any(top == o or top.startswith(o + "/") for o in ws_own):  # not a folder or file of its own
                            bad.append(f"{where(node)}: {service} builds ws.path({', '.join(repr(p) for p in parts)})")
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.left, ast.Call) \
                            and isinstance(node.left.func, ast.Attribute) and node.left.func.attr == "job_dir":  # the core's folder of a job
                        file = literal(node.right)  # job_dir(jid) / "posting.md"
                        if file is not None and not owned(file, job_own):  # another service's file in that folder
                            bad.append(f"{where(node)}: {service} builds job_dir(...) / {file!r}")
                    if isinstance(node, ast.JoinedStr) and len(node.values) > 2 and literal(node.values[0]) == "jobs/":  # an undo step's name
                        rest = literal(node.values[2]) or ""  # f"jobs/{jid}/questions.json"
                        file = rest.lstrip("/").split("/")[0]  # the name in the job's folder; "" for the whole folder
                        if rest and not owned(file or "*", job_own):  # another service's file, or every file of the job
                            bad.append(f"{where(node)}: {service} names jobs/<id>/{rest.lstrip('/')}")
        self.assertEqual([], bad)

    def test_a_service_names_no_file_inside_another_services_folder(self):
        owners = folders()  # build_dir -> {documents}, talk_folder -> {interview}, ...
        self.assertIn("documents", owners.get("build_dir", set()))  # the table found the folders it is meant to find
        bad = []  # what breaks the rule, with its file and line
        for service in NAMES:  # every service
            for name, path, tree in modules(SERVICES / service):  # every module of it
                for node in ast.walk(tree):  # every division in it
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.left, ast.Call):  # f(...) / name
                        func = node.left.func  # t.build_dir(jid, lang) / "build.json", or a function's own name
                        called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
                        if called in owners and service not in owners[called]:  # a folder or file another service names
                            bad.append(f"{path.relative_to(ROOT)}:{node.lineno}: {service} builds {called}(...) / {ast.unparse(node.right)}"
                                       f" ({', '.join(sorted(owners[called]))}'s)")
        self.assertEqual([], bad)


def folders() -> dict:
    """The services' functions that name a folder or a file of their own (build_dir, talk_folder, posting_file and the
    like: a name ending in _dir, _folder, _path or _file), with the services that define them. Another service may hand
    such a path on as it is (to the engine, to an answer), but a path built inside it names the owner's files."""
    owners = {}  # name -> the services that define it
    for service in NAMES:  # every service
        for name, path, tree in modules(SERVICES / service):  # every module of it
            if path.name == "routes.py":  # the endpoints' handlers (get_file and the like) return answers, not paths
                continue
            for node in ast.walk(tree):  # module functions and methods of its task parts alike
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.endswith(("_dir", "_folder", "_path", "_file")):
                    owners.setdefault(node.name, set()).add(service)
    return owners


class Packages(unittest.TestCase):
    def test_each_service_says_what_it_owns_and_offers_and_has_its_own_table(self):
        import importlib  # the packages, imported
        for service in NAMES:  # every service
            pkg = importlib.import_module(f"apps.api.services.{service}")  # its package, as the others import it
            doc = pkg.__doc__ or ""  # what it says of itself
            self.assertIn("Owns:", doc, service)  # the files it owns
            self.assertIn("Offers:", doc, service)  # the API it offers the others
            self.assertTrue((SERVICES / service / "routes.py").is_file(), service)  # its own endpoints
            for table in ("GET_ROUTES", "POST_ROUTES", "UPLOAD_ROUTES"):  # the tables the gateway gathers
                self.assertIsInstance(getattr(pkg, table), tuple, f"{service}.{table}")

    def test_no_package_exports_a_name_that_hides_one_of_its_modules(self):
        import importlib  # the packages, imported
        import pkgutil  # their modules
        bad = []  # each name that hides a module
        for service in NAMES:  # every service
            pkg = importlib.import_module(f"apps.api.services.{service}")  # its package
            for m in pkgutil.iter_modules(pkg.__path__):  # each of its modules
                got = getattr(pkg, m.name, None)  # the module, unless an export took its name
                if got is not None and getattr(got, "__name__", None) != f"apps.api.services.{service}.{m.name}":  # something else answers to it
                    bad.append(f"{service}.{m.name} is {got!r}, not the module")
        self.assertEqual([], bad)


# A path for every route of every table (and a few that must match none): each must match exactly one route.
GET_PATHS = ["/api/v1/health", "/health", "/api/v1/state", "/api/v1/history", "/api/v1/schema/profile", "/api/v1/photo", "/api/v1/blind",
             "/api/v1/profile", "/api/v1/facts", "/api/v1/style", "/api/v1/jobs", "/api/v1/jobs/gamma", "/api/v1/jobs/gamma/fit",
             "/api/v1/jobs/gamma/materials", "/api/v1/jobs/gamma/materials/m1", "/api/v1/jobs/gamma/materials/m1/preview",
             "/api/v1/jobs/gamma/materials/m1/pages/1.png", "/api/v1/tracker", "/api/v1/reminders/due", "/api/v1/reminders.ics",
             "/api/v1/documents/resume", "/api/v1/documents/cover", "/api/v1/editions", "/api/v1/jobs/gamma/figures/ko/timeline.png",
             "/api/v1/jobs/gamma/figures/en/logo_delta.png", "/api/v1/jobs/gamma/deck/ko", "/api/v1/jobs/-general/depth",
             "/api/v1/jobs/gamma/files/ko/resume.pdf", "/api/v1/jobs/gamma/files/en/preview/r-1.png", "/api/v1/jobs/gamma/interview",
             "/api/v1/jobs/gamma/interview/view", "/api/v1/jobs/gamma/interview/deck", "/api/v1/jobs/gamma/talk", "/api/v1/jobs/gamma/talk/script",
             "/api/v1/jobs/gamma/talk/slides/1.png", "/api/v1/agent", "/api/v1/ask", "/api/v1/jobs/gamma/posting", "/api/v1/jobs/gamma/sent/resume.pdf",
             "/api/v1/jobs/gamma/kit/notes.md", "/api/v1/jobs/gamma/kit/out/plan.md", "/api/v1/materials/m1", "/api/v1/library",
             "/api/v1/removed", "/api/v1/workspace/backup", "/api/v1/insights",
             "/api/v1/jobs/materials", "/api/v1/jobs/gamma/talk/slides"]  # the last two: a job named "materials", and a talk path no route has
NO_GET = {"/api/v1/jobs/gamma/talk/slides"}  # matched by none: answered 404


class Routes(unittest.TestCase):
    def test_no_two_routes_match_one_path(self):
        from apps.api import routes as R  # the gateway's gathered tables
        from apps.api.core.routing import matches  # how a matcher is read
        used = set()  # the routes some path matched
        for p in GET_PATHS:  # each read's path
            hits = [i for i, (m, _) in enumerate(R.GET) if matches(m, p)]  # every read that would answer it
            self.assertEqual(0 if p in NO_GET else 1, len(hits), (p, [R.GET[i][1].__qualname__ for i in hits]))  # one, or none for a 404
            used.update(hits)
        self.assertEqual(set(range(len(R.GET))), used, [R.GET[i][1].__qualname__ for i in set(range(len(R.GET))) - used])  # every read has a path above
        exact = [m for m, _ in R.POST]  # every write is an exact path, or a few
        self.assertTrue(all(isinstance(m, (str, tuple)) for m in exact))  # no pattern among the writes
        paths = [p for m in exact for p in ((m,) if isinstance(m, str) else m)]  # every write's path
        self.assertEqual(len(paths), len(set(paths)))  # no write path twice
        self.assertFalse(set(paths) & set(R.UPLOADS))  # an upload is never a JSON write too
        for m, _ in R.GET:  # no exact read is matched by a pattern of another read
            for p in ((m,) if isinstance(m, str) else m if isinstance(m, tuple) else ()):  # an exact path, or a few
                self.assertEqual(1, sum(1 for m2, _ in R.GET if matches(m2, p)), p)  # only its own route


if __name__ == "__main__":
    unittest.main()
