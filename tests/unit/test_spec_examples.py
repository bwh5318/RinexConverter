"""Spec examples layer (PLAN §1 clause 5d, §4): every example file printed in the RINEX
specs, run through our tools.

The fixtures are in tests/fixtures/spec_examples/<spec version>/. Each is the example
as printed in specs/text/*.txt, with only the page furniture removed, the spec's own
elision markers and line wraps undone, and the damage done by the PDF-to-text
extraction repaired. Every such change, and every error in the spec itself, is listed
in tests/fixtures/spec_errata.md (sections a-d); errata are referenced below as E-nn.
Files named *_derived_*.rnx are not as printed: they are minimal edits of an elided
example, listed in spec_errata.md §d.

For every fixture:
  1. it loads strictly (unless the example is invalid per its own spec: expectedFailure);
  2. same-version identity: the output equals the input after the normalisations PLAN
     §1 clause 7 allows (trailing blanks, D/E exponent letter, 0.000 vs blank for a
     missing observation, I2 fields ' 6' vs '06', '.123' vs '0.123', satellite ids
     'G 1'/'G01'/' 1') and the header repairs of clause 9 that the report lists;
  3. it converts to every write version with outcome 'converted', or
     'refused-not-representable' when the target can hold none of its systems;
  4. the independent token comparator (tests/independent/compare.py) finds no
     unexplained difference.
Standard library unittest; runs under pytest.
"""

import os
import re
import shutil
import tempfile
import unittest
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

from rinexconv.engine import Options, convert_data, load_bytes
from rinexcore.errors import CorruptError, NotRepresentableError
from tests.independent.compare import compare_met, compare_nav, compare_obs

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spec_examples"
TARGETS = ("2.10", "2.11", "3.00", "3.01", "3.02", "3.03", "3.04", "3.05", "4.00", "4.01", "4.02")

# Systems each target can hold, written from the specs (not from rinexcore/spec):
#   obs  2.10: G R S T (rinex210.txt Table A1, line 824); 2.11 adds E (rinex211.txt Table A1,
#        line 1079); 3.00: G R E S (rinex300.txt lines 459-461); 3.01 adds C (rinex301.txt
#        line 453); 3.02 adds J (rinex302.txt line 3264); 3.03 adds I (rinex303.txt line 2733).
#   nav  2.x: GPS (N), GLONASS (G), GEO/SBAS (H) files only (rinex211.txt Tables A3, A10, A15);
#        3.00/3.01: G R E S (rinex301.txt Table A4); 3.02: G R E J C S (rinex302.txt
#        lines 3261-3266); 3.03 adds I (rinex303.txt line 3540).
OBS_SYSTEMS = {"2.10": "GRST", "2.11": "GRSTE", "3.00": "GRES", "3.01": "GRESC", "3.02": "GRESCJ"}
NAV_SYSTEMS = {"2.10": "GRS", "2.11": "GRS", "3.00": "GRES", "3.01": "GRES", "3.02": "GRESCJ"}
ALL = "GRESCJI"

