"""Regression tests for review round 10 (2026-10-31, docs/DECISIONS.md "review round 10 fixes"):
Sol's blockers 2 and 3, each from the reviewer's reproduction (blocker 1, gunzip, is in
test_compress.py)."""

import copy
import unittest

from rinexcore import validate as V
from tests.independent.compare import compare_nav, compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL, obs_file
from .test_round3 import MIXED, QzssIonArea, convert
from .test_user_options import nav400
from .test_validate import nav_v4, payload


def forged(rep, cat, n):
    r = copy.deepcopy(rep)
    if n is None:
        del r["losses"][cat]
    else:
        r["losses"][cat]["count"] = n
    return r


class FlagOnlyLosses(unittest.TestCase):
    """Sol 2: a flag-only field (blank value, LLI/SSI set) in a dropped column, or one whose LLI
    bit 2 is cleared, changed the output with no loss counted for it."""

    def test_collapsed_flag_only_column(self):
        src = obs_file("G    3 C1C L1C L1W", [hdr("G L1C", "SYS / PHASE SHIFT"), hdr("G L1W", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F(" 115000000.405") + F(" " * 14, "1")])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        e = rep["losses"]["obs-code-collapsed:G:L1W"]               # was: obs-code-collapsed-empty
        self.assertEqual((e["count"], e["detail"].get("flag_only")), (1, 1))
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        self.assertTrue(compare_obs(src, outs[0].data, forged(rep, "obs-code-collapsed:G:L1W", 0)))
        self.assertTrue(compare_obs(src, outs[0].data, forged(rep, "obs-code-collapsed:G:L1W", None)))

    def test_not_representable_flag_only_column(self):
        src = lines(MIXED, *HEAD[1:], hdr("C    3 C2I L2I L1X", "SYS / # / OBS TYPES"),
                    hdr("C L2I", "SYS / PHASE SHIFT"), hdr("C L1X", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1",
                    "C11" + F("  22000000.105") + F(" 115000000.405") + F(" " * 14, " ", "7"), width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.02")
        e = rep["losses"]["obs-code-not-representable:C:L1X"]
        self.assertEqual((e["count"], e["detail"].get("flag_only")), (1, 1))
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        self.assertTrue(compare_obs(src, outs[0].data, forged(rep, "obs-code-not-representable:C:L1X", 0)))

    def test_bit2_cleared_on_flag_only_fields_counted(self):
        src = lines(
            hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
            hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
            hdr("TEST", "MARKER NAME"),
            hdr("     2    C1    L1", "# / TYPES OF OBSERV"),
            hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
            hdr("", "END OF HEADER"),
            " 26 10  1  0  0  0.0000000  0  2G05G12",
            F("  22000000.105") + F(" 115000000.405", "4"),
            F("  21000000.112") + F(" " * 14, "5"))
        outs, rep = convert(src, "3.05")
        self.assertEqual(rep["losses"]["lli-bit2-meaning-differs"]["count"], 2)   # was 1
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        for n in (1, 0):
            with self.subTest(forged=n):
                self.assertTrue(compare_obs(src, outs[0].data, forged(rep, "lli-bit2-meaning-differs", n)))


class NavDuplicatesCounted(unittest.TestCase):
    """Sol 3: --dedupe of correction records failed both checks, and the removal count of
    ephemerides was never compared."""

    def test_correction_duplicates(self):
        src = nav400(QzssIonArea.J_CNVX)                  # the same CNVX set twice
        outs, rep = convert(src, "4.02", qzss_ion_area="WIDE", dedupe=True)
        self.assertEqual(outs[0].data.decode().count("> ION J01 CNVX WIDE"), 1)
        self.assertEqual(rep["losses"]["nav-duplicate-removed"]["count"], 1)
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])       # was: 2 problems

    def test_ephemeris_duplicates_count(self):
        b = nav_v4("4.02")
        i = b.index("> EPH G01 LNAV")
        j = next(k for k in range(i + 1, len(b)) if b[k].startswith(">"))
        src = payload(b[:j] + b[i:j] * 2 + b[j:])          # G01 three times
        outs, rep = convert(src, "4.02", dedupe=True)
        self.assertEqual(outs[0].data.decode().count("> EPH G01 LNAV"), 1)
        self.assertEqual(rep["losses"]["nav-duplicate-removed"]["count"], 2)
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        self.assertTrue(compare_nav(src, [o.data for o in outs], forged(rep, "nav-duplicate-removed", 999)))
        self.assertTrue(compare_nav(src, [o.data for o in outs], forged(rep, "nav-duplicate-removed", None)))


if __name__ == "__main__":
    unittest.main()
