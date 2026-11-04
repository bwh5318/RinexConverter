"""Changes from the user's answers of 2026-11-01 (docs/DECISIONS.md): an SBAS UTC offset
with UTC number 5 ('Europe Lab', rinex305.txt Table A5) is UTC(OP) in RINEX 4, the only
European lab rinex_4.02.txt Table 27 (p.43-44) lists for SBUT, and back. (The tar input is in
test_tar_input.py.)"""

import copy
import unittest

from rinexconv.engine import Options, convert_data
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav

from .test_independent_meta import SPEC

SBAS = (SPEC / "3.02" / "a15_nav_sbas.rnx").read_bytes()      # TIME SYSTEM CORR SBUT ... EGNOS  5


def lines(data, needle):
    return [l for l in data.decode("latin-1").splitlines() if needle in l]


class SbasEuropeLabIsUtcOp(unittest.TestCase):
    def test_to_rinex4(self):
        outs = convert_data(SBAS, "x.rnx", Options("4.02", compression="none"))
        rep = outs[0].report.to_dict()
        (body,) = lines(outs[0].data, " SBUT ")
        self.assertEqual(body[62:80].strip(), "UTC(OP)")
        self.assertIn("SBUT:5->UTC(OP)", str(rep["assumptions"]))
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(SBAS, [o.data for o in outs], rep), [])
        # an output with the old reading is caught
        bad = outs[0].data.replace(b"UTC(OP)", b"UTC(Europe Lab)")
        self.assertNotEqual(bad, outs[0].data)
        self.assertTrue(compare_nav(SBAS, [bad], rep))

    def test_back_to_rinex3_and_2(self):
        v4 = convert_data(SBAS, "x.rnx", Options("4.02", compression="none"))[0].data
        for t, label in (("3.05", "TIME SYSTEM CORR"), ("3.02", "TIME SYSTEM CORR"),
                         ("2.11", "D-UTC A0,A1,T,W,S,U")):
            with self.subTest(target=t):
                outs = convert_data(v4, "y.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                (rec,) = lines(outs[0].data, label)
                self.assertEqual(rec[:60].split()[-1], "5")         # U = 5, no longer 0
                self.assertFalse([k for k in rep["losses"] if "UTC-ID" in k])
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(v4, [o.data for o in outs], rep), [])
                bad = copy.deepcopy(rep)
                bad["losses"][f"header-field-not-representable:{label.split(' A0')[0]}:UTC-ID:UTC(OP)"] = \
                    {"count": 1}
                self.assertTrue(compare_nav(v4, [o.data for o in outs], bad))

    def test_utc_op_elsewhere_has_no_number(self):
        # UTC(OP) is 5 only in an SBUT record: Table 27 gives it to no other offset
        v4 = convert_data(SBAS, "x.rnx", Options("4.02", compression="none"))[0].data
        v4 = v4.replace(b" SBUT ", b" GPUT ").replace(b"> STO S", b"> STO G")
        outs = convert_data(v4, "y.rnx", Options("3.05", compression="none"))
        rep = outs[0].report.to_dict()
        (rec,) = lines(outs[0].data, "TIME SYSTEM CORR")
        self.assertEqual(rec[:60].split()[-1], "0")
        self.assertEqual(rep["losses"]["header-field-not-representable:TIME SYSTEM CORR:UTC-ID:UTC(OP)"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_nav(v4, [o.data for o in outs], rep), [])


class PlainFallbacksConfirmedByRnxcmp(unittest.TestCase):
    """The two cases written as plain RINEX instead of Compact RINEX (the user's answer 1,
    2026-11-01; test_round22) were found by reading rnx2crx.c and crx2rnx.c. With RNX2CRX 4.2.0
    now here: the official pair does not carry either file (RNX2CRX stops, or CRX2RNX does
    not give the file back), so Compact RINEX output would have been wrong."""

    @classmethod
    def setUpClass(cls):
        from .test_hatanaka import find_crx2rnx, find_rnx2crx
        cls.enc, cls.dec = find_rnx2crx(), find_crx2rnx()
        if not (cls.enc and cls.dec):
            raise unittest.SkipTest("RNX2CRX.exe or CRX2RNX.exe not available")

    def official_pair_carries(self, plain):
        from .test_hatanaka import run_crx2rnx, run_rnx2crx
        code, crx, err = run_rnx2crx(self.enc, plain)
        if code != 0:
            return False
        c2, back, err2 = run_crx2rnx(self.dec, crx)
        return c2 == 0 and back == plain

    def sources(self):
        from .test_obs_fixtures import F, hdr
        from .test_round22 import mixed, rec
        stale = mixed("3.05", "E", "C1C L1C", body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("G05", 22e6, 115e6),
            "> 2026 10 01 00 00 15.0000000  4  1", hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
            "> 2026 10 01 00 00 30.0000000  6  1", "G05" + F("  22000100.105"),
            "> 2026 10 01 00 00 45.0000000  0  1", rec("G05", 22e6 + 200, 115e6 + 900)])
        pico = mixed("4.02", "E", "C1C L1C", body=[
            "> 2026 10 01 00 00  0.0000000  0  1", rec("G05", 22e6, 115e6),
            "> 2026 10 01 00 00 30.0000000  0  1" + " " * 21 + " 01234", rec("G05", 22e6 + 100, 115e6 + 500),
            "> 2026 10 01 00 01  0.0000000  0  1", rec("G05", 22e6 + 200, 115e6 + 900)])
        return {"stale type label": (stale, "3.05"), "picoseconds that stop": (pico, "4.02")}

    def plain(self, name):
        src, t = self.sources()[name]
        return convert_data(src, "x.rnx", Options(t, compression="none", crx=False,
                                                  assume_phase_aligned=True))[0].data

    def test_stale_type_label(self):
        # RNX2CRX reads the short cycle-slip record as a type count from the stale label
        from .test_hatanaka import run_rnx2crx
        plain = self.plain("stale type label")
        code, crx, err = run_rnx2crx(self.enc, plain)
        self.assertEqual(code, 1)
        self.assertIn("MAXTYPE", err)
        self.assertFalse(self.official_pair_carries(plain))
        # the same record padded past column 79 goes through
        padded = plain.replace(b"G05  22000100.105\n", b"G05  22000100.105".ljust(80) + b"\n")
        self.assertNotEqual(padded, plain)
        code, crx, err = run_rnx2crx(self.enc, padded)
        self.assertEqual(code, 0, err)

    def test_picoseconds_that_stop(self):
        # CRX2RNX repeats the last picosecond value on the epoch that has none
        from .test_hatanaka import run_crx2rnx, run_rnx2crx
        plain = self.plain("picoseconds that stop")
        code, crx, err = run_rnx2crx(self.enc, plain)
        self.assertEqual(code, 0, err)
        c2, back, err2 = run_crx2rnx(self.dec, crx)
        self.assertEqual(c2, 0, err2)
        self.assertIn(b"> 2026 10 01 00 01  0.0000000  0  1" + b" " * 22 + b"01234", back)
        self.assertNotIn(b"> 2026 10 01 00 01  0.0000000  0  1" + b" " * 22 + b"01234", plain)
        # without the picosecond field the file goes through unchanged
        fixed = plain.replace(b" " * 21 + b" 01234", b"")
        self.assertNotEqual(fixed, plain)
        self.assertTrue(self.official_pair_carries(fixed))


