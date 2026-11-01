"""Regression tests for review round 23 (2026-11-01, docs/DECISIONS.md "review round 23
fixes"): Sol's four blockers, from Sol's reproductions."""

import tempfile
import unittest
from unittest import mock

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.errors import CorruptError, MissingInformationError
from rinexcore.rinexfile import open_container
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines, table_file
from .test_round2 import HEAD
from .test_round13 import Exact
from .test_round22 import mixed, rec

TARGETS = ["2.10", "2.11", "3.00", "3.01", "3.02", "3.03", "3.04", "3.05", "4.00", "4.01", "4.02"]


def convert(src, t, **kw):
    outs = convert_data(src, "x.rnx", Options(t, compression="none", **kw))
    return outs, outs[0].report.to_dict()


def v2(version, types, body):
    return lines(hdr(f"{version:>9}           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
                 hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
                 hdr("TEST", "MARKER NAME"), *HEAD[4:], hdr("     1     1", "WAVELENGTH FACT L1/2"),
                 hdr(f"{len(types):6d}" + "".join(f"    {c}" for c in types), "# / TYPES OF OBSERV"),
                 hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
                 hdr("", "END OF HEADER"), *body)


class ReadOnlyVersions(Exact, unittest.TestCase):
    """Sol 1: the round-22 lookups of the source version's code table had no 2.00/2.01 table:
    KeyError in the checker and ValueError in the converter (corpus run 16, 66 crashes)."""

    def test_every_target(self):
        for version in ("2", "2.01"):
            # C2 is no 2.0x or 2.10 code (dubr1800.10d has one): claimed to 2.10 with values
            src = v2(version, ["C1", "P2", "L1", "S1", "C2"], [
                " 26 10  1  0  0  0.0000000  0  1G05",
                F("  22000000.105") + F("  22000001.205") + F(" 115000000.405") + F("        45.000")
                + F("  22000002.205"),
                " 26 10  1  0  0 30.0000000  0  1G05",
                (F("  22000100.105") + F("  22000101.205") + F(" 115000500.405")).rstrip()])
            self.assertEqual(V.errors(V.validate(src)), [])
            for t in TARGETS:
                with self.subTest(version=version, target=t):
                    outs, rep = convert(src, t, assume_phase_aligned=True)      # was: KeyError/ValueError
                    self.assertEqual(allowed_check(rep), [])
                    self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


class PlainFallbackFromScratch(unittest.TestCase):
    """Sol 2: the Compact RINEX plain fallback kept what only Compact RINEX 1.0 needed (the
    LLI/SSI of a blank value, claimed flags-on-missing-value-dropped): the fallback output
    differed from a plain conversion. It now starts again from the report's snapshot."""

    def test_flags_kept(self):
        src = v2("2.11", ["C1", "L1"], [
            " 26 10  1  0  0  0.0000000  0  1G05", "  22000000.105" + " " * 16 + "17",
            " 26 10  1  0  0 15.0000000  4  1", hdr("     2    C1    L1", "# / TYPES OF OBSERV"),
            " 26 10  1  0  0 30.0000000  6  1G05", "  22000100.105 115000500.4051",
            " 26 10  1  0  0 45.0000000  0  1G05", "  22000200.105 115000900.405"])
        self.assertEqual(V.errors(V.validate(src)), [])
        plain, prep = convert(src, "2.11")
        outs, rep = convert(src, "2.11", crx=True)
        self.assertFalse(outs[0].report.output["crx"])
        self.assertIn("OBS.CRX.EVENT-PLAIN", [w["rule"] for w in rep["warnings"]])
        self.assertNotIn("flags-on-missing-value-dropped", rep["losses"])
        self.assertEqual(open_container(outs[0].data).payload, plain[0].data)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class ChannelsGivenLate(unittest.TestCase):
    """Sol 3: a channel first given in an event at 00:00:15 was written into the header and
    so applied to R02's observation at 00:00:00, with nothing reported (rinex305.txt section
    6.5 p.42: header records in events hold from there on)."""

    SRC = mixed("3.01", "R", "C1C L1C", [hdr("  1 R01  1", "GLONASS SLOT / FRQ #")], body=[
        "> 2026 10 01 00 00  0.0000000  0  2", rec("R01", 21e6, 112e6), rec("R02", 20e6, 107e6),
        "> 2026 10 01 00 00 15.0000000  4  1", hdr("  1 R02 -4", "GLONASS SLOT / FRQ #"),
        "> 2026 10 01 00 00 30.0000000  0  1", rec("R02", 20e6 + 100, 107e6 + 500)])

    def test_needs_a_companion(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        with self.assertRaises(MissingInformationError):
            convert(self.SRC, "3.05")                                       # was: R02 -4 unreported
        fcn = table_file(tempfile.mkdtemp(), "R02 -4\n")
        outs, rep = convert(self.SRC, "3.05", glo_fcn=fcn)
        self.assertIn({"category": "glonass-fcn", "detail": "R02=-4"},
                      [{k: a[k] for k in ("category", "detail")} for a in rep["assumptions"]])
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
        # the checker: without that assumption the channel is not the file's for R02's first record
        rep2 = dict(rep, assumptions=[a for a in rep["assumptions"] if a["category"] != "glonass-fcn"])
        self.assertTrue(compare_obs(self.SRC, outs[0].data, rep2))

    def test_given_before_first_record(self):
        # the round-22 case: the event comes before R02's first record, so its channel is the file's
        src = mixed("3.01", "R", "C1C L1C", [hdr("  1 R01  1", "GLONASS SLOT / FRQ #")], body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("R01", 21e6, 112e6),
            "> 2026 10 01 00 00 15.0000000  4  1", hdr("  1 R02 -4", "GLONASS SLOT / FRQ #"),
            "> 2026 10 01 00 00 30.0000000  0  1", rec("R02", 20e6 + 100, 107e6 + 500)])
        outs, rep = convert(src, "3.05")
        self.assertIn(hdr("  2 R01  1 R02 -4", "GLONASS SLOT / FRQ #"), outs[0].data.decode())
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class BlankRecordAcrossLayouts(unittest.TestCase):
    """Generator, round 23: a 2.11 header list 'L1' whose one record is blank, then a flag-4
    list. To RINEX 3 the list is rebuilt from columns that hold data, so the record has no
    column and its epoch is emptied (claimed); the loss table had no reason to allow it."""

    def test_allowed(self):
        src = v2("2.11", ["L1"], [
            " 26 10  1  0  0  0.0000000  0  1G05", "",
            " 26 10  1  0  0 15.0000000  4  1", hdr("     2    C1    L1", "# / TYPES OF OBSERV"),
            " 26 10  1  0  0 30.0000000  0  1G05", "  22000100.105 115000500.405"])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.05", assume_phase_aligned=True)
        self.assertEqual(rep["losses"]["epoch-emptied-by-system-removal"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class GeneratedRefusalsJustified(unittest.TestCase):
    """Sol 4: test_generated passed any RinexError, so a converter refusing every file would
    pass; a refusal now passes only where the independent code tables find nothing of the
    file the target can hold."""

    def test_unjustified_refusal_fails(self):
        from tests.independent.generate import ObsGen
        from tests.unit import test_generated as T
        g = next(ObsGen(s) for s in range(100) if "R" not in ObsGen(s).sys)
        src = g.data()

        def refuse(*a, **k):
            raise CorruptError("injected", rule="TEST.INJECTED")
        with mock.patch.object(T, "convert_data", refuse):
            self.assertTrue(T.check_one(src, g.v, None, None))
        self.assertFalse(T.check_one(src, g.v, None, None))


if __name__ == "__main__":
    unittest.main()
