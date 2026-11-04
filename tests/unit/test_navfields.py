"""The field-by-name navigation check (tests/independent/navfields.py, PLAN §1 clause 5a).

(i)   every spec-example navigation record parses into the line count of its layout;
(ii)  mutation: two fields swapped inside one record of a real converter output (or a key
      field moved) are reported, by name;
(iii) clean conversions report nothing;
plus the version-to-version transformations the specs define, on hand-written records
(GLONASS tk day <-> week, the RINEX 2.00 GammaN sign, SBAS 2.10 frame time, the unknown
transmission time, the D19.12 precision rule, the Galileo message type).

Corpus tests need data/corpus (gitignored) and are skipped without it."""

import glob
import unittest
from pathlib import Path

from rinexconv.engine import Options, convert_data
from rinexcore.io.compress import unwrap
from tests.independent.navfields import (compare_nav_fields, field_columns, layout_for, nav_field_check,
                                         named, parse_nav)

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "tests" / "fixtures" / "spec_examples"
CORPUS = ROOT / "data" / "corpus" / "nav"


def L(*ls):
    return ("\n".join(ls) + "\n").encode("latin-1")


def hdr(content, label):
    return content.ljust(60) + label


def convert(raw, name, target):
    return [o.data for o in convert_data(raw, name, Options(target, crx=False, compression="none"))]


def kinds(problems):
    return [(p["kind"], p["field"]) for p in problems]


# ----------------------------------------------------------------------------------------
# (i) spec examples
# ----------------------------------------------------------------------------------------

# tests/fixtures/spec_errata.md E-13: the 4.01 Table A12 CNV2 record lacks BROADCAST ORBIT - 7
SHORT_RECORDS = {("4.01/a12_nav_gps.rnx", "G04", "CNV2"): 9}

# Spec-example conversions the converter gets wrong by this check (filled in from the corpus
# run of 2026-11-02; see the report): (example, target) -> what
KNOWN_FINDINGS = {
    # SBAS 2.10 'message frame time (sec of day GPS)' kept as the 2.11+ transmission time in
    # GPS seconds of the week (rinex210.txt l.1656 vs rinex211.txt l.909-915)
    ("2.10/a18_nav_geo.rnx", "2.11"): "sbas-2.10-frame-time",
    ("2.10/a18_nav_geo.rnx", "3.05"): "sbas-2.10-frame-time",
    # and back: 2.11 seconds of week written into the 2.10 seconds-of-day field
    ("2.11/a18_nav_geo_derived_columns.rnx", "2.10"): "sbas-2.10-frame-time",
}


