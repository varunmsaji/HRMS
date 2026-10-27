"""Runner entry point: ALWAYS runs the strict isolation check first, then dispatches.
Usage (inside the runner):  entry.py -m <module> [args...]   |   entry.py <script.py> [args...]
Nothing else in the harness starts Python in the sandbox, so no command can skip the check."""
import os
import runpy
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "src")
from tests import isolation_guard  # noqa: E402

os.environ["HRMS_QA_STRICT"] = "1"
try:
    isolation_guard.check(os.environ)
except RuntimeError as exc:
    print(exc, file=sys.stderr)
    sys.exit(97)
args = sys.argv[1:]
if not args:
    sys.exit("entry.py: nothing to run")
if args[0] == "-m":
    sys.argv = [args[1], *args[2:]]
    runpy.run_module(args[1], run_name="__main__", alter_sys=True)
else:
    sys.argv = args
    runpy.run_path(args[0], run_name="__main__")
