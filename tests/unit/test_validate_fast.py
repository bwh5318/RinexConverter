"""The validator's speed-ups give exactly the findings of the per-line checks they stand in for
(rinexcore/validate.py): the chunk screen of observation fields (_Reader.screen_fields,
_fields_bad), whole RINEX 2 records at once (_Reader.take), canonical navigation numbers
(_nav_fast) and met values (_met_fast).

Each speed-up is switched off, so that every line takes the per-line path, and the findings
(rule, severity, message, line, column, scope, in order, with the per-rule cap) are compared
with those of the normal run, on valid and damaged samples, also with chunks of a few hundred
bytes so that chunk boundaries fall everywhere. Standard library unittest; runs under pytest.
"""

import random
import unittest
from unittest import mock

import rinexcore.validate as V
from rinexcore.errors import CorruptError

from .test_validate import MET10, met, nav_v2_glonass, nav_v2_gps, nav_v3, nav_v4, payload, v2_obs, v3_obs, v4_obs


def findings(data, cap=V.DEFAULT_MAX_PER_RULE):
    try:
        return [(f.severity, f.rule, f.message, f.line, f.column, f.scope) for f in V.validate(data, cap)]
    except CorruptError as e:
        return ("corrupt", str(e))


def per_line(data, cap=V.DEFAULT_MAX_PER_RULE):
    """findings() with every speed-up off."""
    def flag_all(lines, start, off, first):
        return set(range(first, first + len(lines) - start))
    with mock.patch.object(V, "_fields_bad", flag_all), \
            mock.patch.object(V._Reader, "take", lambda self, k: None), \
            mock.patch.object(V, "_nav_fast", lambda letters: None), \
            mock.patch.object(V, "_met_fast", lambda k: (lambda line, a: None)):
        return findings(data, cap)


ALPHA = " 0123456789.-+>DdEexGR\t\r\xb2"


def damage(data, rng):
    """1-12 edits, mostly in the data section: characters, LLI/SSI columns, exponent letters,
    line length, duplicated/deleted/swapped lines."""
    lines = data.decode("latin-1").split("\n")
    h = next((i for i, x in enumerate(lines) if "END OF HEADER" in x), 0)
    for _ in range(rng.randint(1, 12)):
        k = rng.randrange(h + 1, len(lines)) if len(lines) > h + 1 and rng.random() < 0.9 \
            else rng.randrange(len(lines))
        x = lines[k]
        p = rng.randrange(len(x) + 1)
        op = rng.randrange(9)
        if op == 0 and x:
            x = x[:p] + rng.choice(ALPHA) + x[p + 1:]
        elif op == 1:
            x = x[:p] + rng.choice(ALPHA) + x[p:]
        elif op == 2:
            x = x[:p] + x[p + 1:]
        elif op == 3:
            x = x[:p]
        elif op == 4:
            x = x + "".join(rng.choice(ALPHA) for _ in range(rng.randint(1, 20)))
        elif op == 5:                                       # an LLI or SSI column
            q = 16 * rng.randrange(6) + rng.choice((14, 15)) + rng.choice((0, 3))
            if q < len(x):
                x = x[:q] + rng.choice("0123456789 x") + x[q + 1:]
        elif op == 6:                                       # another exponent letter
            x = x.replace(rng.choice("DE"), rng.choice("DdEe"), rng.randint(1, 3))
        elif op == 7:
            j = min(len(lines) - 1, k + 1)
            lines[k], lines[j] = lines[j], lines[k]
            continue
        else:
            if rng.random() < 0.5:
                lines.insert(k, x)
            else:
                del lines[k]
            continue
        lines[k] = x
    return "\n".join(lines).encode("latin-1")


SAMPLES = [v2_obs(), v2_obs("2.10"), v3_obs(), v3_obs("3.02"), v4_obs(), nav_v2_gps(), nav_v2_glonass(),
           nav_v3(), nav_v4(), nav_v4("4.00", "D"), met("2.11"), met("3.05", MET10)]


class SpeedUpsGiveTheSameFindings(unittest.TestCase):
    def compare(self, data, cap=V.DEFAULT_MAX_PER_RULE):
        self.assertEqual(findings(data, cap), per_line(data, cap))

    def test_valid_samples(self):
        for lines in SAMPLES:
            data = payload(lines)
            with self.subTest(lines[0]):
                self.compare(data)
                self.compare(data.replace(b"\n", b"\r\n"))

    def test_damaged_samples(self):
        rng = random.Random(20261103)
        for i, lines in enumerate(SAMPLES):
            src = payload(lines)
            for case in range(60):
                data = damage(src, rng)
                cap = 2 if case % 5 == 0 else V.DEFAULT_MAX_PER_RULE
                with self.subTest(sample=i, case=case):
                    self.compare(data, cap)

    def test_small_chunks(self):
        """Chunk boundaries inside epochs, records and pushed-back lines."""
        rng = random.Random(7)
        for chunk in (97, 256, 1000):
            with mock.patch.object(V._Reader, "CHUNK", chunk):
                for i, lines in enumerate(SAMPLES):
                    src = payload(lines)
                    for case in range(15):
                        data = src if case == 0 else damage(src, rng)
                        with self.subTest(chunk=chunk, sample=i, case=case):
                            self.compare(data)

    def test_very_long_lines(self):
        """Lines longer than _SCREEN_MAX (here a record and the whole data section joined by
        CR-only line ends) take the per-line path."""
        for lines in (v3_obs(), v2_obs()):
            h = next(i for i, x in enumerate(lines) if "END OF HEADER" in x)
            x = list(lines)
            x[h + 2] = x[h + 2] + "  22000000.105 7" * 300
            self.compare(payload(x))
            cr = "\n".join(lines[:h + 1]) + "\n" + "\r".join(lines[h + 1:] * 40) + "\n"
            self.compare(cr.encode("latin-1"))

    def test_mixed_exponent_letters(self):
        """The navigation fast path must not skip the first line of a new exponent letter, and
        the letters keep their first lines and order (VAL.NAV.EXPONENT.MIXED, .DEPRECATED)."""
        for make in (nav_v3, nav_v4):
            lines = make()
            h = next(i for i, x in enumerate(lines) if "END OF HEADER" in x)
            for k in range(h + 1, len(lines)):
                for a, b in (("E", "D"), ("E", "e"), ("E", "d")):
                    x = list(lines)
                    x[k] = x[k].replace(a, b)
                    with self.subTest(make.__name__, line=k, letter=b):
                        f = findings(payload(x))
                        self.assertEqual(f, per_line(payload(x)))


