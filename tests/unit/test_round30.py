"""Regression tests for review round 30 (2026-11-01, docs/DECISIONS.md "review round 30
fixes"): Sol's two blockers (a leap-second day tied to its week; report names past the
device-name guard) and the polish of both reviewers."""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

from rinexconv.cli import main as cli_main
from rinexconv.engine import Options, convert_data
from rinexcore import names
from rinexcore.io import archive
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav

from .test_obs_fixtures import V211
from .test_round28 import bds_only, leap
from .test_tar_input import tar_bytes


class LeapDayOnItsOwn(unittest.TestCase):
    """Sol 1: the fields are optional one by one ("(BNK)", rinex305.txt Table A5) and a day is
    BeiDou 0-6 against GPS 1-7 whether or not the week is given; round 28 tied the day to its
    week, so '4 3 _ 2BDT' went to 4.02 with day 2 (should be 3) and 3.02 '4 3 0 2' lost its
    day in 3.05, both unreported and passed by the checker."""

    def check(self, src, t, want, bad_line):
        outs = convert_data(src, "x.rnx", Options(t, compression="none"))
        rep = outs[0].report.to_dict()
        self.assertEqual(leap(outs[0].data), [want])
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        bad = outs[0].data.replace(want.encode(), bad_line.encode())
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_nav(src, [bad], rep), bad_line)

    def test_day_without_week_to_gps(self):
        src = bds_only("3.05", "     4     3           2BDT")
        self.check(src, "4.02", "    18    17           3GPS", "    18    17           2GPS")

    def test_day_kept_when_week_unknown(self):
        src = bds_only("3.02", "     4     3     0     2")
        self.check(src, "3.05", "     4     3           2BDT", "     4     3                  BDT")
        self.check(src, "4.02", "    18    17     0     3GPS", "    18    17     0     2GPS")


class FileNames(unittest.TestCase):
    """Sol 2: Windows also reserves COM¹ COM² COM³ LPT¹ LPT² LPT³, CONIN$ and CONOUT$, and names
    ending in a dot or a blank (ntpath.isreserved, Python 3.13); a tar member 'COM¹' passed and
    its report 'COM¹.report.json' was written unchecked. One check (names.unsafe_file_name)
    now serves members, outputs and reports."""

    UNSAFE = ["CON", "con.rnx", "nul .txt", "COM1", "COM¹", "com².26o", "LPT³", "LPT9.x",
              "CONIN$", "conout$.rnx", "trail.20n.", "x0010.26o ", " lead", "a:b", "a<b", "a|b", "a\x7f"[:1] + "\x01",
              "x" * 256, "", ".", ".."]
    SAFE = ["ALGO00CAN_R_20262740000_01D_30S_MO.crx.gz", "algo2740.26o", "COM10.rnx", "CONX", "obs.rnx.v3.05.rnx",
            "x" * 255, "nul_x.rnx"]

    def test_rules(self):
        for n in self.UNSAFE:
            with self.subTest(name=n):
                self.assertIsNotNone(names.unsafe_file_name(n))
        for n in self.SAFE:
            with self.subTest(name=n):
                self.assertIsNone(names.unsafe_file_name(n))

    def test_against_ntpath_where_python_has_it(self):
        import ntpath
        if not hasattr(ntpath, "isreserved"):
            self.skipTest("ntpath.isreserved is Python 3.13+")
        # (isreserved takes a path: 'a:b' is drive a: and file b there; as one file name it is
        # refused, which is stricter)
        for n in self.UNSAFE + self.SAFE:
            if n and n not in (".", "..") and len(n) <= 255 and n[0] != " " and n[1:2] != ":":
                with self.subTest(name=n):
                    self.assertEqual(names.unsafe_file_name(n) is not None, ntpath.isreserved(n))

    def test_superscript_member_skipped(self):
        got = {b: w for f, b, d, w in archive.members(tar_bytes([("COM¹", V211), ("ok0010.26o", V211)]))}
        self.assertEqual(got, {"COM¹": "no usable file name", "ok0010.26o": None})

    def test_long_name_shortened_in_messages(self):
        self.assertLessEqual(len(names.shown("x" * 300)), 82)
        self.assertEqual(names.shown("abc"), "'abc'")


class ReportFailureKeepsTheBatchGoing(unittest.TestCase):
    """Sol polish: a report that cannot be written is an io-error for its input, and the next
    input is still converted."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_report_dir_is_a_file(self):
        a = os.path.join(self.tmp, "a0010.26o")
        b = os.path.join(self.tmp, "b0010.26o")
        for p in (a, b):
            with open(p, "wb") as fh:
                fh.write(V211)
        rep = os.path.join(self.tmp, "rep")
        with open(rep, "wb") as fh:
            fh.write(b"not a folder")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli_main([a, b, "--to", "3.01", "--out", os.path.join(self.tmp, "out"), "--report", rep,
                           "--no-auto-nav"])
        self.assertEqual(rc, 5, err.getvalue())
        self.assertEqual(err.getvalue().count("io-error: the report could not be written"), 2)
        # round 32: the report's place is checked before any output of the input is written, so
        # an input whose report cannot be written leaves no output behind (it was written before)
        out = os.path.join(self.tmp, "out")
        self.assertFalse(os.path.exists(out) and os.listdir(out))


if __name__ == "__main__":
    unittest.main()