class SpecExamples(unittest.TestCase):
    def files(self):
        out = [p for p in sorted(glob.glob(str(SPEC / "*" / "*nav*.rnx"))) if "header_example" not in p]
        self.assertGreater(len(out), 50)
        return out

    def test_every_record_has_its_layout_line_count(self):
        seen = set()
        for p in self.files():
            rel = Path(p).parent.name + "/" + Path(p).name
            f = parse_nav(Path(p).read_bytes())
            self.assertTrue(f.records, rel)
            for r in f.records:
                with self.subTest(file=rel, record=repr(r)):
                    lay = layout_for(f.version, r.sys, r.msg, r.kind, r.sub)
                    self.assertIsNotNone(lay, "no layout")
                    want = SHORT_RECORDS.get((rel, r.sat, r.msg), len(lay.fields))
                    self.assertEqual(len(r.vals), want)
                    # every field on the 19-column grid is a number or blank
                    self.assertFalse([x for line in r.vals for x in line if isinstance(x, str)])
                    seen.add((f.version, r.kind, r.sys, r.msg))
        # the examples reach every system (3.00-3.02 print no Galileo record: spec_errata E-06)
        for v, s in (("2.10", "S"), ("2.11", "R"), ("3.03", "E"), ("3.02", "S"), ("3.03", "J"),
                     ("3.03", "C"), ("3.03", "I"), ("3.05", "R")):
            self.assertIn(("EPH", s), {(k, s2) for v2, k, s2, m in seen if v2 == v}, (v, s))
        for m in ("LNAV", "CNAV", "CNV2", "INAV", "FNAV", "FDMA", "L1OC", "L3OC", "D1", "D2", "CNV1",
                  "CNV3", "SBAS", "L1NV"):
            self.assertIn(m, {m2 for v2, k, s2, m2 in seen if v2 == "4.02" and k == "EPH"}, m)
        for k in ("STO", "EOP", "ION"):
            self.assertIn(k, {k2 for v2, k2, s2, m2 in seen if v2 == "4.02"})

    def test_short_record_is_the_erratum(self):
        f = parse_nav((SPEC / "4.01" / "a12_nav_gps.rnx").read_bytes())
        r = next(r for r in f.records if r.msg == "CNV2")
        self.assertEqual(len(r.vals), 9)
        self.assertEqual(len(layout_for("4.01", "G", "CNV2").fields), 10)

    def test_glonass_line5_from_305(self):
        self.assertEqual(len(layout_for("3.04", "R").fields), 4)
        self.assertEqual(len(layout_for("3.05", "R").fields), 5)
        self.assertEqual(len(layout_for("4.00", "R", "FDMA").fields), 5)

    def pairs(self):
        for p in self.files():
            rel = Path(p).parent.name + "/" + Path(p).name
            v = rel[:4]
            for t in {"2.10": ["2.11", "3.05"], "2.11": ["2.10", "3.05"], "3.00": ["3.01", "3.05", "2.11"],
                      "4.00": ["4.01", "4.02", "3.05"], "4.01": ["4.00", "4.02", "3.05"],
                      "4.02": ["4.00", "4.01", "3.05"]}.get(v, ["3.05", "3.04", "4.02", "2.11"]):
                if t != v:
                    yield rel, Path(p).read_bytes(), t

    def test_spec_examples_convert_clean(self):
        # every example to its neighbour versions: no field moves or changes (a field one side
        # lacks is not compared; refusals are the converter's business, not ours)
        for rel, data, t in self.pairs():
            if (rel, t) in KNOWN_FINDINGS:
                continue
            try:
                outs = convert(data, "x.rnx", t)
            except Exception:              # noqa: BLE001 - refusals are tested elsewhere
                continue
            with self.subTest(file=rel, target=t):
                self.assertEqual(compare_nav_fields(data, outs), [])

    def test_known_converter_findings(self):
        """Conversions this check rejects, from the spec text (KNOWN_FINDINGS): an unexpected
        success means the converter changed; move the pair back to the clean list."""
        bad = []
        for rel, data, t in self.pairs():
            if (rel, t) in KNOWN_FINDINGS:
                bad += compare_nav_fields(data, convert(data, "x.rnx", t))[:1]
        self.assertEqual(bad, [])


# ----------------------------------------------------------------------------------------
# transformations, on hand-written records (rinex211.txt Table A11, rinex305.txt Table A10)
# R01 of 2026-10-01 (a Thursday) as broadcast: brdc2740.26g (2.01) and BRDC00IGS (3.04)
# ----------------------------------------------------------------------------------------

def glo_v2(version="2.11", tk="0.000000000000D+00", gamma="0.909494701773D-12"):
    return L(hdr(f"{version:>9s}           G: GLONASS NAV DATA", "RINEX VERSION / TYPE"),
             hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE"),
             hdr("", "END OF HEADER"),
             f" 1 26 10  1  0 15  0.0 0.187545083463D-03{gamma:>19s}{tk:>19s}",
             "   -0.613975537109D+04-0.182036018372D+01 0.186264514923D-08 0.000000000000D+00",
             "    0.958122705078D+04-0.254422473908D+01 0.931322574616D-09 0.100000000000D+01",
             "    0.228222685547D+05 0.578757286072D+00-0.186264514923D-08 0.000000000000D+00")


def glo_v3(tk="3.456000000000E+05", gamma="9.094947017730E-13"):
    # the same values in E19.12 / 13 digits (BRDC00IGS itself differs from brdc2740.26g in the
    # 13th digit of two fields, decoder rounding: not used here)
    return L(hdr("     3.05           N: GNSS NAV DATA    R: GLONASS", "RINEX VERSION / TYPE"),
             hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE"),
             hdr("", "END OF HEADER"),
             f"R01 2026 10 01 00 15 00 1.875450834630E-04{gamma:>19s}{tk:>19s}",
             "    -6.139755371090E+03-1.820360183720E+00 1.862645149230E-09 0.000000000000E+00",
             "     9.581227050780E+03-2.544224739080E+00 9.313225746160E-10 1.000000000000E+00",
             "     2.282226855470E+04 5.787572860720E-01-1.862645149230E-09 0.000000000000E+00",
             "                         .999999999999E+09 1.500000000000E+01")


