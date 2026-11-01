"""Navigation fixtures: the RINEX 2.11 spec example (rinex211.txt Table A8, ~1619) as
input, expected outputs written by hand (PLAN §1.5b/d)."""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore.errors import NotRepresentableError


def L(*ls):
    return ("\n".join(ls) + "\n").encode("latin-1")


def hdr(content, label):
    return content.ljust(60) + label


# rinex211.txt Table A8, first record (verbatim from the spec text)
SPEC_211 = L(
    "     2.11           N: GPS NAV DATA                         RINEX VERSION / TYPE",
    "XXRINEXN V2.10      AIUB                 3-SEP-99 15:22     PGM / RUN BY / DATE",
    "EXAMPLE OF VERSION 2.11 FORMAT                              COMMENT",
    "     .1676D-07   .2235D-07  -.1192D-06  -.1192D-06          ION ALPHA",
    "     .1208D+06   .1310D+06  -.1310D+06  -.1966D+06          ION BETA",
    "     .133179128170D-06  .107469588780D-12   552960     1025 DELTA-UTC: A0,A1,T,W",
    "    13                                                      LEAP SECONDS",
    "                                                            END OF HEADER",
    " 6 99  9  2 17 51 44.0 -.839701388031D-03 -.165982783074D-10  .000000000000D+00",
    "     .910000000000D+02  .934062500000D+02  .116040547840D-08  .162092304801D+00",
    "     .484101474285D-05  .626740418375D-02  .652112066746D-05  .515365489006D+04",
    "     .409904000000D+06 -.242143869400D-07  .329237003460D+00 -.596046447754D-07",
    "     .111541663136D+01  .326593750000D+03  .206958726335D+01 -.638312302555D-08",
    "     .307155651409D-09  .000000000000D+00  .102500000000D+04  .000000000000D+00",
    "     .000000000000D+00  .000000000000D+00  .000000000000D+00  .910000000000D+02",
    "     .406800000000D+06  .000000000000D+00",
)

# Expected RINEX 3.05 (hand-written):
#  - ION ALPHA/BETA -> IONOSPHERIC CORR GPSA/GPSB, same D12.4 precision (rinex305.txt Table A5)
#  - DELTA-UTC (D19.12) -> TIME SYSTEM CORR GPUT a0 D17.10, a1 D16.9: rounded, a reported loss
#    (the spec's own 3.05 example A7 shows the same rounding: .1331791282D-06, .107469589D-12)
#  - UTC identifier unknown in RINEX 2 -> 0 ("0 if unknown", Table A5)
#  - record: 'G06', 4-digit year, I2.2 fields, values unchanged, 4X continuation
SPEC_305 = L(
    hdr("     3.05           N: GNSS NAV DATA    G: GPS", "RINEX VERSION / TYPE"),
    hdr("XXRINEXN V2.10      AIUB                 3-SEP-99 15:22", "PGM / RUN BY / DATE"),
    hdr("EXAMPLE OF VERSION 2.11 FORMAT", "COMMENT"),
    hdr("GPSA   0.1676D-07  0.2235D-07 -0.1192D-06 -0.1192D-06", "IONOSPHERIC CORR"),
    hdr("GPSB   0.1208D+06  0.1310D+06 -0.1310D+06 -0.1966D+06", "IONOSPHERIC CORR"),
    hdr("GPUT  0.1331791282D-06 0.107469589D-12 552960 1025        0", "TIME SYSTEM CORR"),
    hdr("    13", "LEAP SECONDS"),
    hdr("", "END OF HEADER"),
    "G06 1999 09 02 17 51 44 -.839701388031D-03 -.165982783074D-10  .000000000000D+00",
    "      .910000000000D+02  .934062500000D+02  .116040547840D-08  .162092304801D+00",
    "      .484101474285D-05  .626740418375D-02  .652112066746D-05  .515365489006D+04",
    "      .409904000000D+06 -.242143869400D-07  .329237003460D+00 -.596046447754D-07",
    "      .111541663136D+01  .326593750000D+03  .206958726335D+01 -.638312302555D-08",
    "      .307155651409D-09  .000000000000D+00  .102500000000D+04  .000000000000D+00",
    "      .000000000000D+00  .000000000000D+00  .000000000000D+00  .910000000000D+02",
    "      .406800000000D+06  .000000000000D+00",
)

