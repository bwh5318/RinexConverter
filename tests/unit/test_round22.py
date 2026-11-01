"""Regression tests for review round 22 (2026-11-01, docs/DECISIONS.md "review round 22
fixes"): Sol's five blockers, from Sol's reproductions."""

import tempfile
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines, table_file
from .test_round2 import HEAD, TAIL
from .test_round13 import Exact


def convert(src, t, **kw):
    outs = convert_data(src, "x.rnx", Options(t, compression="none", **kw))
    return outs, outs[0].report.to_dict()


def mixed(version, sys2, types2, extra=(), body=(), phase=True):
    """A RINEX 3 file of GPS (C1C L1C) and a second system with its own types."""
    label = "SYS / PHASE SHIFTS" if version == "3.01" else "SYS / PHASE SHIFT"
    ph = [hdr("G L1C", label), hdr(f"{sys2} {types2[4:]}", label)] if phase and version >= "3.01" else []
    return lines(hdr(f"     {version}           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
                 *HEAD[1:], hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
                 hdr(f"{sys2}    2 {types2}", "SYS / # / OBS TYPES"), *ph, *extra, *TAIL, *body, width=None)


def rec(sat, c, l):
    return sat + F("%14.3f" % c) + F("%14.3f" % l)


class ChannelsFromEvents(Exact, unittest.TestCase):
    """Sol 1: a flag-4 event that gives R02's channel before R02 is observed: 3.01 -> 3.05
    raised MissingInformationError, and a 3.05 file got OBS.GLONASS-SLOTS-INCOMPLETE (a
    refusal under --strict)."""

    def src(self, version):
        slot = [hdr("  1 R01  1", "GLONASS SLOT / FRQ #")]
        if version >= "3.02":
            slot.append(hdr(" C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS"))
        return mixed(version, "R", "C1C L1C", slot, body=[
            "> 2026 10 01 00 00  0.0000000  0  2", rec("G05", 22e6, 115e6), rec("R01", 21e6, 112e6),
            "> 2026 10 01 00 00 15.0000000  4  1", hdr("  2 R01  1 R02 -4", "GLONASS SLOT / FRQ #"),
            "> 2026 10 01 00 00 30.0000000  0  2", rec("R01", 21e6 + 100, 112e6 + 500),
            rec("R02", 20e6, 107e6)])

    def test_3_01_to_3_05(self):
        src = self.src("3.01")
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.05")                   # was: MissingInformationError
        head = outs[0].data.decode().split("END OF HEADER")[0]
        self.assertIn(hdr("  2 R01  1 R02 -4", "GLONASS SLOT / FRQ #"), head)
        self.assertIn("OBS.GLONASS-SLOTS-FROM-EVENTS", rep["rules"])
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_3_05_strict(self):
        src = self.src("3.05")
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("3.05", "3.04", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t, strict=True)    # was: refused (slots incomplete)
                self.assertNotIn("OBS.GLONASS-SLOTS-INCOMPLETE", [w["rule"] for w in rep["warnings"]])
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_event_channel_changed(self):
        # Sol 2 (second half): an event's R02 channel -4 -> +6 passed the comparison
        src = self.src("3.05")
        outs, rep = convert(src, "3.04")
        bad = outs[0].data.replace(b"  2 R01  1 R02 -4 ", b"  2 R01  1 R02  6 ")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_obs(src, bad, rep))


class PhaseCenterScopes(unittest.TestCase):
    """Sol 2: header and event ANTENNA: PHASECENTER records were pooled, so swapping two
    different vectors between the header and an event passed the comparison; a value holds
    until an event changes it (rinex305.txt section 6.5 p.42)."""

    def test_swap_caught(self):
        h = hdr("G L1C   0.1234        0.0000        0.0567", "ANTENNA: PHASECENTER")
        e = hdr("G L1C   0.2345        0.0000        0.0678", "ANTENNA: PHASECENTER")
        src = mixed("3.05", "E", "C1C L1C", [h], body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("G05", 22e6, 115e6),
            "> 2026 10 01 00 00 15.0000000  4  1", e,
            "> 2026 10 01 00 00 30.0000000  0  1", rec("G05", 22e6 + 100, 115e6 + 500)])
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("3.04", "3.05"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])
                d = outs[0].data
                swapped = d.replace(b"0.1234", b"0.XXXX").replace(b"0.2345", b"0.1234").replace(
                    b"0.XXXX", b"0.2345").replace(b"0.0567", b"0.YYYY").replace(b"0.0678", b"0.0567").replace(
                    b"0.YYYY", b"0.0678")
                self.assertNotEqual(swapped, d)
                self.assertTrue(compare_obs(src, swapped, rep))