class Transformations(unittest.TestCase):
    def test_glonass_tk_day_to_week(self):
        self.assertEqual(compare_nav_fields(glo_v2(), glo_v3()), [])
        p, _ = nav_field_check(glo_v2(), glo_v3("0.000000000000E+00"))      # left in seconds of day
        self.assertEqual(kinds(p), [("field", "tk")])
        p, _ = nav_field_check(glo_v2(), glo_v3("5.184000000000E+05"))      # Saturday: no nd gives it
        self.assertEqual(kinds(p), [("field", "tk")])
        p, _ = nav_field_check(glo_v2(), glo_v3("2.592000000000E+05"))      # Wednesday: not nearest
        self.assertEqual(kinds(p), [("tk-day", "tk")])
        p, _ = nav_field_check(glo_v2(), glo_v3("3.456010000000E+05"))      # not congruent
        self.assertEqual(kinds(p), [("field", "tk")])

    def test_glonass_tk_week_to_day(self):
        self.assertEqual(compare_nav_fields(glo_v3(), glo_v2()), [])
        p, _ = nav_field_check(glo_v3(), glo_v2(tk="0.345600000000D+06"))
        self.assertEqual(kinds(p), [("field", "tk")])

    def test_glonass_200_gamma_sign(self):
        # 2.00 stored -GammaN (rinex210.txt l.170-178): 2.00 -> 3.05 negates it
        old = glo_v2("2.00", gamma="-.909494701773D-12")
        self.assertEqual(compare_nav_fields(old, glo_v3()), [])
        p, _ = nav_field_check(old, glo_v3(gamma="-9.094947017730E-13"))
        self.assertEqual(kinds(p), [("field", "GammaN")])
        # 2.01 is the current convention: no sign change
        self.assertEqual(compare_nav_fields(glo_v2("2.01"), glo_v3()), [])

    def test_sbas_210_frame_time(self):
        def geo(version, t):
            return L(hdr(f"{version:>9s}           H: GEO NAV MSG DATA", "RINEX VERSION / TYPE"),
                     hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE"),
                     hdr("", "END OF HEADER"),
                     f"20 26 10  1  0  1  4.0-0.100582838059D-06 0.636646291241D-11{t:>19s}",
                     "    0.248283239200D+05-0.359375000000D-03-0.137500000000D-06 0.000000000000D+00",
                     "   -0.340892087200D+05-0.148062500000D-02-0.500000000000D-07 0.400000000000D+01",
                     # (field 4: spare in 2.10, the IODN from 2.11: left blank on both sides, as
                     # a spare fills no IODN and an IODN no spare, review round 33)
                     "   -0.165056000000D+02 0.836000000000D-03 0.625000000000D-07")
        # Thursday 00:01:04 GPS: day 4, 2.10 frame time 42 s -> 2.11 345642 s of week
        self.assertEqual(compare_nav_fields(geo("2.10", "0.420000000000D+02"), geo("2.11", "0.345642000000D+06")), [])
        p, _ = nav_field_check(geo("2.10", "0.420000000000D+02"), geo("2.11", "0.420000000000D+02"))
        self.assertEqual(kinds(p), [("field", "Ttm")])
        self.assertEqual(compare_nav_fields(geo("2.11", "0.345642000000D+06"), geo("2.10", "0.420000000000D+02")), [])
        # IODN is spare in 2.10 (rinex210.txt Table A16): not compared
        self.assertIsNone(named(parse_nav(geo("2.10", "0.42D+02")).records[0], "2.10").get("IODN"))

    def test_unknown_transmission_time_and_precision(self):
        def gps(version, ttm, af0):
            return L(hdr(f"{version:>9s}           N: GNSS NAV DATA    G: GPS", "RINEX VERSION / TYPE"),
                     hdr("TEST                TEST                20261002 000000 UTC", "PGM / RUN BY / DATE"),
                     hdr("", "END OF HEADER"),
                     f"G06 1999 09 02 17 51 44{af0:>19s}-.165982783074D-10  .000000000000D+00",
                     "      .910000000000D+02  .934062500000D+02  .116040547840D-08  .162092304801D+00",
                     "      .484101474285D-05  .626740418375D-02  .652112066746D-05  .515365489006D+04",
                     "      .409904000000D+06 -.242143869400D-07  .329237003460D+00 -.596046447754D-07",
                     "      .111541663136D+01  .326593750000D+03  .206958726335D+01 -.638312302555D-08",
                     "      .307155651409D-09  .000000000000D+00  .102500000000D+04  .000000000000D+00",
                     "      .000000000000D+00  .000000000000D+00  .000000000000D+00  .910000000000D+02",
                     f"{ttm:>25s}  .400000000000D+01")
        # 3.04 '0.9999E9' and 3.05 '.999999999999E+09' both mean unknown (rinex304.txt p.78, rinex305.txt p.70)
        self.assertEqual(compare_nav_fields(gps("3.04", "0.9999E9", "-.839701388031D-03"),
                                            gps("3.05", ".999999999999E+09", "-.839701388031D-03")), [])
        # 13 significant digits rounded to D19.12's 12: allowed; one unit more: a change
        self.assertEqual(compare_nav_fields(gps("3.04", ".4068D+06", "-8.3970138803150E-04"),
                                            gps("3.05", ".4068D+06", "-.839701388032D-03")), [])
        p, _ = nav_field_check(gps("3.04", ".4068D+06", "-8.3970138803150E-04"),
                               gps("3.05", ".4068D+06", "-.839701388033D-03"))
        self.assertEqual(kinds(p), [("field", "af0")])

    def test_galileo_message_type_follows_data_sources(self):
        v3 = (SPEC / "3.05" / "a9_nav_galileo.rnx").read_bytes()
        outs = convert(v3, "x.rnx", "4.02")
        self.assertEqual(compare_nav_fields(v3, outs), [])
        f = parse_nav(outs[0])
        r = next(r for r in f.records if r.kind == "EPH")
        swapped = "FNAV" if r.msg == "INAV" else "INAV"
        bad = outs[0].replace(f"> EPH {r.sat} {r.msg}".encode(), f"> EPH {r.sat} {swapped}".encode(), 1)
        self.assertIn("msgtype", [p["kind"] for p in nav_field_check(v3, bad)[0]])


