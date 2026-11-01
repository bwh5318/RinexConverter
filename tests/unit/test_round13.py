"""Round 13 (2026-10-31, docs/DECISIONS.md "cycle-slip epochs in Compact RINEX 1.0"): the
user's choice for a RINEX 2 epoch with event flag 6 that Compact RINEX 1.0 cannot hold
(rnx2crx.c put_event_data copies one line per satellite after an event flag above 1). The
file is written as plain RINEX 2 with a warning: no data are lost, nothing is refused."""

import copy
import os
import shutil
import tempfile
import unittest

from rinexconv.cli import main as cli_main
from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.io import hatanaka
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_met, compare_obs

from .test_independent_meta import SPEC
from .test_obs_fixtures import F, hdr
from . import test_round3 as R3
from .test_round3 import convert as r3convert
from . import test_round11 as R11
from .test_round12 import v3x

SRC = R11.CycleSlipEpochInCompactRinex1.src
LONG = "XXXX00XXX_R_20201800000_01D_30S_MO.rnx"
RULE = "OBS.CRX1.EVENT-PLAIN"


def warned(rep):
    return [w for w in rep.warnings if w["rule"] == RULE]


class PlainInsteadOfCompact(unittest.TestCase):
    def test_explicit_crx(self):
        src = SRC(6)
        plain = convert_data(src, LONG, Options("2.11", compression="none", crx=False))[0]
        out = convert_data(src, LONG, Options("2.11", compression="none", crx=True))[0]
        self.assertEqual(out.data, plain.data)                     # the plain output, byte for byte
        self.assertTrue(out.name.endswith("o"), out.name)          # .YYo, not .YYd
        self.assertEqual(out.name, plain.name)
        self.assertFalse(out.report.output["crx"])
        (w,) = warned(out.report)
        self.assertIn("input line", w["message"])
        self.assertIn("more than 5 observation types", w["message"])
        rep = out.report.to_dict()
        self.assertEqual(compare_obs(src, out.data, rep), [])
        # the first, abandoned pass leaves nothing behind: the report is the plain one's plus
        # the warning
        want = plain.report.to_dict()
        for k in ("rules", "assumptions", "losses", "repairs", "normalisations"):
            self.assertEqual(rep[k], want[k], k)
        self.assertEqual([x for x in rep["warnings"] if x["rule"] != RULE], want["warnings"])
        self.assertEqual(rep["outcome"], "converted")

    def test_kept_state_from_a_compact_rinex_3_input(self):
        # a .crx input keeps Hatanaka by default: the RINEX 2 output falls back the same way
        crx3 = hatanaka.rnx_to_crx(SRC(6))
        self.assertTrue(crx3.startswith(b"3.0"))
        out = convert_data(crx3, LONG.replace(".rnx", ".crx"), Options("2.11", compression="none"))[0]
        self.assertTrue(out.data.startswith(b"     2.11"))
        self.assertTrue(out.name.endswith("o"), out.name)
        self.assertEqual(len(warned(out.report)), 1)
        self.assertEqual(compare_obs(SRC(6), out.data, out.report.to_dict()), [])

    def test_gzip_layer_kept(self):
        out = convert_data(SRC(6), LONG, Options("2.11", compression="gz", crx=True))[0]
        self.assertTrue(out.data.startswith(b"\x1f\x8b"))
        self.assertTrue(out.name.endswith("o.gz"), out.name)

    def test_representable_epochs_stay_compact(self):
        out = convert_data(SRC(4), LONG, Options("2.11", compression="none", crx=True))[0]
        self.assertTrue(out.data.startswith(b"1.0"))
        self.assertTrue(out.name.endswith("d"), out.name)
        self.assertTrue(out.report.output["crx"])
        self.assertEqual(warned(out.report), [])

    def test_rinex3_targets_unaffected(self):
        # CRINEX 3 copies a flag-6 record per satellite line, which RINEX 3/4 writes unwrapped
        for t in ("3.05", "4.02"):
            with self.subTest(target=t):
                out = convert_data(SRC(6), LONG, Options(t, compression="none", crx=True))[0]
                self.assertTrue(out.data.startswith(b"3.1" if t == "4.02" else b"3.0"))   # CRINEX 3.1 from 4.02
                self.assertEqual(warned(out.report), [])


