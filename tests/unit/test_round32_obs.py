"""Regression tests for review round 32, observation part (2026-11-02): the obs fixer's items
O1-O6 and the checker holes C4-C6.

Inputs and expected outputs are written here by hand from the specs (cited per class); they
are not produced by our writer. Each checker fix has mutation asserts: a converter output
changed in the failure mode the reviewers found must be caught by tests/independent.
"""

import copy
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore.errors import CorruptError, MissingInformationError, NotRepresentableError
from rinexcore.io.hatanaka import CrxCannotHold, crx_to_rnx, rnx_to_crx
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines

PGM = hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE")
XYZ = hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ")
TFO = hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS")
EOH = hdr("", "END OF HEADER")
# the other mandatory records (rinex305.txt Table A2; rinex211.txt Table A1)
SITE = [hdr("TEST", "MARKER NAME"), hdr("ME                  US", "OBSERVER / AGENCY"),
        hdr("1                   REC                 1", "REC # / TYPE / VERS"),
        hdr("1                   ANT", "ANT # / TYPE"), XYZ,
        hdr("        0.0000        0.0000        0.0000", "ANTENNA: DELTA H/E/N")]
MTYPE = hdr("GEODETIC", "MARKER TYPE")


def conv(src, target, name="x.rnx", **kw):
    kw.setdefault("compression", "none")
    outs = convert_data(src, name, Options(target, **kw))
    return outs[0].data, outs[0].report.to_dict()


def problems(src, out, rep, flags=None):
    return compare_obs(src, out, rep) + [f"loss not allowed: {x}" for x in allowed_check(rep, flags)]


def swap(data, old, new):
    """data with one line replaced (exactly one occurrence)."""
    assert data.count(old) == 1, (old, data.count(old))
    return data.replace(old, new)


# ---------------------------------------------------------------------------------------------
# O1: the receiver clock offset of an event epoch (flags 2-5)
# ---------------------------------------------------------------------------------------------
# rinex305.txt Table A3 p.59: the EPOCH record, one for every flag, ends with the optional
# receiver clock offset F15.12 in columns 42-56 (after the reserved 6X); rinex211.txt Table
# A2: the EPOCH/SAT or EVENT FLAG record's clock F12.9 is in columns 69-80. Written without
# the leading zero below 1 s, as RNX2CRX/CRX2RNX write it (rinexcore.obs.fmt_clock).
EV_IN = "> 2026 10 01 00 01 30.0000000  5  1      0.123456789012"
EV305 = lines(
    hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
    SITE[0], MTYPE, *SITE[1:],
    hdr("G    1 C1C", "SYS / # / OBS TYPES"), TFO,
    hdr("G", "SYS / PHASE SHIFT"), EOH,
    "> 2026 10 01 00 00  0.0000000  0  1",
    "G01  20000000.001",
    EV_IN,
    hdr("EXTERNAL EVENT", "COMMENT"),
    "> 2026 10 01 00 02  0.0000000  0  1",
    "G01  20000000.002", width=None)
EV_OUT3 = "> 2026 10 01 00 01 30.0000000  5  1        .123456789012"
EV_OUT2 = " 26 10  1  0  1 30.0000000  5  1" + " " * 36 + "  .123456789"
EV211 = lines(
    hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM, *SITE,
    hdr("     1     1", "WAVELENGTH FACT L1/2"),
    hdr("     1    C1", "# / TYPES OF OBSERV"), TFO, EOH,
    " 26 10  1  0  0  0.0000000  0  1G 1",
    "  20000000.001",
    EV_OUT2,
    hdr("EXTERNAL EVENT", "COMMENT"),
    " 26 10  1  0  2  0.0000000  0  1G 1",
    "  20000000.002")


class EventClock(unittest.TestCase):
    """O1 (Sol): an event's clock vanished in every conversion with losses {} and passed the
    checker."""

    def test_same_version_strict(self):
        out, rep = conv(EV305, "3.05", strict=True, auto_nav=False)
        self.assertEqual(out, swap(EV305, EV_IN.encode(), EV_OUT3.encode()))
        self.assertEqual(rep["losses"], {})
        self.assertEqual(problems(EV305, out, rep), [])

    def test_to_402(self):
        out, rep = conv(EV305, "4.02")
        self.assertIn(b"\n" + EV_OUT3.encode() + b"\n", out)
        self.assertEqual(rep["losses"], {})
        self.assertEqual(problems(EV305, out, rep), [])

    def test_to_211_hand_written(self):
        out, rep = conv(EV305, "2.11")
        self.assertEqual(out, EV211)
        # F15.12 -> F12.9: 0.123456789012 rounds to 0.123456789 (the rule of observation epochs)
        # (MARKER TYPE is RINEX 3/4 only: rinex211.txt Table A1 has none)
        self.assertEqual({k: v["count"] for k, v in rep["losses"].items()},
                         {"clock-precision": 1, "header-record-not-representable:MARKER TYPE": 1})
        self.assertEqual(problems(EV305, out, rep), [])

    def test_v2_event_clock_to_v3(self):
        out, rep = conv(EV211, "3.05", name="test2740.26o")
        self.assertIn(b"\n> 2026 10 01 00 01 30.0000000  5  1        .123456789000\n", out)
        self.assertEqual(rep["losses"], {})
        self.assertEqual(problems(EV211, out, rep), [])
        back, rep2 = conv(out, "2.11")
        self.assertIn(b"\n" + EV_OUT2.encode() + b"\n", back)
        self.assertEqual(rep2["losses"], {})

    def test_checker_sees_a_dropped_or_changed_event_clock(self):
        for t, line, bad in (("3.05", EV_OUT3, EV_OUT3[:35]), ("3.05", EV_OUT3, EV_OUT3[:-1] + "3"),
                             ("4.02", EV_OUT3, EV_OUT3[:35]), ("2.11", EV_OUT2, EV_OUT2[:32]),
                             ("2.11", EV_OUT2, EV_OUT2[:-1] + "8")):
            with self.subTest(target=t, bad=bad):
                out, rep = conv(EV305, t)
                self.assertTrue(problems(EV305, swap(out, line.encode(), bad.encode()), rep))
        # and a clock-overflow claim for a clock that fits is no excuse
        out, rep = conv(EV305, "3.05")
        rep = copy.deepcopy(rep)
        rep["losses"]["clock-overflow"] = {"count": 1, "detail": {}}
        self.assertTrue(problems(EV305, swap(out, EV_OUT3.encode(), EV_OUT3[:35].encode()), rep))

    def test_validator_takes_a_v2_event_clock(self):
        from rinexcore import validate as V
        self.assertEqual([f.rule for f in V.errors(V.validate(EV211))], [])
        bad = swap(EV211, EV_OUT2.encode(), (EV_OUT2[:-3] + "x89").encode())
        self.assertIn("VAL.OBS.EPOCH.SYNTAX", [f.rule for f in V.errors(V.validate(bad))])
        bad = swap(EV211, EV_OUT2.encode(), (EV_OUT2[:40] + "G01" + EV_OUT2[43:]).encode())
        self.assertIn("VAL.OBS.EPOCH.SYNTAX", [f.rule for f in V.errors(V.validate(bad))])

    def test_clock_wider_than_f15_12(self):
        """A RINEX 2 clock written wider than F12.9 (readable; validator warning) has no F15.12
        form: dropped and claimed clock-overflow (it escaped as an OverflowError)."""
        src = swap(EV211, b"0  1G 1\n  20000000.001",
                   b"0  1G 1" + b" " * 33 + b" 123.4567890\n  20000000.001")
        out, rep = conv(src, "3.05", name="test2740.26o")
        self.assertEqual({k: v["count"] for k, v in rep["losses"].items()}, {"clock-overflow": 1})
        self.assertIn(b"\n> 2026 10 01 00 00  0.0000000  0  1\n", out)
        self.assertEqual(problems(src, out, rep), [])

    def test_hatanaka_round_trip(self):
        """RNX2CRX copies an event line verbatim (rnx2crx.c put_event_data l.491-528); ours too,
        and both decoders give the line back."""
        for plain in (conv(EV305, "3.05")[0], conv(EV305, "4.02")[0], EV211):
            with self.subTest(version=plain[:9]):
                crx = rnx_to_crx(plain, date="30-Oct-26 00:00")
                self.assertEqual(crx_to_rnx(crx), plain)
                want = ("&" + EV_OUT2[1:]) if plain[5:6] == b"2" else EV_OUT3
                self.assertIn(b"\n" + want.encode() + b"\n", crx)

    def test_rnxcmp_live(self):
        from .test_hatanaka import body, find_crx2rnx, find_rnx2crx, run_crx2rnx, run_rnx2crx
        enc, dec = find_rnx2crx(), find_crx2rnx()
        if not enc or not dec:
            self.skipTest("RNX2CRX / CRX2RNX 4.2.0 not available")
        for plain in (conv(EV305, "3.05")[0], conv(EV305, "4.02")[0], EV211):
            with self.subTest(version=plain[:9]):
                code, out, err = run_rnx2crx(enc, plain)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(body(out), body(rnx_to_crx(plain, date="30-Oct-26 00:00")))
                code, back, err = run_crx2rnx(dec, out)
                self.assertEqual(code, 0, err)
                self.assertEqual(back, plain)


