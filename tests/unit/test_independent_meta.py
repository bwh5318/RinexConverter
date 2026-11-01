"""The independent header / clock / event / correction checks (tests/independent/headers.py)
must pass a correct conversion and fail a damaged one (PLAN §1 clauses 3 and 5a: "the checks
must not be able to pass a wrong converter").

Each test converts a hand-written fixture or a spec example with the converter, checks that
the result passes, then damages the output (or the report) in one place and expects at
least one problem."""

import copy
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from rinexconv.engine import Options, convert_data
from tests.independent.headers import compare_met_meta, compare_nav_meta, compare_obs_meta

from .test_nav_fixtures import SPEC_211, SPEC_305
from .test_obs_fixtures import V211, V305, table_file

SPEC = Path(__file__).resolve().parents[1] / "fixtures" / "spec_examples"


def _sub(data, old, new, count=1):
    assert data.count(old) >= 1, old
    return data.replace(old, new, count)


def _drop_line(data, needle):
    lines = data.split(b"\n")
    k = next(i for i, l in enumerate(lines) if needle in l)
    del lines[k]
    return b"\n".join(lines)


def _clock_edit(data, epoch_start, fn):
    """Rewrite the receiver clock of the epoch line that starts with epoch_start, found by
    column (RINEX 3/4: F15.12 in columns 42-56, rinex_4.02.txt Table A3; RINEX 2: F12.9 in
    columns 69-80, rinex211.txt Table A2), not by its text (writers differ on the leading
    zero). fn(old value or None) returns the new field text, or None for a blank field."""
    lines = data.split(b"\n")
    k = next(i for i, l in enumerate(lines) if l.startswith(epoch_start))
    l = lines[k].decode("latin-1")
    a, b = (41, 56) if l.startswith(">") else (68, 80)
    l = l.ljust(b)
    old = l[a:b].strip()
    new = fn(Decimal(old) if old else None)
    lines[k] = (l[:a] + (new.rjust(b - a) if new else " " * (b - a)) + l[b:]).rstrip().encode("latin-1")
    return b"\n".join(lines)


def _plus_1ns(decimals):
    """Field text of the old clock plus 1 ns (the old clock must exist)."""
    def fn(c):
        assert c is not None
        return f"{c + Decimal('1e-9'):.{decimals}f}"
    return fn


def _invent(c):
    assert c is None
    return "0.000000999000"


def _lose(rep, cat):
    rep = copy.deepcopy(rep)
    del rep["losses"][cat]
    return rep


def _claim(rep, cat, n=1):
    rep = copy.deepcopy(rep)
    rep["losses"][cat] = {"count": n, "detail": {}}
    return rep


class _Tmp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="indep-meta-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def convert(self, data, target, fcn=None, **kw):
        outs = convert_data(data, "t0010.26o", Options(target, compression="none", glo_fcn=fcn,
                                                      assume_phase_aligned=True, **kw))
        return outs, outs[0].report.to_dict()


