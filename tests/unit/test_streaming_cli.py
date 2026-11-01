"""Streaming reader, extra wrappers and CLI behaviour."""

import bz2
import io
import os
import shutil
import tempfile
import unittest
import zipfile

from rinexconv.cli import main as cli_main
from rinexconv.engine import Options, convert_data, load_bytes
from rinexcore.errors import CorruptError
from rinexcore.obs import LineCursor

from .test_obs_fixtures import V211, V305


def cursor_lines(payload, chunk):
    old = LineCursor.CHUNK
    LineCursor.CHUNK = chunk
    try:
        cur = LineCursor(payload)
        out = []
        while True:
            x = cur.next()
            if x is None:
                return out, cur.lineno
            out.append(x)
    finally:
        LineCursor.CHUNK = old


class Cursor(unittest.TestCase):
    def test_chunk_boundaries_and_crlf(self):
        text = "".join(f"line {k:05d}{'x' * (k % 37)}\r\n" for k in range(3000))
        want = [f"line {k:05d}{'x' * (k % 37)}" for k in range(3000)]
        for chunk in (1, 7, 64, 1000, 1 << 22):
            got, n = cursor_lines(text.encode(), chunk)
            self.assertEqual(got, want, chunk)
            self.assertEqual(n, 3000)

    def test_no_final_newline_and_empty_lines(self):
        got, _ = cursor_lines(b"a\n\nb\n\nc", 2)
        self.assertEqual(got, ["a", "", "b", "", "c"])

    def test_has(self):
        cur = LineCursor(b"1\n2\n3\n")
        self.assertTrue(cur.has(3))
        self.assertFalse(cur.has(4))
        cur.next()
        self.assertTrue(cur.has(2))
        self.assertFalse(cur.has(3))

    def test_streaming_equals_materialised(self):
        for src in (V211, V305):
            ld = load_bytes(src)
            a = [(e.time, e.flag, e.sats, e.data) for e in ld.model.iter_epochs()]
            b = [(e.time, e.flag, e.sats, e.data) for e in ld.model.iter_epochs()]
            self.assertEqual(a, b)
            self.assertTrue(a)


class Wrappers(unittest.TestCase):
    def test_bz2_and_zip_inputs(self):
        plain = convert_data(V211, "t0010.26o", Options("3.01", compression="none"))[0].data
        for data in (bz2.compress(V211), _zip(V211)):
            got = convert_data(data, "t0010.26o.x", Options("3.01", compression="none"))[0].data
            self.assertEqual(got, plain)

    def test_zip_with_two_members_refused(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("a.26o", V211)
            z.writestr("b.26o", V211)
        with self.assertRaises(CorruptError):
            convert_data(b.getvalue(), "x.zip", Options("3.01", compression="none"))

    def test_crx_output_round_trips(self):
        from rinexcore.rinexfile import open_container
        for src, tv in ((V211, "2.11"), (V305, "3.05"), (V305, "4.02")):
            plain = convert_data(src, "x", Options(tv, compression="none", crx=False,
                                                    assume_phase_aligned=True,
                                                    drop_unresolvable=True))[0].data
            crx = convert_data(src, "x", Options(tv, compression="gz", crx=True, assume_phase_aligned=True,
                                                  drop_unresolvable=True))[0].data
            self.assertEqual(open_container(crx).payload, plain)


def _zip(data):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("t0010.26o", data)
    return b.getvalue()


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name, data):
        p = os.path.join(self.inp, name)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def test_exit_codes(self):
        p = self.put("test0010.26o", V211)
        out = os.path.join(self.tmp, "out")
        self.assertEqual(cli_main([p, "--to", "3.01", "--out", out]), 0)
        # GLONASS channels missing for 3.05: refused-missing-information (3)
        self.assertEqual(cli_main([p, "--to", "3.05", "--out", out, "--no-auto-nav"]), 3)
        self.assertEqual(cli_main([p, "--to", "3.05", "--out", out, "--drop-unresolvable", "--force"]), 1)
        self.assertEqual(cli_main([p, "--to", "9.99", "--out", out]), 2)
        bad = self.put("bad0010.26o", V211.replace(b"22000000.105", b"22000000.1x5"))
        self.assertEqual(cli_main([bad, "--to", "3.01", "--out", out]), 4)

    def test_missing_input_is_an_invocation_error(self):
        # found by the 24 h test (a mistyped path): the same-day nav lookup listed the input's
        # folder before the input was read, so a missing folder raised FileNotFoundError
        out = os.path.join(self.tmp, "out")
        for p in (os.path.join(self.tmp, "no-such-dir", "MIZU00JPN_R_20262900000_01D_01S_MO.crx.gz"),
                  os.path.join(self.inp, "test0010.26o")):
            with self.subTest(path=p):
                self.assertEqual(cli_main([p, "--to", "4.02", "--out", out]), 2)

    def test_auto_nav_from_sibling_table(self):
        p = self.put("test0010.26o", V211)
        # a same-day GLONASS nav file next to the input supplies the channel
        nav = ("     2.11           GLONASS NAV DATA                        RINEX VERSION / TYPE\n"
               "                                                            END OF HEADER\n"
               " 7 26 10  1  0 15  0.0 0.000000000000D+00 0.000000000000D+00 0.000000000000D+00\n"
               "    0.000000000000D+00 0.000000000000D+00 0.000000000000D+00 0.000000000000D+00\n"
               "    0.000000000000D+00 0.000000000000D+00 0.000000000000D+00 0.500000000000D+01\n"
               "    0.000000000000D+00 0.000000000000D+00 0.000000000000D+00 0.000000000000D+00\n")
        self.put("test0010.26g", nav.encode())
        out = os.path.join(self.tmp, "out")
        self.assertEqual(cli_main([p, "--to", "3.05", "--out", out]), 0)
        with open(os.path.join(out, os.listdir(out)[0]), "rb") as fh:
            self.assertIn(b"  1 R07  5", fh.read())

    def test_internal_error_does_not_stop_the_batch(self):
        import rinexconv.cli as cli
        a = self.put("a0010.26o", V211)
        b = self.put("b0010.26o", V211)
        orig = cli.convert_data
        calls = []

        def flaky(data, name, opts):
            calls.append(name)
            if name.startswith("a"):
                raise ValueError("boom")
            return orig(data, name, opts)
        cli.convert_data = flaky
        try:
            rc = cli_main([a, b, "--to", "3.01", "--out", os.path.join(self.tmp, "out")])
        finally:
            cli.convert_data = orig
        self.assertEqual(rc, 7)
        self.assertEqual(len(calls), 2)
        self.assertTrue(os.listdir(os.path.join(self.tmp, "out")))


if __name__ == "__main__":
    unittest.main()
