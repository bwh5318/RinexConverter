"""Unit tests for the output validator rinexcore/validate.py (PLAN §1 clause 2, §3.8).

The small files below are written from the spec layouts, field by field (the format of
each line is in the comment next to its builder), not produced by our writer:
  obs  rinex211.txt Tables A1/A2; rinex305.txt Tables A2/A3; rinex_4.02.txt Tables A2/A3
  nav  rinex211.txt Tables A3/A4, A10/A11; rinex305.txt Tables A5-A10; rinex_4.02.txt
       Tables A7, A9, A15, A23, A33-A35
  met  rinex211.txt Tables A5/A6; rinex305.txt Tables A20/A21
Every valid sample must give no error; each check has a damaged copy that must give the
expected rule. The spec examples (tests/fixtures/spec_examples) are run and their findings
printed (not asserted, except for a few errata the validator must see). A corpus smoke test
runs a few real files the reader accepts.
Standard library unittest; runs under pytest.
"""

import gzip
import random
import unittest
from pathlib import Path

from rinexcore.errors import CorruptError
from rinexcore.validate import ERROR, WARNING, Finding, errors, rules, validate

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "spec_examples"
CORPUS = ROOT / "data" / "corpus"


# ---------------------------------------------------------------------------
# field writers (Fortran formats of the specs)
# ---------------------------------------------------------------------------
def hdr(content, label):
    """Header line: A60 content, label in columns 61-80."""
    assert len(content) <= 60, content
    return content.ljust(60) + label


def f14(v, lli=" ", ssi=" "):
    """Observation field F14.3,I1,I1 (blank value if v is None)."""
    return (" " * 14 if v is None else f"{v:14.3f}") + lli + ssi


def d19(v, letter="D"):
    """Navigation number D19.12."""
    return f"{v:19.12E}".replace("E", letter)


def tfirst(y, mo, d, h, mi, s, ts="GPS"):
    """TIME OF FIRST/LAST OBS 5I6,F13.7,5X,A3."""
    return f"{y:6d}{mo:6d}{d:6d}{h:6d}{mi:6d}{s:13.7f}     {ts:3s}"


def payload(lines):
    return ("\n".join(lines) + "\n").encode("latin-1")


def has(findings, rule, severity=None):
    return any(f.rule == rule and (severity is None or f.severity == severity) for f in findings)


# ---------------------------------------------------------------------------
# RINEX 2.11 observation file: GPS + GLONASS, 7 types (2 data lines per satellite),
# 13 satellites in one epoch (satellite-list continuation), an event with a COMMENT.
# ---------------------------------------------------------------------------
V2_TYPES = ["C1", "L1", "L2", "P2", "D1", "S1", "S2"]
V2_SATS_A = ["G01", "G02", "R01"]
V2_SATS_B = [f"G{k:02d}" for k in range(1, 11)] + ["R01", "R02", "R03"]


def v2_value(sat, k, ep):
    base = 20000000.0 + 1000.0 * int(sat[1:]) + (500.0 if sat[0] == "R" else 0.0)
    return base + 100.0 * k + 0.125 * ep


def v2_record(sat, ep):
    """5 fields per line (rinex211.txt Table A2: 'If more than 5 observation types')."""
    fields = [f14(v2_value(sat, k, ep), " ", "7") for k in range(len(V2_TYPES))]
    return ["".join(fields[:5]), "".join(fields[5:])]


def v2_epoch_line(y, mo, d, h, mi, s, flag, sats, clock=None):
    """1X,I2.2,4(1X,I2),F11.7,2X,I1,I3,12(A1,I2),F12.9 (+ 32X,12(A1,I2) continuation)."""
    head = f" {y % 100:02d} {mo:2d} {d:2d} {h:2d} {mi:2d}{s:11.7f}  {flag:1d}{len(sats):3d}"
    out = []
    for k in range(0, max(1, len(sats)), 12):
        ids = "".join(f"{x[0]}{int(x[1:]):2d}" for x in sats[k:k + 12])
        if k == 0:
            line = head + ids.ljust(36)
            if clock is not None:
                line += f"{clock:12.9f}"
            out.append(line.rstrip())
        else:
            out.append((" " * 32 + ids).rstrip())
    return out


def v2_obs(version="2.11", with_counts=True):
    epochs = [((2026, 10, 30, 0, 0, 0.0), V2_SATS_A), ((2026, 10, 30, 0, 0, 30.0), V2_SATS_B),
              ((2026, 10, 30, 0, 1, 0.0), V2_SATS_A)]
    sats = sorted({s for _, ss in epochs for s in ss})
    h = [hdr(f"{version:>9s}           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                30-OCT-26 12:00", "PGM / RUN BY / DATE"),
         hdr("TEST", "MARKER NAME"),
         hdr("OBSERVER            AGENCY", "OBSERVER / AGENCY"),
         hdr("1234                TESTRCV             1.0", "REC # / TYPE / VERS"),
         hdr("5678                TESTANT", "ANT # / TYPE"),
         hdr("  4000000.0000  1000000.0000  4800000.0000", "APPROX POSITION XYZ"),
         hdr("        0.1000        0.0000        0.0000", "ANTENNA: DELTA H/E/N"),
         hdr("     1     1", "WAVELENGTH FACT L1/2"),
         hdr(f"{len(V2_TYPES):6d}" + "".join(f"{c:>6s}" for c in V2_TYPES), "# / TYPES OF OBSERV"),
         hdr("    30.000", "INTERVAL"),
         hdr(tfirst(2026, 10, 30, 0, 0, 0.0), "TIME OF FIRST OBS"),
         hdr(tfirst(2026, 10, 30, 0, 1, 0.0), "TIME OF LAST OBS")]
    if with_counts:
        h.append(hdr(f"{len(sats):6d}", "# OF SATELLITES"))
        for s in sats:
            n = sum(1 for _, ss in epochs if s in ss)
            h.append(hdr(f"   {s[0]}{int(s[1:]):2d}" + "".join(f"{n:6d}" for _ in V2_TYPES),
                         "PRN / # OF OBS"))
    h.append(hdr("", "END OF HEADER"))
    body = []
    for ep, (t, ss) in enumerate(epochs):
        body += v2_epoch_line(*t, 0, ss)
        for s in ss:
            body += v2_record(s, ep)
        if ep == 0:      # an event with one special record (flag 5, significant epoch)
            body += [" 26 10 30  0  0 15.0000000  5  1",
                     hdr("EXTERNAL EVENT", "COMMENT")]
    return h + body


# ---------------------------------------------------------------------------
# RINEX 3.05 observation file: GPS (14 types, a continuation line) + GLONASS
# ---------------------------------------------------------------------------
G_TYPES = ["C1C", "L1C", "D1C", "S1C", "C2W", "L2W", "D2W", "S2W", "C5Q", "L5Q", "D5Q", "S5Q",
           "C1W", "S1W"]
R_TYPES = ["C1C", "L1C", "D1C", "S1C"]


def sys_types(s, codes):
    """A1,2X,I3,13(1X,A3) + 6X,13(1X,A3)."""
    out = []
    for k in range(0, len(codes), 13):
        head = f"{s}  {len(codes):3d}" if k == 0 else " " * 6
        out.append(hdr(head + "".join(f" {c}" for c in codes[k:k + 13]), "SYS / # / OBS TYPES"))
    return out


def v3_value(sat, k, ep):
    return 20000000.0 + 1000.0 * int(sat[1:]) + 10.0 * k + 0.25 * ep + (300.0 if sat[0] == "R" else 0)


def v3_record(sat, ep, types):
    """A1,I2.2,m(F14.3,I1,I1)."""
    return sat + "".join(f14(v3_value(sat, k, ep), " ", "8") for k in range(len(types)))


def v3_epoch_line(y, mo, d, h, mi, s, flag, n, clock=None, ps=None):
    """'>',1X,I4,4(1X,I2.2),F11.7,2X,I1,I3,6X,F15.12[,1X,I5.5 (4.02)]."""
    line = f"> {y:4d} {mo:02d} {d:02d} {h:02d} {mi:02d}{s:11.7f}  {flag:1d}{n:3d}"
    if clock is not None or ps is not None:
        line += " " * 6 + (f"{clock:15.12f}" if clock is not None else " " * 15)
    if ps is not None:
        line += f" {ps:05d}"
    return line


