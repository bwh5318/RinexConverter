"""Regression tests for review round 32, navigation (2026-11-02): values the converter wrote
wrong without a word, and holes in the independent checker. Expected values are written here
from the spec text by hand, not taken from the converter.

N1 GLONASS message frame time: RINEX 2 'tk ... (0 .le. tk .lt. 86400 sec of day UTC)'
   (rinex211.txt Table A11 l.1718-1719), RINEX 3/4 '(tk+nd*86400) in seconds of the UTC week'
   (rinex305.txt Table A10 p.74; rinex_4.02.txt Table A15 p.87).
N2 SBAS frame time: 2.10 'message frame time (sec of day GPS)' (rinex210.txt Table A16
   l.1656); 2.11+ GPS seconds of the week, 'the same GPS week as the Epoch of Ephemerides ...
   adjusted by - or + 604800' (rinex211.txt l.910-915).
N3 QZSS Klobuchar area: 4.00/4.01 Region code (rinex_4.00.txt Table A32 l.5908 p.104;
   rinex_4.01.txt l.6190 p.108) <-> 4.02 subtype WIDE/JAPN (rinex_4.02.txt Table 25 p.40).
N4/P1 fields a RINEX 4 line defines (rinex_4.02.txt Tables A9 p.79, A10 p.81, A13 p.85).
N5 DELTA-UTC W 'Continuous number, not mod(1024)!' (rinex211.txt Table A3 l.1344).
N6 RINEX 2.00 GLONASS signs -TauN, -GammaN, +TauC (rinex210.txt l.171-180).
P3 STO systems G,R,E,C,J,I in 4.00/4.01 (rinex_4.00.txt Table A30 p.102).
C1-C3 checker holes: STO identifiers, records from header corrections, EPH body satellite.
"""

import copy
import unittest
from decimal import Decimal

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.errors import CorruptError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav
from tests.independent.tokens import lines_of, nav_tokens

from .test_round13 import Exact
from .test_validate import d19, hdr, nav_v4, payload


def convert(src, target, **kw):
    outs = convert_data(src, "x.rnx", Options(target, compression="none", **kw))
    return outs, outs[0].report.to_dict()


def recs(data):
    return nav_tokens(lines_of(data))


def field(data, sat, n=2):
    """Value n of line 0 of every record of `sat`, by epoch."""
    return {k[2][:5]: v[0][1][n] for k, v in recs(data).items() if k[0] == "EPH" and k[1] == sat}


def rule_n(rep, name):
    return (rep["rules"].get(name) or {}).get("count", 0)


def assumed(rep, cat):
    return [(a["detail"], a["source"], a["count"]) for a in rep["assumptions"] if a["category"] == cat]


# ------------------------------------------------------------------ GLONASS files
GLO_ORBITS2 = ["   -0.613975537109D+04-0.182036018372D+01 0.186264514923D-08 0.000000000000D+00",
               "    0.958122705078D+04-0.254422473908D+01 0.931322574616D-09 0.100000000000D+01",
               "    0.228222685547D+05 0.578757286072D+00-0.186264514923D-08 0.000000000000D+00"]