GLO_304 = L(
    hdr("     3.04           N: GNSS NAV DATA    R: GLONASS", "RINEX VERSION / TYPE"),
    hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
    hdr("    18", "LEAP SECONDS"),
    hdr("", "END OF HEADER"),
    "R01 2026 10 01 00 15 00 1.875450834632D-04 9.094947017729D-13 1.800000000000D+02",
    "    -1.214091503906D+04 1.637722015381D+00 9.313225746155D-10 0.000000000000D+00",
    "    -1.024543798828D+04-2.405881881714D+00 0.000000000000D+00 1.000000000000D+00",
    "     2.012014794922D+04-1.093914031982D-01-2.793967723846D-09 0.000000000000D+00",
)
# 3.05 adds BROADCAST ORBIT - 4 (rinex305.txt Table A10, p.73-74): unknown values are
# status flags BNK, group delay .999999999999E+09, URAI 1.500000000000E+01, health BNK.
GLO_305_LINE5 = "                         .999999999999D+09 1.500000000000D+01"


class Nav(unittest.TestCase):
    def test_spec_211_to_305(self):
        outs = convert_data(SPEC_211, "brdc2450.99n", Options("3.05", compression="none"))
        self.assertEqual(outs[0].data.decode("latin-1").split("\n"),
                         SPEC_305.decode("latin-1").split("\n"))
        rep = outs[0].report.to_dict()
        self.assertEqual(rep["losses"]["nav-correction-precision:TIME SYSTEM CORR"]["count"], 2)

    def test_305_back_to_211(self):
        outs = convert_data(SPEC_305, "X.rnx", Options("2.11", compression="none"))
        txt = outs[0].data.decode("latin-1")
        # values are unchanged; ION/DELTA-UTC come back (DELTA-UTC with the rounded mantissas)
        self.assertIn(" 6 99  9  2 17 51 44.0 -.839701388031D-03", txt)
        # 3X, then D19.12 right-justified: one more blank before the leading zero
        self.assertIn(hdr("    0.133179128200D-06 0.107469589000D-12   552960     1025",
                          "DELTA-UTC: A0,A1,T,W"), txt)
        self.assertIn(hdr("    0.1676D-07  0.2235D-07 -0.1192D-06 -0.1192D-06", "ION ALPHA"), txt)

    def test_v4_exponent_letter_and_message_type(self):
        out = convert_data(SPEC_305, "X.rnx", Options("4.02", compression="none"))[0].data.decode()
        self.assertIn("> EPH G06 LNAV\nG06 1999 09 02 17 51 44 -.839701388031E-03", out)
        self.assertNotIn("D+", out.split("END OF HEADER")[1])
        self.assertIn("> ION G   LNAV", out)
        self.assertIn("> STO G   LNAV", out)
        self.assertNotIn("IONOSPHERIC CORR", out)
        back = convert_data(out.encode(), "X.rnx", Options("3.05", compression="none"))[0].data.decode()
        self.assertIn("G06 1999 09 02 17 51 44 -.839701388031D-03", back)
        self.assertIn("IONOSPHERIC CORR", back)
        self.assertIn("TIME SYSTEM CORR", back)

    def test_glonass_fifth_line(self):
        out = convert_data(GLO_304, "X.rnx", Options("3.05", compression="none"))
        txt = out[0].data.decode()
        self.assertIn("\n" + GLO_305_LINE5 + "\n", txt)
        self.assertTrue(any(a["category"] == "glonass-nav-line5" for a in out[0].report.to_dict()["assumptions"]))
        back = convert_data(out[0].data, "X.rnx", Options("3.04", compression="none"))
        self.assertEqual(back[0].data, GLO_304)
        # line 5 held only the spec's "unknown" values: dropping it loses nothing
        self.assertNotIn("glonass-nav-line5-dropped", back[0].report.losses)
        real = out[0].data.replace(b".999999999999D+09", b".200000000000D-08")   # same width
        back = convert_data(real, "X.rnx", Options("3.04", compression="none"))
        self.assertIn("glonass-nav-line5-dropped", back[0].report.losses)

    def test_split_to_v2_and_not_representable(self):
        bds = L(hdr("     3.04           N: GNSS NAV DATA    C: BEIDOU", "RINEX VERSION / TYPE"),
                hdr("", "END OF HEADER"),
                "C06 2026 09 30 22 00 00 3.115237923339D-04 1.862510146111D-12 0.000000000000D+00",
                # BDS record: 7 BROADCAST ORBIT lines (rinex305.txt Table A14)
                *(["     1.000000000000D+00 1.000000000000D+00 1.000000000000D+00 1.000000000000D+00"] * 6),
                "     3.394380000000D+05 1.000000000000D+00")
        with self.assertRaises(NotRepresentableError):
            convert_data(bds, "X.rnx", Options("2.11", compression="none"))

    def test_galileo_message_type_from_bitmask(self):
        rec = ["E01 2026 10 01 00 00 00-6.651098374277D-06-5.115907697473D-13 0.000000000000D+00",
               "     6.400000000000D+01 3.343750000000D+00 2.339383158984D-09-1.028423514356D+00",
               "     2.309679985046D-07 9.007973130792D-05 9.784474968910D-06 5.440611940384D+03",
               "     3.456000000000D+05-1.490116119385D-07 6.681256221140D-01-1.676380634308D-08",
               "     9.975879822523D-01 1.494687500000D+02 2.157772554722D+00-5.180215776780D-09",
               None,
               "     3.120000000000D+00 0.000000000000D+00-6.286427378654D-09-7.683411240578D-09",
               "     3.462640000000D+05"]
        for bits, want in ((517, "INAV"), (258, "FNAV"), (513, "INAV"), (519, "INAV")):
            r = list(rec)
            # BROADCAST ORBIT 5: IDOT, data sources, GAL week, spare (rinex305.txt Table A8)
            r[5] = ("    -3.410856361573D-10" + f"{bits / 1000:.12f}D+03".rjust(19)
                    + " 2.385000000000D+03 0.000000000000D+00")
            src = L(hdr("     3.05           N: GNSS NAV DATA    E: GALILEO", "RINEX VERSION / TYPE"),
                    hdr("", "END OF HEADER"), *r)
            out = convert_data(src, "X.rnx", Options("4.02", compression="none"))[0].data.decode()
            self.assertIn(f"> EPH E01 {want}", out, bits)
            # the bitmask itself is carried verbatim (PLAN §3.5)
            self.assertIn(f"{bits / 1000:.12f}E+03", out)


