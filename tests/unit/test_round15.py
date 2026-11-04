"""Regression tests for review round 15 (2026-10-31, docs/DECISIONS.md "review round 15
fixes"): Sol's two blockers, from the reviewer's reproductions."""

import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_nav

from .test_independent_meta import SPEC
from .test_nav_fixtures import SPEC_305
from .test_round13 import Exact
from .test_validate import nav_v4, payload


def convert(src, t):
    outs = convert_data(src, "x.rnx", Options(t, compression="none"))
    return outs, outs[0].report.to_dict()


def lines_with(outs, needle):
    return [l for o in outs for l in o.data.decode().splitlines() if needle in l]


class LegacySbasIdsUpgraded(Exact, unittest.TestCase):
    """Sol 1: the 1X,A5,1X field of 2.11 D-UTC and RINEX 3 TIME SYSTEM CORR is a satellite
    ('Snn') or an SBAS provider name (rinex211.txt Table A15, rinex305.txt Table A5); RINEX 4
    STO records keep them apart (rinex_4.02.txt Table A33). 3.05 'EGNOS' became an STO record
    without a provider, and 2.11 'S27' a provider."""

    def check(self, src, sat, sbas):
        # 4.00 has no SBAS STO record: its STO systems are G,R,E,C,J,I (rinex_4.00.txt Table A30
        # p.102; S from 4.02, Table A33 p.115), so the offset is claimed there (round 32)
        outs, rep = convert(src, "4.00")
        self.assertEqual(lines_with(outs, "> STO S"), [])
        self.assertEqual(rep["losses"]["nav-sto-system-not-representable:S:SBUT"]["count"], 1)
        self.assertEqual(allowed_check(rep), [])
        self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)
        for t in ("4.02",):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                (head,) = [l for o in outs for l in o.data.decode().splitlines() if l.startswith("> STO S")]
                body = next(l for o in outs for l in o.data.decode().splitlines() if " SBUT " in l)
                self.assertEqual(head[6:9].strip(), sat)
                self.assertEqual(body[43:61].strip(), sbas)
                # U = 5 'Europe Lab', SBUT: UTC(OP) (the user's choice, 2026-11-01)
                self.assertEqual(body[62:80].strip(), "UTC(OP)")
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assertEqual(allowed_check(rep), [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_provider_from_rinex3(self):
        self.check((SPEC / "3.02" / "a15_nav_sbas.rnx").read_bytes(), "S", "EGNOS")

    def test_satellite_from_rinex2(self):
        src = (SPEC / "2.11" / "a18_nav_geo_derived_columns.rnx").read_bytes().replace(b"1240 EGNOS  5", b"1240 S27    5")
        self.check(src, "S27", "")


class IonosphereTransmissionTimeAndSatellite(Exact, unittest.TestCase):
    """Sol 2: a RINEX 4 ION record's transmission epoch and satellite (rinex_4.02.txt Table
    A35) went unclaimed to RINEX 2/3, and 3.05 lost even the time mark it can hold (only BDS
    got one); a 3.05 set's time mark and SV ID (rinex305.txt Table A5 p.64-65) went unclaimed
    to RINEX 2, and to 3.00/3.01 were copied into columns those versions do not define."""

    def test_rinex4_record(self):
        b = nav_v4("4.02")
        i = b.index("> ION G01 LNAV")
        b[i] = "> ION G13 LNAV"
        b[i + 1] = "    2026 10 30 12 34 56" + b[i + 1][23:]
        src = payload(b)
        for t, mark, claims in (("3.05", " M 13", {"ION-TTM:G"}), ("3.01", "", {"ION-TTM:G", "ION-SAT:G"}),
                                ("2.11", None, {"ION-TTM:G", "ION-SAT:G"})):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                if mark is not None:
                    (gpsa,) = lines_with(outs, "GPSA")
                    self.assertEqual(gpsa[53:58].rstrip(), mark)            # hour 12 = M, PRN 13
                got = {k.split(":", 1)[1] for k in rep["losses"] if ":ION-" in k and k.endswith(":G")}
                self.assertEqual(got, claims)
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)

    def test_rinex3_marks(self):
        src = b"".join((l.rstrip(b"\n")[:53].ljust(53) + b" M 13" + b" " * 2 + l[60:] if l.startswith((b"GPSA", b"GPSB"))
                        else l) for l in SPEC_305.splitlines(True))
        self.assertEqual(V.errors(V.validate(src)), [])
        for t, kept, claims in (("3.04", True, set()), ("3.01", False, {"ION-TTM:G", "ION-SAT:G"}),
                                ("2.11", False, {"ION-TTM:G", "ION-SAT:G"})):
            with self.subTest(target=t):
                outs, rep = convert(src, t)
                text = "".join(o.data.decode() for o in outs)
                self.assertEqual(" M 13" in text, kept)
                got = {k.split(":", 1)[1] for k in rep["losses"] if ":ION-" in k}
                self.assertEqual(got, claims)
                self.assertEqual(V.errors(V.validate(outs[0].data)), [])
                self.assert_exact(lambda r: compare_nav(src, [o.data for o in outs], r), rep)


class ApproxPositionChecked(unittest.TestCase):
    """Sol polish: --approx-position NaN or 1e9 escaped as AssertionError / OverflowError; the
    record is 3F14.4 (rinex305.txt Table A2), so a value must be finite and fit."""

    def test_invocation_error(self):
        from rinexconv.cli import main as cli_main
        import os
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.rnx")
        from .test_obs_fixtures import V211
        with open(p, "wb") as fh:
            fh.write(V211)
        for bad in (["nan", "0", "0"], ["1e9", "0", "0"], ["inf", "1", "2"], ["-1e9", "0", "0"]):
            with self.subTest(value=bad):
                self.assertEqual(cli_main([p, "--to", "2.11", "--out", d, "--force", "--no-auto-nav",
                                           "--approx-position", *bad]), 2)
        from rinexcore.errors import InvocationError
        with self.assertRaises(InvocationError):
            convert_data(V211, "x.rnx", Options("2.11", approx_position=(float("nan"), 0, 0)))


if __name__ == "__main__":
    unittest.main()