# Per-fixture expectations that follow from errata (keys: path relative to FIXTURES).
#   load:     the example is invalid per its own spec, so strict loading must fail
#             (expectedFailure; identity and conversions are skipped if it does fail)
#   identity: same-version identity cannot hold because of the erratum (expectedFailure)
#   glo_slots: GLONASS SLOT / FRQ # misses observed satellites (see below)
#   refuse:   the example is corrupt per its own spec; every conversion must end
#             refused-corrupt
META = {
    # 2.10 Table A7: the last event record says 4 records, 3 follow (fixed in 2.11).
    "2.10/a7_obs_mixed.rnx": {"load": "E-01"},
    # Example #2/#3 (3.03-3.05) and #3 (4.0x): header plus one epoch line whose satellites
    # are not printed, then an 'END OF FILE' comment outside any event record.
    "3.03/a4_obs_example2.rnx": {"load": "E-08"},
    "3.03/a4_obs_example3.rnx": {"load": "E-08"},
    "3.04/a4_obs_example2.rnx": {"load": "E-08"},
    "3.04/a4_obs_example3.rnx": {"load": "E-08"},
    "3.05/a4_obs_example2.rnx": {"load": "E-08"},
    "3.05/a4_obs_example3.rnx": {"load": "E-08"},
    "4.00/a6_obs_example3.rnx": {"load": "E-08"},
    "4.01/a6_obs_example3.rnx": {"load": "E-08"},
    "4.02/a6_obs_example3.rnx": {"load": "E-08"},
    # 2.11 Table A18: D-UTC A0,A1,T,W,S,U printed one column left of its 2D19.12,I7,I5,X,A5,X,I2
    # layout, so A0 reads '0.133179128170D-06-': refused-corrupt is the right outcome.
    "2.11/a18_nav_geo.rnx": {"refuse": "E-02"},
    # E-13: the CNV2 record has 9 of its 10 lines; the converter now refuses it (NAV.RECORD.LINES)
    "4.01/a12_nav_gps.rnx": {"refuse": "E-13"},
    # (4.01 Table A12 lacks BROADCAST ORBIT - 7; 4.02 'Table A12: add missing example data'.)
    # 4.0x Table A5: the epoch declares 42 satellites, 21 are printed ('[…]' elisions).
    "4.00/a5_obs_example2.rnx": {"load": "E-09"},
    "4.01/a5_obs_example2.rnx": {"load": "E-09"},
    "4.02/a5_obs_example2.rnx": {"load": "E-09"},
}
# 3.02+ obs example #1 observes R21 and R22, which its GLONASS SLOT / FRQ # does not list
# (E-07). The converter needs their channels even for the same version, so identity is
# checked with test-only channels and without that record.
for _v in ("3.02/a4_obs_mixed", "3.03/a4_obs_example1", "3.04/a4_obs_example1", "3.05/a4_obs_example1",
           "4.00/a4_obs_example1", "4.01/a4_obs_example1", "4.02/a4_obs_example1"):
    META[_v + ".rnx"] = {"glo_slots": "E-07"}
for _v in ("3.05/a4_obs_example1", "4.00/a4_obs_example1", "4.01/a4_obs_example1", "4.02/a4_obs_example1"):
    META[_v + ".rnx"]["time_columns"] = "E-10"

LABELS_REPAIRABLE = ("TIME OF FIRST OBS", "TIME OF LAST OBS", "INTERVAL", "# OF SATELLITES",
                     "PRN / # OF OBS")


def fixtures():
    out = []
    for p in sorted(FIXTURES.rglob("*.rnx")):
        out.append(p.relative_to(FIXTURES).as_posix())
    return out


def _lines(data):
    t = data.decode("latin-1").replace("\r\n", "\n")
    ls = t.split("\n")
    if ls and ls[-1] == "":
        ls.pop()
    return ls


def _kind(first):
    t = first[20:21]
    if t == "O":
        return "obs"
    if "MET" in first[20:40].upper():
        return "met"
    return "nav"


def _version(first):
    return "%.2f" % float(first[:9])


# ---------------------------------------------------------------------------
# normalisation for same-version identity (PLAN §1 clause 7)
# ---------------------------------------------------------------------------
_EXP = re.compile(r"(?<=[\d.])[DdEe](?=[+-]\d)")
_PAD2 = re.compile(r"(?<![\w.+-])0(\d)(?![\w.])")          # standalone '06' -> ' 6'
_PADSEC = re.compile(r"(?<![\w.+-])0(\d\.)")               # '06.0000000' -> ' 6.0000000'
_LEAD0 = re.compile(r"(?<![\d.])(-?)0\.(?=\d)")            # '0.123' -> ' .123', '-0.1' -> ' -.1'
_SATID = re.compile(r"(?<![A-Za-z0-9])([GRESCJI])[ 0](\d)(?!\d)")
_V2EPOCH = re.compile(r"^ [ \d]\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d[ \d.]{11}  [0-6][ \d]{2}\d")
_V2CONT = re.compile(r"^ {32}([A-Z ][ \d]\d)+$")


def _numbers(l):
    l = _EXP.sub("E", l)
    l = _PADSEC.sub(r" \1", l)
    l = _PAD2.sub(r" \1", l)
    l = _LEAD0.sub(lambda m: " " + m.group(1) + ".", l)
    return l


def _blank_missing(body):
    """F14.3 fields that are blank or zero -> blank ("Missing observations are written as 0.0
    or blanks", rinex211.txt line 1288; rinex305.txt §6.7)."""
    out = []
    for k in range(0, len(body), 16):
        f = body[k:k + 16]
        v = f[:14]
        if not v.strip(" 0.+-"):
            f = " " * 14 + f[14:]
        out.append(f)
    return "".join(out)


def _v2_satlist(l, dsys):
    head, sats = l[:32], l[32:68]
    rest = l[68:]
    trip = [sats[k:k + 3] for k in range(0, len(sats), 3)]
    fixed = []
    for t in trip:
        if t.strip() and t[1:].strip().isdigit():
            s = t[0] if t[0] != " " else dsys
            fixed.append(f"{s}{int(t[1:]):02d}")
        else:
            fixed.append(t)
    return head + "".join(fixed).ljust(len(sats)) + rest