# ---------------------------------------------------------------------------------------------
# O2: SYS / PHASE SHIFT of RINEX 3.02 has the three states of 3.03+
# ---------------------------------------------------------------------------------------------
# rinex302.txt section 9.1 p.41-42: values zero = aligned at the source; the observation code
# given and the rest blank = only reference signals (aligned); code field and the rest blank =
# unknown. rinex301.txt p.25: in 3.01 one blank form means 'none affected, or not known'.
# PLAN 3.3: to 4.x unknown alignment is refused without --assume-phase-aligned; a record with
# values is strongly deprecated in 4.x and claimed (rinex_4.00.txt Table A2 p.61).
def phase_src(version, entries):
    label = "SYS / PHASE SHIFTS" if version == "3.01" else "SYS / PHASE SHIFT"
    return lines(
        hdr(f"{version:>9s}           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
        hdr("TEST", "MARKER NAME"),
        hdr("G    4 C1C L1C C2L L2L", "SYS / # / OBS TYPES"), TFO,
        *[hdr(e, label) for e in entries], EOH,
        "> 2026 10 01 00 00  0.0000000  0  1",
        "G01  20000000.001   104000000.002   20000000.003    81000000.004", width=None)


FORMS = {"zero": ["G L1C  0.00000", "G L2L  0.00000"], "code-only": ["G L1C"],
         "values": ["G L2L -0.25000"], "blank": ["G"], "none": []}
# what each target holds, by hand: the entries carried within 3.01-3.05 (3.01 spells the label
# SYS / PHASE SHIFTS); nothing in 4.02 (a record naming a code is claimed deprecated, one
# per entry: the code-only form says 'only reference signals' from 3.02), and a refusal
# where the alignment is unknown
WANT_402 = {"zero": {"phase-shift-record-deprecated": 2}, "code-only": {"phase-shift-record-deprecated": 1},
            "values": {"phase-shift-record-deprecated": 1}, "blank": "refused", "none": "refused"}


class Phase302(unittest.TestCase):
    """O2: a valid 3.02 code-only record ('only reference signals') was read as unknown, so the
    file was refused going to RINEX 4."""

    def test_every_302_form_to_every_family(self):
        for form, entries in FORMS.items():
            src = phase_src("3.02", entries)
            for t in ("3.01", "3.02", "3.03", "3.05"):
                with self.subTest(form=form, target=t):
                    out, rep = conv(src, t)
                    label = "SYS / PHASE SHIFTS" if t == "3.01" else "SYS / PHASE SHIFT"
                    got = [l[:60].rstrip() for l in out.decode().split("\n") if "PHASE SHIFT" in l]
                    # 3.01 has no code-only form: its blank form, the system alone (verify
                    # round V2, class Phase30xCodeOnlyTo301)
                    want, lost = (["G"], {"phase-shift-entry-dropped:G:L1C": {"count": 1, "detail": {}}}) \
                        if (form, t) == ("code-only", "3.01") else (entries, {})
                    self.assertEqual(got, want)
                    self.assertTrue(all(label == l[60:].strip() for l in out.decode().split("\n")
                                        if "PHASE SHIFT" in l))
                    self.assertEqual(rep["losses"], lost)
                    self.assertEqual(problems(src, out, rep), [])
            with self.subTest(form=form, target="4.02"):
                if WANT_402[form] == "refused":
                    with self.assertRaises(MissingInformationError):
                        conv(src, "4.02")
                    continue
                out, rep = conv(src, "4.02")
                self.assertNotIn(b"PHASE SHIFT", out)
                self.assertEqual({k: v["count"] for k, v in rep["losses"].items()}, WANT_402[form])
                self.assertEqual(problems(src, out, rep), [])

    def test_301_code_without_value_stays_unknown(self):
        """3.01 has no 'reference signals only' form (rinex301.txt p.25): kept as it was."""
        with self.assertRaises(MissingInformationError):
            conv(phase_src("3.01", ["G L1C"]), "4.02")

    def test_302_target_forms(self):
        """Writing 3.02: aligned (a RINEX 4 source) is the zero form; unknown (RINEX 2) is the
        fully blank form, which 3.02 says should not be published (p.41): warned, as from 3.03.
        3.01's blank form also means 'none affected' (p.25): no warning there."""
        v4 = phase_src("4.02", [])
        out, rep = conv(v4, "3.02")
        self.assertIn((hdr("G L1C  0.00000", "SYS / PHASE SHIFT") + "\n"
                       + hdr("G L2L  0.00000", "SYS / PHASE SHIFT")).encode(), out)
        self.assertEqual(problems(v4, out, rep), [])
        v2 = lines(hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
                   hdr("TEST", "MARKER NAME"), XYZ, hdr("     1     1", "WAVELENGTH FACT L1/2"),
                   hdr("     2    C1    L1", "# / TYPES OF OBSERV"), TFO, EOH,
                   " 26 10  1  0  0  0.0000000  0  1G01", "  20000000.001  104000000.002")
        for t, warned in (("3.01", False), ("3.02", True), ("3.03", True)):
            with self.subTest(target=t):
                out, rep = conv(v2, t, name="test2740.26o")
                lab = "SYS / PHASE SHIFTS" if t == "3.01" else "SYS / PHASE SHIFT"
                self.assertIn(("\n" + hdr("G", lab) + "\n").encode(), out)
                self.assertEqual("OBS.PHASE-UNKNOWN" in [w["rule"] for w in rep["warnings"]], warned)
                self.assertEqual(problems(v2, out, rep), [])


# ---------------------------------------------------------------------------------------------
# O3: the RINEX 2.20 OBS SCALE FACTOR record
# ---------------------------------------------------------------------------------------------
# rinex300.txt section 5.5 p.12: SYS / SCALE FACTOR 'is a modification of the Version 2.20 OBS
# SCALE FACTOR record' (2.20: Gurtner and Estey 2002, cited rinex300.txt l.1583; I6 factor, I6
# number of types, 8(4X,A2) types); rinex305.txt Table A2 p.56: A1,1X,I4 factor (1, 10, 100,
# 1000),2X,I2 count, 12(1X,A3) types. The stored values are not changed: the factor goes with
# them. Codes: P2 -> C2W, L1 -> L1C, L2 -> L2W (the documented defaults, codemap.py).
SC_DATA = F("  22000000.105") + F("1150000000.405") + F("  22000002.305") + F(" 896000000.505")
SC211 = lines(
    hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
    hdr("TEST", "MARKER NAME"), XYZ, hdr("     1     1", "WAVELENGTH FACT L1/2"),
    hdr("     4    C1    L1    P2    L2", "# / TYPES OF OBSERV"),
    hdr("    10     2    L1    L2", "OBS SCALE FACTOR"), TFO, EOH,
    " 26 10  1  0  0  0.0000000  0  1G 5",
    SC_DATA.rstrip())
SC305 = lines(
    hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
    hdr("TEST", "MARKER NAME"), XYZ,
    hdr("G    4 C1C L1C C2W L2W", "SYS / # / OBS TYPES"), TFO,
    hdr("G   10   2 L1C L2W", "SYS / SCALE FACTOR"),
    hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), hdr("G L2W  0.00000", "SYS / PHASE SHIFT"), EOH,
    "> 2026 10 01 00 00  0.0000000  0  1",
    ("G05" + SC_DATA).rstrip(), width=None)


