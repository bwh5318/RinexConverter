"""Regression tests for review round 25 (2026-11-01, docs/DECISIONS.md "review round 25
fixes")."""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore.errors import CorruptError

from .test_obs_fixtures import hdr
from .test_round22 import mixed, rec


class EventChannelColumns(unittest.TestCase):
    """Sonnet round 24/25 polish, and worse: an event's GLONASS SLOT / FRQ # entry one column
    off ('R02-4') was read as channel +4 and written into the header; another ('  1R02 -4')
    ended in an internal error. Entries must sit in I3,1X,8(A1,I2.2,1X,I2,1X)."""

    def src(self, line):
        return mixed("3.05", "R", "C1C L1C", [
            hdr("  1 R01  1", "GLONASS SLOT / FRQ #"),
            hdr(" C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS")], body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("R01", 21e6, 112e6),
            "> 2026 10 01 00 00 15.0000000  4  1", hdr(line, "GLONASS SLOT / FRQ #"),
            "> 2026 10 01 00 00 30.0000000  0  1", rec("R02", 20e6 + 100, 107e6 + 500)])

    def test_refused(self):
        for line in ("  1 R02-4", " 1 R02 -4", "  1R02 -4", "  1 R02 -45"):
            with self.subTest(line=line):
                with self.assertRaises(CorruptError) as cm:
                    convert_data(self.src(line), "x.rnx", Options("3.04", compression="none"))
                self.assertEqual(cm.exception.rule, "HDR.GLOSLOT")

    def test_good_lines(self):
        for line, want in (("  1 R02 -4", "R02 -4"), ("  2 R02 -4 R03 10", "R03 10")):
            with self.subTest(line=line):
                outs = convert_data(self.src(line), "x.rnx", Options("3.04", compression="none"))
                head = outs[0].data.decode().split("END OF HEADER")[0]
                self.assertIn(want, head)


class NavRefusalsByMessage(unittest.TestCase):
    """Sonnet round 25: the nav cutter's refusal oracle was by system only; RINEX 2/3 hold an
    ephemeris only in the forms LNAV, FDMA, INAV/FNAV, D1/D2, SBAS (GPS CNAV, BeiDou CNV2 have
    none), and RINEX 4.00/4.01 not GLONASS L1OC/L3OC nor NavIC L1NV."""

    def test_holds(self):
        from tests.unit.test_generated import nav_holds
        self.assertTrue(nav_holds("2.11", "G", "LNAV"))
        self.assertFalse(nav_holds("2.11", "G", "CNAV"))
        self.assertFalse(nav_holds("3.05", "C", "CNV2"))
        self.assertTrue(nav_holds("3.05", "C", "D1"))
        self.assertFalse(nav_holds("3.01", "C", "D1"))         # BeiDou nav from 3.02
        self.assertFalse(nav_holds("4.01", "R", "L1OC"))
        self.assertTrue(nav_holds("4.02", "R", "L1OC"))
        self.assertFalse(nav_holds("3.05", "G", "CNAV"))       # Sol round 25: CNAV-only cuts


class BeiDouIonosphereSlots(unittest.TestCase):
    """Sol round 25, 2: RINEX 4 to 3 kept one BeiDou Klobuchar set; a 3.02+ header holds one
    per time mark and SV, which BDS must give (rinex305.txt Table A5 p.65-66): C11 at hour 00
    and C12 at hour 01 are both kept."""

    def test_both_kept(self):
        from tests.independent.allowed import check as allowed_check
        from tests.independent.compare import compare_nav
        from .test_validate import d19, nav_v4, payload
        b = nav_v4("4.02")
        num = lambda *v: "".join(d19(x, "E") for x in v)
        for sat, hh, last in (("C11", "00", -5e5), ("C12", "01", -4e5)):
            b += [f"> ION {sat} D1D2", f"    2026 10 30 {hh} 00 00" + num(1e-8, 2e-8, -6e-8),
                  "    " + num(-1e-7, 9e4, 1e5, -6e4), "    " + num(last)]
        src = payload(b)
        for t in ("3.05", "3.02"):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                bds = [l for l in outs[0].data.decode().split("\n") if l.startswith("BDS")]
                self.assertEqual([l[54:59].strip() for l in bds], ["A 11", "A 11", "B 12", "B 12"])
                self.assertFalse([k for k in rep["losses"] if k.startswith("nav-correction-extra")])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


class MergedLeapBases(unittest.TestCase):
    """Sol round 25, 1: a BeiDou-only 3.02 file's leap count (since 2006) merged with a GPS
    one: written as GPS 4 when BeiDou came first, a false 'conflict' the other way round. Each
    input is now read in its own terms and the merged record written in GPS terms."""

    def test_both_orders(self):
        from tests.independent.allowed import check as allowed_check
        from tests.independent.compare import compare_nav
        from .test_independent_meta import SPEC
        from .test_round16 import merge
        bds = (SPEC / "3.05" / "a15_nav_beidou.rnx").read_bytes()
        bds = bds.replace(b"     3.05           NAVIGATION DATA", b"     3.02           NAVIGATION DATA", 1)
        bds = bds.replace(b" " * 60 + b"END OF HEADER",
                          b"     4".ljust(60) + b"LEAP SECONDS\n" + b" " * 60 + b"END OF HEADER", 1)
        gps = (SPEC / "3.05" / "a7_nav_gps.rnx").read_bytes().replace(
            b"    13                                                      LEAP SECONDS",
            b"    18                                                      LEAP SECONDS").replace(
            b"     3.05           N: GNSS NAV DATA", b"     3.02           N: GNSS NAV DATA", 1)
        for one, two in ((bds, gps), (gps, bds)):
            for t in ("3.02", "3.05", "4.02"):
                with self.subTest(first=one[:200].decode().split("\n")[0][40:60], target=t):
                    outs, rep = merge(one, two, target=t)
                    lp = [l[:6] for l in outs[0].data.decode().split("\n") if l.endswith("LEAP SECONDS")]
                    self.assertEqual(lp, ["    18"])
                    self.assertNotIn("merge-header-record-dropped:LEAP SECONDS", rep["losses"])
                    self.assertIn("leap-seconds-basis", [a["category"] for a in rep["assumptions"]])
                    self.assertEqual(allowed_check(rep), [])
                    self.assertEqual(compare_nav(one, [o.data for o in outs], rep, merged=[two]), [])


if __name__ == "__main__":
    unittest.main()
