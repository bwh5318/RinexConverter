"""Tests for rinexcore/io/hatanaka.py, the Compact RINEX (Hatanaka) codec.

Run from the repository root:  python -m unittest tests.unit.test_hatanaka -v

* The hand-made fixtures below were written from docs/HATANAKA.md (the grammar
  taken from crx2rnx.c), not produced by our encoder. Each has its expected
  RINEX output, also written by hand.
* Oracle tests run CRX2RNX.exe when it is present and are skipped otherwise
  (CLAUDE.md rule 2). The archived digests in tests/oracle/crx2rnx_sha256.json
  are checked even without the exe (PLAN §1.5c).
* Corpus tests need data/corpus (gitignored); they are skipped without it. By
  default one small file per (CRINEX, RINEX version) bucket is decoded; set
  HATANAKA_FULL_CORPUS=1 to decode all 299 (about 5 minutes).

Standard library unittest only; pytest can collect these classes too.
"""

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rinexcore.errors import CorruptError  # noqa: E402
from rinexcore.io import hatanaka  # noqa: E402
from rinexcore.io.hatanaka import crx_to_rnx, is_crx, iter_crx_to_rnx, rnx_to_crx  # noqa: E402

ARCHIVE = os.path.join(ROOT, "tests", "oracle", "crx2rnx_sha256.json")
MANIFEST = os.path.join(ROOT, "tests", "corpus", "manifest.json")
CORPUS = os.path.join(ROOT, "data", "corpus")
PROG = "RNX2CRX ver.4.2.0"
DATE = "30-Oct-26 00:00"


def find_crx2rnx():
    """Path of the CRX2RNX 4.2.0 oracle, or None (tests using it are skipped)."""
    for p in (os.environ.get("RINEX_ORACLE_CRX2RNX", ""),
              os.path.join(ROOT, "tools", "oracles", "rnxcmp", "CRX2RNX.exe"),
              os.path.join(ROOT, "reference", "tools", "rnxcmp-4.2.0", "CRX2RNX.exe")):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def run_crx2rnx(exe, crx):
    """(exit code, stdout with CRLF -> LF, stderr). The Windows build writes text mode."""
    with tempfile.TemporaryDirectory() as d:
        inp = os.path.join(d, "in.crx")
        with open(inp, "wb") as f:
            f.write(crx)
        with open(inp, "rb") as fi:
            r = subprocess.run([exe, "-"], stdin=fi, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=120)
    out = r.stdout
    if os.name == "nt":
        out = out.replace(b"\r\n", b"\n")
    return r.returncode, out, r.stderr.decode("latin-1")


def find_rnx2crx():
    """Path of the RNX2CRX 4.2.0 oracle (tools/oracles/ORACLES.md), or None (tests using it
    are skipped)."""
    for p in (os.environ.get("RINEX_ORACLE_RNX2CRX", ""),
              os.path.join(ROOT, "tools", "oracles", "rnxcmp", "RNX2CRX.exe")):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def run_rnx2crx(exe, rnx):
    """(exit code, stdout with CRLF -> LF, stderr) of RNX2CRX reading stdin, writing stdout."""
    with tempfile.TemporaryDirectory() as d:
        inp = os.path.join(d, "in.rnx")
        with open(inp, "wb") as f:
            f.write(rnx)
        with open(inp, "rb") as fi:
            r = subprocess.run([exe], stdin=fi, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=120)
    out = r.stdout
    if os.name == "nt":
        out = out.replace(b"\r\n", b"\n")
    return r.returncode, out, r.stderr.decode("latin-1")


def body(crx):
    """A CRX file without line 2, CRINEX PROG / DATE (program name and run date)."""
    a = crx.split(b"\n", 2)
    return a[0] + b"\n" + (a[2] if len(a) > 2 else b"")


