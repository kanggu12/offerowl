#!/usr/bin/env python3
"""The interview kit's commands (docs/INTERVIEW.md).

    python3 src/interview/cli.py serve --job <dir> [--port 8796]       the search view
    python3 src/interview/cli.py check --job <dir> [--grow 1.6 --base <dir>] [--strict]   scene checks
    python3 src/interview/cli.py cards --job <dir> [--size 2560x1300] [--ids A1,B2]      card defects in the real page
    python3 src/interview/cli.py eval  --job <dir> [--questions FILE]    search hit rate on the job's eval set, or on another set
    python3 src/interview/cli.py plan  --job <dir> [--phrase]            question map from the posting, resume and portfolio
    python3 src/interview/cli.py draft --job <dir> [--ids P1,P2] [--limit N]   new scenes for planned questions
    python3 src/interview/cli.py audit --job <dir> [--consistency]       posting coverage and consistency with what was sent
    python3 src/interview/cli.py cue   --job <dir> [--ids A1,A2] [--sec A] [--pdf]   printable cue cards
    python3 src/interview/cli.py talk  --job <dir> [--lang ko] [--backend none]   the presentation interview's deck and script

<dir> is a job folder (<workspace>/jobs/<job>) or its interview folder. --kit names a kit.json kept elsewhere.
Model calls go through src/llm.py (OFFEROWL_LLM picks the backend; backend none never calls a model).
"""
import argparse  # the command line
import pathlib  # paths
import sys  # exit codes and the import path

SRC = pathlib.Path(__file__).resolve().parent.parent  # src/, so `interview` and `llm` import the same way from anywhere
if str(SRC) not in sys.path:  # add src/ only once, so a second import does not stack it
    sys.path.insert(0, str(SRC))  # first on the path, so this checkout wins over an installed copy

from interview import i18n  # noqa: E402  strings
from interview.job import Job  # noqa: E402  the job folder


def job_args(p):  # shared by every subcommand below
    """The options every command shares."""
    p.add_argument("--job", required=True, help="job folder (<workspace>/jobs/<job>) or its interview folder")  # the one option no command can run without
    p.add_argument("--kit", help="kit.json kept outside the job folder")  # for a kit shared between jobs or kept in another folder
    p.add_argument("--workspace", help="workspace folder (default: two levels above the job folder)")  # for a job folder outside the usual layout
    p.add_argument("--profile", help="profile file (default: <workspace>/profile/profile.json)")  # for a profile kept outside the workspace
    p.add_argument("--out", help="output folder (default: <workspace>/out/interview/<job>)")  # where reports and caches go when the default does not suit


def open_job(a):  # every command starts here
    """The job named on the command line, with the message language decided."""
    job = Job(a.job, kit=a.kit, workspace=a.workspace, profile=a.profile)  # stops with a message on a bad path
    i18n.use(job.kit.get("ui"))  # OFFEROWL_LANG, then the kit, then Korean
    return job


def dense_setting():  # the similarity model a person named once for every kit
    """(folder, problem) of OFFEROWL_SEARCH_MODEL (src/interview/dense.py from_setting)."""
    from interview import dense  # standard library only until the model is switched on
    return dense.from_setting()


def cmd_serve(a):  # the serve subcommand
    """Serve the search view until Ctrl+C."""
    from interview import server  # the HTTP server
    job = open_job(a)  # the job, with the message language set
    model, problem = (a.model, "") if a.model else dense_setting()  # --model, else the folder OFFEROWL_SEARCH_MODEL names
    if problem:  # the setting names a folder without the model's files: say so, and serve by keywords
        print(i18n.t("search_model_missing", missing=problem), flush=True)
    cache = job.out_dir(a.out) / "vectors" if model else None  # the model's vector cache goes with the outputs
    # build the server and the index now, so the counts printed below are real
    srv, index = server.make_server(job, port=a.port, host=a.host, model_dir=model, threads=a.threads, public_port=a.public_port, cache_dir=cache,
                                    out_dir=job.out_path(a.out), backend=a.backend)  # practice sessions go to the output folder, written on the first session
    if not index.items:  # an empty folder is almost always a wrong path
        print(i18n.t("no_items", dir=job.interview))  # say where it looked, so a wrong --job is easy to spot
    # the address to open; behind a port mapping the browser's port, not the bound one
    print(i18n.t("serving", host="127.0.0.1", port=a.public_port or srv.server_address[1], items=len(index.items), job=job.name), flush=True)
    print(i18n.t("serving_model", model=model) if model else i18n.t("serving_keywords"), flush=True)  # say which search is on: keywords only, or with the model
    print(i18n.t("stop_hint"), flush=True)  # how to stop, since the command blocks
    try:
        srv.serve_forever(poll_interval=0.5)  # until interrupted
    except KeyboardInterrupt:  # Ctrl+C: stop quietly
        pass
    finally:
        srv.server_close()  # release the port, also after Ctrl+C
    return 0  # a normal stop is a success