def mutants(rep):
    """Each loss claim deleted, one more, and 999: the independent checks must reject all."""
    for k, e in rep["losses"].items():
        for how in ("del", "plus1", "999"):
            bad = copy.deepcopy(rep)
            if how == "del":
                del bad["losses"][k]
            else:
                bad["losses"][k]["count"] = e["count"] + 1 if how == "plus1" else 999
            yield f"{how} {k}", bad


class Exact:
    def assert_exact(self, check, rep):
        self.assertEqual(check(rep), [])
        for what, bad in mutants(rep):
            with self.subTest(mutation=what):
                self.assertTrue(check(bad), what)


class SolRound13(Exact, unittest.TestCase):
    """Sol's round-13 blockers, all in the independent checks: blank attributes in the phase
    readers, the loss table on blank-attribute pseudoranges, and loss counts compared exactly."""

    BODY = ["> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.400")]

    def test_blank_attribute_phase_entry(self):
        # Sol 1: a 3.01 'L1 ' entry of 0.25 to 3.02 is claimed phase-shift-entry-dropped:G:L1
        src = v3x("3.01", hdr("G    2 C1C L1 ", "SYS / # / OBS TYPES"),
                  hdr("G L1   0.25000", "SYS / PHASE SHIFTS"), body=self.BODY)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = r3convert(src, "3.02")
        self.assertEqual(rep["losses"]["phase-shift-entry-dropped:G:L1 "]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_blank_attribute_pseudorange_to_v2(self):
        # Sol 2: 'C1 ' has no tracking family, so neither C1 (C/A) nor P1 (P) holds it
        src = v3x("3.00", hdr("G    2 C1  L1C", "SYS / # / OBS TYPES"), body=self.BODY)
        self.assertEqual(V.errors(V.validate(src)), [])
        for t in ("2.10", "2.11"):
            with self.subTest(target=t):
                outs, rep = r3convert(src, t)
                self.assertEqual(rep["losses"]["obs-code-not-representable:G:C1 "]["count"], 1)
                self.assertEqual(allowed_check(rep), [])        # was: not allowed
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_phase_record_claims_exact(self):
        # Sol 3: a known 0.25 shift lost to 2.11 / 3.00 (no record) or 4.02 (deprecated)
        src = v3x("3.05", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
                  hdr("G L1C  0.25000", "SYS / PHASE SHIFT"), body=self.BODY)
        want = {"2.11": "phase-shift-record-not-representable", "3.00": "phase-shift-record-not-representable",
                "4.02": "phase-shift-record-deprecated"}
        for t, cat in want.items():
            with self.subTest(target=t):
                outs, rep = r3convert(src, t)
                self.assertEqual(rep["losses"][cat]["count"], 1)
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_leap_seconds_count_exact(self):
        src = R3.HeaderRecordsInEvents.src(None, "LEAP SECONDS", "    18    18  2185     7GPS")
        outs, rep = r3convert(src, "2.11")
        self.assertEqual(rep["losses"]["header-field-not-representable:LEAP SECONDS"]["count"], 1)
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_met_type_count_exact(self):
        inp = (SPEC / "2.11" / "a9_met.rnx").read_bytes()
        inp = inp.replace(b"     3    PR    TD    HR      ", b"     4    PR    TD    HR    WD")
        inp = inp.replace(b"  89.5\n", b"  89.5  270.0\n")
        outs = convert_data(inp, "x.rnx", Options("2.10", compression="none"))
        rep = outs[0].report.to_dict()
        self.assertGreater(rep["losses"]["met-type-not-representable:WD"]["count"], 0)
        self.assert_exact(lambda r: compare_met(inp, outs[0].data, r), rep)


class EveryClaimCountedExactly(Exact, unittest.TestCase):
    """The mutation audit's survivors (DECISIONS "review round 13 fixes"): each claim below
    could be deleted, or its count changed, unnoticed. Every loss of these conversions must
    now be counted exactly. (RINEX_MUTATION_AUDIT=<file> runs the same mutations on every
    clean comparison of the unit suite: tests/conftest.py.)"""

    CASES = [  # (spec example, target, a claim the case must have)
        ("3.02/a4_obs_mixed.rnx", "2.10", "header-record-not-representable:GLONASS SLOT / FRQ #"),
        ("3.03/a4_obs_example2_derived_header.rnx", "2.10", "header-record-not-representable:GLONASS COD/PHS/BIS"),
        ("3.03/a4_obs_example2_derived_header.rnx", "2.10", "system-not-representable:E"),   # count 0
        # (2.10/a17_obs_gps_geo.rnx to 2.11 claimed obs-code-not-representable:S:L2 with count
        # 0 until round 22: L2 is no SBAS code in either version, and its column is empty, so
        # nothing is lost and nothing is claimed now: test_round22.GeneratedFiles)
        ("3.03/a4_obs_example3_derived_header.rnx", "3.01", "phase-shift-entry-dropped:G:L2Q"),
        ("3.03/a4_obs_example1.rnx", "2.10", "phase-shift-record-not-representable"),
        ("3.03/a4_obs_example3_derived_header.rnx", "2.10", "header-field-not-representable:LEAP SECONDS"),
        ("2.11/a18_nav_geo_derived_columns.rnx", "2.10", "header-field-not-representable:CORR TO SYSTEM TIME:T-W-S-U"),
        ("4.00/a35_nav_sto_eop_ion.rnx", "3.03", "header-field-not-representable:TIME SYSTEM CORR:UTC-ID:UTCIRN"),
    ]

    def test_spec_examples(self):
        from tests.independent.compare import compare_nav
        for path, t, cat in self.CASES:
            with self.subTest(fixture=path, target=t):
                src = (SPEC / path).read_bytes()
                outs = convert_data(src, os.path.basename(path),
                                    Options(t, compression="none", assume_phase_aligned=True))
                rep = outs[0].report.to_dict()
                self.assertIn(cat, rep["losses"])
                if "_nav_" in path:
                    self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
                else:
                    self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_event_records(self):
        cases = [("SYS / PHASE SHIFT", "G L1C  0.25000", "2.11", "event-record-not-representable:SYS / PHASE SHIFT"),
                 ("SYS / PHASE SHIFT", "G L1C  0.25000", "4.02", "event-record-deprecated:SYS / PHASE SHIFT"),
                 ("GLONASS COD/PHS/BIS", " C1C    0.250 C2C    0.000 C2P    0.000", "3.01",
                  "event-record-not-representable:GLONASS COD/PHS/BIS")]
        for lab, content, t, cat in cases:
            with self.subTest(record=lab, target=t):
                src = R3.HeaderRecordsInEvents.src(None, lab, content)
                outs, rep = r3convert(src, t)
                self.assertIn(cat, rep["losses"])
                self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


class LossKindsNoAuditReached(Exact, unittest.TestCase):
    """Loss kinds neither mutation audit reached (no corpus row, no clean unit comparison had
    them): one fixture each, every claim counted exactly."""

    def nav(self, src, target):
        from tests.independent.compare import compare_nav
        outs = convert_data(src, "x.rnx", Options(target, compression="none"))
        rep = outs[0].report.to_dict()
        return rep, (lambda r: compare_nav(src, [o.data for o in outs], r))

    def test_galileo_disturbance_flags(self):
        # v4 NeQuick-G flags (rinex_4.02.txt Table A36) have no room in 3.03+'s blank 4th slot
        from .test_validate import nav_v4, payload
        b = nav_v4("4.02")
        i = b.index("> ION E11 IFNV")
        b[i + 2] = "     1.000000000000E+00"
        rep, check = self.nav(payload(b), "3.05")
        self.assertEqual(rep["losses"]["header-field-not-representable:IONOSPHERIC CORR:GAL-flags"]["count"], 1)
        self.assert_exact(check, rep)

    def test_klobuchar_alpha_only(self):
        # a RINEX 4 Klobuchar record needs alpha and beta (rinex_4.02.txt Table A35)
        from .test_nav_fixtures import SPEC_305
        src = b"".join(l for l in SPEC_305.splitlines(True) if not l.startswith(b"GPSB"))
        rep, check = self.nav(src, "4.02")
        self.assertEqual(rep["losses"]["nav-correction-not-representable:ION:KLOB-incomplete:G"]["count"], 1)
        self.assert_exact(check, rep)

    def test_nav_epoch_fraction(self):
        # RINEX 3/4 nav epochs have whole seconds (I2.2, rinex305.txt Table A6)
        from .test_nav_fixtures import SPEC_211
        src = SPEC_211.replace(b" 6 99  9  2 17 51 44.0", b" 6 99  9  2 17 51 44.5")
        rep, check = self.nav(src, "3.05")
        self.assertEqual(rep["losses"]["nav-epoch-precision"]["count"], 1)
        self.assert_exact(check, rep)

    def test_clock_overflow(self):
        # 99.999999999999 s (F15.12) rounds to 100.000000000, which F12.9 (RINEX 2) cannot hold
        from .test_obs_fixtures import V305
        src = V305.replace(b"  0  3        .000000123000", b"  0  3      99.999999999999")
        outs, rep = r3convert(src, "2.11", approx_position=(4027894.006, 307045.6, 4919474.91))
        self.assertEqual(rep["losses"]["clock-overflow"]["count"], 1)
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)

    def test_epoch_emptied_by_system_removal(self):
        # a BeiDou-only epoch: RINEX 2 has no BeiDou, so the epoch has nothing left
        src = R11.SystemLossCounted.SRC + b"".join(
            (l + "\n").encode() for l in ["> 2026 10 01 00 01  0.0000000  0  1",
                                          "C11" + F("  23000200.105") + F(" 120001000.405")])
        outs, rep = r3convert(src, "2.11", assume_phase_aligned=True)
        self.assertEqual(rep["losses"]["epoch-emptied-by-system-removal"]["count"], 1)
        self.assert_exact(lambda r: compare_obs(src, outs[0].data, r), rep)


