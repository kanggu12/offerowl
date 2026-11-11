"""A stand-in for an engine script, started through the app's interpreter role."""
import json  # the report
import os  # paths
import sys  # the command line the script sees

here = os.path.dirname(os.path.abspath(__file__))  # the folder this script is in
# what the test reads back: the arguments, the module name, and whether the script's own folder is first on the path
print(json.dumps({"argv": sys.argv[1:], "name": __name__, "path0_is_script_folder": os.path.realpath(sys.path[0]) == os.path.realpath(here)}))
raise SystemExit(3)  # a script's own exit code must reach the caller