def cmd_check(a):  # the check subcommand
    """Scene checks; the last line is the verdict."""
    from interview import check  # the checker
    job = open_job(a)  # the job, with the message language set
    if a.grow and not a.base:  # growth is measured against an earlier copy; without one it would silently pass
        print(i18n.t("grow_needs_base"))  # an option error, like argparse's own
        return 2  # argparse's exit code for a usage error
    # the checker prints the verdict and returns the exit code
    return check.main(job, grow=a.grow, base=a.base, strict=a.strict, style=a.style, files=a.files, ids=a.ids, quiet=a.quiet)


def cmd_cards(a):  # the cards subcommand
    """Card defects and window sizes in the real page (Playwright)."""
    from interview import cards  # the browser checks
    job = open_job(a)  # the job, with the message language set
    return cards.main(job, sizes=a.size, ids=a.ids, url=a.url, port=a.port, with_sizes=a.sizes, out=a.out)  # window sizes, the subset and the page to use; its exit code is ours


def cmd_eval(a):  # the eval subcommand
    """Search hit rate on the job's eval set, measured in the real page."""
    from interview import evalset  # the eval
    job = open_job(a)  # the job, with the message language set
    return evalset.main(job, url=a.url, port=a.port, size=a.size, out=a.out,  # the page to type into and the window size that fixes the board layout
                        questions_file=a.questions)  # another question set, or the job's own


def cmd_plan(a):  # the plan subcommand
    """The question map."""
    from interview import plan  # the map
    job = open_job(a)  # the job, with the message language set
    return plan.main(job, out=a.out, phrase=a.phrase, backend=a.backend, expect=a.anticipate)  # the model is used only with --phrase and --anticipate


def cmd_draft(a):  # the draft subcommand
    """New scenes for planned questions."""
    from interview import draft  # the writer
    job = open_job(a)  # the job, with the message language set
    return draft.main(job, out=a.out, ids=a.ids, limit=a.limit, backend=a.backend, plan_file=a.plan, jobs=a.jobs)  # a subset or a cap keeps each model run small


def cmd_audit(a):  # the audit subcommand
    """Posting coverage, portfolio claims and consistency, optionally scored against an answer key."""
    from interview import audit  # the audits
    job = open_job(a)  # the job, with the message language set
    # the model is used only with --consistency (and --judge); --key scores the result against a person's own audit
    return audit.main(job, out=a.out, consistency=a.consistency, backend=a.backend, ids=a.ids, limit=a.limit,
                      calls=a.calls, judge=a.judge, key=a.key)


def cmd_cue(a):  # the cue subcommand
    """Printable cue cards."""
    from interview import cue  # the cards
    job = open_job(a)  # the job, with the message language set
    return cue.main(job, ids=a.ids, sections=a.sec, roles=a.roles, out=a.out, pdf=a.pdf)  # a file to print, and a PDF when asked


def cmd_deck(a):  # the deck subcommand
    """The printable interview deck."""
    from interview import deck  # the deck
    job = open_job(a)  # the job, with the message language set
    return deck.main(job, kinds=a.kinds, ids=a.ids, n=a.n, out=a.out, pdf=a.pdf, lang=a.lang)  # a file to print, and a PDF when asked


def cmd_talk(a):  # the talk subcommand
    """The presentation interview's deck and script."""
    from interview import talk  # the talk
    job = open_job(a)  # the job, with the message language set
    try:
        summary = talk.make(job, lang=a.lang, backend=a.backend, out=a.out, pdf=not a.no_pdf)  # plan, write, draw, check
    except talk.TalkError as e:  # the brief, the profile or the portfolio stopped it: one line, no stack trace
        print(f"talk: {e}", file=sys.stderr)
        return 1
    print(summary["folder"])  # where the deck and the script are
    return 0 if not summary["layout"] else 2  # a deck with layout defects is made, but the exit code says so


