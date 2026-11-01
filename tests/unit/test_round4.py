"""Regression tests for review round 4 (2026-10-31, docs/DECISIONS.md "review round 4 fixes"):
Sol's five blockers and polish, each from the reviewer's reproduction, plus a mutation the
independent checks must catch where the fix is in the checker."""

import os
import tempfile
import unittest

from rinexconv.engine import Options, convert_data, convert_loaded, load_bytes
from rinexcore import validate as V
from rinexcore.errors import CorruptError, MissingInformationError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs

from .test_nav_fixtures import L as nav_lines, SPEC_305, hdr as nhdr
from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL
from .test_round3 import SolRound3, convert, head_lines

H402 = [hdr("     4.02           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE")] + HEAD[1:]


class PhaseAlignmentFromEvents(unittest.TestCase):
    """Sol 1: phase alignment came from the header only. SYS / PHASE SHIFT in an event holds
    from that epoch on ('each value remains valid until changed by an additional header
    record', rinex305.txt Â§6.5 p.41)."""

    ALIGNED_THEN_UNKNOWN = lines(
        *HEAD, hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), *TAIL,
        "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405"),
        "> 2026 10 01 00 00 15.0000000  4  2", hdr("G    3 C1C L1C L2W", "SYS / # / OBS TYPES"),
        hdr("G", "SYS / PHASE SHIFT"),
        "> 2026 10 01 00 00 30.0000000  0  1",
        "G05" + F("  22000100.105") + F(" 115000500.405") + F("  89000000.123"), width=None)

    PHASE_LATER_402 = lines(
        *H402, hdr("G    1 C1C", "SYS / # / OBS TYPES"), *TAIL,
        "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"),
        "> 2026 10 01 00 00 15.0000000  4  1", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
        "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405"), width=None)

    def test_event_unknown_needs_the_override_for_v4(self):
        src = self.ALIGNED_THEN_UNKNOWN
        self.assertEqual(V.errors(V.validate(src)), [])
        with self.assertRaises(MissingInformationError):
            convert(src, "4.02")
        outs, rep = convert(src, "4.02", assume_phase_aligned=True)
        self.assertIn(("phase-alignment", "G"), [(a["category"], a["detail"]) for a in rep["assumptions"]])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        # RINEX 3 targets carry the event record as written
        outs, rep = convert(src, "3.04")
        self.assertIn(hdr("G", "SYS / PHASE SHIFT"), outs[0].data.decode().split("END OF HEADER")[1])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_v4_phase_only_in_a_later_list_to_v3(self):
        src = self.PHASE_LATER_402
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("3.01", "3.02", "3.05"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)      # was: AssertionError, mandatory record missing
                lab = "SYS / PHASE SHIFTS" if t == "3.01" else "SYS / PHASE SHIFT"
                self.assertIn(hdr("G L1C  0.00000", lab), head_lines(outs[0].data))
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_v4_code_only_to_v3(self):
        src = lines(*H402, hdr("G    1 C1C", "SYS / # / OBS TYPES"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105"), width=None)
        outs, rep = convert(src, "3.05")
        self.assertIn(hdr("G", "SYS / PHASE SHIFT"), head_lines(outs[0].data))
        self.assertIn("OBS.PHASESHIFT.NO-PHASE-TYPES", rep["rules"])
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class SaturatedCounts(unittest.TestCase):
    """Sol 2: '99999 indicates >= 99999 observations' only from 3.01 (rinex301.txt Table A2
    l.2157); RINEX 2 and 3.00 give the count (rinex211.txt Table A1, I6). A 2 Hz input of
    100,000 epochs."""

    @classmethod
    def setUpClass(cls):
        body = []
        for k in range(100000):
            t = k * 0.5
            h, rest = divmod(t, 3600)
            m, s = divmod(rest, 60)
            body.append(f"> 2026 10 01 {int(h):02d} {int(m):02d}{s:11.7f}  0  1")
            body.append("G05" + F("  22000000.105"))
        cls.src = lines(*HEAD, hdr("G    1 C1C", "SYS / # / OBS TYPES"), hdr("     1", "# OF SATELLITES"),
                        hdr("   G05 99999", "PRN / # OF OBS"), *TAIL, *body, width=None)
        cls.ld = load_bytes(cls.src, False)

    def out(self, t):
        o = convert_loaded(self.ld, "x.rnx", Options(t, compression="none"))
        return o[0].data, o[0].report.to_dict()

    def test_exact_before_301_saturated_from_301(self):
        for t, want in (("2.11", "100000"), ("3.00", "100000"), ("3.01", " 99999"), ("3.05", " 99999")):
            with self.subTest(target=t):
                data, rep = self.out(t)
                prn = [x for x in head_lines(data) if "PRN / # OF OBS" in x]
                self.assertEqual(len(prn), 1)
                self.assertEqual(prn[0][6:12], want)
                self.assertEqual(V.errors(V.validate(data)), [])

    def test_validator_and_checker_reject_99999_before_301(self):
        data, rep = self.out("2.11")
        self.assertIn(b"   G 5100000", data)
        bad = data.replace(b"   G 5100000", b"   G 5 99999", 1)
        self.assertIn("VAL.HDR.PRN-NUM-OBS", [f.rule for f in V.errors(V.validate(bad))])
        self.assertEqual(compare_obs(self.src, data, rep), [])
        self.assertTrue(compare_obs(self.src, bad, rep))
        # from 3.01 the independent recount accepts the sentinel (Sol polish 1)
        data, rep = self.out("3.05")
        self.assertEqual(compare_obs(self.src, data, rep), [])


class MergedInputPolicy(unittest.TestCase):
    """Sol 3: a merge input skipped the damage check, so text after column 80 vanished."""

    def setUp(self):
        Lns = SPEC_305.decode().split("\n")
        k = next(i for i, x in enumerate(Lns) if "END OF HEADER" in x) + 2
        Lns[k] += " 1.5"
        fd, self.path = tempfile.mkstemp(suffix=".rnx")
        with os.fdopen(fd, "wb") as fh:
            fh.write("\n".join(Lns).encode())

    def tearDown(self):
        os.unlink(self.path)

    def test_merge_input_damage_refused(self):
        with self.assertRaises(CorruptError) as cm:
            convert_data(SPEC_305, "x.rnx", Options("3.05", compression="none", merge=[self.path]))
        self.assertEqual(cm.exception.rule, "NAV.MERGE.INPUT")
        self.assertIn("VAL.NAV.LAYOUT", str(cm.exception))
        outs = convert_data(SPEC_305, "x.rnx", Options("3.05", compression="none", merge=[self.path],
                                                        lenient=True))
        self.assertIn("VAL.INPUT-DAMAGE", [w["rule"] for w in outs[0].report.to_dict()["warnings"]])


class PhaseValuesChecked(unittest.TestCase):
    """Sol 4: the independent checks compared no SYS / PHASE SHIFT values or satellites."""

    def test_event_value_change_caught(self):
        src = SolRound3.BDS
        outs, rep = convert(src, "3.05")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        bad = outs[0].data.replace(b"C L2I  0.25000", b"C L2I  0.50000")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(any("is no input entry" in x for x in compare_obs(src, bad, rep)))

    def test_header_value_and_satellites_caught(self):
        from .test_round2 import obs_file
        src = obs_file("G    2 C1C L1C", [hdr("G L1C -0.25000  02 G05 G07", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405")])
        for t in ("3.03", "3.05", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        outs, rep = convert(src, "3.04")
        for old, new in ((b"G L1C -0.25000  02 G05 G07", b"G L1C  0.25000  02 G05 G07"),
                         (b"G L1C -0.25000  02 G05 G07", b"G L1C -0.25000  02 G05 G08"),
                         (b"G L1C -0.25000  02 G05 G07", b"G L1C                     ")):
            bad = outs[0].data.replace(old, new)
            self.assertNotEqual(bad, outs[0].data)
            self.assertTrue(compare_obs(src, bad, rep), new)

    def test_generated_forms_checked(self):
        # v2 -> 3.05 writes 'unknown' per system; an output claiming 'aligned' without the
        # --assume-phase-aligned assumption is caught
        from .test_round2 import obs_file
        v2, _ = convert(obs_file("G    2 C1C L1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405")]), "2.11")
        src = v2[0].data
        outs, rep = convert(src, "3.05")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        txt = outs[0].data.decode()
        self.assertIn(hdr("G", "SYS / PHASE SHIFT"), txt)
        bad = txt.replace(hdr("G", "SYS / PHASE SHIFT"), hdr("G L1C  0.00000", "SYS / PHASE SHIFT")).encode()
        self.assertTrue(compare_obs(src, bad, rep))
        # with --assume-phase-aligned the zero form is reported, and dropping a code is caught
        outs, rep = convert(src, "3.05", assume_phase_aligned=True)
        self.assertIn(hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), outs[0].data.decode())
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        bad = outs[0].data.replace(hdr("G L1C  0.00000", "SYS / PHASE SHIFT").encode() + b"\n", b"")
        self.assertTrue(compare_obs(src, bad, rep))


class ComparatorMustFail(unittest.TestCase):
    """Sonnet round 5 polish 3: the independent checks are regression-tested themselves. Every
    mutation of a correct output below must be caught; the unmutated output must pass. (Clock,
    event, epoch, header-record and PRN-count mutations: test_independent_meta.py; phase
    shifts and nav message types: the classes above.)"""

    def outputs(self):
        from .test_obs_fixtures import V305
        pos = dict(approx_position=(4027894.006, 307045.6, 4919474.91))
        for t, kw in (("3.04", {}), ("4.02", {"assume_phase_aligned": True}), ("2.11", pos)):
            outs, rep = convert(V305, t, **kw)
            yield t, V305, outs[0].data, rep

    V3_MUTATIONS = [
        ("value", b"G05  22000000.105", b"G05  22000000.106"),
        ("lli", b" 115000000.40517", b" 115000000.40527"),
        ("ssi", b"G05  22000000.105 7", b"G05  22000000.105 5"),
        ("satellite", b"\nG12  21000000.112", b"\nG13  21000000.112"),
        ("epoch time", b"> 2026 10 01 00 00 30.0000000", b"> 2026 10 01 00 00 31.0000000"),
        ("signal attribute", b"C1C C1W C2W L1C L2W", b"C1C C1W C2X L1C L2W"),
        ("header field", b"TEST                                                        MARKER NAME",
         b"TEXT                                                        MARKER NAME"),
    ]
    V2_MUTATIONS = [
        ("value", b"  22000000.105 7", b"  22000000.106 7"),
        ("lli", b" 115000000.40517", b" 115000000.40527"),
        ("satellite", b"G 5G12R 7", b"G 5G13R 7"),
        ("epoch time", b" 26 10  1  0  0 30.0000000", b" 26 10  1  0  0 31.0000000"),
        ("obs type", b"C1    P1    P2", b"C1    P1    C2"),
    ]

    def test_baselines_pass(self):
        for t, src, out, rep in self.outputs():
            with self.subTest(target=t):
                self.assertEqual(compare_obs(src, out, rep), [])

    def test_mutations_caught(self):
        for t, src, out, rep in self.outputs():
            for name, old, new in (self.V2_MUTATIONS if t < "3" else self.V3_MUTATIONS):
                with self.subTest(target=t, mutation=name):
                    self.assertIn(old, out)
                    bad = out.replace(old, new, 1)
                    self.assertTrue(compare_obs(src, bad, rep))

    def test_phase_shift_claiming_alignment_caught(self):
        from .test_obs_fixtures import V305
        outs, rep = convert(V305, "3.04")
        g = hdr("G", "SYS / PHASE SHIFT").encode()
        self.assertIn(g, outs[0].data)
        bad = outs[0].data.replace(g, hdr("G L1C  0.00000", "SYS / PHASE SHIFT").encode())
        self.assertTrue(compare_obs(V305, bad, rep))


class CheckerFalseAlarms(unittest.TestCase):
    """Two checker changes of corpus run 5 (verify3_changes.md item 13) flagged correct
    output on the recheck of the touched rows."""

    def test_301_label_in_a_302_file_same_version(self):
        # BRUX00BEL / KOUR00GUF / MAS100ESP: 3.02 files with the 3.01 spelling, repaired
        src = lines(hdr("     3.02           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), *HEAD[1:],
                    hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("G L1C", "SYS / PHASE SHIFTS"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405"),
                    width=None)
        outs, rep = convert(src, "3.02")
        self.assertIn("HDR.PHASESHIFT.LABEL", [x["rule"] for x in rep["repairs"]])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])

    def test_phase_only_event_to_targets_without_event_phase_records(self):
        # BOGI00POL / MET300FIN / POTS00DEU: events holding only SYS / PHASE SHIFT, to 3.00
        # (not defined) and RINEX 4 (deprecated)
        src = lines(hdr("     3.03           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), *HEAD[1:],
                    hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405"),
                    "> 2026 10 01 00 00 15.0000000  4  1", hdr("G L1C  0.25000", "SYS / PHASE SHIFT"),
                    "> 2026 10 01 00 00 30.0000000  0  1", "G05" + F("  22000100.105") + F(" 115000500.405"),
                    width=None)
        for t in ("3.00", "4.00", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertEqual(rep["losses"]["event-emptied"]["count"], 1)
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_obs(src, outs[0].data, rep), [])
        # 3.05 carries it; emptying it there is still caught
        outs, rep = convert(src, "3.05")
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class GalileoMessageIdentity(unittest.TestCase):
    """Sol 5: the nav comparison ignored message types, so INAV -> FNAV passed."""

    def src(self, bits):
        rec = ["E01 2026 10 01 00 00 00-6.651098374277D-06-5.115907697473D-13 0.000000000000D+00",
               "     6.400000000000D+01 3.343750000000D+00 2.339383158984D-09-1.028423514356D+00",
               "     2.309679985046D-07 9.007973130792D-05 9.784474968910D-06 5.440611940384D+03",
               "     3.456000000000D+05-1.490116119385D-07 6.681256221140D-01-1.676380634308D-08",
               "     9.975879822523D-01 1.494687500000D+02 2.157772554722D+00-5.180215776780D-09",
               "    -3.410856361573D-10" + f"{bits / 1000:.12f}D+03".rjust(19)
               + " 2.385000000000D+03 0.000000000000D+00",
               "     3.120000000000D+00 0.000000000000D+00-6.286427378654D-09-7.683411240578D-09",
               "     3.462640000000D+05"]
        return nav_lines(nhdr("     3.05           N: GNSS NAV DATA    E: GALILEO", "RINEX VERSION / TYPE"),
                         nhdr("", "END OF HEADER"), *rec)

    def test_swapped_type_caught_going_up_and_between_v4(self):
        for bits, want, other in ((517, "INAV", "FNAV"), (258, "FNAV", "INAV")):
            with self.subTest(bits=bits):
                src = self.src(bits)
                outs, rep = convert(src, "4.02")
                self.assertEqual(compare_nav(src, [outs[0].data], rep), [])
                bad = outs[0].data.replace(f"EPH E01 {want}".encode(), f"EPH E01 {other}".encode())
                self.assertNotEqual(bad, outs[0].data)
                self.assertTrue(compare_nav(src, [bad], rep))
                # 4.02 -> 4.00 keeps the type
                v4 = outs[0].data
                outs, rep = convert(v4, "4.00")
                self.assertEqual(compare_nav(v4, [outs[0].data], rep), [])
                bad = outs[0].data.replace(f"EPH E01 {want}".encode(), f"EPH E01 {other}".encode())
                self.assertTrue(compare_nav(v4, [bad], rep))


if __name__ == "__main__":
    unittest.main()