class ObsScaleFactor(unittest.TestCase):
    """O3: the record was carried verbatim into 3.x/4.x, where no reader divides by it."""

    def test_to_305_hand_written(self):
        out, rep = conv(SC211, "3.05", name="test2740.26o", assume_phase_aligned=True)
        self.assertEqual(out, SC305)
        self.assertEqual(rep["losses"], {})
        self.assertIn("OBS.V2V3.OBS-SCALE-FACTOR", rep["rules"])
        self.assertEqual(problems(SC211, out, rep), [])

    def test_to_v2_carried(self):
        out, rep = conv(SC211, "2.11", name="test2740.26o")
        self.assertEqual(out, SC211)
        self.assertEqual(problems(SC211, out, rep), [])

    def test_round_trip_through_305(self):
        """3.05 back to RINEX 2: the values are divided (no RINEX 2 record), a rounding claimed."""
        out, rep = conv(SC305, "2.11")
        want = F("  22000000.105") + F(" 115000000.040") + F("  22000002.305") + F("  89600000.050")
        self.assertIn(("\n" + want.rstrip() + "\n").encode(), out)
        self.assertEqual({k: v["count"] for k, v in rep["losses"].items()},
                         {"scale-factor-rounding:G:L1C": 1, "scale-factor-rounding:G:L2W": 1,
                          "phase-shift-record-not-representable": 2})
        self.assertEqual(problems(SC305, out, rep), [])

    def test_in_an_event(self):
        src = swap(SC211, b"\n 26 10  1  0  0  0.0000000  0  1G 5",
                   b"\n 26 10  1  0  0  0.0000000  4  1\n"
                   + hdr("   100     1    L1", "OBS SCALE FACTOR").encode()
                   + b"\n 26 10  1  0  0  0.0000000  0  1G 5")
        out, rep = conv(src, "3.05", name="test2740.26o", assume_phase_aligned=True)
        self.assertIn(b"\n> 2026 10 01 00 00  0.0000000  4  1\n"
                      + hdr("G  100   1 L1C", "SYS / SCALE FACTOR").encode() + b"\n", out)
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(problems(src, swap(out, hdr("G  100   1 L1C", "SYS / SCALE FACTOR").encode(),
                                           hdr("   100     1    L1", "OBS SCALE FACTOR").encode()), rep))

    def test_checker_catches_the_old_output(self):
        """The round-31 output: OBS SCALE FACTOR verbatim in RINEX 3, values taken unscaled."""
        out, rep = conv(SC211, "3.05", name="test2740.26o", assume_phase_aligned=True)
        old = swap(out, hdr("G   10   2 L1C L2W", "SYS / SCALE FACTOR").encode(),
                   hdr("    10     2    L1    L2", "OBS SCALE FACTOR").encode())
        self.assertTrue(problems(SC211, old, rep))
        dropped = swap(out, (hdr("G   10   2 L1C L2W", "SYS / SCALE FACTOR") + "\n").encode(), b"")
        self.assertTrue(problems(SC211, dropped, rep))

    def test_factor_without_v3_form_refused(self):
        """2.20 allows factors such as 5; SYS / SCALE FACTOR takes 1, 10, 100, 1000 only."""
        src = swap(SC211, b"    10     2    L1", b"     5     2    L1")
        with self.assertRaises(NotRepresentableError):
            conv(src, "3.05", name="test2740.26o", assume_phase_aligned=True)
        out, rep = conv(src, "2.11", name="test2740.26o")      # RINEX 2: carried as written
        self.assertEqual(out, src)

    def test_unreadable_record_refused(self):
        src = swap(SC211, b"    10     2    L1    L2", b"    10     3    L1    L2")
        with self.assertRaises(CorruptError):
            conv(src, "3.05", name="test2740.26o", assume_phase_aligned=True)


# ---------------------------------------------------------------------------------------------
# O4: --lenient and text no field covers
# ---------------------------------------------------------------------------------------------
G7 = [F("  22000000.105"), F("  22000001.205"), F("  22000002.305"), F(" 115000000.405"),
      F("  89000000.505"), F("        45.000"), F("        38.500")]
LONG211 = lines(
    hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
    hdr("TEST", "MARKER NAME"), XYZ, hdr("     1     1", "WAVELENGTH FACT L1/2"),
    hdr("     7    C1    P1    P2    L1    L2    S1    S2", "# / TYPES OF OBSERV"), TFO, EOH,
    " 26 10  1  0  0  0.0000000  0  1G05",
    "".join(G7[0:5]).rstrip(), "".join(G7[5:7]).rstrip()).replace(
        b"  89000000.505", b"  89000000.505  12345678.901 1")       # a sixth field on line 1


