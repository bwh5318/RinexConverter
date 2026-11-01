"""AST import-purity test (PLAN §0 "Which module may import what").

  rinexcore/ (except cddis.py) and rinexconv/: standard library only
  rinexcore/cddis.py, tools/: standard library + requests
  no shipped module imports subprocess (CLAUDE.md rule 2)
"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDLIB = set(sys.stdlib_module_names)
LOCAL = {"rinexcore", "rinexconv", "rinexqc"}


def imports(path):
    tree = ast.parse(path.read_bytes().decode("utf-8"), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # relative import: inside the package
                continue
            yield (node.module or "").split(".")[0], node.lineno


class ImportPurity(unittest.TestCase):
    def check(self, package, allowed_extra=frozenset()):
        bad = []
        for p in sorted((ROOT / package).rglob("*.py")):
            extra = allowed_extra
            if p.name == "cddis.py" and package == "rinexcore":
                extra = extra | {"requests"}
            for mod, line in imports(p):
                if mod == "subprocess":
                    bad.append(f"{p.relative_to(ROOT)}:{line} imports subprocess")
                elif mod not in STDLIB and mod not in LOCAL and mod not in extra:
                    bad.append(f"{p.relative_to(ROOT)}:{line} imports {mod}")
        self.assertEqual(bad, [])

    def test_rinexcore_stdlib_only(self):
        self.check("rinexcore")

    def test_rinexconv_stdlib_only(self):
        self.check("rinexconv")

    def test_core_does_not_import_converter(self):
        bad = []
        for p in sorted((ROOT / "rinexcore").rglob("*.py")):
            for mod, line in imports(p):
                if mod in ("rinexconv", "rinexqc"):
                    bad.append(f"{p.relative_to(ROOT)}:{line} imports {mod}")
        self.assertEqual(bad, [])

    def test_independent_checks_do_not_import_the_converter(self):
        """PLAN §3.7: the token comparator has no imports from rinexcore/rinexconv."""
        bad = []
        for p in sorted((ROOT / "tests" / "independent").rglob("*.py")):
            for mod, line in imports(p):
                if mod in LOCAL:
                    bad.append(f"{p.relative_to(ROOT)}:{line} imports {mod}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
