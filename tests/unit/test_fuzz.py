"""Seeded fuzzing (PLAN §4 "Fuzz"): byte flips, truncation, column shifts, label damage.

Whatever the damage, conversion either succeeds or raises a RinexError (one of
the named refusals); no other exception may escape (PLAN §1 clause 1).
"""

import random
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore.errors import RinexError

from .test_nav_fixtures import GLO_304, SPEC_211, SPEC_305
from .test_obs_fixtures import V211, V305

SEEDS = int(__import__("os").environ.get("RINEX_FUZZ_SEEDS", "150"))


def mutate(data, rng):
    b = bytearray(data)
    op = rng.randrange(7)
    if op == 0:                                  # flip some bytes
        for _ in range(rng.randint(1, 8)):
            b[rng.randrange(len(b))] = rng.randrange(256)
    elif op == 1:                                # truncate
        del b[rng.randrange(len(b)):]
    elif op == 2:                                # delete a line
        lines = bytes(b).split(b"\n")
        del lines[rng.randrange(len(lines))]
        b = bytearray(b"\n".join(lines))
    elif op == 3:                                # shift a line by one column
        lines = bytes(b).split(b"\n")
        k = rng.randrange(len(lines))
        lines[k] = (b" " + lines[k]) if rng.random() < 0.5 else lines[k][1:]
        b = bytearray(b"\n".join(lines))
    elif op == 4:                                # damage a header label
        i = bytes(b).find(b"END OF HEADER" if rng.random() < 0.3 else b"OBS")
        if i >= 0:
            b[i] = ord("X")
    elif op == 5:                                # duplicate a line
        lines = bytes(b).split(b"\n")
        k = rng.randrange(len(lines))
        lines.insert(k, lines[k])
        b = bytearray(b"\n".join(lines))
    else:                                        # replace digits with letters
        for _ in range(3):
            i = rng.randrange(len(b))
            if chr(b[i]).isdigit():
                b[i] = ord("x")
    return bytes(b)


class Fuzz(unittest.TestCase):
    def run_cases(self, src, name, targets):
        rng = random.Random(name)
        for k in range(SEEDS):
            data = mutate(src, rng)
            for t in targets:
                with self.subTest(case=k, target=t):
                    for lenient in (False, True):
                        try:
                            convert_data(data, name, Options(t, compression="none", lenient=lenient,
                                                             assume_phase_aligned=True,
                                                             drop_unresolvable=True))
                        except RinexError:
                            pass

    def test_obs_v2(self):
        self.run_cases(V211, "f0010.26o", ("3.05", "2.11"))

    def test_obs_v3(self):
        self.run_cases(V305, "F.rnx", ("2.11", "4.02"))

    def test_nav(self):
        self.run_cases(SPEC_211, "f.99n", ("3.05", "4.02"))
        self.run_cases(SPEC_305, "f.rnx", ("2.11", "4.01"))
        self.run_cases(GLO_304, "g.rnx", ("3.05", "2.10"))

    def test_wrappers(self):
        from rinexcore.io import compress
        for wrap in (compress.gzip_bytes, compress.lzw):
            self.run_cases(wrap(V211), "f0010.26o.gz", ("3.05",))


if __name__ == "__main__":
    unittest.main()
