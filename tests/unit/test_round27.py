"""Regression tests for review round 27 (2026-11-01, docs/DECISIONS.md "review round 27
fixes"): Sol's two blockers, Sonnet's checker false alarm, and what the nav corpus rerun found
on real files."""

import unittest

from rinexconv.engine import Options, convert_data
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav

from .test_independent_meta import SPEC
from .test_validate import d19, nav_v4, payload

EOH = b" " * 60 + b"END OF HEADER"


def leap(data):
    return [l[:27].rstrip() for l in data.decode().split("\n") if l.endswith("LEAP SECONDS")]


def bds_only(version, leap_line):
    b = (SPEC / "3.05" / "a15_nav_beidou.rnx").read_bytes()
    b = b.replace(b"     3.05           NAVIGATION DATA", f"{version:>9}           NAVIGATION DATA".encode(), 1)
    return b.replace(EOH, leap_line.ljust(60).encode() + b"LEAP SECONDS\n" + EOH, 1)


class LeapWeekBefore2006(unittest.TestCase):
    """Sol 1: a past leap second's week before BDS week 0 (GPS week 1356) was blanked when a
    BeiDou-only output was written in BDS terms; I6 holds -1 and it converts back."""

    def test_negative_week(self):
        src = bds_only("3.05", "    18    14  1355     7GPS")
        outs = convert_data(src, "x.rnx", Options("3.02", compression="none"))
        rep = outs[0].report.to_dict()
        # (round 28: in BDS terms the past leap of 14 s would be 0, which reads "not known", so
        # the GPS terms stay; a count of 14 or more reads as GPS)
        self.assertEqual(leap(outs[0].data), ["    18    14  1355     7"])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        back = convert_data(outs[0].data, "y.rnx", Options("4.02", compression="none"))
        self.assertEqual(leap(back[0].data)[0][:24], "    18    14  1355     7")   # (blank id = GPS)


class BeiDouOnlyBlankIdentifier(unittest.TestCase):
    """Corpus ADIS00ETH_R_20262740000_01D_CN (3.04, BeiDou only): '4 4 573 6' with no
    identifier, in BeiDou terms ("When BDS only file leap seconds specified, weeks since
    1-Jan-2006": rinex304.txt p.65); round 26 read it as GPS and wrote '-10 -10 _ 5' to 3.02."""

    def test_read_as_bds(self):
        src = bds_only("3.04", "     4     4   573     6")
        for t, want in (("3.02", "     4     4   573     6"), ("3.05", "     4     4   573     6BDT"),
                        ("4.02", "    18    18  1929     7GPS")):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(leap(outs[0].data), [want])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


class IonosphereSetsInTheirPlaces(unittest.TestCase):
    """Sonnet round 27 (BRD400DLR 2026-001 G24) and Sol 2: sets of equal values at other
    hours, and a set with no room, were paired with output sets in other places (time mark /
    SV) and their marks called wrong; a set now pairs only within its own place. Also a GPSA
    with SV ID '01' and a GPSB with ' 1' are one set (Sol, during round 27)."""

    def test_equal_values_other_hours(self):
        b = nav_v4("4.02")
        num = lambda *v: "".join(d19(x, "E") for x in v)
        for sat, t, last in (("G24", "00 11", -5e5), ("G24", "00 23", -4e5), ("G24", "23 56", -4e5),
                             ("G03", "00 05", -3e5), ("G03", "00 20", -2e5), ("G04", "00 30", -2e5)):
            b += [f"> ION {sat} LNAV", f"    2026 10 30 {t} 00" + num(1e-8, 2e-8, -6e-8),
                  "    " + num(-1e-7, 9e4, 1e5, -6e4), "    " + num(last)]
        src = payload(b)
        for t in ("3.05", "3.02"):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(rep["losses"]["nav-correction-extra:ION:KLOB:G"]["count"], 2)
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_sv_id_padding(self):
        b = (SPEC / "3.05" / "a7_nav_gps.rnx").read_bytes()
        a1 = b"GPSA    .1676D-07   .2235D-07   .1192D-06   .1192D-06       IONOSPHERIC CORR"
        b1 = b"GPSB    .1208D+06   .1310D+06  -.1310D+06  -.1966D+06       IONOSPHERIC CORR"
        src = b.replace(a1, a1[:54] + b"A 01" + a1[58:]).replace(b1, b1[:54] + b"A  1" + b1[58:])
        outs = convert_data(src, "x.rnx", Options("4.02", compression="none"))
        rep = outs[0].report.to_dict()
        self.assertEqual(outs[0].data.count(b"> ION G"), 1)            # one complete set
        self.assertFalse([k for k in rep["losses"] if "KLOB-incomplete" in k])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


if __name__ == "__main__":
    unittest.main()