def v3_obs(version="3.05", letter="M", systems=("G", "R"), extra_header=(), phase_label=None):
    types = {"G": G_TYPES, "R": R_TYPES}
    sats = [s for s in ("G01", "G02", "R01", "R02") if s[0] in systems]
    times = [(2026, 10, 30, 0, 0, 0.0), (2026, 10, 30, 0, 0, 30.0), (2026, 10, 30, 0, 1, 0.0)]
    phase_label = phase_label or ("SYS / PHASE SHIFTS" if version == "3.01" else "SYS / PHASE SHIFT")
    h = [hdr(f"{version:>9s}           OBSERVATION DATA    {letter}", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
         hdr("TEST", "MARKER NAME"),
         hdr("GEODETIC", "MARKER TYPE"),
         hdr("OBSERVER            AGENCY", "OBSERVER / AGENCY"),
         hdr("1234                TESTRCV             1.0", "REC # / TYPE / VERS"),
         hdr("5678                TESTANT", "ANT # / TYPE"),
         hdr("  4000000.0000  1000000.0000  4800000.0000", "APPROX POSITION XYZ"),
         hdr("        0.1000        0.0000        0.0000", "ANTENNA: DELTA H/E/N")]
    for s in systems:
        h += sys_types(s, types[s])
    if version < "4" and version >= "3.01":
        for s in systems:
            # A1,1X,A3,1X,F8.5,...: code given, rest blank = only reference signals
            h.append(hdr(f"{s} L1C", phase_label))
    h += [hdr("    30.000", "INTERVAL"),
          hdr(tfirst(*times[0]), "TIME OF FIRST OBS"),
          hdr(tfirst(*times[-1]), "TIME OF LAST OBS")]
    if "R" in systems and version >= "3.01":
        h.append(hdr("  2 R01  1 R02 -4", "GLONASS SLOT / FRQ #"))       # I3,1X,8(A1,I2.2,1X,I2,1X)
        if "3.02" <= version < "4":       # mandatory 3.02-3.05, strongly deprecated in 4.x
            h.append(hdr(" C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS"))
    h += list(extra_header)
    h.append(hdr(f"{len(sats):6d}", "# OF SATELLITES"))
    for s in sats:
        n = len(types[s[0]])
        vals = [len(times)] * n
        for k in range(0, n, 9):               # 3X,A1,I2.2,9I6 + 6X,9I6
            head = f"   {s}" if k == 0 else " " * 6
            h.append(hdr(head + "".join(f"{v:6d}" for v in vals[k:k + 9]), "PRN / # OF OBS"))
    h.append(hdr("", "END OF HEADER"))
    body = []
    for ep, t in enumerate(times):
        body.append(v3_epoch_line(*t, 0, len(sats)))
        body += [v3_record(s, ep, types[s[0]]) for s in sats]
    return h + body


def v4_obs(version="4.02"):
    """GPS-only RINEX 4.02 file with a picosecond epoch and a clock offset."""
    lines = v3_obs(version, "G", ("G",))
    k = next(i for i, x in enumerate(lines) if x.startswith("> "))
    lines[k] = v3_epoch_line(2026, 10, 30, 0, 0, 0.0, 0, 2, clock=0.000123456789, ps=12345)
    lines.insert(next(i for i, x in enumerate(lines) if x.endswith("INTERVAL")),
                 hdr("     1", "RCV CLOCK OFFS APPL"))
    return lines


# ---------------------------------------------------------------------------
# navigation files
# ---------------------------------------------------------------------------
def nav_v2_record(prn, t, nlines, letter="D"):
    """I2,1X,I2.2,4(1X,I2),F5.1,3D19.12 then 3X,4D19.12 lines."""
    y, mo, d, h, mi, s = t
    out = [f"{prn:2d} {y % 100:02d} {mo:2d} {d:2d} {h:2d} {mi:2d}{s:5.1f}"
           + "".join(d19(1e-4 * (j + 1), letter) for j in range(3))]
    for i in range(1, nlines):
        # GPS BROADCAST ORBIT 7 fields 3-4 are spares (rinex211.txt Table A4 l.1411-1412): 0
        out.append("   " + "".join(d19(0.0 if (nlines == 8 and i == 7 and j >= 2) else 1.5 * i + j, letter)
                                   for j in range(4)))
    return out


def nav_v2_gps():
    h = [hdr("     2.11           N: GPS NAV DATA", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                30-OCT-26 12:00", "PGM / RUN BY / DATE"),
         hdr("  " + "".join(f"{v:12.4E}".replace("E", "D") for v in (1.676e-8, 2.235e-8, -1.192e-7,
                                                                    -1.192e-7)), "ION ALPHA"),
         hdr("  " + "".join(f"{v:12.4E}".replace("E", "D") for v in (1.208e5, 1.311e5, -1.311e5,
                                                                    -1.966e5)), "ION BETA"),
         hdr("   " + d19(1.3e-7) + d19(1.1e-13) + f"{552960:9d}{2391:9d}", "DELTA-UTC: A0,A1,T,W"),
         hdr("    18", "LEAP SECONDS"),
         hdr("", "END OF HEADER")]
    return h + nav_v2_record(1, (2026, 10, 30, 0, 0, 0.0), 8) + nav_v2_record(2, (2026, 10, 30, 2, 0, 0.0), 8)


def nav_v2_glonass():
    h = [hdr("     2.11           G: GLONASS NAV DATA", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                30-OCT-26 12:00", "PGM / RUN BY / DATE"),
         hdr(f"{2026:6d}{10:6d}{30:6d}   " + d19(-1.1e-8), "CORR TO SYSTEM TIME"),
         hdr("", "END OF HEADER")]
    return h + nav_v2_record(1, (2026, 10, 30, 0, 15, 0.0), 4)


def nav_v3_record(sat, t, nlines, letter="E", last=4):
    """A1,I2.2,1X,I4,5(1X,I2.2),3D19.12 then 4X,4D19.12 lines (`last` fields on the last one:
    RINEX 4 LNAV and BDS D1/D2 orbit 7 define two, rinex_4.02.txt Tables A9 p.79, A23 p.100).
    A GLONASS record's message frame time is Toc in seconds of the UTC week, as RINEX 3/4
    define it (rinex305.txt Table A10 p.74; round 32: 6e-5 on a Friday is the day basis)."""
    import datetime
    y, mo, d, h, mi, s = t
    vals = [2e-5 * (j + 1) for j in range(3)]
    if sat[0] == "R":
        vals[2] = ((datetime.date(y, mo, d).weekday() + 1) % 7) * 86400 + h * 3600 + mi * 60 + s
    out = [f"{sat} {y:4d} {mo:02d} {d:02d} {h:02d} {mi:02d} {s:02d}"
           + "".join(d19(v, letter) for v in vals)]
    # spare fields hold 0 (rinex305.txt Tables A6, A8, A12, A14, A18; section 6.4 p.42)
    spare = {"G": {7: (2, 3)}, "J": {7: (2, 3)}, "E": {5: (3,), 7: (1, 2, 3)},
             "C": {5: (1, 3), 7: (2, 3)}, "I": {5: (1, 3), 6: (3,), 7: (1, 2, 3)}}.get(sat[0], {})
    for i in range(1, nlines):
        out.append("    " + "".join(d19(0.0 if j in spare.get(i, ()) else 0.5 * i - j, letter)
                                    for j in range(4 if i < nlines - 1 else last)))
    return out


def nav_v3(version="3.05", glo_lines=None):
    glo_lines = glo_lines or (5 if version >= "3.05" else 4)
    h = [hdr(f"{version:>9s}           N: GNSS NAV DATA    M: MIXED", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
         hdr("GPSA " + "".join(f"{v:12.4E}" for v in (1.676e-8, 2.235e-8, -1.192e-7, -1.192e-7)),
             "IONOSPHERIC CORR"),
         # A4,1X,D17.10,D16.9,I7,I5,1X,A5,1X,I2
         hdr("GPUT " + f"{1.3e-7:17.10E}{1.1e-13:16.9E}{552960:7d}{2391:5d} G10    2",
             "TIME SYSTEM CORR"),
         hdr("    18", "LEAP SECONDS"),
         hdr("", "END OF HEADER")]
    return (h + nav_v3_record("G01", (2026, 10, 30, 0, 0, 0), 8)
            + nav_v3_record("R01", (2026, 10, 30, 0, 15, 0), glo_lines)
            + nav_v3_record("E11", (2026, 10, 30, 0, 10, 0), 8))


def nav_v4(version="4.02", letter="E"):
    stamp = "2026 10 30 00 00 00"
    h = [hdr(f"{version:>9s}           N: GNSS NAV DATA    M: MIXED", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
         hdr("    18", "LEAP SECONDS"),
         hdr("", "END OF HEADER")]
    num = lambda *v: "".join(d19(x, letter) for x in v)
    b = ["> EPH G01 LNAV"] + nav_v3_record("G01", (2026, 10, 30, 0, 0, 0), 8, letter, last=2)
    b += ["> EPH R01 FDMA"] + nav_v3_record("R01", (2026, 10, 30, 0, 15, 0), 5, letter)
    c05 = nav_v3_record("C05", (2026, 10, 30, 0, 0, 0), 8, letter, last=2)
    # BROADCAST ORBIT 5 'IDOT, Spare, BDT Week #, Spare' (rinex_4.02.txt Table A23 p.100):
    # spare fields are to be left blank (section 6.4 p.48)
    c05[5] = c05[5][:23] + " " * 19 + c05[5][42:61]
    b += ["> EPH C05 D2"] + c05
    # STO: 4X,I4,5(1X,I2.2),1X,A18,1X,A18,1X,A18 then 4X,4D19.12 (Table A33)
    b += ["> STO G01 LNAV",
          f"    {stamp} " + "GPUT".ljust(18) + " " + " " * 18 + " " + "UTC(USNO)".ljust(18),
          "    " + num(1.0e5, 1.0e-9, 0.0, 0.0)]
    # ION Klobuchar: epoch + 3 numbers, 4X,4D19.12, 4X,D19.12 (Table A35)
    b += ["> ION G01 LNAV", f"    {stamp}" + num(1e-8, 2e-8, -6e-8), "    " + num(-1e-7, 9e4, 1e5, -6e4),
          "    " + num(-5e5)]
    # ION NeQuick-G: epoch + 3 numbers, 4X,D19.12 (Table A36)
    b += ["> ION E11 IFNV", f"    {stamp}" + num(54.5, 0.36, 0.0136), "    " + num(0.0)]
    # EOP: epoch + 3, 4X,A19 (spare) + 3, 4X,4D19.12 (Table A34)
    b += ["> EOP G01 LNAV", f"    {stamp}" + num(0.2, -2.6e-4, 0.0), " " * 23 + num(0.33, -1.4e-3, 0.0),
          "    " + num(2.5e5, -0.17, -8e-5, 0.0)]
    if version >= "4.02":
        b += ["> ION J01 CNVX WIDE", f"    {stamp}" + num(1e-8, 2e-8, -6e-8),
              "    " + num(-1e-7, 9e4, 1e5, -6e4), "    " + num(-5e5)]
    return h + b


# ---------------------------------------------------------------------------
# meteorological files
# ---------------------------------------------------------------------------
def met(version="2.11", types=("PR", "TD", "HR")):
    v2 = version < "3.02"
    h = [hdr(f"{version:>9s}           METEOROLOGICAL DATA", "RINEX VERSION / TYPE"),
         hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
         hdr("TEST", "MARKER NAME")]
    for k in range(0, len(types), 9):                  # I6,9(4X,A2) + 6X,9(4X,A2)
        head = f"{len(types):6d}" if k == 0 else " " * 6
        h.append(hdr(head + "".join(f"{t:>6s}" for t in types[k:k + 9]), "# / TYPES OF OBSERV"))
    for t in types:                                    # A20,A20,6X,F7.1,4X,A2,1X
        h.append(hdr("MAKER".ljust(20) + "MODEL".ljust(20) + " " * 6 + f"{0.1:7.1f}" + " " * 4 + t,
                     "SENSOR MOD/TYPE/ACC"))
    h.append(hdr(f"{0.0:14.4f}{0.0:14.4f}{0.0:14.4f}{123.4567:14.4f} PR", "SENSOR POS XYZ/H"))
    h.append(hdr("", "END OF HEADER"))
    body = []
    for k in range(3):
        stamp = (f" {26:02d}" if v2 else f" {2026:4d}") + f" {10:2d} {30:2d} {0:2d} {k:2d} {0:2d}"
        vals = [f"{900.0 + j + 0.1 * k:7.1f}" for j in range(len(types))]
        body.append(stamp + "".join(vals[:8]))
        for j in range(8, len(vals), 10):              # 4X,10F7.1
            body.append("    " + "".join(vals[j:j + 10]))
    return h + body


MET10 = ("PR", "TD", "HR", "ZW", "ZD", "ZT", "WD", "WS", "RI", "HI")


# ---------------------------------------------------------------------------
# helpers to damage a file
# ---------------------------------------------------------------------------
def drop_label(lines, label):
    return [x for x in lines if x[60:].strip() != label]


def index_of(lines, pred):
    return next(i for i, x in enumerate(lines) if pred(x))


def label_index(lines, label):
    return index_of(lines, lambda x: x[60:].strip() == label)


def replace_label_content(lines, label, content):
    out = list(lines)
    out[label_index(out, label)] = hdr(content, label)
    return out


def first_data(lines):
    return label_index(lines, "END OF HEADER") + 1


class ValidSamples(unittest.TestCase):
    """Hand-written files of each kind and several versions: no errors."""

    def clean(self, lines, allow_warnings=()):
        f = validate(payload(lines))
        self.assertEqual(errors(f), [], f)
        warn = [x for x in f if x.severity == WARNING and x.rule not in allow_warnings]
        self.assertEqual(warn, [], warn)
        return f

    def test_obs_211(self):
        self.clean(v2_obs("2.11"))

    def test_obs_210(self):
        self.clean(v2_obs("2.10"))

    def test_obs_v2_without_counts(self):
        self.clean(v2_obs("2.11", with_counts=False))

    def test_obs_v2_crlf(self):
        f = validate(payload(v2_obs()).replace(b"\n", b"\r\n"))
        self.assertEqual(errors(f), [])

    def test_obs_305(self):
        self.clean(v3_obs("3.05"))

    def test_obs_302_303_304(self):
        for v in ("3.02", "3.03", "3.04"):
            with self.subTest(v):
                self.clean(v3_obs(v))

    def test_obs_301_phase_shifts_spelling(self):
        # 3.01 spells the label SYS / PHASE SHIFTS (rinex301.txt p.32); GLONASS COD/PHS/BIS
        # does not exist yet; GLONASS SLOT / FRQ # is optional.
        self.clean(v3_obs("3.01"))

    def test_obs_300(self):
        self.clean(v3_obs("3.00"))

    def test_obs_gps_only_without_glonass_records(self):
        self.clean(v3_obs("3.05", "G", ("G",)))

    def test_obs_400_401(self):
        for v in ("4.00", "4.01"):
            with self.subTest(v):
                self.clean(v3_obs(v))

    def test_obs_402_picoseconds_and_clock(self):
        self.clean(v4_obs("4.02"))

    def test_nav_211_gps_and_glonass(self):
        self.clean(nav_v2_gps())
        self.clean(nav_v2_glonass())

    def test_nav_305_mixed(self):
        self.clean(nav_v3("3.05"))

    def test_nav_304_glonass_four_lines(self):
        self.clean(nav_v3("3.04"))

    def test_nav_402(self):
        self.clean(nav_v4("4.02"))

    def test_nav_400_d_letter_warns_only(self):
        f = self.clean(nav_v4("4.00", "D"), allow_warnings=("VAL.NAV.EXPONENT.DEPRECATED",))
        self.assertTrue(has(f, "VAL.NAV.EXPONENT.DEPRECATED", WARNING))

    def test_met_211_and_305(self):
        self.clean(met("2.11"))
        self.clean(met("3.05"))

    def test_met_continuations(self):
        self.clean(met("3.05", MET10))
        self.clean(met("2.11", MET10))

    def test_met_301_two_digit_year(self):
        # 3.00/3.01 met epochs keep the 2-digit year (rinex301.txt Table A14 p.43)
        self.clean(met("3.01"))


class FindingObject(unittest.TestCase):
    def test_fields_and_repairable(self):
        lines = replace_label_content(v2_obs(), "TIME OF FIRST OBS", tfirst(2026, 10, 30, 0, 0, 1.0))
        f = [x for x in validate(payload(lines)) if x.rule == "VAL.HDR.TIME-OF-FIRST-OBS"]
        self.assertEqual(len(f), 1)
        x = f[0]
        self.assertIsInstance(x, Finding)
        self.assertEqual(x.severity, ERROR)
        self.assertEqual(x.scope, "header")
        self.assertTrue(x.repairable)
        self.assertEqual(x.line, label_index(lines, "TIME OF FIRST OBS") + 1)
        d = x.as_dict()
        self.assertEqual(set(d), {"severity", "rule", "message", "line", "column", "scope", "repairable"})

    def test_cap_per_rule(self):
        lines = v3_obs()
        k = first_data(lines)
        lines = lines[:k] + [""] * 30 + lines[k:]
        f = validate(payload(lines), max_per_rule=5)
        self.assertEqual(rules(f).get("VAL.OBS.BLANK-LINE"), 5)
        self.assertTrue(has(f, "VAL.FINDINGS.SUPPRESSED"))


class Unreadable(unittest.TestCase):
    def test_raises_only_corrupt(self):
        for data in (b"", b"\n", b"hello world\n", gzip.compress(payload(v2_obs())),
                     payload(["1.0                 COMPACT RINEX FORMAT                    CRINEX VERS   / TYPE"]),
                     payload([hdr("     x.yy           OBSERVATION DATA", "RINEX VERSION / TYPE")]),
                     payload([hdr("     3.05           Q", "RINEX VERSION / TYPE")])):
            with self.subTest(data[:30]):
                with self.assertRaises(CorruptError):
                    validate(data)

    def test_fuzz_only_corrupt_escapes(self):
        rng = random.Random(20261030)
        samples = [payload(x) for x in (v2_obs(), v3_obs(), v4_obs(), nav_v2_gps(), nav_v3(),
                                        nav_v4(), met("2.11"), met("3.05", MET10))]
        alphabet = b" 0123456789.-+>DEGRSJCIabc\n\r\t\xb2\xff"
        for case in range(400):
            data = bytearray(rng.choice(samples))
            for _ in range(rng.randint(1, 12)):
                op = rng.random()
                pos = rng.randrange(len(data))
                if op < 0.5:
                    data[pos] = rng.choice(alphabet)
                elif op < 0.75:
                    del data[pos:pos + rng.randint(1, 40)]
                else:
                    data[pos:pos] = bytes(rng.choice(alphabet) for _ in range(rng.randint(1, 20)))
            try:
                f = validate(bytes(data))
            except CorruptError:
                continue
            self.assertIsInstance(f, list, case)


class ObsHeaderChecks(unittest.TestCase):
    def check(self, lines, rule, severity=ERROR):
        f = validate(payload(lines))
        self.assertTrue(has(f, rule, severity), f)
        return f

    def test_end_of_header_missing(self):
        lines = v3_obs()
        self.check(lines[:label_index(lines, "END OF HEADER")], "VAL.HDR.END")

    def test_mandatory_missing(self):
        for label in ("MARKER NAME", "TIME OF FIRST OBS", "ANT # / TYPE", "SYS / PHASE SHIFT",
                      "GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS"):
            with self.subTest(label):
                f = self.check(drop_label(v3_obs("3.05"), label), "VAL.HDR.MANDATORY")
                self.assertTrue(any(label in x.message for x in f if x.rule == "VAL.HDR.MANDATORY"))

    def test_wavelength_fact_mandatory_in_210_only(self):
        self.check(drop_label(v2_obs("2.10"), "WAVELENGTH FACT L1/2"), "VAL.HDR.MANDATORY")
        self.assertEqual(errors(validate(payload(drop_label(v2_obs("2.11"), "WAVELENGTH FACT L1/2")))), [])

    def test_glonass_records_not_required_without_glonass(self):
        f = validate(payload(v3_obs("3.05", "G", ("G",))))
        self.assertFalse(has(f, "VAL.HDR.MANDATORY"))

    def test_label_placement(self):
        lines = v3_obs()
        k = label_index(lines, "MARKER NAME")
        lines[k] = "TEST".ljust(61) + "MARKER NAME"            # col 62, still inside 61-80
        self.check(lines, "VAL.HDR.LABEL.PLACEMENT", WARNING)
        lines = v3_obs()
        k = label_index(lines, "TIME OF FIRST OBS")
        lines[k] = tfirst(2026, 10, 30, 0, 0, 0.0).ljust(64) + "TIME OF FIRST OBS"   # past col 80
        self.check(lines, "VAL.HDR.LABEL.PLACEMENT")
        lines = v3_obs()
        k = label_index(lines, "MARKER NAME")
        lines[k] = "TEST".ljust(59) + "MARKER NAME"            # col 60
        self.check(lines, "VAL.HDR.LABEL.PLACEMENT")

    def test_label_without_text(self):
        lines = v3_obs()
        lines.insert(3, "SOME TEXT WITHOUT A LABEL")
        self.check(lines, "VAL.HDR.LABEL.MISSING")

    def test_unknown_and_other_version_labels(self):
        f = validate(payload(v3_obs(extra_header=[hdr("X", "MY OWN LABEL"),
                                                  hdr("10.1234/abc", "DOI")])))
        self.assertTrue(has(f, "VAL.HDR.LABEL.UNKNOWN", WARNING))
        self.assertTrue(has(f, "VAL.HDR.LABEL.VERSION", WARNING))      # DOI is 4.x only
        self.assertEqual(errors(f), [])

    def test_phase_shift_spelling(self):
        # 3.01's 'SYS / PHASE SHIFTS' in 3.05: a spelling warning, and no missing record
        f = validate(payload(v3_obs("3.05", phase_label="SYS / PHASE SHIFTS")))
        self.assertTrue(has(f, "VAL.HDR.LABEL.SPELLING", WARNING))
        self.assertFalse(has(f, "VAL.HDR.MANDATORY"))
        f = validate(payload(v3_obs("3.01", phase_label="SYS / PHASE SHIFT")))
        self.assertTrue(has(f, "VAL.HDR.LABEL.SPELLING", WARNING))

    def test_blank_header_line(self):
        lines = v3_obs()
        lines.insert(3, "")
        self.check(lines, "VAL.HDR.BLANK-LINE", WARNING)

    def test_version_field(self):
        lines = v2_obs()
        lines[0] = hdr("      2.1           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE")
        self.check(lines, "VAL.HDR.VERSION.FORMAT", WARNING)
        lines[0] = hdr("     2.12           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE")
        self.check(lines, "VAL.VERSION.UNSUPPORTED", WARNING)

    def test_v2_type_count(self):
        lines = replace_label_content(v2_obs(), "# / TYPES OF OBSERV",
                                      "     8" + "".join(f"{c:>6s}" for c in V2_TYPES))
        self.check(lines, "VAL.HDR.OBSTYPES.COUNT")

    def test_v2_type_layout_and_code(self):
        lines = replace_label_content(v2_obs(), "# / TYPES OF OBSERV",
                                      "     7  C1      L1    L2    P2    D1    S1    S2")
        self.check(lines, "VAL.HDR.OBSTYPES.LAYOUT")
        types = ["C1", "L1", "L2", "P2", "D1", "S1", "C9"]
        lines = replace_label_content(v2_obs(), "# / TYPES OF OBSERV",
                                      "     7" + "".join(f"{c:>6s}" for c in types))
        self.check(lines, "VAL.HDR.OBSTYPES.CODE", WARNING)

    def test_v3_type_count_layout_code(self):
        lines = v3_obs()
        k = index_of(lines, lambda x: x.startswith("R    4") and "SYS / # / OBS TYPES" in x)
        good = lines[k]
        lines[k] = good.replace("R    4", "R    5")
        self.check(lines, "VAL.HDR.OBSTYPES.COUNT")
        lines[k] = hdr("R    4  C1C L1C D1C S1C", "SYS / # / OBS TYPES")       # shifted by one
        self.check(lines, "VAL.HDR.OBSTYPES.LAYOUT")
        lines[k] = hdr("R    4 C1C L1C D1C S1Z", "SYS / # / OBS TYPES")        # no GLONASS 1Z
        self.check(lines, "VAL.HDR.OBSTYPES.CODE", WARNING)

    def test_v3_continuation_without_system(self):
        lines = v3_obs()
        k = index_of(lines, lambda x: x.startswith("G   14"))
        lines.insert(k, hdr("       C1C", "SYS / # / OBS TYPES"))
        self.check(lines, "VAL.HDR.OBSTYPES.CONTINUATION")

    def test_time_of_first_and_last_obs(self):
        lines = replace_label_content(v3_obs(), "TIME OF FIRST OBS", tfirst(2026, 10, 30, 0, 0, 0.0000001))
        self.check(lines, "VAL.HDR.TIME-OF-FIRST-OBS")
        lines = replace_label_content(v3_obs(), "TIME OF LAST OBS", tfirst(2026, 10, 30, 0, 1, 30.0))
        self.check(lines, "VAL.HDR.TIME-OF-LAST-OBS")

    def test_time_system(self):
        lines = replace_label_content(v3_obs(), "TIME OF FIRST OBS", tfirst(2026, 10, 30, 0, 0, 0.0, "XYZ"))
        self.check(lines, "VAL.HDR.TIME-SYSTEM", WARNING)

    def test_number_of_satellites(self):
        self.check(replace_label_content(v3_obs(), "# OF SATELLITES", "     5"), "VAL.HDR.NUM-SATELLITES")
        self.check(replace_label_content(v2_obs(), "# OF SATELLITES", "    12"), "VAL.HDR.NUM-SATELLITES")

    def test_prn_obs_counts(self):
        lines = v3_obs()
        k = index_of(lines, lambda x: x.startswith("   R01"))
        lines[k] = hdr("   R01" + "".join(f"{v:6d}" for v in (3, 3, 2, 3)), "PRN / # OF OBS")
        f = self.check(lines, "VAL.HDR.PRN-NUM-OBS")
        self.assertTrue(any("R01 D1C" in x.message for x in f))
        # a satellite missing from the list
        lines = v3_obs()
        del lines[index_of(lines, lambda x: x.startswith("   R02"))]
        self.check(lines, "VAL.HDR.PRN-NUM-OBS")
        # RINEX 2 (one line per satellite, I2 satellite number)
        lines = v2_obs()
        k = index_of(lines, lambda x: x.startswith("   G 5"))
        lines[k] = hdr("   G 5" + "".join(f"{v:6d}" for v in (1, 1, 1, 1, 1, 1, 0)), "PRN / # OF OBS")
        self.check(lines, "VAL.HDR.PRN-NUM-OBS")

    def test_prn_obs_counts_ignore_zero_values(self):
        # "0.000" is a missing observation (rinex305.txt sec. 6.7): not counted
        lines = v3_obs()
        k = index_of(lines, lambda x: x.startswith("R01"))
        rec = lines[k]
        lines[k] = rec[:3 + 32] + f14(0.0) + rec[3 + 48:]           # D1C of R01, epoch 0
        f = self.check(lines, "VAL.HDR.PRN-NUM-OBS")
        self.assertTrue(any("R01 D1C: header says 3, the data hold 2" in x.message for x in f), f)
        # and with the header count corrected it is clean
        p = index_of(lines, lambda x: x.startswith("   R01"))
        lines[p] = hdr("   R01" + "".join(f"{v:6d}" for v in (3, 3, 2, 3)), "PRN / # OF OBS")
        self.assertEqual(errors(validate(payload(lines))), [])

    def test_prn_obs_counts_random(self):
        """The batched counter agrees with a plain count (value not blank, not all zeros)."""
        rng = random.Random(7)
        choices = [None, 0.0, -0.0, 0.001, -0.001, 1.0, 123456789.123, -5.5, 100.0, 0.25]
        for v2 in (False, True):
            for trial in range(3):
                sats = ["G01", "G02", "G03"]
                types = V2_TYPES if v2 else G_TYPES
                vals = {s: [[rng.choice(choices) for _ in types] for _ in range(1100)] for s in sats}
                count = {s: [sum(1 for e in vals[s] if e[k] is not None and e[k] != 0.0)
                             for k in range(len(types))] for s in sats}
                lines = self.random_file(v2, types, sats, vals, count)
                f = validate(payload(lines))
                self.assertEqual(errors(f), [], (v2, trial, f[:5]))

    def random_file(self, v2, types, sats, vals, count):
        n = len(next(iter(vals.values())))
        def t(k):
            return (2026, 10, 30, k // 120, (k // 2) % 60, 30.0 * (k % 2))
        if v2:
            h = v2_obs("2.11", with_counts=False)
            h = h[:label_index(h, "INTERVAL")]
            h = [x if x[60:].strip() != "RINEX VERSION / TYPE" else
                 hdr("     2.11           OBSERVATION DATA    G", "RINEX VERSION / TYPE") for x in h]
        else:
            h = v3_obs("3.05", "G", ("G",))
            h = h[:label_index(h, "INTERVAL")]
        h += [hdr(tfirst(*t(0)), "TIME OF FIRST OBS"), hdr(tfirst(*t(n - 1)), "TIME OF LAST OBS"),
              hdr(f"{len(sats):6d}", "# OF SATELLITES")]
        for s in sats:
            c = count[s]
            for k in range(0, len(c), 9):
                head = (f"   {s[0]}{int(s[1:]):2d}" if v2 else f"   {s}") if k == 0 else " " * 6
                h.append(hdr(head + "".join(f"{x:6d}" for x in c[k:k + 9]), "PRN / # OF OBS"))
        h.append(hdr("", "END OF HEADER"))
        body = []
        for e in range(n):
            if v2:
                body += v2_epoch_line(*t(e), 0, sats)
                for s in sats:
                    fields = [f14(x) for x in vals[s][e]]
                    body += ["".join(fields[i:i + 5]).rstrip() for i in range(0, len(fields), 5)]
            else:
                body.append(v3_epoch_line(*t(e), 0, len(sats)))
                body += [(s + "".join(f14(x) for x in vals[s][e])).rstrip() for s in sats]
        return h + body

    def test_system_letter_mismatch(self):
        lines = v3_obs()
        lines[0] = hdr("     3.05           OBSERVATION DATA    G", "RINEX VERSION / TYPE")
        self.check(lines, "VAL.HDR.SYSTEM.MISMATCH")

    def test_clock_without_rcv_clock_offs_appl(self):
        lines = drop_label(v4_obs(), "RCV CLOCK OFFS APPL")
        self.check(lines, "VAL.HDR.CONDITIONAL", WARNING)

    def test_v4_pgm_must_be_second_line(self):
        lines = v3_obs("4.02")
        lines.insert(1, hdr("A COMMENT", "COMMENT"))
        self.check(lines, "VAL.HDR.ORDER")
        lines = v3_obs("3.05")                     # RINEX 3 is not checked (see validate.py)
        lines.insert(1, hdr("A COMMENT", "COMMENT"))
        self.assertFalse(has(validate(payload(lines)), "VAL.HDR.ORDER"))

    def test_v4_deprecated_phase_shift(self):
        lines = v3_obs("4.00")
        lines.insert(label_index(lines, "INTERVAL"), hdr("G L1C", "SYS / PHASE SHIFT"))
        self.check(lines, "VAL.HDR.DEPRECATED", WARNING)

    def test_glonass_slot_coverage(self):
        lines = replace_label_content(v3_obs(), "GLONASS SLOT / FRQ #", "  1 R01  1")
        self.check(lines, "VAL.HDR.GLONASS-SLOTS", WARNING)

    def test_numeric_header_field(self):
        lines = replace_label_content(v3_obs(), "INTERVAL", "    30.0x0")
        self.check(lines, "VAL.HDR.NUMBER")

    def test_repeated_record(self):
        lines = v3_obs()
        lines.insert(3, hdr("TEST2", "MARKER NAME"))
        self.check(lines, "VAL.HDR.REPEATED", WARNING)


class ObsDataChecks(unittest.TestCase):
    def check(self, lines, rule, severity=ERROR):
        f = validate(payload(lines))
        self.assertTrue(has(f, rule, severity), f)
        return f

    def epoch_index(self, lines, n=0):
        return [i for i, x in enumerate(lines) if x.startswith("> ")][n]

    def test_epoch_flag(self):
        lines = v3_obs()
        k = self.epoch_index(lines)
        lines[k] = lines[k][:31] + "7" + lines[k][32:]
        self.check(lines, "VAL.OBS.EPOCH.FLAG")

    def test_fewer_records_than_declared(self):
        lines = v3_obs()
        k = self.epoch_index(lines)
        lines[k] = lines[k][:32] + "  5"
        self.check(lines, "VAL.OBS.EPOCH.NSAT")

    def test_more_records_than_declared(self):
        lines = v3_obs()
        k = self.epoch_index(lines)
        lines[k] = lines[k][:32] + "  3"
        self.check(lines, "VAL.OBS.EPOCH.START")

    def test_epoch_order(self):
        lines = v3_obs()
        k = self.epoch_index(lines, 1)
        lines[k] = v3_epoch_line(2026, 10, 29, 0, 0, 30.0, 0, 4)
        self.check(lines, "VAL.OBS.EPOCH.ORDER", WARNING)

    def test_epoch_time_out_of_range(self):
        lines = v3_obs()
        k = self.epoch_index(lines, 1)
        lines[k] = v3_epoch_line(2026, 10, 30, 24, 0, 30.0, 0, 4)
        self.check(lines, "VAL.OBS.EPOCH.TIME")

    def test_epoch_pad_and_syntax(self):
        lines = v3_obs()
        k = self.epoch_index(lines, 1)
        lines[k] = lines[k][:7] + " " + lines[k][8:]          # month '10' -> ' 0'... use 6
        lines[k] = "> 2026  6 30 00 00 30.0000000  0  4"
        self.check(lines, "VAL.OBS.EPOCH.PAD", WARNING)
        lines[k] = "> 2026 06 30 00 00 30.00000x0  0  4"
        self.check(lines, "VAL.OBS.EPOCH.SYNTAX")
        lines[k] = "> 2026 10 30 00 00 30.0000000  0  4 X"           # reserved 6X
        self.check(lines, "VAL.OBS.EPOCH.SYNTAX")

    def test_picoseconds(self):
        lines = v4_obs("4.02")
        k = self.epoch_index(lines)
        lines[k] = lines[k][:56] + " 1234x"
        self.check(lines, "VAL.OBS.EPOCH.PICOSECONDS")
        lines = v4_obs("4.01")                    # no picosecond field before 4.02
        self.check(lines, "VAL.OBS.EPOCH.PICOSECONDS")

    def test_bad_field(self):
        lines = v3_obs()
        k = self.epoch_index(lines) + 1
        lines[k] = lines[k][:3] + "  2000x000.123" + lines[k][17:]
        self.check(lines, "VAL.OBS.DATA.FIELD")

    def test_field_format_warning(self):
        lines = v3_obs()
        k = self.epoch_index(lines) + 1
        lines[k] = lines[k][:3] + "    20001000.1" + lines[k][17:]        # one decimal, not F14.3
        f = self.check(lines, "VAL.OBS.DATA.FORMAT", WARNING)
        self.assertFalse(has(f, "VAL.OBS.DATA.FIELD"))

    def test_lli_out_of_range(self):
        lines = v3_obs()
        k = self.epoch_index(lines) + 1
        lines[k] = lines[k][:17] + "9" + lines[k][18:]
        self.check(lines, "VAL.OBS.DATA.LLI", WARNING)

    def test_too_many_fields(self):
        lines = v3_obs()
        k = self.epoch_index(lines) + 3                     # R01, 4 types
        lines[k] = lines[k] + f14(1.0)
        self.check(lines, "VAL.OBS.DATA.EXTRA")
        lines = v2_obs()                                    # RINEX 2: 2 fields on the 2nd line
        k = index_of(lines, lambda x: x.startswith(" 26 10 30  0  0  0.0000000")) + 2
        lines[k] = lines[k] + f14(1.0)
        self.check(lines, "VAL.OBS.DATA.EXTRA")

    def test_system_without_types(self):
        lines = v3_obs()
        k = self.epoch_index(lines) + 1
        lines[k] = "E" + lines[k][1:]
        self.check(lines, "VAL.OBS.DATA.SYSTEM")

    def test_duplicate_satellite(self):
        lines = v3_obs()
        k = self.epoch_index(lines) + 2
        lines[k] = "G01" + lines[k][3:]
        self.check(lines, "VAL.OBS.DATA.DUPLICATE-SAT")

    def test_truncated(self):
        lines = v3_obs()
        self.check(lines[:-1], "VAL.OBS.TRUNCATED")
        lines = v2_obs()
        self.check(lines[:-1], "VAL.OBS.TRUNCATED")

    def test_v2_satellite_list(self):
        lines = v2_obs()
        k = index_of(lines, lambda x: x.startswith(" 26 10 30  0  0 30.0000000"))
        lines[k + 1] = "X" + lines[k + 1][1:]          # continuation line must start with 32X
        self.check(lines, "VAL.OBS.EPOCH.SATLIST")
        lines = v2_obs()
        k = index_of(lines, lambda x: x.startswith(" 26 10 30  0  0  0.0000000"))
        lines[k] = lines[k] + "G05"                    # 3 declared, 4 listed
        self.check(lines, "VAL.OBS.EPOCH.SATLIST")

    def test_v2_blank_system_identifier(self):
        lines = v2_obs()
        k = index_of(lines, lambda x: x.startswith(" 26 10 30  0  0  0.0000000"))
        lines[k] = lines[k].replace("G 1", "  1", 1)
        self.check(lines, "VAL.OBS.DATA.SATID", WARNING)

    def test_event_count(self):
        lines = v2_obs()
        k = index_of(lines, lambda x: x.startswith(" 26 10 30  0  0 15.0000000  5"))
        lines[k] = lines[k][:29] + "  2"               # announces 2, 1 follows
        self.check(lines, "VAL.OBS.EVENT.COUNT")
        lines = v2_obs()
        lines.insert(k + 2, hdr("ANOTHER", "COMMENT"))  # announces 1, 2 follow
        self.check(lines, "VAL.OBS.EVENT.COUNT")

    def test_event_record_without_label(self):
        lines = v2_obs()
        k = index_of(lines, lambda x: x.startswith(" 26 10 30  0  0 15.0000000  5"))
        lines[k + 1] = "EXTERNAL EVENT"
        self.check(lines, "VAL.OBS.EVENT.RECORD")

    def test_new_site_without_marker_name(self):
        lines = v2_obs()
        k = index_of(lines, lambda x: x.startswith(" 26 10 30  0  0 15.0000000  5"))
        lines[k] = lines[k][:28] + "3" + lines[k][29:]
        self.check(lines, "VAL.OBS.EVENT.MARKER")

    def test_event_redefines_types(self):
        # flag 4 with a new SYS / # / OBS TYPES for R: later R records use 2 types
        lines = v3_obs()
        k = self.epoch_index(lines, 2)
        new = sys_types("R", ["C1C", "L1C"])
        lines[k:k] = [v3_epoch_line(2026, 10, 30, 0, 0, 45.0, 4, len(new))] + new
        for i in range(k + 1 + len(new), len(lines)):
            if lines[i].startswith("R0"):
                lines[i] = lines[i][:3 + 32]
        f = validate(payload(lines))
        self.assertFalse(has(f, "VAL.OBS.DATA.EXTRA"), f)
        # the old (4-type) records after the event would now have too many fields
        lines2 = v3_obs()
        lines2[k:k] = [v3_epoch_line(2026, 10, 30, 0, 0, 45.0, 4, len(new))] + new
        self.assertTrue(has(validate(payload(lines2)), "VAL.OBS.DATA.EXTRA"))

    def test_blank_line_between_epochs(self):
        lines = v3_obs()
        lines.insert(self.epoch_index(lines, 1), "")
        self.check(lines, "VAL.OBS.BLANK-LINE", WARNING)


class NavChecks(unittest.TestCase):
    def check(self, lines, rule, severity=ERROR):
        f = validate(payload(lines))
        self.assertTrue(has(f, rule, severity), f)
        return f

    def test_v2_record_lines(self):
        lines = nav_v2_gps()
        del lines[first_data(lines) + 7]                # first record: 7 lines instead of 8
        self.check(lines, "VAL.NAV.RECORD.LINES")
        lines = nav_v2_glonass()
        lines.append("   " + d19(1.0) * 4)               # 5 lines instead of 4
        self.check(lines, "VAL.NAV.RECORD.LINES")

    def test_v3_glonass_lines_by_version(self):
        self.check(nav_v3("3.05", glo_lines=4), "VAL.NAV.RECORD.LINES")
        self.check(nav_v3("3.04", glo_lines=5), "VAL.NAV.RECORD.LINES")

    def test_numbers(self):
        lines = nav_v3()
        k = first_data(lines) + 1
        lines[k] = lines[k][:4] + "    0.5000000x0E+00" + lines[k][23:]
        self.check(lines, "VAL.NAV.NUMBER")
        lines[k] = lines[k][:4] + "   0.50000000000E+0" + lines[k][23:]
        self.check(lines, "VAL.NAV.NUMBER.EXPONENT")
        lines[k] = lines[k][:4] + "                0.5" + lines[k][23:]
        self.check(lines, "VAL.NAV.NUMBER.FORMAT", WARNING)

    def test_layout(self):
        lines = nav_v3()
        k = first_data(lines) + 1
        lines[k] = lines[k] + "  X"
        self.check(lines, "VAL.NAV.LAYOUT")
        lines = nav_v3()
        lines[k] = "1" + lines[k][1:]                   # neither 'A1,I2.2' nor '4X'
        self.check(lines, "VAL.NAV.RECORD.START")

    def test_v3_epoch_pad(self):
        lines = nav_v3()
        k = first_data(lines)
        lines[k] = "G 1" + lines[k][3:]
        self.check(lines, "VAL.NAV.EPOCH.PAD", WARNING)

    def test_header_numbers(self):
        lines = nav_v3()
        k = label_index(lines, "TIME SYSTEM CORR")
        lines[k] = hdr("GPUT    " + f"{1.3e-7:17.10E}{1.1e-13:16.9E}{552960:7d}{2391:2d}", "TIME SYSTEM CORR")
        self.check(lines, "VAL.HDR.NUMBER")

    def test_system_letter(self):
        lines = nav_v3()
        lines[0] = hdr("     3.05           N: GNSS NAV DATA    G: GPS", "RINEX VERSION / TYPE")
        self.check(lines, "VAL.HDR.SYSTEM.MISMATCH")

    def test_v3_label_of_v4(self):
        lines = nav_v3()
        lines.insert(2, hdr("        2", "MERGED FILE"))
        self.check(lines, "VAL.HDR.LABEL.VERSION", WARNING)

    def test_v4_leap_seconds_mandatory(self):
        self.check(drop_label(nav_v4(), "LEAP SECONDS"), "VAL.HDR.MANDATORY")

    def test_v4_record_lines(self):
        lines = nav_v4()
        k = index_of(lines, lambda x: x.startswith("> EPH R01"))
        del lines[k + 5]                                  # FDMA: 4 lines instead of 5
        self.check(lines, "VAL.NAV.RECORD.LINES")
        lines = nav_v4()
        k = index_of(lines, lambda x: x.startswith("> EOP"))
        del lines[k + 2]
        self.check(lines, "VAL.NAV.RECORD.LINES")
        # a GPS CNV2 record with 9 lines (rinex_4.01.txt Table A12, erratum E-13)
        lines = nav_v4()
        lines += ["> EPH G04 CNV2"] + nav_v3_record("G04", (2026, 10, 30, 0, 0, 0), 9)
        self.check(lines, "VAL.NAV.RECORD.LINES")

    def test_v4_record_types(self):
        lines = nav_v4()
        lines += ["> EPH G04 XNAV"] + nav_v3_record("G04", (2026, 10, 30, 0, 0, 0), 8)
        self.check(lines, "VAL.NAV.RECORD.TYPE")
        lines = nav_v4("4.01")                           # L1NV is 4.02 only
        lines += ["> EPH I01 L1NV"] + nav_v3_record("I01", (2026, 10, 30, 0, 0, 0), 9)
        self.check(lines, "VAL.NAV.RECORD.TYPE")

    def test_v4_ion_subtype(self):
        lines = nav_v4("4.02")
        k = index_of(lines, lambda x: x.startswith("> ION J01 CNVX"))
        lines[k] = "> ION J01 CNVX"
        self.check(lines, "VAL.NAV.RECORD.TYPE")
        lines = nav_v4("4.01")                           # no subtypes before 4.02
        lines += ["> ION J01 CNVX", "    2026 10 30 00 00 00" + d19(1e-8, "E") * 3,
                  "    " + d19(1.0, "E") * 4, "    " + d19(1.0, "E")]
        self.assertEqual(errors(validate(payload(lines))), [])

    def test_v4_record_head(self):
        lines = nav_v4()
        k = index_of(lines, lambda x: x.startswith("> EPH G01"))
        lines[k] = ">EPH G01 LNAV"
        self.check(lines, "VAL.NAV.RECORD.HEAD")

    def test_v4_exponent_letters(self):
        lines = nav_v4("4.02")
        k = index_of(lines, lambda x: x.startswith("> EPH R01")) + 1
        lines[k] = lines[k].replace("E", "D")
        self.check(lines, "VAL.NAV.EXPONENT.MIXED")
        self.check(lines, "VAL.NAV.EXPONENT.DEPRECATED", WARNING)


class MetChecks(unittest.TestCase):
    def check(self, lines, rule, severity=ERROR):
        f = validate(payload(lines))
        self.assertTrue(has(f, rule, severity), f)
        return f

    def test_type_count_and_code(self):
        self.check(replace_label_content(met(), "# / TYPES OF OBSERV", "     4    PR    TD    HR"),
                   "VAL.MET.TYPES.COUNT")
        self.check(met("2.10", ("PR", "TD", "WS")), "VAL.MET.TYPES.CODE", WARNING)   # WS from 2.11

    def test_epoch_layout(self):
        lines = met("3.05")
        k = first_data(lines)
        lines[k] = " 26" + lines[k][5:]
        self.check(lines, "VAL.MET.EPOCH.LAYOUT")
        lines = met("2.11")
        k = first_data(lines)
        lines[k] = " 2026" + lines[k][3:]
        self.check(lines, "VAL.MET.EPOCH.LAYOUT")

    def test_value(self):
        lines = met("3.05")
        k = first_data(lines)
        lines[k] = lines[k][:20] + "  9x0.0" + lines[k][27:]
        self.check(lines, "VAL.MET.VALUE")
        lines[k] = lines[k][:20] + " 900.00" + lines[k][27:]      # 2 decimals: not F7.1
        self.check(lines, "VAL.MET.VALUE.FORMAT", WARNING)

    def test_continuation(self):
        lines = met("3.05", MET10)
        del lines[first_data(lines) + 1]
        self.check(lines, "VAL.MET.CONTINUATION")
        lines = met("3.05")
        k = first_data(lines)
        lines[k] = lines[k] + "    1.0"
        self.check(lines, "VAL.MET.CONTINUATION")

    def test_order(self):
        lines = met("3.05")
        k = first_data(lines)
        lines[k], lines[k + 1] = lines[k + 1], lines[k]
        self.check(lines, "VAL.MET.EPOCH.ORDER", WARNING)

    def test_sensor_records(self):
        self.check(drop_label(met(), "SENSOR POS XYZ/H"), "VAL.MET.SENSOR")
        self.check(drop_label(met(), "SENSOR MOD/TYPE/ACC"), "VAL.HDR.MANDATORY")


class ConverterOutput(unittest.TestCase):
    """Clause 2: what the converter writes must validate (a sample, not the matrix)."""

    def convert_and_validate(self, sources, targets):
        import tempfile
        from rinexconv.engine import Options, convert_data
        with tempfile.TemporaryDirectory() as tmp:
            fcn = Path(tmp) / "glo_fcn.txt"
            fcn.write_bytes(b"R01 1\nR02 -4\nR03 5\n")         # test-only channels
            for name, lines in sources.items():
                for target in targets:
                    with self.subTest(name=name, target=target):
                        outs = convert_data(payload(lines), name + ".rnx",
                                            Options(target, glo_fcn=str(fcn), compression="none",
                                                    assume_phase_aligned=True))
                        for o in outs:
                            f = validate(o.data)
                            self.assertEqual(errors(f), [], (o.name, f))

    def test_samples_convert_to_valid_files(self):
        self.convert_and_validate({"obs211": v2_obs(), "obs305": v3_obs(), "met211": met()},
                                  ("2.11", "3.05", "4.02"))
        self.convert_and_validate({"nav305": nav_v3()}, ("2.11", "3.05"))

    def test_nav_ionospheric_corr_without_beta_to_402(self):
        # Converter finding: a 3.05 IONOSPHERIC CORR GPSA line without GPSB becomes a
        # '> ION G   LNAV' record whose last line (beta3, 4X,E19.12) is written empty, so the
        # record reads as 2 lines where rinex_4.02.txt Table A35 defines 3 (our own reader
        # also stops the record at the blank line). The STO record's t_tm is written
        # '552960.0' (no exponent, not E19.12).
        self.convert_and_validate({"nav305": nav_v3()}, ("4.02",))


# ---------------------------------------------------------------------------
# spec examples: run every one and print what the validator says (PLAN §1 clause 5d)
# ---------------------------------------------------------------------------
# Errata the validator must see (tests/fixtures/spec_errata.md section a).
ERRATA_RULES = {
    "2.10/a7_obs_mixed.rnx": "VAL.OBS.TRUNCATED",           # E-01: 4 records announced, 3 follow
    "2.11/a18_nav_geo.rnx": "VAL.HDR.NUMBER",               # E-02: D-UTC one column left
    "2.11/a17_obs_gps_geo.rnx": "VAL.HDR.TIME-OF-LAST-OBS", # E-15
    "3.05/a4_obs_example1.rnx": "VAL.HDR.NUMBER",           # E-10: TIME OF FIRST OBS 2 columns left
    "4.02/a4_obs_example1.rnx": "VAL.HDR.NUMBER",           # E-10
    "4.02/a5_obs_example2.rnx": "VAL.OBS.TRUNCATED",        # E-09: 42 announced, 21 printed
    "4.01/a12_nav_gps.rnx": "VAL.NAV.RECORD.LINES",         # E-13: CNV2 record with 9 lines
    "3.04/a4_obs_example2.rnx": "VAL.OBS.TRUNCATED",        # E-08: epoch without satellites
}


class SpecExamples(unittest.TestCase):
    def test_report_findings(self):
        if not FIXTURES.is_dir():
            self.skipTest("no spec-example fixtures")
        lines = []
        for p in sorted(FIXTURES.rglob("*.rnx")):
            rel = p.relative_to(FIXTURES).as_posix()
            try:
                f = validate(p.read_bytes())
            except CorruptError as e:
                lines.append(f"{rel}: unreadable ({e})")
                continue
            r = rules(f)
            if r:
                lines.append(f"{rel}: " + ", ".join(f"{k}x{n}" for k, n in sorted(r.items())))
            if rel in ERRATA_RULES:
                self.assertIn(ERRATA_RULES[rel], r, rel)
        print("\nvalidator findings on the spec examples:\n  " + "\n  ".join(lines))


# ---------------------------------------------------------------------------
# corpus smoke test
# ---------------------------------------------------------------------------
# The smallest real file of each of these corpus folders (data/corpus, kept as served).
SMOKE = [
    "obs/v2.11/", "obs/v2.10/", "obs/v3.02/", "obs/v3.04/", "obs/v3.05/", "obs/v4.01/", "obs/v4.02/",
    "nav/v2.11/", "nav/v3.04/", "nav/v3.05/", "nav/v4.01/", "nav/v4.02/",
    "met/v2.11/", "met/v3.04/", "met/v4.00/",
]
# Real files that violate their own spec, judged against the spec text (docs/DECISIONS.md
# "Validator"): path -> {rule: citation}. Our reader accepts all of them (corpus run of
# 2026-10-30); the validator must report exactly these non-repairable error rules.
KNOWN_VIOLATIONS = {
    "met/v2.10/kit31800.15m.Z": {
        "VAL.MET.SENSOR": "PR observed, no SENSOR POS XYZ/H: 'Record required for barometer' "
                          "(rinex210.txt Table A5 l.1217)"},
    "met/v2.10/lpgs1800.03m.Z": {
        "VAL.HDR.MANDATORY": "no SENSOR MOD/TYPE/ACC, an unstarred record (rinex210.txt Table A5)",
        "VAL.MET.SENSOR": "PR observed, no SENSOR POS XYZ/H (rinex210.txt Table A5 l.1217)"},
    "met/v3.04/GOPE00CZE_R_20201800000_01D_MM.rnx.gz": {
        "VAL.HDR.NUMBER": "SENSOR POS XYZ/H X written '3979315.365' + two UTF-8 bytes, so the "
                          "3F14.4 fields and the label shift (rinex304.txt Table A20 p.95)"},
    "met/v3.05/BAUT00DEU_R_20262740000_01D_10S_MM.rnx.gz": {
        "VAL.HDR.MANDATORY": "no PGM / RUN BY / DATE; line 2 is a gfzrnx COMMENT (rinex305.txt "
                             "Table A20 p.86)"},
    "nav/v4.02/ES1300DEU_R_20262740000_01D_MN.rnx.gz": {
        "VAL.NAV.FIELDS": "the 4.01 Region code (0.0) after Beta3 on ION MESSAGE LINE - 2 of 15 GPS LNAV / "
                          "BDS D1D2 records; 4.02 defines Beta3 only there, 4X,E19.12 (rinex_4.02.txt "
                          "Table A35 p.117; 4.00/4.01: 4X,2E19.12, rinex_4.01.txt l.6189 p.108)"},
    "nav/v3.02/BOR100POL_R_20262740000_01D_CN.rnx.gz": {
        "VAL.HDR.NUMBER": "TIME SYSTEM CORR values 3 columns right of A4,1X,D17.10,D16.9,I7,I5 "
                          "(rinex302.txt Table A5 p.62-63)",
        "VAL.HDR.SEPARATOR": "the same shift puts digits in the 1X separators around the A5 "
                             "satellite field (rinex302.txt Table A5 p.62-63)"},
    "obs/v3.03/ARUC00ARM_R_20171800000_01D_30S_MO.crx.gz": {
        "VAL.HDR.NUMBER": "APPROX POSITION XYZ and ANTENNA: DELTA H/E/N in 13-column fields, not "
                          "3F14.4 (rinex303_update1.txt Table A2 p.55)"},
    "obs/v3.02/DAEJ00KOR_R_20171800000_01D_30S_MO.crx.gz": {
        "VAL.HDR.MANDATORY": "GLONASS data without GLONASS SLOT / FRQ # (rinex302.txt Table A2 "
                             "p.56, unstarred; sec. 9.5 p.43 still says optional: "
                             "docs/SPEC_TABLES.md item 6)"},
    "obs/v3.01/WUHN00CHN_R_20201800000_01D_30S_MO.crx.gz": {
        "VAL.HDR.SYSTEM.MISMATCH": "RINEX VERSION / TYPE 'G (GPS)' but BDS and GLONASS data "
                                   "(rinex301.txt Table A1 p.29: M for mixed files)"},
}


class CorpusSmoke(unittest.TestCase):
    """Repairable header findings (PLAN §1 clause 9: TIME OF FIRST/LAST OBS, # OF SATELLITES,
    PRN / # OF OBS) are printed, not asserted: real files get them wrong constantly and the
    converter repairs them by default."""

    def run_file(self, p):
        from rinexconv.engine import load_bytes
        from rinexcore.rinexfile import open_container
        data = p.read_bytes()
        try:
            load_bytes(data)
        except Exception:
            return None                # only files our own reader accepts
        return validate(open_container(data).payload)

    def test_no_errors_on_files_the_reader_accepts(self):
        if not CORPUS.is_dir():
            self.skipTest("data/corpus is missing")
        checked = 0
        repaired = []
        for prefix in SMOKE:
            d = CORPUS / prefix
            if not d.is_dir():
                continue
            files = sorted((p for p in d.iterdir() if p.is_file()), key=lambda p: p.stat().st_size)[:1]
            for p in files:
                rel = p.relative_to(CORPUS).as_posix()
                f = self.run_file(p)
                if f is None:
                    continue
                # (a known violation is asserted exactly by test_known_violations_are_reported)
                bad = [x for x in errors(f) if not x.repairable and x.rule not in KNOWN_VIOLATIONS.get(rel, {})]
                repaired += [f"{rel}: {x.rule}" for x in errors(f) if x.repairable]
                with self.subTest(rel):
                    self.assertEqual(bad, [], rel)
                checked += 1
        self.assertGreater(checked, 0)
        if repaired:
            print("\nrepairable header findings:\n  " + "\n  ".join(repaired))

    def test_known_violations_are_reported(self):
        if not CORPUS.is_dir():
            self.skipTest("data/corpus is missing")
        for rel, want in KNOWN_VIOLATIONS.items():
            p = CORPUS / rel
            if not p.is_file():
                continue
            with self.subTest(rel):
                f = self.run_file(p)
                self.assertIsNotNone(f, f"our reader no longer accepts {rel}")
                got = {x.rule for x in errors(f) if not x.repairable}
                self.assertEqual(got, set(want), rel)


if __name__ == "__main__":
    unittest.main()