class ObsMeta(_Tmp):
    """Hand-written RINEX 2.11 / 3.05 fixtures (tests/unit/test_obs_fixtures.py)."""

    def setUp(self):
        self.fcn = table_file(self.tmp, "R07 5\n")
        outs, self.rep = self.convert(V211, "3.05", self.fcn)
        self.out = outs[0].data

    def check(self, out=None, rep=None, inp=V211):
        return compare_obs_meta(inp, self.out if out is None else out, self.rep if rep is None else rep)

    def test_correct_conversions_pass(self):
        self.assertEqual(self.check(), [])
        outs, rep = self.convert(V305, "2.11", approx_position=(4027894.006, 307045.6, 4919474.91))
        self.assertEqual(compare_obs_meta(V305, outs[0].data, rep), [])
        outs, rep = self.convert(V211, "4.02", self.fcn)
        self.assertEqual(compare_obs_meta(V211, outs[0].data, rep), [])

    def test_changed_clock_fails(self):
        bad = _clock_edit(self.out, b"> 2026 10 01 00 00  0.0", _plus_1ns(12))
        self.assertTrue(self.check(bad))

    def test_dropped_clock_fails(self):
        bad = _clock_edit(self.out, b"> 2026 10 01 00 00  0.0", lambda c: None)
        self.assertTrue(self.check(bad))

    def test_invented_clock_fails(self):
        bad = _clock_edit(self.out, b"> 2026 10 01 00 00 30.0", _invent)
        self.assertTrue(self.check(bad))

    def test_dropped_marker_name_fails(self):
        self.assertTrue(self.check(_drop_line(self.out, b"MARKER NAME")))

    def test_changed_marker_name_fails(self):
        self.assertTrue(self.check(_sub(self.out, b"TEST" + b" " * 56 + b"MARKER NAME",
                                        b"TEST2" + b" " * 55 + b"MARKER NAME")))

    def test_altered_event_comment_fails(self):
        self.assertTrue(self.check(_sub(self.out, b"A COMMENT INSIDE", b"A COMMENT OUTSIDE")))

    def test_dropped_event_fails(self):
        bad = _sub(self.out, b"> 2026 10 01 00 00 15.0000000  4  1\n", b"")
        bad = _drop_line(bad, b"A COMMENT INSIDE")
        self.assertTrue(self.check(bad))

    def test_moved_event_fails(self):
        self.assertTrue(self.check(_sub(self.out, b"00 15.0000000  4", b"00 16.0000000  4")))

    def test_dropped_epoch_fails(self):
        out = self.out.decode("latin-1").split("\n")
        k = next(i for i, l in enumerate(out) if l.startswith("> 2026 10 01 00 00 30"))
        del out[k:k + 3]
        bad = "\n".join(out).encode("latin-1")
        self.assertTrue(self.check(bad))

    def test_unclaimed_epoch_emptying_fails(self):
        # GLONASS dropped (no channel, --drop-unresolvable): no epoch is emptied here, so a
        # claim of one is false
        outs, rep = self.convert(V211, "3.05", None, drop_unresolvable=True)
        self.assertEqual(compare_obs_meta(V211, outs[0].data, rep), [])
        self.assertTrue(compare_obs_meta(V211, outs[0].data, _claim(rep, "epoch-emptied-by-system-removal")))

    def test_time_of_first_obs_changed_fails(self):
        self.assertTrue(self.check(_sub(self.out, b"  2026    10     1     0     0    0.0000000",
                                        b"  2026    10     1     0     0    1.0000000")))

    def test_glonass_channel_changed_fails(self):
        self.assertTrue(self.check(_sub(self.out, b"  1 R07  5", b"  1 R07  4")))

    def test_claimed_header_loss_that_did_not_happen_fails(self):
        self.assertTrue(self.check(rep=_claim(self.rep, "header-record-not-representable:MARKER NAME")))
        self.assertTrue(self.check(rep=_claim(self.rep, "header-record-not-representable:ANT # / TYPE")))
        self.assertTrue(self.check(rep=_claim(self.rep, "clock-precision")))
        self.assertTrue(self.check(rep=_claim(self.rep, "event-emptied")))


