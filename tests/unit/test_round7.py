"""Regression tests for review round 7 (2026-10-31, docs/DECISIONS.md "review round 7 fixes"):
Sol's three blockers, each from the reviewer's reproduction."""

import copy
import unittest

from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL, obs_file
from .test_round3 import convert, head_lines


class TypesReplacedBeforeData(unittest.TestCase):
    """Sol 1: a flag-4 type list before the first observation epoch. The header's list holds
    no data, which made it empty for RINEX 2, and the 'nothing representable' check looked at
    that list only."""

    SRC = lines(*HEAD, hdr("G    1 C1C", "SYS / # / OBS TYPES"), hdr("G", "SYS / PHASE SHIFT"), *TAIL,
                "> 2026 10 01 00 00  0.0000000  4  1", hdr("G    2 C1C S1C", "SYS / # / OBS TYPES"),
                "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F("        45.250"),
                width=None)

    def test_converts_to_v2(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        for t in ("2.10", "2.11", "3.05"):
            with self.subTest(target=t):
                outs, rep = convert(self.SRC, t)            # was: refused-not-representable
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
        outs, rep = convert(self.SRC, "2.11")
        self.assertIn(hdr("     1    C1", "# / TYPES OF OBSERV"), head_lines(outs[0].data))


class CollapsedSignalIdentity(unittest.TestCase):
    """Sol 2 and 3: RINEX 2 holds one L1 per satellite. The comparison now leaves out the
    columns the report claims lost, so the kept column must hold its own values, and RINEX 2
    rounding is expected only for kept columns."""

    def src(self, scale=False):
        extra = [hdr("G   10  2 L1C L1W", "SYS / SCALE FACTOR")] if scale else []
        return obs_file("G    3 C1C L1C L1W", extra + [hdr("G L1C", "SYS / PHASE SHIFT"),
                                                         hdr("G L1W", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F("1150000004.051") + F("1150000009.009")])

    def test_wrong_kept_value_caught(self):
        src = self.src()
        outs, rep = convert(src, "2.11")
        self.assertIn("obs-code-collapsed:G:L1W", rep["losses"])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        bad = outs[0].data.replace(b"1150000004.051", b"1150000009.009")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_obs(src, bad, rep))

    def test_rounding_only_for_the_kept_column(self):
        src = self.src(scale=True)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        self.assertEqual(rep["losses"]["scale-factor-rounding:G:L1C"]["count"], 1)
        self.assertNotIn("scale-factor-rounding:G:L1W", rep["losses"])
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])     # was: demanded 2 roundings
        bare = copy.deepcopy(rep)
        del bare["losses"]["scale-factor-rounding:G:L1C"]
        self.assertTrue(compare_obs(src, outs[0].data, bare))


class SolRound8(unittest.TestCase):
    """Review round 8 (Sol): collapse claims checked against the type list in force, and an
    unsupported header list replaced before the data."""

    def test_collapse_claim_without_a_collision_fails(self):
        src = obs_file("G    2 C1C L1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405")])
        outs, rep = convert(src, "2.11")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        bad = outs[0].data.replace(b" 115000000.405", b"              ")
        self.assertNotEqual(bad, outs[0].data)
        claimed = copy.deepcopy(rep)
        claimed["losses"]["obs-code-collapsed:G:L1C"] = {"count": 1, "detail": {}}
        self.assertTrue(any("no type list has another column" in p for p in compare_obs(src, bad, claimed)))

    def test_collapse_in_one_list_only(self):
        # L1W collides with L1C under the header list, not under the flag-4 list without L1C
        src = lines(*HEAD, hdr("G    3 C1C L1C L1W", "SYS / # / OBS TYPES"), hdr("G L1C", "SYS / PHASE SHIFT"),
                    hdr("G L1W", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1",
                    "G05" + F("  22000000.105") + F(" 115000000.405") + F(" 115000000.909"),
                    "> 2026 10 01 00 00 15.0000000  4  1", hdr("G    2 C1C L1W", "SYS / # / OBS TYPES"),
                    "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.909"),
                    width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        self.assertEqual(rep["losses"]["obs-code-collapsed:G:L1W"]["count"], 1)
        self.assertIn(b" 115000500.909", outs[0].data)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])     # was: false alarm

    def test_unsupported_header_list_replaced_before_data(self):
        src = lines(*HEAD, hdr("G    1 X1 ", "SYS / # / OBS TYPES"), hdr("G", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  4  1", hdr("G    1 C1C", "SYS / # / OBS TYPES"),
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"), width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")                    # was: AssertionError (empty list)
        self.assertIn(hdr("     1    C1", "# / TYPES OF OBSERV"), head_lines(outs[0].data))
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


if __name__ == "__main__":
    unittest.main()