def _v2_epoch(l):
    """(flag, count) if l is a RINEX 2 epoch/event line, else None."""
    l = l.ljust(32)
    if l[26:28] != "  " or not l[28].isdigit() or not l[29:32].strip().isdigit():
        return None
    if l[:26].strip() and not _V2EPOCH.match(l):
        return None
    return int(l[28]), int(l[29:32])


def normalise(data, labels_to_drop=()):
    ls = _lines(data)
    first = ls[0]
    kind, major = _kind(first), first[:9].strip()[0]
    dsys = first[40:41].strip()
    dsys = dsys if dsys and dsys != "M" else "G"
    out = []
    i = 0
    n = len(ls)
    while i < n:                                     # header
        l = ls[i].rstrip()
        i += 1
        lab = l[60:].strip()
        if lab not in labels_to_drop:
            out.append(_SATID.sub(r"\g<1>0\2", _numbers(l)).rstrip())
        if lab == "END OF HEADER":
            break
    nev = 0
    while i < n:                                     # body
        l = ls[i].rstrip()
        i += 1
        if nev:                                      # header record inside an event (flags 2-5)
            nev -= 1
            out.append(l)
            continue
        if kind != "obs":
            out.append(_SATID.sub(r"\g<1>0\2", _numbers(l)).rstrip())
            continue
        if major == "2":
            ev = _v2_epoch(l)
            if ev is not None:
                flag, cnt = ev
                if 2 <= flag <= 5:
                    nev = cnt
                l = _v2_satlist(l.ljust(68), dsys).rstrip() if len(l) > 32 else l
                out.append(_numbers(l).rstrip())
                continue
            if _V2CONT.match(l):
                out.append(_v2_satlist(l.ljust(68), dsys).rstrip())
                continue
            out.append(_numbers(_blank_missing(l)).rstrip())
        else:
            if l.startswith(">"):
                flag = l[31:32]
                if flag in "2345" and flag.strip():
                    nev = int(l[32:35] or 0)
                out.append(_numbers(l).rstrip())
                continue
            sat = _SATID.sub(r"\g<1>0\2", l[:3])
            out.append((sat + _numbers(_blank_missing(l[3:]))).rstrip())
    return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _time_tuple(y, mo, d, h, mi, sec):
    y = int(y)
    if y < 100:
        y += 1900 if y >= 80 else 2000
    q = Decimal(sec).quantize(Decimal("1e-7"), rounding=ROUND_FLOOR)
    return (y, int(mo), int(d), int(h), int(mi), q)


def expected_time_repairs(data):
    """{label: repair expected?} for TIME OF FIRST / LAST OBS, computed from the epoch
    lines (flags 0/1) floored to the records' F13.7 resolution (rinex211.txt Table A1,
    rinex305.txt Table A2). The record value is read by whitespace, so a record printed
    out of column (E-10) still compares by value."""
    ls = _lines(data)
    first = ls[0]
    if _kind(first) != "obs":
        return {}
    major = first[:9].strip()[0]
    hdr = {}
    i = 0
    for i, l in enumerate(ls):
        lab = l[60:].strip()
        if lab in ("TIME OF FIRST OBS", "TIME OF LAST OBS"):
            hdr[lab] = l[:43].split()
        if lab == "END OF HEADER":
            break
    times = []
    for l in ls[i + 1:]:
        if major == "2":
            ev = _v2_epoch(l)
            if ev and ev[0] <= 1 and l[:26].strip():
                times.append(_time_tuple(l[1:3], l[4:6], l[7:9], l[10:12], l[13:15], l[15:26]))
        elif l.startswith(">") and l[31:32] in "01" and l[1:29].strip():
            sec = Decimal(l[18:29])
            if l[56:62].strip():
                sec += Decimal(l[56:62].strip()).scaleb(-12)      # 4.02 picoseconds
            times.append(_time_tuple(l[2:6], l[7:9], l[10:12], l[13:15], l[16:18], sec))
    out = {}
    for lab, pick in (("TIME OF FIRST OBS", 0), ("TIME OF LAST OBS", -1)):
        if lab not in hdr or not times:
            continue
        try:
            have = _time_tuple(*hdr[lab][:6])
        except (ValueError, ArithmeticError, TypeError):
            out[lab] = True
            continue
        out[lab] = have != times[pick]
    return out


