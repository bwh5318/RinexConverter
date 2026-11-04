"""Regression tests for review round 9 (2026-10-31, docs/DECISIONS.md "review round 9 fixes"):
Sol's three blockers, each from the reviewer's reproduction, and the flag-only fields the
second one showed the checker never compared."""

import copy
import os
import tempfile
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.errors import InvocationError
from rinexcore.io.hatanaka import crx_to_rnx
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import obs_file
from .test_round3 import QzssIonArea, convert
from .test_user_options import nav400
from .test_validate import d19, nav_v4, payload


def merged(primary, *others, **kw):
    """convert_data(primary, merge=[others written to temporary files])."""
    paths = []
    try:
        for data in others:
            fd, p = tempfile.mkstemp(suffix=".rnx")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            paths.append(p)
        outs = convert_data(primary, "x.rnx", Options("4.02", compression="none", merge=paths, **kw))
        return outs, outs[0].report.to_dict()
    finally:
        for p in paths:
            os.unlink(p)


class AreaPerSourceFile(unittest.TestCase):
    """Sol 1 and 3: --qzss-ion-area looked at the primary file's version only, and compared the
    coefficients as text. Round 32: a 4.00/4.01 record names its own area (Region code '0 or
    blank (wide area parameters), 1 (QZSS only - Japan area coefficients)', rinex_4.00.txt Table
    A32 l.5908 p.104), which wins over the option; the option labels sets without one."""

    def test_merged_400_records_get_the_area(self):
        for area in ("WIDE", None):
            with self.subTest(option=area):
                outs, rep = merged(payload(nav_v4("4.02")), nav400(), qzss_ion_area=area)
                out = outs[0].data.decode()
                self.assertEqual(out.count("> ION J01 CNVX WIDE"), 2)     # the 4.02 file's own + the merged one
                self.assertNotIn("nav-correction-not-representable:ION:CNVX-area-unknown:J", rep["losses"])
                self.assertEqual([(a["detail"], a["count"]) for a in rep["assumptions"]
                                  if a["category"] == "qzss-ion-area"], [])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])

    def test_same_set_written_differently_is_one_set(self):
        # QZSS LNAV sets of a 4.02 file name no area: the option labels them in 4.01
        from .test_user_options import nav402_lnav, region_codes
        one = nav402_lnav(1e-8)
        k = one.index(b"> ION J01 LNAV")
        other = one + one[k:].replace(d19(1e-8, "E").encode(), b" 0.100000000000E-07", 1)
        self.assertNotEqual(one, other)
        outs, rep = convert(other, "4.01", qzss_ion_area="JAPN")   # was: InvocationError
        self.assertEqual(region_codes(outs[0].data), [" 1.000000000000E+00"] * 2)
        with self.assertRaises(InvocationError):
            convert(nav402_lnav(1e-8, 3e-8), "4.01", qzss_ion_area="JAPN")
        # a 4.00 file's sets name their area: no contradiction, whatever the option says
        one = QzssIonArea.J_CNVX
        different = [one[0], one[1].replace(d19(1e-8, "E"), d19(3e-8, "E"), 1), *one[2:]]
        outs, rep = convert(nav400(different), "4.02", qzss_ion_area="JAPN")
        self.assertEqual(outs[0].data.decode().count("> ION J01 CNVX WIDE"), 2)


class FlagOnlyFields(unittest.TestCase):
    """Sol 2: a blank value that carries an LLI or SSI flag is information the converter keeps
    (or claims flags-on-missing-value-dropped for Compact RINEX 1.0); the checker skipped such
    fields, so it neither saw a flag-only collision partner nor a lost flag."""

    SRC = obs_file("G    3 C1C L1C L1W", [hdr("G L1C", "SYS / PHASE SHIFT"), hdr("G L1W", "SYS / PHASE SHIFT")], [
        "> 2026 10 01 00 00  0.0000000  0  1",
        "G05" + F("  22000000.105") + F(" " * 14, "1") + F(" 115000009.009")])

    def test_flag_only_partner_collapses(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        outs, rep = convert(self.SRC, "2.11")
        self.assertEqual(rep["losses"]["obs-code-collapsed:G:L1W"]["count"], 1)
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])     # was: 'no ... other column'

    def test_lost_flag_caught(self):
        for t in ("2.11", "3.05", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(self.SRC, t, assume_phase_aligned=True)
                self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
                field = " " * 14 + "1"
                self.assertIn(field.encode(), outs[0].data)
                bad = outs[0].data.replace(field.encode(), b" " * 15, 1)
                self.assertTrue(compare_obs(self.SRC, bad, rep))

    def test_compact_rinex_1_claim_counted(self):
        outs = convert_data(self.SRC, "x.rnx", Options("2.11", compression="none", crx=True))
        rep = outs[0].report.to_dict()
        self.assertEqual(rep["losses"]["flags-on-missing-value-dropped"]["count"], 1)
        plain = crx_to_rnx(outs[0].data)
        self.assertEqual(compare_obs(self.SRC, plain, rep), [])
        bare = copy.deepcopy(rep)
        del bare["losses"]["flags-on-missing-value-dropped"]
        self.assertTrue(compare_obs(self.SRC, plain, bare))


class WavelengthRuleOnValuesOnly(unittest.TestCase):
    """RINEX 2 'WAVELENGTH FACT L1/2' factor 2 turns into RINEX 3 LLI bit 1 (rinex305.txt
    §6.7); a missing phase has no observation to flag, so no flag is created on it."""

    SRC = lines(
        hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
        hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
        hdr("TEST", "MARKER NAME"),
        hdr("     2     2", "WAVELENGTH FACT L1/2"),
        hdr("     4    C1    P2    L1    L2", "# / TYPES OF OBSERV"),
        hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
        hdr("", "END OF HEADER"),
        " 26 10  1  0  0  0.0000000  0  2G05G12",
        F("  22000000.105") + F("  22000002.305") + " " * 16 + F("  89000000.505"),
        F("  21000000.112") + F("  21000002.312") + F(" " * 14, "1") + F("  88000000.512"))

    def test_no_flag_on_a_missing_phase(self):
        outs, rep = convert(self.SRC, "3.05", assume_phase_aligned=True)
        data = outs[0].data.decode().split("END OF HEADER")[1].split("\n")
        g05 = next(x for x in data if x.startswith("G05")).ljust(3 + 4 * 16)
        self.assertEqual(g05[3 + 2 * 16:3 + 3 * 16], " " * 16)            # L1C: no value, no flag
        self.assertEqual(g05[3 + 3 * 16 + 14], "2")                         # L2: factor 2 -> bit 1
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])


if __name__ == "__main__":
    unittest.main()
