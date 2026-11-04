"""Regression tests for the corpus findings of 2026-10-31 (docs/DECISIONS.md, "corpus run 3
findings"). Each input is written by hand from the spec tables; the real file that showed the
problem is named in each class docstring.
"""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs
from tests.independent.tokens import signal_class

from .test_obs_fixtures import B, F, hdr, lines
from .test_round2 import HEAD, TAIL, obs_file
from .test_validate import d19, nav_v4, payload

MIXED = hdr("     3.05           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE")


def convert(src, target, **kw):
    outs = convert_data(src, "x.rnx", Options(target, compression="none", **kw))
    return outs, outs[0].report.to_dict()


def head_lines(data):
    return data.decode("latin-1").split("END OF HEADER")[0].split("\n")


class PhaseShiftCodeWithoutL(unittest.TestCase):
    """MOBS00AUS/STJ300CAN/VILL00ESP: SYS / PHASE SHIFT codes written '1C' (no type letter).
    The record holds carrier phase codes only (rinex305.txt p.57, 'Carrier phase observation
    code: A3'), so '1C' is L1C: repaired and reported, never dropped."""

    def src(self, entry):
        return obs_file("G    2 C1C L1C", [hdr(entry, "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F(" 115000000.405")])

    def test_validator_flags_it(self):
        for entry in ("G  1C  0.00000", "G 1C   0.00000"):
            with self.subTest(entry=entry):
                rules = [f.rule for f in V.errors(V.validate(self.src(entry)))]
                self.assertEqual(rules, ["VAL.HDR.PHASESHIFT"])

    def test_repaired_for_every_v3_target(self):
        for entry in ("G  1C  0.00000", "G 1C   0.00000"):
            src = self.src(entry)
            for t in ("3.01", "3.04", "3.05"):
                with self.subTest(entry=entry, target=t):
                    outs, rep = convert(src, t)
                    lab = "SYS / PHASE SHIFTS" if t == "3.01" else "SYS / PHASE SHIFT"
                    self.assertIn(hdr("G L1C  0.00000", lab), head_lines(outs[0].data))
                    self.assertEqual([x["rule"] for x in rep["repairs"]], ["HDR.PHASESHIFT.CODE"])
                    self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                    self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class CountColumnsFollowTypes(unittest.TestCase):
    """KOKV00USA 3.03 -> 3.01: a dropped type whose PRN / # OF OBS counts were all 0 kept
    its column, because the count comparison ignores trailing zeros."""

    SRC = lines(
        MIXED, *HEAD[1:],
        hdr("C    3 C2I L2I C1P", "SYS / # / OBS TYPES"),     # C1P: BDS-3 B1C pilot (3.04+)
        hdr("C L2I", "SYS / PHASE SHIFT"),
        hdr("     1", "# OF SATELLITES"),
        hdr("   C05     1     1     0", "PRN / # OF OBS"),
        *TAIL,
        "> 2026 10 01 00 00  0.0000000  0  1",
        ("C05" + F("  38000000.105") + F(" 198000000.405") + B).rstrip(), width=None)

    def test_fixture_is_valid(self):
        self.assertEqual([(f.rule, f.message) for f in V.errors(V.validate(self.SRC))], [])

    def test_counts_lose_the_dropped_column(self):
        outs, rep = convert(self.SRC, "3.02")          # B1C has no 3.02 code
        h = head_lines(outs[0].data)
        self.assertIn(hdr("C    2 C1I L1I", "SYS / # / OBS TYPES"), h)
        self.assertIn(hdr("   C05     1     1", "PRN / # OF OBS"), h)
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])


class LossCountsPerColumn(unittest.TestCase):
    """KMNM00TWN: QZSS C1C/L1C/S1C listed twice, the second column always blank. A count by
    code name credited the blank column with the first one's values (and counted once per
    obs-type list)."""

    def test_empty_duplicate_is_not_a_loss(self):
        src = obs_file("G    3 C1C L1C C1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1",
            ("G05" + F("  22000000.105") + F(" 115000000.405") + B).rstrip()])
        outs, rep = convert(src, "3.05")
        self.assertEqual([k for k in rep["losses"] if k.startswith("obs-code")], [])
        self.assertIn("obs-code-collapsed-empty:G:C1C", rep["normalisations"])
        self.assertIn(hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), head_lines(outs[0].data))
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_loss_counted_once_across_type_lists(self):
        """C1L (GPS L1C) has no RINEX 2.11 code (rinex211.txt §10.1.1); it holds one value
        under each of two obs-type lists: 2 values lost, not 2 per list."""
        src = obs_file("G    3 C1C L1C C1L", [hdr("G L1C", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000000.555"),
            "> 2026 10 01 00 00 15.0000000  4  1",
            hdr("G    4 C1C L1C C1L S1C", "SYS / # / OBS TYPES"),
            "> 2026 10 01 00 00 30.0000000  0  1",
            "G05" + F("  22000100.105") + F(" 115000500.405") + F("  22000100.555") + F("        45.250")])
        self.assertEqual([(f.rule, f.message) for f in V.errors(V.validate(src))], [])
        outs, rep = convert(src, "2.11")
        self.assertEqual(rep["losses"]["obs-code-not-representable:G:C1L"]["count"], 2)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    DUP = obs_file("G    3 C1C L1C C1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
        "> 2026 10 01 00 00  0.0000000  0  1",
        "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000000.555"),
        "> 2026 10 01 00 00 30.0000000  0  1",
        ("G05" + F("  22000100.105") + F(" 115000500.405") + B).rstrip()])

    def test_duplicate_with_values_kept_in_v3(self):
        """A code listed twice whose second column holds a value: RINEX 3/4 lists are per
        system, so both columns are kept (nothing lost)."""
        for t in ("3.05", "3.03", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(self.DUP, t)
                # (to RINEX 4 the 'G L1C' code-only SYS / PHASE SHIFT, 'only reference signals',
                # is dropped as deprecated and claimed, as a zero form is: round 32)
                self.assertEqual(rep["losses"], {} if t < "4" else
                                 {"phase-shift-record-deprecated": {"count": 1, "detail": {}}})
                self.assertIn(hdr("G    3 C1C L1C C1C", "SYS / # / OBS TYPES"), head_lines(outs[0].data))
                self.assertIn("OBS.DUPLICATE-CODE-KEPT", [w["rule"] for w in rep["warnings"]])
                self.assertEqual(compare_obs(self.DUP, outs[0].data, rep), [])

    def test_duplicate_collapse_counted_per_column(self):
        """To RINEX 2 the two columns become one C1: the loss counts the dropped column's
        values (1), not every value of the code (3)."""
        outs, rep = convert(self.DUP, "2.11")
        self.assertEqual(rep["losses"]["obs-code-collapsed:G:C1C"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(self.DUP, outs[0].data, rep), [])


class BeidouBand2In302(unittest.TestCase):
    """WARK00NZL: a 3.02 file writing B1I as C2I (the 3.01 / 3.03+ band digit). Band 2 at
    1561.098 MHz is B1I in every version that defines it (rinex301.txt Table 5 'E2',
    rinex305.txt Table 19), so the independent comparator classes it as B1I too."""

    def test_comparator_class(self):
        for exact in (False, True):
            self.assertTrue(signal_class("3.02", "C", "C2I", exact).startswith("C:C:B1I"))

    def test_converted_and_compared(self):
        src = lines(
            hdr("     3.02           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), *HEAD[1:],
            hdr("C    2 C2I L2I", "SYS / # / OBS TYPES"), hdr("C L2I", "SYS / PHASE SHIFT"), *TAIL,
            "> 2026 10 01 00 00  0.0000000  0  1",
            "C05" + F("  38000000.105") + F(" 198000000.405"), width=None)
        for t in ("3.02", "3.04", "4.02"):
            with self.subTest(target=t):
                # 3.02 'C L2I' with no value: alignment unknown, so 4.02 needs the option
                outs, rep = convert(src, t, assume_phase_aligned=True)
                self.assertIn("OBS.BDS-B1I-BAND", [x["rule"] for x in rep["repairs"]])
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class DeprecatedEventRecords(unittest.TestCase):
    """UZHL00UKR: a flag-4 event holding only 'GLONASS COD/PHS/BIS C2P 0.000', 3.05 -> 4.x.
    The label is defined in 4.x but strongly deprecated and 'should be ignored by RINEX
    decoders and encoders' (rinex_4.00.txt Table A2 p.61): dropped as the header drops it,
    not claimed 'not representable'."""

    def src(self, value):
        return lines(
            MIXED, *HEAD[1:],
            hdr("R    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("R L1C", "SYS / PHASE SHIFT"),
            hdr("  1 R01  1", "GLONASS SLOT / FRQ #"),
            hdr(" C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS"),
            *TAIL,
            "> 2026 10 01 00 00  0.0000000  0  1",
            "R01" + F("  21000000.105") + F(" 112000000.405"),
            "> 2026 10 01 00 00 15.0000000  4  1",
            hdr(f" C2P {value:8.3f}", "GLONASS COD/PHS/BIS"),
            "> 2026 10 01 00 00 30.0000000  0  1",
            "R01" + F("  21000100.105") + F(" 112000500.405"), width=None)

    def test_fixture_is_valid(self):
        self.assertEqual([(f.rule, f.message) for f in V.errors(V.validate(self.src(0)))], [])

    def test_zero_bias_event_dropped_as_deprecated(self):
        src = self.src(0)
        outs, rep = convert(src, "4.02")
        self.assertEqual(rep["losses"]["event-record-deprecated:GLONASS COD/PHS/BIS"]["count"], 1)
        self.assertEqual(rep["losses"]["event-emptied"]["count"], 1)
        self.assertNotIn("event-record-not-representable:GLONASS COD/PHS/BIS", rep["losses"])
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_nonzero_bias_event_kept(self):
        outs, rep = convert(self.src(-10.5), "4.02")
        self.assertIn(b" C2P  -10.500", outs[0].data.split(b"END OF HEADER")[1])
        self.assertEqual(allowed_check(rep), [])


class QzssIonArea(unittest.TestCase):
    """BRD400DLR: QZSS CNVX ION records need WIDE or JAPN from 4.02 (rinex_4.02.txt Table 25
    p.40, Table A35 note 3*). 4.00/4.01 have no subtype field, but ION MESSAGE LINE - 2 holds
    a 'Region code: 0 or blank (wide area parameters), 1 (QZSS only - Japan area
    coefficients)' (rinex_4.00.txt Table A32 l.5908 p.104; rinex_4.01.txt l.6190 p.108):
    round 32, the area was read as unknown before."""

    J_CNVX = ["> ION J01 CNVX", "    2026 10 30 00 00 00" + d19(1e-8, "E") * 3,
              "    " + d19(1.0, "E") * 4, "    " + d19(1.0, "E")]

    def test_400_to_402_drops_area_unknown(self):
        # a blank Region code is wide area: CNVX WIDE, nothing lost (round 32; it was dropped)
        src = payload(nav_v4("4.00", "D") + [x.replace("E", "D") if x[0] != ">" else x for x in self.J_CNVX])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "4.02")
        self.assertNotIn("nav-correction-not-representable:ION:CNVX-area-unknown:J", rep["losses"])
        self.assertIn(b"\n> ION J01 CNVX WIDE\n", outs[0].data)
        self.assertEqual(rep["rules"]["NAV.ION.REGION-TO-SUBTYPE"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        # a code that names no area (neither 0, blank nor 1) is still dropped and claimed
        bad = [*self.J_CNVX[:3], "    " + d19(1.0, "E") + d19(2.0, "E")]
        src = payload(nav_v4("4.00", "D") + [x.replace("E", "D") if x[0] != ">" else x for x in bad])
        outs, rep = convert(src, "4.02")
        self.assertEqual(rep["losses"]["nav-correction-not-representable:ION:CNVX-area-unknown:J"]["count"], 1)
        self.assertNotIn(b"> ION J01 CNVX", outs[0].data)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_402_to_401_strips_subtype(self):
        # the subtype goes, its area stays as the Region code: WIDE is 0 (round 32: the subtype
        # was claimed lost)
        src = payload(nav_v4("4.02"))
        outs, rep = convert(src, "4.01")
        out = outs[0].data.decode()
        self.assertIn("\n> ION J01 CNVX\n", out)
        self.assertNotIn("WIDE", out)
        self.assertNotIn("nav-subtype-not-representable:ION:J:CNVX", rep["losses"])
        k = out.split("\n").index("> ION J01 CNVX")
        self.assertEqual(out.split("\n")[k + 3][23:42], " 0.000000000000E+00")
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assertEqual([f.rule for f in V.validate(outs[0].data) if "subtype" in f.message], [])
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


class NonstandardHeaderRecordSameVersion(unittest.TestCase):
    """HRAG00ZAF: a 3.05 file (JPS2RIN 2.1) with DOI, which RINEX defines from 4.00 only."""

    SRC = obs_file("G    2 C1C L1C", [hdr("https://doi.org/10.00000/test", "DOI"),
                                      hdr("G L1C", "SYS / PHASE SHIFT")], [
        "> 2026 10 01 00 00  0.0000000  0  1",
        "G05" + F("  22000000.105") + F(" 115000000.405")])

    def test_same_version_carries_it(self):
        outs, rep = convert(self.SRC, "3.05")
        self.assertIn(hdr("https://doi.org/10.00000/test", "DOI"), head_lines(outs[0].data))
        self.assertEqual(rep["losses"], {})
        # corpus run 5: the independent check still required the drop in a same-version
        # conversion
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])

    def test_same_version_drop_is_caught(self):
        outs, rep = convert(self.SRC, "3.05")
        doi = hdr("https://doi.org/10.00000/test", "DOI").encode() + b"\n"
        bad = outs[0].data.replace(doi, b"")
        self.assertNotEqual(bad, outs[0].data)
        claimed = dict(rep, losses={"header-record-not-representable:DOI": {"count": 1, "examples": []}})
        self.assertNotEqual(compare_obs(self.SRC, bad, claimed), [])
        unruled = dict(rep, rules={k: v for k, v in rep["rules"].items() if k != "OBS.HDR.NONSTANDARD-CARRIED"})
        self.assertNotEqual(compare_obs(self.SRC, outs[0].data, unruled), [])

    def test_other_v3_version_reports_it(self):
        outs, rep = convert(self.SRC, "3.04")
        self.assertEqual(rep["losses"]["header-record-not-representable:DOI"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])

    def test_v4_keeps_it(self):
        outs, rep = convert(self.SRC, "4.02")
        self.assertIn(hdr("https://doi.org/10.00000/test", "DOI"), head_lines(outs[0].data))


class EventOfDroppedSystem(unittest.TestCase):
    """DLF100NLD 3.03 -> 3.01: a flag-4 event holding only 'J L2X 0.25000 SYS / PHASE SHIFT'.
    QZSS is defined from 3.02 (absent from rinex301.txt), so the system and its event go;
    the emptied event is justified by the system loss, which the loss table did not accept."""

    def src(self, entry):
        return lines(
            hdr("     3.03           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), *HEAD[1:],
            hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("J    2 C1C L1C", "SYS / # / OBS TYPES"),
            hdr("G L1C", "SYS / PHASE SHIFT"), hdr("J L1C", "SYS / PHASE SHIFT"),
            *TAIL,
            "> 2026 10 01 00 00  0.0000000  0  2",
            "G05" + F("  22000000.105") + F(" 115000000.405"),
            "J01" + F("  38000000.105") + F(" 199000000.405"),
            "> 2026 10 01 00 00 15.0000000  4  1",
            hdr(entry, "SYS / PHASE SHIFT"),
            "> 2026 10 01 00 00 30.0000000  0  2",
            "G05" + F("  22000100.105") + F(" 115000500.405"),
            "J01" + F("  38000100.105") + F(" 199000500.405"), width=None)

    def test_fixture_is_valid(self):
        self.assertEqual([(f.rule, f.message) for f in V.errors(V.validate(self.src("J L1C  0.25000")))], [])

    def test_qzss_event_emptied_with_the_system(self):
        src = self.src("J L1C  0.25000")
        outs, rep = convert(src, "3.01")
        self.assertIn("system-not-representable:J", rep["losses"])
        self.assertEqual(rep["losses"]["event-emptied"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_kept_system_event_dropped_is_caught(self):
        # a converter that empties a GPS phase-shift event the 3.01 output could hold
        src = self.src("G L1C  0.25000")
        outs, rep = convert(src, "3.01")
        self.assertIn(b"G L1C  0.25000", outs[0].data.split(b"END OF HEADER")[1])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        body = outs[0].data.split(b"END OF HEADER")[1].split(b"\n")
        i = next(k for k, x in enumerate(body) if x.startswith(b">") and x[31:32] == b"4")
        bad = outs[0].data.split(b"END OF HEADER")[0] + b"END OF HEADER" + b"\n".join(body[:i] + body[i + 2:])
        emptied = dict(rep, losses=dict(rep["losses"], **{"event-emptied": {"count": 1, "examples": []},
                                                          "system-not-representable:J": {"count": 1,
                                                                                         "examples": []}}))
        self.assertNotEqual(compare_obs(src, bad, emptied), [])


class DropUnresolvableReport(unittest.TestCase):
    """--drop-unresolvable retries the conversion without GLONASS: the first attempt's report
    entries were kept, so every code mapping counted twice and the removed system's
    assumptions stayed in the report."""

    def test_entries_counted_once(self):
        from .test_obs_fixtures import V211
        outs, rep = convert(V211, "3.05", drop_unresolvable=True)
        self.assertEqual(rep["outcome"], "converted-with-removal")
        self.assertEqual({a["count"] for a in rep["assumptions"]}, {1})
        self.assertFalse([a for a in rep["assumptions"] if a["category"].endswith(":R")
                          or a["detail"].startswith("R:")])


class InheritedErrorsVisible(unittest.TestCase):
    """Review round 3 (Sonnet): an output that keeps an input's validator error must say so in
    the one-line summary the CLI prints, and the report carries each finding's text."""

    def test_summary_and_findings(self):
        bad = lines(*[h for h in HEAD if "OBSERVER / AGENCY" not in h],
                    hdr("G    1 C1C", "SYS / # / OBS TYPES"), hdr("G", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"), width=None)
        outs, rep = convert(bad, "3.05")
        self.assertIn("validator error(s) the input already had (VAL.HDR.MANDATORY)",
                      outs[0].report.summary())
        self.assertIn("OBSERVER / AGENCY", " ".join(f["message"] for f in rep["validation"]["findings"]))


class SolRound3(unittest.TestCase):
    """Review round 3 (Sol) blockers, each from the reviewer's reproduction."""

    def test_phase_only_in_a_later_type_list_needs_alignment(self):
        """1: a 3.00 file whose phase type arrives by flag 4 must not reach RINEX 4 without an
        alignment decision (rinex_4.00.txt §5.2.12)."""
        from rinexcore.errors import MissingInformationError
        src = lines(hdr("     3.00           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), *HEAD[1:],
                    hdr("G    1 C1C", "SYS / # / OBS TYPES"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"),
                    "> 2026 10 01 00 00 15.0000000  4  1", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
                    "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405"),
                    width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        with self.assertRaises(MissingInformationError):
            convert(src, "4.02")
        outs, rep = convert(src, "4.02", assume_phase_aligned=True)
        self.assertIn(("phase-alignment", "G"), [(a["category"], a["detail"]) for a in rep["assumptions"]])
        # 3.05: the system has phases, so its SYS / PHASE SHIFT is the "unknown" form
        outs, rep = convert(src, "3.05")
        self.assertIn(hdr("G", "SYS / PHASE SHIFT"), head_lines(outs[0].data))
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])

    BDS = lines(hdr("     3.02           OBSERVATION DATA    C (BEIDOU)", "RINEX VERSION / TYPE"), *HEAD[1:],
                hdr("C    2 C1I L1I", "SYS / # / OBS TYPES"), hdr("C L1I  0.00000", "SYS / PHASE SHIFT"),
                hdr("  2026    10     1     0     0    0.0000000     BDT", "TIME OF FIRST OBS"),
                hdr("", "END OF HEADER"),
                "> 2026 10 01 00 00  0.0000000  0  1", "C05" + F("  38000000.105") + F(" 198000000.405"),
                "> 2026 10 01 00 00 15.0000000  4  1", hdr("C L1I  0.25000", "SYS / PHASE SHIFT"),
                "> 2026 10 01 00 00 30.0000000  0  1", "C05" + F("  38000100.105") + F(" 198000500.405"),
                width=None)

    def test_event_phase_shift_renamed_with_the_header(self):
        """2: BDS B1I is L1I in 3.02 and L2I from 3.03; an event's SYS / PHASE SHIFT follows."""
        self.assertEqual(V.errors(V.validate(self.BDS)), [])
        outs, rep = convert(self.BDS, "3.05")
        body = outs[0].data.decode().split("END OF HEADER")[1]
        self.assertIn(hdr("C L2I  0.25000", "SYS / PHASE SHIFT"), body)
        self.assertEqual(compare_obs(self.BDS, outs[0].data, rep), [])
        # the independent check catches an event entry left in the source's spelling
        stale = outs[0].data.replace(b"C L2I  0.25000", b"C L1I  0.25000")
        self.assertTrue(any("names no observation type" in x for x in compare_obs(self.BDS, stale, rep)))

    def test_event_picoseconds_lost_are_reported(self):
        """3: a 4.02 flag-5 event with picoseconds, written as 4.01."""
        ev = "> 2026 10 01 00 00 10.0000000  5  0" + " " * 22 + "12345"
        src = lines(hdr("     4.02           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), *HEAD[1:],
                    hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("    18", "LEAP SECONDS"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405"),
                    ev,
                    "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405"),
                    width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "4.01")
        self.assertEqual(rep["losses"]["epoch-precision"]["count"], 1)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        self.assertEqual(allowed_check(rep), [])

    def test_extra_correction_claim_needs_a_kept_one(self):
        """5: deleting the only GPUT and calling it 'extra' must not pass."""
        from .test_nav_fixtures import SPEC_305
        outs, rep = convert(SPEC_305, "3.04")
        self.assertEqual(compare_nav(SPEC_305, [outs[0].data], rep), [])
        bad = b"".join(x for x in outs[0].data.splitlines(True) if b"TIME SYSTEM CORR" not in x)
        rep["losses"]["nav-correction-extra:STO:GPUT"] = {"count": 1, "detail": {}}
        self.assertTrue(compare_nav(SPEC_305, [bad], rep))

    def test_malformed_value_refused_by_default(self):
        """4: '12.3.4' in an F14.3 field passes the reader's character check; data damage is an
        error by default (PLAN §1 clause 9), --lenient carries it with a warning."""
        from rinexcore.errors import CorruptError
        src = obs_file("G    2 C1C L1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("        12.3.4") + F(" 115000000.405")])
        with self.assertRaises(CorruptError) as cm:
            convert(src, "3.04")
        self.assertEqual(cm.exception.outcome, "refused-corrupt")
        outs, rep = convert(src, "3.04", lenient=True)
        self.assertIn("VAL.INHERITED", [w["rule"] for w in rep["warnings"]])

    def test_damage_the_output_would_hide(self):
        """Text after column 80 of a nav record line: the writer drops it, so the output is
        clean and only the input shows the damage. Checked on the input before converting."""
        from rinexcore.errors import CorruptError
        from .test_nav_fixtures import SPEC_305
        L = SPEC_305.decode().split("\n")
        k = next(i for i, x in enumerate(L) if "END OF HEADER" in x) + 2
        L[k] += " 1.5"
        src = "\n".join(L).encode()
        with self.assertRaises(CorruptError) as cm:
            convert(src, "3.04")
        self.assertEqual(cm.exception.rule, "VAL.NAV.LAYOUT")
        outs, rep = convert(src, "3.04", lenient=True)
        self.assertIn("VAL.INPUT-DAMAGE", [w["rule"] for w in rep["warnings"]])

    def test_met_values_off_their_columns(self):
        """mate1800.03m (corpus): HR written F8.2 ('   73.91'), so F7.1 columns read 73.9 and
        a stray '1'. Refused by default; --lenient reads the values by pattern, reported."""
        from rinexcore.errors import CorruptError
        from .test_validate import met
        good = met("2.11", ("PR", "TD", "HR"))
        txt = good.decode() if isinstance(good, bytes) else "\n".join(good) + "\n"
        head, body = txt.split("END OF HEADER")
        first = body.split("\n")[1]
        bad_line = first[:18] + "  956.8  +21.8   73.91"
        src = (head + "END OF HEADER" + body.replace(first, bad_line, 1)).encode("latin-1")
        with self.assertRaises(CorruptError) as cm:
            convert(src, "3.05")
        self.assertEqual(cm.exception.rule, "MET.DATA.COLUMNS")
        outs, rep = convert(src, "3.05", lenient=True)
        self.assertIn("  73.91", outs[0].data.decode())
        self.assertIn("MET.DATA.COLUMNS", [x["rule"] for x in rep["repairs"]])

    def test_counts_of_a_code_listed_twice(self):
        """6: C1C L1C C1C with counts 2 2 1 keeps 2 2 1 (counted per column, not summed)."""
        src = obs_file("G    3 C1C L1C C1C", [hdr("G L1C", "SYS / PHASE SHIFT"), hdr("     1", "# OF SATELLITES"),
                                              hdr("   G05     2     2     1", "PRN / # OF OBS")], [
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000000.555"),
            "> 2026 10 01 00 00 30.0000000  0  1",
            ("G05" + F("  22000100.105") + F(" 115000500.405") + B).rstrip()])
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("3.05", "4.02"):
            outs, rep = convert(src, t)
            self.assertIn(hdr("   G05     2     2     1", "PRN / # OF OBS"), head_lines(outs[0].data))


class HeaderRecordsInEvents(unittest.TestCase):
    """A flag-4 event may carry any header record (rinex305.txt §5.3.2). LEAP SECONDS, TIME OF
    FIRST OBS and GLONASS SLOT / FRQ # were dropped with a false 'not representable' claim
    (found while checking review round 3; no corpus file has one)."""

    def src(self, label, content):
        return obs_file("G    2 C1C L1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405"),
            "> 2026 10 01 00 00 15.0000000  4  1", hdr(content, label),
            "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405")])

    def test_carried_where_defined(self):
        cases = (("LEAP SECONDS", "    18    18  2185     7GPS", ("3.04", "4.02")),
                 ("TIME OF FIRST OBS", "  2026    10     1     0     0   15.0000000     GPS", ("3.04", "2.11")),
                 ("GLONASS SLOT / FRQ #", "  1 R01  1", ("3.04", "4.02")))
        for label, content, targets in cases:
            src = self.src(label, content)
            self.assertEqual(V.errors(V.validate(src)), [])
            for t in targets:
                with self.subTest(label=label, target=t):
                    outs, rep = convert(src, t)
                    self.assertIn(hdr(content, label), outs[0].data.decode().split("END OF HEADER")[1])
                    self.assertEqual(allowed_check(rep), [])
                    self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_leap_seconds_fields_to_v2(self):
        src = self.src("LEAP SECONDS", "    18    18  2185     7GPS")
        outs, rep = convert(src, "2.11")
        self.assertIn(hdr("    18", "LEAP SECONDS"), outs[0].data.decode().split("END OF HEADER")[1])
        self.assertIn("header-field-not-representable:LEAP SECONDS", rep["losses"])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        rep["losses"].pop("header-field-not-representable:LEAP SECONDS")
        self.assertTrue(compare_obs(src, outs[0].data, rep))      # an unclaimed drop is caught


class EmptyPhaseShiftRecord(unittest.TestCase):
    """CMUM00THA (3.02, JAXA dconv): a wholly blank 'SYS / PHASE SHIFT' line. Every form the
    spec defines names the system, 'unknown' included (rinex302.txt Table A2, p.41-42), so the
    line records nothing: left out (repair), alignment not recorded. Sonnet round 4: all 11
    targets were refused-corrupt, with no option to convert it."""

    BLANK = hdr("", "SYS / PHASE SHIFT")

    def src(self, phase):
        return lines(
            hdr("     3.02           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), *HEAD[1:],
            hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("E    2 C1X L1X", "SYS / # / OBS TYPES"),
            *phase, *TAIL,
            "> 2026 10 01 00 00  0.0000000  0  2",
            "G05" + F("  22000000.105") + F(" 115000000.405"),
            "E11" + F("  25000000.105") + F(" 131000000.405"), width=None)

    def test_validator_flags_it(self):
        self.assertEqual([f.rule for f in V.errors(V.validate(self.src([self.BLANK])))],
                         ["VAL.HDR.PHASESHIFT"])
        orphan = hdr("                  G01 G02", "SYS / PHASE SHIFT")
        self.assertEqual([f.rule for f in V.errors(V.validate(self.src([orphan])))],
                         ["VAL.HDR.PHASESHIFT"])
        ok = [hdr("G L1C  0.00000  02 G01 G02", "SYS / PHASE SHIFT"), hdr("E L1X", "SYS / PHASE SHIFT")]
        self.assertEqual(V.errors(V.validate(self.src(ok))), [])

    def test_v3_targets_write_the_unknown_form(self):
        src = self.src([self.BLANK])
        for t in ("3.01", "3.02", "3.05"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                lab = "SYS / PHASE SHIFTS" if t == "3.01" else "SYS / PHASE SHIFT"
                head = head_lines(outs[0].data)
                self.assertEqual([x for x in head if lab in x], [hdr("G", lab), hdr("E", lab)])
                self.assertEqual([x["rule"] for x in rep["repairs"]], ["HDR.PHASESHIFT.EMPTY"])
                self.assertEqual(sorted(a["detail"] for a in rep["assumptions"]
                                        if a["category"] == "phase-alignment"), ["E:unknown", "G:unknown"])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_assume_flag_does_not_turn_it_into_zeros(self):
        # corpus run 8: with --assume-phase-aligned the fallback wrote 'G L1C 0', which a
        # source record of explicit 'unknown' ('G' alone) never gets; the flag is for 4.x
        # targets (PLAN §3.3 rule 2), and within 3.01-3.05 nothing is synthesised
        for phase in ([self.BLANK], [hdr("G", "SYS / PHASE SHIFT"), hdr("E", "SYS / PHASE SHIFT")]):
            src = self.src(phase)
            for t in ("3.02", "3.05"):
                with self.subTest(target=t, blank=phase == [self.BLANK]):
                    outs, rep = convert(src, t, assume_phase_aligned=True)
                    head = head_lines(outs[0].data)
                    self.assertEqual([x for x in head if "SYS / PHASE SHIFT" in x],
                                     [hdr("G", "SYS / PHASE SHIFT"), hdr("E", "SYS / PHASE SHIFT")])
                    self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_v2_and_v4_targets(self):
        from rinexcore.errors import MissingInformationError, RinexError
        src = self.src([self.BLANK])
        outs, rep = convert(src, "2.11")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        with self.assertRaises(MissingInformationError):
            convert(src, "4.02")                 # unknown alignment: the user decides
        outs, rep = convert(src, "4.02", assume_phase_aligned=True)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        with self.assertRaises(RinexError):
            convert(src, "3.05", strict=True)    # --strict refuses every repair

    def test_carried_records_unchanged(self):
        # a file with real entries keeps them as written; only the blank line goes
        src = self.src([hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), self.BLANK, hdr("E L1X", "SYS / PHASE SHIFT")])
        outs, rep = convert(src, "3.05")
        head = head_lines(outs[0].data)
        self.assertEqual([x for x in head if "SYS / PHASE SHIFT" in x],
                         [hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), hdr("E L1X", "SYS / PHASE SHIFT")])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class GalileoIonFourthSlot(unittest.TestCase):
    """CKIS00COK round trip: IONOSPHERIC CORR GAL is 'ai0, ai1, ai2, zero' in 3.00-3.02
    (rinex302.txt l.3289) and 'ai0, ai1, ai2, Blank' from 3.03 (rinex305.txt l.3641)."""

    def gal(self, target):
        outs, _ = convert(payload(nav_v4("4.02")), target)
        return [x for x in head_lines(outs[0].data) if x.startswith("GAL ")][0]

    def test_zero_before_303(self):
        self.assertEqual(self.gal("3.02")[41:53], "  0.0000D+00")

    def test_blank_from_303(self):
        self.assertEqual(self.gal("3.05")[41:53], " " * 12)


if __name__ == "__main__":
    unittest.main()
