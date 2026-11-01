"""Memory scales with the file, not with a model of every epoch (review round 2, Sonnet).

A 24 h 1 Hz file (~1 GB of RINEX) is too slow to convert in a unit test, so this measures
the Python heap peak (tracemalloc) on two synthetic 1 Hz files, one four times longer than
the other, and checks (1) the peak grows no faster than the file and (2) it stays within a
fixed multiple of input + output bytes, which is what the streaming design promises
(docs/DECISIONS.md: decoded source and output are each held once).
"""

import tracemalloc
import unittest

from rinexconv.engine import Options, convert_data

from .test_obs_fixtures import F, hdr, lines

SATS = [f"G{n:02d}" for n in range(1, 21)] + [f"E{n:02d}" for n in range(1, 11)]


def synthetic(n_epochs):
    head = [
        hdr("     3.05           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
        hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
        hdr("TEST", "MARKER NAME"),
        hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ"),
        hdr("G    6 C1C L1C S1C C2W L2W S2W", "SYS / # / OBS TYPES"),
        hdr("E    6 C1C L1C S1C C5Q L5Q S5Q", "SYS / # / OBS TYPES"),
        hdr("G L1C", "SYS / PHASE SHIFT"), hdr("G L2W", "SYS / PHASE SHIFT"),
        hdr("E L1C", "SYS / PHASE SHIFT"), hdr("E L5Q", "SYS / PHASE SHIFT"),
        hdr("     1.000", "INTERVAL"),
        hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
        hdr("", "END OF HEADER"),
    ]
    body = []
    for k in range(n_epochs):
        m, s = divmod(k, 60)
        h, m = divmod(m, 60)
        body.append(f"> 2026 10 01 {h:02d} {m:02d}{s:3d}.0000000  0 {len(SATS):2d}")
        for j, sat in enumerate(SATS):
            c = 20000000.0 + 1000 * j + k * 0.7
            body.append(sat + F(f"{c:14.3f}") + F(f"{c * 5.25:14.3f}") + F(f"{40 + j % 9:14.3f}")
                        + F(f"{c + 3.1:14.3f}") + F(f"{c * 4.1:14.3f}") + F(f"{35 + j % 7:14.3f}"))
    return lines(*head, *[b.rstrip() for b in body], width=None)


def peak(data, target):
    tracemalloc.start()
    try:
        outs = convert_data(data, "SYNT00XXX_R_20262740000_01H_01S_MO.rnx", Options(target, compression="none"))
        _, top = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return top, len(outs[0].data)


class MemoryScaling(unittest.TestCase):
    def test_peak_is_linear_in_file_size(self):
        small, large = synthetic(150), synthetic(600)
        for target in ("2.11", "4.02"):
            peak(small, target)           # warm-up: one-time imports and table caches
            with self.subTest(target=target):
                p1, o1 = peak(small, target)
                p4, o4 = peak(large, target)
                # four times the data: at most ~four times the memory (a little slack for
                # fixed costs shrinking in proportion)
                self.assertLess(p4 / p1, 4.6, (p1, p4))
                # a bounded multiple of what has to be held anyway: source + output
                # (measured 2026-10-31: 2.2x to 2.11, 1.9x to 4.02)
                self.assertLess(p4, 4 * (len(large) + o4), (p4, len(large), o4))


class NoWholeFileCopies(unittest.TestCase):
    """The 24 h 1 Hz test (MIZU00JPN, 1.6 GB of RINEX 3.05, 2026-10-31) paged a 7.7 GB laptop:
    the loader decoded and split the whole obs payload only to read its first line (about
    2.5x the input), and join_lines held its chunks and their join at once (2x the output)."""

    def test_obs_payload_never_split_whole(self):
        from rinexconv import engine
        data = synthetic(50)
        seen = []
        real = engine.split_lines

        def spy(payload):
            seen.append(len(payload))
            return real(payload)
        engine.split_lines = spy
        try:
            ld = engine.load_bytes(data)
        finally:
            engine.split_lines = real
        self.assertEqual(ld.kind, "obs")
        self.assertTrue(all(n < 200 for n in seen), seen)       # the version line at most
        self.assertEqual(ld.model.eol, "lf")
        crlf = engine.load_bytes(data.replace(b"\n", b"\r\n"))
        self.assertEqual(crlf.model.eol, "crlf")

    def test_join_lines_holds_the_output_about_once(self):
        from rinexcore import rinexfile
        from rinexcore.io import spool
        rows = [f"G{k % 32:02d}" + f"{20000000.0 + k:14.3f}  " * 5 for k in range(200000)]
        for eol, sep in (("lf", "\n"), ("crlf", "\r\n")):
            want = (sep.join(rows) + sep).encode("latin-1")
            self.assertEqual(rinexfile.join_lines(iter(rows), eol), want)       # in memory
            saved = spool.SPILL_BYTES
            spool.SPILL_BYTES = 1 << 20          # spill early: the temporary-file path
            tracemalloc.start()
            try:
                out = rinexfile.join_lines(iter(rows), eol)
                _, top = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
                spool.SPILL_BYTES = saved
            self.assertEqual(out, want)
            self.assertLess(top, 1.5 * len(out), (eol, top, len(out)))      # was 2x and more


class CodecsThroughTheSpool(unittest.TestCase):
    """The 24 h test's Hatanaka leg peaked at 5.7 GB: the codec split the whole file into line
    objects and joined its output in memory, and gunzip grew a bytearray and copied it. They
    now index lines by offset and write through io.spool; forcing the spill path must give
    the same bytes, CRLF and a final line without LF included."""

    def test_same_bytes_spilled(self):
        import gzip
        from rinexcore.io import compress, hatanaka, spool
        rnx = synthetic(120)
        crx = hatanaka.rnx_to_crx(rnx, date="31-Oct-26 12:00")
        back = hatanaka.crx_to_rnx(crx)
        gz = gzip.compress(rnx[:5000]) + gzip.compress(rnx[5000:])        # two members
        crlf = rnx.replace(b"\n", b"\r\n")
        crx_crlf = hatanaka.rnx_to_crx(crlf, date="31-Oct-26 12:00")
        def outcome(fn, *a, **k):                        # bytes, or the refusal's rule
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                return getattr(e, "rule", repr(e))
        no_lf = [outcome(hatanaka.crx_to_rnx, crx[:-1]),   # last line without its LF
                 outcome(hatanaka.rnx_to_crx, rnx[:-1], date="31-Oct-26 12:00")]
        saved = spool.SPILL_BYTES
        spool.SPILL_BYTES = 4096
        try:
            self.assertEqual(hatanaka.rnx_to_crx(rnx, date="31-Oct-26 12:00"), crx)
            self.assertEqual(hatanaka.crx_to_rnx(crx), back)
            self.assertEqual(compress.gunzip(gz), rnx)
            self.assertEqual(hatanaka.rnx_to_crx(crlf, date="31-Oct-26 12:00"), crx_crlf)
            self.assertEqual([outcome(hatanaka.crx_to_rnx, crx[:-1]),
                              outcome(hatanaka.rnx_to_crx, rnx[:-1], date="31-Oct-26 12:00")], no_lf)
        finally:
            spool.SPILL_BYTES = saved
        self.assertEqual(back, rnx)


if __name__ == "__main__":
    unittest.main()