class CorpusHarness(unittest.TestCase):
    def test_wrapper_leg_accepts_the_warned_fallback(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
        import corpus_run as CR
        from rinexconv.engine import convert_loaded, load_bytes
        ld = load_bytes(SRC(6))
        plain = [o.data for o in convert_loaded(ld, LONG, Options("2.11", compression="none", crx=False))]
        self.assertEqual(CR._wrapper_leg(ld, LONG, "obs", "2.11", plain, [], with_z=False), [])
        real = CR.convert_loaded

        def unwarned(*a, **k):
            outs = real(*a, **k)
            outs[0].report.warnings[:] = [w for w in outs[0].report.warnings if w["rule"] != RULE]
            return outs
        CR.convert_loaded = unwarned
        try:
            self.assertTrue(CR._wrapper_leg(ld, LONG, "obs", "2.11", plain, [], with_z=False))
        finally:
            CR.convert_loaded = real


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_exit_code_and_name(self):
        p = os.path.join(self.tmp, LONG)
        with open(p, "wb") as fh:
            fh.write(SRC(6))
        out = os.path.join(self.tmp, "out")
        self.assertEqual(cli_main([p, "--to", "2.11", "--crx", "--out", out, "--no-auto-nav"]), 0)
        names = [n for n in os.listdir(out) if not n.endswith(".json")]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith("o"), names)
        with open(os.path.join(out, names[0]), "rb") as fh:
            self.assertTrue(fh.read().startswith(b"     2.11"))


if __name__ == "__main__":
    unittest.main()