# ----------------------------------------------------------------------------------------
# (ii) mutations of real converter output, (iii) clean conversions
# ----------------------------------------------------------------------------------------

def swap_fields(out, version, rec, f1, f2):
    """The output payload with fields f1 and f2 of record rec exchanged in place."""
    lines = out.decode("latin-1").split("\n")
    (i1, a1, b1), (i2, a2, b2) = field_columns(version, rec, f1), field_columns(version, rec, f2)
    s1, s2 = lines[i1].ljust(b1)[a1:b1], lines[i2].ljust(b2)[a2:b2]
    lines[i1] = lines[i1].ljust(b1)[:a1] + s2 + lines[i1].ljust(b1)[b1:]
    lines[i2] = lines[i2].ljust(b2)[:a2] + s1 + lines[i2].ljust(b2)[b2:]
    return "\n".join(lines).encode("latin-1")


# (corpus file, target, system, message type of the output record or '', field pairs)
MUTATIONS = [
    ("v2.11/alb42740.26n.gz", "3.05", "G", "", [("Cuc", "Cus"), ("IODE", "IODC"), ("Crs", "Crc"),
                                                 ("Toe", "Ttm"), ("SVhealth", "L2Codes")]),
    ("v2.11/alb42740.26g.gz", "2.10", "R", "", [("mTauN", "GammaN"), ("X", "Y"), ("Xdot", "Zdot"),
                                                 ("Health", "FreqNum")]),
    ("v2.11/bill2740.26h.gz", "3.04", "S", "", [("aGf0", "aGf1"), ("Xacc", "Yacc"), ("URA", "IODN")]),
    ("v3.04/ADIS00ETH_R_20262740000_01D_CN.rnx.gz", "4.02", "C", "D1", [("TGD1", "TGD2"),
                                                                         ("AODE", "AODC"), ("Cic", "Cis")]),
    ("v3.04/ABMF00GLP_R_20262740000_01D_EN.rnx.gz", "3.05", "E", "", [("BGDE5aE1", "BGDE5bE1"),
                                                                      ("IODnav", "SISA"), ("Cuc", "Cus")]),
    ("v3.04/CIBG00IDN_R_20262740000_01D_IN.rnx.gz", "4.01", "I", "LNAV", [("Cuc", "Cus"), ("URA", "TGD")]),
    ("v3.05/KLSQ00GRL_R_20262740000_01D_RN.rnx.gz", "4.00", "R", "FDMA", [("mTauN", "GammaN"),
                                                                          ("X", "Z")]),
    ("v4.02/ES1300DEU_R_20262740000_01D_MN.rnx.gz", "4.01", "G", "CNAV", [("ISC_L2C", "ISC_L5I5"),
                                                                          ("URAI_NED0", "URAI_NED1"),
                                                                          ("Adot", "Crs")]),
    ("v4.02/ES1300DEU_R_20262740000_01D_MN.rnx.gz", "4.00", "C", "CNV2", [("TGD_B1Cp", "TGD_B2ap"),
                                                                          ("ISC_B2ad", "TGD_B1Cp"),
                                                                          ("Cuc", "Cus")]),
    ("v4.02/ES1300DEU_R_20262740000_01D_MN.rnx.gz", "3.05", "E", "", [("BGDE5aE1", "BGDE5bE1"),
                                                                      ("Toe", "Ttm")]),
]


