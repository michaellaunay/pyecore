"""Run legacy fixtures while checking the installed package provenance."""
import importlib
from pathlib import Path
import sys

import pyecore
import pytest

root = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
origin = Path(pyecore.__file__).resolve()
expected = root if mode == "source" else Path(sys.prefix).resolve()
assert origin.is_relative_to(expected), (origin, expected)
assert getattr(sys, "_is_gil_enabled", lambda: True)()
print(sys.version, "origin:", origin, flush=True)
# Tests use relative resource paths and top-level fixture modules.
import os
os.chdir(root)
code = pytest.main(["--import-mode=prepend", "-ra", str(root / "tests"), *sys.argv[3:]])
for name, module in list(sys.modules.items()):
    if name == "pyecore" or name.startswith("pyecore."):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(expected), (name, path, expected)
assert Path(importlib.import_module("pyecore").__file__).resolve() == origin
sys.exit(code)
