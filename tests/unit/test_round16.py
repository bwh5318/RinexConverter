"""Regression tests for review round 16 (2026-10-31/11-01, docs/DECISIONS.md "review round 16
fixes"): Sol's four blockers, from the reviewer's reproductions."""

import os
import tempfile
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_met, compare_nav, compare_obs

from .test_independent_meta import SPEC
from .test_obs_fixtures import V211, hdr
from .test_round13 import Exact
from .test_validate import nav_v4, payload


def convert(src, t, **kw):
    outs = convert_data(src, "x.rnx", Options(t, compression="none", **kw))
    return outs, outs[0].report.to_dict()


def leap_line(outs):
    return next((l for o in outs for l in o.data.decode().split("END OF HEADER")[0].splitlines()
                 if l[60:].strip() == "LEAP SECONDS"), None)


class BeiDouLeapSeconds(Exact, unittest.TestCase):
    """Sol 1: a 3.05 LEAP SECONDS in BDT (leap seconds since 2006, BDS week, day 0-6:
    rinex305.txt Table A5) went to 4.02, which allows only GPS (rinex_4.02.txt Table A7), and to
    2.11, whose I6 is GPS-UTC, unchanged. BDT is 14 s behind GPS and BDT week 0 is GPS week 1356
    (rinex_4.02.txt l.871, l.943)."""

    BDT = hdr("     4     4  1000     3BDT", "LEAP SECONDS")

    def nav(self):
        b = (SPEC / "3.05" / "a15_nav_beidou.rnx").read_bytes()
        return b.replace(b"                                                            END OF HEADER",
                         self.BDT.encode() + b"\n" + b" " * 60 + b"END OF HEADER", 1)

    def test_nav(self):
        src = self.nav()
        self.assertEqual(V.errors(V.validate(src)), [])
        # a BeiDou-only 3.02 output counts from 2006 (rinex302.txt Table A5 p.63; round 26:
        # was written in GPS terms, which a reader takes for BDS)
        want = {"4.02": "    18    18  2356     4GPS", "3.02": "     4     4  1000     3",
                # 3.03 spells BeiDou 'BDS' (rinex303.txt Table A2 p.60; round 24: was 'BDT')
                "3.05": "     4     4  1000     3BDT", "3.03": "     4     4  1000     3BDS"}
        for t, line in want.items():
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertEqual(leap_line(outs)[:60].rstrip(), line)
                for o in outs:
                    self.assertEqual(V.errors(V.validate(o.data)), [], o.name)
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_mixed_to_rinex2(self):
        # RINEX 2's LEAP SECONDS (I6) is GPS-UTC: a mixed file's BDT 4 is 18 there (Sol: was 4)
        b = (SPEC / "3.05" / "a11_nav_mixed.rnx").read_bytes()
        lines = [l for l in b.splitlines(True) if not l.rstrip().endswith(b"LEAP SECONDS")]
        i = next(k for k, l in enumerate(lines) if l.rstrip().endswith(b"END OF HEADER"))
        src = b"".join(lines[:i] + [self.BDT.encode() + b"\n"] + lines[i:])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        self.assertEqual(leap_line(outs)[:6], "    18")
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_checker_catches_the_old_copy(self):
        src = self.nav()
        outs, rep = convert(src, "4.02")
        bad = outs[0].data.replace(b"    18    18  2356     4GPS", b"     4     4  1000     3BDT")
        self.assertTrue(compare_nav(src, [bad], rep))
        self.assertIn("VAL.HDR.LEAP.SYSTEM", [f.rule for f in V.errors(V.validate(bad))])

    def test_obs(self):
        from .test_round12 import v3x
        from .test_obs_fixtures import F
        src = v3x("3.05", hdr("C    2 C2I L2I", "SYS / # / OBS TYPES"), hdr("C L2I", "SYS / PHASE SHIFT"),
                  self.BDT, body=["> 2026 10 01 00 00  0.0000000  0  1", "C11" + F("  23000000.105") + F(" 120000000.405")])
        src = src.replace(b"G (GPS)", b"C (BDS)")
        self.assertEqual(V.errors(V.validate(src)), [])
        for t, line in (("4.02", "    18    18  2356     4GPS"), ("3.05", "     4     4  1000     3BDT")):
            with self.subTest(target=t):
                outs, rep = convert(src, t, assume_phase_aligned=True)
                self.assertEqual(leap_line(outs)[:60].rstrip(), line)
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


def merge(primary, *others, target="4.02"):
    paths = []
    try:
        for data in others:
            fd, p = tempfile.mkstemp(suffix=".rnx")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            paths.append(p)
        outs = convert_data(primary, "x.rnx", Options(target, compression="none", merge=paths))
        return outs, outs[0].report.to_dict()
    finally:
        for p in paths:
            os.unlink(p)