class SolRound29(unittest.TestCase):
    """Sol round 29: (1) an output name made from MARKER NAME escaped the output folder; (2) a
    damaged tar header after the first member ended the archive with no error; (3) a BeiDou 0
    in LEAP SECONDS of a 3.03-3.05 file, a value there, was treated as "not known"."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # (1)
    def test_marker_name_never_becomes_a_path(self):
        import os
        from rinexconv.cli import main as cli_main
        from .test_obs_fixtures import V305
        for marker in (b"../x", b"..\\x", b"C:x", b"A B", b"/abs"):
            with self.subTest(marker=marker):
                src = b"\n".join((marker.ljust(60) + b"MARKER NAME") if l[60:].startswith(b"MARKER NAME")
                                 else l for l in V305.split(b"\n"))
                outs = convert_data(src, "obs.rnx", Options("2.11", auto_nav=False, drop_unresolvable=True,
                                                            approx_position=(1.0, 2.0, 3.0)))
                self.assertEqual(outs[0].name[:4], "xxxx")
                d = os.path.join(self.tmp, "out")
                p = os.path.join(self.tmp, "obs.rnx")
                with open(p, "wb") as fh:
                    fh.write(src)
                self.assertIn(cli_main([p, "--to", "2.11", "--out", d, "--no-auto-nav", "--force",
                                        "--drop-unresolvable", "--approx-position", "1", "2", "3"]), (0, 1))
                self.assertEqual(sorted(os.listdir(self.tmp)), ["obs.rnx", "out"])

    def test_unsafe_output_names_refused(self):
        from rinexconv.engine import Output, write_output
        from rinexcore.errors import InvocationError
        import dataclasses
        fields = {f.name for f in dataclasses.fields(Output)}
        for name in ("../x.rnx", "a/b.rnx", "a\\b.rnx", "C:x.rnx", "x.rnx:s", "CON", "nul.26o", "COM1.rnx",
                     "..", "", " x.rnx", "a\x01.rnx"):
            with self.subTest(name=name):
                out = Output(**{k: v for k, v in (("name", name), ("data", b"x"), ("report", None)) if k in fields})
                with self.assertRaises(InvocationError):
                    write_output(out, self.tmp)
        self.assertEqual(os.listdir(self.tmp) if (os := __import__("os")) else [], [])

    def test_member_names_unusable_for_outputs_or_reports(self):
        # report files are named '<member>.report.json' (cli._write_report): a member name
        # Windows cannot hold, or a device name, is skipped like a nameless member
        from rinexcore.io import archive
        from .test_obs_fixtures import V211
        from .test_tar_input import tar_bytes
        names = ["CON", "nul.26o", "COM1.rnx", "a?b0010.26o", "a*0010.26o", 'q"0010.26o', "x0010.26o ",
                 "t\x01b0010.26o", "ok0010.26o"]
        got = {base: why for full, base, data, why in archive.members(tar_bytes([(n, V211) for n in names]))}
        self.assertEqual({b for b, w in got.items() if w == "no usable file name"}, set(names) - {"ok0010.26o"})
        self.assertIsNone(got["ok0010.26o"])

    # (2)
    def tars(self):
        import io
        import tarfile
        from .test_obs_fixtures import V211
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
            for n in ("a0010.26o", "b0010.26o", "c0010.26o"):
                ti = tarfile.TarInfo(n)
                ti.size = len(V211)
                tf.addfile(ti, io.BytesIO(V211))
        tar = buf.getvalue()
        second = 512 + (len(V211) + 511) // 512 * 512
        bad = bytearray(tar)
        bad[second + 148] ^= 1
        return {"bad checksum": bytes(bad), "header cut short": tar[:second + 300],
                "no end block": tar[:second], "data appended": tar + b"junk" + b"\0" * 508,
                "second archive appended": tar + tar}

    def test_damaged_later_header_refused(self):
        from rinexcore.errors import CorruptError
        from rinexcore.io import archive
        for name, data in self.tars().items():
            with self.subTest(name):
                got = []
                with self.assertRaises(CorruptError) as cm:
                    for m in archive.members(data):
                        got.append(m[1])
                self.assertEqual(cm.exception.rule, "IO.TAR")
                self.assertTrue(got)              # the members before the damage are given
        self.assertEqual([m[1] for m in archive.members(self.tars()["data appended"][:-512 - 512])],
                         ["a0010.26o", "b0010.26o", "c0010.26o"])   # (the intact archive)

    def test_damaged_later_header_in_cli(self):
        import contextlib
        import io
        import os
        from rinexconv.cli import main as cli_main
        p = os.path.join(self.tmp, "x.tar")
        with open(p, "wb") as fh:
            fh.write(self.tars()["bad checksum"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli_main([p, "--to", "3.01", "--out", os.path.join(self.tmp, "out"), "--no-auto-nav"])
        self.assertEqual(rc, 4, err.getvalue())
        self.assertIn("tar archive is damaged after member 'a0010.26o'", err.getvalue())
        self.assertEqual(len(os.listdir(os.path.join(self.tmp, "out"))), 1)

    # (3)
    def test_bdt_zero_is_a_value_from_303(self):
        from .test_round28 import bds_only, leap
        src = bds_only("3.05", "     0                  BDT")     # BDT-UTC was 0 s in 2006-2008
        for t, want in (("4.02", ["    14                  GPS"]), ("3.04", ["     0                  BDS"]),
                        ("3.02", ["    14"])):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(leap(outs[0].data), want)
                self.assertEqual(allowed_check(rep), [])
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
                bad = outs[0].data.replace(want[0].encode(), b"     0" + want[0][6:].encode())
                if bad != outs[0].data:
                    self.assertTrue(compare_nav(src, [bad], rep))
        # the BeiDou-only 3.02 output reads back as GPS 14 (count rule), so 4.02 gets 14
        v302 = convert_data(src, "x.rnx", Options("3.02", compression="none"))[0].data
        back = convert_data(v302, "y.rnx", Options("4.02", compression="none"))[0].data
        self.assertEqual(leap(back), ["    14"])                       # (no identifier = GPS)

    def test_302_unknown_zeros_blank_in_bdt(self):
        # '4 0 0 0' in a BeiDou-only 3.02 file: the zeros are "not known" (rinex302.txt p.63);
        # written as zeros under BDT in 3.05 they would read as a leap event at BDS week 0
        from .test_round28 import bds_only, leap
        src = bds_only("3.02", "     4     0     0     0")
        for t, want in (("3.05", ["     4                  BDT"]), ("3.03", ["     4                  BDS"]),
                        ("4.02", ["    18     0     0     0GPS"])):
            with self.subTest(target=t):
                outs = convert_data(src, "x.rnx", Options(t, compression="none"))
                rep = outs[0].report.to_dict()
                self.assertEqual(leap(outs[0].data), want)
                self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])
        outs = convert_data(src, "x.rnx", Options("3.05", compression="none"))
        bad = outs[0].data.replace(b"     4                  BDT", b"     4     0     0     0BDT")
        self.assertTrue(compare_nav(src, [bad], outs[0].report.to_dict()))


if __name__ == "__main__":
    unittest.main()