class FieldScreen(unittest.TestCase):
    """_fields_bad never passes a text that _OBS_FIELDS rejects, nor flags one it accepts."""

    def field(self, rng):
        if rng.random() < 0.2:
            v = " " * 14
        else:
            num = f"{rng.uniform(-1e9, 1e10):.3f}" if rng.random() < 0.6 else \
                f"{rng.choice(['', '-'])}{rng.randint(0, 10 ** rng.randint(0, 9))}.{rng.randint(0, 999):03d}"
            if rng.random() < 0.2:
                num = num.replace("0.", ".", 1)
            v = num.rjust(14)[-14:]
        return v + rng.choice(" 01234567") + rng.choice(" 0123456789")

    def test_agrees_with_the_regex(self):
        rng = random.Random(3)
        texts = []
        for n in range(0, 40):                         # short texts over a small alphabet
            for _ in range(300):
                texts.append("".join(rng.choice(" 0123456789-.x+") for _ in range(n)))
        for _ in range(20000):                         # fields, cut and damaged
            s = "".join(self.field(rng) for _ in range(rng.randint(0, 6)))
            if rng.random() < 0.5:
                s = s[:rng.randint(0, len(s))]
            if s and rng.random() < 0.6:
                p = rng.randrange(len(s))
                s = s[:p] + rng.choice(" 0123456789.-+x\r\t\xb289") + s[p + 1:]
            texts.append(s)
        # longer than _SCREEN_MAX: always left to the regex
        texts += [self.field(rng) * 300, " " * 5000, "x" * 4100, (" " * 16) * 256]
        rng.shuffle(texts)
        for off in (0, 3):
            lines = ["G01"[:off] + s for s in texts]
            bad = V._fields_bad(lines, 0, off, 1)
            for k, s in enumerate(texts):
                passed, ok = k + 1 not in bad, bool(V._OBS_FIELDS(s))
                if passed and not ok or (ok and not passed and len(lines[k]) <= V._SCREEN_MAX):
                    self.fail(f"off {off}: {s[:100]!r} regex {ok}, screen {passed}")
                if len(lines[k]) > V._SCREEN_MAX:
                    self.assertFalse(passed)

    def test_screened_prefix_is_accepted(self):
        """A line the screen passes is accepted when cut after any whole field (the scans cut
        records to their type count)."""
        rng = random.Random(5)
        for _ in range(3000):
            s = "".join(self.field(rng) for _ in range(rng.randint(1, 8)))
            if not V._fields_bad([s], 0, 0, 1):
                for w in range(0, len(s) + 16, 16):
                    self.assertTrue(V._OBS_FIELDS(s[:w]), (s, w))

    def test_reader_screen_with_a_pushed_back_line(self):
        data = payload(v3_obs())
        with mock.patch.object(V._Reader, "CHUNK", 300):
            rd = V._Reader(data)
            while not rd.next().startswith(">"):
                pass
            x = rd.next()
            rd.back(x)
            rd.screen_fields(3)
            self.assertEqual(rd.lo, rd.n + 1)
            self.assertIs(rd.next(), x)
            n = rd.n
            while True:
                line = rd.next()
                if line is None:
                    break
                n += 1
                self.assertEqual(rd.n, n)
                self.assertTrue(rd.lo <= n <= rd.hi)
                self.assertEqual(n not in rd.bad, bool(V._OBS_FIELDS(line[3:])), line)

    def test_take_and_untake(self):
        rd = V._Reader(b"a\nb\nc\nd\n")
        self.assertEqual(rd.next(), "a")
        self.assertEqual(rd.take(2), ["b", "c"])
        self.assertEqual(rd.n, 3)
        rd.untake(2)
        self.assertEqual((rd.next(), rd.n), ("b", 2))
        rd.back("b")
        self.assertIsNone(rd.take(1))               # a pushed-back line is read by next()
        self.assertEqual((rd.next(), rd.n), ("b", 2))
        self.assertIsNone(rd.take(5))               # more than the chunk holds
        self.assertEqual([rd.next(), rd.next(), rd.next()], ["c", "d", None])


if __name__ == "__main__":
    unittest.main()
