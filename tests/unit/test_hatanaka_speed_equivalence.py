"""The fast paths of rinexcore/io/hatanaka.py against its general code.

``hatanaka._FAST = False`` turns off the decoder's fast path (satellites kept in column form,
each line summed with map() and printed with one %-format from _out_template) and the
encoder's (column form, and the quick check of the F14.3 fields). With and without them,
every case here must give the same output bytes (also those printed before an error), the
same error (message, line, rule) and, for CrxCannotHold, the same plain_rule. The cases aim
at what the fast paths must notice and hand back: blank fields inside and after the last
value, a field going blank and coming back, flags that change, small values printed without
a leading zero, values at the F14.3 limits and past them, huge differences, `-0ddddd`
fields, arcs of other orders, cycle slips, flags `0.` after a blank field and odd
satellite ids that the small-value fix must not touch.

Run from the repository root:  python -m pytest -q tests/unit/test_hatanaka_speed_equivalence.py
"""

import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rinexcore.errors import CorruptError  # noqa: E402
from rinexcore.io import hatanaka  # noqa: E402
from tests.unit import test_hatanaka as th  # noqa: E402

H, L, fmt14, fmt15 = th.H, th.L, th.fmt14, th.fmt15
DATE = th.DATE


def _err(exc):
    return (type(exc).__name__, str(exc), exc.line, exc.rule, getattr(exc, "plain_rule", None))


def decode(data):
    """(bytes printed, error or None): iter_crx_to_rnx yields what CRX2RNX printed before
    an error."""
    out = []
    try:
        for chunk in hatanaka.iter_crx_to_rnx(data):
            out.append(chunk)
    except CorruptError as exc:
        return b"".join(out), _err(exc)
    return b"".join(out), None


def encode(data):
    try:
        return hatanaka.rnx_to_crx(data, program="speed test", date=DATE), None
    except CorruptError as exc:
        return None, _err(exc)


def both(fn, data):
    res = []
    for fast in (True, False):
        hatanaka._FAST = fast
        try:
            res.append(fn(data))
        finally:
            hatanaka._FAST = True
    return res


# ---------------------------------------------------------------- generated files
def make_rinex3(seed, nep=40, version="3.04", odd=False):
    """A RINEX 3/4 file in CRX2RNX's layout that keeps the fast paths busy and makes them
    fall back often. odd=True adds a system '-' with satellite '-0.' (an id holding the
    pattern of the small-value fix), '%' flags and flags '0.' after a blank field."""
    rnd = random.Random(seed)
    hdr = [H("     %s           OBSERVATION DATA    M" % version, "RINEX VERSION / TYPE"),
           H("G    8 C1C L1C D1C S1C C2W L2W D2W S2W", "SYS / # / OBS TYPES"),
           H("E    6 C1C L1C D1C S1C C5Q L5Q", "SYS / # / OBS TYPES"),
           H("C    5 C2I L2I D2I S2I C7I", "SYS / # / OBS TYPES")]
    if odd:
        hdr.append(H("-    3 C1C L1C D1C", "SYS / # / OBS TYPES"))
    hdr.append(th.EOH)
    nty = {"G": 8, "E": 6, "C": 5, "-": 3}
    sats = ["G01", "G05", "G12", "E03", "E11", "C20", "C33"] + (["-0."] if odd else [])
    # per satellite: fields that are always blank, value state
    always_blank = {s: {j for j in range(nty[s[0]]) if rnd.random() < 0.25} for s in sats}
    state = {}
    for s in sats:
        st = []
        for j in range(nty[s[0]]):
            kind = j % 4                      # C, L, D, S
            if kind == 0:
                v, r = rnd.randint(20000000000, 25000000000), rnd.randint(-3000000, 3000000)
            elif kind == 1:
                v, r = rnd.randint(100000000000, 130000000000), rnd.randint(-15000000, 15000000)
            elif kind == 2:
                v, r = rnd.randint(-2000, 2000), rnd.randint(-300, 300)    # small: .ddd
            else:
                v, r = rnd.randint(30000, 50000), 0
            st.append([v, r])
        state[s] = st
    flags = {s: [" " + str(rnd.randint(4, 9)) for _ in range(nty[s[0]])] for s in sats}
    lines = list(hdr)
    clock = 123456789
    for k in range(nep):
        t = 30 * k
        present = [s for s in sats if not (s == "C33" and 10 <= k < 14)]
        head = "> 2026 10 30 %02d %02d%11.7f  0%3d      " % (t // 3600, t // 60 % 60, t % 60,
                                                           len(present))
        clock += rnd.randint(-20000, 20000)
        if clock < 0 and clock % 100000000 == 0:
            clock += 1
        if k % 5 != 3:
            head += fmt15(clock)
        lines.append(head.rstrip(" ").encode("ascii") if k % 5 == 3 else head.encode("ascii"))
        for s in present:
            n = nty[s[0]]
            vals = []
            for j in range(n):
                v, r = state[s][j]
                v += r + rnd.randint(-40, 40)
                if rnd.random() < 0.01:
                    v += rnd.choice((1, -1)) * rnd.randint(10 ** 10, 10 ** 11)   # slip
                if j % 4 == 2 and rnd.random() < 0.05:
                    v = rnd.choice((0, -1, 1, 999, -999, 1000, -1000))
                if s == "E11" and j == 0 and 20 <= k < 24:
                    v = 9999999999999 if k % 2 else -999999999999           # F14.3 limits
                v = max(-999999999999, min(9999999999999, v))
                state[s][j][0] = v
                blank = (j in always_blank[s] or (s == "G05" and j == 1 and k % 7 in (2, 3))
                         or (s == "E03" and j >= n - 2 and k % 9 < 3))
                vals.append(None if blank else v)
            if rnd.random() < 0.3:
                j = rnd.randrange(n)
                flags[s][j] = rnd.choice(("1", " ")) + rnd.choice("456789 ")
            fl = list(flags[s])
            if odd and s == "G12":
                fl[0] = "%%" if k % 3 == 0 else " %"
            if odd and s == "E11":
                vals[1] = None if k % 4 < 2 else vals[1]
                fl[1] = "0." if k % 4 < 2 else fl[1]
            line = s + "".join(fmt14(v) + f for v, f in zip(vals, fl))
            lines.append(line.rstrip(" ").encode("latin-1"))
    return b"\n".join(lines) + b"\n"