class EventRecordsInTheirOwnEvent(unittest.TestCase):
    """Round 22 (found while fixing Sol 2): event LEAP SECONDS were paired over the whole file,
    so a record could move to another event unnoticed; event GLONASS COD/PHS/BIS values were
    not compared at all."""

    def src(self):
        slot = [hdr("  1 R01  1", "GLONASS SLOT / FRQ #"),
                hdr(" C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS")]
        return mixed("3.05", "R", "C1C L1C", slot, body=[
            "> 2026 10 01 00 00  0.0000000  0  2", rec("G05", 22e6, 115e6), rec("R01", 21e6, 112e6),
            "> 2026 10 01 00 00 15.0000000  4  3", hdr("FIRST EVENT", "COMMENT"), hdr("    18", "LEAP SECONDS"),
            hdr(" C1C   -0.250 C1P    0.125 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS"),
            "> 2026 10 01 00 00 30.0000000  0  1", rec("R01", 21e6 + 100, 112e6 + 500),
            "> 2026 10 01 00 00 45.0000000  4  1", hdr("SECOND EVENT", "COMMENT"),
            "> 2026 10 01 00 01  0.0000000  0  1", rec("G05", 22e6 + 200, 115e6 + 900)])

    def test_leap_moved_between_events(self):
        src = self.src()
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.04")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        d = outs[0].data.decode()
        leap = hdr("    18", "LEAP SECONDS") + "\n"
        first = "> 2026 10 01 00 00 15.0000000  4  3\n"
        second = "> 2026 10 01 00 00 45.0000000  4  1\n" + hdr("SECOND EVENT", "COMMENT") + "\n"
        self.assertIn(first, d)
        self.assertIn(second, d)
        bad = d.replace(leap, "").replace(first, first.replace("  4  3", "  4  2")).replace(
            second, second.replace("  4  1", "  4  2") + leap)
        self.assertNotEqual(bad, d)
        self.assertEqual(V.errors(V.validate(bad.encode())), [])
        self.assertTrue(compare_obs(src, bad.encode(), rep))

    def test_event_cod_phs_bis_values(self):
        src = self.src()
        outs, rep = convert(src, "3.04")
        bad = outs[0].data.replace(b" C1C   -0.250 C1P    0.125", b" C1C   -0.375 C1P    0.125")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_obs(src, bad, rep))


