"""Regression tests for review round 14 (2026-10-31, docs/DECISIONS.md "review round 14
fixes"): Sol's three blockers, each from the reviewer's reproduction."""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL
from .test_round3 import MIXED, convert
from .test_round13 import Exact
from .test_validate import nav_v4, payload


class SystemDeclaredOnlyByAnEvent(Exact, unittest.TestCase):
    """Sol 1: Galileo declared by a flag-4 event and never observed vanished from a RINEX 3/4
    output, unreported: the systems came from the data and the header's type lists only."""

    SRC = lines(MIXED, *HEAD[1:], hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("G L1C", "SYS / PHASE SHIFT"),
                *TAIL, "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405"),
                "> 2026 10 01 00 00 15.0000000  4  2", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
                hdr("E    1 C1X", "SYS / # / OBS TYPES"),
                "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405"), width=None)

    def test_kept(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        for t in ("3.04", "3.05", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(self.SRC, t, assume_phase_aligned=True)
                self.assertIn(hdr("E    1 C1X", "SYS / # / OBS TYPES"), outs[0].data.decode())   # was: gone
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assert_exact(lambda r: compare_obs(self.SRC, outs[0].data, r), rep)


def sto_file(provider):
    """nav_v4 with a GPUT record of known broadcasting satellite and transmission time, and an
    SBUT record (with an SBAS ephemeris, so RINEX 2 writes an h file)."""
    b = nav_v4("4.02")
    i = b.index("> STO G01 LNAV")
    b[i] = "> STO G13 LNAV"
    b[i + 2] = "     4.321200000000E+05 1.000000000000E-09 0.000000000000E+00 0.000000000000E+00"
    eph = ["> EPH S27 SBAS", "S27 2026 10 30 00 00 00 2.000000000000E-05 4.000000000000E-05 6.000000000000E-05",
           "     5.000000000000E-01-5.000000000000E-01-1.500000000000E+00-2.500000000000E+00",
           "     1.000000000000E+00 0.000000000000E+00-1.000000000000E+00-2.000000000000E+00",
           "     1.500000000000E+00 5.000000000000E-01-5.000000000000E-01-1.500000000000E+00"]
    sto = ["> STO S27 SBAS", f"    2026 10 30 00 00 00 SBUT               {provider:18s} {'UTC(USNO)':18s}",
           "     4.320000000000E+05 2.000000000000E-09 0.000000000000E+00 0.000000000000E+00"]
    return payload(b[:i] + eph + sto + b[i:])


class StoFieldsWithoutRoom(Exact, unittest.TestCase):
    """Sol 2 and 3. A RINEX 4 STO record's transmission time t_tm has no RINEX 2/3 field
    (rinex_4.02.txt Table A33), nor has GPS DELTA-UTC a satellite field (rinex211.txt Table
    A3): both went unclaimed. 2.11 D-UTC and RINEX 3 TIME SYSTEM CORR hold one 1X,A5,1X
    field, the SBAS provider (MT17) or else the satellite 'Snn' (rinex211.txt Table A15,
    rinex305.txt Table A5): 'A-SBAS' (six characters) ran into the UTC identifier."""

    def check(self, provider, target, want_field, want_claims):
        src = sto_file(provider)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs = convert_data(src, "x.rnx", Options(target, compression="none"))
        rep = outs[0].report.to_dict()
        text = "".join(o.data.decode() for o in outs)
        sbut = next(l for l in text.splitlines() if l.startswith(("SBUT", " 0.2")) or
                    ("D-UTC" in l and "0.2" in l))
        self.assertEqual(sbut[51:56].strip(), want_field)
        self.assertEqual(sbut[57:59], " 2")                        # UTC(USNO), in its columns
        for o in outs:
            self.assertEqual(V.errors(V.validate(o.data)), [], o.name)
        got = {k for k in rep["losses"] if k.split(":")[1:2] in (["STO-TTM"], ["STO-SAT"], ["SBAS-ID"])}
        self.assertEqual(got, {"header-field-not-representable:" + c for c in want_claims})
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_long_provider(self):
        for t in ("2.11", "3.05"):
            with self.subTest(target=t):
                self.check("A-SBAS", t, "S27", {"SBAS-ID:A-SBAS", "STO-TTM:GPUT", "STO-TTM:SBUT"}
                           | ({"STO-SAT:GPUT"} if t < "3" else set()))

    def test_provider_that_fits(self):
        for t in ("2.11", "3.05"):
            with self.subTest(target=t):
                self.check("EGNOS", t, "EGNOS", {"STO-SAT:SBUT", "STO-TTM:GPUT", "STO-TTM:SBUT"}
                           | ({"STO-SAT:GPUT"} if t < "3" else set()))

    def test_validator_catches_the_overflow(self):
        bad = ("     2.11           N: GPS NAV DATA                         RINEX VERSION / TYPE\n"
               " 0.200000000000D-08 0.000000000000D+00 432000 2442 A-SBAS  2D-UTC A0,A1,T,W,S,U\n"
               "                                                            END OF HEADER\n")
        rules = {f.rule for f in V.errors(V.validate(bad.encode()))}
        self.assertIn("VAL.HDR.SEPARATOR", rules)


class CorrectionUnderAnotherVersionsLabel(Exact, unittest.TestCase):
    """Sonnet round 15: the corpus file BOR100POL_R_20262740000_01D_SN (RINEX 3.02, cnvtToRINEX
    3.09) writes its SBUT TIME SYSTEM CORR under the RINEX 2 label CORR TO SYSTEM TIME, with
    a0 and a1 only. The header writer consumes every correction label but the RINEX 3 reader
    read only RINEX 3 ones, so the correction vanished from every output, unreported; the
    checker read labels by version too. Both now read any correction label by its own layout
    (a CORR TO SYSTEM TIME holding a time-system code as TIME SYSTEM CORR) and report it."""

    BOR = "SBUT    0.931322574615D-09 0.266453525910D-14               CORR TO SYSTEM TIME"

    def convert(self, src, t):
        outs = convert_data(src, "x.rnx", Options(t, compression="none"))
        rep = outs[0].report.to_dict()
        self.assertIn("NAV.HDR.FOREIGN-LABEL", [x["rule"] for x in rep["repairs"]])
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        return "".join(o.data.decode() for o in outs)

    def test_cnvtToRINEX_mislabel(self):
        from .test_independent_meta import SPEC
        src = (SPEC / "3.02" / "a15_nav_sbas.rnx").read_bytes().replace(
            b"SBUT  -.1331791282D-06 -.107469589D-12 552960 1025 EGNOS  5 TIME SYSTEM CORR", self.BOR.encode())
        want = {"3.02": "CORR TO SYSTEM TIME", "3.05": "TIME SYSTEM CORR", "2.11": "D-UTC A0,A1,T,W,S,U",
                "2.10": "CORR TO SYSTEM TIME", "4.02": "SBUT"}
        for t, label in want.items():
            with self.subTest(target=t):
                out = self.convert(src, t)
                self.assertIn(label, out)                       # was: no time correction at all
                self.assertTrue("0.9313225746" in out or "0.931322574615" in out)

    def test_rinex2_label_in_rinex3_and_back(self):
        from .test_nav_fixtures import SPEC_211, SPEC_305
        v3 = SPEC_305.replace(b"GPUT  0.1331791282D-06 0.107469589D-12 552960 1025        0 TIME SYSTEM CORR\n",
                              b"     .133179128170D-06  .107469588780D-12   552960     1025 DELTA-UTC: A0,A1,T,W\n")
        v2 = SPEC_211.replace(b"     .133179128170D-06  .107469588780D-12   552960     1025 DELTA-UTC: A0,A1,T,W\n",
                              b"GPUT  0.1331791282D-06 0.107469589D-12 552960 1025        0 TIME SYSTEM CORR\n")
        for src, t in ((v3, "3.05"), (v3, "2.11"), (v2, "2.11"), (v2, "3.05")):
            with self.subTest(source=src[:9].decode().strip(), target=t):
                out = self.convert(src, t)
                self.assertIn("133179128", out)                 # the GPUT a0 is there


if __name__ == "__main__":
    unittest.main()