class LenientDroppedText(unittest.TestCase):
    """O4: a RINEX 2 record line longer than 80 columns was cut at 80 under --lenient, the
    value in columns 81-96 gone with losses {}. rinex211.txt Table A2: 5 fields per line."""

    def test_refused_by_default(self):
        with self.assertRaises(CorruptError):
            conv(LONG211, "3.05", name="test2740.26o")

    def test_lenient_claims_it(self):
        for t in ("2.11", "3.05"):
            with self.subTest(target=t):
                out, rep = conv(LONG211, t, name="test2740.26o", lenient=True, assume_phase_aligned=True)
                self.assertEqual({k: v["count"] for k, v in rep["losses"].items()}, {"data-text-dropped": 1})
                self.assertIn("OBS.DATA.SKIPPED-TEXT", [r["rule"] for r in rep["repairs"]])
                self.assertNotIn(b"12345678.901", out)
                self.assertEqual(problems(LONG211, out, rep), [])
                gone = copy.deepcopy(rep)
                del gone["losses"]["data-text-dropped"]
                self.assertTrue(compare_obs(LONG211, out, gone))
                more = copy.deepcopy(rep)
                more["losses"]["data-text-dropped"]["count"] = 2
                self.assertTrue(compare_obs(LONG211, out, more))

    def test_v3_extra_field(self):
        src = swap(EV305, b"G01  20000000.002", b"G01  20000000.002    30000000.003")
        with self.assertRaises(CorruptError):
            conv(src, "3.05")
        out, rep = conv(src, "3.05", lenient=True)
        self.assertEqual({k: v["count"] for k, v in rep["losses"].items()}, {"data-text-dropped": 1})
        self.assertEqual(problems(src, out, rep), [])


# ---------------------------------------------------------------------------------------------
# O5: --keep-v2-nonstandard and BeiDou B1I of a 3.02 file
# ---------------------------------------------------------------------------------------------
# rinex302.txt p.20: B1I is band 1 (C1I/L1I) in 3.02; rinex303.txt p.24: band 2 from 3.03. The
# same signal must get the same RINEX 2 code (C2/L2, codemap.v3_to_v2) from either.
def bds(version, band):
    return lines(
        hdr(f"{version:>9s}           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), PGM,
        hdr("TEST", "MARKER NAME"), XYZ,
        hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
        hdr(f"C    2 C{band}I L{band}I", "SYS / # / OBS TYPES"), TFO,
        hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), hdr(f"C L{band}I  0.00000", "SYS / PHASE SHIFT"), EOH,
        "> 2026 10 01 00 00  0.0000000  0  2",
        "G01  20000000.001   104000000.002",
        "C01  30000000.003   156000000.004", width=None)