def systems_of(data):
    """Systems of the example's observations / ephemerides (satellite ids from our reader)."""
    ld = load_bytes(data, lenient=False)
    if ld.kind == "obs":
        return {s[0] for ep in ld.model.epochs for s in ep.sats}
    if ld.kind == "nav":
        return {r.system for r in ld.model.records if r.kind == "EPH"}
    return set()


def representable(kind, target, systems):
    """True / False, or None when the specs leave the outcome open: a navigation file
    with no ephemeris at all (only STO/EOP/ION records, or a bare header) has no RINEX 2
    file type to go to (rinex211.txt Tables A3, A10, A15), but its GPS ION/STO values
    would fit a GPS nav header. Either outcome is accepted there for RINEX 2 targets."""
    if kind == "met":
        return True
    table = OBS_SYSTEMS if kind == "obs" else NAV_SYSTEMS
    can = set(table.get(target, ALL))
    if not systems:
        return None if (kind == "nav" and target < "3") else True
    return bool(systems & can)


def glonass_without_channel(data):
    """GLONASS satellites observed but not listed in GLONASS SLOT / FRQ #."""
    ld = load_bytes(data, lenient=False)
    if ld.kind != "obs":
        return []
    listed = set()
    for r in ld.model.header:
        if r.label == "GLONASS SLOT / FRQ #":
            for m in re.finditer(r"R[ \d]\d", r.content[4:60]):
                listed.add("R%02d" % int(m.group(0)[1:]))
    seen = {s for ep in ld.model.epochs for s in ep.sats if s[0] == "R"}
    return sorted(seen - listed)


def compare(kind, data, outs):
    rep = outs[0].report.to_dict()
    if kind == "obs":
        return compare_obs(data, outs[0].data, rep)
    if kind == "nav":
        return compare_nav(data, [o.data for o in outs], rep)
    return compare_met(data, outs[0].data, rep)


def _diff(a, b, n=12):
    import difflib
    d = list(difflib.unified_diff(a, b, "input (normalised)", "output (normalised)", lineterm="", n=0))
    return "\n".join(d[:n * 3])


