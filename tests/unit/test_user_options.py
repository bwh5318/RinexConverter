"""Options the user asked for on 2026-10-31 (docs/DECISIONS.md "the user's answers"):
--qzss-ion-area supplies the area of QZSS ION sets whose source names none (round 32), and --approx-position-zero
writes teqc's 0 0 0 placeholder for a RINEX 2 APPROX POSITION XYZ the input does not have."""

import copy
import unittest

from rinexconv.cli import build_parser
from rinexcore import validate as V
from rinexcore.errors import InvocationError, MissingInformationError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav, compare_obs
from tests.independent.headers import compare_obs_meta

from .test_obs_fixtures import V305, F, hdr
from .test_round2 import obs_file
from .test_round3 import QzssIonArea, convert, head_lines
from .test_validate import d19, nav_v4, payload


def nav400(*extra):
    """A 4.00 nav file (D exponents) with QZSS CNVX ION records without an area."""
    body = QzssIonArea.J_CNVX + [x for rec in extra for x in rec]
    return payload(nav_v4("4.00", "D") + [x.replace("E", "D") if x[0] != ">" else x for x in body])


def assumptions(rep, category):
    return [(a["detail"], a["source"], a["count"]) for a in rep.get("assumptions", [])
            if a["category"] == category]


def nav402_lnav(*sets):
    """A 4.02 nav file with QZSS LNAV ION records, which name no area: 4.02 gives one only to
    CNVX ('for the other types the subtype shall be left blank', rinex_4.02.txt Table A35 note
    3* p.117). sets: alpha0 of each record (all at one time)."""
    body = []
    for a0 in sets:
        body += ["> ION J01 LNAV", "    2026 10 30 00 00 00" + d19(a0, "E") + d19(1e-8, "E") * 2,
                 "    " + d19(1.0, "E") * 4, "    " + d19(1.0, "E")]
    return payload(nav_v4("4.02") + body)


def region_codes(out):
    """Region code text (ION MESSAGE LINE 2, columns 24-42) of each '> ION J01 LNAV' record."""
    lines = out.decode().splitlines()
    return [lines[k + 3][23:42] for k, l in enumerate(lines) if l.rstrip() == "> ION J01 LNAV"]


class QzssIonAreaOption(unittest.TestCase):
    """Round 32: a 4.00/4.01 Klobuchar ION record names its area in the 'Region code: 0 or
    blank (wide area parameters), 1 (QZSS only - Japan area coefficients)' (rinex_4.00.txt Table
    A32 l.5908 p.104; rinex_4.01.txt l.6190 p.108), and a 4.02 CNVX record in its subtype WIDE/
    JAPN (rinex_4.02.txt Table 25 p.40). --qzss-ion-area names the area of QZSS sets whose source
    names none (a 4.02 LNAV record, a RINEX 3 QZSA/QZSB set), written as the Region code of a
    4.00/4.01 target; a code or subtype in the source always wins over it."""

    def test_area_given_keeps_the_records(self):
        # the source's own Region code wins: a blank code is wide area whatever the option says
        src = nav400()
        for area in ("WIDE", "JAPN"):
            with self.subTest(source_code=area):
                outs, rep = convert(src, "4.02", qzss_ion_area=area)
                self.assertIn(b"> ION J01 CNVX WIDE", outs[0].data.splitlines())
                self.assertNotIn("nav-correction-not-representable:ION:CNVX-area-unknown:J", rep["losses"])
                self.assertEqual(assumptions(rep, "qzss-ion-area"), [])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        japn = payload(nav_v4("4.00", "D") + [x.replace("E", "D") if x[0] != ">" else x for x in
                                              QzssIonArea.J_CNVX[:3] + ["    " + d19(1.0, "E") * 2]])
        outs, rep = convert(japn, "4.02", qzss_ion_area="WIDE")
        self.assertIn(b"> ION J01 CNVX JAPN", outs[0].data.splitlines())
        self.assertEqual(assumptions(rep, "qzss-ion-area"), [])
        self.assertEqual(compare_nav(japn, [o.data for o in outs], rep), [])
        # a set that names no area takes the option, as the 4.00/4.01 Region code
        src = nav402_lnav(1e-8)
        for area, code in (("WIDE", " 0.000000000000E+00"), ("JAPN", " 1.000000000000E+00")):
            with self.subTest(option=area):
                outs, rep = convert(src, "4.01", qzss_ion_area=area)
                self.assertEqual(region_codes(outs[0].data), [code])
                self.assertEqual(assumptions(rep, "qzss-ion-area"), [(area, "user", 1)])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_without_the_option_still_dropped(self):
        # without the option a set that names no area keeps a blank Region code, which 4.00/4.01
        # read as wide area: reported as an assumption, nothing dropped
        src = nav402_lnav(1e-8)
        outs, rep = convert(src, "4.01")
        self.assertEqual(region_codes(outs[0].data), [""])
        self.assertEqual(assumptions(rep, "qzss-ion-area"), [("WIDE", "spec-default:blank-region-code", 1)])
        self.assertEqual(rep["losses"], {})
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_checker_needs_the_assumption_and_its_area(self):
        src = nav402_lnav(1e-8)
        outs, rep = convert(src, "4.01", qzss_ion_area="WIDE")
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        bare = copy.deepcopy(rep)
        bare["assumptions"] = [a for a in bare["assumptions"] if a["category"] != "qzss-ion-area"]
        self.assertTrue(compare_nav(src, [o.data for o in outs], bare))
        swapped = outs[0].data.replace(b"     1.000000000000E+00 0.000000000000E+00",
                                       b"     1.000000000000E+00 1.000000000000E+00")
        self.assertNotEqual(swapped, outs[0].data)
        self.assertTrue(compare_nav(src, [swapped], rep))
        # and a 4.00 code the converter turned into the wrong subtype
        src = nav400()
        outs, rep = convert(src, "4.02")
        swapped = outs[0].data.replace(b"CNVX WIDE", b"CNVX JAPN")
        self.assertTrue(compare_nav(src, [swapped], rep))

    def test_two_sets_at_one_time_refused(self):
        # WIDE and JAPN sets are both broadcast (rinex_4.02.txt §8.4.3 p.47): two different sets
        # of one satellite, message and time without an area cannot both be the area the option
        # names
        src = nav402_lnav(1e-8, 2e-8)
        with self.assertRaises(InvocationError) as cm:
            convert(src, "4.01", qzss_ion_area="WIDE")
        self.assertIn("--qzss-ion-area", str(cm.exception))
        outs, rep = convert(src, "4.01")             # without it: both written, blank code assumed wide
        self.assertEqual(assumptions(rep, "qzss-ion-area"), [("WIDE", "spec-default:blank-region-code", 2)])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_no_effect_where_the_area_is_known_or_not_written(self):
        outs, rep = convert(nav400(), "4.01", qzss_ion_area="WIDE")
        self.assertIn(b"\n> ION J01 CNVX\n", outs[0].data)
        self.assertEqual(assumptions(rep, "qzss-ion-area"), [])
        src = payload(nav_v4("4.02"))                   # already 'CNVX WIDE'
        outs, rep = convert(src, "4.02", qzss_ion_area="JAPN")
        self.assertIn(b"\n> ION J01 CNVX WIDE\n", outs[0].data)
        self.assertEqual(assumptions(rep, "qzss-ion-area"), [])

    def test_cli(self):
        a = build_parser().parse_args(["x.rnx", "--to", "4.02", "--qzss-ion-area", "JAPN"])
        self.assertEqual(a.qzss_ion_area, "JAPN")
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["x.rnx", "--to", "4.02", "--qzss-ion-area", "EAST"])


