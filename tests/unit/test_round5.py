"""Regression tests for review round 5 (2026-10-31, docs/DECISIONS.md "review round 5 fixes"):
Sol's four blockers, each from the reviewer's reproduction, with a mutation the independent
checks must catch where the fix is in the checker."""

import copy
import unittest

from rinexcore import validate as V
from rinexcore.errors import MissingInformationError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL, ScaleFactorEvents, obs_file
from .test_round3 import convert, head_lines
from .test_round4 import PhaseAlignmentFromEvents
from .test_validate import nav_v4, payload


class ScaledValueRoundsToZero(unittest.TestCase):
    """Sol 1: D1C 0.001 with factor 10 is 0.0001, which F14.3 (RINEX 2, no factors) rounds to
    0.000, i.e. missing (rinex211.txt ~1288): written blank and not counted."""

    SRC = obs_file("G    2 C1C D1C", [hdr("G   10  1 D1C", "SYS / SCALE FACTOR"), hdr("G", "SYS / PHASE SHIFT"),
                                      hdr("     1", "# OF SATELLITES"), hdr("   G05     1     1", "PRN / # OF OBS")], [
        "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F("         0.001")])

    def test_to_211(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        outs, rep = convert(self.SRC, "2.11")          # was: AssertionError (PRN count 1)
        data = outs[0].data
        self.assertIn(hdr("   G 5     1     0", "PRN / # OF OBS"), head_lines(data))
        self.assertIn(b"\n  22000000.105\n", data)    # the D1 field is blank (and trimmed)
        self.assertEqual(rep["losses"]["scale-factor-rounding:G:D1C"]["count"], 1)
        self.assertEqual(V.errors(V.validate(data)), [])
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(self.SRC, data, rep), [])
        # a report without the rounding claim fails
        bare = copy.deepcopy(rep)
        del bare["losses"]["scale-factor-rounding:G:D1C"]
        self.assertTrue(compare_obs(self.SRC, data, bare))


class AlignmentPerInterval(unittest.TestCase):
    """Sol 2: unknown alignment matters only while the type list in effect has phases."""

    def test_phases_arrive_with_their_alignment(self):
        src = lines(*HEAD, hdr("G    1 C1C", "SYS / # / OBS TYPES"), hdr("G", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"),
                    "> 2026 10 01 00 00 15.0000000  4  2", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
                    hdr("G L1C  0.00000", "SYS / PHASE SHIFT"),
                    "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405"),
                    width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "4.02")                 # was: refused-missing-information
        self.assertNotIn("phase-alignment", [a["category"] for a in rep["assumptions"]])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_refusal_names_the_event(self):
        """Sol polish 1: the refusal says where the unknown alignment starts."""
        with self.assertRaises(MissingInformationError) as cm:
            convert(PhaseAlignmentFromEvents.ALIGNED_THEN_UNKNOWN, "4.02")
        self.assertIn("G: the event at input line", str(cm.exception))


class ScaleFactorsChecked(unittest.TestCase):
    """Sol 3: the independent tokens now divide by the factor in effect (header, then events)."""

    SRC = ScaleFactorEvents.SRC

    def test_correct_division_to_211_passes(self):
        outs, rep = convert(self.SRC, "2.11")
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
        self.assertEqual(allowed_check(rep), [])        # the emptied scale event is accepted
        bad = outs[0].data.replace(b"  89000040.050", b" 890000400.500")   # L2W / 10, not / 100
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_obs(self.SRC, bad, rep))

    def test_changed_factor_in_v3_output_caught(self):
        outs, rep = convert(self.SRC, "3.04")
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
        for old, new in ((b"G  100  1 L2W", b"G   10  1 L2W"), (b"G   10  1 L1C", b"G  100  1 L1C")):
            bad = outs[0].data.replace(old, new)
            self.assertNotEqual(bad, outs[0].data, old)
            self.assertTrue(compare_obs(self.SRC, bad, rep), new)


class NavSubtypes(unittest.TestCase):
    """Sol 4: 'CNVX WIDE' and 'CNVX JAPN' are different coefficient areas (rinex_4.02.txt
    Table 25 p.40); the comparison now sees the subtype."""

    SRC = payload(nav_v4("4.02"))

    def test_swapped_area_caught(self):
        outs, rep = convert(self.SRC, "4.02")
        self.assertEqual(compare_nav(self.SRC, [outs[0].data], rep), [])
        bad = outs[0].data.replace(b"CNVX WIDE", b"CNVX JAPN")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_nav(self.SRC, [bad], rep))

    def test_mixed_areas_to_v3_one_kept_set(self):
        """Sonnet round 6: BRD400DLR 4.02 holds QZSS LNAV and CNVX sets, each WIDE and JAPN
        (record forms copied from the corpus file). RINEX 3 keeps one QZSA/QZSB set per time
        mark and SV (round 26; one in all before): here the hour-02 and the hour-00 sets, so
        each kept set's subtype is claimed, the rest are nav-correction-extra. The check
        demanded a claim per message type (false alarm on the corpus)."""
        body = []
        for msg, area, t, a in (("LNAV", "WIDE", "02 01 54", "1.955777406693E-08"),
                                ("CNVX", "WIDE", "02 01 12", "1.955777406693E-08"),
                                ("LNAV", "JAPN", "00 04 00", "2.887099981308E-08"),
                                ("CNVX", "JAPN", "00 03 12", "2.887099981308E-08")):
            body += [f"> ION J02 {msg} {area}",
                     f"    2026 10 01 {t} {a}-1.415610313416E-07-2.622604370117E-06",
                     "    -7.629394531250E-06 9.216000000000E+04 9.830400000000E+04 2.424832000000E+06",
                     "     8.323072000000E+06"]
        src = payload(nav_v4("4.02")[:-4] + body)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.05")
        claims = {k: e["count"] for k, e in rep["losses"].items() if "subtype" in k}
        self.assertEqual(sum(claims.values()), 2)
        self.assertEqual(sum(1 for l in outs[0].data.decode().split("\n") if l.startswith("QZSA")), 2)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        bare = copy.deepcopy(rep)
        for k in claims:
            del bare["losses"][k]
        self.assertTrue(compare_nav(src, [o.data for o in outs], bare))

    def test_subtype_loss_claimed_below_402(self):
        # 3.05 has no area field (rinex305.txt Table A5 p.65): the subtype is claimed. 4.01
        # holds the area as the Klobuchar Region code ('0 or blank (wide area parameters), 1
        # (QZSS only - Japan area coefficients)', rinex_4.01.txt l.6190 p.108): WIDE is written
        # 0, nothing lost (round 32; it was claimed lost)
        for t in ("4.01", "3.05"):
            with self.subTest(target=t):
                outs, rep = convert(self.SRC, t)
                if t == "4.01":
                    self.assertNotIn("nav-subtype-not-representable:ION:J:CNVX", rep["losses"])
                    self.assertEqual(rep["rules"]["NAV.ION.SUBTYPE-TO-REGION"]["count"], 1)
                    lines = outs[0].data.decode().split("\n")
                    k = next(i for i, l in enumerate(lines) if l.startswith("> ION J01 CNVX"))
                    self.assertEqual(lines[k].rstrip(), "> ION J01 CNVX")
                    self.assertEqual(lines[k + 3][23:42], " 0.000000000000E+00")
                    self.assertEqual(compare_nav(self.SRC, [o.data for o in outs], rep), [])
                    bad = outs[0].data.replace(lines[k + 3].encode(), lines[k + 3][:23].encode()
                                               + b" 1.000000000000E+00")
                    self.assertTrue(compare_nav(self.SRC, [bad], rep))
                    continue
                self.assertEqual(rep["losses"]["nav-subtype-not-representable:ION:J:CNVX"]["count"], 1)
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(self.SRC, [o.data for o in outs], rep), [])
                bare = copy.deepcopy(rep)
                del bare["losses"]["nav-subtype-not-representable:ION:J:CNVX"]
                self.assertTrue(compare_nav(self.SRC, [o.data for o in outs], bare))


if __name__ == "__main__":
    unittest.main()
