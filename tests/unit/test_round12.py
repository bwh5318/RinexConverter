"""Regression tests for review round 12 (2026-10-31, docs/DECISIONS.md "review round 12 fixes"):
Sol's blockers, each from the reviewer's reproduction. Blank attributes ('L1 ') are valid in
3.00 and 3.01 only (rinex300.txt l.690, rinex301.txt l.706; rinex303.txt l.451: "decided in
3.02 not to allow unknown signals")."""

import os
import sys
import unittest

from rinexconv.engine import Options, convert_data, convert_loaded, load_bytes
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL
from .test_round3 import convert, head_lines
from .test_validate import nav_v4, payload


def v3x(version, *types_and_more, body):
    return lines(hdr(f"     {version}           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), *HEAD[1:],
                 *types_and_more, *TAIL, *body, width=None)


class ScaleFactorBlankAttribute(unittest.TestCase):
    """Sol 1: SYS / SCALE FACTOR codes were split on blanks, so 'L1 ' never matched the type
    list's 'L1 ' and a scaled phase was copied undivided: ten times too large, unreported."""

    SRC = v3x("3.00", hdr("G    2 C1C L1 ", "SYS / # / OBS TYPES"), hdr("G   10   1 L1 ", "SYS / SCALE FACTOR"),
              body=["> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.400")])

    def test_divided_for_rinex2(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        outs, rep = convert(self.SRC, "2.11")
        self.assertIn(b"  11500000.040", outs[0].data)               # was 115000000.400
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])

    def test_same_family_keeps_factor_and_value(self):
        for t in ("3.00", "3.01"):
            with self.subTest(target=t):
                outs, rep = convert(self.SRC, t, strict=True)
                head = head_lines(outs[0].data)
                self.assertIn(hdr("G   10   1 L1 ", "SYS / SCALE FACTOR"), head)    # was: record dropped
                self.assertIn(b" 115000000.400", outs[0].data)
                self.assertEqual(rep["losses"], {})
                self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])

    def test_not_representable_from_302_is_counted(self):
        outs, rep = convert(self.SRC, "3.05", assume_phase_aligned=True)
        self.assertEqual(rep["losses"]["obs-code-not-representable:G:L1 "]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])     # was: count mismatch


class PhaseShiftBlankAttribute(unittest.TestCase):
    """Sol 2: a 3.01 SYS / PHASE SHIFT naming 'L1 ' (A3, blank attribute) was invalid for the
    validator and so refused under --strict."""

    SRC = v3x("3.01", hdr("G    2 C1C L1 ", "SYS / # / OBS TYPES"), hdr("G L1   0.00000", "SYS / PHASE SHIFTS"),
              body=["> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.400")])

    def test_valid_and_carried(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        outs, rep = convert(self.SRC, "3.01", strict=True)                  # was: refused
        self.assertIn(hdr("G L1   0.00000", "SYS / PHASE SHIFTS"), head_lines(outs[0].data))
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
        # from 3.02 a blank attribute is not allowed (rinex303.txt l.451): still an error there
        v305 = v3x("3.05", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("G L1   0.00000", "SYS / PHASE SHIFT"),
                   body=["> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.400")])
        self.assertIn("VAL.HDR.PHASESHIFT", [f.rule for f in V.errors(V.validate(v305))])


class DuplicateIdentityIgnoresSeparators(unittest.TestCase):
    """Sol 3: a blank separator after one of two identical RINEX 4 STO/ION/EOP records (a
    repaired NAV.BLANKLINE) made their identities differ, so --dedupe looked like a loss."""

    def test_each_kind(self):
        for head in ("> EOP G01 LNAV", "> ION G01 LNAV", "> STO G01 LNAV"):
            with self.subTest(record=head):
                b = nav_v4("4.02")
                i = b.index(head)
                j = next(k for k in range(i + 1, len(b)) if b[k].startswith(">"))
                src = payload(b[:j] + [""] + b[i:j] + b[j:])
                outs, rep = convert(src, "4.02", dedupe=True, lenient=True)
                self.assertEqual(outs[0].data.decode().count(head), 1)
                self.assertEqual(rep["losses"]["nav-duplicate-removed"]["count"], 1)
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


class WrapperLegOutputCount(unittest.TestCase):
    """Sol polish 1: the harness paired outputs with zip, so a missing split output passed."""

    def test_missing_output_caught(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
        import corpus_run as CR
        src = payload(nav_v4("4.02"))
        ld = load_bytes(src)
        plain = [o.data for o in convert_loaded(ld, "x.rnx", Options("2.11", compression="none"))]
        self.assertGreater(len(plain), 1)                     # GPS and GLONASS files
        self.assertEqual(CR._wrapper_leg(ld, "x.rnx", "nav", "2.11", plain, [], with_z=False), [])
        real = CR.convert_loaded
        CR.convert_loaded = lambda *a, **k: real(*a, **k)[:1]
        try:
            self.assertTrue(CR._wrapper_leg(ld, "x.rnx", "nav", "2.11", plain, [], with_z=False))
        finally:
            CR.convert_loaded = real


if __name__ == "__main__":
    unittest.main()
