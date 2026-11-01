"""Regression tests for review round 28 (2026-11-01, docs/DECISIONS.md "review round 28
fixes"): Sol's blocker (unknown leap fields) and Sonnet's checker hole (subtype claims)."""

import copy
import unittest

from rinexconv.engine import Options, convert_data
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav

from .test_independent_meta import SPEC
from .test_round16 import merge
from .test_validate import payload

EOH = b" " * 60 + b"END OF HEADER"


def leap(data):
    return [l[:27].rstrip() for l in data.decode().split("\n") if l.endswith("LEAP SECONDS")]


def bds_only(version, line):
    b = (SPEC / "3.05" / "a15_nav_beidou.rnx").read_bytes()
    b = b.replace(b"     3.05           NAVIGATION DATA", f"{version:>9}           NAVIGATION DATA".encode(), 1)
    return b.replace(EOH, line.ljust(60).encode() + b"LEAP SECONDS\n" + EOH, 1)


class UnknownLeapFields(unittest.TestCase):
    """Sol: "Zero or blank if not known" (rinex302.txt Table A5 p.63): a BeiDou-only '0' became
    GPS 14, '4 0 0 0' became '18 14 1356 1GPS' (an invented leap-event date), and an unknown
    '0' merged first overrode a GPS 18 and claimed it lost."""

    def test_zero_count(self):
        src = bds_only("3.02", "     0")
        for t in ("4.02", "3.05"):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(leap(outs[0].data)[0][:6], "     0")
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_unknown_event(self):
        src = bds_only("3.02", "     4     0     0     0")
        outs = convert_data(src, "x.rnx", Options("4.02", compression="none"))
        rep = outs[0].report.to_dict()
        self.assertEqual(leap(outs[0].data), ["    18     0     0     0GPS"])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        bad = outs[0].data.replace(b"    18     0     0     0GPS", b"    18    14  1356     1GPS")
        self.assertTrue(compare_nav(src, [bad], rep))

    def test_merge_unknown_first(self):
        unknown = bds_only("3.02", "     0")
        gps = (SPEC / "3.05" / "a7_nav_gps.rnx").read_bytes().replace(
            b"    13                                                      LEAP SECONDS",
            b"    18                                                      LEAP SECONDS")
        for one, two in ((unknown, gps), (gps, unknown)):
            with self.subTest(first=one[60:80].decode().strip() or one[:20].decode()):
                outs, rep = merge(one, two, target="3.05")
                self.assertEqual([x[:6] for x in leap(outs[0].data)], ["    18"])
                self.assertNotIn("merge-header-record-dropped:LEAP SECONDS", rep["losses"])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(one, [o.data for o in outs], rep, merged=[two]), [])


class SubtypeClaimsExact(unittest.TestCase):
    """Sonnet round 28: from 3.02 several QZSS sets are kept (one per time mark and SV), and
    deleting one of the J:LNAV / J:CNVX subtype claims passed (BRD400DLR 2026-001): the claims
    are now counted per (system, message) from the input record each kept set came from."""

    def test_each_claim_counted(self):
        from .test_validate import nav_v4
        body = []
        for msg, area, t, a in (("LNAV", "WIDE", "02 01 54", "1.955777406693E-08"),
                                ("CNVX", "WIDE", "05 01 12", "1.955777406693E-08"),
                                ("LNAV", "JAPN", "00 04 00", "2.887099981308E-08")):
            body += [f"> ION J02 {msg} {area}",
                     f"    2026 10 01 {t} {a}-1.415610313416E-07-2.622604370117E-06",
                     "    -7.629394531250E-06 9.216000000000E+04 9.830400000000E+04 2.424832000000E+06",
                     "     8.323072000000E+06"]
        src = payload(nav_v4("4.02")[:-4] + body)
        outs = convert_data(src, "x.rnx", Options("3.05", compression="none"))
        rep = outs[0].report.to_dict()
        claims = {k: e["count"] for k, e in rep["losses"].items() if "subtype" in k}
        self.assertEqual(claims, {"nav-subtype-not-representable:ION:J:LNAV": 2,
                                  "nav-subtype-not-representable:ION:J:CNVX": 1})
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        for k in claims:
            for how in ("del", "plus"):
                with self.subTest(claim=k, mutation=how):
                    bad = copy.deepcopy(rep)
                    if how == "del":
                        del bad["losses"][k]
                    else:
                        bad["losses"][k]["count"] += 1
                    self.assertTrue(compare_nav(src, [o.data for o in outs], bad))


if __name__ == "__main__":
    unittest.main()
