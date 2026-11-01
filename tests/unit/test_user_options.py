"""Options the user asked for on 2026-10-31 (docs/DECISIONS.md "the user's answers"):
--qzss-ion-area supplies the 4.02 area of QZSS CNVX ION records, and --approx-position-zero
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


class QzssIonAreaOption(unittest.TestCase):
    """rinex_4.02.txt Table 25 p.40 and Table A35 note 3*: a QZSS CNVX ION record 'must have
    a subtype indicator (WIDE or JAPN)'; 4.00/4.01 records have no such field."""

    def test_area_given_keeps_the_records(self):
        src = nav400()
        for area in ("WIDE", "JAPN"):
            with self.subTest(area=area):
                outs, rep = convert(src, "4.02", qzss_ion_area=area)
                self.assertIn(f"\n> ION J01 CNVX {area}\n".encode(), outs[0].data)
                self.assertNotIn("nav-correction-not-representable:ION:CNVX-area-unknown:J", rep["losses"])
                self.assertEqual(assumptions(rep, "qzss-ion-area"), [(area, "user", 1)])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_without_the_option_still_dropped(self):
        outs, rep = convert(nav400(), "4.02")
        self.assertEqual(rep["losses"]["nav-correction-not-representable:ION:CNVX-area-unknown:J"]["count"], 1)
        self.assertEqual(assumptions(rep, "qzss-ion-area"), [])

    def test_checker_needs_the_assumption_and_its_area(self):
        src = nav400()
        outs, rep = convert(src, "4.02", qzss_ion_area="WIDE")
        bare = copy.deepcopy(rep)
        bare["assumptions"] = [a for a in bare["assumptions"] if a["category"] != "qzss-ion-area"]
        self.assertTrue(compare_nav(src, [o.data for o in outs], bare))
        swapped = outs[0].data.replace(b"CNVX WIDE", b"CNVX JAPN")
        self.assertTrue(compare_nav(src, [swapped], rep))

    def test_two_sets_at_one_time_refused(self):
        # WIDE and JAPN sets are both broadcast (rinex_4.02.txt §8.4.3 p.47): two different CNVX
        # sets of one satellite and time cannot both be the area the option names
        other = [QzssIonArea.J_CNVX[0], QzssIonArea.J_CNVX[1].replace(d19(1e-8, "E"), d19(2e-8, "E"), 1),
                 *QzssIonArea.J_CNVX[2:]]
        src = nav400(other)
        with self.assertRaises(InvocationError) as cm:
            convert(src, "4.02", qzss_ion_area="WIDE")
        self.assertIn("--qzss-ion-area", str(cm.exception))
        outs, rep = convert(src, "4.02")             # without it: both dropped, as before
        self.assertEqual(rep["losses"]["nav-correction-not-representable:ION:CNVX-area-unknown:J"]["count"], 2)

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