def utf8_stdio() -> None:
    """Print UTF-8 whatever the console's code page: the kit's lines hold Korean, which a Windows pipe or a redirected file in
    cp1252 would refuse at the first Hangul letter."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # a text stream of this Python, not a test's replacement
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):  # the entry point, also called by the tests
    """Parse the command line and run one command; returns the exit code."""
    utf8_stdio()  # the questions, the scenes and the messages are Korean
    ap = argparse.ArgumentParser(prog="offerowl interview", description="Offerowl interview kit")  # the top-level parser; prog matches how the launcher names it
    sub = ap.add_subparsers(dest="cmd", required=True)  # one subparser per command; required, so a bare call shows usage

    p = sub.add_parser("serve", help="serve the search view")  # the search view server
    job_args(p)  # the shared job options
    p.add_argument("--port", type=int, default=8796, help="port (default 8796)")  # a fixed default, so an open browser tab keeps working after a restart
    # loopback by default; a container needs 0.0.0.0 to be reachable from the host
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (0.0.0.0 only inside a container)")
    # the Host check and the printed address must use the mapped port
    p.add_argument("--public-port", type=int, help="the port the browser uses, when a container maps another one")
    # without it the server stays keyword-only and needs no third-party packages
    p.add_argument("--model", help="bge-m3 folder (tokenizer.json, onnx/model_int8.onnx): turns on the optional similarity switch "
                                   "(default: the folder OFFEROWL_SEARCH_MODEL names)")
    p.add_argument("--threads", type=int, default=6, help="model threads")  # caps the model's CPU use so the machine stays responsive
    p.add_argument("--backend", help="model backend for practice mode (claude-code, codex, openai-compat, none)")  # none: the fixed list
    p.set_defaults(fn=cmd_serve)  # main runs cmd_serve for this command

    p = sub.add_parser("check", help="check the scenes")  # the scene checker
    job_args(p)  # the shared job options
    # 0 turns the length comparison off; used when lengthening scenes
    p.add_argument("--grow", type=float, default=0, help="each scene's lines must be at least this many times longer than in --base")
    p.add_argument("--base", help="an earlier copy of the interview folder to compare lengths with")  # only read with --grow
    # a tighter grounding pass for scenes about to be used
    p.add_argument("--strict", action="store_true", help="ground numbers and names in the materials only, not in the scene's own notes")
    # to try another wording style without editing the kit
    p.add_argument("--style", help="style pack name (<workspace>/style/<name>.json) or path; default: the kit's")
    p.add_argument("--files", help="only these source files, comma-separated")  # quicker runs while editing one file
    p.add_argument("--ids", help="only these items, comma-separated")  # quicker runs while editing a few scenes
    p.add_argument("--quiet", action="store_true", help="print the verdict line only")  # for scripts that read only the last line
    p.set_defaults(fn=cmd_check)  # main runs cmd_check for this command

    p = sub.add_parser("cards", help="count card defects in the real page")  # the browser check of every card
    job_args(p)  # the shared job options
    # append, so several sizes run in one call
    p.add_argument("--size", action="append", help="window size WxH (repeatable; default 2560x1300 and 1440x900)")
    p.add_argument("--ids", help="only these items, comma-separated")  # only the cards that changed
    # slower, so it runs only when asked
    p.add_argument("--sizes", action="store_true", help="also check the contents and three searches at four window sizes and both themes")
    p.add_argument("--url", help="a page already being served (default: start one on a free port)")  # reuse a running server instead of starting a second one
    # 0 lets the system pick, so it never clashes with a running server
    p.add_argument("--port", type=int, default=0, help="port for the page this command starts (default: a free one)")
    p.set_defaults(fn=cmd_cards)  # main runs cmd_cards for this command

    p = sub.add_parser("eval", help="search hit rate on the job's eval set")  # the search hit-rate measure
    job_args(p)  # the shared job options
    p.add_argument("--url", help="a page already being served (default: start one on a free port)")  # reuse a running server instead of starting a second one
    # 0 lets the system pick, so it never clashes with a running server
    p.add_argument("--port", type=int, default=0, help="port for the page this command starts (default: a free one)")
    # one fixed default, so hit rates from different runs compare
    p.add_argument("--size", default="1920x1080", help="window size (the board's layout decides which three cards come first)")
    # questions in other words than the cards use, kept apart from the job's own set, which aims at full marks
    p.add_argument("--questions", help="another question set of the same form (default: the job's eval_questions.json)")
    p.set_defaults(fn=cmd_eval)  # main runs cmd_eval for this command

    p = sub.add_parser("plan", help="make the question map")  # the question map from the posting and what was sent
    job_args(p)  # the shared job options
    # off by default, so a plan costs no model calls
    p.add_argument("--phrase", action="store_true", help="let the model phrase the questions (one small call per group)")
    # one call per job, kept beside the map
    p.add_argument("--anticipate", action="store_true", help="ask the model once for the scenario and technical questions of this job")
    p.add_argument("--backend", help="model backend for --phrase and --anticipate (claude-code, codex, openai-compat, none)")  # overrides OFFEROWL_LLM for this run
    p.set_defaults(fn=cmd_plan)  # main runs cmd_plan for this command

    p = sub.add_parser("draft", help="write scenes for planned questions")  # scene drafts for planned questions
    job_args(p)  # the shared job options
    p.add_argument("--plan", help="question map (default: <out>/plan.json)")  # a map kept elsewhere, such as an older one
    p.add_argument("--ids", help="only these planned questions, comma-separated")  # draft a few questions at a time
    p.add_argument("--limit", type=int, default=0, help="at most this many scenes")  # 0 means no cap; a cap keeps model spend small
    p.add_argument("--backend", help="model backend (claude-code, codex, openai-compat, none)")  # overrides OFFEROWL_LLM for this run
    p.add_argument("--jobs", type=int, default=1, help="scenes written side by side (default 1)")  # a CLI agent can take a few; a local model answers one at a time
    p.set_defaults(fn=cmd_draft)  # main runs cmd_draft for this command

    p = sub.add_parser("audit", help="posting coverage and consistency")  # posting coverage and agreement with what was sent
    job_args(p)  # the shared job options
    # off by default because it calls the model
    p.add_argument("--consistency", action="store_true", help="also compare scenes with the submitted resume and portfolio (model calls)")
    p.add_argument("--backend", help="model backend for --consistency")  # overrides OFFEROWL_LLM for this run
    p.add_argument("--ids", help="consistency for these items only, comma-separated")  # check a few scenes at a time
    p.add_argument("--limit", type=int, default=0, help="consistency for at most this many scenes")  # 0 means no cap; a cap keeps model spend small
    # the budget decides which scenes go to the model: the riskiest first, a batch per call
    p.add_argument("--calls", type=int, default=0, help="at most this many model calls for consistency (default: every scene that touches the documents)")
    p.add_argument("--judge", action="store_true", help="one more call: does the closest scene really answer each posting line")  # the coverage rule cannot tell
    p.add_argument("--key", help="an answer key (expected findings JSON): print recall and precision against it")  # a person's own audit
    p.set_defaults(fn=cmd_audit)  # main runs cmd_audit for this command

    p = sub.add_parser("cue", help="printable cue cards")  # one scene per card
    job_args(p)  # the shared job options
    p.add_argument("--ids", help="only these items, comma-separated")  # the scenes to print
    p.add_argument("--sec", help="only these section letters, comma-separated")  # a section at a time
    p.add_argument("--roles", default="scenes", help="which kinds of item get cards (scenes, deep, terms; default scenes)")  # deep dives and terms on request
    p.add_argument("--pdf", action="store_true", help="also print the page to PDF (Playwright)")  # a file to send to a printer
    p.set_defaults(fn=cmd_cue)  # main runs cmd_cue for this command

    p = sub.add_parser("deck", help="the printable interview deck (16:9 pages)")  # the posting's lines, then one script per question
    job_args(p)  # the shared job options
    p.add_argument("--kinds", help="only these parts, comma-separated (opening, behavioral, company, posting, resume, portfolio, scenario, technical, closing)")
    p.add_argument("--ids", help="only these scripts, comma-separated")  # the scripts to print
    p.add_argument("--n", type=int, help="scripts per part (default: a few of each, the likeliest first)")  # a longer or shorter deck
    p.add_argument("--lang", choices=("ko", "en"), help="the deck's own words (default: the kit's)")  # the labels, not the scripts
    p.add_argument("--pdf", action="store_true", help="also print the page to PDF (Playwright)")  # a file to send or print
    p.set_defaults(fn=cmd_deck)  # main runs cmd_deck for this command

    p = sub.add_parser("talk", help="the presentation interview's deck and script (the brief is <job>/interview/talk.json)")  # docs/INTERVIEW.md, The talk
    job_args(p)  # the shared job options
    p.add_argument("--lang", choices=("ko", "en"), help="the talk's language (default: the brief's, else the job's edition)")  # Korean or English slides
    p.add_argument("--backend", help="the agent that writes the talk's own words (default: OFFEROWL_LLM); none keeps to the documents' words")  # no model at all with none
    p.add_argument("--no-pdf", action="store_true", help="draw the deck and the script without printing the script")  # the deck's PDF is always printed: its pictures feed the script
    p.set_defaults(fn=cmd_talk)  # main runs cmd_talk for this command

    a = ap.parse_args(argv)  # argv lets the tests call main without a shell
    return a.fn(a)  # run the chosen command; its return value is the exit code


if __name__ == "__main__":  # only when run as a script, not when imported by the tests
    sys.exit(main())  # hand the command's exit code to the shell