class _Base(unittest.TestCase):
    path = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="spec-examples-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def data(self):
        return (FIXTURES / self.path).read_bytes()

    def meta(self):
        return META.get(self.path, {})

    def skip_if_unloadable(self):
        """Skip when an example that is invalid as printed (META 'load') indeed fails to
        load; fail (once, with the reason) when any other example does not load."""
        m = self.meta()
        try:
            load_bytes(self.data(), lenient=False)
        except Exception as e:  # noqa: BLE001
            if m.get("load"):
                self.skipTest(f"example invalid as printed ({m['load']}); see the *_derived_* fixture")
            self.fail(f"strict load failed, and no erratum explains it: {type(e).__name__}: {e}")

    def glo_fcn(self, data):
        need = glonass_without_channel(data)
        if not need:
            return None
        p = os.path.join(self.tmp, re.sub(r"\W", "_", self.path) + ".fcn")
        with open(p, "wb") as fh:
            # test-only channel numbers for satellites the example observes but gives no channel for
            fh.write("".join(f"{s} 1\n" for s in need).encode("ascii"))
        return p

    # -- the three checks ------------------------------------------------------
    def check_load(self):
        try:
            load_bytes(self.data(), lenient=False)
        except Exception as e:  # noqa: BLE001
            self.fail(f"strict load failed: {type(e).__name__}: {e}")

    def check_identity(self):
        self.skip_if_unloadable()
        data = self.data()
        first = _lines(data)[0]
        v = _version(first)
        if v not in TARGETS:
            self.skipTest(f"RINEX {v} is not a write version")
        drop = set()
        fcn = None
        if self.meta().get("glo_slots"):
            # E-07: the example's GLONASS SLOT / FRQ # misses observed satellites; supply
            # test-only channels and leave that record out of the comparison
            fcn = self.glo_fcn(data)
            drop.add("GLONASS SLOT / FRQ #")
        opts = Options(target=v, compression="none", glo_fcn=fcn)
        if self.meta().get("refuse"):
            with self.assertRaises(CorruptError, msg=f"spec erratum {self.meta()['refuse']}"):
                convert_data(data, os.path.basename(self.path), opts)
            return
        try:
            outs = convert_data(data, os.path.basename(self.path), opts)
        except Exception as e:  # noqa: BLE001 - any exception is a failure here
            self.fail(f"same-version conversion raised {type(e).__name__} "
                      f"[{getattr(e, 'outcome', 'no outcome')}]: {e}")
        rep = outs[0].report.to_dict()
        reported = {lab for lab in LABELS_REPAIRABLE for r in rep["repairs"]
                    if lab in r["message"] or lab.replace(" ", "-") in r["rule"]}
        # clause 7: a repaired record may differ only where the repair is expected; for the
        # time records that is decided here independently, from the epochs themselves
        expected = expected_time_repairs(data)
        repaired = {lab for lab in reported if expected.get(lab, True)}
        if self.meta().get("time_columns") and "TIME OF FIRST OBS" in reported:
            # E-10: the record is printed two columns left; rewriting it in its columns is
            # the repair (the values are equal, so the independent check sees no change)
            repaired.add("TIME OF FIRST OBS")
        self.assertEqual(len(outs), 1, "same-version conversion split the file")
        a = normalise(data, repaired | drop)
        b = normalise(outs[0].data, repaired | drop)
        if a != b:
            self.fail(f"same-version output differs from the input beyond PLAN §1 clause 7 "
                      f"(repairs reported: {sorted(reported) or 'none'}; accepted: "
                      f"{sorted(repaired) or 'none'}):\n{_diff(a, b)}")

    def check_convert(self):
        self.skip_if_unloadable()
        data = self.data()
        kind = _kind(_lines(data)[0])
        systems = systems_of(data)
        fcn = self.glo_fcn(data)
        for t in TARGETS:
            with self.subTest(fixture=self.path, target=t):
                opts = Options(target=t, compression="none", assume_phase_aligned=True, glo_fcn=fcn)
                if self.meta().get("refuse"):
                    # the example is corrupt per its own spec: refused-corrupt is the right outcome
                    with self.assertRaises(CorruptError, msg=f"spec erratum {self.meta()['refuse']}") as cm:
                        convert_data(data, os.path.basename(self.path), opts)
                    self.assertEqual(cm.exception.outcome, "refused-corrupt")
                    continue
                rp = representable(kind, t, systems)
                if rp is False:
                    with self.assertRaises(NotRepresentableError) as cm:
                        convert_data(data, os.path.basename(self.path), opts)
                    self.assertEqual(cm.exception.outcome, "refused-not-representable")
                    continue
                try:
                    outs = convert_data(data, os.path.basename(self.path), opts)
                except NotRepresentableError:
                    if rp is None:
                        continue
                    raise
                except Exception as e:  # noqa: BLE001 - any exception is a failure here
                    self.fail(f"{type(e).__name__} [{getattr(e, 'outcome', 'no outcome')}]: {e}")
                rep = outs[0].report.to_dict()
                self.assertEqual(rep["outcome"], "converted", rep.get("message"))
                problems = compare(kind, data, outs)
                self.assertEqual(problems, [], "token comparator disagrees")


def _make(path):
    meta = META.get(path, {})
    name = "SpecExample_" + re.sub(r"\W", "_", path[:-4])

    def test_1_load(self):
        self.check_load()

    def test_2_identity(self):
        self.check_identity()

    def test_3_convert_all_targets(self):
        self.check_convert()

    if meta.get("load"):
        test_1_load = unittest.expectedFailure(test_1_load)
    if meta.get("identity"):
        test_2_identity = unittest.expectedFailure(test_2_identity)
    doc = f"{path}" + (f" (errata: {', '.join(sorted(set(meta.values())))})" if meta else "")
    test_1_load.__doc__ = f"{doc}: loads strictly"
    test_2_identity.__doc__ = f"{doc}: same-version identity"
    test_3_convert_all_targets.__doc__ = f"{doc}: converts to every write version"
    return type(name, (_Base,), {"path": path, "test_1_load": test_1_load,
                                 "test_2_identity": test_2_identity,
                                 "test_3_convert_all_targets": test_3_convert_all_targets})


class Inventory(unittest.TestCase):
    def test_fixtures_present(self):
        fs = fixtures()
        self.assertGreaterEqual(len(fs), 100, "spec example fixtures missing")
        for p in META:
            self.assertIn(p, fs, f"META names a fixture that does not exist: {p}")

    def test_fixtures_are_lf_latin1(self):
        for p in fixtures():
            data = (FIXTURES / p).read_bytes()
            self.assertNotIn(b"\r", data, p)
            self.assertTrue(data.endswith(b"\n"), p)
            data.decode("latin-1")


for _p in fixtures():
    _cls = _make(_p)
    globals()[_cls.__name__] = _cls
del _p, _cls


if __name__ == "__main__":
    unittest.main()
