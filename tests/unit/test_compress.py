"""gzip and Unix compress (.Z) codecs (PLAN §3.2)."""

import gzip
import random
import unittest
from pathlib import Path

from rinexcore.errors import CorruptError
from rinexcore.io import compress

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "corpus"


class LZW(unittest.TestCase):
    def roundtrip(self, data):
        enc = compress.lzw(data)
        self.assertEqual(enc[:3], b"\x1f\x9d\x90")
        self.assertEqual(compress.unlzw(enc), data)

    def test_small(self):
        for d in (b"", b"a", b"abababababab", b"TOBEORNOTTOBEORTOBEORNOT", bytes(range(256)) * 3):
            self.roundtrip(d)

    def test_table_full_and_clear(self):
        """Enough random data to fill the 16-bit table and trigger the ratio-check CLEAR."""
        rng = random.Random(7)
        data = bytes(rng.getrandbits(8) for _ in range(300_000))
        self.roundtrip(data)
        text = b"".join(b"%d %f\n" % (i, rng.random()) for i in range(40_000))
        self.roundtrip(text)

    def test_truncated_and_garbage(self):
        enc = compress.lzw(b"hello world " * 1000)
        for bad in (b"\x1f\x9d", b"\x1f\x9d\x05xxxx", enc[:3] + b"\xff\xff\xff\xff"):
            with self.assertRaises(CorruptError):
                compress.unlzw(bad)

    @unittest.skipUnless(CORPUS.is_dir(), "corpus not present")
    def test_reencode_matches_compress1(self):
        """Our encoder reproduces the CDDIS .Z files byte for byte (they were made by compress(1))."""
        files = sorted(CORPUS.glob("met/*/*.Z"))[:20]
        self.assertTrue(files)
        for f in files:
            z = f.read_bytes()
            raw = compress.unlzw(z)
            self.assertEqual(compress.lzw(raw), z, f.name)


class Gzip(unittest.TestCase):
    def test_concatenated_members(self):
        d = gzip.compress(b"abc") + gzip.compress(b"def")
        self.assertEqual(compress.gunzip(d), b"abcdef")

    def test_member_ending_at_the_piece_limit(self):
        # Sol round 10: a member whose output passes the 16 MiB piece by one byte ends while
        # zlib keeps the next member in unconsumed_tail as well as unused_data: the loop
        # spun forever. Python's gzip skips zero padding between members too.
        big = gzip.compress(b"a" * (2 ** 24 + 1))
        for tail in (gzip.compress(b"next"), b"\x00" * 8, b"\x00" * 4 + gzip.compress(b"x"),
                     b"\x00" * 3 + gzip.compress(b"y") + b"\x00" * 5):
            with self.subTest(tail=tail[:6]):
                self.assertEqual(compress.gunzip(big + tail), gzip.decompress(big + tail))
        self.assertEqual(compress.gunzip(gzip.compress(b"ab") + b"\x00\x00" + gzip.compress(b"cd")), b"abcd")
        with self.assertRaises(CorruptError):
            compress.gunzip(gzip.compress(b"ab") + b"junk")

    def test_deterministic(self):
        self.assertEqual(compress.gzip_bytes(b"x" * 100), compress.gzip_bytes(b"x" * 100))

    def test_truncated(self):
        with self.assertRaises(CorruptError):
            compress.gunzip(gzip.compress(b"abc" * 1000)[:-10])

    def test_unwrap_layers(self):
        inner = compress.lzw(b"RINEX")
        payload, layers = compress.unwrap(compress.gzip_bytes(inner))
        self.assertEqual((payload, layers), (b"RINEX", ["gz", "Z"]))


if __name__ == "__main__":
    unittest.main()
