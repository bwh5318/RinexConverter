"""Hand-written observation fixtures (PLAN §1.5b).

The inputs and the expected outputs below are written by hand from the specs
(rinex211.txt Tables A1/A2, rinex305.txt Tables A2/A3) and the documented
conversion defaults (rinexconv/codemap.py docstring, PLAN §3.3/§3.5). They are
not produced by our writer. Fields are spelled out one by one so their columns
can be checked against the F14.3 + LLI + SSI layout.
"""

import unittest

from rinexconv.engine import Options, convert_data, load_bytes
from rinexcore.errors import MissingInformationError, NotRepresentableError


def F(value, lli=" ", ssi=" "):
    """One observation field: F14.3 text as written by hand, then LLI and SSI."""
    assert len(value) == 14, value
    return value + lli + ssi


B = " " * 16


def lines(*ls, width=80):
    """RINEX 2 lines are at most 80 columns; RINEX 3/4 data lines are unwrapped (width=None)."""
    for x in ls:
        if width:
            assert len(x) <= width, (len(x), x)
        else:
            assert x[0] == ">" or x[60:80].strip() or len(x) <= 80 or x[0].isalpha(), x
    return ("\n".join(ls) + "\n").encode("latin-1")


def hdr(content, label):
    assert len(content) <= 60
    return content.ljust(60) + label


# --- input: RINEX 2.11, GPS + GLONASS, 7 types (two data lines per satellite) ---------
G05 = [F("  22000000.105", " ", "7"), F("  22000001.205", " ", "7"), F("  22000002.305", " ", "7"),
       F(" 115000000.405", "1", "7"), F("  89000000.505", " ", "6"), F("        45.000"),
       F("        38.500")]
G12 = [F("  21000000.112"), B, F("  21000002.312"), F(" 110000000.412"), F("         0.000"),
       F("        44.000"), B]
R07 = [F("  19000000.107"), F("  19000001.207"), F("  19000002.307"), F(" 101000000.407"),
       F("  78000000.507"), F("        40.000"), F("        35.000")]
G05b = [F("  22000100.105"), F("  22000101.205"), F("  22000102.305"), F(" 115000500.405"),
        F("  89000400.505"), F("        45.250"), F("        38.750")]
R07b = [F("  19000100.107"), F("  19000101.207"), F("  19000102.307"), F(" 101000500.407"),
        F("  78000400.507"), F("        40.250"), F("        35.250")]


def v2data(fields):
    return ["".join(fields[0:5]).rstrip(), "".join(fields[5:7]).rstrip()]


