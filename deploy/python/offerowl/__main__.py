"""`python -m offerowl`: the same as the `offerowl` command, for systems where the command's folder is not on PATH."""
from offerowl.cli import main  # an absolute import: python -m runs this file as __main__ inside the package

if __name__ == "__main__":  # only when started as a program
    raise SystemExit(main())  # the command's exit code becomes the process's
