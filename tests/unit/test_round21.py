"""Regression tests for review round 21 (2026-11-01, docs/DECISIONS.md "review round 21
fixes"): Sonnet's blocker (tested in test_round20.py) and Sol's four, from their
reproductions."""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL
from .test_round13 import Exact


def convert(src, t, **kw):
    outs = convert_data(src, "x.rnx", Options(t, compression="none", **kw))
    return outs, outs[0].report.to_dict()


def mixed(version, ctypes, extra=(), body=None, tail=TAIL):
    body = body or ["> 2026 10 01 00 00  0.0000000  0  2", "G05" + F("  22000000.105") + F(" 115000000.405"),
                    "C11" + F("  23000000.105") + F(" 120000000.405")]
    return lines(hdr(f"     {version}           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), *HEAD[1:],
                 hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr(f"C    2 {ctypes}", "SYS / # / OBS TYPES"),
                 hdr("G L1C", "SYS / PHASE SHIFT"), hdr(f"C {ctypes[4:]}", "SYS / PHASE SHIFT"), *extra,
                 *tail, *body, width=None)


class EventPhaseCenter(Exact, unittest.TestCase):
    """Sol 1: an event's ANTENNA: PHASECENTER bypassed the code map: a 3.02 'C L1X' (B1I) stayed
    'L1X' (B1C) in 3.05 while the header's became 'L2X'."""

    def test_mapped(self):
        pc = hdr("C L1X   0.1234        0.0000        0.0567", "ANTENNA: PHASECENTER")
        src = mixed("3.02", "C1X L1X", [pc], body=[
            "> 2026 10 01 00 00  0.0000000  0  2", "G05" + F("  22000000.105") + F(" 115000000.405"),
            "C11" + F("  23000000.105") + F(" 120000000.405"),
            "> 2026 10 01 00 00 15.0000000  4  1", pc,
            "> 2026 10 01 00 00 30.0000000  0  1", "C11" + F("  23000100.105") + F(" 120000500.405")])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.05")
        body = outs[0].data.decode().split("END OF HEADER")[1]
        self.assertIn(hdr("C L2X   0.1234        0.0000        0.0567", "ANTENNA: PHASECENTER"), body)
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)
        bad = outs[0].data.replace(b"\nC L2X   0.1234", b"\nC L1X   0.1234")
        self.assertTrue(compare_obs(src, bad, rep))


class SystemRecordsOfDroppedSystems(Exact, unittest.TestCase):
    """Sol 2: SYS / DCBS APPLIED and SYS / PCVS APPLIED of BeiDou stayed in a 3.00 output (3.00
    allows G/R/E/S there: rinex300.txt Table A1 p.29), in the header and in events."""

    def test_claimed(self):
        dcb = hdr("C RTKLIB              https://example.org/dcb", "SYS / DCBS APPLIED")
        pcv = hdr("C RTKLIB              https://example.org/pcv", "SYS / PCVS APPLIED")
        gdcb = hdr("G RTKLIB              https://example.org/dcb", "SYS / DCBS APPLIED")
        src = mixed("3.05", "C2I L2I", [dcb, pcv, gdcb], body=[
            "> 2026 10 01 00 00  0.0000000  0  2", "G05" + F("  22000000.105") + F(" 115000000.405"),
            "C11" + F("  23000000.105") + F(" 120000000.405"),
            "> 2026 10 01 00 00 15.0000000  4  1", dcb,
            "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405")])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.00", assume_phase_aligned=True)
        text = outs[0].data.decode()
        self.assertNotIn("C RTKLIB", text)
        self.assertIn("G RTKLIB", text)                                   # GPS's stays
        self.assertEqual(rep["losses"]["sys-record-not-representable:C:SYS / DCBS APPLIED"]["count"], 2)
        self.assertEqual(rep["losses"]["sys-record-not-representable:C:SYS / PCVS APPLIED"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


class EpochsAndSatellitesLeftOut(Exact, unittest.TestCase):
    """Sol 3: records left out because no type of theirs exists in the target still counted
    in TIME OF FIRST OBS (an AssertionError for a file that starts with a BeiDou B1C-only epoch,
    to 3.02) and in the counts; and the source's TIME OF FIRST OBS was checked against the kept
    epochs, a false repair."""

    def test_first_epoch_left_out(self):
        src = mixed("3.05", "C1P L1P", body=[
            "> 2026 10 01 00 00  0.0000000  0  1", "C11" + F("  23000000.105") + F(" 120000000.405"),
            "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405")])
        self.assertEqual(V.errors(V.validate(src)), [])
        for strict in (False, True):
            with self.subTest(strict=strict):
                outs, rep = convert(src, "3.02", strict=strict)            # was: AssertionError
                head = outs[0].data.decode().split("END OF HEADER")[0]
                self.assertIn("  2026    10     1     0     0   30.0000000     GPS         TIME OF FIRST OBS", head)
                self.assertEqual(rep["repairs"], [])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_counts_after_a_flag4_list(self):
        # BeiDou has no 3.02 type in the header's list, then a flag-4 list gives it one
        counts = [hdr("     2", "# OF SATELLITES"), hdr("   G05     2     2", "PRN / # OF OBS"),
                  hdr("   C11     1     1", "PRN / # OF OBS")]
        src = mixed("3.05", "C1P L1P", counts, body=[
            "> 2026 10 01 00 00  0.0000000  0  2", "G05" + F("  22000000.105") + F(" 115000000.405"),
            "C11" + F("  23000000.105") + F(" 120000000.405"),
            "> 2026 10 01 00 00 15.0000000  4  2", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
            hdr("C    2 C2I L2I", "SYS / # / OBS TYPES"),
            "> 2026 10 01 00 00 30.0000000  0  2", "G05" + F("  22000100.105") + F(" 115000500.405"),
            "C12" + F("  23000100.105") + F(" 120000500.405")])
        outs, rep = convert(src, "3.02")
        head = outs[0].data.decode().split("END OF HEADER")[0]
        self.assertNotIn("C11", head)                     # C11's only record had no 3.02 type
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


class OptionalCountRecords(unittest.TestCase):
    """Sol 4: a header with a correct # OF SATELLITES and no (optional) PRN / # OF OBS got
    HDR.COUNTS, and --strict refused even a same-version conversion."""

    def test_only_what_is_there(self):
        src = mixed("3.05", "C2I L2I", [hdr("     2", "# OF SATELLITES")])
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("3.05", "3.04"):
            with self.subTest(target=t):
                outs, rep = convert(src, t, strict=True)            # was: refused
                self.assertEqual(rep["repairs"], [])
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        wrong = mixed("3.05", "C2I L2I", [hdr("     3", "# OF SATELLITES")])
        outs, rep = convert(wrong, "3.05")
        self.assertIn("HDR.COUNTS", [r["rule"] for r in rep["repairs"]])


if __name__ == "__main__":
    unittest.main()
