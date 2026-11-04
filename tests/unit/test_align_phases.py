"""--align-phases (the user's decision of 2026-11-02, "old versions only"; PLAN section 3.3 rules
2-4; docs/PHASE_ALIGNMENT.md).

Expected values are written here by hand from the shift tables (3.02 Table A19 p.80-82; 3.03-3.05
Table A23: rinex303.txt p.92-94, rinex304.txt p.97-100, rinex305.txt p.88-91): phiRINEX = phi
original + delta-phi. Every conversion is also run through the independent checker, and the
mutations show it catches a shift left out, a shift without its claim and a wrong record.
"""

import contextlib
import copy
import io
import os
import shutil
import tempfile
import unittest

from rinexconv.cli import main as cli_main
from rinexconv.engine import Options, convert_data
from rinexcore.errors import InvocationError, MissingInformationError
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines

PGM = hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE")
SITE = [hdr("TEST", "MARKER NAME"), hdr("ME                  US", "OBSERVER / AGENCY"),
        hdr("1                   REC                 1", "REC # / TYPE / VERS"),
        hdr("1                   ANT", "ANT # / TYPE"),
        hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ"),
        hdr("        0.0000        0.0000        0.0000", "ANTENNA: DELTA H/E/N")]
EOH = hdr("", "END OF HEADER")


def tfo(ts="GPS"):
    return hdr(f"  2026    10     1     0     0    0.0000000     {ts}", "TIME OF FIRST OBS")


def conv(src, target, name="x.rnx", **kw):
    kw.setdefault("compression", "none")
    outs = convert_data(src, name, Options(target, align_phases=True, **kw))
    return outs[0].data, outs[0].report.to_dict()


def problems(src, out, rep):
    return compare_obs(src, out, rep) + [f"loss not allowed: {x}" for x in allowed_check(rep)]


def phase_lines(out):
    return [l[:60].rstrip() for l in out.decode("latin-1").split("\n") if "SYS / PHASE SHIFT" in l[60:]]