class ApproxPositionZero(unittest.TestCase):
    """APPROX POSITION XYZ is mandatory in RINEX 2 (rinex211.txt Table A1) and optional for
    moving platforms from 3.00 (rinex305.txt Table A2). teqc writes 0 0 0 when it has no
    position; the spec gives that no meaning, so it is reported as a placeholder."""

    ZERO = hdr("        0.0000        0.0000        0.0000", "APPROX POSITION XYZ")

    def test_writes_zero_and_reports_it(self):
        outs, rep = convert(V305, "2.11", approx_position_zero=True)
        self.assertIn(self.ZERO, head_lines(outs[0].data))
        self.assertEqual(assumptions(rep, "approx-position"), [("0 0 0 (unknown)", "teqc-convention", 1)])
        self.assertIn("OBS.APPROX-POSITION-ZERO", [w["rule"] for w in rep["warnings"]])
        # (the minimal V305 fixture lacks other RINEX 2 records, e.g. OBSERVER / AGENCY)
        self.assertEqual([f for f in V.errors(V.validate(outs[0].data)) if "APPROX" in f.message], [])
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(V305, outs[0].data, rep), [])

    def test_still_refused_without_an_option(self):
        with self.assertRaises(MissingInformationError):
            convert(V305, "2.11")

    def test_checker_needs_zero_and_the_assumption(self):
        outs, rep = convert(V305, "2.11", approx_position_zero=True)
        bare = copy.deepcopy(rep)
        bare["assumptions"] = [a for a in bare["assumptions"] if a["category"] != "approx-position"]
        self.assertTrue(compare_obs_meta(V305, outs[0].data, bare))
        moved = outs[0].data.replace(self.ZERO.encode(),
                                     hdr("        1.0000        0.0000        0.0000", "APPROX POSITION XYZ").encode())
        self.assertTrue(compare_obs_meta(V305, moved, rep))

    def test_a_given_position_wins_and_a_real_one_is_kept(self):
        outs, rep = convert(V305, "2.11", approx_position=(1.0, 2.0, 3.0), approx_position_zero=True)
        self.assertEqual([(d.split(), s) for d, s, n in assumptions(rep, "approx-position")],
                         [(["1.0000", "2.0000", "3.0000"], "user")])
        src = obs_file("G    2 C1C L1C", [hdr("G L1C", "SYS / PHASE SHIFT")], [
            "> 2026 10 01 00 00  0.0000000  0  1", "G05" + F("  22000000.105") + F(" 115000000.405")])
        outs, rep = convert(src, "2.11", approx_position_zero=True)
        self.assertIn(hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ"),
                      head_lines(outs[0].data))           # the input's own position is kept
        self.assertEqual(assumptions(rep, "approx-position"), [])

    def test_cli(self):
        a = build_parser().parse_args(["x.rnx", "--to", "2.11", "--approx-position-zero"])
        self.assertTrue(a.approx_position_zero)


if __name__ == "__main__":
    unittest.main()
