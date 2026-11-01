"""Regression tests for review round 24 (2026-11-01, docs/DECISIONS.md "review round 24
fixes"): Sonnet's two blockers, found by the generators on fresh seeds."""

import tempfile
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs
from tests.independent.generate import FCN_TABLE, ObsGen

from .test_independent_meta import SPEC
from .test_round13 import Exact
from .test_round16 import merge


class NoSatelliteLeft(unittest.TestCase):
    """Sonnet 1: a 3.05 file whose only observed satellite is NavIC (I10) has PRN / # OF OBS;
    to 3.00-3.02 (no NavIC) no satellite is left, so there is no PRN / # OF OBS line to
    write, and the checker called the record dropped (generator seed 12112)."""

    def test_seed_12112(self):
        from tests.unit.test_generated import check_one
        g = ObsGen(12112)
        src = g.data()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(FCN_TABLE)
        for t in ("3.00", "3.01", "3.02", "3.03"):
            with self.subTest(target=t):
                self.assertFalse(check_one(src, t, fh.name, None))


class MergedCorrections(Exact, unittest.TestCase):
    """Sonnet 2 (and the nav cutter, seed 20257): a --merge wrote every input's header
    corrections into one RINEX 3 header: the primary's GPSA with the other input's GPSB, read
    as one Klobuchar set, and two GPUT records. A RINEX 3 header holds one set per type
    (rinex305.txt Table A5): the first input's is kept, the others are claimed
    nav-correction-extra; RINEX 4 keeps each as its own record."""

    def files(self):
        b = (SPEC / "3.05" / "a7_nav_gps.rnx").read_bytes()
        one = b.replace(b"GPSB    .1208D+06   .1310D+06  -.1310D+06  -.1966D+06       IONOSPHERIC CORR\n", b"")
        two = b.replace(b"GPSA    .1676D-07", b"GPSA    .2676D-07").replace(
            b"GPUT   .1331791282D-06", b"GPUT   .2331791282D-06")
        self.assertNotEqual(one, b)
        self.assertNotEqual(two, b)
        return one, two

    def test_one_set_per_type(self):
        one, two = self.files()
        for t in ("3.05", "3.02"):
            with self.subTest(target=t):
                outs, rep = merge(one, two, target=t)
                head = outs[0].data.decode().split("END OF HEADER")[0]
                self.assertEqual(head.count("TIME SYSTEM CORR"), 1)
                self.assertIn(".1331791282D-06", head)                     # the primary's
                self.assertIn("GPSA    .1676D-07", head)
                self.assertNotIn("GPSB", head)       # not the other input's beta with our alpha
                self.assertEqual(rep["losses"]["nav-correction-extra:ION:KLOB:G"]["count"], 1)
                self.assertEqual(rep["losses"]["nav-correction-extra:STO:GPUT"]["count"], 1)
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(one, [o.data for o in outs], r, merged=[two]), rep)

    def test_rinex4_keeps_both(self):
        one, two = self.files()
        outs, rep = merge(one, two, target="4.02")
        self.assertFalse([k for k in rep["losses"] if k.startswith("nav-correction-extra")])
        self.assertEqual(outs[0].data.count(b"> STO G"), 2)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(one, [o.data for o in outs], rep, merged=[two]), [])


class BeiDouLeapSeconds(unittest.TestCase):
    """Sol round 24, 1 and 2: 3.03 and 3.04 spell the LEAP SECONDS BeiDou identifier 'BDS'
    (rinex303.txt Table A2 p.60, rinex304.txt Table A2 p.65), 3.05 'BDT': a 3.04 '4 ... BDS'
    went to 3.02 as GPS 4 and failed the 4.02 output check. A 3.02 navigation file has no
    identifier but counts "since 1-Jan-2006 as transmitted by BDS almanac" when it is BeiDou
    only (rinex302.txt Table A5 p.63; corpus BOR100POL_R_20262740000_01D_CN: '4'), and went to
    4.02 as GPS 4."""

    def test_bds_identifier(self):
        from .test_obs_fixtures import hdr
        from .test_round22 import mixed, rec
        src = mixed("3.04", "C", "C2I L2I", [hdr("     4     4  1000     3BDS", "LEAP SECONDS")], body=[
            "> 2026 10 01 00 00  0.0000000  0  2", rec("G05", 22e6, 115e6), rec("C11", 23e6, 120e6)])
        self.assertEqual(V.errors(V.validate(src)), [])
        want = {"3.02": "    18    18  2356     4", "3.03": "     4     4  1000     3BDS",
                "3.05": "     4     4  1000     3BDT", "4.02": "    18    18  2356     4GPS",
                "2.11": "    18"}
        for t, line in want.items():
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none", assume_phase_aligned=True))
                rep = outs[0].report.to_dict()
                got = [l[:60].rstrip() for l in outs[0].data.decode().split("\n") if l.endswith("LEAP SECONDS")]
                self.assertEqual(got, [line])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])
                # the old reading (BDS taken for GPS) is caught
                if t == "3.02":
                    bad = outs[0].data.replace(b"    18    18  2356     4", b"     4     4  1000     3")
                    self.assertTrue(compare_obs(src, bad, rep))

    def test_beidou_only_302_navigation(self):
        b = (SPEC / "3.05" / "a15_nav_beidou.rnx").read_bytes()
        b = b.replace(b"     3.05           NAVIGATION DATA", b"     3.02           NAVIGATION DATA", 1)
        b = b.replace(b" " * 60 + b"END OF HEADER",
                      b"     4     4  1000     3".ljust(60) + b"LEAP SECONDS\n" + b" " * 60 + b"END OF HEADER", 1)
        self.assertEqual(V.errors(V.validate(b)), [])
        want = {"3.02": "     4     4  1000     3", "3.04": "     4     4  1000     3BDS",
                "3.05": "     4     4  1000     3BDT", "4.02": "    18    18  2356     4GPS"}
        for t, line in want.items():
            with self.subTest(target=t):
                outs = convert_data(b, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                got = [l[:60].rstrip() for l in outs[0].data.decode().split("\n") if l.endswith("LEAP SECONDS")]
                self.assertEqual(got, [line])
                self.assertEqual(compare_nav(b, [o.data for o in outs], rep), [])
                basis = [a for a in rep["assumptions"] if a["category"] == "leap-seconds-basis"]
                self.assertEqual(len(basis), 0 if t == "3.02" else 1)
                if basis:
                    rep2 = dict(rep, assumptions=[a for a in rep["assumptions"] if a not in basis])
                    self.assertTrue(compare_nav(b, [o.data for o in outs], rep2))


class NavRefusalsJustified(unittest.TestCase):
    """Sol round 24, 3: the nav cutter accepted a refusal by its wording; it now requires that
    no input has a system the target's navigation files hold."""

    def test_systems(self):
        from tests.unit.test_generated import nav_systems, nav_target_systems
        gps = (SPEC / "3.05" / "a7_nav_gps.rnx").read_bytes()
        self.assertEqual(nav_systems(gps), {"G"})
        for t in ("2.10", "3.00", "4.02"):
            self.assertIn("G", nav_target_systems(t))          # a refusal of it would fail
        bds = (SPEC / "3.05" / "a15_nav_beidou.rnx").read_bytes()
        self.assertFalse(nav_systems(bds) & nav_target_systems("3.01"))   # C from 3.02


if __name__ == "__main__":
    unittest.main()