def norms(rep):
    return {k: v for k, v in rep["normalisations"].items() if k.startswith("phase-shift-")}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fcn = os.path.join(self.tmp, "fcn.txt")
        with open(self.fcn, "wb") as fh:
            fh.write(b"R07 5\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# --- RINEX 2.11, GPS + GLONASS -------------------------------------------------------------------
def v211(types, g, r):
    n = len(types.split())
    return lines(hdr("     2.11           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"), PGM, *SITE,
                 hdr("     1     1", "WAVELENGTH FACT L1/2"), hdr(f"{n:6d}" + "".join(f"    {c}" for c in types.split()),
                                                                   "# / TYPES OF OBSERV"),
                 tfo(), EOH, " 26 10  1  0  0  0.0000000  0  2G05R07", "".join(g).rstrip(), "".join(r).rstrip())


G5 = [F("  22000000.105"), F("  22000001.205"), F("  22000002.305"), F(" 115000000.405"), F("  89000000.505")]
R5 = [F("  19000000.107"), F("  19000001.207"), F("  19000002.307"), F(" 101000000.407"), F("  78000000.507")]


STATED = {"G:L1": "L1C", "G:L2": "L2W", "R:L1": "L1C", "R:L2": "L2P"}


class FromRinex2(Tmp):
    """A RINEX 2 code names no tracking mode, and the tables' shifts differ between the modes an
    L1 or L2 phase could be (GPS L1: C 0, W/P +1/4; GPS L2: W 0, X -1/4, C by block; GLONASS:
    C 0, P +1/4), so the converter's default attribute may not decide a shift: refused unless
    --overrides states it (review round 39; PLAN section 1 clause 8)."""

    def test_refused_without_stated_attributes(self):
        for types, names in (("C1 P1 P2 L1 L2", ["G L1", "G L2", "R L1", "R L2"]),
                             ("C1 C2 L1 L2", ["G L2 (written L2X", "R L2 (written L2C"])):
            g = G5[:len(types.split())]
            r = R5[:len(types.split())]
            with self.subTest(types=types):
                with self.assertRaises(MissingInformationError) as cm:
                    conv(v211(types, g, r), "3.05", name="test2740.26o", glo_fcn=self.fcn)
                for n in names:
                    self.assertIn(n, str(cm.exception))
                self.assertIn('--overrides FILE', str(cm.exception))
                self.assertIn('"G:L2": ', str(cm.exception))

    def test_checker_catches_a_guessed_shift(self):
        """The round-38 output (GLONASS L2 shifted +1/4 by the default L2P) fails the checker."""
        src = v211("C1 P1 P2 L1 L2", G5, R5)
        out, rep = conv(src, "3.05", name="test2740.26o", glo_fcn=self.fcn, overrides=STATED)
        guessed = copy.deepcopy(rep)
        for a in guessed["assumptions"]:
            if a["category"].startswith("obs-code-attribute:") and a["source"] == "override":
                a["source"] = "table"
        self.assertTrue(any("guessed" in x for x in compare_obs(src, out, guessed)))

    def test_defaults(self):
        """C1 P1 P2 L1 L2 with the attributes stated: GPS L1C (reference) and L2W ('None'): no
        shift, the code-only form; GLONASS L1C (reference), L2P +1/4."""
        src = v211("C1 P1 P2 L1 L2", G5, R5)
        for t in ("3.05", "3.02"):
            with self.subTest(target=t):
                out, rep = conv(src, t, name="test2740.26o", glo_fcn=self.fcn, overrides=STATED)
                self.assertIn(hdr("G    5 C1C C1W C2W L1C L2W", "SYS / # / OBS TYPES").encode(), out)
                self.assertIn(hdr("R    5 C1C C1P C2P L1C L2P", "SYS / # / OBS TYPES").encode(), out)
                self.assertEqual(phase_lines(out), ["G L1C", "G L2W", "R L2P  0.25000"])
                self.assertIn(("\nG05" + "".join(G5)).rstrip().encode() + b"\n", out)
                r7 = R5[:4] + [F("  78000000.757")]
                self.assertIn(("\nR07" + "".join(r7)).rstrip().encode() + b"\n", out)
                self.assertEqual(norms(rep), {"phase-shift-applied:R:L2P:+0.25": 1})
                self.assertEqual({a["detail"] for a in rep["assumptions"] if a["category"] == "phase-alignment"},
                                 {"G", "R"})
                self.assertIn(f"OBS.PHASE.ALIGN-{'A19' if t == '3.02' else 'A23'}-{t}", rep["rules"])
                self.assertEqual(problems(src, out, rep), [])
                # mutations: the shift left out; the claim deleted; the record of another table value
                self.assertTrue(problems(src, out.replace(b"78000000.757", b"78000000.507"), rep))
                quiet = copy.deepcopy(rep)
                quiet["normalisations"] = {}
                self.assertTrue(compare_obs(src, out, quiet))
                self.assertTrue(problems(src, out.replace(b"R L2P  0.25000", b"R L2P -0.25000"), rep))

    def test_l2_follows_code(self):
        """C1 C2 L1 L2, no P2 (an L2C receiver), the attributes stated: GPS L2X (-1/4), GLONASS
        L2C (reference)."""
        g = [F("  22000000.105"), F("  22000001.205"), F(" 115000000.405"), F("  89000000.505")]
        r = [F("  19000000.107"), F("  19000001.207"), F(" 101000000.407"), F("  78000000.507")]
        src = v211("C1 C2 L1 L2", g, r)
        out, rep = conv(src, "3.05", name="test2740.26o", glo_fcn=self.fcn,
                        overrides={"G:L1": "L1C", "G:L2": "L2X", "R:L1": "L1C", "R:L2": "L2C"})
        self.assertEqual(phase_lines(out), ["G L2X -0.25000", "R L1C", "R L2C"])
        self.assertIn(("\nG05" + "".join(g[:3] + [F("  89000000.255")])).rstrip().encode() + b"\n", out)
        self.assertEqual(norms(rep), {"phase-shift-applied:G:L2X:-0.25": 1})
        self.assertEqual(problems(src, out, rep), [])

    def test_override_to_l1p(self):
        """--overrides R:L1 -> L1P (the user's): GLONASS L1P +1/4 too."""
        src = v211("C1 P1 P2 L1 L2", G5, R5)
        out, rep = conv(src, "3.05", name="test2740.26o", glo_fcn=self.fcn, overrides={**STATED, "R:L1": "L1P"})
        self.assertEqual(phase_lines(out), ["G L1C", "G L2W", "R L1P  0.25000", "R L2P  0.25000"])
        r7 = R5[:3] + [F(" 101000000.657"), F("  78000000.757")]
        self.assertIn(("\nR07" + "".join(r7)).rstrip().encode() + b"\n", out)
        self.assertEqual(problems(src, out, rep), [])


# --- RINEX 3 sources -----------------------------------------------------------------------------
def v3(version, letter, types, recs, data, extra=(), ts="GPS"):
    return lines(hdr(f"{version:>9s}           OBSERVATION DATA    {letter}", "RINEX VERSION / TYPE"), PGM,
                 SITE[0], hdr("GEODETIC", "MARKER TYPE"), *SITE[1:],
                 *[hdr(t, "SYS / # / OBS TYPES") for t in types], tfo(ts),
                 *[hdr(x, "SYS / PHASE SHIFTS" if version == "3.01" else "SYS / PHASE SHIFT") for x in recs],
                 *extra, EOH, "> 2026 10 01 00 00  0.0000000  0  %d" % len(data), *[d.rstrip() for d in data],
                 width=None)


E11 = "E11" + F("  23000000.111") + F(" 115000000.405") + F("  23000002.333") + F("  86000000.505")
GAL300 = v3("3.00", "E", ["E    4 C1C L1C C5Q L5Q"], [], [E11], ts="GAL")


class Galileo300(unittest.TestCase):
    def test_every_table(self):
        """E1 L1C +1/2, E5a L5Q -1/4 in every 3.02-3.05 table."""
        want = "E11" + F("  23000000.111") + F(" 115000000.905") + F("  23000002.333") + F("  86000000.255")
        for t in ("3.02", "3.03", "3.04", "3.05"):
            with self.subTest(target=t):
                out, rep = conv(GAL300, t)
                self.assertEqual(phase_lines(out), ["E L1C  0.50000", "E L5Q -0.25000"])
                self.assertIn(("\n" + want.rstrip() + "\n").encode(), out)
                self.assertEqual(norms(rep), {"phase-shift-applied:E:L1C:+0.5": 1,
                                              "phase-shift-applied:E:L5Q:-0.25": 1})
                self.assertEqual(problems(GAL300, out, rep), [])

    def test_round_trip(self):
        """3.00 -> 3.05 --align-phases -> 3.00 --align-phases: the recorded shifts are undone
        (rule 3), so the original values come back (PLAN 3.3: a round-trip fixture per path)."""
        out, rep = conv(GAL300, "3.05")
        back, rep2 = conv(out, "3.00")
        self.assertEqual(back.split(b"END OF HEADER")[1], GAL300.split(b"END OF HEADER")[1])
        self.assertEqual(norms(rep2), {"phase-shift-removed:E:L1C:+0.5": 1, "phase-shift-removed:E:L5Q:-0.25": 1})
        self.assertEqual(problems(out, back, rep2), [])
        self.assertTrue(problems(out, back.replace(b"115000000.405", b"115000000.905"), rep2))


class ScaledAndEvents(unittest.TestCase):
    def test_scale_factor(self):
        """A stored value is divided by its SYS / SCALE FACTOR before use (rinex305.txt Table A2):
        L1C stored x10, so +1/2 cycle is +5 in the stored value."""
        e = "E11" + F("  23000000.111") + F("1150000004.050") + F("  23000002.333") + F("  86000000.505")
        src = v3("3.00", "E", ["E    4 C1C L1C C5Q L5Q"], [], [e], ts="GAL",
                 extra=[hdr("E   10   1 L1C", "SYS / SCALE FACTOR")])
        out, rep = conv(src, "3.05")
        want = "E11" + F("  23000000.111") + F("1150000009.050") + F("  23000002.333") + F("  86000000.255")
        self.assertIn(("\n" + want.rstrip() + "\n").encode(), out)
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(problems(src, out.replace(b"1150000009.050", b"1150000004.550"), rep))

    def test_phase_record_in_an_event_refused(self):
        g = "G05" + F("  22000000.105") + F(" 115000000.405")
        src = v3("3.02", "G", ["G    2 C1C L1C"], ["G"], [g]).replace(
            b"> 2026 10 01 00 00  0.0000000  0  1",
            (">                              4  1\n" + hdr("G L1C", "SYS / PHASE SHIFT")
             + "\n> 2026 10 01 00 00  0.0000000  0  1").encode())
        with self.assertRaises(InvocationError):
            conv(src, "3.05")


class GlonassL3QTables(Tmp):
    """GLONASS G3 L3Q: -1/4 in 3.02 and 3.03, +1/4 in 3.04, 'must be aligned to L3I' (no value)
    in 3.05 (docs/PHASE_ALIGNMENT.md section 4 item 3)."""
    R07 = "R07" + F("  19000000.107") + F(" 101000000.407") + F("  19000003.333") + F(" 120000000.123")
    SRC = v3("3.02", "R", ["R    4 C1C L1C C3Q L3Q"], ["R"], [R07],
             extra=[hdr("  1 R07  5", "GLONASS SLOT / FRQ #"), hdr("", "GLONASS COD/PHS/BIS")])

    def test_versions(self):
        for t, rec, val, d in (("3.02", "R L3Q -0.25000", " 119999999.873", "-0.25"),
                               ("3.03", "R L3Q -0.25000", " 119999999.873", "-0.25"),
                               ("3.04", "R L3Q  0.25000", " 120000000.373", "+0.25")):
            with self.subTest(target=t):
                out, rep = conv(self.SRC, t)
                self.assertEqual(phase_lines(out), [rec])
                self.assertIn(("\n" + self.R07[:51] + F(val)).rstrip().encode() + b"\n", out)
                self.assertEqual(norms(rep), {f"phase-shift-applied:R:L3Q:{d}": 1})
                self.assertEqual(problems(self.SRC, out, rep), [])
        with self.assertRaises(MissingInformationError) as cm:
            conv(self.SRC, "3.05")
        self.assertIn("R L3Q", str(cm.exception))


class Refusals(unittest.TestCase):
    def check_missing(self, src, target, names):
        with self.assertRaises(MissingInformationError) as cm:
            conv(src, target)
        for n in names:
            self.assertIn(n, str(cm.exception))
        self.assertEqual(cm.exception.outcome, "refused-missing-information")

    def test_no_table_value(self):
        g = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000003.305") + F("  89000000.505")
        # GPS L5X 'must be aligned to L5I' (no value); GPS L2C depends on the satellite block
        self.check_missing(v3("3.00", "G", ["G    4 C1C L1C C5X L5X"], [], [g]), "3.05", ["G L5X"])
        self.check_missing(v3("3.00", "G", ["G    4 C1C L1C C2C L2C"], [], [g]), "3.03", ["G L2C"])
        # both named at once (no partial alignment)
        self.check_missing(v3("3.00", "G", ["G    4 C1C L2C C5X L5X"], [], [g]), "3.05", ["G L2C", "G L5X"])
        # SBAS is in no table
        s = "S27" + F("  38000000.105") + F(" 200000000.405")
        self.check_missing(v3("3.02", "S", ["S    2 C1C L1C"], ["S"], [s]), "3.05", ["S L1C"])

    def test_bds3_preliminary_rows(self):
        """3.04 prints BDS-3 L1P/L5P/L7P/L8P '+1/4 (preliminary)' (Table A23 p.99); 3.05 withdrew
        them, 'the 1/4 cycle alignment direction is implementation dependent' (rinex305.txt
        history p.10): treated as rows without a value (the user's decision, 2026-11-02)."""
        c = "C30" + F("  21000000.105") + F(" 109000000.405") + F("  21000001.205") + F(" 109000001.405") \
            + F("  21000002.305") + F(" 110000000.505")
        src = v3("3.04", "C", ["C    6 C2I L2I C1P L1P C7P L7P"], ["C"], [c], ts="BDT")
        for t in ("3.04", "3.05"):
            with self.subTest(target=t):
                self.check_missing(src, t, ["C L1P", "C L7P"])
        b1i = v3("3.04", "C", ["C    2 C2I L2I"], ["C"], [c[:35]], ts="BDT")
        out, rep = conv(b1i, "3.04")
        self.assertEqual(phase_lines(out), ["C L2I"])           # reference signal only
        self.assertEqual(problems(b1i, out, rep), [])

    def test_qzss_l1s(self):
        """QZSS L1S: 'None' in 3.02/3.03, block-dependent in 3.04/3.05 (Note 5)."""
        g = "G05" + F("  22000000.105") + F(" 115000000.405")
        j = "J02" + F("  37000000.105") + F(" 195000000.405")
        src = v3("3.02", "M", ["G    2 C1C L1C", "J    2 C1S L1S"], ["G", "J"], [g, j])
        out, rep = conv(src, "3.03")
        self.assertEqual(phase_lines(out), ["G L1C", "J L1S"])
        self.assertEqual(norms(rep), {})
        self.assertEqual(problems(src, out, rep), [])
        self.check_missing(src, "3.05", ["J L1S"])

    def test_invocation(self):
        for t in ("4.02", "4.00", "3.01", "2.11", "2.10"):
            with self.subTest(target=t):
                with self.assertRaises(InvocationError):
                    conv(GAL300, t)
        with self.assertRaises(InvocationError):
            conv(GAL300, "3.05", assume_phase_aligned=True)

    def test_applied_values_never_twice(self):
        """PLAN 3.3 rule 4: a record of applied corrections contradicts 'the source is unaligned'."""
        g = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000003.305") + F("  89000000.255")
        src = v3("3.05", "G", ["G    4 C1C L1C C2X L2X"], ["G L2X -0.25000"], [g])
        with self.assertRaises(InvocationError) as cm:
            conv(src, "3.05")
        self.assertIn("twice", str(cm.exception))


class UndoTo300(unittest.TestCase):
    """PLAN 3.3 rule 3: to 3.00 ('not corrected', rinex300.txt p.7) only the corrections a
    record says were applied are removed: phi original = phiRINEX - delta-phi."""
    G = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000003.305") + F("  89000000.255")

    def test_applied_removed(self):
        src = v3("3.05", "G", ["G    4 C1C L1C C2X L2X"], ["G L1C", "G L2X -0.25000"], [self.G])
        out, rep = conv(src, "3.00")
        want = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000003.305") + F("  89000000.505")
        self.assertIn(("\n" + want.rstrip() + "\n").encode(), out)
        self.assertNotIn(b"PHASE SHIFT", out)
        self.assertEqual(norms(rep), {"phase-shift-removed:G:L2X:-0.25": 1})
        # the L2X entry is undone (in the data now); only 'G L1C' has no 3.00 form (review round 39)
        self.assertEqual(rep["losses"]["phase-shift-record-not-representable"]["count"], 1)
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(problems(src, out.replace(b"89000000.505", b"89000000.255"), rep))
        more = copy.deepcopy(rep)
        more["losses"]["phase-shift-record-not-representable"]["count"] = 2
        self.assertTrue(compare_obs(src, out, more))

    def test_two_values_for_one_satellite(self):
        """Every entry counts, zeros too, per satellite: G12 given -1/4 and 0 is refused, in
        either order (review round 39: the zero was dropped and G12 shifted)."""
        g12 = "G12" + self.G[3:]
        for recs, sat in ((["G L2X -0.25000", "G L2X  0.00000  01 G12"], "G12"),
                          (["G L2X  0.00000  01 G12", "G L2X -0.25000"], "G12"),
                          (["G L2X -0.25000  01 G05", "G L2X  0.00000  01 G05"], "G05")):
            with self.subTest(record=recs):
                src = v3("3.05", "G", ["G    4 C1C L1C C2X L2X"], recs, [self.G, g12])
                with self.assertRaises(MissingInformationError) as cm:
                    conv(src, "3.00")
                self.assertIn(f"G L2X {sat}", str(cm.exception))

    def test_disjoint_lists(self):
        """BAUT/BRMG style ('C L2I .00000 1 C02' and 'C L2I .50000 34 ...'; 3.00 has no BeiDou,
        so shown with GPS): lists that cover no satellite twice are fine: G02 unchanged, G05
        and G10 lose their +1/2."""
        g = [s + F("  22000000.105") + F(" 115000000.905") for s in ("G02", "G05", "G10")]
        src = v3("3.05", "G", ["G    2 C1C L1C"], ["G L1C  0.00000  01 G02", "G L1C  0.50000  02 G05 G10"], g)
        out, rep = conv(src, "3.00")
        self.assertIn(("\n" + g[0].rstrip() + "\n").encode(), out)
        for s in ("G05", "G10"):
            self.assertIn(("\n" + s + F("  22000000.105") + F(" 115000000.405")).rstrip().encode() + b"\n", out)
        self.assertEqual(norms(rep), {"phase-shift-removed:G:L1C:+0.5": 2})
        self.assertEqual(problems(src, out, rep), [])

    def test_code_without_column(self):
        """A correction for a code the file has no observations of: reported, still a lost entry."""
        src = v3("3.05", "G", ["G    4 C1C L1C C2X L2X"], ["G L2X -0.25000", "G L2L -0.25000"], [self.G])
        out, rep = conv(src, "3.00")
        self.assertIn("OBS.PHASE.ALIGN-NO-COLUMN", [w["rule"] for w in rep["warnings"]])
        self.assertEqual(rep["losses"]["phase-shift-record-not-representable"]["count"], 1)
        self.assertEqual(problems(src, out, rep), [])

    def test_satellite_list(self):
        g12 = "G12" + self.G[3:]
        src = v3("3.05", "G", ["G    4 C1C L1C C2X L2X"], ["G L2X -0.25000  01 G12"], [self.G, g12])
        out, rep = conv(src, "3.00")
        self.assertIn(("\n" + self.G.rstrip() + "\n").encode(), out)             # G05 not listed
        self.assertIn(b"\nG12" + self.G[3:-16].encode() + b"  89000000.505\n", out)
        self.assertEqual(norms(rep), {"phase-shift-removed:G:L2X:-0.25": 1})
        self.assertEqual(problems(src, out, rep), [])

    def test_nothing_to_undo(self):
        for recs in (["G L1C  0.00000", "G L2X  0.00000"], ["G L1C"], ["G"]):
            with self.subTest(record=recs):
                src = v3("3.05", "G", ["G    4 C1C L1C C2X L2X"], recs, [self.G])
                out, rep = conv(src, "3.00")
                self.assertIn(("\n" + self.G.rstrip() + "\n").encode(), out)
                self.assertEqual(norms(rep), {})
                self.assertIn("OBS.PHASE.ALIGN-NOTHING-TO-UNDO", [w["rule"] for w in rep["warnings"]])
                self.assertEqual(problems(src, out, rep), [])


class NothingToDo(unittest.TestCase):
    def test_all_aligned(self):
        """Every system already aligned (a 3.02+ zero form): nothing shifted, a warning says so."""
        g = "G05" + F("  22000000.105") + F(" 115000000.405")
        src = v3("3.05", "G", ["G    2 C1C L1C"], ["G L1C  0.00000"], [g])
        out, rep = conv(src, "3.04")
        self.assertIn("OBS.PHASE.ALIGN-NOTHING-TO-DO", [w["rule"] for w in rep["warnings"]])
        self.assertEqual(phase_lines(out), ["G L1C  0.00000"])
        self.assertEqual(norms(rep), {})
        self.assertEqual(problems(src, out, rep), [])


class Cli(Tmp):
    def run_cli(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = cli_main(list(args) + ["--out", os.path.join(self.tmp, "out"), "--no-auto-nav", "--force"])
        return rc, err.getvalue()

    def test_exit_codes(self):
        p = os.path.join(self.tmp, "GAL300.rnx")
        with open(p, "wb") as fh:
            fh.write(GAL300)
        self.assertEqual(self.run_cli(p, "--to", "3.05", "--align-phases")[0], 0)
        self.assertEqual(self.run_cli(p, "--to", "4.02", "--align-phases")[0], 2)
        self.assertEqual(self.run_cli(p, "--to", "3.05", "--align-phases", "--assume-phase-aligned")[0], 2)
        q = os.path.join(self.tmp, "L5X.rnx")
        g = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000003.305") + F("  89000000.505")
        with open(q, "wb") as fh:
            fh.write(v3("3.00", "G", ["G    4 C1C L1C C5X L5X"], [], [g]))
        self.assertEqual(self.run_cli(q, "--to", "3.05", "--align-phases")[0], 3)


class AstraRound39(unittest.TestCase):
    """Codex Astra's review of --align-phases (round 39): undone accounting, precision,
    overflow, non-finite numbers."""
    G5 = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000003.305") + F("  89000000.255")

    def test_entry_without_observations_is_lost(self):
        """A2: 'G L2X -0.25000  01 G12' with observations of G05 only changes no value: the
        entry is not undone, so it is claimed lost, with nothing shifted."""
        src = v3("3.05", "G", ["G    4 C1C L1C C2X L2X"], ["G L2X -0.25000  01 G12"], [self.G5])
        out, rep = conv(src, "3.00")
        self.assertEqual(norms(rep), {})
        self.assertEqual(rep["losses"]["phase-shift-record-not-representable"]["count"], 1)
        self.assertEqual(problems(src, out, rep), [])
        none = copy.deepcopy(rep)
        del none["losses"]["phase-shift-record-not-representable"]
        self.assertTrue(compare_obs(src, out, none))

    def test_entry_of_a_dropped_column_is_lost(self):
        """A2: 3.00 has no GLONASS L3Q (rinex300.txt Table A1 p.28): its correction changes no
        value the output keeps; the L2P one is undone."""
        r = "R07" + F("  19000000.107") + F(" 101000000.407") + F("  19000003.333") + F(" 120000000.373") \
            + F("  19000004.444") + F("  78000000.757")
        src = v3("3.05", "R", ["R    6 C1C L1C C3Q L3Q C2P L2P"], ["R L3Q  0.25000", "R L2P  0.25000"], [r],
                 extra=[hdr("  1 R07  5", "GLONASS SLOT / FRQ #"), hdr("", "GLONASS COD/PHS/BIS")])
        out, rep = conv(src, "3.00")
        self.assertEqual(norms(rep), {"phase-shift-removed:R:L2P:+0.25": 1})
        self.assertEqual(rep["losses"]["phase-shift-record-not-representable"]["count"], 1)
        self.assertIn(b"  78000000.507", out)
        self.assertEqual(problems(src, out, rep), [])

    def test_unalign_rounds_to_3_decimals(self):
        """A3: F8.5 corrections give 5 decimals; F14.3 holds 3. Where no SYS / SCALE FACTOR
        holds the value (verify round V1: x10 already overflows F14.3), half-even, claimed."""
        g = "G05" + F("  22000000.105") + F("1150000000.000")
        src = v3("3.05", "G", ["G    2 C1W L1W"], ["G L1W  0.12345"], [g])
        out, rep = conv(src, "3.00")
        self.assertIn(b"G05  22000000.105  1149999999.877\n", out)      # 1149999999.87655 -> .877
        self.assertNotIn(b"SCALE FACTOR", out)
        self.assertNotIn("OBS.PHASE.UNALIGN-SCALE", rep["rules"])
        self.assertEqual(rep["losses"]["phase-unalign-precision:G:L1W"]["count"], 1)
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(problems(src, out.replace(b"1149999999.877", b"1149999999.876"), rep))
        quiet = copy.deepcopy(rep)
        del quiet["losses"]["phase-unalign-precision:G:L1W"]
        self.assertTrue(compare_obs(src, out, quiet))

    def test_overflow_clipped(self):
        """A4: 'Phase values overflowing the fixed format F14.3 have to be clipped into the
        valid interval (e.g add or subtract 10**9), set bit 0 of LLI indicator' (rinex305.txt
        section 6.7 p.43): -999999999.900 - 1/4 = -1000000000.150 -> -0.150, LLI 1."""
        g = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000005.555") + F("-999999999.900")
        src = v3("3.00", "G", ["G    4 C1C L1C C5Q L5Q"], [], [g])
        out, rep = conv(src, "3.05")
        want = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000005.555") + F("        -0.150", "1")
        self.assertIn(("\n" + want.rstrip() + "\n").encode(), out)
        self.assertEqual(norms(rep), {"phase-shift-applied:G:L5Q:-0.25": 1, "phase-shift-clipped:G:L5Q": 1})
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(problems(src, out.replace(b"        -0.1501", b"        -0.150 "), rep))

    def test_non_finite_numbers_refused(self):
        """A5: 'sNaN', 'NaN' or 'Infinity' in SYS / PHASE SHIFT's F8.5 is no number: refused-corrupt,
        located (it raised decimal.InvalidOperation); the same in SYS / SCALE FACTOR's I4."""
        from rinexcore.errors import CorruptError
        g = "G05" + F("  22000000.105") + F(" 115000000.405")
        for val in ("    sNaN", "     NaN", "Infinity"):
            with self.subTest(value=val):
                src = v3("3.05", "G", ["G    2 C1C L1C"], ["G L1C " + val], [g])
                for t in ("3.05", "3.00"):
                    with self.assertRaises(CorruptError) as cm:
                        convert_data(src, "x.rnx", Options(t, compression="none"))
                    self.assertEqual(cm.exception.rule, "HDR.PHASESHIFT")
        src = v3("3.05", "G", ["G    2 C1C L1C"], ["G L1C  0.00000"], [g], extra=[hdr("G  NaN", "SYS / SCALE FACTOR")])
        with self.assertRaises(CorruptError) as cm:
            convert_data(src, "x.rnx", Options("2.11", compression="none"))
        self.assertEqual(cm.exception.rule, "HDR.SCALE")


def _event(*records, flag=4):
    """A flag 2-5 event line (flag 5, an external event, with its epoch) and its header records
    (no trailing newline)."""
    head = "> 2026 10 01 00 00 15.0000000  5" if flag == 5 else ">" + " " * 30 + str(flag)
    return head + "%3d" % len(records) + "".join("\n" + r for r in records)


class AstraVerifyV1(unittest.TestCase):
    """Verify round V1: to 3.00 a value less its recorded correction (F8.5: 5 decimals) is kept
    exactly where an allowed SYS / SCALE FACTOR (1, 10, 100, 1000: rinex300.txt Table A1 p.28;
    'to increase resolution', section 5.5 p.12) holds it: the smallest such factor per system,
    code and scope (header or event), times the source's factor, written as SYS / SCALE FACTOR
    in that place, the values counted as rule OBS.PHASE.UNALIGN-SCALE; only where none does
    are they rounded (and claimed: AstraRound39.test_unalign_rounds_to_3_decimals).

    A product of 1000 never arises from a valid file: a correction times a source factor of 10
    has at most 4 decimals, so x10 holds it (10 x 10 = 100); a source factor of 100 or 1000
    already holds all 5 at 3 decimals. The largest factor this writes is 100."""

    def run_case(self, recs, val, extra=(), types=("G    2 C1W L1W",)):
        g = "G05" + F("  22000000.105") + F(val)
        src = v3("3.05", "G", list(types), recs, [g], extra=extra)
        out, rep = conv(src, "3.00")
        return src, out, rep

    @staticmethod
    def scale_lines(out):
        return [l[:60].rstrip() for l in out.decode("latin-1").split("\n") if "SYS / SCALE FACTOR" in l[60:]]

    def test_five_decimals_factor_100(self):
        """0.12345: 100000000.000 - 0.12345 = 99999999.87655, stored x100 = 9999999987.655."""
        src, out, rep = self.run_case(["G L1W  0.12345"], " 100000000.000")
        self.assertEqual(self.scale_lines(out), ["G  100   1 L1W"])
        self.assertIn(b"\nG05  22000000.105  9999999987.655\n", out)
        self.assertEqual(norms(rep), {"phase-shift-removed:G:L1W:+0.12345": 1})
        self.assertEqual(rep["rules"]["OBS.PHASE.UNALIGN-SCALE"]["count"], 1)
        self.assertFalse([k for k in rep["losses"] if k.startswith("phase-unalign-precision")])
        self.assertEqual(problems(src, out, rep), [])
        # mutations: the wrong factor; the value rounded instead (Astra round 39's output), with
        # its claim; a precision claim on the exact output; the rule's count left out
        self.assertTrue(compare_obs(src, out.replace(b"G  100   1 L1W", b"G   10   1 L1W"), rep))
        rounded = copy.deepcopy(rep)
        rounded["losses"]["phase-unalign-precision:G:L1W"] = {"count": 1}
        del rounded["rules"]["OBS.PHASE.UNALIGN-SCALE"]
        old = out.replace(hdr("G  100   1 L1W", "SYS / SCALE FACTOR").encode() + b"\n", b"").replace(
            b"9999999987.655", b"  99999999.877")
        self.assertNotIn(b"SCALE", old)
        p = compare_obs(src, old, rounded)
        self.assertTrue(any("SYS / SCALE FACTOR 100 would hold" in x for x in p), p)
        claim = copy.deepcopy(rep)
        claim["losses"]["phase-unalign-precision:G:L1W"] = {"count": 1}
        self.assertTrue(compare_obs(src, out, claim))
        count = copy.deepcopy(rep)
        del count["rules"]["OBS.PHASE.UNALIGN-SCALE"]
        self.assertTrue(compare_obs(src, out, count))

    def test_smallest_factor(self):
        """1000000.000 - 0.12345: x100 holds it (99999987.655); x1000 (999999876.550) would
        too, but the smallest is the one."""
        src, out, rep = self.run_case(["G L1W  0.12345"], "   1000000.000")
        self.assertEqual(self.scale_lines(out), ["G  100   1 L1W"])
        self.assertIn(b"\nG05  22000000.105    99999987.655\n", out)
        self.assertEqual(problems(src, out, rep), [])
        finer = out.replace(b"G  100   1 L1W", b"G 1000   1 L1W").replace(b"  99999987.655", b" 999999876.550")
        p = compare_obs(src, finer, rep)
        self.assertTrue(any("where 100 holds every value exactly" in x for x in p), p)

    def test_four_decimals_factor_10(self):
        """0.12340 (4 decimals): x10 holds it: 999999998.766."""
        src, out, rep = self.run_case(["G L1W  0.12340"], " 100000000.000")
        self.assertEqual(self.scale_lines(out), ["G   10   1 L1W"])
        self.assertIn(b"\nG05  22000000.105   999999998.766\n", out)
        self.assertEqual(problems(src, out, rep), [])
        p = compare_obs(src, out.replace(b"G   10   1 L1W", b"G  100   1 L1W").replace(
            b" 999999998.766", b"9999999987.660"), rep)
        self.assertTrue(any("where 10 holds every value exactly" in x for x in p), p)

    def test_value_with_four_decimals(self):
        """A stored value written with 4 decimals (no F14.3, but read and kept as written by a
        plain conversion): the value less a 2-decimal correction needs x10 too:
        1234567.1234 - 0.25 = 1234566.8734 -> 12345668.734."""
        src, out, rep = self.run_case(["G L1W  0.25000"], "  1234567.1234")
        self.assertEqual(self.scale_lines(out), ["G   10   1 L1W"])
        self.assertIn(b"\nG05  22000000.105    12345668.734\n", out)
        self.assertEqual(problems(src, out, rep), [])

    def test_source_already_scaled(self):
        """The source's factor 10 (stored 1000000000.000 = 100000000.0): 0.12345 x 10 has 4
        decimals, so k = 10 and the product 100 is written (a listed source record of the code
        is replaced, not repeated beside it; an 'all types' one stays, the listed code beating
        it in the group). A 4-decimal correction under factor 10 needs nothing new; under
        factor 1000 none ever does."""
        for extra, want in (("G   10   1 L1W", ["G  100   1 L1W"]),
                            ("G   10", ["G   10", "G  100   1 L1W"])):
            with self.subTest(source=extra):
                src, out, rep = self.run_case(["G L1W  0.12345"], "1000000000.000",
                                              extra=[hdr(extra, "SYS / SCALE FACTOR")])
                self.assertEqual(self.scale_lines(out), want)
                self.assertIn(b"\nG05  22000000.105  9999999987.655\n", out)
                self.assertEqual(rep["rules"]["OBS.PHASE.UNALIGN-SCALE"]["count"], 1)
                self.assertEqual(problems(src, out, rep), [])
        src, out, rep = self.run_case(["G L1W  0.12340"], "1000000000.000",
                                      extra=[hdr("G   10   1 L1W", "SYS / SCALE FACTOR")])
        self.assertEqual(self.scale_lines(out), ["G   10   1 L1W"])
        self.assertIn(b"\nG05  22000000.105   999999998.766\n", out)
        self.assertNotIn("OBS.PHASE.UNALIGN-SCALE", rep["rules"])
        self.assertEqual(problems(src, out, rep), [])
        src, out, rep = self.run_case(["G L1W  0.12345"], "1000000000.000",
                                      extra=[hdr("G 1000   1 L1W", "SYS / SCALE FACTOR")])
        self.assertEqual(self.scale_lines(out), ["G 1000   1 L1W"])
        self.assertIn(b"\nG05  22000000.105   999999876.550\n", out)
        self.assertNotIn("OBS.PHASE.UNALIGN-SCALE", rep["rules"])
        self.assertEqual(problems(src, out, rep), [])

    def test_other_satellites_and_codes(self):
        """'G L1W  0.12345  01 G05': G12's L1W has no correction but shares the code's factor
        (stored x100, unshifted); L2W keeps its own (none)."""
        g05 = "G05" + F("  22000000.105") + F(" 100000000.000") + F("  80000000.125")
        g12 = "G12" + F("  23000000.105") + F("  11000000.250") + F("  85000000.375")
        src = v3("3.05", "G", ["G    3 C1W L1W L2W"], ["G L1W  0.12345  01 G05"], [g05, g12])
        out, rep = conv(src, "3.00")
        self.assertEqual(self.scale_lines(out), ["G  100   1 L1W"])
        self.assertIn(b"\nG05  22000000.105  9999999987.655    80000000.125\n", out)
        self.assertIn(b"\nG12  23000000.105  1100000025.000    85000000.375\n", out)
        self.assertEqual(rep["rules"]["OBS.PHASE.UNALIGN-SCALE"]["count"], 2)
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(compare_obs(src, out.replace(b"1100000025.000", b"  11000000.250"), rep))
        self.assertTrue(compare_obs(src, out.replace(b"  80000000.125", b"8000000012.500"), rep))

    def test_event_scopes(self):
        """Each scope chooses its own: the header's (factor 1) needs x100; a flag-4 event's
        SYS / SCALE FACTOR 'G 1000' (rinex305.txt section 6.5: it holds from there on, and an
        'all types' record replaces the system's factors) holds 0.12345 x 1000 = 123.450
        already, so nothing is added there; a later 'G   10' event needs x10 (product 100)."""
        e1 = "> 2026 10 01 00 00  0.0000000  0  1\nG05" + F("  22000000.105") + F(" 100000000.000").rstrip()
        e2 = "> 2026 10 01 00 00 30.0000000  0  1\nG05" + F("  22000000.105") + F("1000000000.000").rstrip()
        e3 = "> 2026 10 01 00 01  0.0000000  0  1\nG05" + F("  22000000.105") + F("1000000000.000")
        src = lines(hdr("     3.05           OBSERVATION DATA    G", "RINEX VERSION / TYPE"), PGM,
                    SITE[0], hdr("GEODETIC", "MARKER TYPE"), *SITE[1:], hdr("G    2 C1W L1W", "SYS / # / OBS TYPES"),
                    tfo(), hdr("G L1W  0.12345", "SYS / PHASE SHIFT"), EOH, e1,
                    _event(hdr("G 1000", "SYS / SCALE FACTOR")), e2,
                    _event(hdr("G   10", "SYS / SCALE FACTOR")), e3, width=None)
        out, rep = conv(src, "3.00")
        text = out.decode("latin-1")
        self.assertEqual(self.scale_lines(out), ["G  100   1 L1W", "G 1000", "G   10", "G  100   1 L1W"])
        self.assertIn("G05  22000000.105  9999999987.655\n>", text)
        self.assertIn("G05  22000000.105   999999876.550\n>", text)
        self.assertTrue(text.rstrip().endswith("G05  22000000.105  9999999987.655"))
        self.assertEqual(rep["rules"]["OBS.PHASE.UNALIGN-SCALE"]["count"], 2)
        self.assertEqual(problems(src, out, rep), [])
        # the last event's added record made x10: its value is read x10, not x100
        g10 = hdr("G   10", "SYS / SCALE FACTOR") + "\n"
        cut = out.replace((g10 + hdr("G  100   1 L1W", "SYS / SCALE FACTOR")).encode(),
                          (g10 + hdr("G   10   1 L1W", "SYS / SCALE FACTOR")).encode())
        self.assertNotEqual(cut, out)
        self.assertTrue(compare_obs(src, cut, rep))


class AstraVerify2(unittest.TestCase):
    """Astra's second verify round: W1, the checker judges each scope of a code's factor on its
    own (it grouped by input factor, so a scope no factor could hold hid one a factor did); W2,
    the converter's factor comes from the values, each less the correction that applies to it,
    not from every recorded correction."""

    @staticmethod
    def two_scopes(flag, event="G    1   1 L1W"):
        e1 = "> 2026 10 01 00 00  0.0000000  0  1\nG05" + F("  22000000.105") + F(" 100000000.000").rstrip()
        e2 = "> 2026 10 01 00 00 30.0000000  0  1\nG05" + F("  22000000.105") + F("1150000000.000").rstrip()
        return lines(hdr("     3.05           OBSERVATION DATA    G", "RINEX VERSION / TYPE"), PGM,
                     SITE[0], hdr("GEODETIC", "MARKER TYPE"), *SITE[1:], hdr("G    2 C1W L1W", "SYS / # / OBS TYPES"),
                     tfo(), hdr("G L1W  0.12345", "SYS / PHASE SHIFT"), EOH, e1,
                     _event(hdr(event, "SYS / SCALE FACTOR"), flag=flag), e2, width=None)

    def test_scopes_judged_apart(self):
        """W1 (Astra's repro): 100000000.000 under the header's factor 1, then an event (flags 2
        to 5) setting L1W's factor to 1 again, then 1150000000.000. The first scope is held x100
        (9999999987.655); in the second no factor holds 1149999999.87655 (x10 overflows), so
        it is rounded and claimed. Mutated to round the first too, claimed (count 2), with the
        x100 record and UNALIGN-SCALE gone: the first scope's avoidable loss is found."""
        for flag in (2, 3, 4, 5):
            with self.subTest(flag=flag):
                src = self.two_scopes(flag)
                out, rep = conv(src, "3.00")
                text = out.decode("latin-1")
                self.assertEqual(AstraVerifyV1.scale_lines(out), ["G  100   1 L1W", "G    1   1 L1W"])
                self.assertIn("G05  22000000.105  9999999987.655\n>", text)
                self.assertTrue(text.rstrip().endswith("G05  22000000.105  1149999999.877"))
                self.assertEqual(rep["losses"]["phase-unalign-precision:G:L1W"]["count"], 1)
                self.assertEqual(rep["rules"]["OBS.PHASE.UNALIGN-SCALE"]["count"], 1)
                self.assertEqual(problems(src, out, rep), [])
                bad = out.replace(hdr("G  100   1 L1W", "SYS / SCALE FACTOR").encode() + b"\n", b"").replace(
                    b"9999999987.655", b"  99999999.877")
                claim = copy.deepcopy(rep)
                claim["losses"]["phase-unalign-precision:G:L1W"]["count"] = 2
                del claim["rules"]["OBS.PHASE.UNALIGN-SCALE"]
                p = problems(src, bad, claim)
                self.assertTrue(any("(the header)" in x and "SYS / SCALE FACTOR 100 would hold" in x for x in p), p)

    def test_no_factor_holds_then_none_written(self):
        """1234.1234567 (7 decimals, read as written) less 0.25: no allowed factor holds
        1233.8734567, so the input's factor stays and the value is rounded (1233.873). A factor
        10 written anyway (12338.735, rounded as well) is found."""
        g = "G05" + F("  22000000.105") + F("  1234.1234567")
        src = v3("3.05", "G", ["G    2 C1W L1W"], ["G L1W  0.25000"], [g])
        out, rep = conv(src, "3.00")
        self.assertEqual(AstraVerifyV1.scale_lines(out), [])
        self.assertIn(b"\nG05  22000000.105        1233.873\n", out)
        self.assertEqual(problems(src, out, rep), [])
        finer = out.replace(hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS").encode(),
                            (hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS") + "\n"
                             + hdr("G   10   1 L1W", "SYS / SCALE FACTOR")).encode()).replace(
            b"      1233.873", b"     12338.735")
        more = copy.deepcopy(rep)
        more["rules"]["OBS.PHASE.UNALIGN-SCALE"] = {"count": 1}
        p = compare_obs(src, finer, more)
        self.assertTrue(any("no allowed factor holds every value" in x for x in p), p)

    def test_correction_no_value_takes(self):
        """W2: 'G L1W  0.12345  01 G12' with only G05 observed: no value is corrected, so G05's
        1000000.000 keeps the input's factor (Astra's 72 event and Hatanaka cases: x100 was
        written). The entry changes no value: claimed lost."""
        g = "G05" + F("  22000000.105") + F("   1000000.000")
        src = v3("3.05", "G", ["G    2 C1W L1W"], ["G L1W  0.12345  01 G12"], [g])
        out, rep = conv(src, "3.00")
        self.assertEqual(AstraVerifyV1.scale_lines(out), [])
        self.assertIn(b"\nG05  22000000.105     1000000.000\n", out)
        self.assertNotIn("OBS.PHASE.UNALIGN-SCALE", rep["rules"])
        self.assertEqual(norms(rep), {})
        self.assertEqual(rep["losses"]["phase-shift-record-not-representable"]["count"], 1)
        self.assertEqual(problems(src, out, rep), [])
        # the old output: x100 for nothing
        x100 = out.replace(hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS").encode(),
                           (hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS") + "\n"
                            + hdr("G  100   1 L1W", "SYS / SCALE FACTOR")).encode()).replace(
            b"   1000000.000", b" 100000000.000")
        more = copy.deepcopy(rep)
        more["rules"]["OBS.PHASE.UNALIGN-SCALE"] = {"count": 1}
        p = compare_obs(src, x100, more)
        self.assertTrue(any("where 1 holds every value exactly" in x for x in p), p)


class AstraVerifyV2(unittest.TestCase):
    """Verify round V2: OBS.PHASE.ALIGN-CLIPPED comes with either direction; the checker
    chooses the rule by the explicit table rules (OBS.PHASE.ALIGN-A19-3.02, -A23-3.0x) and
    OBS.PHASE.UNALIGN-3.00, not by a name's prefix. A subtraction (to 3.00) past F14.3 is
    clipped by 1e9 with LLI bit 0 set (rinex305.txt section 6.7 p.43)."""

    def test_unalign_clipped_below(self):
        """-999999999.900 - 0.25 = -1000000000.150 -> -0.150, LLI 1."""
        g = "G05" + F("  22000000.105") + F("-999999999.900")
        src = v3("3.05", "G", ["G    2 C1W L1W"], ["G L1W  0.25000"], [g])
        out, rep = conv(src, "3.00")
        self.assertIn(("\nG05" + F("  22000000.105") + F("        -0.150", "1")).rstrip().encode() + b"\n", out)
        self.assertEqual(norms(rep), {"phase-shift-removed:G:L1W:+0.25": 1, "phase-shift-clipped:G:L1W": 1})
        self.assertIn("OBS.PHASE.ALIGN-CLIPPED", rep["rules"])
        self.assertIn("OBS.PHASE.UNALIGN-3.00", rep["rules"])
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(problems(src, out.replace(b"        -0.1501", b"        -0.150 "), rep))
        # the direction's rule taken away: shifts claimed with no rule to check them by
        bare = copy.deepcopy(rep)
        del bare["rules"]["OBS.PHASE.UNALIGN-3.00"]
        p = compare_obs(src, out, bare)
        self.assertTrue(any("no --align-phases rule" in x for x in p), p)
        both = copy.deepcopy(rep)
        both["rules"]["OBS.PHASE.ALIGN-A23-3.05"] = {"count": 1}
        self.assertTrue(compare_obs(src, out, both))

    def test_unalign_clipped_above(self):
        """9999999999.900 + 0.25 (a -1/4 correction removed) = 10000000000.150 -> 9000000000.150,
        LLI 1."""
        g = "G05" + F("  22000000.105") + F("9999999999.900")
        src = v3("3.05", "G", ["G    2 C1W L1W"], ["G L1W -0.25000"], [g])
        out, rep = conv(src, "3.00")
        self.assertIn(("\nG05" + F("  22000000.105") + F("9000000000.150", "1")).rstrip().encode() + b"\n", out)
        self.assertEqual(norms(rep), {"phase-shift-removed:G:L1W:-0.25": 1, "phase-shift-clipped:G:L1W": 1})
        self.assertEqual(problems(src, out, rep), [])
        self.assertTrue(problems(src, out.replace(b"9000000000.1501", b"9000000000.150 "), rep))

    def test_wrong_table_rule(self):
        """Rule 2's table rule must be the target's: A23-3.05 for 3.05, not A19-3.02."""
        g = "G05" + F("  22000000.105") + F(" 115000000.405") + F("  22000005.555") + F("-999999999.900")
        src = v3("3.00", "G", ["G    4 C1C L1C C5Q L5Q"], [], [g])
        out, rep = conv(src, "3.05")
        self.assertEqual(problems(src, out, rep), [])
        wrong = copy.deepcopy(rep)
        wrong["rules"]["OBS.PHASE.ALIGN-A19-3.02"] = wrong["rules"].pop("OBS.PHASE.ALIGN-A23-3.05")
        p = compare_obs(src, out, wrong)
        self.assertTrue(any("table rules" in x for x in p), p)

if __name__ == "__main__":
    unittest.main()
