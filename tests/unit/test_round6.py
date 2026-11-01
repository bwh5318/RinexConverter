"""Regression tests for review round 6 (2026-10-31, docs/DECISIONS.md "review round 6 fixes"):
Sonnet's checker false alarm and Sol's five blockers, each from the reviewer's reproduction."""

import copy
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.errors import CorruptError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL, obs_file
from .test_round3 import convert, head_lines
from .test_validate import nav_v4, payload

SCALED = [hdr("G   10  1 D1C", "SYS / SCALE FACTOR"), hdr("G", "SYS / PHASE SHIFT")]


class CycleSlipOnlySatellite(unittest.TestCase):
    """Sol 1: a satellite seen only in flag-6 records is in the data, so in # OF SATELLITES
    and PRN / # OF OBS (with no flag 0/1 counts)."""

    SRC = obs_file("G    2 C1C L1C", [hdr("G", "SYS / PHASE SHIFT"), hdr("     1", "# OF SATELLITES"),
                                      hdr("   G05     1     1", "PRN / # OF OBS")], [
        "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405"),
        "> 2026 10 01 00 00  0.0000000  6  1", "G06" + F("  21000000.105", "1") + F(" 110000000.405", "1")])

    def test_converts(self):
        for t in ("2.11", "3.05", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(self.SRC, t, assume_phase_aligned=True)     # was: AssertionError
                head = head_lines(outs[0].data)
                self.assertIn(hdr("     2", "# OF SATELLITES"), head)
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])


class CompactAfterScaling(unittest.TestCase):
    """Sol 2: a scaled value that rounds to 0.000 is blank; Compact RINEX 1.0 cannot hold its
    SSI, so the flag goes too (claimed), after scaling, not before."""

    def test_crx_211(self):
        src = obs_file("G    2 C1C D1C", SCALED, [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F("         0.001", " ", "7")])
        outs = convert_data(src, "x.rnx", Options("2.11", compression="none", crx=True))   # was CRX.ENC.FLAG2
        rep = outs[0].report.to_dict()
        self.assertEqual(rep["losses"]["flags-on-missing-value-dropped"]["count"], 1)
        self.assertEqual(rep["losses"]["scale-factor-rounding:G:D1C"]["count"], 1)


class DamageInScaledField(unittest.TestCase):
    """Sol 3: '12.3.4' in a scaled field raised decimal.InvalidOperation at load."""

    SRC = obs_file("G    2 C1C D1C", SCALED, [
        "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F("        12.3.4")])

    def test_refused_not_crashed(self):
        with self.assertRaises(CorruptError) as cm:
            convert(self.SRC, "2.11")
        self.assertEqual(cm.exception.rule, "VAL.OBS.DATA.FIELD")
        with self.assertRaises(CorruptError) as cm:          # --lenient cannot divide it either
            convert(self.SRC, "2.11", lenient=True)
        self.assertEqual(cm.exception.rule, "OBS.DATA.SCALE")
        outs, rep = convert(self.SRC, "3.05", lenient=True)  # kept as read where factors exist
        self.assertIn(b"12.3.4", outs[0].data)


class RoundingClaimsPerSignal(unittest.TestCase):
    """Sol 4: rounding is checked per signal, for the values the output keeps."""

    def test_claim_under_another_signal_fails(self):
        src = obs_file("G    2 C1C D1C", SCALED, [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F("         0.123")])
        outs, rep = convert(src, "2.11")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        moved = copy.deepcopy(rep)
        moved["losses"]["scale-factor-rounding:G:C1C"] = moved["losses"].pop("scale-factor-rounding:G:D1C")
        self.assertTrue(compare_obs(src, outs[0].data, moved))

    def test_dropped_system_needs_no_rounding_claim(self):
        # BeiDou (no RINEX 2 form): its scaled values go with the system
        src = lines(hdr("     3.05           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), *HEAD[1:],
                    hdr("G    1 C1C", "SYS / # / OBS TYPES"), hdr("C    1 C2I", "SYS / # / OBS TYPES"),
                    hdr("C   10  1 C2I", "SYS / SCALE FACTOR"), hdr("G", "SYS / PHASE SHIFT"),
                    hdr("C", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  2", "G05" + F("  22000000.105"),
                    "C11" + F(" 380000001.234"), width=None)
        outs, rep = convert(src, "2.11")
        self.assertIn("system-not-representable:C", rep["losses"])
        self.assertNotIn("scale-factor-rounding:C:C2I", rep["losses"])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class KeptIonSetIdentified(unittest.TestCase):
    """Sol 5 (and Sonnet 1): the RINEX 3 header keeps one QZSS set; its subtype claim follows
    the record it came from, matched by value."""

    EXTRA_LNAV = ["> ION J02 LNAV",
                  "    2026 10 30 00 00 00 3.000000000000E-08 2.000000000000E-08-6.000000000000E-08",
                  "    -1.000000000000E-07 9.000000000000E+04 1.000000000000E+05-6.000000000000E+04",
                  "    -5.000000000000E+05"]

    def test_kept_subtyped_set_needs_the_claim(self):
        src = payload(nav_v4("4.02") + self.EXTRA_LNAV)
        outs, rep = convert(src, "3.05")
        self.assertEqual(rep["losses"]["nav-subtype-not-representable:ION:J:CNVX"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        bare = copy.deepcopy(rep)
        del bare["losses"]["nav-subtype-not-representable:ION:J:CNVX"]
        self.assertTrue(compare_nav(src, [o.data for o in outs], bare))


if __name__ == "__main__":
    unittest.main()
