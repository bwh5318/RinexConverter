"""Tar archives as input (the user's choice, 2026-11-01, docs/DECISIONS.md): every RINEX member
converted as if given on the command line, other members skipped and listed, no prompt,
nothing unpacked to disk (rinexcore/io/archive.py, rinexconv/cli.run_archive)."""

import bz2
import contextlib
import gzip
import io
import os
import shutil
import tarfile
import tempfile
import unittest

from rinexconv.cli import main as cli_main
from rinexconv.engine import Options, convert_data
from rinexcore.errors import InvocationError
from rinexcore.io import archive, compress

from .test_independent_meta import SPEC
from .test_obs_fixtures import V211

NAV = (SPEC / "3.05" / "a7_nav_gps.rnx").read_bytes()


def tar_bytes(entries):
    """A tar archive of (name, bytes) regular files; bytes None makes a folder, a str a
    symbolic link to it."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in entries:
            ti = tarfile.TarInfo(name)
            if data is None:
                ti.type = tarfile.DIRTYPE
                tf.addfile(ti)
            elif isinstance(data, str):
                ti.type, ti.linkname = tarfile.SYMTYPE, data
                tf.addfile(ti)
            else:
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


MEMBERS = [("day", None), ("day/a0010.26o", V211), ("day/b0010.26o.gz", gzip.compress(V211)),
           ("nav/a7_nav_gps.rnx", NAV), ("README.txt", b"daily files\n"),
           ("day/link0010.26o", "day/a0010.26o"), ("../evil0010.26o", V211),
           ("inner.tar", tar_bytes([("c0010.26o", V211)])), ("C:x0010.26o", V211)]
RINEX = {"a0010.26o": V211, "b0010.26o.gz": gzip.compress(V211), "a7_nav_gps.rnx": NAV,
         "evil0010.26o": V211}


class TarInput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def run_cli(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli_main(list(args))
        return rc, err.getvalue()

    def expected(self, target):
        want = {}
        for name, data in RINEX.items():
            for o in convert_data(data, name, Options(target, auto_nav=False)):
                want[o.name] = o.data
        return want

    def outputs(self):
        got = {}
        for name in os.listdir(self.out):
            with open(os.path.join(self.out, name), "rb") as fh:
                got[name] = fh.read()
        return got

    def test_every_rinex_member_converted(self):
        tar = tar_bytes(MEMBERS)
        for suffix, wrap in ((".tar", bytes), (".tar.gz", gzip.compress), (".tar.bz2", bz2.compress),
                             (".tar.Z", compress.lzw)):
            with self.subTest(archive=suffix):
                shutil.rmtree(self.out, ignore_errors=True)
                p = self.put("day001" + suffix, wrap(tar))
                rc, err = self.run_cli(p, "--to", "3.01", "--out", self.out, "--no-auto-nav")
                self.assertEqual(rc, 0, err)
                self.assertEqual(self.outputs(), self.expected("3.01"))
                for name, why in (("day", "not a regular file"), ("README.txt", "not a RINEX file"),
                                  ("day/link0010.26o", "not a regular file"),
                                  ("inner.tar", "an archive inside the archive"),
                                  ("C:x0010.26o", "no usable file name")):
                    self.assertIn(f"skipped: {p}:{name} ({why})", err)
                # nothing outside the output folder, whatever a member is called
                self.assertEqual(sorted(os.listdir(self.tmp)), sorted(["out", os.path.basename(p)]))
                os.remove(p)

    def test_damaged_members_are_refused_not_skipped(self):
        bad = V211.replace(b"22000000.105", b"22000000.1x5")
        tar = tar_bytes([("a0010.26o", V211), ("bad0010.26o", bad), ("junk0010.26o", b"hello\n"),
                         ("notes.txt", b"hello\n")])
        p = self.put("x.tar", tar)
        rc, err = self.run_cli(p, "--to", "3.01", "--out", self.out, "--no-auto-nav")
        self.assertEqual(rc, 4, err)
        self.assertIn(f"refused-corrupt: bad0010.26o:", err)
        self.assertIn(f"refused-corrupt: junk0010.26o:", err)           # a RINEX name: refused
        self.assertIn(f"skipped: {p}:notes.txt (not a RINEX file)", err)
        self.assertEqual(len(os.listdir(self.out)), 1)

    def test_truncated_archive(self):
        tar = tar_bytes([("a0010.26o", V211), ("b0010.26o", V211)])
        first = 512 + (len(V211) + 511) // 512 * 512
        p = self.put("x.tar", tar[:first + 512 + 100])         # the second member cut short
        rc, err = self.run_cli(p, "--to", "3.01", "--out", self.out, "--no-auto-nav")
        self.assertEqual(rc, 4, err)
        self.assertIn("tar archive is damaged", err)
        self.assertEqual(len(os.listdir(self.out)), 1)

    def test_no_rinex_member(self):
        p = self.put("x.tar", tar_bytes([("README.txt", b"hello\n")]))
        rc, err = self.run_cli(p, "--to", "3.01", "--out", self.out)
        self.assertEqual(rc, 2, err)
        self.assertIn("the archive holds no RINEX file", err)

    def test_merge_refuses_an_archive(self):
        nav = self.put("a7.rnx", NAV)
        p = self.put("x.tar", tar_bytes([("b.rnx", NAV)]))
        rc, err = self.run_cli(nav, p, "--to", "3.04", "--merge", "--out", self.out)
        self.assertEqual(rc, 2, err)
        self.assertIn("--merge takes navigation files, not a tar archive", err)

    def test_library_names_an_archive(self):
        for data in (tar_bytes([("a0010.26o", V211)]), gzip.compress(tar_bytes([("a0010.26o", V211)]))):
            with self.assertRaises(InvocationError) as cm:
                convert_data(data, "x.tar", Options("3.01"))
            self.assertIn("tar archive", str(cm.exception))

    def test_ustar_in_a_rinex_header_is_not_an_archive(self):
        fake = V211[:257] + b"ustar" + V211[262:]
        self.assertFalse(archive.is_tar(fake))
        self.assertTrue(archive.is_tar(tar_bytes([("a0010.26o", V211)])))
        self.assertTrue(archive.is_rinex(gzip.compress(V211)))
        self.assertFalse(archive.is_rinex(b"hello\n"))


if __name__ == "__main__":
    unittest.main()