class TypeEmptiedLosses(unittest.TestCase):
    """Sol 3: losses that follow from types the target lacks were refused by the loss table:
    an epoch emptied because its records' types are all gone (no system lost), and SYS / DCBS
    APPLIED of a system the target defines but that keeps no type."""

    def test_epoch_emptied_by_types(self):
        # BeiDou B1C (C1P L1P) has no 3.02 code: the BeiDou-only epoch has nothing left
        src = mixed("3.05", "C", "C1P L1P", body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("C11", 23e6, 120e6),
            "> 2026 10 01 00 00 30.0000000  0  1", rec("G05", 22e6, 115e6)])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.02")
        self.assertEqual(rep["losses"]["epoch-emptied-by-system-removal"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_dcbs_of_a_system_left_without_types(self):
        dcb = hdr("C RTKLIB              https://example.org/dcb", "SYS / DCBS APPLIED")
        src = mixed("3.05", "C", "C1P L1P", [dcb], body=[
            "> 2026 10 01 00 00  0.0000000  0  2", rec("G05", 22e6, 115e6), rec("C11", 23e6, 120e6)])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.02")
        self.assertNotIn(b"C RTKLIB", outs[0].data)
        self.assertEqual(rep["losses"]["sys-record-not-representable:C:SYS / DCBS APPLIED"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class IntervalOfKeptEpochs(unittest.TestCase):
    """Sol 4: BeiDou and GPS epochs alternating every 15 s become GPS epochs every 30 s in
    2.11 (no BeiDou); the converter's INTERVAL 30 (rule OBS.INTERVAL.FROM-KEPT-EPOCHS) was
    flagged as an unreported repair."""

    def test_interval_changed(self):
        body = []
        for k in range(6):
            sat = rec("G05", 22e6 + k, 115e6 + k) if k % 2 == 0 else rec("C11", 23e6 + k, 120e6 + k)
            body += ["> 2026 10 01 00 %02d %2d.0000000  0  1" % (k * 15 // 60, k * 15 % 60), sat]
        src = mixed("3.05", "C", "C2I L2I", [hdr("    15.000", "INTERVAL")], body=body)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        head = outs[0].data.decode().split("END OF HEADER")[0]
        self.assertIn(hdr("    30.000", "INTERVAL"), head)
        self.assertIn("OBS.INTERVAL.FROM-KEPT-EPOCHS", rep["rules"])
        self.assertEqual(rep["repairs"], [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        wrong = outs[0].data.replace(b"    30.000", b"    60.000")
        self.assertTrue(compare_obs(src, wrong, rep))


class GlobalListOfRinex2(unittest.TestCase):
    """Sol 5: to 2.11, a GLONASS record whose types (C3I L3I: band 3 has no RINEX 2 code)
    are all gone stays, blank, under the one global list; the checker expected the epoch
    emptied."""

    def test_blank_record_kept(self):
        glo = [hdr("  1 R05  1", "GLONASS SLOT / FRQ #"),
               hdr(" C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS")]
        src = mixed("3.05", "R", "C3I L3I", glo, body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("R05", 22e6, 115e6),
            "> 2026 10 01 00 00 30.0000000  0  1", rec("G05", 22e6 + 100, 115e6 + 500)])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        self.assertIn(b" 26 10  1  0  0  0.0000000  0  1R05", outs[0].data.replace(b"R 5", b"R05"))
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


def v2file(version, types, body, single="G (GPS)"):
    return lines(hdr(f"     {version}           OBSERVATION DATA    {single}", "RINEX VERSION / TYPE"),
                 hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
                 hdr("TEST", "MARKER NAME"), *HEAD[4:], hdr("     1     1", "WAVELENGTH FACT L1/2"),
                 hdr(f"{len(types):6d}" + "".join(f"    {c}" for c in types), "# / TYPES OF OBSERV"),
                 hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
                 hdr("", "END OF HEADER"), *body)


class GeneratedFiles(Exact, unittest.TestCase):
    """Found by a structured random generator of valid files (round 22, scratchpad
    gen_obs.py): each converted to every version and checked independently."""

    def test_header_list_without_target_code(self):
        # 2.11 C2/C5 have no 2.10 code; a flag-4 list then gives C1/L1: the header list was
        # written with 0 types and the output failed its own validation (AssertionError)
        src = v2file("2.11", ["C2", "C5"], [
            " 26 10  1  0  0  0.0000000  0  1G05", "  22000000.105  22000001.205",
            " 26 10  1  0  0 15.0000000  4  1", hdr("     2    C1    L1", "# / TYPES OF OBSERV"),
            " 26 10  1  0  0 30.0000000  0  1G05", "  22000100.105 115000500.405"], )
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.10")
        head = outs[0].data.decode().split("END OF HEADER")[0]
        self.assertIn(hdr("     2    C1    L1", "# / TYPES OF OBSERV"), head)
        self.assertIn("OBS.HDR.TYPES-FROM-FIRST-DATA-LIST", rep["rules"])
        self.assertEqual(rep["losses"]["epoch-emptied-by-system-removal"]["count"], 1)
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_v3_header_list_without_target_code(self):
        # the same in RINEX 3: BeiDou B1C only (no 3.02 code), then a flag-4 B1I list
        src = lines(hdr("     3.05           OBSERVATION DATA    C (BEIDOU)", "RINEX VERSION / TYPE"),
                    *HEAD[1:], hdr("C    2 C1P L1P", "SYS / # / OBS TYPES"), hdr("C L1P", "SYS / PHASE SHIFT"),
                    hdr("  2026    10     1     0     0    0.0000000     BDT", "TIME OF FIRST OBS"),
                    hdr("", "END OF HEADER"),
                    "> 2026 10 01 00 00  0.0000000  0  1", rec("C11", 23e6, 120e6),
                    "> 2026 10 01 00 00 15.0000000  4  2", hdr("C    2 C2I L2I", "SYS / # / OBS TYPES"),
                    hdr("C L2I", "SYS / PHASE SHIFT"),
                    "> 2026 10 01 00 00 30.0000000  0  1", rec("C11", 23e6 + 100, 120e6 + 500), width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "3.02")
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_collapse_winner_per_list(self):
        # SBAS S5X and S5Q are both RINEX 2 S5: one column is kept per type list. S5X wins in
        # the header's list and loses to S5I in a flag-4 list, so both S5Q and S5X are
        # claimed collapsed; the checker took S5X for lost everywhere and found no column
        # that S5Q could collapse into
        src = lines(hdr("     3.05           OBSERVATION DATA    S (SBAS)", "RINEX VERSION / TYPE"),
                    *HEAD[1:], hdr("S    2 S5X S5Q", "SYS / # / OBS TYPES"), hdr("S", "SYS / PHASE SHIFT"),
                    hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
                    hdr("", "END OF HEADER"),
                    "> 2026 10 01 00 00  0.0000000  0  2", "S20" + F("        41.250") + F("        40.500"),
                    "S27" + F("        38.750") + F("        37.000"),
                    "> 2026 10 01 00 00 15.0000000  4  1", hdr("S    2 S5I S5X", "SYS / # / OBS TYPES"),
                    "> 2026 10 01 00 00 30.0000000  0  1", "S20" + F("        42.250") + F("        43.500"),
                    width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        self.assertEqual(rep["losses"]["obs-code-collapsed:S:S5Q"]["count"], 2)
        self.assertEqual(rep["losses"]["obs-code-collapsed:S:S5X"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)
        # the other column's values in place of the kept one's are caught
        bad = outs[0].data.replace(b"        41.250", b"        40.500")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_obs(src, bad, rep))

    def test_crx_stale_type_label(self):
        # a flag-4 SYS / # / OBS TYPES line leaves its label in RNX2CRX/CRX2RNX's line buffer;
        # a later cycle-slip record shorter than column 79 would be read as a type count
        # (rnx2crx.c E:521, crx2rnx.c C:513): CorruptError CRX.ENC.MAXTYPE, or a wrong
        # count. Written plain with a warning instead (the user's flag-6 choice)
        from rinexcore.rinexfile import open_container
        src = mixed("3.05", "E", "C1C L1C", body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("G05", 22e6, 115e6),
            "> 2026 10 01 00 00 15.0000000  4  1", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
            "> 2026 10 01 00 00 30.0000000  6  1", "G05" + F("  22000100.105"),
            "> 2026 10 01 00 00 45.0000000  0  1", rec("G05", 22e6 + 200, 115e6 + 900)])
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("3.05", "4.02"):
            with self.subTest(target=t):
                plain = convert(src, t, assume_phase_aligned=True)[0][0].data
                outs, rep = convert(src, t, crx=True, assume_phase_aligned=True)  # was: CorruptError
                self.assertFalse(outs[0].report.output["crx"])
                self.assertIn("OBS.CRX.EVENT-PLAIN", [w["rule"] for w in rep["warnings"]])
                self.assertEqual(open_container(outs[0].data).payload, plain)

    def test_crx_picoseconds_that_stop(self):
        # the 4.02 picosecond field is optional per epoch (rinex_4.02.txt Table A3); CRINEX 3.1
        # differences it, so CRX2RNX would repeat the last value where it stops: written
        # plain with a warning (was: CorruptError CRX.ENC.PICOSEC on a valid file)
        from rinexcore.rinexfile import open_container
        src = mixed("4.02", "E", "C1C L1C", body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("G05", 22e6, 115e6),
            "> 2026 10 01 00 00 30.0000000  0  1" + " " * 21 + " 01234", rec("G05", 22e6 + 100, 115e6 + 500),
            "> 2026 10 01 00 01  0.0000000  0  1", rec("G05", 22e6 + 200, 115e6 + 900)])
        self.assertEqual(V.errors(V.validate(src)), [])
        plain = convert(src, "4.02")[0][0].data
        outs, rep = convert(src, "4.02", crx=True)
        self.assertFalse(outs[0].report.output["crx"])
        self.assertIn("OBS.CRX.PICOSEC-PLAIN", [w["rule"] for w in rep["warnings"]])
        self.assertEqual(open_container(outs[0].data).payload, plain)
        outs, rep = convert(src, "4.01")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_v2_codes_a_system_lacks(self):
        # RINEX 2's one list names P2 and D2 for SBAS too, where 2.10 defines neither
        # (rinex211.txt section 10.1.1): without values nothing is lost and no claim is
        # needed; a GLONASS value under C6 (Galileo E6 only in 2.11) is claimed, allowed
        src = v2file("2.10", ["C1", "P2", "D2"], [
            " 26 10  1  0  0  0.0000000  0  2G05S20", "  22000000.105  22000001.205       100.250",
            "  38000000.105"], single="M (MIXED)")
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("3.05", "2.11"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertFalse([k for k in rep["losses"] if k.startswith("obs-code-not-representable:S:")])
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)
        src = v2file("2.11", ["C1", "C6"], [
            " 26 10  1  0  0  0.0000000  0  2G05R05", "  22000000.105", "  21000000.105  21000001.205"],
            single="M (MIXED)")
        self.assertEqual(V.errors(V.validate(src)), [])
        fcn = table_file(tempfile.mkdtemp(), "R05 1\n")
        outs, rep = convert(src, "3.05", glo_fcn=fcn, assume_phase_aligned=True)
        self.assertEqual(rep["losses"]["obs-code-not-representable:R:C6"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


if __name__ == "__main__":
    unittest.main()
