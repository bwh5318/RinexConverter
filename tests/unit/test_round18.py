"""Regression tests for review round 18 (2026-11-01, docs/DECISIONS.md "review round 18
fixes"): Sol's four blockers and polish, from the reviewer's reproductions."""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs

from .test_independent_meta import SPEC
from .test_nav_fixtures import SPEC_305
from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL
from .test_round3 import MIXED
from .test_round13 import Exact
from .test_round16 import merge
from .test_validate import nav_v4, payload


def convert(src, t, **kw):
    outs = convert_data(src, "x.rnx", Options(t, compression="none", **kw))
    return outs, outs[0].report.to_dict()


class BeiDouTimeObservations(Exact, unittest.TestCase):
    """Sol 1: a 3.05 mixed file in BDT went to 2.11 still tagged BDT; TIME OF FIRST OBS allows
    GPS, GLO and GAL there (rinex211.txt Table A1). BDT is 14 s behind GPS time (rinex305.txt
    l.805): every epoch is written 14 s later, in GPS time. QZS, IRN and GAL, aligned with GPS
    time, are relabelled (an assumption)."""

    def src(self, tsys):
        tail = [TAIL[0].replace("GPS", tsys)] + TAIL[1:]
        return lines(MIXED, *HEAD[1:], hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
                     hdr("C    2 C2I L2I", "SYS / # / OBS TYPES"), hdr("G L1C", "SYS / PHASE SHIFT"),
                     hdr("C L2I", "SYS / PHASE SHIFT"), *tail,
                     "> 2026 10 01 23 59 50.0000000  0  2",
                     "G05" + F("  22000000.105") + F(" 115000000.405"),
                     "C11" + F("  23000000.105") + F(" 120000000.405"), width=None).replace(
            b"  2026    10     1     0     0    0.0000000", b"  2026    10     1    23    59   50.0000000")

    def test_bdt_to_rinex2(self):
        src = self.src("BDT")
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11", assume_phase_aligned=True)
        text = outs[0].data.decode()
        self.assertIn(" 26 10  2  0  0  4.0000000  0  1G 5", text)                 # +14 s, next day
        self.assertIn("  2026    10     2     0     0    4.0000000     GPS         TIME OF FIRST OBS", text)
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)
        # the old output (BDT epochs kept) is caught
        bad = outs[0].data.replace(b" 26 10  2  0  0  4.0000000", b" 26 10  1 23 59 50.0000000")
        self.assertTrue(compare_obs(src, bad, rep))

    def test_bdt_kept_where_defined(self):
        src = self.src("BDT")
        for t in ("3.02", "3.05", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t, assume_phase_aligned=True)
                self.assertIn("> 2026 10 01 23 59 50.0000000", outs[0].data.decode())
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_bdt_to_301(self):
        src = self.src("BDT")
        outs, rep = convert(src, "3.01", assume_phase_aligned=True)
        self.assertIn("> 2026 10 02 00 00  4.0000000", outs[0].data.decode())
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_qzs_relabelled(self):
        src = self.src("QZS")
        outs, rep = convert(src, "3.01", assume_phase_aligned=True)
        self.assertIn("> 2026 10 01 23 59 50.0000000", outs[0].data.decode())      # no shift
        self.assertIn(("time-system", "QZS->GPS"), [(a["category"], a["detail"]) for a in rep["assumptions"]])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        bad = dict(rep, assumptions=[a for a in rep["assumptions"] if a["category"] != "time-system"])
        self.assertTrue(compare_obs(src, outs[0].data, bad))