def load_archive():
    with open(ARCHIVE, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def H(content, label):
    """A header line: content in columns 1-60, label from column 61."""
    return (content.ljust(60) + label).encode("ascii")


def L(*lines):
    return b"".join((ln if isinstance(ln, bytes) else ln.encode("ascii")) + b"\n"
                    for ln in lines)


CRX_HDR1 = H("1.0                 COMPACT RINEX FORMAT", "CRINEX VERS   / TYPE")
CRX_HDR3 = H("3.0                 COMPACT RINEX FORMAT", "CRINEX VERS   / TYPE")
CRX_HDR31 = H("3.1                 COMPACT RINEX FORMAT", "CRINEX VERS   / TYPE")
CRX_PROG = H(PROG.ljust(40) + DATE, "CRINEX PROG / DATE")
EOH = H("", "END OF HEADER")

# ---------------------------------------------------------------- CRINEX 1.0
# init epoch, clock arc, text difference with '&', new satellite, blank field,
# flags, an event (flag 4) and the re-initialised epoch after it.
RNX10_HDR = [H("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
             H("     2    C1    L1", "# / TYPES OF OBSERV"),
             EOH]
CRX10 = L(CRX_HDR1, CRX_PROG, *RNX10_HDR,
          "&26 10 30  0  0  0.0000000  0  2G01G02",
          "3&123456789",
          "3&20000000123 3&105000000456",
          "3&21000000000 3&110000000000 1",
          "                3",
          "1000",
          "100 200",
          "-5",
          "&26 10 30  0  1  0.0000000  4  1",
          H("A COMMENT", "COMMENT"),
          "&26 10 30  0  1 30.0000000  0  1G02",
          "",
          "3&21000003000 3&110000010000  5 7",
          "              2 &              2   G05",
          "3&-5",
          "300 1000",
          "3&-12345 3&-50")
RNX10 = L(*RNX10_HDR,
          " 26 10 30  0  0  0.0000000  0  2G01G02".ljust(68) + "  .123456789",
          "  20000000.123   105000000.456",
          "  21000000.0001  110000000.000",
          " 26 10 30  0  0 30.0000000  0  2G01G02".ljust(68) + "  .123457789",
          "  20000000.223   105000000.656",
          "  20999999.9951",
          " 26 10 30  0  1  0.0000000  4  1",
          H("A COMMENT", "COMMENT"),
          " 26 10 30  0  1 30.0000000  0  1G02",
          "  21000003.000 5 110000010.000 7",
          " 26 10 30  0  2  0.0000000  0  2G02G05".ljust(68) + " -.000000005",
          "  21000003.300 5 110000011.000 7",
          "       -12.345           -.050")

# ---------------------------------------------------------------- CRINEX 3.0
# per-system type counts, flags of a new satellite written in full with '&',
# a blank field that keeps its SSI, an escape line, clock gaps, the satellite
# list shrinking ('&&&'), second-order differences.
RNX30_HDR = [H("     3.04           OBSERVATION DATA    M", "RINEX VERSION / TYPE"),
             H("G    3 C1C L1C S1C", "SYS / # / OBS TYPES"),
             H("E    2 C1C L1C", "SYS / # / OBS TYPES"),
             EOH]
CRX30_BODY = ["> 2026 10 30 00 00  0.0000000  0  2      G01E11",
              "3&123456789",
              "3&20000000123 3&105000000456 3&45250 &&17&&",
              "3&23000000000  &&&5",
              "&an escape line, skipped by CRX2RNX",
              "                   3",
              "",
              "100 200 -250",
              "-3000 3&1234    6",
              " " * 17 + "1" + " " + "&" + " " * 14 + "1" + " " * 9 + "&&&",
              "3&-123456789012",
              "10 20 30   &"]
CRX30 = L(CRX_HDR3, CRX_PROG, *RNX30_HDR, *CRX30_BODY)
CRX30_NO_ESCAPE = L(CRX_HDR3, CRX_PROG, *RNX30_HDR, *(x for x in CRX30_BODY if x[:1] != "&"))
RNX30 = L(*RNX30_HDR,
          "> 2026 10 30 00 00  0.0000000  0  2      " + "  .000123456789",
          "G01  20000000.123   105000000.45617        45.250",
          "E11  23000000.000                 5",
          "> 2026 10 30 00 00 30.0000000  0  2",
          "G01  20000000.223   105000000.65617        45.000",
          "E11  22999997.000           1.234 6",
          "> 2026 10 30 00 01  0.0000000  0  1      " + " -.123456789012",
          "G01  20000000.333   105000000.876 7        44.780")

# ---------------------------------------------------------------- CRINEX 3.1
# the picosecond record: with the clock, unchanged-and-trimmed, without clock.
RNX31_HDR = [H("     4.02           OBSERVATION DATA    G", "RINEX VERSION / TYPE"),
             H("G    1 C1C", "SYS / # / OBS TYPES"),
             EOH]
CRX31 = L(CRX_HDR31, CRX_PROG, *RNX31_HDR,
          "> 2026 10 30 00 00  0.0000000  0  1      G01",
          "3&123456789 01234",
          "3&20000000123 &&",
          "                   3",
          "0     5",
          "1",
          "                 1 &",
          "",
          "1",
          "                   3",
          " 99999",
          "1")
RNX31 = L(*RNX31_HDR,
          "> 2026 10 30 00 00  0.0000000  0  1      " + "  .000123456789" + " 01234",
          "G01  20000000.123",
          "> 2026 10 30 00 00 30.0000000  0  1      " + "  .000123456789" + " 01235",
          "G01  20000000.124",
          "> 2026 10 30 00 01  0.0000000  0  1      " + " " * 16 + "01235",
          "G01  20000000.126",
          "> 2026 10 30 00 01 30.0000000  0  1      " + " " * 16 + "99999",
          "G01  20000000.130")

HANDMADE = {"crinex10": (CRX10, RNX10), "crinex30": (CRX30, RNX30), "crinex31": (CRX31, RNX31)}


# ---------------------------------------------------------------- RINEX 4.02 fixture
def fmt14(v):
    """F14.3 the way CRX2RNX prints it (no leading zero); v in units of 0.001."""
    if v is None:
        return " " * 14
    a = abs(v)
    s = "%d.%03d" % (a // 1000, a % 1000) if a >= 1000 else ".%03d" % a
    return ("-" + s if v < 0 else s).rjust(14)


def fmt15(v):
    """F15.12 the way CRX2RNX prints it; v in units of 1e-12 s."""
    a = abs(v)
    s = "%d.%012d" % (a // 10 ** 12, a % 10 ** 12) if a >= 10 ** 12 else ".%012d" % a
    return ("-" + s if v < 0 else s).rjust(15)


def make_rinex402_fixture(seed=4021):
    """A deterministic RINEX 4.02 file with picosecond epochs, in CRX2RNX layout.

    30 epochs: clock on two epochs out of three, picosecond field on every
    epoch (sometimes unchanged), a satellite that appears and one that goes, a
    power-failure flag, an event (flag 4) that changes the Galileo types, a
    cycle slip big enough to restart the arc, blank fields with SSI, small
    Doppler values printed without a leading zero.
    """
    rnd = random.Random(seed)
    lines = [H("     4.02           OBSERVATION DATA    M", "RINEX VERSION / TYPE"),
             H("rinexcore           test_hatanaka.py    20261030 000000 UTC", "PGM / RUN BY / DATE"),
             H("Synthetic RINEX 4.02 file with picosecond epoch fields", "COMMENT"),
             H("PICO", "MARKER NAME"),
             H("G    4 C1C L1C D1C S1C", "SYS / # / OBS TYPES"),
             H("E    3 C1C L1C S1C", "SYS / # / OBS TYPES"),
             H("R    2 C1C L1C", "SYS / # / OBS TYPES"),
             H("  2026    10    30     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
             EOH]
    ntypes = {"G": 4, "E": 3, "R": 2}
    base = {s: (rnd.randint(20000000000, 25000000000), rnd.randint(-3000000, 3000000))
            for s in ("G01", "G05", "G12", "E03", "E11", "R07")}
    phase = {s: rnd.randint(100000000000, 130000000000) for s in base}
    clock = 123456789
    ps = 12345
    for k in range(30):
        t = 30 * k
        sats = ["G01", "G05", "E03", "E11"]
        if k < 20:
            sats.insert(2, "G12")
        if k >= 5:
            sats.append("R07")
        if k == 15:
            lines.append(("> 2026 10 30 %02d %02d%11.7f  4  2" % (t // 3600, t // 60 % 60, t % 60)
                          ).encode("ascii"))
            lines.append(H("GALILEO S1C DROPPED FROM HERE ON", "COMMENT"))
            lines.append(H("E    2 C1C L1C", "SYS / # / OBS TYPES"))
            ntypes["E"] = 2
            continue
        flag = 1 if k == 10 else 0
        if rnd.random() < 0.7:
            ps = rnd.randint(0, 99999)
        clock += rnd.randint(-20000, 20000)
        if clock < 0 and clock % 100000000 == 0:
            clock += 1
        head = "> 2026 10 30 %02d %02d%11.7f  %d%3d      " % (t // 3600, t // 60 % 60,
                                                           t % 60 + 0.25 * (k % 3), flag, len(sats))
        head += fmt15(clock) if k % 3 != 2 else " " * 15
        lines.append((head + " %05d" % ps).encode("ascii"))
        for s in sats:
            r0, rate = base[s]
            rng = r0 + rate * k + rnd.randint(-500, 500)
            phase[s] += rate * 5 + rnd.randint(-50, 50)
            if s == "G01" and k == 12:
                phase[s] += 30000000000          # cycle slip: restarts the arc
            vals = [rng, phase[s]]
            if ntypes[s[0]] >= 3:
                if s[0] == "G":
                    vals.append(rnd.randint(-900, 900) if s == "G05" else rate // 1000)
                vals.append(rnd.randint(30000, 50000))
            vals = vals[:ntypes[s[0]]]
            flags = []
            for j, v in enumerate(vals):
                lli = "1" if (j == 1 and rnd.random() < 0.1) else " "
                ssi = str(rnd.randint(4, 9)) if rnd.random() < 0.8 else " "
                flags.append(lli + ssi)
            if s == "G05" and k % 4 == 1:
                vals[-1] = None                  # blank S1C that keeps an SSI
                flags[-1] = " 5"
            line = s + "".join(fmt14(v) + f for v, f in zip(vals, flags))
            lines.append(line.rstrip(" ").encode("ascii"))
    return b"\n".join(lines) + b"\n"


# ---------------------------------------------------------------- tests
class TestPrimitives(unittest.TestCase):
    def test_repair(self):
        r = hatanaka._repair
        self.assertEqual(r(b"abcdef", b" & x"), b"a cxef")
        self.assertEqual(r(b"ab", b" &xyz&"), b"a xyz ")
        self.assertEqual(r(b"", b"a&b"), b"a b")
        self.assertEqual(r(b"abc", b""), b"abc")
        self.assertEqual(r(b"abc", b"   "), b"abc")

    def test_strdiff(self):
        d = hatanaka._strdiff
        self.assertEqual(d(b"abcdef", b"abXd f"), b"  X & ")
        self.assertEqual(d(b"abcdef", b"ab"), b"  &&&&")
        self.assertEqual(d(b"ab cd", b"a"), b" & &&")
        self.assertEqual(d(b"ab", b"abcd "), b"  cd ")
        self.assertEqual(d(b"&", b"> 2026"), b"> 2026")
        self.assertEqual(d(b"&", b" 26 10"), b"&26 10")

    def test_strdiff_repair_inverse(self):
        rnd = random.Random(7)
        alphabet = b" G0123456789.>"
        for _ in range(500):
            a = bytes(rnd.choice(alphabet) for _ in range(rnd.randint(0, 30)))
            b = bytes(rnd.choice(alphabet) for _ in range(rnd.randint(0, 30)))
            diff = hatanaka._strdiff(a, b).rstrip(b" ")
            got = hatanaka._repair(a.rstrip(b" "), diff).rstrip(b" ")
            self.assertEqual(got, b.rstrip(b" "), (a, b, diff))

    def test_chop_blank(self):
        c = hatanaka._chop_blank
        self.assertEqual(c(b"abc  "), b"abc")
        self.assertEqual(c(b"   "), b" ")
        self.assertEqual(c(b""), b"")

    def test_c_atoi(self):
        a = hatanaka._c_atoi
        self.assertEqual(a(b"  12G01", 0), 12)
        self.assertEqual(a(b" -5x", 0), -5)
        self.assertEqual(a(b"abc", 0), 0)
        self.assertEqual(a(bytearray(b"12\x0034"), 0), 12)

    def test_is_crx(self):
        self.assertTrue(is_crx(CRX10))
        self.assertTrue(is_crx(CRX31.replace(b"\n", b"\r\n")))
        self.assertFalse(is_crx(RNX10))
        self.assertFalse(is_crx(b""))

    def test_value_format(self):
        f = lambda v: hatanaka._fmt_value(v, 1)  # noqa: E731
        self.assertEqual(f(0), b"          .000")
        self.assertEqual(f(123), b"          .123")
        self.assertEqual(f(-5), b"         -.005")
        self.assertEqual(f(1000), b"         1.000")
        self.assertEqual(f(-12345), b"       -12.345")
        self.assertEqual(f(9999999999999), b"9999999999.999")
        self.assertEqual(f(-999999999999), b"-999999999.999")
        for bad in (10000000000000, -1000000000000):
            with self.assertRaises(CorruptError) as cm:
                f(bad)
            self.assertEqual(cm.exception.rule, "CRX.RANGE")

    def test_clock_format(self):
        f = hatanaka._fmt_clock
        self.assertEqual(f(123456789, 1, 1, False), b"  .123456789")
        self.assertEqual(f(-123456789, 1, 1, False), b" -.123456789")
        self.assertEqual(f(1123456789, 1, 1, False), b" 1.123456789")
        self.assertEqual(f(-123456789012, 4, 1, False), b" -.123456789012")
        self.assertEqual(f(99999999999999, 4, 1, False), b"99.999999999999")
        self.assertEqual(f(0, 4, 1, False), b"  .000000000000")
        # CRX2RNX 4.2.0 prints a negative clock with eight trailing zero digits wrongly
        self.assertEqual(f(-100000000, 1, 1, False), b" -.000000000")
        self.assertEqual(f(-100000000, 1, 1, True), b" -.100000000")
        with self.assertRaises(CorruptError):
            f(100000000000000, 4, 1, False)


class TestDecodeHandMade(unittest.TestCase):
    def test_fixtures(self):
        for name, (crx, rnx) in HANDMADE.items():
            with self.subTest(name):
                self.assertEqual(crx_to_rnx(crx), rnx)
                self.assertEqual(b"".join(iter_crx_to_rnx(crx, chunk_size=1)), rnx)

    def test_crlf_input(self):
        for name, (crx, rnx) in HANDMADE.items():
            with self.subTest(name):
                self.assertEqual(crx_to_rnx(crx.replace(b"\n", b"\r\n")), rnx)

    def test_final_epoch_line_without_lf(self):
        # A data line without its LF is "truncated" (C:854-858) ...
        with self.assertRaises(CorruptError) as cm:
            crx_to_rnx(CRX10[:-1])
        self.assertEqual(cm.exception.rule, "CRX.TRUNCATED")

    def test_dos_eof(self):
        self.assertEqual(crx_to_rnx(CRX10 + b"\x1a\n"), RNX10)

    def test_minus_zero_quirk(self):
        # "-000123": C splits off the lower 5 digits; the upper part "-0" is 0,
        # so the sign is lost (getdiff C:757-765). CRX2RNX prints .123.
        crx = CRX10.replace(b"3&-12345 3&-50", b"3&-12345 3&-000123")
        self.assertTrue(crx_to_rnx(crx).endswith(b"       -12.345" + b" " * 12 + b".123\n"))

    def test_fix_clock_bug_option(self):
        crx = CRX10.replace(b"3&-5\n", b"3&-100000000\n")
        epoch = b" 26 10 30  0  2  0.0000000  0  2G02G05".ljust(68)
        self.assertIn(epoch + b" -.000000000\n", crx_to_rnx(crx))       # as CRX2RNX 4.2.0
        self.assertIn(epoch + b" -.100000000\n", crx_to_rnx(crx, fix_clock_bug=True))

    def test_partial_output_before_error(self):
        lines = CRX10.split(b"\n")
        cut = b"\n".join(lines[:-2]) + b"\n"        # last epoch loses a data line
        got = []
        with self.assertRaises(CorruptError):
            for chunk in iter_crx_to_rnx(cut, chunk_size=1):
                got.append(chunk)
        want = RNX10[:RNX10.index(b" 26 10 30  0  2  0.0000000")]
        self.assertEqual(b"".join(got), want)


class TestEncodeHandMade(unittest.TestCase):
    def test_same_bytes_as_rnx2crx_would_write(self):
        self.assertEqual(rnx_to_crx(RNX10, program=PROG, date=DATE), CRX10)
        self.assertEqual(rnx_to_crx(RNX30, program=PROG, date=DATE), CRX30_NO_ESCAPE)
        self.assertEqual(rnx_to_crx(RNX31, program=PROG, date=DATE), CRX31)

    def test_round_trip(self):
        for name, (crx, rnx) in HANDMADE.items():
            with self.subTest(name):
                self.assertEqual(crx_to_rnx(rnx_to_crx(rnx)), rnx)

    def test_value_preserving_canonicalisation(self):
        # 0.123 and -0.000123456789 come back as .123 / -.000123456789 (CRX2RNX layout)
        rnx = RNX30.replace(b"         1.234 6", b"         0.234 6").replace(
            b" -.123456789012", b"-0.123456789012")
        back = crx_to_rnx(rnx_to_crx(rnx))
        self.assertIn(b"          .234 6", back)
        self.assertIn(b" -.123456789012", back)

    def test_crlf_and_trailing_blanks_in_input(self):
        rnx = RNX10.replace(b"\n", b"   \r\n")
        self.assertEqual(crx_to_rnx(rnx_to_crx(rnx)), RNX10)

    def test_missing_final_newline_accepted(self):
        self.assertEqual(crx_to_rnx(rnx_to_crx(RNX10[:-1])), RNX10)

    def test_header_lines(self):
        crx = rnx_to_crx(RNX10, program="prog", date=DATE)
        lines = crx.split(b"\n")
        self.assertEqual(lines[0], CRX_HDR1)
        self.assertEqual(lines[1], H("prog".ljust(40) + DATE, "CRINEX PROG / DATE"))
        self.assertTrue(rnx_to_crx(RNX30).startswith(b"3.0 "))
        self.assertTrue(rnx_to_crx(RNX31).startswith(b"3.1 "))
        date_field = rnx_to_crx(RNX31).split(b"\n")[1][40:60]
        self.assertRegex(date_field.decode(), r"^\d\d-[A-Z][a-z]{2}-\d\d \d\d:\d\d +$")

    def test_slip_restarts_arc(self):
        rnx = RNX10.replace(b"  20000000.223   105000000.656", b"  20000000.223   999999999.656")
        crx = rnx_to_crx(rnx)
        self.assertIn(b"\n100 3&999999999656\n", crx)
        self.assertEqual(crx_to_rnx(crx), rnx)

    def test_slip_threshold_is_upper_part(self):
        # RNX2CRX restarts when |upper part of the k-th difference| > 100000 (E:648),
        # with upper part = value // 100000 truncated, differenced separately.
        prev = (0,)
        self.assertFalse(hatanaka._slip((10000099999, 10000099999), prev))
        self.assertTrue(hatanaka._slip((10000100000, 10000100000), prev))
        self.assertFalse(hatanaka._slip((-10000099999, -10000099999), prev))


def _err(fn, data, **kw):
    try:
        fn(data, **kw)
    except CorruptError as exc:
        return exc.rule
    return None


class TestDecodeErrors(unittest.TestCase):
    cases = [
        ("not crinex", b"garbage\n" + CRX10[CRX10.index(b"\n") + 1:], "CRX.NOT_CRINEX"),
        ("crinex 2.0", CRX10.replace(b"1.0   ", b"2.0   ", 1), "CRX.NOT_CRINEX"),
        ("empty", b"", "CRX.TRUNCATED"),
        ("no end of header", CRX10[:CRX10.index(b"END OF HEADER") - 60], "CRX.TRUNCATED"),
        ("bad rinex version", CRX10.replace(b"     2.11  ", b"     5.11  "), "CRX.RINEX_VERSION"),
        ("truncated epoch", CRX10[:CRX10.rindex(b"3&-12345")], "CRX.TRUNCATED"),
        ("new sat no init", CRX10.replace(b"3&20000000123 ", b"20000000123 "),
         "CRX.NEW_SAT_NO_INIT"),
        ("blank then no init", CRX30.replace(b"-3000 3&1234", b"-3000 1234"),
         "CRX.BLANK_NO_INIT"),
        ("undefined system", CRX30.replace(b"G01E11", b"G01J11"), "CRX.SYS"),
        ("bad field", CRX10.replace(b"100 200", b"100 2a0"), "CRX.FIELD"),
        ("empty init", CRX10.replace(b"3&-12345 3&-50", b"3&-12345 3&"), "CRX.FIELD"),
        ("arc order 6", CRX10.replace(b"3&-12345", b"6&-12345"), "CRX.ARC_ORDER"),
        ("range", CRX10.replace(b"3&-12345", b"3&99999999999999"), "CRX.RANGE"),
        ("clock garbage", CRX10.replace(b"\n3&-5\n", b"\n3&-5x\n"), "CRX.CLOCK"),
        ("event not followed by init",
         CRX10.replace(b"&26 10 30  0  1 30.0000000", b" 26 10 30  0  1 30.0000000"),
         "CRX.EVENT"),
        ("epoch flag column", CRX10.replace(b"\n                3\n", b"\n                3          x\n"),
         "CRX.EPOCH"),
        ("nul", CRX10.replace(b"100 200", b"100\x00200"), "CRX.NUL"),
        ("short satellite list", CRX10.replace(b"0  2G01G02", b"0  3G01G02"), "CRX.SATLIST"),
        ("more than 100 satellites", CRX10.replace(b"0  2G01G02", b"0101G01G02"), "CRX.MAXSAT"),
        ("picosecond too long", CRX31.replace(b"3&123456789 01234", b"3&123456789 012345"),
         "CRX.PICOSEC"),
        ("short new-sat flags", CRX30.replace(b"&&17&&", b"&&17"), "CRX.FLAGS"),
        ("line too long", CRX10.replace(b"100 200", b"100 200" + b" " * 3000), "CRX.LINE_TOO_LONG"),
        ("too many types", CRX10.replace(b"     2    C1    L1", b"   101    C1    L1"), "CRX.MAXTYPE"),
    ]

    def test_cases(self):
        for name, data, rule in self.cases:
            with self.subTest(name):
                self.assertEqual(_err(crx_to_rnx, data), rule)


class TestEncodeErrors(unittest.TestCase):
    cases = [
        ("navigation file", RNX10.replace(b"OBSERVATION DATA", b"NAVIGATION DATA "), "CRX.ENC.HEADER"),
        ("empty", b"", "CRX.ENC.HEADER"),
        ("no end of header", RNX10[:RNX10.index(b"END OF HEADER") - 60], "CRX.ENC.EOF"),
        ("misplaced point", RNX10.replace(b"  20000000.123 ", b"  2000000.0123 "), "CRX.ENC.FIELD"),
        ("garbage digits", RNX10.replace(b"  20000000.123 ", b"  200 0000.123 "), "CRX.ENC.FIELD"),
        ("ampersand flag", RNX10.replace(b"  21000000.0001", b"  21000000.000&"), "CRX.ENC.FIELD"),
        ("rinex 2 blank with flags", RNX10.replace(b"  20999999.9951",
                                                   b"  20999999.9951" + b" " * 15 + b"1"),
         "CRX.ENC.FLAG2"),
        ("duplicate satellite", RNX10.replace(b"0  2G01G02", b"0  2G01G01"), "CRX.ENC.DUPSAT"),
        ("undefined system", RNX30.replace(b"E11  ", b"J11  "), "CRX.ENC.SYS"),
        ("bad clock", RNX10.replace(b"  .123456789", b" .1234567890"), "CRX.ENC.CLOCK"),
        ("clock bug", RNX10.replace(b"  .123456789", b" -.100000000"), "CRX.ENC.CLOCKBUG"),
        ("picosecond stops", RNX31.replace(b"  .000123456789 01235", b"  .000123456789"),
         "CRX.ENC.PICOSEC"),
        ("picosecond not digits", RNX31.replace(b" 01234", b" 01x34"), "CRX.ENC.PICOSEC"),
        ("truncated", RNX10[:RNX10.rindex(b"       -12.345")], "CRX.ENC.EOF"),
        ("trailing empty line", RNX10 + b"\n", "CRX.ENC.EPOCH"),
        ("nul", RNX10.replace(b"A COMMENT", b"A\x00COMMENT"), "CRX.ENC.NUL"),
        ("satellite count", RNX10.replace(b"0  2G01G02", b"0  3G01G02"), "CRX.ENC.SATLIST"),
        ("ampersand in epoch line", RNX30.replace(b"> 2026 10 30 00 00 30.0000000  0  2",
                                                  b"> 2026 10 30 00 00 30.0000000  0  2 &"),
         "CRX.ENC.AMP"),
        ("too many fields", RNX30.replace(b"E11  23000000.000                 5",
                                          b"E11  23000000.000                 5"
                                          b"     1.000  1.000"), "CRX.ENC.NFIELD"),
    ]

    def test_cases(self):
        for name, data, rule in self.cases:
            with self.subTest(name):
                self.assertEqual(_err(rnx_to_crx, data), rule)


class TestCrinex31Fixture(unittest.TestCase):
    """The RINEX 4.02 picosecond fixture (generated here, archived with its oracle result)."""

    def setUp(self):
        self.rnx = make_rinex402_fixture()
        self.arch = load_archive().get("fixtures", {}).get("rinex402_picosec")

    def test_round_trip(self):
        crx = rnx_to_crx(self.rnx, program="rinexcore fixture", date=DATE)
        self.assertTrue(crx.startswith(b"3.1                 COMPACT RINEX FORMAT"))
        self.assertEqual(crx_to_rnx(crx), self.rnx)
        self.assertEqual(crx_to_rnx(rnx_to_crx(crx_to_rnx(crx))), self.rnx)

    def test_archive(self):
        if self.arch is None:
            self.skipTest("fixture not archived yet (tools/check_hatanaka.py fixtures)")
        self.assertEqual(sha(self.rnx), self.arch["rinex_sha256"])
        crx = rnx_to_crx(self.rnx, program="rinexcore fixture", date=DATE)
        self.assertEqual(sha(crx), self.arch["crx_sha256"])
        res = self.arch["crx2rnx"]
        self.assertEqual(res["exit_code"], 0)
        self.assertEqual(res["sha256_lf"], self.arch["rinex_sha256"],
                         "CRX2RNX did not give the fixture back")

    def test_oracle_live(self):
        exe = find_crx2rnx()
        if not exe:
            self.skipTest("CRX2RNX.exe not available")
        crx = rnx_to_crx(self.rnx, program="rinexcore fixture", date=DATE)
        code, out, err = run_crx2rnx(exe, crx)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, self.rnx)


class TestFuzz(unittest.TestCase):
    """Seeded mutations: nothing but CorruptError may escape (PLAN §1 clause 1)."""

    # includes latin-1 bytes such as superscripts (0xB2 0xB3 0xB9), for which
    # str.isdigit() is True but int() fails; the codec only works on bytes.
    POOL = b" 0123456789&->G\n.\r\x00\x1aE\xb2\xb3\xb9\xbd\xe9\xff"

    def mutate(self, rnd, data):
        lines = data.split(b"\n")
        op = rnd.randrange(6)
        if op == 0 and data:
            i = rnd.randrange(len(data))
            return data[:i] + bytes([rnd.choice(self.POOL)]) + data[i + 1:]
        if op == 1 and len(lines) > 1:
            del lines[rnd.randrange(len(lines))]
        elif op == 2:
            return data[:rnd.randrange(len(data) + 1)]
        elif op == 3:
            i = rnd.randrange(len(lines))
            lines.insert(i, lines[rnd.randrange(len(lines))])
        elif op == 4 and data:
            i = rnd.randrange(len(data))
            return data[:i] + bytes(rnd.choice(self.POOL) for _ in range(rnd.randint(1, 4))) + data[i:]
        else:
            i, j = rnd.randrange(len(lines)), rnd.randrange(len(lines))
            lines[i], lines[j] = lines[j], lines[i]
        return b"\n".join(lines)

    def test_decoder(self):
        rnd = random.Random(20261030)
        sources = [c for c, _ in HANDMADE.values()]
        sources.append(rnx_to_crx(make_rinex402_fixture(), date=DATE))
        n_ok = 0
        for k in range(1500):
            data = rnd.choice(sources)
            for _ in range(rnd.randint(1, 3)):
                data = self.mutate(rnd, data)
            try:
                crx_to_rnx(data)
                n_ok += 1
            except CorruptError:
                pass
            except Exception as exc:  # pragma: no cover - the failure being tested for
                self.fail(f"case {k}: {type(exc).__name__}: {exc}\n{data!r}")
        self.assertGreater(n_ok, 10)         # some mutations stay valid

    def test_high_bytes_in_digit_positions(self):
        """Every kind of digit (counts, values, clock, picosecond, version, flags)
        replaced by a byte 0x80-0xFF: only CorruptError may escape, and a byte that
        is accepted must come back unchanged (it can only be in copied text)."""
        rnd = random.Random(80)
        sources = ([(crx_to_rnx, c) for c, _ in HANDMADE.values()]
                   + [(rnx_to_crx, r) for _, r in HANDMADE.values()]
                   + [(rnx_to_crx, make_rinex402_fixture())])
        for fn, data in sources:
            digits = [i for i, b in enumerate(data) if 48 <= b <= 57]
            for i in rnd.sample(digits, min(150, len(digits))):
                for hb in (0xB2, 0xB9, 0xFF):
                    bad = data[:i] + bytes([hb]) + data[i + 1:]
                    try:
                        out = fn(bad)
                    except CorruptError:
                        continue
                    except Exception as exc:  # pragma: no cover
                        self.fail(f"{fn.__name__} offset {i} byte {hb:#x}: "
                                  f"{type(exc).__name__}: {exc}")
                    if fn is rnx_to_crx:
                        self.assertIn(bytes([hb]), crx_to_rnx(out))

    def test_encoder(self):
        rnd = random.Random(42)
        sources = [r for _, r in HANDMADE.values()]
        sources.append(make_rinex402_fixture())
        n_ok = 0
        for k in range(800):
            data = rnd.choice(sources)
            for _ in range(rnd.randint(1, 2)):
                data = self.mutate(rnd, data)
            try:
                crx = rnx_to_crx(data, date=DATE)
            except CorruptError:
                continue
            except Exception as exc:  # pragma: no cover
                self.fail(f"case {k}: {type(exc).__name__}: {exc}\n{data!r}")
            n_ok += 1
            # whatever the encoder accepts, the decoder must read, and the
            # decoded file must survive another round trip unchanged
            try:
                r1 = crx_to_rnx(crx)
                self.assertEqual(crx_to_rnx(rnx_to_crx(r1, date=DATE)), r1)
            except CorruptError as exc:
                self.fail(f"case {k}: our own CRX was refused: {exc}\n{data!r}")
        self.assertGreater(n_ok, 10)


def _corpus_entries():
    if not (os.path.isfile(MANIFEST) and os.path.isdir(CORPUS)):
        return []
    with open(MANIFEST, "rb") as f:
        files = [e for e in json.loads(f.read().decode("utf-8"))["files"] if e.get("crx")]
    files = [e for e in files if os.path.isfile(os.path.join(CORPUS, e["path"]))]
    if os.environ.get("HATANAKA_FULL_CORPUS") == "1":
        return sorted(files, key=lambda e: e["path"])
    smallest = {}
    for e in files:
        key = (e["crx"], e["version"])
        if key not in smallest or e["bytes"] < smallest[key]["bytes"]:
            smallest[key] = e
    return [smallest[k] for k in sorted(smallest)]


def _load_corpus(e):
    from rinexcore.io.compress import unwrap
    with open(os.path.join(CORPUS, e["path"]), "rb") as f:
        return unwrap(f.read())[0]


class TestCorpusArchive(unittest.TestCase):
    """Our decoder against the archived CRX2RNX digests (no exe needed)."""

    def test_archive_metadata(self):
        a = load_archive()
        self.assertEqual(a["tool"], "CRX2RNX")
        self.assertEqual(a["version"], "4.2.0")
        self.assertEqual(a["exe_sha256"],
                         "bd8f57ce6a314764305a038816e643d9b7d8759f702197108e65fb732e7f1cca")
        self.assertEqual(len(a["files"]), 299)
        self.assertTrue(all(v["exit_code"] == 0 and v["lone_cr"] == 0
                            for v in a["files"].values()))

    def test_decoder_matches_archive(self):
        entries = _corpus_entries()
        if not entries:
            self.skipTest("data/corpus not present")
        arch = load_archive()["files"]
        for e in entries:
            with self.subTest(e["path"]):
                crx = _load_corpus(e)
                a = arch[e["path"]]
                self.assertEqual(sha(crx), a["crx_sha256"])
                h = hashlib.sha256()
                for chunk in iter_crx_to_rnx(crx):
                    h.update(chunk)
                self.assertEqual(h.hexdigest(), a["sha256_lf"])

    def test_encoder_round_trip_sample(self):
        entries = _corpus_entries()
        if not entries:
            self.skipTest("data/corpus not present")
        for e in entries[:4] if os.environ.get("HATANAKA_FULL_CORPUS") != "1" else entries:
            with self.subTest(e["path"]):
                rnx = crx_to_rnx(_load_corpus(e))
                self.assertEqual(crx_to_rnx(rnx_to_crx(rnx)), rnx)


class TestOracleLive(unittest.TestCase):
    """CRX2RNX.exe itself; skipped when it is missing."""

    @classmethod
    def setUpClass(cls):
        cls.exe = find_crx2rnx()
        if not cls.exe:
            raise unittest.SkipTest("CRX2RNX.exe not available")

    def test_handmade_fixtures(self):
        for name, (crx, rnx) in HANDMADE.items():
            with self.subTest(name):
                code, out, err = run_crx2rnx(self.exe, crx)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(out, rnx)

    def test_quirks_agree(self):
        for crx in (CRX10.replace(b"3&-12345 3&-50", b"3&-12345 3&-000123"),
                    CRX10.replace(b"3&-5\n", b"3&-100000000\n")):
            code, out, err = run_crx2rnx(self.exe, crx)
            self.assertEqual(code, 0)
            self.assertEqual(out, crx_to_rnx(crx))

    def test_refusals_are_oracle_errors_too(self):
        """Inputs we refuse because CRX2RNX itself stops with an error."""
        names = {"not crinex", "crinex 2.0", "empty", "no end of header", "bad rinex version",
                 "truncated epoch", "new sat no init", "blank then no init",
                 "undefined system", "arc order 6", "range", "event not followed by init",
                 "more than 100 satellites", "picosecond too long", "too many types"}
        for name, data, rule in TestDecodeErrors.cases:
            if name in names:
                with self.subTest(name):
                    code, out, err = run_crx2rnx(self.exe, data)
                    self.assertNotEqual(code, 0, err)

    def test_differential_fuzz(self):
        """Whenever we decode a mutated file, CRX2RNX must give the same bytes."""
        rnd = random.Random(99)
        fuzz = TestFuzz()
        # no CR / ^Z (the exe's text-mode stdin treats them differently); 0x80-0xFF pass
        fuzz.POOL = b" 0123456789&->G\n.E\xb2\xb9\xff"
        sources = [c for c, _ in HANDMADE.values()]
        agree = refused_by_us_only = 0
        for k in range(150):
            data = rnd.choice(sources)
            data = fuzz.mutate(rnd, data)
            try:
                ours = crx_to_rnx(data)
            except CorruptError:
                code, out, err = run_crx2rnx(self.exe, data)
                if code == 0 and not err:
                    refused_by_us_only += 1
                continue
            code, out, err = run_crx2rnx(self.exe, data)
            self.assertEqual((code, out), (0, ours), f"case {k}: {err}\n{data!r}")
            agree += 1
        self.assertGreater(agree, 5)

    def test_encoder_differential_fuzz(self):
        """Whatever our encoder accepts, CRX2RNX reads exactly as our decoder does."""
        rnd = random.Random(1234)
        fuzz = TestFuzz()
        fuzz.POOL = b" 0123456789&->G\n.E\xb2\xb9\xff"
        sources = [r for _, r in HANDMADE.values()] + [make_rinex402_fixture()]
        accepted = 0
        for k in range(120):
            data = fuzz.mutate(rnd, rnd.choice(sources))
            try:
                crx = rnx_to_crx(data, date=DATE)
            except CorruptError:
                continue
            accepted += 1
            code, out, err = run_crx2rnx(self.exe, crx)
            self.assertEqual((code, out), (0, crx_to_rnx(crx)), f"case {k}: {err}\n{data!r}")
        self.assertGreater(accepted, 5)

    def test_encoder_output_on_corpus_sample(self):
        for e in _corpus_entries()[:4]:
            with self.subTest(e["path"]):
                rnx = crx_to_rnx(_load_corpus(e))
                code, out, err = run_crx2rnx(self.exe, rnx_to_crx(rnx))
                self.assertEqual(code, 0, err)
                self.assertTrue(out == rnx)


RNX2CRX_ARCHIVE = os.path.join(ROOT, "tests", "oracle", "rnx2crx_sha256.json")


class TestRnx2crxArchive(unittest.TestCase):
    """RNX2CRX 4.2.0's results, archived by `tools/check_hatanaka.py rnx2crx` (PLAN §1.5c),
    checked without the exe."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(RNX2CRX_ARCHIVE):
            raise unittest.SkipTest("RNX2CRX results not archived yet")
        with open(RNX2CRX_ARCHIVE, "rb") as f:
            cls.arch = json.loads(f.read().decode("utf-8"))

    def test_crinex31_made_by_rnx2crx(self):
        """PLAN M1: the corpus has no CRINEX 3.1 file, so RNX2CRX 4.2.0's own encoding of the
        RINEX 4.02 picosecond fixture is kept in full: our decoder gives the fixture back, and
        our encoder writes the same bytes apart from line 2."""
        fx = self.arch["fixtures"]["rinex402_picosec"]
        crx = fx["crx"].encode("latin-1")
        rnx = make_rinex402_fixture()
        self.assertEqual((fx["exit_code"], fx["stderr"], fx["lone_cr"]), (0, "", 0))
        self.assertEqual(sha(rnx), fx["rinex_sha256"])
        self.assertEqual(sha(crx), fx["crx_sha256_lf"])
        self.assertEqual(crx[:3], b"3.1")
        self.assertEqual(crx_to_rnx(crx), rnx)
        self.assertEqual(body(rnx_to_crx(rnx, date=DATE)), body(crx))

    def test_every_corpus_obs_file(self):
        """RNX2CRX(r) and our rnx_to_crx(r) agree byte for byte apart from line 2, and our
        decoder reads RNX2CRX's output back, for every corpus obs file (CRX files decoded,
        plain files as they are)."""
        files = self.arch["files"]
        with open(MANIFEST, "rb") as f:
            obs = [e for e in json.loads(f.read().decode("utf-8"))["files"] if e["kind"] == "obs"]
        self.assertEqual(sorted(files), sorted(e["path"] for e in obs))
        bad = {p: (r["exit_code"], r["ours"], r["decodes_back"]) for p, r in files.items()
               if not (r["exit_code"] == 0 and r["lone_cr"] == 0 and r["ours"] == "identical"
                       and r["decodes_back"])}
        # RNX2CRX 4.2.0 refuses a version field written '2.1' (docs/HATANAKA.md section 9),
        # which our encoder reads as 2.10: ebre1800.10d and sulp1800.10d
        v21 = {e["path"] for e in obs if e["version_str"] == "2.1"}
        self.assertEqual(len(v21), 2)
        self.assertEqual(set(bad), v21)
        for p in v21:
            self.assertEqual(files[p]["exit_code"], 1)
            self.assertIn("2.1            OBSERVATION DATA", files[p]["stderr"])

    def test_corpus_sample_offline(self):
        """With the corpus but without the exe: our encoder's output, line 2 aside, has the
        digest RNX2CRX's had."""
        if not os.path.isdir(CORPUS):
            self.skipTest("data/corpus (gitignored) is not here")
        for e in _corpus_entries()[:3]:
            with self.subTest(e["path"]):
                rnx = crx_to_rnx(_load_corpus(e))
                a = self.arch["files"][e["path"]]
                self.assertEqual(sha(rnx), a["rinex_sha256"])
                self.assertEqual(sha(body(rnx_to_crx(rnx))), a["sha256_body"])


class TestRnx2crxLive(unittest.TestCase):
    """RNX2CRX.exe itself (with CRX2RNX.exe for the round trips); skipped when missing."""

    @classmethod
    def setUpClass(cls):
        cls.exe = find_rnx2crx()
        if not cls.exe:
            raise unittest.SkipTest("RNX2CRX.exe not available")
        cls.dec = find_crx2rnx()

    def test_handmade_same_bytes_as_ours(self):
        for name, (_crx, rnx) in HANDMADE.items():
            with self.subTest(name):
                code, out, err = run_rnx2crx(self.exe, rnx)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(body(out), body(rnx_to_crx(rnx, date=DATE)))
                self.assertEqual(crx_to_rnx(out), rnx)

    def test_our_refusals(self):
        """Every input our encoder refuses (TestEncodeErrors) is one the official pair cannot
        carry either: RNX2CRX stops with an error or warning, or CRX2RNX does not give the
        input back (docs/HATANAKA.md section 9)."""
        if not self.dec:
            self.skipTest("CRX2RNX.exe not available")
        for name, data, rule in TestEncodeErrors.cases:
            with self.subTest(name, rule=rule):
                code, out, err = run_rnx2crx(self.exe, data)
                if code != 0:
                    continue
                c2, back, err2 = run_crx2rnx(self.dec, out)
                self.assertFalse(c2 == 0 and back == data,
                                 f"RNX2CRX and CRX2RNX carry {name!r}, which we refuse ({rule})")

    def test_differential_fuzz(self):
        """Whatever our encoder accepts, RNX2CRX encodes to the same bytes (line 2 aside),
        except where docs/HATANAKA.md section 9 says the encoder is more lenient: a file
        without a final LF, which RNX2CRX takes for truncated."""
        rnd = random.Random(4242)
        fuzz = TestFuzz()
        fuzz.POOL = b" 0123456789&->G\n.E\xb2\xb9\xff"
        sources = [r for _, r in HANDMADE.values()] + [make_rinex402_fixture()]
        accepted = lenient = 0
        for k in range(120):
            data = fuzz.mutate(rnd, rnd.choice(sources))
            try:
                ours = rnx_to_crx(data, date=DATE)
            except CorruptError:
                continue
            accepted += 1
            code, out, err = run_rnx2crx(self.exe, data)
            if code != 0 and not data.endswith(b"\n"):
                lenient += 1
                self.assertEqual(crx_to_rnx(ours), crx_to_rnx(rnx_to_crx(data + b"\n")))
                continue
            if code == 0 and body(out) != body(ours) and re.search(rb" -0+\d*\.\d{3}", data):
                lenient += 1          # RNX2CRX loses the sign there (test_minus_with_leading_zeros)
                continue
            self.assertEqual((code, body(out)), (0, body(ours)), f"case {k}: {err}\n{data!r}")
        self.assertGreater(accepted - lenient, 5)

    def test_minus_with_leading_zeros(self):
        """docs/HATANAKA.md section 9: RNX2CRX loses the sign of `-0000000.123` (it encodes
        +0.123); our encoder keeps the true value (found by a 3,000-case differential fuzz,
        2026-11-01)."""
        rnx = RNX10.replace(b"  20000000.123 ", b"  -0000000.123 ")
        self.assertNotEqual(rnx, RNX10)
        code, out, err = run_rnx2crx(self.exe, rnx)
        self.assertEqual(code, 0, err)
        self.assertIn(b"  .123 ", crx_to_rnx(out))          # the sign is gone
        self.assertIn(b" -.123 ", crx_to_rnx(rnx_to_crx(rnx)))   # ours keeps it


if __name__ == "__main__":
    unittest.main()