def glo2(version, records, tauc=None):
    """A RINEX 2 GLONASS nav file; records: (prn, (y, mo, d, h, mi), gamma text, tk text)."""
    h = [hdr(f"{version:>9s}           G: GLONASS NAV DATA", "RINEX VERSION / TYPE"),
         hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE")]
    if tauc is not None:
        h.append(hdr(f"{2026:6d}{10:6d}{1:6d}   " + tauc.rjust(19), "CORR TO SYSTEM TIME"))
    h.append(hdr("", "END OF HEADER"))
    body = []
    for prn, (y, mo, d, hh, mi), gamma, tk in records:
        body.append(f"{prn:2d} {y % 100:02d} {mo:2d} {d:2d} {hh:2d} {mi:2d} 0.0 0.187545083463D-03"
                    f"{gamma:>19s}{tk:>19s}")
        body += GLO_ORBITS2
    return payload(h + body)


def glo3(version, records):
    """A RINEX 3 GLONASS nav file (3.04: 4 lines); records: (prn, (y, mo, d, h, mi), tk text)."""
    h = [hdr(f"{version:>9s}           N: GNSS NAV DATA    R: GLONASS", "RINEX VERSION / TYPE"),
         hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE"),
         hdr("", "END OF HEADER")]
    body = []
    for prn, (y, mo, d, hh, mi), tk in records:
        body.append(f"R{prn:02d} {y:4d} {mo:02d} {d:02d} {hh:02d} {mi:02d} 00 1.875450834630E-04"
                    f" 9.094947017730E-13{tk:>19s}")
        body += ["    " + x[3:].replace("D", "E") for x in GLO_ORBITS2]
    return payload(h + body)


class GlonassFrameTime(Exact, unittest.TestCase):
    """N1. R01 of 2026-10-01 (a Thursday) 00:15: brdc2740.26g (2.01) holds tk 0.0, BRDC00IGS
    (3.04) 3.456000000000E+05 for the same message: 4 x 86400 + 0."""

    def test_v2_to_v3_and_back(self):
        src = glo2("2.01", [(1, (2026, 10, 1, 0, 15), "0.909494701773D-12", "0.000000000000D+00")])
        for t in ("3.04", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertEqual(field(outs[0].data, "R01")[(2026, 10, 1, 0, 15)], Decimal(345600))
                self.assertEqual(rule_n(rep, "NAV.GLO.FRAME-TIME-BASIS"), 1)
                self.assertEqual(rep["losses"], {})
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
                # the old behaviour (the value copied) is caught
                bad = outs[0].data.replace(b"3.456000000000", b"0.000000000000")
                self.assertNotEqual(bad, outs[0].data)
                self.assertTrue(compare_nav(src, [bad], rep))
        back = glo3("3.04", [(1, (2026, 10, 1, 0, 15), "3.456000000000E+05")])
        outs, rep = convert(back, "2.11")
        self.assertEqual(field(outs[0].data, "R01")[(2026, 10, 1, 0, 15)], Decimal(0))
        self.assertEqual(rule_n(rep, "NAV.GLO.FRAME-TIME-BASIS"), 1)
        self.assert_exact(lambda r: compare_nav(back, [o.data for o in outs], r), rep)
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith(" 1 26 10  1  0 15"))
        lines[k] = lines[k][:60] + d19(345600.0)            # the value copied, as before
        self.assertTrue(compare_nav(back, ["\n".join(lines).encode()], rep))
        self.assertTrue(compare_nav(back, [o.data for o in outs], {**rep, "rules": {}}))

    def test_midnight_nearest_day(self):
        # Toc Thursday 23:45, tk 300 s (00:05): the instant nearest Toc is Friday 00:05, 20 min
        # after Toc (the Thursday 00:05 reading is 23 h 40 min before it): 5 x 86400 + 300
        src = glo2("2.11", [(2, (2026, 10, 1, 23, 45), "0.0D+00", "0.300000000000D+03")])
        outs, rep = convert(src, "3.05")
        self.assertEqual(field(outs[0].data, "R02")[(2026, 10, 1, 23, 45)], Decimal(432300))
        self.assertEqual(assumed(rep, "glonass-frame-time-week"), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_sunday_week_boundary(self):
        # Toc Sunday 2026-10-04 00:15, tk 86370 s (Saturday 23:59:30): counted from the start of
        # Toc's UTC week, -30 (the user's decision of 2026-11-02, 'Toc week', as SBAS does; it
        # was 604770, the frame's own week), reported as an assumption; and back, -30 mod 86400
        # = 86370
        src = glo2("2.11", [(3, (2026, 10, 4, 0, 15), "0.0D+00", "0.863700000000D+05")])
        outs, rep = convert(src, "3.05")
        self.assertEqual(field(outs[0].data, "R03")[(2026, 10, 4, 0, 15)], Decimal(-30))
        self.assertEqual(assumed(rep, "glonass-frame-time-week"),
                         [("seconds from the start of Toc's UTC week", "user:2026-11-02 Toc week", 1)])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("R03"))
        lines[k] = lines[k][:61] + d19(604770.0)                # the frame's own week: caught
        self.assertTrue(compare_nav(src, ["\n".join(lines).encode()], rep))
        # Saturday 23:45 with tk 30 s (Sunday 00:00:30, the next week): 6 x 86400 + 86430 = 604830
        src = glo2("2.11", [(3, (2026, 10, 3, 23, 45), "0.0D+00", "0.300000000000D+02")])
        outs, rep = convert(src, "3.05")
        self.assertEqual(field(outs[0].data, "R03")[(2026, 10, 3, 23, 45)], Decimal(604830))
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        back, _ = convert(outs[0].data, "2.11")                 # round trip: unchanged
        self.assertEqual(field(back[0].data, "R03")[(2026, 10, 3, 23, 45)], Decimal(30))
        for tk in ("6.047700000000E+05", "-3.000000000000E+01"):     # either week reading
            with self.subTest(v3_value=tk):
                v3 = glo3("3.04", [(3, (2026, 10, 4, 0, 15), tk)])
                outs, rep = convert(v3, "2.11")
                self.assertEqual(field(outs[0].data, "R03")[(2026, 10, 4, 0, 15)], Decimal(86370))
                self.assert_exact(lambda r: compare_nav(v3, [o.data for o in outs], r), rep)

    def test_rinex2_tk_out_of_range_refused(self):
        src = glo2("2.11", [(1, (2026, 10, 1, 0, 15), "0.0D+00", "0.345600000000D+06")])
        with self.assertRaises(CorruptError):
            convert(src, "3.05")


class GlonassTkDayBasis(unittest.TestCase):
    """Real RINEX 3 files (BOR100POL, CKIS00COK 3.02; BRDC00IGS 2017 3.03) write tk as
    seconds of the day. Between RINEX 3/4 versions it is carried and reported (refused under
    --strict); --lenient puts it on the week basis (a repair); to RINEX 2 it is right as is."""

    DAY = glo3("3.04", [(1, (2026, 10, 2, 0, 15), "9.000000000000E+02")])          # a Friday
    LEGIT = glo3("3.04", [(1, (2026, 10, 5, 0, 15), "8.637000000000E+04")])        # Monday: Sun 23:59:30

    def test_validator_warns(self):
        f = V.validate(self.DAY)
        self.assertEqual([x.severity for x in f if x.rule == "VAL.NAV.GLO.TK-DAY-BASIS"], ["warning"])
        self.assertEqual([x for x in V.validate(self.LEGIT) if x.rule == "VAL.NAV.GLO.TK-DAY-BASIS"], [])

    def test_carried_and_reported(self):
        outs, rep = convert(self.DAY, "3.05")
        self.assertEqual(field(outs[0].data, "R01")[(2026, 10, 2, 0, 15)], Decimal(900))
        self.assertEqual([w["rule"] for w in rep["warnings"]], ["NAV.GLO.TK-DAY-BASIS"])
        self.assertEqual(compare_nav(self.DAY, [o.data for o in outs], rep), [])
        quiet = copy.deepcopy(rep)
        quiet["warnings"] = []
        self.assertTrue(compare_nav(self.DAY, [o.data for o in outs], quiet))
        with self.assertRaises(CorruptError):
            convert(self.DAY, "3.05", strict=True)
        outs, rep = convert(self.LEGIT, "3.05")
        self.assertEqual(rep["warnings"], [])

    def test_lenient_repairs(self):
        outs, rep = convert(self.DAY, "4.02", lenient=True)
        self.assertEqual(field(outs[0].data, "R01")[(2026, 10, 2, 0, 15)], Decimal(5 * 86400 + 900))
        self.assertEqual([r["rule"] for r in rep["repairs"]], ["NAV.GLO.TK-DAY-BASIS"])
        self.assertEqual(compare_nav(self.DAY, [o.data for o in outs], rep), [])

    def test_to_rinex2_right_on_either_basis(self):
        outs, rep = convert(self.DAY, "2.11")
        self.assertEqual(field(outs[0].data, "R01")[(2026, 10, 2, 0, 15)], Decimal(900))
        self.assertEqual(compare_nav(self.DAY, [o.data for o in outs], rep), [])


class Glonass200Signs(Exact, unittest.TestCase):
    """N6: a 2.00 GLONASS file stores -GammaN and +TauC; 2.01 and later +GammaN and -TauC."""

    def test_gamma_and_tauc_negated(self):
        src = glo2("2.00", [(1, (2026, 10, 1, 0, 15), "-.909494701773D-12", "0.000000000000D+00")],
                   tauc="0.100000000000D-07")
        outs, rep = convert(src, "2.11")
        self.assertEqual(field(outs[0].data, "R01", 1)[(2026, 10, 1, 0, 15)], Decimal("0.909494701773E-12"))
        head = [l for l in outs[0].data.decode().split("\n") if l[60:].strip() == "CORR TO SYSTEM TIME"]
        self.assertEqual(Decimal(head[0][21:40].replace("D", "E")), Decimal("-1E-8"))
        self.assertEqual(rule_n(rep, "NAV.GLO.V2.00-SIGNS"), 2)
        self.assertEqual(sum(n for d, s, n in assumed(rep, "glonass-nav-2.00-signs")), 2)
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        same = outs[0].data.replace(b" .909494701773D-12", b"-.909494701773D-12")
        self.assertNotEqual(same, outs[0].data)
        self.assertTrue(compare_nav(src, [same], rep))
        # 3.05: GLUT a0 = -TauC (rinex305.txt Table A5)
        outs, rep = convert(src, "3.05")
        glut = [l for l in outs[0].data.decode().split("\n") if l.startswith("GLUT")]
        self.assertEqual(Decimal(glut[0][5:22].replace("D", "E")), Decimal("-1E-8"))
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


# ------------------------------------------------------------------ SBAS
class SbasFrameTime(Exact, unittest.TestCase):
    """N2, on the 2.10 spec example (rinex210.txt Table A18): S20 2000-01-13 14:46:24, a
    Thursday, message frame time 53235.128 s of day -> 4 x 86400 + 53235.128 = 398835.128."""

    def src(self):
        from .test_independent_meta import SPEC
        return (SPEC / "2.10" / "a18_nav_geo.rnx").read_bytes()

    def test_210_to_211_and_back(self):
        src = self.src()
        n = sum(len(v) for k, v in recs(src).items() if k[0] == "EPH")
        for t in ("2.11", "3.05", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertEqual(field(outs[0].data, "S20")[(2000, 1, 13, 14, 46)], Decimal("398835.128"))
                self.assertEqual(rule_n(rep, "NAV.SBAS.FRAME-TIME-BASIS"), n)
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
                # the old behaviour (seconds of day kept) is caught
                lines = outs[0].data.decode().split("\n")
                k = next(i for i, l in enumerate(lines) if l.startswith(("20 00", "S20 2000")) and "14 46" in l)
                lines[k] = lines[k][:-19] + d19(53235.128, "D" if t < "4" else "E")
                self.assertTrue(compare_nav(src, ["\n".join(lines).encode()], rep))
        outs211, _ = convert(src, "2.11")
        outs, rep = convert(outs211[0].data, "2.10")
        self.assertEqual(field(outs[0].data, "S20")[(2000, 1, 13, 14, 46)], Decimal("53235.128"))
        self.assert_exact(lambda r: compare_nav(outs211[0].data, [o.data for o in outs], r), rep)
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("20 00") and "14 46" in l)
        lines[k] = lines[k][:-19] + d19(398835.128)
        self.assertTrue(compare_nav(outs211[0].data, ["\n".join(lines).encode()], rep))

    def test_week_boundary_is_negative(self):
        # Toc Sunday 2026-10-04 00:01 (GPS), frame time Saturday 23:59:50 = 86390 s of day:
        # referred to Toc's GPS week it is -10 (rinex211.txt l.910-915)
        src = self.src().replace(b"20 00 01 13 14 46 24.0", b"20 26 10 04 00 01 00.0").replace(
            b".532351280000D+05", b".863900000000D+05")
        self.assertIn(b"20 26 10 04 00 01 00.0", src)
        outs, rep = convert(src, "3.05")
        self.assertEqual(field(outs[0].data, "S20")[(2026, 10, 4, 0, 1)], Decimal(-10))
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)