class MixedToV2(unittest.TestCase):
    def test_mixed_with_corrections_split_to_211(self):
        """A merged mixed nav file (GPS + GLONASS + SBAS records, GPUT/GLUT/SBUT corrections)
        splits into n/g/h files; header records that fit nowhere are counted once."""
        mixed = L(
            hdr("     3.04           N: GNSS NAV DATA    M: Mixed", "RINEX VERSION / TYPE"),
            hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
            hdr("GPSA   0.1676D-07  0.2235D-07 -0.1192D-06 -0.1192D-06", "IONOSPHERIC CORR"),
            hdr("GPSB   0.1208D+06  0.1310D+06 -0.1310D+06 -0.1966D+06", "IONOSPHERIC CORR"),
            hdr("GPUT  0.1331791282D-06 0.107469589D-12 552960 1025   G12  2", "TIME SYSTEM CORR"),
            hdr("GLUT  0.1071020961D-07 0.000000000D+00      0    0   R10  0", "TIME SYSTEM CORR"),
            hdr("SBUT  0.1000000000D-08 0.000000000D+00 345600 2438   S27  0", "TIME SYSTEM CORR"),
            hdr("GAUT  0.3725290298D-08 0.532907052D-14 345600 2438   E10  5", "TIME SYSTEM CORR"),
            hdr("    18", "LEAP SECONDS"),
            hdr("", "END OF HEADER"),
            *[l.replace("G06 1999", "G06 2026") for l in SPEC_305.decode().split("\n")[8:16]],
            *[l.replace("2026 10 01 00 15 00", "2026 10 01 00 15 00") for l in GLO_304.decode().split("\n")[4:8]],
            "S27 2026 10 01 00 00 00 0.000000000000D+00 0.000000000000D+00 0.345600000000D+06",
            "     0.000000000000D+00 0.000000000000D+00 0.000000000000D+00 0.000000000000D+00",
            "     0.000000000000D+00 0.000000000000D+00 0.000000000000D+00 0.000000000000D+00",
            "     0.000000000000D+00 0.000000000000D+00 0.000000000000D+00 0.000000000000D+00")
        for tv in ("2.10", "2.11"):
            outs = convert_data(mixed, "MIX.rnx", Options(tv, compression="none"))
            self.assertEqual(sorted(o.model.ftype for o in outs), ["G", "H", "N"])
            rep = outs[0].report.to_dict()
            self.assertEqual(rep["outcome"], "converted")
            # GAUT has no RINEX 2 home: one loss, not one per output file
            self.assertEqual(rep["losses"]["nav-correction-not-representable:STO:GAUT"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