class ObsMetaSpecExample(_Tmp):
    """RINEX 3.05 Table A3 example #1 (tests/fixtures/spec_examples/3.05/a4_obs_example1.rnx):
    v3-only records, a picosecond-free clock with 12 decimals, events with flags 2-4."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inp = (SPEC / "3.05" / "a4_obs_example1.rnx").read_bytes()
        # test-only channels for R21/R22, which the example's GLONASS SLOT / FRQ # lacks (E-07)
        cls.fcn = table_file(cls.tmp, "R21 1\nR22 1\n")

    def test_to_211_passes_and_claims_are_needed(self):
        outs, rep = self.convert(self.inp, "2.11", self.fcn)
        out = outs[0].data
        self.assertEqual(compare_obs_meta(self.inp, out, rep), [])
        # F15.12 -> F12.9: rounding must be claimed ...
        self.assertTrue(compare_obs_meta(self.inp, out, _lose(rep, "clock-precision")))
        # ... and may not exceed 0.5e-9 s
        self.assertTrue(compare_obs_meta(self.inp, _clock_edit(out, b" 06  3 24 13 10 36.0", _plus_1ns(9)), rep))
        # a v3-only record dropped for 2.11 must be claimed
        self.assertTrue(compare_obs_meta(self.inp, out,
                                         _lose(rep, "header-record-not-representable:SYS / DCBS APPLIED")))
        # records 2.11 defines must survive
        self.assertTrue(compare_obs_meta(self.inp, _drop_line(out, b"APPROX POSITION XYZ"), rep))
        self.assertTrue(compare_obs_meta(self.inp, _sub(out, b"G1234               ROVER",
                                                        b"G1234               RAVER"), rep))
        # the event that starts a new site carries MARKER NAME: it must survive too
        self.assertTrue(compare_obs_meta(self.inp, _sub(out, b"A 9081", b"A 9082"), rep))

    def test_to_402_passes(self):
        outs, rep = self.convert(self.inp, "4.02", self.fcn)
        out = outs[0].data
        self.assertEqual(compare_obs_meta(self.inp, out, rep), [])
        # a record 4.02 defines may not be claimed as lost, nor dropped
        self.assertTrue(compare_obs_meta(self.inp, out,
                                         _claim(rep, "header-record-not-representable:SIGNAL STRENGTH UNIT")))
        self.assertTrue(compare_obs_meta(self.inp, _drop_line(out, b"SIGNAL STRENGTH UNIT"), rep))
        # 2.11 Table A7 event comments, re-checked after a round trip through 4.02
        self.assertTrue(compare_obs_meta(self.inp, _sub(out, b"TWO COMMENT LINES", b"TWO COMMENT LINEZ"), rep))

    def test_prn_counts_recounted(self):
        # PRN / # OF OBS of the output is checked against a recount of the output's values
        inp = (SPEC / "4.02" / "a5_obs_example2_derived_count.rnx").read_bytes()
        for t in ("2.11", "3.05"):
            with self.subTest(target=t):
                outs, rep = self.convert(inp, t)
                out = outs[0].data
                self.assertEqual(compare_obs_meta(inp, out, rep), [])
                lines = out.split(b"\n")
                k = next(i for i, l in enumerate(lines) if l.endswith(b"PRN / # OF OBS"))
                lines[k] = lines[k][:6] + b"%6d" % (int(lines[k][6:12]) + 1) + lines[k][12:]
                self.assertTrue(compare_obs_meta(inp, b"\n".join(lines), rep))

    def test_v211_events_to_305(self):
        inp = (SPEC / "2.11" / "a7_obs_mixed.rnx").read_bytes()
        fcn = table_file(self.tmp, "R21 1\nR22 1\n")
        outs, rep = self.convert(inp, "3.05", fcn)
        out = outs[0].data
        self.assertEqual(compare_obs_meta(inp, out, rep), [])
        self.assertTrue(compare_obs_meta(inp, _sub(out, b"ANTISPOOFING ON G 16", b"ANTISPOOFING ON G 17"), rep))
        self.assertTrue(compare_obs_meta(inp, _clock_edit(out, b"> 2005 03 24 13 12  6.0", _plus_1ns(12)), rep))
        self.assertTrue(compare_obs_meta(inp, _drop_line(out, b"OBSERVER / AGENCY"), rep))


class NavMeta(_Tmp):
    """rinex211.txt Table A8 (SPEC_211) and its hand-written 3.05 form (SPEC_305)."""

    def nav(self, data, target):
        outs = convert_data(data, "brdc2450.99n", Options(target, compression="none"))
        return [o.data for o in outs], outs[0].report.to_dict()

    def test_correct_conversions_pass(self):
        for src in (SPEC_211, SPEC_305):
            for t in ("2.10", "2.11", "3.00", "3.04", "3.05", "4.00", "4.02"):
                with self.subTest(src=src[:9], target=t):
                    outs, rep = self.nav(src, t)
                    self.assertEqual(compare_nav_meta(src, outs, rep), [])

    def test_dropped_ionospheric_corr_fails(self):
        outs, rep = self.nav(SPEC_211, "3.05")
        self.assertTrue(compare_nav_meta(SPEC_211, [_drop_line(outs[0], b"GPSB")], rep))
        self.assertTrue(compare_nav_meta(SPEC_211, [_drop_line(outs[0], b"TIME SYSTEM CORR")], rep))

    def test_changed_ionospheric_value_fails(self):
        outs, rep = self.nav(SPEC_211, "3.05")
        self.assertTrue(compare_nav_meta(SPEC_211, [_sub(outs[0], b"0.1310D+06", b"0.1311D+06")], rep))

    def test_rounding_without_claim_fails(self):
        # DELTA-UTC D19.12 -> TIME SYSTEM CORR D17.10/D16.9 rounds both values: claimed
        outs, rep = self.nav(SPEC_211, "3.05")
        self.assertEqual(rep["losses"]["nav-correction-precision:TIME SYSTEM CORR"]["count"], 2)
        self.assertTrue(compare_nav_meta(SPEC_211, outs, _lose(rep, "nav-correction-precision:TIME SYSTEM CORR")))
        # 3.05 -> 3.04 keeps the precision: rounding a coefficient there is a change
        outs, rep = self.nav(SPEC_305, "3.04")
        self.assertEqual(compare_nav_meta(SPEC_305, outs, rep), [])
        self.assertTrue(compare_nav_meta(SPEC_305, [_sub(outs[0], b"0.1331791282D-06", b"0.1331791280D-06")], rep))
        # rounding beyond half a unit of the last digit is a change even when claimed
        outs, rep = self.nav(SPEC_211, "3.05")
        self.assertTrue(compare_nav_meta(SPEC_211, [_sub(outs[0], b"0.1331791282D-06", b"0.1331791283D-06")], rep))

    def test_claimed_loss_that_did_not_happen_fails(self):
        outs, rep = self.nav(SPEC_211, "3.05")
        self.assertTrue(compare_nav_meta(SPEC_211, outs, _claim(rep, "nav-correction-not-representable:STO:GPUT")))
        self.assertTrue(compare_nav_meta(SPEC_211, outs, _claim(rep, "nav-correction-not-representable:ION:KLOB:G")))
        self.assertTrue(compare_nav_meta(SPEC_211, outs, _claim(rep, "nav-correction-precision:IONOSPHERIC CORR")))
        self.assertTrue(compare_nav_meta(SPEC_211, outs, _claim(rep, "header-field-not-representable:LEAP SECONDS")))

    def test_v4_records(self):
        outs, rep = self.nav(SPEC_305, "4.02")
        self.assertEqual(compare_nav_meta(SPEC_305, outs, rep), [])
        txt = outs[0].decode("latin-1").split("\n")
        k = next(i for i, l in enumerate(txt) if l.startswith("> STO"))
        bad = "\n".join(txt[:k] + txt[k + 3:]).encode("latin-1")
        self.assertTrue(compare_nav_meta(SPEC_305, [bad], rep))
        # and back: the v4 STO/ION records become header records again
        back, rep2 = self.nav(outs[0], "3.05")
        self.assertEqual(compare_nav_meta(outs[0], back, rep2), [])
        self.assertTrue(compare_nav_meta(outs[0], [_drop_line(back[0], b"GPSA")], rep2))

    def test_v4_sto_eop_ion_example(self):
        inp = (SPEC / "4.02" / "a41_nav_sto_eop_ion.rnx").read_bytes()
        outs, rep = self.nav(inp, "3.05")
        self.assertEqual(compare_nav_meta(inp, outs, rep), [])
        self.assertTrue(compare_nav_meta(inp, outs, _lose(rep, "nav-correction-not-representable:EOP")))
        self.assertTrue(compare_nav_meta(inp, [_drop_line(outs[0], b"GAUT")], rep))

    def test_leap_seconds(self):
        outs, rep = self.nav(SPEC_211, "3.05")
        self.assertTrue(compare_nav_meta(SPEC_211, [_sub(outs[0], b"    13" + b" " * 54 + b"LEAP SECONDS",
                                                         b"    14" + b" " * 54 + b"LEAP SECONDS")], rep))
        self.assertTrue(compare_nav_meta(SPEC_211, [_drop_line(outs[0], b"LEAP SECONDS")], rep))

    def test_comment_kept(self):
        outs, rep = self.nav(SPEC_211, "4.00")
        self.assertTrue(compare_nav_meta(SPEC_211, [_drop_line(outs[0], b"COMMENT")], rep))


class MetMeta(_Tmp):
    """rinex211.txt Table A9 met example."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inp = (SPEC / "2.11" / "a9_met.rnx").read_bytes()

    def met(self, target, inp=None):
        inp = self.inp if inp is None else inp
        outs = convert_data(inp, "x.rnx", Options(target, compression="none"))
        return outs[0].data, outs[0].report.to_dict()

    def test_correct_conversions_pass(self):
        for t in ("2.10", "3.05", "4.02"):
            with self.subTest(target=t):
                out, rep = self.met(t)
                self.assertEqual(compare_met_meta(self.inp, out, rep), [])

    def test_damage_fails(self):
        out, rep = self.met("3.05")
        self.assertTrue(compare_met_meta(self.inp, _drop_line(out, b"SENSOR POS XYZ/H"), rep))
        self.assertTrue(compare_met_meta(self.inp, _sub(out, b"740-16B", b"740-16C"), rep))
        self.assertTrue(compare_met_meta(self.inp, _sub(out, b"A 9080", b"A 9081"), rep))
        self.assertTrue(compare_met_meta(self.inp, _drop_line(out, b"COMMENT"), rep))
        self.assertTrue(compare_met_meta(self.inp, out, _claim(rep, "header-record-not-representable:MARKER NAME")))

    def test_sensor_of_lost_type(self):
        # 2.11 adds WD (rinex211.txt §10.3): to 2.10 the type and its sensor record go, claimed
        inp = self.inp.replace(b"     3    PR    TD    HR      ", b"     4    PR    TD    HR    WD")
        inp = inp.replace(b"ROTRONIC            I-240W                        5.0    HR SENSOR MOD/TYPE/ACC\n",
                          b"ROTRONIC            I-240W                        5.0    HR SENSOR MOD/TYPE/ACC\n"
                          b"VAISALA             WMT52                         3.0    WD SENSOR MOD/TYPE/ACC\n")
        inp = inp.replace(b"  89.5\n", b"  89.5  270.0\n")
        out, rep = self.met("2.10", inp)
        self.assertIn("header-record-not-representable:SENSOR MOD/TYPE/ACC:WD", rep["losses"])
        self.assertEqual(compare_met_meta(inp, out, rep), [])
        self.assertTrue(compare_met_meta(inp, out, _lose(rep, "header-record-not-representable:SENSOR MOD/TYPE/ACC:WD")))


if __name__ == "__main__":
    unittest.main()