# ------------------------------------------------------------------ QZSS area
def ion(version, sat, msg, sub, a0, line2):
    stamp = "2026 10 30 00 00 00"
    return [f"> ION {sat} {msg}" + (f" {sub}" if sub else ""),
            f"    {stamp}" + d19(a0, "E") + d19(2e-8, "E") + d19(-6e-8, "E"),
            "    " + "".join(d19(x, "E") for x in (-1e-7, 9e4, 1e5, -6e4)),
            "    " + "".join(d19(x, "E") for x in line2)]


class QzssRegionCode(Exact, unittest.TestCase):
    """N3 (the reviewer's repro: 4.01 '> ION J02 CNVX' with region 1.0 to 4.02 was written
    WIDE with the 1.0 left on the Beta3 line)."""

    def test_401_code_1_is_japn(self):
        src = payload(nav_v4("4.01") + ion("4.01", "J02", "CNVX", "", 3e-8, (-5e5, 1.0)))
        for opt in (None, "WIDE"):                     # the code in the source wins
            with self.subTest(option=opt):
                outs, rep = convert(src, "4.02", qzss_ion_area=opt)
                lines = outs[0].data.decode().split("\n")
                k = lines.index("> ION J02 CNVX JAPN")
                self.assertEqual(lines[k + 3].rstrip(), "    " + d19(-5e5, "E"))     # Beta3 only
                self.assertEqual(assumed(rep, "qzss-ion-area"), [])
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
                wide = outs[0].data.replace(b"CNVX JAPN", b"CNVX WIDE")
                self.assertTrue(compare_nav(src, [wide], rep))

    def test_402_japn_to_401_code_1(self):
        # DLR writes WIDE/JAPN on QZSS LNAV too (BRD400DLR 4.02): both become the code
        src = payload(nav_v4("4.02") + ion("4.02", "J02", "LNAV", "JAPN", 3e-8, (-5e5,))
                      + ion("4.02", "J03", "CNVX", "JAPN", 3e-8, (-5e5,)))
        outs, rep = convert(src, "4.01")
        out = outs[0].data.decode().split("\n")
        for head in ("> ION J02 LNAV", "> ION J03 CNVX"):
            k = out.index(head)
            self.assertEqual(out[k + 3], "    " + d19(-5e5, "E") + d19(1.0, "E"))
        self.assertNotIn("nav-subtype-not-representable:ION:J:CNVX", rep["losses"])
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        wide = outs[0].data.replace(("    " + d19(-5e5, "E") + d19(1.0, "E")).encode(),
                                    ("    " + d19(-5e5, "E") + d19(0.0, "E")).encode())
        self.assertNotEqual(wide, outs[0].data)
        self.assertTrue(compare_nav(src, [wide], rep))

    def test_401_lnav_area_has_no_402_place(self):
        # the user's decision of 2026-11-02: the area as the LNAV subtype, as DLR (BRD400DLR)
        # writes it, not rinex_4.02.txt Table A35 note 3* (it was claimed
        # nav-ion-area-not-representable:J:LNAV)
        src = payload(nav_v4("4.01") + ion("4.01", "J02", "LNAV", "", 3e-8, (-5e5, 1.0)))
        outs, rep = convert(src, "4.02")
        self.assertIn(b"\n> ION J02 LNAV JAPN\n", outs[0].data)
        self.assertEqual(rep["losses"], {})
        self.assertEqual([f.severity for f in V.validate(outs[0].data) if "DLR" in f.message], ["warning"])
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        self.assertTrue(compare_nav(src, [outs[0].data.replace(b"LNAV JAPN", b"LNAV WIDE")], rep))
        # a code naming no area is still claimed
        src = payload(nav_v4("4.01") + ion("4.01", "J02", "LNAV", "", 3e-8, (-5e5, 2.0)))
        outs, rep = convert(src, "4.02")
        self.assertEqual(rep["losses"]["nav-ion-area-not-representable:J:LNAV"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_401_area_to_rinex3_claimed(self):
        src = payload(nav_v4("4.01") + ion("4.01", "J02", "CNVX", "", 3e-8, (-5e5, 1.0)))
        outs, rep = convert(src, "3.05")
        self.assertEqual(rep["losses"]["nav-ion-area-not-representable:J:CNVX"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_rinex3_set_into_401(self):
        h = [hdr("     3.05           N: GNSS NAV DATA    M: MIXED", "RINEX VERSION / TYPE"),
             hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
             hdr("QZSA " + "".join(f"{v:12.4E}" for v in (1.676e-8, 2.235e-8, -1.192e-7, -1.192e-7)),
                 "IONOSPHERIC CORR"),
             hdr("QZSB " + "".join(f"{v:12.4E}" for v in (1.1e5, 1.3e5, -6.6e4, -3.9e5)), "IONOSPHERIC CORR"),
             hdr("    18", "LEAP SECONDS"), hdr("", "END OF HEADER")]
        from .test_validate import nav_v3_record
        src = payload(h + nav_v3_record("J01", (2026, 10, 30, 0, 0, 0), 8))
        outs, rep = convert(src, "4.01")
        self.assertEqual(assumed(rep, "qzss-ion-area"), [("WIDE", "spec-default:blank-region-code", 1)])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        outs, rep = convert(src, "4.01", qzss_ion_area="JAPN")
        out = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(out) if l.startswith("> ION J"))
        self.assertEqual(out[k + 3][23:42], " 1.000000000000E+00")
        self.assertEqual(assumed(rep, "qzss-ion-area"), [("JAPN", "user", 1)])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        # 4.02: the LNAV subtype, as DLR writes it (the user's decision of 2026-11-02)
        outs, rep = convert(src, "4.02", qzss_ion_area="JAPN")
        self.assertIn(b"LNAV JAPN", outs[0].data)
        self.assertEqual(assumed(rep, "qzss-ion-area"), [("JAPN", "user", 1)])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        self.assertTrue(compare_nav(src, [outs[0].data.replace(b"LNAV JAPN", b"LNAV WIDE")], rep))
        outs, rep = convert(src, "4.02")                        # no option: no area
        self.assertNotIn(b"LNAV JAPN", outs[0].data)
        self.assertEqual(assumed(rep, "qzss-ion-area"), [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


# ------------------------------------------------------------------ fields per line
def gps_v3(version, orbit7, cnav=None):
    """A RINEX 3 GPS record with BROADCAST ORBIT 7 values `orbit7`."""
    h = [hdr(f"{version:>9s}           N: GNSS NAV DATA    G: GPS", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
         hdr("    18", "LEAP SECONDS"), hdr("", "END OF HEADER")]
    from .test_validate import nav_v3_record
    r = nav_v3_record("G01", (2026, 10, 30, 0, 0, 0), 7)
    r.append("    " + "".join(d19(x, "E") for x in orbit7))
    return payload(h + r)


class FieldsPerLine(Exact, unittest.TestCase):
    """N4 and P1."""

    def test_rinex3_spares_cut_from_lnav(self):
        # 3.x GPS orbit 7 't_tm, fit interval, spare, spare' (rinex305.txt Table A6); 4.x LNAV
        # orbit 7 't_tm, fit interval' (rinex_4.02.txt Table A9 p.79)
        zero = gps_v3("3.03", (3.45618e5, 4.0, 0.0, 0.0))
        outs, rep = convert(zero, "4.02")
        last = outs[0].data.decode().rstrip("\n").split("\n")[-1]
        self.assertEqual(last, "    " + d19(3.45618e5, "E") + d19(4.0, "E"))
        self.assertEqual(rep["losses"], {})
        self.assert_exact(lambda r: compare_nav(zero, [o.data for o in outs], r), rep)
        spare = gps_v3("3.03", (3.45618e5, 4.0, 7.0, 0.0))
        outs, rep = convert(spare, "4.02")
        self.assertEqual(rep["losses"]["nav-spare-value-dropped:EPH:G"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assert_exact(lambda r: compare_nav(spare, [o.data for o in outs], r), rep)

    def test_402_cnav_flags_to_401(self):
        from .test_validate import nav_v3_record
        rec = nav_v3_record("G04", (2026, 10, 30, 0, 0, 0), 9)
        flagged = payload(nav_v4("4.02") + ["> EPH G04 CNAV"] + rec[:-1]
                          + ["    " + d19(3.45618e5, "E") + d19(2438.0, "E") + d19(0.0, "E")])
        self.assertEqual(V.errors(V.validate(flagged)), [])
        outs, rep = convert(flagged, "4.01")
        self.assertEqual(rep["losses"]["nav-field-not-representable:G:CNAV:flags"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(V.errors(V.validate(outs[0].data)), [])
        self.assert_exact(lambda r: compare_nav(flagged, [o.data for o in outs], r), rep)
        blank = payload(nav_v4("4.02") + ["> EPH G04 CNAV"] + rec[:-1]
                        + ["    " + d19(3.45618e5, "E") + d19(2438.0, "E")])
        outs, rep = convert(blank, "4.01")
        self.assertEqual(rep["losses"], {})
        # a 4.01 line with a third field is no 4.01 line
        bad = outs[0].data.replace(("    " + d19(3.45618e5, "E") + d19(2438.0, "E")).encode(),
                                   ("    " + d19(3.45618e5, "E") + d19(2438.0, "E") + d19(1.0, "E")).encode())
        self.assertTrue(any(f.rule == "VAL.NAV.FIELDS" for f in V.errors(V.validate(bad))))


# ------------------------------------------------------------------ SBAS STO in 4.00/4.01
class SbasStoIn400(Exact, unittest.TestCase):
    """P3: STO satellite systems G,R,E,C,J,I in 4.00/4.01 (rinex_4.00.txt Table A30 p.102,
    rinex_4.01.txt l.6062 p.106); S from 4.02 (rinex_4.02.txt Table A33 p.115)."""

    def test_402_sto_s_to_401(self):
        stamp = "2026 10 30 00 00 00"
        src = payload(nav_v4("4.02") + ["> STO S27 SBAS",
                                        f"    {stamp} " + "SBUT".ljust(18) + " " + "EGNOS".ljust(18),
                                        "    " + "".join(d19(x, "E") for x in (1e5, 1e-9, 0.0, 0.0))])
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "4.01")
        self.assertNotIn(b"> STO S", outs[0].data)
        self.assertEqual(rep["losses"]["nav-sto-system-not-representable:S:SBUT"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        kept = payload(nav_v4("4.01") + [l for l in lines_of(src)[len(nav_v4("4.02")):]])
        self.assertTrue(any(f.rule == "VAL.NAV.SYSTEM" for f in V.errors(V.validate(kept))))


# ------------------------------------------------------------------ UTC week
def gps_v2(w, year_month_day=(2010, 6, 29)):
    y, mo, d = year_month_day
    h = [hdr("     2.10           N: GPS NAV DATA", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20100630 000000 UTC", "PGM / RUN BY / DATE"),
         hdr("   " + d19(1.3e-7) + d19(1.1e-13) + f"{552960:9d}{w:9d}", "DELTA-UTC: A0,A1,T,W"),
         hdr("", "END OF HEADER")]
    from .test_validate import nav_v2_record
    return payload(h + nav_v2_record(1, (y, mo, d, 0, 0, 0.0), 8))


class TruncatedUtcWeek(Exact, unittest.TestCase):
    """N5: brdc1800.10n writes W=566 for week 1590 (mod 1024), tubi1800.15n W=59 for 1851
    (mod 256); they went to 4.02 as STO records of 1990 and 1981."""

    def test_resolved_everywhere(self):
        for w, day, want in ((566, (2010, 6, 29), 1590), (59, (2015, 6, 29), 1851)):
            src = gps_v2(w, day)
            for t in ("2.11", "3.05", "4.02"):
                with self.subTest(W=w, target=t):
                    outs, rep = convert(src, t)
                    self.assertEqual([r["rule"] for r in rep["repairs"]], ["NAV.HDR.UTC-WEEK"])
                    text = outs[0].data.decode()
                    if t == "2.11":
                        line = next(l for l in text.split("\n") if "DELTA-UTC" in l)
                        self.assertEqual(int(line[50:59]), want)
                    elif t == "3.05":
                        line = next(l for l in text.split("\n") if l.startswith("GPUT"))
                        self.assertEqual(int(line[45:50]), want)
                    else:
                        k = text.split("\n").index("> STO G   LNAV")
                        epoch = text.split("\n")[k + 1][4:14]
                        self.assertEqual(epoch[:4], str(day[0]))
                    self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
                    norep = copy.deepcopy(rep)
                    norep["repairs"] = []
                    self.assertTrue(compare_nav(src, [o.data for o in outs], norep))
            with self.assertRaises(CorruptError):
                convert(src, "3.05", strict=True)

    def test_continuous_week_untouched(self):
        outs, rep = convert(gps_v2(1590), "3.05")
        self.assertEqual(rep["repairs"], [])


# ------------------------------------------------------------------ checker holes
class CheckerHoles(unittest.TestCase):
    """C1-C3, from the reviewer's mutations of real outputs (each passed compare_nav)."""

    def test_sto_identifiers_compared(self):
        src = payload(nav_v4("4.02"))
        outs, rep = convert(src, "4.01")
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        for old, new in ((b"UTC(USNO)", b"UTC(NIST)"), (b"GPUT", b"GAUT")):
            bad = outs[0].data.replace(old, new)
            self.assertNotEqual(bad, outs[0].data)
            self.assertTrue(compare_nav(src, [bad], rep), new)
        added = outs[0].data.replace(b"GPUT                  ", b"GPUT               EGNOS")
        self.assertNotEqual(added, outs[0].data)
        self.assertTrue(compare_nav(src, [added], rep))

    def test_records_from_header_corrections(self):
        from .test_validate import nav_v2_gps
        src = payload(nav_v2_gps())
        outs, rep = convert(src, "4.02")
        data = outs[0].data
        self.assertEqual(compare_nav(src, [data], rep), [])
        lines = data.decode().split("\n")
        k_ion = next(i for i, l in enumerate(lines) if l.startswith("> ION"))
        k_sto = next(i for i, l in enumerate(lines) if l.startswith("> STO"))

        def mutate(k, f):
            m = list(lines)
            m[k] = f(m[k])
            return "\n".join(m).encode()
        for what, bad in (
                ("ION epoch +1 day", mutate(k_ion + 1, lambda l: l[:12] + "%02d" % (int(l[12:14]) + 1) + l[14:])),
                ("ION LNAV->CNAV", mutate(k_ion, lambda l: l.replace("LNAV", "CNVX"))),
                ("ION G->G01", mutate(k_ion, lambda l: l.replace("G  ", "G01"))),
                ("STO t_tm 0", mutate(k_sto + 2, lambda l: "    " + d19(0.0, "E") + l[23:])),
                ("STO t_tm +600", mutate(k_sto + 2, lambda l: "    " + d19(float(l[4:23]) + 600, "E") + l[23:])),
                ("STO LNAV->CNVX", mutate(k_sto, lambda l: l.replace("LNAV", "CNVX")))):
            with self.subTest(mutation=what):
                self.assertNotEqual(bad, data)
                self.assertTrue(compare_nav(src, [bad], rep), what)

    def test_eph_body_satellite(self):
        src = payload(nav_v4("4.02"))
        outs, rep = convert(src, "4.02")
        bad = outs[0].data.replace(b"\nG01 2026", b"\nG02 2026", 1)
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_nav(src, [bad], rep))


# ------------------------------------------------------------------ BDS reference week (Q3)
def bds_v3(version, t, w, day, spares=None):
    """A BeiDou-only RINEX 3 file with a BDUT TIME SYSTEM CORR of T and W
    (A4,1X,D17.10,D16.9,1X,I6,1X,I4: rinex305.txt Table A5 p.67)."""
    from .test_validate import nav_v3_record
    h = [hdr(f"{version:>9s}           N: GNSS NAV DATA    C: BEIDOU", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
         hdr("BDUT " + f"{-3.7252902985e-9:17.10E}" + f"{9.769962617e-15:16.9E}" + f"{t:7d}{w:5d}",
             "TIME SYSTEM CORR"),
         hdr("", "END OF HEADER")]
    rec = nav_v3_record("C06", day + (0, 0, 0), 8)
    rec[5] = "    " + ("".join(" " * 19 if x is None else d19(x) for x in spares) if spares
                         else d19(1e-10) + " " * 19 + d19(860.0))
    return payload(h + rec)


def bdut(data):
    return next(l for l in data.decode().split("\n") if l.startswith("BDUT"))


class BdsReferenceWeek(Exact, unittest.TestCase):
    """Q3: BDUT T and W count BDS weeks from 3.03 (rinex303.txt p.70, rinex304.txt p.75,
    rinex305.txt Table A5 p.67) and GPS weeks in 3.02 (rinex302.txt Table A5 p.63); 'BDT zero
    time started at 00:00:00 UTC on January 1st, 2006 (GPS week 1356) therefore BDT is 14
    seconds behind GPS time' (rinex305.txt section 4.1.4 p.16): GPS week w second t is BDS week
    w - 1356 second t - 14."""

    def test_304_gps_week_repaired(self):
        # BRDM00DLR 3.04 writes 14 2216 (GPS) for BDS week 860 second 0; its 4.02 STO record
        # was dated 2048
        src = bds_v3("3.04", 14, 2216, (2022, 6, 29))
        outs, rep = convert(src, "3.04")
        self.assertEqual(bdut(outs[0].data)[38:50], "      0  860")
        self.assertEqual([r["rule"] for r in rep["repairs"]], ["NAV.HDR.BDS-WEEK"])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        norep = copy.deepcopy(rep)
        norep["repairs"] = []
        self.assertTrue(compare_nav(src, [o.data for o in outs], norep))
        with self.assertRaises(CorruptError):
            convert(src, "3.04", strict=True)
        outs, rep = convert(src, "4.02")
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("> STO C"))
        self.assertEqual(lines[k + 1][4:23], "2022 06 26 00 00 00")     # 2006-01-01 + 860 weeks
        self.assertEqual(Decimal(lines[k + 2][4:23]), 0)
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_302_gps_terms_converted(self):
        src = bds_v3("3.02", 14, 1851, (2015, 6, 29))
        outs, rep = convert(src, "3.02")
        self.assertEqual(bdut(outs[0].data)[38:50], "     14 1851")      # 3.02's own terms
        self.assertEqual(rep["repairs"], [])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        outs, rep = convert(src, "3.05")
        self.assertEqual(bdut(outs[0].data)[38:50], "      0  495")
        self.assertEqual(rule_n(rep, "NAV.HDR.BDS-WEEK-BASIS"), 1)
        self.assertEqual(rep["repairs"], [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        bad = outs[0].data.replace(b"      0  495", b"     14 1851")
        self.assertTrue(compare_nav(src, [bad], rep))
        back = bds_v3("3.05", 345185, 1082, (2026, 10, 1))
        outs, rep = convert(back, "3.02")
        self.assertEqual(bdut(outs[0].data)[38:50], " 345199 2438")
        self.assert_exact(lambda r: compare_nav(back, [o.data for o in outs], r), rep)

    def test_303_names_both(self):
        # the 3.03 example itself writes BDUT ... 14 1849 (rinex303.txt; 3.04 corrected the text)
        src = bds_v3("3.03", 14, 1849, (2015, 6, 15))
        outs, rep = convert(src, "3.03")
        self.assertEqual(bdut(outs[0].data)[38:50], "     14 1849")      # kept as written
        self.assertEqual(assumed(rep, "bds-week-basis"),
                         [("BDUT:GPS-week", "data:W-near-the-ephemeris-GPS-week", 1)])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        outs, rep = convert(src, "3.05")
        self.assertEqual(bdut(outs[0].data)[38:50], "      0  493")
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])


class SparesLeftBlank(Exact, unittest.TestCase):
    """Q4: 'Spare fields are to be left blank so as to avoid confusion' (rinex_4.02.txt section
    6.4 p.48; rinex_4.00.txt p.43; rinex_4.01.txt p.46): BDS D1/D2 BROADCAST ORBIT 5 'IDOT,
    Spare, BDT Week #, Spare' (Table A23 p.100)."""

    def test_rinex3_spare_values(self):
        # BOR100POL (cnvtToRINEX 3.02) writes 1.0 in the first spare
        src = bds_v3("3.05", 345185, 1082, (2026, 10, 1), spares=(1e-10, 1.0, 1082.0, 0.0))
        outs, rep = convert(src, "4.02")
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("C06 "))
        self.assertEqual(lines[k + 5], "    " + d19(1e-10).replace("D", "E") + " " * 19 + d19(1082.0).replace("D", "E"))
        # the orbit 5 spare's 1.0 (not its 0.0; orbit 7's RINEX 3 spares hold 0, which D1
        # orbit 7 't_tm, AODC' has no field for: Table A23 p.100, blank, nothing claimed)
        self.assertEqual(rep["losses"]["nav-spare-value-dropped:EPH:C"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual([f for f in V.validate(outs[0].data) if f.rule == "VAL.NAV.SPARE"], [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_rinex4_own_spare(self):
        b = nav_v4("4.02")
        k = b.index("> EPH C05 D2") + 6
        for value, claims in ((0.0, 0), (1.0, 1)):
            with self.subTest(spare=value):
                v4 = list(b)
                v4[k] = v4[k][:23] + d19(value, "E") + v4[k][42:]
                src = payload(v4)
                self.assertEqual([f.severity for f in V.validate(src) if f.rule == "VAL.NAV.SPARE"], ["warning"])
                outs, rep = convert(src, "4.02")
                self.assertEqual(rep["losses"].get("nav-spare-value-dropped:EPH:C", {}).get("count", 0), claims)
                self.assertEqual([f for f in V.validate(outs[0].data) if f.rule == "VAL.NAV.SPARE"], [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)


# ======================================================================== review round 33
def v3_with_corr(version, corr_line, day, sat="G01"):
    """A RINEX 3 file with one TIME SYSTEM CORR record and one ephemeris on `day`."""
    from .test_validate import nav_v3_record
    h = [hdr(f"{version:>9s}           N: GNSS NAV DATA    M: MIXED", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
         hdr(corr_line, "TIME SYSTEM CORR"),
         hdr("    18", "LEAP SECONDS"), hdr("", "END OF HEADER")]
    return payload(h + nav_v3_record(sat, day + (0, 0, 0), 8))


def pos(data, sat, k):
    """Value position k of the (first) record of `sat` (None: blank or absent)."""
    v = next(lst[0][1] for key, lst in recs(data).items() if key[0] == "EPH" and key[1] == sat)
    return v[k] if k < len(v) else None


def gps_date(week, sow):
    import datetime
    return datetime.datetime(1980, 1, 6) + datetime.timedelta(weeks=week, seconds=sow)


class SystemWeekBasis(Exact, unittest.TestCase):
    """S1: BRDC00IGS 2022 3.04 writes 'IRUT ... 173088 1192', a NavIC week (NavIC/IRNSS and GST
    broadcast week 0 = RINEX week 1024: rinex305.txt Table 3 p.18), where TIME SYSTEM CORR wants
    the week 'aligned to GPS, continuous number from 6-Jan-1980' (Table A5 p.67): GPS week 2216.
    Its 4.02 STO record was dated 2002."""

    def check(self, code, sys_, t, w, day, want_w):
        line = f"{code} " + f"{1.36788e-9:17.10E}" + f"{1.0658e-14:16.9E}" + f" {t:6d} {w:4d}"
        src = v3_with_corr("3.04", line, day)
        outs, rep = convert(src, "3.04")
        corr = next(l for l in outs[0].data.decode().split("\n") if l.startswith(code))
        self.assertEqual(int(corr[45:50]), want_w)
        self.assertEqual([r["rule"] for r in rep["repairs"]], ["NAV.HDR.UTC-WEEK"])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        outs, rep = convert(src, "4.02")
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith(f"> STO {sys_}"))
        self.assertEqual(lines[k + 1][4:23], gps_date(want_w, t).strftime("%Y %m %d %H %M %S"))
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        norep = copy.deepcopy(rep)
        norep["repairs"] = []
        self.assertTrue(compare_nav(src, [o.data for o in outs], norep))

    def test_irut_navic_weeks(self):
        self.check("IRUT", "I", 173088, 1192, (2022, 6, 28), 2216)     # BRDC00IGS 2022
        self.check("IRUT", "I", 172800, 1296, (2024, 6, 25), 2320)     # BRDC00IGS 2024

    def test_gaut_gst_week(self):
        self.check("GAUT", "E", 345600, 1192, (2022, 6, 30), 2216)


class SparesV2V3(Exact, unittest.TestCase):
    """S2: a field spare in one RINEX 2/3 version and real in another. A spare holds no defined
    content: it fills no field and no value goes into it (rinex305.txt section 6.4 p.42)."""

    def geo(self, version, last):
        h = [hdr(f"{version:>9s}           H: GEO NAV MSG DATA", "RINEX VERSION / TYPE"),
             hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE"),
             hdr("", "END OF HEADER"),
             "20 26 10  1  0  1  4.0-0.100582838059D-06 0.636646291241D-11 0.345642000000D+06"
             if version >= "2.11" else
             "20 26 10  1  0  1  4.0-0.100582838059D-06 0.636646291241D-11 0.420000000000D+02",
             "    0.248283239200D+05-0.359375000000D-03-0.137500000000D-06 0.000000000000D+00",
             "   -0.340892087200D+05-0.148062500000D-02-0.500000000000D-07 0.400000000000D+01",
             "   -0.165056000000D+02 0.836000000000D-03 0.625000000000D-07" + last]
        return payload(h)

    def iodn(self, data):
        return pos(data, "S20", 14)

    def test_iodn_to_210(self):
        from tests.independent.navfields import compare_nav_fields
        src = self.geo("2.11", " 0.230000000000D+02")       # bill2740.26h: IODN 178
        outs, rep = convert(src, "2.10")
        self.assertIsNone(self.iodn(outs[0].data))
        self.assertEqual(rep["losses"]["nav-field-not-representable:S:SBAS:IODN"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        self.assertEqual(compare_nav_fields(src, [o.data for o in outs]), [])
        kept = outs[0].data.replace(b"0.625000000000D-07\n", b"0.625000000000D-07 0.230000000000D+02\n")
        self.assertNotEqual(kept, outs[0].data)
        self.assertTrue(compare_nav(src, [kept], rep))
        self.assertTrue(compare_nav_fields(src, [kept]))

    def test_210_spare_is_no_iodn(self):
        from tests.independent.navfields import compare_nav_fields
        for last, claims in ((" 0.000000000000D+00", 0), (" 0.500000000000D+01", 1)):
            with self.subTest(spare=last):
                src = self.geo("2.10", last)
                outs, rep = convert(src, "3.05")
                self.assertIsNone(self.iodn(outs[0].data))      # not an invented IODN 0
                self.assertEqual(rep["losses"].get("nav-spare-value-dropped:EPH:S", {}).get("count", 0), claims)
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
                self.assertEqual(compare_nav_fields(src, [o.data for o in outs]), [])
                lines = outs[0].data.decode().split("\n")
                k = next(i for i, l in enumerate(lines) if l.startswith("S20"))
                lines[k + 3] = lines[k + 3].rstrip() + d19(0.0, "D")
                self.assertTrue(compare_nav(src, ["\n".join(lines).encode()], rep))
                self.assertTrue(compare_nav_fields(src, ["\n".join(lines).encode()]))

    def test_qzss_l2p_flag_and_302_spare(self):
        from .test_validate import nav_v3_record

        def qzs(version, flag):
            rec = nav_v3_record("J02", (2026, 10, 1, 0, 0, 0), 8)
            rec[5] = rec[5][:61] + ("" if flag is None else d19(flag, "E"))
            h = [hdr(f"{version:>9s}           N: GNSS NAV DATA    J: QZSS", "RINEX VERSION / TYPE"),
                 hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE"),
                 hdr("", "END OF HEADER")]
            return payload(h + rec)
        src = qzs("3.03", 1.0)                                  # BRDC00IGS J02: L2 P flag 1
        outs, rep = convert(src, "3.02")
        self.assertIsNone(pos(outs[0].data, "J02", 22))
        self.assertEqual(rep["losses"]["nav-field-not-representable:J:LNAV:L2P-flag"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        back = qzs("3.02", 1.0)                                 # a value in the 3.02 spare
        outs, rep = convert(back, "3.05")
        self.assertEqual(rep["losses"]["nav-spare-value-dropped:EPH:J"]["count"], 1)
        self.assert_exact(lambda r: compare_nav(back, [o.data for o in outs], r), rep)
        self.assertEqual([f.severity for f in V.validate(back) if f.rule == "VAL.NAV.SPARE"], ["warning"])


class Round33Polish(unittest.TestCase):

    def test_tk_day_basis_later_than_toc(self):
        # P1: Monday 00:15 with tk 1470 (00:24:30) is the day basis; 86370 (Sunday 23:59:30) is not
        day = glo3("3.04", [(1, (2026, 10, 5, 0, 15), "1.470000000000E+03")])
        legit = glo3("3.04", [(1, (2026, 10, 5, 0, 15), "8.637000000000E+04")])
        self.assertTrue([f for f in V.validate(day) if f.rule == "VAL.NAV.GLO.TK-DAY-BASIS"])
        self.assertFalse([f for f in V.validate(legit) if f.rule == "VAL.NAV.GLO.TK-DAY-BASIS"])
        outs, rep = convert(day, "4.02", lenient=True)
        self.assertEqual(field(outs[0].data, "R01")[(2026, 10, 5, 0, 15)], Decimal(86400 + 1470))
        self.assertEqual(compare_nav(day, [o.data for o in outs], rep), [])
        outs, rep = convert(legit, "4.02", lenient=True)
        self.assertEqual(rep["repairs"], [])

    def test_glut_from_rinex2(self):
        # P3: GLUT 'a1 = zero' (rinex305.txt Table A5 p.66); its UTC ID UTC(SU) (rinex_4.02.txt
        # Table 27 p.43)
        src = glo2("2.11", [(1, (2026, 10, 1, 0, 15), "0.0D+00", "0.000000000000D+00")],
                   tauc="-0.100000000000D-07")
        outs, rep = convert(src, "3.05")
        glut = next(l for l in outs[0].data.decode().split("\n") if l.startswith("GLUT"))
        self.assertEqual(Decimal(glut[22:38].replace("D", "E")), 0)
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        outs, rep = convert(src, "4.02")
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("> STO R"))
        self.assertEqual(lines[k + 1][62:80].strip(), "UTC(SU)")
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        bad = "\n".join(lines[:k + 1] + [lines[k + 1][:62]] + lines[k + 2:]).encode()
        self.assertTrue(compare_nav(src, [bad], rep))

    def test_zero_ttm_formatted(self):
        # P4: t_tm of T = 0 was written 0.000000000000E+12
        line = "GPUT " + f"{1.3e-7:17.10E}" + f"{1.1e-13:16.9E}" + f" {0:6d} {2438:4d}"
        src = v3_with_corr("3.05", line, (2026, 10, 1))
        outs, rep = convert(src, "4.02")
        lines = outs[0].data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("> STO G"))
        self.assertEqual(lines[k + 2][4:23], " 0.000000000000E+00")

    def test_200_signs_warned(self):
        # P5: a modern file mislabelled '2' would be flipped: visible as a warning
        src = glo2("2.00", [(1, (2026, 10, 1, 0, 15), "-.909494701773D-12", "0.000000000000D+00")],
                   tauc="0.100000000000D-07")
        outs, rep = convert(src, "2.11")
        self.assertEqual([w["rule"] for w in rep["warnings"]].count("NAV.GLO.V2.00-SIGNS"), 1)


class UtcIdTable(unittest.TestCase):
    """'A UTC ID is necessary, as detailed in Table 27, for every "UT" time offset message'
    (rinex_4.02.txt p.43; rinex_4.00.txt Table 23 p.40, rinex_4.01.txt Table 23 p.42, the same
    rows): GPUT UTC(USNO), GLUT UTC(SU), GAUT UTCGAL, BDUT UTC(NTSC), QZUT UTC(NICT)."""

    WANT = {"GPUT": "UTC(USNO)", "GAUT": "UTCGAL", "BDUT": "UTC(NTSC)", "QZUT": "UTC(NICT)"}

    def sto_utc(self, data, code):
        lines = data.decode().split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("> STO") and lines[i + 1][24:42].strip() == code)
        return lines[k + 1][62:80].strip()

    def test_rinex3_without_u(self):
        sat = {"GPUT": "G01", "GAUT": "E11", "BDUT": "C06", "QZUT": "J02"}
        for code, want in self.WANT.items():
            for t in ("4.00", "4.01", "4.02"):
                with self.subTest(code=code, target=t):
                    w, ttm = (1082, 345600) if code == "BDUT" else (2438, 345600)
                    line = f"{code} " + f"{1.3e-9:17.10E}" + f"{1.1e-14:16.9E}" + f" {ttm:6d} {w:4d}"
                    src = v3_with_corr("3.05", line, (2026, 10, 1), sat[code])
                    outs, rep = convert(src, t)
                    self.assertEqual(self.sto_utc(outs[0].data, code), want)
                    self.assertGreaterEqual(rule_n(rep, "NAV.STO.UTC-ID"), 1)
                    self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
                    lines = outs[0].data.decode().split("\n")
                    bad = "\n".join(l.replace(want, " " * len(want)).rstrip() if l[24:42].strip() == code else l
                                    for l in lines).encode()
                    self.assertNotEqual(bad, outs[0].data)
                    self.assertTrue(compare_nav(src, [bad], rep))

    def test_source_id_wins(self):
        # U = 1 (UTC(NIST), rinex305.txt Table A5) on GPUT: kept, the conflict warned
        line = "GPUT " + f"{1.3e-9:17.10E}" + f"{1.1e-14:16.9E}" + f" {345600:6d} {2438:4d}" + " G10    1"
        src = v3_with_corr("3.05", line, (2026, 10, 1))
        outs, rep = convert(src, "4.02")
        self.assertEqual(self.sto_utc(outs[0].data, "GPUT"), "UTC(NIST)")
        self.assertIn("NAV.STO.UTC-ID-CONFLICT", [w["rule"] for w in rep["warnings"]])
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])

    def test_rinex4_record_without_id(self):
        b = nav_v4("4.02")
        k = b.index("> STO G01 LNAV") + 1
        b[k] = b[k][:62].rstrip()                               # GPUT without its UTC ID
        src = payload(b)
        for t in ("4.01", "4.02"):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                self.assertEqual(self.sto_utc(outs[0].data, "GPUT"), "UTC(USNO)")
                self.assertEqual(rule_n(rep, "NAV.STO.UTC-ID"), 1)
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
                bad = outs[0].data.replace(b"UTC(USNO)", b"")
                self.assertTrue(compare_nav(src, [bad], rep))


class TocWeekValuesInRinex3(unittest.TestCase):
    """U3: RINEX 3/4 values near the week boundary on either reading (Toc's week: -30, 604830;
    the frame's own week: 604770, 603000-ish) are no day-basis tk, and are carried as written
    between RINEX 3/4 versions."""

    def test_not_day_basis_and_carried(self):
        for toc, tk in (((2026, 10, 4, 0, 15), "-3.000000000000E+01"),
                        ((2026, 10, 4, 0, 15), "6.047700000000E+05"),
                        ((2026, 10, 3, 23, 45), "6.048300000000E+05"),
                        ((2026, 10, 3, 23, 45), "6.030000000000E+05")):
            with self.subTest(toc=toc, tk=tk):
                src = glo3("3.04", [(3, toc[:5], tk)])
                self.assertEqual([f for f in V.validate(src) if f.rule == "VAL.NAV.GLO.TK-DAY-BASIS"], [])
                outs, rep = convert(src, "4.02")
                self.assertEqual(field(outs[0].data, "R03")[toc[:5]], Decimal(tk.replace("E", "E")))
                self.assertEqual(rep["warnings"], [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
                outs, rep = convert(src, "2.11")                 # down: mod 86400
                self.assertEqual(field(outs[0].data, "R03")[toc[:5]], Decimal(tk) % 86400 if Decimal(tk) >= 0
                                 else Decimal(tk) + 86400)


if __name__ == "__main__":
    unittest.main()
