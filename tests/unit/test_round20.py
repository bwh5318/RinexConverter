"""Regression tests for review round 20 (2026-11-01, docs/DECISIONS.md "review round 20
fixes"): Sol's three blockers, from the reviewer's reproductions."""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.errors import NotRepresentableError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_obs

from .test_independent_meta import SPEC
from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL
from .test_round13 import Exact


def convert(src, t, **kw):
    outs = convert_data(src, "x.rnx", Options(t, compression="none", **kw))
    return outs, outs[0].report.to_dict()


def mixed(version, ctypes, pc):
    return lines(hdr(f"     {version}           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), *HEAD[1:],
                 hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr(f"C    2 {ctypes}", "SYS / # / OBS TYPES"),
                 hdr("G L1C", "SYS / PHASE SHIFT"), hdr(f"C {ctypes[4:]}", "SYS / PHASE SHIFT"),
                 hdr(pc, "ANTENNA: PHASECENTER"), *TAIL,
                 "> 2026 10 01 00 00  0.0000000  0  2", "G05" + F("  22000000.105") + F(" 115000000.405"),
                 "C11" + F("  23000000.105") + F(" 120000000.405"), width=None)


class AntennaPhaseCenterCode(Exact, unittest.TestCase):
    """Sol 1: ANTENNA: PHASECENTER names an observation code (rinex305.txt Table A2 p.53). A
    3.02 BeiDou 'C L1X' (B1I: band 1 in 3.02) went to 3.05 unchanged while the data became
    C2X/L2X, so it named B1C there."""

    PC = "C L1X   0.1234        0.0000        0.0567"

    def test_renamed_with_the_data(self):
        src = mixed("3.02", "C1X L1X", self.PC)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.05")
        head = outs[0].data.decode().split("END OF HEADER")[0]
        self.assertIn(hdr("C L2X   0.1234        0.0000        0.0567", "ANTENNA: PHASECENTER"), head)
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)
        bad = outs[0].data.replace(b"C L2X   0.1234", b"C L1X   0.1234")          # the old output
        self.assertTrue(compare_obs(src, bad, rep))

    def test_same_version_and_rinex2(self):
        src = mixed("3.02", "C1X L1X", self.PC)
        outs, rep = convert(src, "3.02")
        self.assertIn(hdr(self.PC, "ANTENNA: PHASECENTER"), outs[0].data.decode())
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        outs, rep = convert(src, "2.11", assume_phase_aligned=True)
        self.assertEqual(rep["losses"]["header-record-not-representable:ANTENNA: PHASECENTER"]["count"], 1)
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_code_with_no_room(self):
        # 3.05 band 1 is B1C (C1P): 3.02 has no B1C code (band 1 is B1I there)
        src = mixed("3.05", "C1P L1P", "C L1P   0.1234        0.0000        0.0567")
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.02")
        self.assertEqual(rep["losses"]["antenna-phasecenter-code-not-representable:C:L1P"]["count"], 1)
        self.assertNotIn("ANTENNA: PHASECENTER", outs[0].data.decode())
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


class CountsCheckedAgainstTheSource(unittest.TestCase):
    """Sol 2: PRN / # OF OBS was checked against the output's counts, so a type the target
    cannot hold (C1S to 3.00) looked like a wrong count: a false HDR.COUNTS repair, and
    --strict refused the valid file."""

    def test_no_false_repair(self):
        src = lines(*HEAD, hdr("G    2 C1C C1S", "SYS / # / OBS TYPES"), hdr("G", "SYS / PHASE SHIFT"),
                    hdr("     1", "# OF SATELLITES"), hdr("   G05     1     1", "PRN / # OF OBS"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F("  22000000.205"),
                    width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        for strict in (False, True):
            with self.subTest(strict=strict):
                outs, rep = convert(src, "3.00", strict=strict)            # was: refused under --strict
                self.assertEqual(rep["repairs"], [])
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        # a wrong count is still repaired, for every target (Sonnet round 21: to RINEX 2 it was
        # corrected unreported), and the checker requires it
        bad = src.replace(hdr("   G05     1     1", "PRN / # OF OBS").encode(), hdr("   G05     2     1", "PRN / # OF OBS").encode())
        for t in ("3.00", "2.11"):
            with self.subTest(target=t, counts="wrong"):
                outs, rep = convert(bad, t, assume_phase_aligned=True)
                self.assertIn("HDR.COUNTS", [r["rule"] for r in rep["repairs"]])
                self.assertEqual(compare_obs(bad, outs[0].data, rep), [])
                unreported = dict(rep, repairs=[r for r in rep["repairs"] if r["rule"] != "HDR.COUNTS"])
                self.assertTrue(compare_obs(bad, outs[0].data, unreported))


class MetWithNoTypeLeft(unittest.TestCase):
    """Sol 3: a 3.05 wind-only met file to 2.10 (WD exists from 2.11) lost its only type and
    failed the output check as an internal error; nothing can be written: refused."""

    def test_refused(self):
        src = (SPEC / "3.05" / "a22_met.rnx").read_bytes()
        head, sep, body = src.partition(b"END OF HEADER\n")
        out = []
        for l in head.splitlines(True):
            lab = l[60:80].strip()
            if lab == b"# / TYPES OF OBSERV":
                out.append(hdr("     1    WD", "# / TYPES OF OBSERV").encode() + b"\n")
                out.append(hdr("VAISALA             WMT52                         3.0    WD",
                               "SENSOR MOD/TYPE/ACC").encode() + b"\n")
            elif lab not in (b"SENSOR MOD/TYPE/ACC", b"SENSOR POS XYZ/H"):
                out.append(l)
        # epochs: 1X,I4,5(1X,I2) (20 columns, from 3.02: rinex305.txt Table A21), then F7.1
        data = [l[:20] + b"  270.0\n" for l in body.splitlines(True) if l.strip()]
        src = b"".join(out) + sep + b"".join(data)
        self.assertEqual(V.errors(V.validate(src)), [])
        with self.assertRaises(NotRepresentableError):
            convert_data(src, "x.rnx", Options("2.10", compression="none"))
        outs, rep = convert(src, "2.11")
        self.assertIn("WD", outs[0].data.decode())


if __name__ == "__main__":
    unittest.main()
