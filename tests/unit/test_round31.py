"""Regression tests for review round 31 (2026-11-01, docs/DECISIONS.md "review round 31
fixes"): Sonnet's malformed LEAP SECONDS records and Sol's temporary-file failure."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from rinexconv.engine import Options, convert_data, write_output
from rinexconv.leap import malformed
from rinexcore.errors import CorruptError, InvocationError

from .test_obs_fixtures import V305
from .test_round16 import merge
from .test_round28 import bds_only, leap

BAD = {"     4      1000      BDT": "field 4", "     4     x  1000     3BDT": "field 2",
       "    4a     3  1000     3BDT": "field 1", "     4     3  1000     3XYZ": "columns 25-27",
       "    18    18  2185     7 GP": "columns 25-27", "    18    18  2185     7GPSX": "text after",
       "    1²": "field 1"}


def nav_with(line):
    """bds_only, with the record written as latin-1 bytes (RINEX is read so)."""
    return bds_only("3.05", "    18").replace(b"    18".ljust(60) + b"LEAP SECONDS",
                                             line.ljust(60).encode("latin-1") + b"LEAP SECONDS")


def obs_with(line):
    lines = V305.split(b"\n")
    i = next(k for k, l in enumerate(lines) if l[60:].startswith(b"END OF HEADER"))
    lines.insert(i, line.ljust(60).encode("latin-1") + b"LEAP SECONDS")
    return b"\n".join(lines)


class MalformedLeapSeconds(unittest.TestCase):
    """Sonnet round 31: a LEAP SECONDS record a column off ended in an internal error going to
    4.02 ('T' read as the identifier) and gave '-10 / -356' in 3.02; text in a field was
    dropped to blank without a word. Such a record is refused (HDR.LEAP) whenever it has to be
    rewritten, and carried as written in a same-version conversion."""

    def test_reasons(self):
        for line, why in BAD.items():
            with self.subTest(line=line):
                self.assertIn(why, malformed(line) or "")
        for line in ("    18", "    18    18  2185     7GPS", "     4     4   573     6BDT", "  18      18",
                     "", "    18    18  2185     7", "    -1"):
            with self.subTest(line=line):
                self.assertIsNone(malformed(line))

    def test_refused_across_versions_kept_within(self):
        for line in BAD:
            for kind, src in (("nav", nav_with(line)), ("obs", obs_with(line))):
                for t in ("4.02", "3.02", "2.11"):
                    if kind == "nav" and t == "2.11":
                        continue              # (a BeiDou-only file has no RINEX 2 form at all)
                    with self.subTest(line=line, kind=kind, target=t):
                        with self.assertRaises(CorruptError) as cm:
                            convert_data(src, "x.rnx", Options(t, compression="none", assume_phase_aligned=True,
                                                               auto_nav=False, approx_position=(1.0, 2.0, 3.0),
                                                               drop_unresolvable=True))
                        self.assertEqual(cm.exception.rule, "HDR.LEAP")
                with self.subTest(line=line, kind=kind, target="3.05"):
                    outs = convert_data(src, "x.rnx", Options("3.05", compression="none", auto_nav=False))
                    rec = lambda b: [l for l in b.split(b"\n") if l.endswith(b"LEAP SECONDS")]
                    self.assertEqual(rec(outs[0].data), rec(src))       # carried as written

    def test_merge_refuses(self):
        good = bds_only("3.05", "     4     4   573     6BDT")
        bad = bds_only("3.05", "     4     x  1000     3BDT")
        with self.assertRaises(CorruptError) as cm:
            merge(good, bad, target="3.05")
        self.assertEqual(cm.exception.rule, "HDR.LEAP")


class TempFileFailure(unittest.TestCase):
    """Sol round 31: a failure creating the temporary output file escaped as OSError; it is an
    InvocationError (the CLI's io-error for that input)."""

    def test_mkstemp_failure(self):
        d = tempfile.mkdtemp()
        try:
            out = convert_data(V305, "x.rnx", Options("3.04", compression="none"))[0]
            with mock.patch("tempfile.mkstemp", side_effect=PermissionError("denied")):
                with self.assertRaises(InvocationError):
                    write_output(out, d)
            self.assertEqual(os.listdir(d), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