@unittest.skipUnless(CORPUS.is_dir(), "data/corpus (gitignored) is not here")
class CorpusMutations(unittest.TestCase):
    cache = {}

    def converted(self, rel, target):
        if (rel, target) not in self.cache:
            raw = (CORPUS / rel).read_bytes()
            self.cache[(rel, target)] = (unwrap(raw)[0], convert(raw, Path(rel).name, target))
        return self.cache[(rel, target)]

    def test_swapped_fields_are_reported(self):
        for rel, target, sys_, msg, swaps in MUTATIONS:
            plain, outs = self.converted(rel, target)
            out = next(o for o in outs if any(r.sys == sys_ and r.msg == msg for r in parse_nav(o).records))
            f = parse_nav(out)
            before = {(p["sat"], p["toc"], p["field"]) for p in nav_field_check(plain, out)[0]}
            for f1, f2 in swaps:
                with self.subTest(file=rel, target=target, swap=(f1, f2)):
                    rec = next(r for r in f.records if r.sys == sys_ and r.msg == msg and r.kind == "EPH"
                               and named(r, f.version).get(f1) is not None
                               and named(r, f.version).get(f2) is not None
                               and named(r, f.version)[f1] != named(r, f.version)[f2])
                    bad = swap_fields(out, f.version, rec, f1, f2)
                    probs = nav_field_check(plain, bad)[0]
                    new = {p["field"] for p in probs if (p["sat"], p["toc"], p["field"]) not in before}
                    self.assertEqual(new & {f1, f2}, {f1, f2}, probs[:4])

    def test_moved_key_is_reported(self):
        plain, outs = self.converted("v2.11/alb42740.26n.gz", "3.05")
        out = outs[0]
        f = parse_nav(out)
        r = f.records[0]
        lines = out.decode("latin-1").split("\n")
        # satellite renumbered (to one with no record at this time) / time of clock moved 2 h
        prns = {x.prn for x in f.records if x.toc == r.toc}
        new = next(n for n in range(1, 33) if n not in prns)
        for edit in (lambda l: l[0] + "%02d" % new + l[3:], lambda l: l[:15] + "%02d" % ((r.toc[3] + 2) % 24) + l[17:]):
            with self.subTest(edit=edit):
                bad = lines[:]
                bad[r.line] = edit(bad[r.line])
                probs = nav_field_check(plain, "\n".join(bad).encode("latin-1"))[0]
                self.assertIn("unmatched", [p["kind"] for p in probs], probs[:3])

    def test_changed_galileo_data_source_is_reported(self):
        plain, outs = self.converted("v3.04/ABMF00GLP_R_20262740000_01D_EN.rnx.gz", "4.02")
        out = outs[0]
        f = parse_nav(out)
        rec = next(r for r in f.records if r.msg == "FNAV")
        i, a, b = field_columns(f.version, rec, "DataSources")
        lines = out.decode("latin-1").split("\n")
        lines[i] = lines[i][:a] + "%19s" % "5.170000000000E+02" + lines[i][b:]
        probs = nav_field_check(plain, "\n".join(lines).encode("latin-1"))[0]
        # FNAV data sources (bit 1) rewritten as I/NAV (bits 0, 2, 8): matched on satellite and
        # time of clock, the changed field is named
        self.assertIn(("field", "DataSources"), kinds(probs))

    def test_clean_conversions_report_nothing(self):
        for rel, targets in (("v2.11/alb42740.26n.gz", ("2.10", "3.00", "3.05", "4.02")),
                             ("v2.11/alb42740.26g.gz", ("2.10",)),
                             ("v2.11/bill2740.26h.gz", ("3.00", "3.05", "4.02")),
                             ("v3.04/ABMF00GLP_R_20262740000_01D_EN.rnx.gz", ("3.01", "3.05", "4.00", "4.02")),
                             ("v3.04/ADIS00ETH_R_20262740000_01D_CN.rnx.gz", ("3.02", "3.05", "4.02")),
                             ("v3.05/KLSQ00GRL_R_20262740000_01D_RN.rnx.gz", ("3.00", "3.04", "4.01")),
                             ("v4.02/ES1300DEU_R_20262740000_01D_MN.rnx.gz", ("3.05", "4.00", "4.01"))):
            for t in targets:
                with self.subTest(file=rel, target=t):
                    plain, outs = self.converted(rel, t)
                    self.assertEqual(compare_nav_fields(plain, outs)[:5], [])