class DedupeByValue(Exact, unittest.TestCase):
    """Sol 2: --dedupe compared spellings, so the same record with D and with E exponents was
    kept twice (a second pass then removed one)."""

    def test_d_and_e(self):
        one, two = payload(nav_v4("4.02")), payload(nav_v4("4.00", "D"))
        import os
        import tempfile
        fd, p = tempfile.mkstemp(suffix=".rnx")
        with os.fdopen(fd, "wb") as fh:
            fh.write(two)
        self.addCleanup(os.unlink, p)
        outs = convert_data(one, "x.rnx", Options("4.02", compression="none", merge=[p], dedupe=True))
        rep = outs[0].report.to_dict()
        self.assertEqual(outs[0].data.decode().count("> EPH G01 LNAV"), 1)
        again = convert_data(outs[0].data, "y.rnx", Options("4.02", compression="none", dedupe=True))
        self.assertNotIn("nav-duplicate-removed", again[0].report.to_dict()["losses"])  # nothing left
        self.assert_exact(lambda r: compare_nav(one, [o.data for o in outs], r, merged=[two]), rep)


class MixedVersionMerge(Exact, unittest.TestCase):
    """Sol 3: the checks took the first input's version for every record of a merge: a 3.05
    record in a 4.02-first merge was expected without a message type, and a 4.02 input's CNAV
    removal (to 3.05, 3.05 first) was refused by the loss table."""

    def test_both_orders(self):
        v4 = (SPEC / "4.02" / "a12_nav_gps.rnx").read_bytes()
        for first, second, t in ((v4, SPEC_305, "4.02"), (SPEC_305, v4, "3.05"), (SPEC_305, v4, "4.02")):
            with self.subTest(first=first[:9].decode().strip(), target=t):
                outs, rep = merge(first, second, target=t)
                if t == "3.05":
                    self.assertIn("nav-message-not-representable:G:CNAV", rep["losses"])
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(first, [o.data for o in outs], r, merged=[second]), rep)


class MergedMakersAndReceivers(Exact, unittest.TestCase):
    """Sol 4: another input's PGM / RUN BY / DATE vanished unreported (a navigation file has one:
    rinex_4.02.txt section 5.2.2); and 'merged navigation files from multiple stations are not
    to include' REC # / TYPE / VERS (Table A7 note 2)."""

    def nav(self, pgm, rec=None):
        b = nav_v4("4.02")
        b[1] = hdr(pgm, "PGM / RUN BY / DATE")
        if rec:
            b.insert(2, hdr(rec, "REC # / TYPE / VERS"))
        return payload(b)

    def test_claims(self):
        one = self.nav("TESTGEN 1.0         ONE                 20261030 120000 UTC", "1  RCV-A  1.0")
        two = self.nav("TESTGEN 2.0         TWO                 20261030 130000 UTC", "2  RCV-B  2.0")
        outs, rep = merge(one, two, target="4.02")
        head = outs[0].data.decode().split("END OF HEADER")[0]
        self.assertNotIn("REC # / TYPE / VERS", head)
        self.assertEqual(rep["losses"]["merge-header-record-dropped:PGM / RUN BY / DATE"]["count"], 1)
        self.assertEqual(rep["losses"]["merge-header-record-dropped:REC # / TYPE / VERS"]["count"], 2)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(one, [o.data for o in outs], r, merged=[two]), rep)
        same = self.nav("TESTGEN 1.0         ONE                 20261030 120000 UTC", "1  RCV-A  1.0")
        outs, rep = merge(one, same, target="4.02")
        self.assertIn("REC # / TYPE / VERS", outs[0].data.decode())         # one receiver: kept
        self.assertEqual(compare_nav(one, [o.data for o in outs], rep, merged=[same]), [])

    def test_blank_leap_seconds(self):
        # Sol polish: a blank LEAP SECONDS in the second input, none in the first: TypeError
        one = payload([l for l in nav_v4("4.02") if not l.endswith("LEAP SECONDS")])
        b = nav_v4("4.02")
        b = [hdr("", "LEAP SECONDS") if l.endswith("LEAP SECONDS") else l for l in b]
        two = payload(b)
        outs, rep = merge(one, two, target="4.02")
        self.assertIn("leap-seconds", [a["category"] for a in rep["assumptions"]])   # from the table
        self.assertEqual(compare_nav(one, [o.data for o in outs], rep, merged=[two]), [])


