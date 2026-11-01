"""Regression tests for the second review round (docs/DECISIONS.md, "review round 2 fixes").

Each input is written by hand from rinex305.txt Tables A2/A3 and checked by our validator
first, so a failure here is the converter's, not the fixture's.
"""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.errors import CorruptError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs

from .test_obs_fixtures import F, hdr, lines

HEAD = [
    hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
    hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
    hdr("TEST", "MARKER NAME"),
    hdr("GEODETIC", "MARKER TYPE"),
    hdr("OBSERVER            AGENCY", "OBSERVER / AGENCY"),
    hdr("1                   TESTRCV             1.0", "REC # / TYPE / VERS"),
    hdr("1                   TESTANT         NONE", "ANT # / TYPE"),
    hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ"),
    hdr("        0.0000        0.0000        0.0000", "ANTENNA: DELTA H/E/N"),
]
TAIL = [
    hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
    hdr("", "END OF HEADER"),
]


def obs_file(types, extra_header, body):
    return lines(*HEAD, hdr(types, "SYS / # / OBS TYPES"), *extra_header, *TAIL, *body, width=None)


class StableStateKeys(unittest.TestCase):
    """Sol round 2: states were indexed by id() of objects that streaming re-parses."""

    SRC = obs_file("G    2 C1C L1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
        "> 2026 10 01 00 00  0.0000000  0  1",
        ("G05" + F("  22000000.105") + F(" 115000000.405")).rstrip(),
        "> 2026 10 01 00 00 15.0000000  4  1",
        hdr("G    3 C1C L1C S1C", "SYS / # / OBS TYPES"),
        "> 2026 10 01 00 00 30.0000000  0  1",
        ("G05" + F("  22000100.105") + F(" 115000500.405") + F("        45.250")).rstrip(),
    ])

    def test_fixture_is_valid(self):
        self.assertEqual([(f.rule, f.message) for f in V.errors(V.validate(self.SRC))], [])

    def test_flag4_type_change_converts(self):
        for t in ("3.05", "4.02", "3.03", "2.11"):
            with self.subTest(target=t):
                outs = convert_data(self.SRC, "TEST00XXX_R_20262740000_01D_30S_GO.rnx",
                                    Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(rep["outcome"], "converted")
                self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
        self.assertEqual(convert_data(self.SRC, "x.rnx", Options("3.05", compression="none"))[0].data,
                         self.SRC)


class ScaleFactorEvents(unittest.TestCase):
    """An event that sets one code's factor keeps the other codes' factors."""

    SRC = obs_file("G    3 C1C L1C L2W", [
        hdr("G   10  1 L1C", "SYS / SCALE FACTOR"),
        hdr("G   10  1 L2W", "SYS / SCALE FACTOR"),
        hdr("G L1C", "SYS / PHASE SHIFT"),
        hdr("G L2W", "SYS / PHASE SHIFT"),
    ], [
        "> 2026 10 01 00 00  0.0000000  0  1",
        "G05" + F("  22000000.105") + F("1150000004.050") + F(" 890000005.050"),
        "> 2026 10 01 00 00 15.0000000  4  1",
        hdr("G  100  1 L2W", "SYS / SCALE FACTOR"),
        "> 2026 10 01 00 00 30.0000000  0  1",
        "G05" + F("  22000100.105") + F("1150005004.050") + F("8900004005.000"),
    ])

    def test_fixture_is_valid(self):
        self.assertEqual([(f.rule, f.message) for f in V.errors(V.validate(self.SRC))], [])

    def test_v2_values_divided_by_their_own_factor(self):
        out = convert_data(self.SRC, "x.rnx", Options("2.11", compression="none"))[0].data.decode()
        data = out.split("END OF HEADER")[1]
        self.assertIn(" 115000500.405", data)    # L1C still / 10 after the event
        self.assertIn("  89000040.050", data)    # L2W now / 100
        self.assertIn("  89000000.505", data)    # first epoch: L2W / 10


class PseudoAndBlankCodes(unittest.TestCase):
    def test_channel_pseudo_obs_kept_305_to_402(self):
        src = obs_file("G    2 C1C X1 ", [hdr("G", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F("         5.000"),
        ])
        outs = convert_data(src, "x.rnx", Options("4.02", compression="none"))
        rep = outs[0].report.to_dict()
        self.assertNotIn("obs-code-not-representable:G:X1 ", rep["losses"])
        self.assertIn(b"G    2 C1C X1 ", outs[0].data)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_blank_attribute_kept_300_to_301(self):
        src = lines(
            hdr("     3.00           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
            *HEAD[1:],
            hdr("G    2 C1  L1 ", "SYS / # / OBS TYPES"), *TAIL,
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F(" 115000000.405"), width=None)
        outs = convert_data(src, "x.rnx", Options("3.01", compression="none"))
        rep = outs[0].report.to_dict()
        self.assertEqual([k for k in rep["losses"] if k.startswith("obs-code")], [])
        self.assertIn(b"G    2 C1  L1 ", outs[0].data)


class ValidatorGate(unittest.TestCase):
    def test_strict_refuses_invalid_input(self):
        bad = lines(*[h for h in HEAD if "OBSERVER / AGENCY" not in h],
                    hdr("G    1 C1C", "SYS / # / OBS TYPES"), hdr("G", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"), width=None)
        self.assertTrue(V.errors(V.validate(bad)))
        convert_data(bad, "x.rnx", Options("3.05", compression="none"))      # inherited: carried
        with self.assertRaises(CorruptError):
            convert_data(bad, "x.rnx", Options("3.05", compression="none", strict=True))

    def test_new_violation_of_an_inherited_rule_is_caught(self):
        """The input breaks VAL.HDR.MANDATORY for one record; an output that loses another
        mandatory record must still fail the gate (rule-level matching let it through)."""
        from rinexconv import engine
        from rinexconv.report import Report
        bad = lines(*[h for h in HEAD if "OBSERVER / AGENCY" not in h],
                    hdr("G    1 C1C", "SYS / # / OBS TYPES"), hdr("G", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"), width=None)
        ld = engine.load_bytes(bad)
        broken = b"".join(x + b"\n" for x in bad.split(b"\n")[:-1] if b"ANT # / TYPE" not in x)
        with self.assertRaises(AssertionError):
            engine._validate(broken, ld, Report())


class ComparatorExactCodes(unittest.TestCase):
    def test_swapped_attribute_detected_v3_v3(self):
        src = StableStateKeys.SRC
        outs = convert_data(src, "x.rnx", Options("3.04", compression="none"))
        rep = outs[0].report.to_dict()
        good = outs[0].data
        self.assertEqual(compare_obs(src, good, rep), [])
        bad = good.replace(b"C1C L1C", b"C1C L1X")
        self.assertTrue(compare_obs(src, bad, rep))


class NavCorrectionCapability(unittest.TestCase):
    def test_representable_correction_claimed_lost_is_rejected(self):
        rep = {"file_kind": "nav", "source_version": "4.02", "target_version": "3.05",
               "losses": {"nav-correction-not-representable:STO:GPUT": {"count": 1}}}
        self.assertEqual(allowed_check(rep), ["nav-correction-not-representable:STO:GPUT"])
        rep["losses"] = {"nav-correction-not-representable:STO:IRUT": {"count": 1}}
        rep["target_version"] = "3.02"           # IRUT has a 3.x form only from 3.03
        self.assertEqual(allowed_check(rep), [])


class GlonassLine5(unittest.TestCase):
    def test_unclaimed_line5_drop_detected(self):
        """A 3.05 GLONASS record with real line-5 values (rinex305.txt Table A10) loses them in
        3.04: the comparator must see a report that does not claim it."""
        from .test_nav_fixtures import GLO_304
        glo = GLO_304.replace(b"     3.04 ", b"     3.05 ") + (
            b"     1.700000000000D+01 1.396983861923D-09 2.000000000000D+00 0.000000000000D+00\n")
        self.assertEqual([(f.rule, f.message) for f in V.errors(V.validate(glo))], [])
        outs = convert_data(glo, "x.rnx", Options("3.04", compression="none"))
        rep = outs[0].report.to_dict()
        self.assertEqual(rep["losses"]["glonass-nav-line5-dropped"]["count"], 1)
        self.assertEqual(compare_nav(glo, [o.data for o in outs], rep), [])
        rep["losses"] = {k: v for k, v in rep["losses"].items() if k != "glonass-nav-line5-dropped"}
        self.assertTrue(compare_nav(glo, [o.data for o in outs], rep))


class PgmStamp(unittest.TestCase):
    def test_one_stamp_per_input(self):
        import os
        from .test_nav_fixtures import L, hdr as nhdr, SPEC_305, GLO_304
        mixed = L(
            nhdr("     3.04           N: GNSS NAV DATA    M: Mixed", "RINEX VERSION / TYPE"),
            nhdr("", "END OF HEADER"),
            *[l.replace("G06 1999", "G06 2026") for l in SPEC_305.decode().split("\n")[8:16]],
            *GLO_304.decode().split("\n")[4:8])
        old = os.environ.pop("SOURCE_DATE_EPOCH", None)
        try:
            outs = convert_data(mixed, "MIX.rnx", Options("2.11", compression="none"))
            stamps = {[l for l in o.data.decode().split("\n") if "PGM / RUN BY / DATE" in l][0][40:60]
                      for o in outs}
            self.assertEqual(len(outs), 2)
            self.assertEqual(len(stamps), 1)
            os.environ["SOURCE_DATE_EPOCH"] = "1793404800"      # 2026-10-31 00:00:00 UTC
            outs = convert_data(mixed, "MIX.rnx", Options("2.11", compression="none"))
            self.assertIn(b"20261031 000000 UTC", outs[0].data)
        finally:
            os.environ.pop("SOURCE_DATE_EPOCH", None)
            if old is not None:
                os.environ["SOURCE_DATE_EPOCH"] = old


if __name__ == "__main__":
    unittest.main()
