"""Regression tests for review round 26 (2026-11-01, docs/DECISIONS.md "review round 26
fixes"): Sol's two blockers."""

import unittest

from rinexconv.engine import Options, convert_data
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav

from .test_independent_meta import SPEC
from .test_round16 import merge
from .test_validate import d19, nav_v4, payload

EOH = b" " * 60 + b"END OF HEADER"


def leap(data):
    return [l[:24].rstrip() for l in data.decode().split("\n") if l.endswith("LEAP SECONDS")]


class BeiDouOnly302Output(unittest.TestCase):
    """Sol 1: a 3.02 navigation file of BeiDou records only is read on the BDS basis
    (rinex302.txt Table A5 p.63; round 24), so it must be written so: two such files merged
    into 3.02 were written GPS 18, which then read as BDS 18 became 32 in 4.02."""

    def setUp(self):
        base = (SPEC / "3.05" / "a15_nav_beidou.rnx").read_bytes()
        self.b302 = base.replace(b"     3.05           NAVIGATION DATA", b"     3.02           NAVIGATION DATA",
                                 1).replace(EOH, b"     4".ljust(60) + b"LEAP SECONDS\n" + EOH, 1)
        self.b305 = base.replace(EOH, b"     4     4  1000     3BDT".ljust(60) + b"LEAP SECONDS\n" + EOH, 1)

    def test_merge_then_rinex4(self):
        outs, rep = merge(self.b302, self.b302, target="3.02")
        self.assertEqual(leap(outs[0].data), ["     4"])
        self.assertEqual(compare_nav(self.b302, [o.data for o in outs], rep, merged=[self.b302]), [])
        back = convert_data(outs[0].data, "m.rnx", Options("4.02", compression="none"))
        self.assertEqual(leap(back[0].data), ["    18"])

    def test_written_in_bds_terms(self):
        for src, want in ((self.b305, "     4     4  1000     3"), (self.b302, "     4")):
            with self.subTest(source=src[:9].decode().strip()):
                outs = convert_data(src, "x.rnx", Options("3.02", compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(leap(outs[0].data), [want])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
                back = convert_data(outs[0].data, "y.rnx", Options("4.02", compression="none"))
                self.assertEqual(leap(back[0].data)[0][:6], "    18")
        # GPS terms in a BeiDou-only 3.02 file read as GPS too since round 27 (a count of 14 or
        # more is no BDS one: navconv._leap_basis), so that form is consistent as well; a BDS
        # count written as if GPS ('4' read back as GPS 4 in a mixed file) is what stays wrong
        outs = convert_data(self.b305, "x.rnx", Options("3.02", compression="none"))
        rep = outs[0].report.to_dict()
        gps = outs[0].data.replace(b"     4     4  1000     3", b"    18    18  2356     4")
        self.assertEqual(compare_nav(self.b305, [gps], rep), [])
        bad = outs[0].data.replace(b"     4     4  1000     3", b"    32    32  3712     5")
        self.assertTrue(compare_nav(self.b305, [bad], rep))


class IonosphereSlotsEverySystem(unittest.TestCase):
    """Sol 2: the per-time-mark/SV slots of round 25 covered BeiDou only; RINEX 3.02+ headers
    may mark any system's IONOSPHERIC CORR (rinex305.txt Table A5, Note 1), so G11 at hour 00
    and G12 at hour 01 both stay; before 3.02 one set per type, the rest claimed."""

    def src(self):
        b = nav_v4("4.02")
        num = lambda *v: "".join(d19(x, "E") for x in v)
        for sat, hh, last in (("G11", "00", -5e5), ("G12", "01", -4e5)):
            b += [f"> ION {sat} LNAV", f"    2026 10 30 {hh} 00 00" + num(1e-8, 2e-8, -6e-8),
                  "    " + num(-1e-7, 9e4, 1e5, -6e4), "    " + num(last)]
        return payload(b)

    def test_kept_from_302(self):
        src = self.src()
        for t, n_sets, extra in (("3.05", 3, 0), ("3.02", 3, 0), ("3.01", 1, 2)):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                gpsa = [l for l in outs[0].data.decode().split("\n") if l.startswith("GPSA")]
                self.assertEqual(len(gpsa), n_sets)
                self.assertEqual(rep["losses"].get("nav-correction-extra:ION:KLOB:G", {"count": 0})["count"], extra)
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_marked_sets_to_301(self):
        # (found during round 27) 3.05 sets marked A/01 and B/02 were written unmarked into
        # 3.01, two GPSA/GPSB pairs a reader cannot tell apart; 3.00/3.01 have one place per type
        b = (SPEC / "3.05" / "a7_nav_gps.rnx").read_bytes()
        a1 = b"GPSA    .1676D-07   .2235D-07   .1192D-06   .1192D-06       IONOSPHERIC CORR"
        b1 = b"GPSB    .1208D+06   .1310D+06  -.1310D+06  -.1966D+06       IONOSPHERIC CORR"
        mark = lambda line, m: line[:54] + m + line[58:]
        src = b.replace(a1 + b"\n" + b1, b"\n".join(
            [mark(a1, b"A  1"), mark(b1, b"A  1"), mark(a1.replace(b".1676", b".2676"), b"B  2"),
             mark(b1.replace(b".1208", b".2208"), b"B  2")]))
        for t, n in (("3.05", 2), ("3.01", 1), ("3.00", 1)):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(outs[0].data.count(b"GPSA "), n)
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
                self.assertEqual(allowed_check(rep), [])
        # the round-26 output (both sets, unmarked) is caught
        outs = convert_data(src, "x.rnx", Options("3.01", compression="none"))
        rep = outs[0].report.to_dict()
        lines = outs[0].data.split(b"\n")
        i = next(k for k, l in enumerate(lines) if l.startswith(b"GPSB"))
        bad = b"\n".join(lines[:i + 1] + [a1.replace(b".1676", b".2676"), b1.replace(b".1208", b".2208")]
                         + lines[i + 1:])
        del rep["losses"]["nav-correction-extra:ION:KLOB:G"]
        self.assertTrue(compare_nav(src, [bad], rep))

    def test_false_extra_claim_caught(self):
        # a set left out of 3.05 although its (type, mark, SV) place is free, and claimed extra
        src = self.src()
        outs = convert_data(src, "x.rnx", Options("3.05", compression="none"))
        rep = outs[0].report.to_dict()
        lines = outs[0].data.decode().split("\n")
        bad = "\n".join(l for l in lines if not (l.startswith("GPS") and l[54:58].strip() == "B 12")).encode()
        rep["losses"]["nav-correction-extra:ION:KLOB:G"] = {"count": 1, "detail": {}}
        self.assertTrue(compare_nav(src, [bad], rep))


if __name__ == "__main__":
    unittest.main()