class ConverterFindings(unittest.TestCase):
    """Converter behaviour this check rejects, from the spec text (corpus run of 2026-11-02).
    To be fixed in the converter, not here: an unexpected success means it was."""

    def test_glonass_200_gamma_sign(self):
        # rinex210.txt l.170-178: a 2.00 GLONASS file stores -GammaN (no corpus file has one)
        old = glo_v2("2.00", gamma="-.909494701773D-12")
        self.assertEqual(compare_nav_fields(old, convert(old, "x.00g", "2.11")), [])

    @unittest.skipUnless(CORPUS.is_dir(), "data/corpus (gitignored) is not here")
    def test_glonass_v2_to_v3_tk_becomes_seconds_of_week(self):
        # rinex211.txt l.1718-1719 (sec of day) vs rinex305.txt p.74 Table A10 (tk+nd*86400)
        raw = (CORPUS / "v2.11" / "alb42740.26g.gz").read_bytes()
        self.assertEqual(compare_nav_fields(unwrap(raw)[0], convert(raw, "alb42740.26g.gz", "3.05"))[:3], [])

    @unittest.skipUnless(CORPUS.is_dir(), "data/corpus (gitignored) is not here")
    def test_glonass_v3_to_v2_tk_becomes_seconds_of_day(self):
        raw = (CORPUS / "v3.05" / "KLSQ00GRL_R_20262740000_01D_RN.rnx.gz").read_bytes()
        self.assertEqual(compare_nav_fields(unwrap(raw)[0], convert(raw, "KLSQ.rnx.gz", "2.11"))[:3], [])

    @unittest.skipUnless(CORPUS.is_dir(), "data/corpus (gitignored) is not here")
    def test_sbas_v3_to_210_ttm_becomes_seconds_of_day(self):
        # rinex211.txt l.909-915: 2.10's field is the message frame time in seconds of the day
        raw = (CORPUS / "v3.04" / "ABMF00GLP_R_20262740000_01D_SN.rnx.gz").read_bytes()
        self.assertEqual(compare_nav_fields(unwrap(raw)[0], convert(raw, "ABMF.rnx.gz", "2.10"))[:3], [])

    @unittest.skipUnless(CORPUS.is_dir(), "data/corpus (gitignored) is not here")
    def test_qzss_ion_japan_area_kept_as_region_code(self):
        # 4.02 subtype JAPN -> 4.00/4.01 'Region code ... 1 (QZSS only - Japan area
        # coefficients)', not blank (= wide area): rinex_4.01.txt p.108 Table A32
        raw = (CORPUS / "v4.02" / "BRD400DLR_S_20262740000_01D_MN.rnx.gz").read_bytes()
        self.assertEqual(compare_nav_fields(unwrap(raw)[0], convert(raw, "BRD4.rnx.gz", "4.01"))[:3], [])


if __name__ == "__main__":
    unittest.main()