def make_rinex2(seed, nep=40):
    """A RINEX 2.11 file in CRX2RNX's layout: 12 types (three lines a satellite, the last
    holding 2), blank fields with blank flags, more than 12 satellites some epochs."""
    rnd = random.Random(seed)
    types = "    L1    C1    P1    L2    P2    D1    D2    S1    S2    L5    C5    S5"
    hdr = [H("     2.11           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
           H("    12" + types[:54], "# / TYPES OF OBSERV"),
           H("      " + types[54:], "# / TYPES OF OBSERV"),
           th.EOH]
    n = 12
    sats = ["G%02d" % i for i in range(1, 15)] + ["R07", "E19"]
    always_blank = {s: {j for j in range(n) if rnd.random() < 0.35} for s in sats}
    state = {s: [[rnd.randint(20000000000, 130000000000) if j % 6 < 5 else rnd.randint(-2000, 2000),
                  rnd.randint(-3000000, 3000000) if j % 6 < 5 else rnd.randint(-200, 200)]
                 for j in range(n)] for s in sats}
    flags = {s: ["  "] * n for s in sats}
    lines = list(hdr)
    for k in range(nep):
        t = 30 * k
        present = sats if k % 6 else sats[:10]
        sl = "".join(present)
        head = " 26 10 30 %2d %2d%11.7f  0%3d" % (t // 3600, t // 60 % 60, t % 60, len(present))
        head += sl[:36]
        if k % 4:
            head = head.ljust(68) + ("%12.9f" % (rnd.randint(-99999, 99999) / 1e9)).replace(
                "0.", " .", 1).replace("- .", " -.")
        lines.append(head.encode("ascii"))
        for q in range(36, len(sl), 36):
            lines.append((" " * 32 + sl[q:q + 36]).encode("ascii"))
        for s in present:
            vals = []
            fl = []
            for j in range(n):
                v, r = state[s][j]
                v += r + rnd.randint(-30, 30)
                if rnd.random() < 0.01:
                    v += rnd.randint(10 ** 10, 10 ** 11)
                v = max(-999999999999, min(9999999999999, v))
                state[s][j][0] = v
                blank = j in always_blank[s] or (s == "G03" and j == 2 and k % 5 < 2)
                vals.append(None if blank else v)
                if not blank and rnd.random() < 0.2:
                    flags[s][j] = rnd.choice(" 1") + rnd.choice(" 56789")
                fl.append("  " if blank else flags[s][j])
            body = "".join(fmt14(v) + f for v, f in zip(vals, fl))
            for q in range(0, 16 * n, 80):
                lines.append(body[q:q + 80].rstrip(" ").encode("ascii"))
    return b"\n".join(lines) + b"\n"


POOL = b" 0123456789&-.%\n\r\x00E\xb9"


def mutate(rnd, data):
    lines = data.split(b"\n")
    hdr = next((k for k, ln in enumerate(lines) if b"END OF HEADER" in ln), 0)
    li = rnd.randrange(hdr + 1, len(lines)) if len(lines) > hdr + 2 else rnd.randrange(len(lines))
    ln = lines[li]
    op = rnd.randrange(9)
    if op == 0 and ln:                                  # one byte
        i = rnd.randrange(len(ln))
        lines[li] = ln[:i] + bytes([rnd.choice(POOL)]) + ln[i + 1:]
    elif op == 1 and ln:                                # a digit for a digit (stays valid)
        ds = [i for i, b in enumerate(ln) if 48 <= b <= 57]
        if ds:
            i = rnd.choice(ds)
            lines[li] = ln[:i] + bytes([rnd.randrange(48, 58)]) + ln[i + 1:]
    elif op == 2 and ln:                                # a CRX field for a special one
        fs = ln.split(b" ")
        fs[rnd.randrange(len(fs))] = rnd.choice(
            [b"", b"3&123456", b"2&-5", b"5&77", b"-0123456", b"-00000001", b"-0", b"0",
             b"9" * 14, b"-" + b"9" * 13, b"9" * 400, b"3&" + b"9" * 13, b"3&-" + b"9" * 12,
             b"3&10000000000000", b"3&-1000000000000", b"0."])
        lines[li] = b" ".join(fs)
    elif op == 3 and len(ln) > 3:                       # a RINEX field for a special one
        k = 3 + 16 * rnd.randrange(max(1, (len(ln) - 3) // 16 + 1))
        lines[li] = ln[:k] + rnd.choice(
            [b" " * 16, b"9999999999.999", b"-999999999.999", b"         0.000", b"          .001",
             b"   12345.6789 ", b"1234567890123.", b"       -12.345", b"           -.5",
             b"     12 45.678", b"       -.  123", b"    123456.7-8", b"        .123  ",
             b"-0000000000.12"]) + ln[k + 14:]
    elif op == 4:
        del lines[li]
    elif op == 5:
        lines.insert(li, lines[rnd.randrange(len(lines))])
    elif op == 6:
        lines[li] = ln + rnd.choice([b" ", b"   1 2", b"  0.", b" %", b"            0."])
    elif op == 7 and ln:
        lines[li] = ln[:rnd.randrange(len(ln) + 1)]
    else:
        return data[:rnd.randrange(len(data) + 1)]
    return b"\n".join(lines)


class TestGenerated(unittest.TestCase):
    def check_file(self, rnx, crinex):
        crx_f, crx_s = both(encode, rnx)
        self.assertEqual(crx_f, crx_s)
        crx, err = crx_f
        self.assertIsNone(err)
        self.assertEqual(crx[:3], crinex)
        dec_f, dec_s = both(decode, crx)
        self.assertEqual(dec_f, dec_s)
        self.assertEqual(dec_f, (rnx, None))          # rnx is in CRX2RNX's layout
        return crx

    def test_fast_path_is_taken(self):
        """The decoder fast path runs (it makes its line templates) on these files."""
        made = []
        orig = hatanaka._out_template

        def counting(*args):
            made.append(1)
            return orig(*args)

        hatanaka._out_template = counting
        try:
            for rnx in (make_rinex3(1), make_rinex2(1)):
                n = len(made)
                hatanaka.crx_to_rnx(encode(rnx)[0])
                self.assertGreater(len(made), n)
        finally:
            hatanaka._out_template = orig

    def test_rinex3(self):
        for seed in range(4):
            with self.subTest(seed=seed):
                self.check_file(make_rinex3(seed, version="3.04"), b"3.0")

    def test_rinex3_odd_ids_and_flags(self):
        rnx = make_rinex3(7, odd=True)
        self.assertIn(b"-0.", rnx)
        self.assertIn(b" " * 14 + b"0.", rnx)
        self.check_file(rnx, b"3.0")

    def test_rinex4(self):
        self.check_file(make_rinex3(11, version="4.01"), b"3.0")

    def test_rinex2(self):
        for seed in range(3):
            with self.subTest(seed=seed):
                self.check_file(make_rinex2(seed), b"1.0")

    def test_mutations(self):
        """Seeded edits of the generated files and of their CRX: both codecs, both ways."""
        rnd = random.Random(20261103)
        rnxs = [make_rinex3(21), make_rinex3(22, odd=True), make_rinex2(23)]
        crxs = [encode(r)[0] for r in rnxs] + [c for c, _ in th.HANDMADE.values()]
        n_ok = [0, 0]
        for k in range(500):
            if k % 2:
                data = rnd.choice(crxs)
                fn = decode
            else:
                data = rnd.choice(rnxs)
                fn = encode
            for _ in range(rnd.randint(1, 3)):
                data = mutate(rnd, data)
            a, b = both(fn, data)
            self.assertEqual(a, b, f"case {k} ({fn.__name__})")
            n_ok[k % 2] += a[1] is None
        self.assertGreater(min(n_ok), 20)         # enough cases that went to the end


class TestHandMade(unittest.TestCase):
    """CRX lines aimed at the decoder's hand-backs (on top of the generated files)."""

    HDR = [H("     3.04           OBSERVATION DATA    G", "RINEX VERSION / TYPE"),
           H("G    3 C1C L1C D1C", "SYS / # / OBS TYPES"), th.EOH]

    def crx(self, *body, ver=th.CRX_HDR3):
        return L(ver, th.CRX_PROG, *self.HDR, *body)

    def epochs(self, rows, last):
        """Epoch lines + one satellite with the given CRX data rows; `last` replaces the
        last row."""
        body = []
        for k, row in enumerate(rows[:-1] + [last]):
            body.append("> 2026 10 30 00 00%11.7f  0  1      G01" % (30.0 * k % 60)
                        if k == 0 else "             %2d" % (30 * k % 60))
            body.append("")
            body.append(row)
        return body

    def same(self, data):
        a, b = both(decode, data)
        self.assertEqual(a, b)
        return a

    STEADY = ["3&20000000000 3&100000000000 3&500  5 6 7",
              "1000 2000 -3", "10 20 30", "1 2 3", "4 5 6", "7 8 9"]

    def test_steady_then_edges(self):
        for last in ["1 2 3", "-0123 2 3", "-01234567 2 3", "-0 0 0", "9" * 15 + " 0 0",
                     "-" + "9" * 15 + " 0 0", "9" * 400 + " 0 0", "3&5 2 3", "1 2", "1  3",
                     " 2 3", "1 2 3 4", "1 2 3   1", "x 2 3", "1 2 -", "1 2 3&", "1 -2- 3",
                     "", "1 2 3  0."]:
            with self.subTest(last=last):
                out, err = self.same(self.crx(*self.epochs(self.STEADY, last)))
                if last == "1 2 3":
                    self.assertIsNone(err)

    def test_range_limits(self):
        # v = 10**13 - 1 prints; 10**13 is out of range; likewise -10**12 + 1 / -10**12
        base = ["3&9999999999990 3&-999999999990 3&0  5 6 7", "0 0 0", "0 0 0", "0 0 0",
                "0 0 0"]
        for last, ok in [("9 -9 0", True), ("10 0 0", False), ("0 -10 0", False),
                         ("-9999999999990 999999999990 -999", True)]:
            with self.subTest(last=last):
                out, err = self.same(self.crx(*self.epochs(base, last)))
                self.assertEqual(err is None, ok, err)

    def test_other_arc_orders(self):
        for a in "012345":
            with self.subTest(order=a):
                rows = [f"{a}&20000000000 {a}&100000000000 3&500  5 6 7"] + ["7 -3 2"] * 8
                out, err = self.same(self.crx(*self.epochs(rows, rows[-1])))
                self.assertIsNone(err)

    def test_blank_flags_crinex1(self):
        """CRINEX 1: a blank field prints, and keeps, blank flags; here its flags in the
        CRX are not blank."""
        hdr = [H("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
               H("     3    C1    L1    D1", "# / TYPES OF OBSERV"), th.EOH]
        body = ["&26 10 30  0  0  0.0000000  0  1G01", "",
                "3&20000000000 3&100000000000 3&500  1 2 3"]
        rows = ["1 2 3", "1 2 3", "1  3", "1  3  &7&&", "1  3", "1 2 3", "1  3 4567"]
        for k, row in enumerate(rows):
            body += ["                %2d" % (k + 1), "", row]
        out, err = self.same(L(th.CRX_HDR1, th.CRX_PROG, *hdr, *body))
        self.assertEqual(err[3], "CRX.BLANK_NO_INIT")
        self.assertEqual(out.count(b"\n 26 10 30"), 6)


class TestCorpusSample(unittest.TestCase):
    """A few corpus files (all with HATANAKA_FULL_CORPUS=1), when data/corpus is present."""

    def test_sample(self):
        entries = th._corpus_entries()
        if not entries:
            self.skipTest("data/corpus not present")
        if os.environ.get("HATANAKA_FULL_CORPUS") != "1":
            entries = sorted(entries, key=lambda e: e["bytes"])[:3]
        for e in entries:
            with self.subTest(e["path"]):
                crx = th._load_corpus(e)
                (rnx, err), slow = both(decode, crx)
                self.assertEqual(slow, (rnx, err))
                if err is None:
                    a, b = both(encode, rnx)
                    self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