class MergedHeaderRecords(unittest.TestCase):
    """Sol 2: --merge kept the other inputs' COMMENT lines only; their DOI, LICENSE OF USE and
    STATION INFORMATION went unreported (rinex_4.02.txt Table A7: DOI one record, the others
    'Line(s)')."""

    def nav(self, doi, lic, sta):
        b = nav_v4("4.02")
        b[2:2] = [hdr(doi, "DOI"), hdr(lic, "LICENSE OF USE"), hdr(sta, "STATION INFORMATION")]
        return payload(b)

    def test_kept_or_claimed(self):
        one = self.nav("https://doi.org/10.1/one", "CC BY 4.0", "https://example.org/one")
        two = self.nav("https://doi.org/10.1/two", "CC BY 4.0", "https://example.org/two")
        outs, rep = merge(one, two)
        head = outs[0].data.decode().split("END OF HEADER")[0]
        self.assertEqual(head.count("LICENSE OF USE"), 1)                 # the same line once
        self.assertEqual(head.count("STATION INFORMATION"), 2)            # both inputs' lines
        self.assertIn("https://example.org/two", head)
        self.assertEqual(head.count("DOI"), 1)
        self.assertEqual(rep["losses"]["merge-header-record-dropped:DOI"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        outs, rep = merge(one, two, target="3.05")
        for lab, n in (("DOI", 2), ("LICENSE OF USE", 2), ("STATION INFORMATION", 2)):
            self.assertEqual(rep["losses"][f"header-record-not-representable:{lab}"]["count"], n)
        self.assertEqual(allowed_check(rep), [])


class GalileoPlaceholder(unittest.TestCase):
    """Sol 3: the fourth GAL parameter is 'zero' in 3.00-3.02 (rinex302.txt l.3289), a
    placeholder, not disturbance flags; to RINEX 4 it became flags 0 without the assumption a
    blank one gets."""

    def test_assumption(self):
        src = (SPEC / "3.05" / "a9_nav_galileo.rnx").read_bytes().replace(b"     3.05      ", b"     3.02      ", 1)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "4.02")
        got = [(a["detail"], a["source"]) for a in rep["assumptions"] if a["category"] == "ion-galileo-disturbance-flags"]
        self.assertEqual(got, [("0", "default:zero-placeholder-in-v3.00-3.02")])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        bad = dict(rep, assumptions=[a for a in rep["assumptions"] if a["category"] != "ion-galileo-disturbance-flags"])
        self.assertTrue(compare_nav(src, [o.data for o in outs], bad))     # was: accepted


class ForeignRecordsSameVersion(Exact, unittest.TestCase):
    """Sol 4: a SYS / SCALE FACTOR in a 2.11 file (a record 2.11 does not define) vanished in a
    2.11 -> 2.11 conversion, reported as 'applied' while the values were not divided; a 3.05 met
    LICENSE OF USE was claimed, a loss the table refuses for a same-version conversion. Such
    records are now carried as written to the file's own version; interpreted ones (scale
    factors, phase shifts, GLONASS records) are never interpreted, and claimed elsewhere."""

    FOREIGN = [hdr("G   10  1 L1", "SYS / SCALE FACTOR"), hdr("G L1C  0.25000", "SYS / PHASE SHIFT"),
               hdr(" C1C    0.250 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS")]

    def src(self):
        return V211.replace(b"                                                            END OF HEADER",
                            b"".join(x.encode() + b"\n" for x in self.FOREIGN) + b" " * 60 + b"END OF HEADER", 1)

    def test_obs(self):
        src = self.src()
        fd, fcn = tempfile.mkstemp(suffix=".txt")            # R07's channel, for 3.02+ targets
        with os.fdopen(fd, "w") as fh:
            fh.write("R07  1\n")
        self.addCleanup(os.unlink, fcn)
        for t in ("2.11", "2.10", "3.05", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t, assume_phase_aligned=True, glo_fcn=fcn)
                head = outs[0].data.decode().split("END OF HEADER")[0]
                if t == "2.11":
                    for x in self.FOREIGN:
                        self.assertIn(x, head)
                    self.assertEqual(rep["losses"], {})
                else:
                    self.assertEqual({k: v["count"] for k, v in rep["losses"].items() if "foreign" in k},
                                     {"header-record-foreign-dropped:SYS / SCALE FACTOR": 1,
                                      "header-record-foreign-dropped:SYS / PHASE SHIFT": 1,
                                      "header-record-foreign-dropped:GLONASS COD/PHS/BIS": 1})
                    self.assertNotIn("0.25000", head)               # never interpreted
                self.assertNotIn("OBS.V3V2.SCALE-APPLIED", rep["rules"])
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_met(self):
        src = (SPEC / "3.05" / "a22_met.rnx").read_bytes().replace(
            b"EXAMPLE OF A MET DATA FILE                                  COMMENT\n",
            b"EXAMPLE OF A MET DATA FILE                                  COMMENT\n"
            + hdr("CC BY 4.0", "LICENSE OF USE").encode() + b"\n", 1)
        outs, rep = convert(src, "3.05")
        self.assertIn(hdr("CC BY 4.0", "LICENSE OF USE"), outs[0].data.decode())
        self.assertEqual(rep["losses"], {})
        self.assertEqual(compare_met(src, outs[0].data, rep), [])
        outs, rep = convert(src, "3.04")
        self.assertEqual(rep["losses"]["header-record-not-representable:LICENSE OF USE"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_met(src, outs[0].data, rep), [])


if __name__ == "__main__":
    unittest.main()


class MergedLeapSeconds(Exact, unittest.TestCase):
    """Sol round 17: --merge ignored the other inputs' LEAP SECONDS (a second input's '18 18 1929
    7 GPS' vanished when the first had none, or only the current count), and the checker saw
    the first input alone, so a merge claim of any count passed."""

    def nav(self, leap, sat="G06"):
        from .test_nav_fixtures import SPEC_305
        lines = [l for l in SPEC_305.splitlines(True) if not l.rstrip().endswith(b"LEAP SECONDS")]
        if leap is not None:
            i = next(k for k, l in enumerate(lines) if l.rstrip().endswith(b"END OF HEADER"))
            lines.insert(i, hdr(leap, "LEAP SECONDS").encode() + b"\n")
        return b"".join(lines).replace(b"G06 1999 09 02", sat.encode() + b" 1999 09 02")

    def check(self, first, second, t, want, claims):
        one, two = self.nav(first), self.nav(second, "G07")
        outs, rep = merge(one, two, target=t)
        self.assertEqual((leap_line(outs) or "")[:60].rstrip(), want)
        got = {k: v["count"] for k, v in rep["losses"].items() if "LEAP" in k}
        self.assertEqual(got, claims)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(one, [o.data for o in outs], r, merged=[two]), rep)

    def test_from_the_second_input(self):
        full = "    18    18  1929     7GPS"
        self.check(None, full, "3.05", full, {})
        self.check(None, full, "4.02", full, {})                # not the table's current-only 18
        self.check(None, full, "3.02", "    18    18  1929     7", {})
        self.check(None, full, "2.11", "    18", {"header-field-not-representable:LEAP SECONDS": 1})

    def test_combined(self):
        self.check("    18", "    18    18  1929     7GPS", "3.05", "    18    18  1929     7GPS", {})

    def test_conflict(self):
        self.check("    17", "    18", "3.05", "    17", {"merge-header-record-dropped:LEAP SECONDS": 1})

    def test_merge_needs_its_inputs(self):
        one, two = self.nav("    18"), self.nav("    18", "G07")
        outs, rep = merge(one, two, target="3.05")
        self.assertTrue(compare_nav(one, [o.data for o in outs], rep))           # merged= missing
        self.assertEqual(compare_nav(one, [o.data for o in outs], rep, merged=[two]), [])

    def test_header_records_counted(self):
        m = MergedHeaderRecords()
        one = m.nav("https://doi.org/10.1/one", "CC BY 4.0", "https://example.org/one")
        two = m.nav("https://doi.org/10.1/two", "CC BY 4.0", "https://example.org/two")
        for t in ("4.02", "3.05"):
            with self.subTest(target=t):
                outs, rep = merge(one, two, target=t)
                self.assert_exact(lambda r: compare_nav(one, [o.data for o in outs], r, merged=[two]), rep)


class MergedRinex4Records(Exact, unittest.TestCase):
    """Sonnet round 18: merging two 4.02 nav files, the checker paired STO records of equal
    values at different epochs out of order (a merge sorts them by epoch), a false alarm; and
    MERGED FILE kept the first input's number (rinex_4.02.txt Table A7, section 6.11: 'Number
    of files merged')."""

    def nav(self, day, merged=None):
        b = nav_v4("4.02")
        b = [l.replace("2026 10 30", f"2026 10 {day}") for l in b]
        if merged is not None:
            b.insert(2, hdr(f"{merged:9d}", "MERGED FILE"))
        return payload(b)

    def test_epoch_order_and_count(self):
        one, two = self.nav(31, merged=5), self.nav(30)            # 'two' sorts first
        for t, count in (("4.02", "        6"), ("4.00", "        6"), ("3.05", None)):
            with self.subTest(target=t):
                outs, rep = merge(one, two, target=t)
                head = outs[0].data.decode().split("END OF HEADER")[0]
                if count:
                    self.assertIn(hdr(count, "MERGED FILE"), head)
                else:
                    self.assertEqual(rep["losses"]["header-record-not-representable:MERGED FILE"]["count"], 1)
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(one, [o.data for o in outs], r, merged=[two]), rep)

    def test_real_pair(self):
        from rinexconv.engine import load_bytes
        root = os.path.join(os.path.dirname(__file__), "..", "..", "data", "corpus", "nav", "v4.02")
        a = os.path.join(root, "BRD400DLR_S_20260010000_01D_MN.rnx.gz")
        b = os.path.join(root, "BRD400DLR_S_20262740000_01D_MN.rnx.gz")
        if not (os.path.exists(a) and os.path.exists(b)):
            self.skipTest("corpus not present")
        pa, pb = (load_bytes(open(x, "rb").read()).container.payload for x in (a, b))
        outs = convert_data(open(a, "rb").read(), os.path.basename(a), Options("4.02", compression="none", merge=[b]))
        rep = outs[0].report.to_dict()
        self.assertIn(hdr("      190", "MERGED FILE"), outs[0].data.decode())     # 105 + 85
        self.assertEqual(compare_nav(pa, [o.data for o in outs], rep, merged=[pb]), [])