BDS211 = lines(
    hdr("     2.11           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), PGM,
    hdr("TEST", "MARKER NAME"), XYZ, hdr("     1     1", "WAVELENGTH FACT L1/2"),
    hdr("     4    C1    L1    C2    L2", "# / TYPES OF OBSERV"), TFO, EOH,
    " 26 10  1  0  0  0.0000000  0  2G 1C 1",
    (F("  20000000.001") + F(" 104000000.002")).rstrip(),
    (" " * 32 + F("  30000000.003") + F(" 156000000.004")).rstrip())


class BeiDouB1IToV2(unittest.TestCase):
    def test_302_and_303_give_the_same_file(self):
        for v, band in (("3.02", "1"), ("3.03", "2")):
            with self.subTest(version=v):
                src = bds(v, band)
                out, rep = conv(src, "2.11", keep_v2_nonstandard=True)
                self.assertEqual(out, BDS211)
                self.assertEqual({k: v["count"] for k, v in rep["losses"].items()},
                                 {"phase-shift-record-not-representable": 2})
                self.assertEqual(problems(src, out, rep), [])


# ---------------------------------------------------------------------------------------------
# O6: an F14.3 value RNX2CRX cannot take
# ---------------------------------------------------------------------------------------------
class NonCanonicalValueCrx(unittest.TestCase):
    """O6: '     1050010.1' reads as F14.3 (an explicit point), so the file is valid, but RNX2CRX
    needs the point in column 11 and three decimals: the converter writes plain RINEX with a
    warning (as for the other inputs Compact RINEX cannot carry: docs/DECISIONS.md, the user's
    answer 1 of 2026-11-01) and keeps the value text as written."""

    SRC = swap(EV305, b"G01  20000000.002", b"G01     1050010.1")

    def test_plain_with_warning(self):
        outs = convert_data(self.SRC, "TEST00XXX_R_20262740000_01D_30S_MO.rnx",
                            Options("3.05", crx=True, compression="none"))
        rep = outs[0].report.to_dict()
        self.assertEqual(rep["outcome"], "converted")
        self.assertIn("OBS.CRX.FIELD-PLAIN", [w["rule"] for w in rep["warnings"]])
        self.assertTrue(outs[0].name.endswith(".rnx"))
        self.assertIn(b"\nG01     1050010.1\n", outs[0].data)
        self.assertEqual(problems(self.SRC, outs[0].data, rep), [])

    def test_encoder(self):
        with self.assertRaises(CrxCannotHold) as cm:
            rnx_to_crx(self.SRC)
        self.assertEqual(cm.exception.rule, "CRX.ENC.FIELD")
        try:
            rnx_to_crx(swap(EV305, b"G01  20000000.002", b"G01  200 0000.002"))
        except CorruptError as e:
            self.assertNotIsInstance(e, CrxCannotHold)        # garbage stays refused-corrupt
        else:
            self.fail("garbage digits were encoded")


# ---------------------------------------------------------------------------------------------
# C4: WAVELENGTH FACT L1/2
# ---------------------------------------------------------------------------------------------
# rinex211.txt Table A1/A2: factors 1 (full) or 2 (half cycle) for L1 and L2, per satellite if
# listed; LLI bit 1 'opposite wavelength factor'. rinex300.txt section 5.4 p.12: RINEX 3 stores
# half-wavelength phases in full cycles (LLI bit 1: half-cycle ambiguity).
WL211 = lines(
    hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
    hdr("TEST", "MARKER NAME"), XYZ,
    hdr("     2     2", "WAVELENGTH FACT L1/2"),
    hdr("     1     1     1   G12", "WAVELENGTH FACT L1/2"),
    hdr("     2    C1    L1", "# / TYPES OF OBSERV"), TFO, EOH,
    " 26 10  1  0  0  0.0000000  0  2G05G12",
    "  20000000.001  104000000.002", "  21000000.001  109000000.002")


class WavelengthChecks(unittest.TestCase):
    def test_v2_to_v2(self):
        out, rep = conv(WL211, "2.10", name="test2740.26o")
        self.assertEqual(problems(WL211, out, rep), [])
        for old, new in (("     2     2", "     1     1"), ("     1     1     1   G12", "     2     2     1   G12"),
                         ("     1     1     1   G12", "     1     1     1   G05")):
            with self.subTest(change=(old, new)):
                bad = swap(out, hdr(old, "WAVELENGTH FACT L1/2").encode(), hdr(new, "WAVELENGTH FACT L1/2").encode())
                self.assertTrue(problems(WL211, bad, rep))
        gone = swap(out, (hdr("     2     2", "WAVELENGTH FACT L1/2") + "\n").encode(), b"")
        self.assertTrue(problems(WL211, gone, rep))

    def test_v3_to_v2_full_cycles(self):
        out, rep = conv(EV305, "2.10")
        self.assertIn(hdr("     1     1", "WAVELENGTH FACT L1/2").encode(), out)
        self.assertEqual(problems(EV305, out, rep), [])
        bad = swap(out, hdr("     1     1", "WAVELENGTH FACT L1/2").encode(),
                   hdr("     2     2", "WAVELENGTH FACT L1/2").encode())
        self.assertTrue(problems(EV305, bad, rep))
        gone = swap(out, (hdr("     1     1", "WAVELENGTH FACT L1/2") + "\n").encode(), b"")
        self.assertTrue(problems(EV305, gone, rep))          # mandatory in 2.10

    def test_v2_to_v3_record_gone(self):
        out, rep = conv(WL211, "3.05", name="test2740.26o", assume_phase_aligned=True)
        self.assertNotIn(b"WAVELENGTH", out)
        self.assertEqual(problems(WL211, out, rep), [])
        bad = swap(out, b"G    2 C1C L1C", hdr("     2     2", "WAVELENGTH FACT L1/2").encode()
                   + b"\nG    2 C1C L1C")
        self.assertTrue(problems(WL211, bad, rep))


# ---------------------------------------------------------------------------------------------
# C5: RINEX 2 -> 3 attributes against the report's assumptions
# ---------------------------------------------------------------------------------------------
class AttributeAssumptions(unittest.TestCase):
    def setUp(self):
        from .test_obs_fixtures import V211
        self.src = V211
        self.out, self.rep = conv(V211, "3.00", name="test2740.26o", drop_unresolvable=True)
        self.flags = {"drop_unresolvable": True}

    def test_clean(self):
        self.assertEqual(problems(self.src, self.out, self.rep, self.flags), [])

    def test_renamed_output_code(self):
        for old, new in (("L2W", "L2C"), ("C1W", "C1P"), ("L1C", "L1W"), ("C2W", "C2D")):
            with self.subTest(rename=(old, new)):
                bad = self.out.replace(f" {old}".encode(), f" {new}".encode(), 1)
                self.assertNotEqual(bad, self.out)
                self.assertTrue(problems(self.src, bad, self.rep, self.flags))

    def test_assumption_of_another_signal(self):
        rep = copy.deepcopy(self.rep)
        a = next(x for x in rep["assumptions"] if x["detail"] == "P1->C1W")
        a["detail"] = "P1->C1C"
        self.assertTrue(compare_obs(self.src, self.out.replace(b" C1W", b" C1C", 1), rep))


# ---------------------------------------------------------------------------------------------
# C6: # OF SATELLITES and PRN / # OF OBS inside events
# ---------------------------------------------------------------------------------------------
CNT305 = lines(
    hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
    hdr("TEST", "MARKER NAME"), XYZ,
    hdr("G    1 C1C", "SYS / # / OBS TYPES"), TFO,
    hdr("G", "SYS / PHASE SHIFT"), EOH,
    "> 2026 10 01 00 00  0.0000000  0  2",
    "G01  20000000.001",
    "G02  21000000.001",
    "> 2026 10 01 00 00 30.0000000  0  1",
    "G01  20000000.002",
    ">                              4  3",
    hdr("     2", "# OF SATELLITES"),
    hdr("   G01     2", "PRN / # OF OBS"),
    hdr("   G02     1", "PRN / # OF OBS"), width=None)


class EventCounts(unittest.TestCase):
    def test_counts_checked_like_the_header(self):
        for t in ("3.05", "2.11"):
            with self.subTest(target=t):
                out, rep = conv(CNT305, t)
                self.assertEqual(problems(CNT305, out, rep), [])
                g01 = "   G01     2" if t >= "3" else "   G 1     2"
                for old, new in ((g01, g01[:-1] + "3"), ("     2", "     3")):
                    lab = "PRN / # OF OBS" if old == g01 else "# OF SATELLITES"
                    bad = swap(out, hdr(old, lab).encode(), hdr(new, lab).encode())
                    self.assertTrue(problems(CNT305, bad, rep), (old, new))
                gone = swap(out, (hdr(g01, "PRN / # OF OBS") + "\n").encode(), b"")
                gone = gone.replace(b"4  3\n", b"4  2\n")
                self.assertTrue(problems(CNT305, gone, rep))

    def test_wrong_input_counts_are_a_repair(self):
        src = swap(CNT305, hdr("   G02     1", "PRN / # OF OBS").encode(), hdr("   G02     7", "PRN / # OF OBS").encode())
        out, rep = conv(src, "3.05")
        self.assertIn("HDR.COUNTS", [r["rule"] for r in rep["repairs"]])
        self.assertIn(hdr("   G02     1", "PRN / # OF OBS").encode(), out)
        self.assertEqual(problems(src, out, rep), [])
        quiet = copy.deepcopy(rep)
        quiet["repairs"] = [r for r in quiet["repairs"] if r["rule"] != "HDR.COUNTS"]
        self.assertTrue(compare_obs(src, out, quiet))


# ---------------------------------------------------------------------------------------------
# F1 (lead follow-up): a 3.01 code-only entry is 'unknown', not 'only reference signals'
# ---------------------------------------------------------------------------------------------
# rinex301.txt section 9.1 p.24-25: only applied corrections are recorded; the one blank form
# means 'none affected, or not known'. rinex302.txt section 9.1 p.41: from 3.02 a code with
# the rest blank means 'only reference signals' (aligned), the system alone means unknown.
# PLAN section 3.3 rule 1: unknown is written as the fully blank form, with an assumption and
# (3.02+) a warning.
class Phase301CodeOnly(unittest.TestCase):
    SRC = phase_src("3.01", ["G L1C"])

    def test_to_302_and_305(self):
        for t in ("3.02", "3.05"):
            with self.subTest(target=t):
                out, rep = conv(self.SRC, t)
                got = [l[:60].rstrip() for l in out.decode().split("\n") if "PHASE SHIFT" in l]
                self.assertEqual(got, ["G"])
                self.assertEqual({k: v["count"] for k, v in rep["losses"].items()},
                                 {"phase-shift-entry-dropped:G:L1C": 1})
                self.assertIn(("phase-alignment", "G:unknown"),
                              {(a["category"], a["detail"]) for a in rep["assumptions"]})
                self.assertIn("OBS.PHASE-UNKNOWN", [w["rule"] for w in rep["warnings"]])
                self.assertEqual(problems(self.SRC, out, rep), [])
                # the round-31 output (the code-only form carried) and a deleted claim are caught
                old = swap(out, hdr("G", "SYS / PHASE SHIFT").encode(), hdr("G L1C", "SYS / PHASE SHIFT").encode())
                self.assertTrue(problems(self.SRC, old, rep))
                quiet = copy.deepcopy(rep)
                quiet["losses"] = {}
                self.assertTrue(compare_obs(self.SRC, out, quiet))

    def test_same_version_carried(self):
        out, rep = conv(self.SRC, "3.01")
        self.assertIn(hdr("G L1C", "SYS / PHASE SHIFTS").encode(), out)
        self.assertEqual(rep["losses"], {})

    def test_with_a_value_beside_it(self):
        src = phase_src("3.01", ["G L1C", "G L2L -0.25000"])
        out, rep = conv(src, "3.05")
        got = [l[:60].rstrip() for l in out.decode().split("\n") if "PHASE SHIFT" in l]
        self.assertEqual(got, ["G L2L -0.25000"])
        self.assertEqual({k: v["count"] for k, v in rep["losses"].items()},
                         {"phase-shift-entry-dropped:G:L1C": 1})
        self.assertEqual(problems(src, out, rep), [])

    def test_to_402(self):
        with self.assertRaises(MissingInformationError):
            conv(self.SRC, "4.02")
        out, rep = conv(self.SRC, "4.02", assume_phase_aligned=True)
        self.assertNotIn(b"PHASE SHIFT", out)
        self.assertEqual({k: v["count"] for k, v in rep["losses"].items()}, {"phase-shift-record-deprecated": 1})
        self.assertEqual(problems(self.SRC, out, rep), [])


# ---------------------------------------------------------------------------------------------
# F2 (lead follow-up): columns 57-62 of an epoch line before 4.02
# ---------------------------------------------------------------------------------------------
# rinex_4.02.txt Table A3: the picosecond field (1X,I5.5, columns 57-62) is 4.02's; rinex305.txt
# Table A3 p.59 ends the EPOCH record with the clock F15.12 at column 56.
class PicosecondColumnsBefore402(unittest.TestCase):
    EP = "> 2026 10 01 00 00  0.0000000  0  1"
    SRC = swap(EV305, EP.encode() + b"\n", (EP.ljust(56) + " 12345\n").encode())

    def test_refused_by_default(self):
        with self.assertRaises(CorruptError) as cm:
            conv(self.SRC, "3.05")
        self.assertEqual(cm.exception.rule, "VAL.OBS.EPOCH.PICOSECONDS")

    def test_lenient_drops_and_claims(self):
        for t in ("3.05", "4.02"):
            with self.subTest(target=t):
                out, rep = conv(self.SRC, t, lenient=True)
                self.assertIn(("\n" + self.EP + "\n").encode(), out)     # no picoseconds read
                self.assertEqual({k: v["count"] for k, v in rep["losses"].items()}, {"data-text-dropped": 1})
                self.assertEqual(problems(self.SRC, out, rep), [])
                quiet = copy.deepcopy(rep)
                quiet["losses"] = {}
                self.assertTrue(compare_obs(self.SRC, out, quiet))
        # the round-31 reading: 12345 ps added to the epoch, written in 4.02
        out, rep = conv(self.SRC, "4.02", lenient=True)
        old = swap(out, ("\n" + self.EP + "\n").encode(), ("\n" + self.EP.ljust(56) + " 12345\n").encode())
        self.assertTrue(problems(self.SRC, old, rep))


# ---------------------------------------------------------------------------------------------
# F3 (lead follow-up): a blank LEAP SECONDS time-system identifier is GPS (3.03+)
# ---------------------------------------------------------------------------------------------
# rinex303.txt Table A2 p.60, rinex305.txt Table A2 p.58: 'Time system identifier: only GPS
# and BDS/BDT are valid identifiers. Blank defaults to GPS'; 3.01/3.02 have 4I6 and no such
# field (rinex302.txt Table A2 p.55).
class LeapIdentifierBlankIsGps(unittest.TestCase):
    def test_check_leap(self):
        from tests.independent.headers import check_leap
        gps = "    18    18  2185     7GPS"
        self.assertEqual(check_leap(gps, "    18    18  2185     7", "3.03", "3.05", {})[0], [])
        self.assertEqual(check_leap(gps, gps, "3.03", "4.02", {})[0], [])
        for bad in ("    17    18  2185     7", "    18    18  2185     7BDT", "    18    18  2185     6GPS"):
            with self.subTest(bad=bad):
                self.assertTrue(check_leap(gps, bad, "3.03", "3.05", {})[0])

    def test_round_trip_through_302(self):
        """NRCan 3.03 -> 3.02 -> 3.03: '18 GPS' comes back as '18', the same record."""
        src = swap(EV305, b"     3.05           OBSERVATION", b"     3.03           OBSERVATION")
        src = swap(src, hdr("G", "SYS / PHASE SHIFT").encode(),
                   hdr("G", "SYS / PHASE SHIFT").encode() + b"\n"
                   + hdr("    18    18  2185     7GPS", "LEAP SECONDS").encode())
        ident, _ = conv(src, "3.03")
        mid, rep1 = conv(src, "3.02")
        self.assertIn(hdr("    18    18  2185     7", "LEAP SECONDS").encode(), mid)
        self.assertEqual(rep1["losses"], {})
        back, rep2 = conv(mid, "3.03")
        self.assertEqual(compare_obs(ident, back, rep2), [])


# ---------------------------------------------------------------------------------------------
# Astra round 39, A1: header records after every event flag 2-5 hold from there on
# ---------------------------------------------------------------------------------------------
# rinex211.txt section 0.4 (l.241-242): 'Header records now allowed after all epoch flags >1';
# rinex305.txt section 6.5 p.42: a header value holds until changed. Only flags 3 and 4 were
# applied: a flag-2 event's SYS / SCALE FACTOR 10 for L1C left 3.05 -> 2.11 with L1 x10.
class HeaderRecordsAfterEveryEventFlag(unittest.TestCase):
    def test_scale_factor(self):
        for flag in ("2", "5"):
            with self.subTest(flag=flag):
                src = scale_src("event", ["G   10   1 L1C"]).replace(
                    b"                              4  1", b"                              " + flag.encode() + b"  1")
                out, rep = conv(src, "2.11")
                self.assertIn(("\n" + (F("   2200000.010") + F(" 115000000.040")).rstrip() + "\n").encode(), out)
                self.assertEqual(problems(src, out, rep), [])
                self.assertTrue(problems(src, out.replace(b"115000000.040", b" 11500000.004"), rep))
                v3out, rep3 = conv(src, "3.05")
                self.assertIn(hdr("G   10   1 L1C", "SYS / SCALE FACTOR").encode(), v3out)
                self.assertEqual(problems(src, v3out, rep3), [])

    def test_type_list_v3(self):
        """A flag-5 event's SYS / # / OBS TYPES holds for the epochs after it."""
        src = lines(hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
                    SITE[0], MTYPE, *SITE[1:], hdr("G    1 C1C", "SYS / # / OBS TYPES"), TFO,
                    hdr("G", "SYS / PHASE SHIFT"), EOH,
                    "> 2026 10 01 00 00  0.0000000  0  1", "G01  20000000.001",
                    "> 2026 10 01 00 00 15.0000000  5  1", hdr("G    2 C1C C2W", "SYS / # / OBS TYPES"),
                    "> 2026 10 01 00 00 30.0000000  0  1", "G01  20000000.002  20000003.003", width=None)
        from rinexcore import validate as V
        self.assertEqual([f.rule for f in V.errors(V.validate(src))], [])
        for t in ("3.05", "2.11"):
            with self.subTest(target=t):
                out, rep = conv(src, t)
                self.assertIn(b"20000003.003", out)
                self.assertEqual(problems(src, out, rep), [])

    def test_type_list_v2(self):
        """A flag-2 event's # / TYPES OF OBSERV holds for the epochs after it (RINEX 2)."""
        src = lines(hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM, *SITE,
                    hdr("     1     1", "WAVELENGTH FACT L1/2"), hdr("     1    C1", "# / TYPES OF OBSERV"), TFO, EOH,
                    " 26 10  1  0  0  0.0000000  0  1G 1", "  20000000.001",
                    " 26 10  1  0  0 15.0000000  2  1", hdr("     2    C1    P2", "# / TYPES OF OBSERV"),
                    " 26 10  1  0  0 30.0000000  0  1G 1", "  20000000.002  20000003.003")
        from rinexcore import validate as V
        self.assertEqual([f.rule for f in V.errors(V.validate(src))], [])
        for t in ("2.11", "3.05"):
            with self.subTest(target=t):
                out, rep = conv(src, t, name="test2740.26o", assume_phase_aligned=True)
                self.assertIn(b"20000003.003", out)
                self.assertEqual(problems(src, out, rep), [])


# ---------------------------------------------------------------------------------------------
# V1 (verify round): SYS / SCALE FACTOR records of one event are one group, as the header's
# ---------------------------------------------------------------------------------------------
# rinex305.txt Table A2 p.56: factor (1, 10, 100, 1000) to divide stored observations with,
# '0 or blank: all observation types'; section 6.5: a header record in an event holds until
# changed. 'A listed code beats its system's all-types factor' is an inference (the spec gives
# no precedence), applied to the header and to events alike. Values by hand: C1C
# 2200000.010 / 10 = 220000.001, L1C 1150000000.400 / 100 = 11500000.004 (no rounding).
SC_V3 = "G05" + F("   2200000.010") + F("1150000000.400")
SC_V2_LINE = (F("    220000.001") + F("  11500000.004")).rstrip()
ORDERS = {"listed first": ["G  100   1 L1C", "G   10"], "all first": ["G   10", "G  100   1 L1C"]}


def scale_src(where, recs):
    head = [hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
            SITE[0], MTYPE, *SITE[1:], hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"), TFO,
            hdr("G L1C  0.00000", "SYS / PHASE SHIFT")]
    if where == "header":
        head += [hdr(r, "SYS / SCALE FACTOR") for r in recs]
    ev = [">" + " " * 30 + "4%3d" % len(recs)] + [hdr(r, "SYS / SCALE FACTOR") for r in recs] \
        if where == "event" else []
    return lines(*head, EOH, *ev, "> 2026 10 01 00 00  0.0000000  0  1", SC_V3, width=None)


class ScaleFactorGroups(unittest.TestCase):
    def test_header_and_event_alike_in_both_orders(self):
        for name, recs in ORDERS.items():
            for where in ("header", "event"):
                with self.subTest(order=name, where=where):
                    src = scale_src(where, recs)
                    out, rep = conv(src, "2.11")
                    self.assertIn(("\n" + SC_V2_LINE + "\n").encode(), out)
                    self.assertFalse([k for k in rep["losses"] if k.startswith("scale")])
                    self.assertEqual(problems(src, out, rep), [])
                    # the round-31 event reading (L1 divided by 10, the later all-types record
                    # wiping L1C=100) must be caught
                    bad = swap(out, F("  11500000.004").rstrip().encode(), F(" 115000000.040").rstrip().encode())
                    self.assertTrue(problems(src, bad, rep))

    def test_event_group_replaces_or_adds(self):
        """After a header 'G 1000 1 C1C', an event 'G 100 1 L1C' changes L1C only (C1C keeps
        1000); an event that also has 'G 10' replaces every earlier G factor."""
        base = scale_src("event", ["G  100   1 L1C"]).replace(
            hdr("G L1C  0.00000", "SYS / PHASE SHIFT").encode(),
            hdr("G L1C  0.00000", "SYS / PHASE SHIFT").encode() + b"\n"
            + hdr("G 1000   1 C1C", "SYS / SCALE FACTOR").encode())
        out, rep = conv(base, "2.11")
        # C1C 2200000.010 / 1000 = 2200.00001 -> 2200.000 (rounding claimed)
        self.assertIn(("\n" + (F("      2200.000") + F("  11500000.004")).rstrip() + "\n").encode(), out)
        self.assertEqual(problems(base, out, rep), [])

    def test_v2_obs_scale_factor_event_group(self):
        src = swap(SC211, b"\n 26 10  1  0  0  0.0000000  0  1G 5",
                   b"\n 26 10  1  0  0  0.0000000  4  2\n"
                   + hdr("   100     1    L1", "OBS SCALE FACTOR").encode() + b"\n"
                   + hdr("    10     0", "OBS SCALE FACTOR").encode()
                   + b"\n 26 10  1  0  0  0.0000000  0  1G 5")
        for t in ("3.05", "2.11"):
            with self.subTest(target=t):
                out, rep = conv(src, t, name="test2740.26o", assume_phase_aligned=True)
                self.assertEqual(problems(src, out, rep), [])
        out, rep = conv(conv(src, "3.05", name="test2740.26o", assume_phase_aligned=True)[0], "2.11")
        # L1 1150000000.405 / 100 = 11500000.00405 -> 11500000.004 (rounding claimed)
        self.assertIn(b"  11500000.004", out)


# ---------------------------------------------------------------------------------------------
# V2 (verify round): a 3.02-3.05 code-only entry going to 3.01
# ---------------------------------------------------------------------------------------------
# rinex301.txt p.25: 3.01's one blank form (the system alone) says 'no observation pairs
# affected by phase shifts, or the applied corrections are not known'; a code without a value
# is no 3.01 form. PLAN section 3.3 rule 1: reference-only becomes blank for 3.01, reported.
class Phase30xCodeOnlyTo301(unittest.TestCase):
    def test_code_only(self):
        for v in ("3.02", "3.05"):
            with self.subTest(source=v):
                src = phase_src(v, ["G L1C"])
                out, rep = conv(src, "3.01")
                got = [l for l in out.decode().split("\n") if "PHASE SHIFT" in l]
                self.assertEqual(got, [hdr("G", "SYS / PHASE SHIFTS")])
                self.assertEqual({k: v["count"] for k, v in rep["losses"].items()},
                                 {"phase-shift-entry-dropped:G:L1C": 1})
                self.assertNotIn("phase-alignment", {a["category"] for a in rep["assumptions"]})
                self.assertEqual(problems(src, out, rep), [])
                old = swap(out, hdr("G", "SYS / PHASE SHIFTS").encode(), hdr("G L1C", "SYS / PHASE SHIFTS").encode())
                self.assertTrue(problems(src, old, rep))
                # read back, a 3.01 blank form is unknown, as any 3.01 input's is
                with self.assertRaises(MissingInformationError):
                    conv(out, "4.02")
                out4, rep4 = conv(out, "4.02", assume_phase_aligned=True)
                self.assertEqual(problems(out, out4, rep4), [])

    def test_zero_form_carried(self):
        src = phase_src("3.05", ["G L1C  0.00000", "G L2L  0.00000"])
        out, rep = conv(src, "3.01")
        self.assertIn((hdr("G L1C  0.00000", "SYS / PHASE SHIFTS") + "\n"
                       + hdr("G L2L  0.00000", "SYS / PHASE SHIFTS")).encode(), out)
        self.assertEqual(rep["losses"], {})
        out4, rep4 = conv(out, "4.02")          # 3.01 values: recorded, as a 3.01 input's
        self.assertEqual(problems(out, out4, rep4), [])


# ---------------------------------------------------------------------------------------------
# V3 (verify round): a RINEX 2 clock readable but not F12.9
# ---------------------------------------------------------------------------------------------
# rinex211.txt Table A2: receiver clock offset F12.9, columns 69-80. ' 123.4567890' (F12.7) is
# readable (the validator warns); it has no F12.9 or F15.12 (rinex305.txt Table A3) form.
class ClockAsWritten(unittest.TestCase):
    WIDE = " 123.4567890"
    SRC = swap(EV211, b"0  1G 1\n  20000000.001", b"0  1G 1" + b" " * 33 + WIDE.encode() + b"\n  20000000.001")

    def test_v2_to_v2_carried(self):
        for t in ("2.11", "2.10"):
            with self.subTest(target=t):
                out, rep = conv(self.SRC, t, name="test2740.26o")
                self.assertIn(b"0  1G 1" + b" " * 33 + self.WIDE.encode() + b"\n", out)
                self.assertEqual(rep["losses"], {})
                self.assertIn("OBS.CLOCK.NOT-F12.9", [w["rule"] for w in rep["warnings"]])
                self.assertEqual(problems(self.SRC, out, rep), [])

    def test_strict_refuses(self):
        with self.assertRaises(CorruptError):
            conv(self.SRC, "2.11", name="test2740.26o", strict=True)

    def test_crx_plain(self):
        outs = convert_data(self.SRC, "test2740.26o", Options("2.11", crx=True, compression="none"))
        rep = outs[0].report.to_dict()
        self.assertIn("OBS.CRX.CLOCK-PLAIN", [w["rule"] for w in rep["warnings"]])
        self.assertIn(self.WIDE.encode(), outs[0].data)

    def test_no_room_is_overflow(self):
        out, rep = conv(self.SRC, "3.05", name="test2740.26o")     # no F15.12 form
        self.assertEqual({k: v["count"] for k, v in rep["losses"].items()}, {"clock-overflow": 1})
        self.assertEqual(problems(self.SRC, out, rep), [])
        v3 = swap(EV305, b"> 2026 10 01 00 00  0.0000000  0  1\n",
                  b"> 2026 10 01 00 00  0.0000000  0  1        123.456789012\n")
        out, rep = conv(v3, "2.11", lenient=True)             # 13 digits: no 12-column form
        self.assertEqual(rep["losses"].get("clock-overflow", {}).get("count"), 1)
        self.assertEqual(problems(v3, out, rep), [])
        # a carried clock dropped instead is caught
        out, rep = conv(self.SRC, "2.11", name="test2740.26o")
        rep = copy.deepcopy(rep)
        rep["losses"]["clock-overflow"] = {"count": 1, "detail": {}}
        self.assertTrue(problems(self.SRC, swap(out, self.WIDE.encode() + b"\n", b"\n"), rep))


# ---------------------------------------------------------------------------------------------
# Verify round (checks): the confirmed attribute defaults and collapse priority are checked
# ---------------------------------------------------------------------------------------------
# docs/DECISIONS.md 'Policy defaults' (confirmed 2026-11-01, answer 7): GPS P1->C1W, L2->L2W ...;
# RINEX 3 -> 2 GPS band 1 C>W>P>Y. tests/independent/attribute_defaults.json holds them.
class ConfirmedCodePolicies(unittest.TestCase):
    def test_wrong_default_in_output_and_report(self):
        from .test_obs_fixtures import V211
        out, rep = conv(V211, "3.00", name="test2740.26o", drop_unresolvable=True)
        flags = {"drop_unresolvable": True}
        self.assertEqual(problems(V211, out, rep, flags), [])
        for sysc, v2, good, bad in (("G", "L2", "L2W", "L2C"), ("G", "P1", "C1W", "C1P"), ("G", "S2", "S2W", "S2C")):
            with self.subTest(change=(v2, bad)):
                mut = copy.deepcopy(rep)
                a = next(x for x in mut["assumptions"] if x["category"] == f"obs-code-attribute:{sysc}"
                         and x["detail"] == f"{v2}->{good}")
                a["detail"] = f"{v2}->{bad}"
                self.assertTrue(problems(V211, out.replace(f" {good}".encode(), f" {bad}".encode(), 1), mut, flags))
        # an override is the user's choice: not held to the table
        out, rep = conv(V211, "3.00", name="test2740.26o", drop_unresolvable=True, overrides={"G:L2": "L2L"})
        self.assertIn(b" L2L", out)
        self.assertEqual(problems(V211, out, rep, flags), [])

    def test_collapse_priority(self):
        src = lines(
            hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"), PGM,
            SITE[0], MTYPE, *SITE[1:], hdr("G    3 C1C L1C L1W", "SYS / # / OBS TYPES"), TFO,
            hdr("G L1C  0.00000", "SYS / PHASE SHIFT"), EOH,
            "> 2026 10 01 00 00  0.0000000  0  1",
            "G05" + F("  22000000.105") + F(" 115000000.405") + F(" 115000000.888"), width=None)
        out, rep = conv(src, "2.11")
        self.assertIn(b"  22000000.105   115000000.405", out)            # L1 from L1C (C before W)
        self.assertEqual(rep["losses"]["obs-code-collapsed:G:L1W"]["count"], 1)
        self.assertEqual(problems(src, out, rep), [])
        # the other column kept, the claim renamed to match: consistent, but not the policy
        bad = swap(out, b" 115000000.405", b" 115000000.888")
        mut = copy.deepcopy(rep)
        mut["losses"]["obs-code-collapsed:G:L1C"] = mut["losses"].pop("obs-code-collapsed:G:L1W")
        p = compare_obs(src, bad, mut)
        self.assertTrue(any("confirmed" in x for x in p), p)


if __name__ == "__main__":
    unittest.main()