V211 = lines(
    hdr("     2.11           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
    hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
    hdr("TEST", "MARKER NAME"),
    hdr("     1     1", "WAVELENGTH FACT L1/2"),
    hdr("     7    C1    P1    P2    L1    L2    S1    S2", "# / TYPES OF OBSERV"),
    hdr("    30.000", "INTERVAL"),
    hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
    hdr("", "END OF HEADER"),
    # 41 columns of epoch + satellites, blanks to column 68, then the clock F12.9 (cols 69-80)
    " 26 10  1  0  0  0.0000000  0  3G05G12R07" + " " * 27 + " 0.000000123",
    *v2data(G05), *v2data(G12), *v2data(R07),
    " 26 10  1  0  0 15.0000000  4  1",
    hdr("A COMMENT INSIDE THE DATA", "COMMENT"),
    " 26 10  1  0  0 30.0000000  0  2G05R07",
    *v2data(G05b), *v2data(R07b),
)

# --- expected RINEX 3.05 (hand-written) ---------------------------------------------------
# codes: G C1->C1C P1->C1W P2->C2W L1->L1C L2->L2W S1->S1C S2->S2W
#        R C1->C1C P1->C1P P2->C2P L1->L1C L2->L2P S1->S1C S2->S2P
# 0.000 is "missing" (rinex211.txt ~1288) and is written blank.
# SYS / PHASE SHIFT: alignment unknown in RINEX 2 -> the fully blank form per system
# (rinex305.txt §5.2.12); GLONASS SLOT / FRQ # from the --glo-fcn table; GLONASS
# COD/PHS/BIS unknown -> all fields blank (rinex305.txt Table A2 p.57).
G12_3 = G12[:4] + [B] + G12[5:]
V305 = lines(
    hdr("     3.05           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
    hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
    hdr("TEST", "MARKER NAME"),
    hdr("G    7 C1C C1W C2W L1C L2W S1C S2W", "SYS / # / OBS TYPES"),
    hdr("R    7 C1C C1P C2P L1C L2P S1C S2P", "SYS / # / OBS TYPES"),
    hdr("    30.000", "INTERVAL"),
    hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
    hdr("G", "SYS / PHASE SHIFT"),
    hdr("R", "SYS / PHASE SHIFT"),
    hdr("  1 R07  5", "GLONASS SLOT / FRQ #"),
    hdr("", "GLONASS COD/PHS/BIS"),
    hdr("", "END OF HEADER"),
    "> 2026 10 01 00 00  0.0000000  0  3        .000000123000",   # F15.12 without the leading zero (RNX2CRX style)
    ("G05" + "".join(G05)).rstrip(),
    ("G12" + "".join(G12_3)).rstrip(),
    ("R07" + "".join(R07)).rstrip(),
    "> 2026 10 01 00 00 15.0000000  4  1",
    hdr("A COMMENT INSIDE THE DATA", "COMMENT"),
    "> 2026 10 01 00 00 30.0000000  0  2",
    ("G05" + "".join(G05b)).rstrip(),
    ("R07" + "".join(R07b)).rstrip(),
    width=None)

# --- and back to RINEX 2.11 (hand-written): the default WAVELENGTH FACT L1/2 (mandatory in
# 2.10, optional in 2.11) is written; satellite numbers are A1,I2 (rinex211.txt Table A2).
V211_BACK = lines(
    hdr("     2.11           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
    hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
    hdr("TEST", "MARKER NAME"),
    hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ"),
    hdr("     1     1", "WAVELENGTH FACT L1/2"),
    hdr("     7    C1    P1    P2    L1    L2    S1    S2", "# / TYPES OF OBSERV"),
    hdr("    30.000", "INTERVAL"),
    hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
    hdr("", "END OF HEADER"),
    " 26 10  1  0  0  0.0000000  0  3G 5G12R 7" + " " * 27 + "  .000000123",
    *v2data(G05), *v2data(G12_3), *v2data(R07),
    " 26 10  1  0  0 15.0000000  4  1",
    hdr("A COMMENT INSIDE THE DATA", "COMMENT"),
    " 26 10  1  0  0 30.0000000  0  2G 5R 7",
    *v2data(G05b), *v2data(R07b),
)


def table_file(tmpdir, text):
    import os
    p = os.path.join(tmpdir, "fcn.txt")
    with open(p, "wb") as fh:
        fh.write(text.encode("ascii"))
    return p


class V2toV3(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.fcn = table_file(self.tmp, "R07 5\n")

    def test_v211_to_v305_hand_written(self):
        outs = convert_data(V211, "test0010.26o", Options("3.05", glo_fcn=self.fcn, compression="none"))
        got = outs[0].data.decode("latin-1").split("\n")
        want = V305.decode("latin-1").split("\n")
        self.assertEqual(got, want)
        rep = outs[0].report.to_dict()
        self.assertEqual(rep["outcome"], "converted")
        self.assertEqual(rep["losses"], {})
        cats = {(a["category"], a["detail"]) for a in rep["assumptions"]}
        self.assertIn(("obs-code-attribute:G", "L2->L2W"), cats)
        self.assertIn(("obs-code-attribute:R", "P1->C1P"), cats)
        self.assertIn(("glonass-fcn", "R07=5"), cats)
        self.assertIn(("phase-alignment", "G:unknown"), cats)
        self.assertIn(("glonass-cod-phs-bis", "unknown"), cats)

    def test_back_to_v211_hand_written(self):
        name = "TEST00XXX_R_20262740000_01D_30S_MO.rnx"
        # the 3.05 input has no APPROX POSITION XYZ (optional for moving platforms), which
        # RINEX 2 makes mandatory: clause 8, refuse and name it ...
        with self.assertRaises(MissingInformationError) as cm:
            convert_data(V305, name, Options("2.11", compression="none"))
        self.assertIn("APPROX POSITION XYZ", str(cm.exception))
        self.assertEqual(cm.exception.outcome, "refused-missing-information")
        # ... unless the user gives the value
        outs = convert_data(V305, name, Options("2.11", compression="none",
                                                approx_position=(4027894.006, 307045.6, 4919474.91)))
        got = outs[0].data.decode("latin-1").split("\n")
        want = V211_BACK.decode("latin-1").split("\n")
        self.assertEqual(got, want)
        rep = outs[0].report.to_dict()
        self.assertEqual(set(rep["losses"]), {"header-record-not-representable:GLONASS SLOT / FRQ #"})
        self.assertIn("approx-position", {a["category"] for a in rep["assumptions"]})

    def test_glonass_channels_missing_is_refused(self):
        with self.assertRaises(MissingInformationError) as cm:
            convert_data(V211, "test0010.26o", Options("3.05", compression="none"))
        self.assertIn("R07", str(cm.exception))
        self.assertEqual(cm.exception.outcome, "refused-missing-information")

    def test_drop_unresolvable_removes_glonass(self):
        outs = convert_data(V211, "test0010.26o", Options("3.05", compression="none",
                                                           drop_unresolvable=True))
        rep = outs[0].report.to_dict()
        self.assertEqual(rep["outcome"], "converted-with-removal")
        self.assertIn("system-removed-unresolvable:R", rep["losses"])
        self.assertNotIn(b"R07", outs[0].data.split(b"END OF HEADER")[1])

    def test_glonass_channels_not_needed_below_302(self):
        outs = convert_data(V211, "test0010.26o", Options("3.01", compression="none"))
        self.assertNotIn(b"GLONASS SLOT", outs[0].data)
        self.assertIn(b"SYS / PHASE SHIFTS", outs[0].data)   # the 3.01 spelling (rinex301.txt p.32)

    def test_unknown_alignment_to_v4_refused(self):
        with self.assertRaises(MissingInformationError) as cm:
            convert_data(V211, "test0010.26o", Options("4.02", glo_fcn=self.fcn, compression="none"))
        self.assertIn("phase", str(cm.exception))
        outs = convert_data(V211, "test0010.26o", Options("4.02", glo_fcn=self.fcn, compression="none",
                                                           assume_phase_aligned=True))
        self.assertNotIn(b"SYS / PHASE SHIFT", outs[0].data)
        self.assertNotIn(b"GLONASS COD/PHS/BIS", outs[0].data)   # deprecated; unknown -> omitted

    def test_v4_to_v305_zero_form(self):
        v4 = convert_data(V211, "test0010.26o", Options("4.02", glo_fcn=self.fcn, compression="none",
                                                         assume_phase_aligned=True))[0].data
        v3 = convert_data(v4, "x.rnx", Options("3.05", compression="none"))[0].data.decode("latin-1")
        # aligned by definition in 4.x -> zero form for every phase code (PLAN §3.3 rule 6)
        for s, c in (("G", "L1C"), ("G", "L2W"), ("R", "L1C"), ("R", "L2P")):
            self.assertIn(hdr(f"{s} {c}  0.00000", "SYS / PHASE SHIFT"), v3)

    def test_idempotent(self):
        a = convert_data(V211, "test0010.26o", Options("3.05", glo_fcn=self.fcn, compression="none"))[0].data
        b = convert_data(a, "x.rnx", Options("3.05", compression="none"))[0].data
        self.assertEqual(a, b)


class Layout(unittest.TestCase):
    def test_more_than_12_satellites_v2(self):
        sats = [f"G{n:02d}" for n in range(1, 15)]
        hdrs = [hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
                hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
                hdr("     1    C1", "# / TYPES OF OBSERV"),
                hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
                hdr("", "END OF HEADER")]
        ep = [" 26 10  1  0  0  0.0000000  0 14" + "".join(s[0] + f"{int(s[1:]):2d}" for s in sats[:12]),
              " " * 32 + "".join(s[0] + f"{int(s[1:]):2d}" for s in sats[12:])]
        data = [f"  2{n:07d}.000" for n in range(1, 15)]
        src = lines(*hdrs, *ep, *data)
        ld = load_bytes(src)
        self.assertEqual(ld.model.epochs[0].sats, sats)
        out = convert_data(src, "t.26o", Options("2.11", compression="none"))[0].data
        self.assertEqual(out, src)
        v3 = convert_data(src, "t.26o", Options("3.05", compression="none"))[0].data.decode()
        self.assertIn("G14  20000014.000", v3)

    def test_picosecond_epoch(self):
        """4.02 picosecond extension (rinex_4.02.txt Table A3): kept in 4.02, dropped below."""
        src = lines(
            hdr("     4.02           OBSERVATION DATA    G", "RINEX VERSION / TYPE"),
            hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
            hdr("G    1 C1C", "SYS / # / OBS TYPES"),
            hdr("  2026    10     1     0     0    0.0000001     GPS", "TIME OF FIRST OBS"),
            hdr("", "END OF HEADER"),
            "> 2026 10 01 00 00  0.0000001  0  1        .000000123456 12345",
            "G01  20000000.001", width=None)
        out = convert_data(src, "x.rnx", Options("4.02", compression="none"))[0].data
        self.assertEqual(out, src)
        outs = convert_data(src, "x.rnx", Options("3.05", compression="none"))
        self.assertIn(b"> 2026 10 01 00 00  0.0000001  0  1        .000000123456\n", outs[0].data)
        self.assertIn("epoch-precision", outs[0].report.losses)

    def test_beidou_only_to_v2_not_representable(self):
        src = lines(
            hdr("     3.04           OBSERVATION DATA    C", "RINEX VERSION / TYPE"),
            hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
            hdr("C    1 C2I", "SYS / # / OBS TYPES"),
            hdr("  2026    10     1     0     0    0.0000000     BDT", "TIME OF FIRST OBS"),
            hdr("", "END OF HEADER"),
            "> 2026 10 01 00 00  0.0000000  0  1",
            "C01  20000000.001", width=None)
        with self.assertRaises(NotRepresentableError):
            convert_data(src, "x.rnx", Options("2.11", compression="none"))

    def test_bds_b1i_band_gate(self):
        """B1I: C1I in 3.02, C2I from 3.03 (rinex302.txt p.20, rinex303.txt p.24)."""
        src = lines(
            hdr("     3.02           OBSERVATION DATA    C", "RINEX VERSION / TYPE"),
            hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
            hdr("C    2 C1I L1I", "SYS / # / OBS TYPES"),
            hdr("  2026    10     1     0     0    0.0000000     BDT", "TIME OF FIRST OBS"),
            hdr("", "END OF HEADER"),
            "> 2026 10 01 00 00  0.0000000  0  1",
            "C01  20000000.001  104000000.002", width=None)
        v305 = convert_data(src, "x.rnx", Options("3.05", compression="none"))[0].data
        self.assertIn(hdr("C    2 C2I L2I", "SYS / # / OBS TYPES").encode(), v305)
        back = convert_data(v305, "x.rnx", Options("3.02", compression="none"))[0].data
        self.assertEqual(back, src)


if __name__ == "__main__":
    unittest.main()