if __name__ == "__main__":
    unittest.main()


class SolRound19(Exact, unittest.TestCase):
    """Sol round 19: the BDT shift was reported as a TIME OF FIRST OBS repair (so --strict
    refused a valid file); and in a merge with a RINEX 3 input, the RINEX 4 STO/ION/EOP
    records were not compared (a changed EOP value passed, a removed duplicate went uncounted,
    and QZSS CNVX handling followed the first input's version)."""

    def test_bdt_strict(self):
        src = BeiDouTimeObservations.src(None, "BDT")
        outs, rep = convert(src, "2.11", assume_phase_aligned=True, strict=True)     # was: refused
        self.assertEqual(rep["repairs"], [])
        # a header that disagrees with its own data is still repaired
        bad = src.replace(b"  2026    10     1    23    59   50.0000000     BDT",
                          b"  2026    10     1    23    59   40.0000000     BDT")
        outs, rep = convert(bad, "2.11", assume_phase_aligned=True)
        self.assertIn("HDR.TIME-OF-FIRST-OBS", [r["rule"] for r in rep["repairs"]])

    def test_eop_value_checked_in_mixed_merge(self):
        v4 = payload(nav_v4("4.02"))
        outs, rep = merge(SPEC_305, v4, target="4.02")
        self.assertEqual(compare_nav(SPEC_305, [o.data for o in outs], rep, merged=[v4]), [])
        bad = outs[0].data.replace(b"2.000000000000E-01-2.600000000000E-04", b"9.900000000000E+01-2.600000000000E-04")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_nav(SPEC_305, [bad], rep, merged=[v4]))           # was: passed

    def test_three_versions_dedupe(self):
        import os
        import tempfile
        from .test_user_options import nav400
        others = [nav400(), payload(nav_v4("4.02"))]
        paths = []
        for data in others:
            fd, p = tempfile.mkstemp(suffix=".rnx")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            paths.append(p)
            self.addCleanup(os.unlink, p)
        outs = convert_data(SPEC_305, "x.rnx", Options("4.02", compression="none", merge=paths, dedupe=True,
                                                       qzss_ion_area="WIDE"))
        rep = outs[0].report.to_dict()
        self.assertGreater(rep["losses"]["nav-duplicate-removed"]["count"], 0)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(SPEC_305, [o.data for o in outs], r, merged=others), rep)

    def test_qzss_area_per_input(self):
        from .test_user_options import nav400
        v402, v400 = payload(nav_v4("4.02")), nav400()
        for area in (None, "WIDE"):
            with self.subTest(area=area):
                import os
                import tempfile
                fd, p = tempfile.mkstemp(suffix=".rnx")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(v400)
                self.addCleanup(os.unlink, p)
                outs = convert_data(v402, "x.rnx", Options("4.02", compression="none", merge=[p], qzss_ion_area=area))
                rep = outs[0].report.to_dict()
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(v402, [o.data for o in outs], r, merged=[v400]), rep)

    def test_name_follows_the_shift(self):
        # rinex211.txt section 4: DDD is the day of the first record (Sol polish: kept day 366)
        src = BeiDouTimeObservations.src(None, "BDT").replace(b"2026 10 01", b"2016 12 31").replace(
            b"  2026    10     1    23", b"  2016    12    31    23")
        for name, t, want in (("test3660.16o", "2.11", "test0010.17o"),
                              ("TEST00XXX_R_20163662359_01D_30S_MO.rnx", "3.01", "TEST00XXX_R_20170010000_01D_30S_MO.rnx"),
                              ("test3660.16o", "3.05", "TEST00XXX_R_20163660000_01D_00U_MO.rnx")):
            with self.subTest(name=name, target=t):
                outs = convert_data(src, name, Options(t, compression="none", assume_phase_aligned=True))
                self.assertEqual(outs[0].name, want)
