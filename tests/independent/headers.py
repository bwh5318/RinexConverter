"""Header, receiver-clock, epoch and event checks (PLAN §1 clauses 3 and 5a).

The token comparator (tokens.py / compare.py) compares observation values, ephemeris
records and met values. This module covers what those checks cannot see:

  obs  receiver clock offsets, the multiset of epochs (time, flag), special events
       (flags 2-5: count, times, COMMENT texts, the other records they carry) and every
       header record;
  nav  ionospheric and time-system corrections (RINEX 2/3 header records, RINEX 4
       '> ION' / '> STO' / '> EOP' records), LEAP SECONDS and the other header records;
  met  sensor records, marker records, comments and the observation-type list.

Every function returns a list of problems; an empty list means every difference between
input and output is claimed by the conversion report (losses, repairs, assumptions) and
every claimed loss really happened.

Deliberately independent: no import from rinexcore or rinexconv. The tables of which
header records each version defines were written from the header tables in
specs/text/*.txt (cited below), not from rinexcore/spec or rinexconv.
"""

import copy
import datetime
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# Which header records each version defines (written from the spec header tables)
# ---------------------------------------------------------------------------
# Observation files:
#   2.10 Table A1 (rinex210.txt line 813), 2.11 Table A1 (rinex211.txt line 1068): the same
#        set of labels in both.
#   3.00 Table A1 (rinex300.txt line 1634, p.26): drops WAVELENGTH FACT L1/2 and
#        # / TYPES OF OBSERV, adds MARKER TYPE ... SYS / SCALE FACTOR (below).
#   3.01 Table A1 (rinex301.txt line 1830, p.29-33): adds SYS / PHASE SHIFTS (plural) and
#        GLONASS SLOT / FRQ # (optional, p.32-33).
#   3.02 Table A2 (rinex302.txt line 2639, p.51-56): SYS / PHASE SHIFT (singular) and adds
#        GLONASS COD/PHS/BIS. 3.03 (rinex303.txt line 2722, p.54), 3.04 (rinex304.txt
#        line 3015, p.59) and 3.05 (rinex305.txt line 2803, p.52): the same set as 3.02.
#   4.00 Table A2 (rinex_4.00.txt line 2855, p.54), 4.01 (rinex_4.01.txt line 3136, p.58),
#        4.02 (rinex_4.02.txt line 3222, p.60): add DOI, LICENSE OF USE, STATION
#        INFORMATION; SYS / PHASE SHIFT and GLONASS COD/PHS/BIS are still defined but
#        "strongly deprecated" (4.02 p.63: "should be ignored by RINEX decoders and encoders").
_OBS_V2 = {"RINEX VERSION / TYPE", "PGM / RUN BY / DATE", "COMMENT", "MARKER NAME", "MARKER NUMBER",
           "OBSERVER / AGENCY", "REC # / TYPE / VERS", "ANT # / TYPE", "APPROX POSITION XYZ",
           "ANTENNA: DELTA H/E/N", "WAVELENGTH FACT L1/2", "# / TYPES OF OBSERV", "INTERVAL",
           "TIME OF FIRST OBS", "TIME OF LAST OBS", "RCV CLOCK OFFS APPL", "LEAP SECONDS",
           "# OF SATELLITES", "PRN / # OF OBS", "END OF HEADER"}
_OBS_300 = (_OBS_V2 - {"WAVELENGTH FACT L1/2", "# / TYPES OF OBSERV"}) | {
    "MARKER TYPE", "ANTENNA: DELTA X/Y/Z", "ANTENNA: PHASECENTER", "ANTENNA: B.SIGHT XYZ",
    "ANTENNA: ZERODIR AZI", "ANTENNA: ZERODIR XYZ", "CENTER OF MASS: XYZ", "SYS / # / OBS TYPES",
    "SIGNAL STRENGTH UNIT", "SYS / DCBS APPLIED", "SYS / PCVS APPLIED", "SYS / SCALE FACTOR"}
_OBS_301 = _OBS_300 | {"SYS / PHASE SHIFTS", "GLONASS SLOT / FRQ #"}
_OBS_302 = _OBS_300 | {"SYS / PHASE SHIFT", "GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS"}
_OBS_4 = _OBS_302 | {"DOI", "LICENSE OF USE", "STATION INFORMATION"}
OBS_LABELS = {"2.10": _OBS_V2, "2.11": _OBS_V2, "3.00": _OBS_300, "3.01": _OBS_301, "3.02": _OBS_302,
              "3.03": _OBS_302, "3.04": _OBS_302, "3.05": _OBS_302, "4.00": _OBS_4, "4.01": _OBS_4,
              "4.02": _OBS_4}
ALL_OBS_LABELS = set().union(*OBS_LABELS.values())

# Records the converter writes itself (from the data, from companions, or as the target's
# own form); only their checkable content is checked (see _obs_regenerated).
OBS_REGEN = {"RINEX VERSION / TYPE", "PGM / RUN BY / DATE", "# / TYPES OF OBSERV", "SYS / # / OBS TYPES",
             "TIME OF FIRST OBS", "TIME OF LAST OBS", "# OF SATELLITES", "PRN / # OF OBS", "INTERVAL",
             "SYS / PHASE SHIFT", "GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS", "LEAP SECONDS",
             "SYS / SCALE FACTOR", "WAVELENGTH FACT L1/2", "ANTENNA: PHASECENTER"}

# Navigation files:
#   2.10/2.11 GPS (Table A3: rinex210.txt line 1049, rinex211.txt line 1320): ION ALPHA,
#        ION BETA, DELTA-UTC: A0,A1,T,W, LEAP SECONDS. GLONASS (Table A10: rinex211.txt
#        line 1675): CORR TO SYSTEM TIME, LEAP SECONDS. GEO (Table A15): 2.10 (rinex210.txt
#        line 1615) CORR TO SYSTEM TIME; 2.11 (rinex211.txt line 1894) adds
#        D-UTC A0,A1,T,W,S,U ("Replaces CORR TO SYSTEM TIME").
#   3.00-3.05 (rinex300.txt line 2116 p.32 ... rinex305.txt Table A5 line 3606 p.65-68):
#        IONOSPHERIC CORR, TIME SYSTEM CORR, LEAP SECONDS.
#   4.00-4.02 (rinex_4.02.txt Table A7 line 4141 p.75-76): REC # / TYPE / VERS, MERGED FILE,
#        DOI, LICENSE OF USE, STATION INFORMATION, LEAP SECONDS; corrections are
#        '> STO' / '> ION' / '> EOP' records (Tables A33-A38, p.114-120).
_NAV_BASE = {"RINEX VERSION / TYPE", "PGM / RUN BY / DATE", "COMMENT", "LEAP SECONDS", "END OF HEADER"}
_NAV_V2 = _NAV_BASE | {"ION ALPHA", "ION BETA", "DELTA-UTC: A0,A1,T,W", "CORR TO SYSTEM TIME"}
_NAV_V3 = _NAV_BASE | {"IONOSPHERIC CORR", "TIME SYSTEM CORR"}
_NAV_V4 = _NAV_BASE | {"REC # / TYPE / VERS", "MERGED FILE", "DOI", "LICENSE OF USE", "STATION INFORMATION"}
NAV_LABELS = {"2.10": _NAV_V2, "2.11": _NAV_V2 | {"D-UTC A0,A1,T,W,S,U"}}
for _v in ("3.00", "3.01", "3.02", "3.03", "3.04", "3.05"):
    NAV_LABELS[_v] = _NAV_V3
for _v in ("4.00", "4.01", "4.02"):
    NAV_LABELS[_v] = _NAV_V4
ALL_NAV_LABELS = set().union(*NAV_LABELS.values())
NAV_CORR_LABELS = {"ION ALPHA", "ION BETA", "DELTA-UTC: A0,A1,T,W", "CORR TO SYSTEM TIME",
                   "D-UTC A0,A1,T,W,S,U", "IONOSPHERIC CORR", "TIME SYSTEM CORR"}

# Meteorological files: 2.10/2.11 Table A5 (rinex211.txt line 1426), 3.00-3.05 (rinex305.txt
# line 4882, p.86), 4.00-4.02 (rinex_4.02.txt line 7168, p.125: adds DOI, LICENSE OF USE,
# STATION INFORMATION).
_MET_V2 = {"RINEX VERSION / TYPE", "PGM / RUN BY / DATE", "COMMENT", "MARKER NAME", "MARKER NUMBER",
           "# / TYPES OF OBSERV", "SENSOR MOD/TYPE/ACC", "SENSOR POS XYZ/H", "END OF HEADER"}
MET_LABELS = {v: _MET_V2 for v in ("2.10", "2.11", "3.00", "3.01", "3.02", "3.03", "3.04", "3.05")}
for _v in ("4.00", "4.01", "4.02"):
    MET_LABELS[_v] = _MET_V2 | {"DOI", "LICENSE OF USE", "STATION INFORMATION"}
ALL_MET_LABELS = set().union(*MET_LABELS.values())

# Fixed-column text fields, compared field by field (stripped). Everything else is
# compared as whitespace tokens with numbers normalised (D/E, leading zeros, '.9' = '0.9').
#   rinex211.txt Table A1 / rinex305.txt Table A2: MARKER NAME A60, MARKER NUMBER A20,
#   MARKER TYPE A20, OBSERVER / AGENCY A20,A40, REC # / TYPE / VERS 3A20, ANT # / TYPE 2A20,
#   SIGNAL STRENGTH UNIT A20, SYS / DCBS|PCVS APPLIED A1,1X,A17,1X,A40;
#   rinex_4.02.txt: DOI, LICENSE OF USE, STATION INFORMATION A60;
#   rinex211.txt Table A5: SENSOR MOD/TYPE/ACC A20,A20,6X,F7.1,4X,A2,1X;
#   SENSOR POS XYZ/H 3F14.4,1F14.4,1X,A2,1X.
FIELDS = {
    "MARKER NAME": [(0, 60, "a")], "MARKER NUMBER": [(0, 20, "a")], "MARKER TYPE": [(0, 20, "a")],
    "OBSERVER / AGENCY": [(0, 20, "a"), (20, 60, "a")],
    "REC # / TYPE / VERS": [(0, 20, "a"), (20, 40, "a"), (40, 60, "a")],
    "ANT # / TYPE": [(0, 20, "a"), (20, 40, "a")], "SIGNAL STRENGTH UNIT": [(0, 20, "a")],
    "SYS / DCBS APPLIED": [(0, 1, "a"), (2, 19, "a"), (20, 60, "a")],
    "SYS / PCVS APPLIED": [(0, 1, "a"), (2, 19, "a"), (20, 60, "a")],
    "DOI": [(0, 60, "a")], "LICENSE OF USE": [(0, 60, "a")], "STATION INFORMATION": [(0, 60, "a")],
    "PGM / RUN BY / DATE": [(0, 20, "a"), (20, 40, "a"), (40, 60, "a")],
    "SENSOR MOD/TYPE/ACC": [(0, 20, "a"), (20, 40, "a"), (46, 53, "n"), (57, 59, "a")],
    "SENSOR POS XYZ/H": [(0, 14, "n"), (14, 28, "n"), (28, 42, "n"), (42, 56, "n"), (57, 59, "a")],
}

_NUMRE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][+-]?\d+)?$")
_Q7 = Decimal("1e-7")
_GPS0 = datetime.date(1980, 1, 6)
_BDS0 = datetime.date(2006, 1, 1)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _lines(payload):
    t = payload.decode("latin-1").replace("\r\n", "\n")
    out = t.split("\n")
    if out and out[-1] == "":
        out.pop()
    return out


def _vstr(first):
    return "%.2f" % float(first[:9])


def _header(lines):
    recs = []
    for i, l in enumerate(lines):
        lab = l[60:80].strip()
        if lab == "END OF HEADER":
            return recs, i
        if lab:
            recs.append((lab, l[:60].ljust(60), i + 1))
    raise ValueError("no END OF HEADER")


def _dec(s):
    s = s.strip()
    if not s or not _NUMRE.match(s):
        return None
    return Decimal(s.replace("D", "E").replace("d", "e"))


def _int(s):
    s = s.strip()
    return int(s) if s.lstrip("+-").isdigit() else None


def _ntok(t):
    return str(Decimal(t.replace("D", "E").replace("d", "e")).normalize()) if _NUMRE.match(t) else t


def norm(label, content):
    """Normalised content of a header record, for 'content survived' comparisons."""
    if label == "COMMENT":
        return content.rstrip()
    lay = FIELDS.get(label)
    c = content.ljust(60)
    if lay is None:
        return tuple(_ntok(x) for x in c.split())
    out = []
    for a, b, kind in lay:
        f = c[a:b]
        out.append(f.strip() if kind == "a" else tuple(_ntok(x) for x in f.split()))
    return tuple(out)


def _family(label):
    """'SYS / PHASE SHIFTS' (3.01 spelling) and 'SYS / PHASE SHIFT' are one record."""
    return "SYS / PHASE SHIFT" if label == "SYS / PHASE SHIFTS" else label


def _year(y):
    y = int(y)
    if y < 100:
        y += 1900 if y >= 80 else 2000
    return y


def _floor7(t):
    if t is None:
        return None
    return t[:5] + ((t[5] // _Q7 * _Q7).normalize(),)


def _sub7(t):
    return t is not None and (t[5] / _Q7) % 1 != 0


def _subsequence(small, big):
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def _losses(report):
    return report.get("losses", {}) or {}


def _count(report, cat):
    e = _losses(report).get(cat)
    return e["count"] if e else 0


def repaired_labels(report, header, labels):
    """Labels of the input header records that a report repair names (by label in the
    message, by label in the rule id with blanks as '-', or by the record's line number)."""
    bylines = {ln: _family(lab) for lab, c, ln in header}
    out = set()
    for r in report.get("repairs", []) or []:
        msg = r.get("message") or ""
        rule = r.get("rule") or ""
        if r.get("line") in bylines:
            out.add(bylines[r["line"]])
        for lab in labels:
            if lab in msg or lab.replace(" ", "-") in rule:
                out.add(_family(lab))
    if any((r.get("rule") or "") == "HDR.COUNTS" for r in report.get("repairs", []) or []):
        out |= {"# OF SATELLITES", "PRN / # OF OBS"}
    return out


def _leap_width(v):
    """Columns of LEAP SECONDS the version defines: I6 in 2.x and 3.00 (rinex211.txt Table A1,
    rinex300.txt Table A1); 4I6 in 3.01/3.02 (rinex301.txt p.33, rinex302.txt p.55); 4I6,A3
    from 3.03 (rinex303.txt Table A2, rinex305.txt Table A2/A5, rinex_4.02.txt Table A2/A7)."""
    if v < "3.01":
        return 6
    if v < "3.03":
        return 24
    return 27


def _leap_fields(c):
    c = c.ljust(60)
    return [_int(c[0:6]), _int(c[6:12]), _int(c[12:18]), _int(c[18:24]), c[24:27].strip()]


_BEIDOU_LEAP = ("BDS", "BDT")      # 3.03/3.04 spell it BDS (rinex303.txt p.60, rinex304.txt p.65)


def _bds_count(f):
    """A LEAP SECONDS record (fields) without identifier whose current count can only be a
    BDS one (below 14: see check_leap); 0 is "not known" (rinex302.txt Table A5 p.63)."""
    return not f[4] and f[0] is not None and 0 < f[0] < 14


def _to_gps(f):
    """Fields [cur, fut, week, day, id] of a BeiDou record in GPS terms: + 14 s, week + 1356,
    day + 1; a field that is 0 or blank is "not known" (rinex302.txt Table A5 p.63) and stays
    as written, and a day goes with its week (Sol round 28)."""
    k = lambda x: x is not None and x != 0
    return [f[0] + 14 if k(f[0]) else f[0], f[1] + 14 if k(f[1]) else f[1],
            f[2] + 1356 if k(f[2]) else f[2], f[3] + 1 if k(f[2]) and f[3] is not None else f[3]] + list(f[4:5])


def check_leap(cin, cout, sv, tv, report, where="LEAP SECONDS", basis=None, out_basis=None):
    """The current leap seconds must be equal; the fields after it must be equal where the
    target holds them, and a claim header-field-not-representable:LEAP SECONDS must exist
    exactly when a non-blank field had no room in the target. basis="BDS": a record with no
    identifier that counts from 2006 (a 3.02 BeiDou-only navigation file: rinex302.txt Table
    A5 p.63). out_basis="BDS": the output is such a file, so its record is read so (Sol round
    26)."""
    p = []
    a, b = _leap_fields(cin), _leap_fields(cout)
    # basis="BDS" / out_basis="BDS": a BeiDou-only 3.02-3.05 file; its record without an
    # identifier counts from 2006 when the count is below 14 (GPS-UTC has been 14 s or more
    # since 2006, BDT-UTC 4 s at most: real files write both, round 27), else from 1980
    a_bds = a[4] in _BEIDOU_LEAP or (basis == "BDS" and _bds_count(a))
    b_bds = b[4] in _BEIDOU_LEAP or (out_basis == "BDS" and _bds_count(b))
    if out_basis == "BDS" and tv == "3.02":
        cin = cin.ljust(24)[:24]          # (the basis says BeiDou: the identifier carries nothing)
    if b[4] in _BEIDOU_LEAP and not ("3.03" <= tv < "4"):
        # 'only GPS' in RINEX 4 (rinex_4.02.txt Tables A2/A7), no identifier before 3.03
        p.append(f"{where}: time system {b[4]!r} in the output, RINEX {tv} cannot name it")
    if a_bds and b_bds:
        # both in BeiDou terms; either spelling is BeiDou, the target's is written (the
        # validator checks which)
        if a[4] in _BEIDOU_LEAP and b[4] in _BEIDOU_LEAP:
            b[4] = a[4]
    elif b_bds:
        b = _to_gps(b)
    if a_bds and not b_bds:
        # 'only GPS and BDT are valid identifiers' in 3.03-3.05; RINEX 4 'only GPS', earlier
        # versions none (GPS fields): BDT counts from 1-Jan-2006 = GPS week 1356, 14 s behind
        # GPS (dtLS_BDS = dtLS - 14 s), days 0-6 against GPS 1-7 (rinex305.txt Table A2/A5,
        # rinex_4.02.txt l.871, l.943, Tables A2/A7)
        a = _to_gps(a)[:4] + ["GPS"]
        cin = "".join(" " * 6 if x is None else f"{x:6d}" for x in a[:4]) + "GPS"
        if b[4] not in ("GPS", "") and tv >= "4":
            p.append(f"{where}: time system {b[4]!r} in the output, RINEX {tv} allows only GPS")
    if a[0] != b[0]:
        p.append(f"{where}: current leap seconds {a[0]} in the input, {b[0]} in the output")
    w = _leap_width(tv)
    nf = {6: 1, 24: 4, 27: 5}[w]
    for k in range(1, 5):
        if k < nf and a[k] not in (None, "") and a[k] != b[k]:
            p.append(f"{where}: field {k + 1} is {a[k]!r} in the input, {b[k]!r} in the output")
    # text beyond the target's columns: dropped (claim needed), carried unchanged (a validity
    # question for the validator, not a difference) or changed (a difference)
    tail_in, tail_out = cin.ljust(60)[w:60], cout.ljust(60)[w:60]
    # (a GPS identifier alone is no field: without one the fields are GPS ones)
    dropped = tail_in.strip() not in ("", "GPS") and not tail_out.strip()
    claimed = "header-field-not-representable:LEAP SECONDS" in _losses(report)
    if dropped and not claimed:
        p.append(f"{where}: fields beyond column {w} ({tail_in.strip()!r}) dropped for RINEX {tv} "
                 "without a header-field-not-representable:LEAP SECONDS claim")
    if tail_out.strip() and tail_out != tail_in:
        p.append(f"{where}: the output writes {tail_out.strip()!r} in columns RINEX {tv} does not define "
                 f"(input {tail_in.strip()!r})")
    return p, dropped


def _ref_week(t, code):
    """(week, seconds of week) of a v4 STO reference epoch in the week the time-system code
    counts in: BDS weeks from 2006-01-01 for BD codes, GPS weeks from 1980-01-06 for the
    others (rinex305.txt Table A5 'W Reference week number'); None for GLONASS codes
    ('GLONASS T and W zero')."""
    if t is None or code[:2] == "GL":
        return None
    d0 = _BDS0 if code[:2] == "BD" else _GPS0
    days = (datetime.date(t[0], t[1], t[2]) - d0).days
    secs = days * 86400 + t[3] * 3600 + t[4] * 60 + int(t[5])
    return secs // 604800, secs % 604800


# ---------------------------------------------------------------------------
# observation files
# ---------------------------------------------------------------------------
class ObsEpoch:
    __slots__ = ("time", "flag", "sats", "clock", "recs", "line")

    def __init__(self, time, flag, sats, clock, recs, line):
        self.time, self.flag, self.sats, self.clock, self.recs, self.line = time, flag, sats, clock, recs, line


class ObsFile:
    def __init__(self, version, header, epochs, single, counts=None, types_changed=False):
        self.version, self.header, self.epochs, self.single = version, header, epochs, single
        # counts[flag class '01' or '6'][sat] = non-missing values per obs type (count=True)
        self.counts, self.types_changed = counts, types_changed

    def recs(self, label):
        return [c for lab, c, ln in self.header if _family(lab) == label]


def _nonmissing(f):
    """Blank or zero means "missing" (rinex211.txt ~1288, rinex305.txt §6.7)."""
    return bool(f[:14].strip(" 0.+-"))


def parse_obs(payload, count=False):
    """Header records and every epoch (time, flag, satellites, clock, event records),
    read with the layouts of rinex211.txt Table A2 and rinex_4.02.txt Table A3.
    RINEX 3/4 epoch: '>' yyyy mm dd hh mm F11.7 at 18:29, flag col 31, count 32:35, clock
    F15.12 at 41:56, 4.02 picoseconds 1X,I5.5 at 57:62. RINEX 2: yy..mm at 1:15, F11.7 at
    15:26, flag col 28, count 29:32, satellites 12(A1,I2) at 32:68, clock F12.9 at 68:80."""
    L = _lines(payload)
    v = _vstr(L[0])
    head, end = _header(L)
    single = L[0][40:41].strip() or "G"
    if single == "M":
        single = "G"
    nt = 0
    nt3 = {}
    for lab, c, ln in head:
        if lab == "# / TYPES OF OBSERV" and c[:6].strip():
            nt = int(c[:6])
        elif lab == "SYS / # / OBS TYPES" and c[0] != " " and c[3:6].strip():
            nt3[c[0]] = int(c[3:6])
    counts = {"01": defaultdict(Counter), "6": defaultdict(Counter)} if count else None
    types_changed = False
    epochs = []
    v3 = v >= "3"
    i = end + 1
    n = len(L)
    while i < n:
        l = L[i]
        if not l.strip():
            i += 1
            continue
        line = i + 1
        if v3:
            if not l.startswith(">"):
                i += 1
                continue
            l = l.ljust(62)
            flag = int(l[31]) if l[31].strip() else 0
            ns = int(l[32:35]) if l[32:35].strip() else 0
            t = None
            if l[2:29].strip():
                sec = Decimal(l[18:29].strip())
                if l[57:62].strip():
                    sec += Decimal(int(l[57:62])).scaleb(-12)
                t = (int(l[2:6]), int(l[7:9]), int(l[10:12]), int(l[13:15]), int(l[16:18]), sec.normalize())
            clock = _dec(l[41:56])
            i += 1
            if 2 <= flag <= 5:
                recs = [(L[i + k][60:80].strip(), L[i + k][:60].ljust(60)) for k in range(ns)]
                types_changed |= any(r[0] == "SYS / # / OBS TYPES" for r in recs)
                epochs.append(ObsEpoch(t, flag, [], clock, recs, line))
                i += ns
                continue
            sats = []
            for k in range(ns):
                d = L[i + k]
                sat = d[0] + "%02d" % int(d[1:3])
                sats.append(sat)
                if count:
                    cc = counts["6" if flag == 6 else "01"][sat]
                    for j in range(nt3.get(d[0], 0)):
                        if _nonmissing(d[3 + 16 * j:19 + 16 * j]):
                            cc[j] += 1
            i += ns
            epochs.append(ObsEpoch(t, flag, sats, clock, [], line))
        else:
            l = l.ljust(80)
            flag = int(l[26:29]) if l[26:29].strip() else 0
            ns = int(l[29:32]) if l[29:32].strip() else 0
            t = None
            if l[0:26].strip():
                t = (_year(l[1:3]), int(l[4:6]), int(l[7:9]), int(l[10:12]), int(l[13:15]),
                     Decimal(l[15:26].strip()).normalize())
            clock = _dec(l[68:80])
            i += 1
            if 2 <= flag <= 5:
                recs = []
                for k in range(ns):
                    hl = L[i + k]
                    recs.append((hl[60:80].strip(), hl[:60].ljust(60)))
                    if hl[60:80].strip() == "# / TYPES OF OBSERV" and hl[:6].strip():
                        nt = int(hl[:6])
                        types_changed = True
                epochs.append(ObsEpoch(t, flag, [], clock, recs, line))
                i += ns
                continue
            sats = []
            sl = l
            while len(sats) < ns:
                for k in range(12):
                    if len(sats) == ns:
                        break
                    sv = sl[32 + 3 * k:35 + 3 * k]
                    sats.append((sv[0] if sv[0] != " " else single) + "%02d" % int(sv[1:3]))
                if len(sats) < ns:
                    sl = L[i].ljust(80)
                    i += 1
            per = max(1, (nt + 4) // 5)
            if count:
                for k, sat in enumerate(sats):
                    rec = "".join(L[i + per * k + m][:80].ljust(80) for m in range(per))
                    cc = counts["6" if flag == 6 else "01"][sat]
                    for j in range(nt):
                        if _nonmissing(rec[16 * j:16 * j + 16]):
                            cc[j] += 1
            i += len(sats) * per
            epochs.append(ObsEpoch(t, flag, sats, clock, [], line))
    f = ObsFile(v, head, epochs, single, counts, types_changed)
    f.ntypes = (lambda sysc: nt) if not v3 else (lambda sysc: nt3.get(sysc, 0))
    return f


def _lost_systems(report):
    return {k.split(":")[1] for k in _losses(report)
            if k.startswith(("system-not-representable:", "system-removed-unresolvable:"))}


def _epoch_checks(a, b, report, tv, type_emptied=None):
    """type_emptied: (time, flag) of input epochs whose every satellite record is left out
    (its system removed, or with no target column under its type list: compare_obs)."""
    p = []
    key = _floor7 if tv < "4.02" else (lambda t: t)
    lost = _lost_systems(report)
    data_in = [e for e in a.epochs if e.flag in (0, 1, 6)]
    data_out = [e for e in b.epochs if e.flag in (0, 1, 6)]

    def gone(e):
        if not e.sats:
            return False
        if all(s[0] in lost for s in e.sats):
            return True
        t = None if e.time is None else tuple(e.time[:5]) + (Decimal(e.time[5]).normalize(),)
        return (t, e.flag) in (type_emptied or ())
    emptied = [e for e in data_in if gone(e)]
    kept = [e for e in data_in if not gone(e)]
    claimed = _count(report, "epoch-emptied-by-system-removal")
    if claimed != len(emptied):
        p.append(f"{len(emptied)} input epochs hold only satellites of removed systems {sorted(lost)}, "
                 f"report claims {claimed} epoch-emptied-by-system-removal")
    cin = Counter((key(e.time), e.flag) for e in kept)
    cout = Counter((key(e.time), e.flag) for e in data_out)
    if cin != cout:
        miss = cin - cout
        extra = cout - cin
        p.append(f"epochs (time, flag 0/1/6) differ: {sum(miss.values())} input epochs missing, "
                 f"{sum(extra.values())} output epochs not in the input; e.g. missing {list(miss)[:2]}, "
                 f"extra {list(extra)[:2]}")
    # sub-0.1 us epoch digits exist only from 4.02 (rinex_4.02.txt Table A3)
    events_in = [e for e in a.epochs if 2 <= e.flag <= 5]
    n_sub = sum(1 for e in kept + events_in if _sub7(e.time)) if tv < "4.02" else 0
    c_sub = _count(report, "epoch-precision")
    if n_sub != c_sub:
        p.append(f"{n_sub} epochs have digits below 0.1 us that RINEX {tv} cannot hold, report "
                 f"claims {c_sub} epoch-precision")
    # receiver clock offsets: equal, or rounded to 1e-9 s for RINEX 2 (F12.9 vs F15.12)
    byk_in = defaultdict(list)
    for e in kept:
        byk_in[(key(e.time), e.flag)].append(e)
    byk_out = defaultdict(list)
    for e in data_out:
        byk_out[(key(e.time), e.flag)].append(e)
    rounded = lost_clock = cand = 0
    bad = []
    q9 = Decimal("1e-9")
    for k, lst in byk_in.items():
        for ei, eo in zip(lst, byk_out.get(k, [])):
            ci, co = ei.clock, eo.clock
            if ci is not None and tv < "3" and ci != ci.quantize(q9):
                cand += 1
            if ci is None and co is None or ci is not None and co is not None and ci == co:
                continue
            if ci is None:
                bad.append(f"epoch {k}: output has receiver clock {co}, the input has none")
            elif co is None:
                lost_clock += 1
            elif tv < "3" and co == co.quantize(q9) and abs(ci - co) <= Decimal("0.5e-9"):
                rounded += 1
            else:
                bad.append(f"epoch {k}: receiver clock {ci} in the input, {co} in the output")
    if bad:
        p.append(f"{len(bad)} receiver clock offsets changed: {bad[:3]}")
    c_prec = _count(report, "clock-precision")
    if not (rounded <= c_prec <= cand):
        p.append(f"{rounded} receiver clocks rounded to 1e-9 s ({cand} have digits below 1e-9 s), "
                 f"report claims {c_prec} clock-precision")
    c_ovf = _count(report, "clock-overflow")
    if lost_clock != c_ovf:
        p.append(f"{lost_clock} epochs lost their receiver clock, report claims {c_ovf} clock-overflow")
    return p


def _event_checks(a, b, report, tv, dropped=None):
    """Flags 2-5: same events (time, flag) in order, except flag-4 events left empty
    (claimed event-emptied); COMMENT texts equal; other records kept when the target
    defines them, else claimed event-record-not-representable:<LABEL>, or for SYS / PHASE
    SHIFT and GLONASS COD/PHS/BIS from RINEX 3 to 4, event-record-deprecated:<LABEL>.
    SYS / PHASE SHIFT entries left out are added to `dropped` (sys, code)."""
    p = []
    dropped = Counter() if dropped is None else dropped
    out_sys = output_systems(b)
    key = _floor7 if tv < "4.02" else (lambda t: t)
    defined = OBS_LABELS.get(tv, set())
    ev_in = [e for e in a.epochs if 2 <= e.flag <= 5]
    if a.version == tv:
        # same version: the file's own non-standard event records are carried as written
        # (as in the header, compare_obs_meta)
        defined = defined | {lab for e in ev_in for lab, c in e.recs if lab in ALL_OBS_LABELS}
    ev_out = [e for e in b.epochs if 2 <= e.flag <= 5]
    pairs, emptied = [], []
    j = 0
    for e in ev_in:
        if j < len(ev_out) and (key(e.time), e.flag) == (key(ev_out[j].time), ev_out[j].flag):
            pairs.append((e, ev_out[j]))
            j += 1
        else:
            emptied.append(e)
    if j < len(ev_out):
        p.append(f"{len(ev_out) - j} output events not in the input, first at "
                 f"{ev_out[j].time} flag {ev_out[j].flag}")
    c_empty = _count(report, "event-emptied")
    if len(emptied) != c_empty:
        p.append(f"{len(emptied)} input events missing from the output "
                 f"({[(e.time, e.flag) for e in emptied][:3]}), report claims {c_empty} event-emptied")
    missing = Counter()
    for e in emptied:
        if e.flag != 4:
            p.append(f"event flag {e.flag} at {e.time} (input line {e.line}) is missing from the output")
        for lab, c in e.recs:
            f = _family(lab)
            missing[f] += 1
            if f == "COMMENT":
                p.append(f"event at {e.time} (input line {e.line}) dropped with its COMMENT {c.rstrip()!r}")
            elif f not in OBS_REGEN and (lab in defined or lab not in ALL_OBS_LABELS):
                p.append(f"event at {e.time} dropped with record {lab} that RINEX {tv} defines")
    out_codes = output_phase_codes(b) if tv >= "3" else {}
    for ei, eo in pairs:
        cin = [c.rstrip() for lab, c in ei.recs if lab == "COMMENT"]
        cout = [c.rstrip() for lab, c in eo.recs if lab == "COMMENT"]
        if cin != cout:
            p.append(f"event at {ei.time} (input line {ei.line}): COMMENT texts differ: {cin} -> {cout}")
        p += phase_compare(phase_entries(ei.recs), phase_entries(eo.recs), a.version, tv, out_codes,
                           report, f"event at {ei.time}", header=False, out_systems=out_sys,
                           dropped=dropped)
        # GLONASS SLOT / FRQ # of an event is carried where the target defines it (3.01 on):
        # the same slot/channel pairs (was not compared at all: Sol round 22)
        gs_in = [c for lab, c in ei.recs if lab == "GLONASS SLOT / FRQ #"]
        gs_out = [c for lab, c in eo.recs if lab == "GLONASS SLOT / FRQ #"]
        if tv >= "3.01" and (gs_in or gs_out) and _glo_pairs(gs_in) != _glo_pairs(gs_out):
            p.append(f"event at {ei.time} (input line {ei.line}): GLONASS SLOT / FRQ # pairs "
                     f"{sorted(_glo_pairs(gs_in))} -> {sorted(_glo_pairs(gs_out))}")
        # GLONASS COD/PHS/BIS carried in an event keeps its values; WAVELENGTH FACT L1/2
        # between RINEX 2 versions is carried as written (into RINEX 3 it becomes LLI bit 1 of
        # the following epochs, which the token comparison sees); both regenerated families,
        # skipped below (were not compared within events: round 22)
        for f in ("GLONASS COD/PHS/BIS", "WAVELENGTH FACT L1/2"):
            xin = [norm(f, c) for lab, c in ei.recs if _family(lab) == f]
            xout = [norm(f, c) for lab, c in eo.recs if _family(lab) == f]
            carried = f == "WAVELENGTH FACT L1/2" and a.version < "3" and tv < "3"
            if (xout or carried) and xin != xout:
                p.append(f"event at {ei.time} (input line {ei.line}): record {f} changed: {xin} -> {xout}")
        gin, gout = defaultdict(list), defaultdict(list)
        for lab, c in ei.recs:
            gin[_family(lab)].append((lab, c))
        for lab, c in eo.recs:
            gout[_family(lab)].append((lab, c))
        for f, lst in gin.items():
            if f == "COMMENT":
                continue
            nmiss = max(0, len(lst) - len(gout.get(f, [])))
            missing[f] += nmiss
            if f in OBS_REGEN:
                continue
            raw = lst[0][0]
            if raw in defined or raw not in ALL_OBS_LABELS:
                a_n = [norm(f, c) for lab, c in lst]
                b_n = [norm(f, c) for lab, c in gout.get(f, [])]
                if a_n != b_n:
                    p.append(f"event at {ei.time} (input line {ei.line}): record {f} changed: "
                             f"{a_n} -> {b_n}")
            elif gout.get(f):
                p.append(f"event at {ei.time}: output keeps {f}, which RINEX {tv} does not define")
        for f, lst in gout.items():
            if f not in gin and f not in OBS_REGEN and f != "COMMENT":
                p.append(f"event at {ei.time}: output adds record {f} not in the input event")
            raw = lst[0][0]
            if raw in ALL_OBS_LABELS and raw not in defined and raw not in {lab for lab, c in ei.recs}:
                p.append(f"event at {ei.time}: output writes {raw}, which RINEX {tv} does not define")
    claims = {_family(k.split(":", 1)[1]): e["count"] for k, e in _losses(report).items()
              if k.startswith("event-record-not-representable:")}
    # RINEX 3 -> 4: defined but strongly deprecated, dropped with a claim per record line
    # (rinex_4.00.txt Table A2 p.61); was not compared at all (Sol round 13)
    depr = {"SYS / PHASE SHIFT", "GLONASS COD/PHS/BIS"} if a.version < "4" <= tv else set()
    dclaims = {_family(k.split(":", 1)[1]): e["count"] for k, e in _losses(report).items()
               if k.startswith("event-record-deprecated:")}
    for f in set(dclaims) | {f for f in missing if f in depr and missing[f]}:
        if f not in depr:
            p.append(f"report claims event-record-deprecated:{f}, which RINEX {a.version} -> {tv} "
                     "does not deprecate")
        elif dclaims.get(f, 0) != missing.get(f, 0):
            p.append(f"{missing.get(f, 0)} event records {f} dropped as deprecated, report claims "
                     f"{dclaims.get(f, 0)} event-record-deprecated:{f}")
    # SYS / PHASE SHIFT (from 3.01) and GLONASS COD/PHS/BIS (from 3.02) are regenerated
    # records, skipped below, but in an event of a target without them they are dropped with a
    # claim per record line (was not compared: Sol round 13 audit)
    for f, since in (("SYS / PHASE SHIFT", "3.01"), ("GLONASS COD/PHS/BIS", "3.02"),
                     ("GLONASS SLOT / FRQ #", "3.01")):
        if tv < since and claims.get(f, 0) != missing.get(f, 0):
            p.append(f"{missing.get(f, 0)} event records {f} dropped (RINEX {tv} does not define it), "
                     f"report claims {claims.get(f, 0)} event-record-not-representable:{f}")
    for f, n in missing.items():
        if f in OBS_REGEN or f == "COMMENT":
            continue
        raw_defined = f in defined or f not in ALL_OBS_LABELS
        if not raw_defined and claims.get(f, 0) != n:
            p.append(f"{n} event records {f} dropped (RINEX {tv} does not define it), report claims "
                     f"{claims.get(f, 0)} event-record-not-representable:{f}")
    for f, n in claims.items():
        if missing.get(f, 0) != n:
            p.append(f"report claims {n} event-record-not-representable:{f}, {missing.get(f, 0)} such "
                     f"event records are missing from the output")
        if f not in OBS_REGEN and (f in defined or f == "COMMENT"):
            p.append(f"report claims event-record-not-representable:{f}, but RINEX {tv} defines {f}")
    # SYS / PHASE SHIFT inside an output event names a carrier phase code (rinex305.txt p.57)
    # of the output's own type lists (header or events): an entry left in the source's
    # spelling (e.g. BDS L1I in 3.05) shows here
    if tv >= "3":
        codes = defaultdict(set)
        cur = None
        listed = [(lab, c) for lab, c, ln in b.header] + [x for e in ev_out for x in e.recs]
        for lab, c in listed:
            if lab == "SYS / # / OBS TYPES":
                if c[:1].strip():
                    cur = c[0]
                codes[cur].update(_type_codes(c))
        for e in ev_out:
            for lab, c in e.recs:
                code = _phase_code(c[2:5])
                if _family(lab) == "SYS / PHASE SHIFT" and c[:1].strip() and code \
                        and code not in codes.get(c[0], ()):
                    p.append(f"event at {e.time}: SYS / PHASE SHIFT {c[0]} {code} names no "
                             "observation type of the output")
        # an event emptied of its SYS / PHASE SHIFT entries: each entry's system is absent
        # from the output, or its non-zero value is claimed phase-shift-entry-dropped (a
        # zero or blank value against a code the output does not list carries nothing)
        losses = _losses(report)
        # only where the target carries event SYS / PHASE SHIFT records (3.01-3.05, and RINEX
        # 4 from RINEX 4); elsewhere they are claimed event-record-not-representable (2.x,
        # 3.00) or event-record-deprecated (RINEX 3 -> 4)
        carries = "3.01" <= tv < "4" or (a.version >= "4" and tv >= "4")
        for e in emptied if carries else ():
            for lab, c in e.recs:
                s, code = c[:1].strip(), _phase_code(c[2:5])
                if _family(lab) != "SYS / PHASE SHIFT" or not s or s not in codes:
                    continue
                val = c[6:14].strip()
                zero = not val or _is_zero(val)
                if code in codes[s] or not (zero or f"phase-shift-entry-dropped:{s}:{code}" in losses):
                    p.append(f"event at {e.time} (input line {e.line}) dropped with SYS / PHASE SHIFT "
                             f"{s} {code} {val}, which the output's {s} types could hold")
                elif not zero:
                    dropped[(s, code)] += 1
    return p


def _is_zero(text):
    try:
        return Decimal(text) == 0
    except InvalidOperation:
        return False


def _phase_code(field):
    """The A3 code of a SYS / PHASE SHIFT entry: a code written without its type letter ('1C')
    reads as L1C (the field holds carrier phase codes only, rinex305.txt p.57); a code with a
    blank attribute ('L1 ', 3.00/3.01: rinex300.txt l.690) stays three characters, as the
    converter's claims name it (Sol round 13)."""
    code = field.strip()
    if len(code) == 2 and code[0].isdigit():
        return "L" + code
    if len(code) == 2:
        return code + " "
    return code


def _type_codes(content):
    """The codes of a SYS / # / OBS TYPES line (13(1X,A3) from column 8), A3 identity kept."""
    from .tokens import _a3
    return _a3(content[7:60])


# ---------------------------------------------------------------------------
# SYS / PHASE SHIFT (header and events)
# ---------------------------------------------------------------------------

def phase_entries(recs):
    """SYS / PHASE SHIFT(S) entries (sys, code, value, sats) of [(label, content), ...]:
    A1,1X,A3,1X,F8.5,2X,I2.2,10(1X,A3), continuation 18X,10(1X,A3) (rinex305.txt Table A2;
    the same columns from 3.01). The code field holds carrier phase codes only, so a code
    written without its type letter ('1C') reads as L1C. Wholly blank lines hold nothing."""
    out = []
    for lab, c in recs:
        if _family(lab) != "SYS / PHASE SHIFT":
            continue
        c = c.ljust(60)
        if not c[:60].strip():
            continue
        if c[0] != " ":
            code = _phase_code(c[2:5])
            v = c[6:14].strip()
            try:
                val = Decimal(v).normalize() if v else None
            except InvalidOperation:
                val = v
            out.append([c[0], code, val, c[18:60].split()])
        elif out:
            out[-1][3].extend(c[18:60].split())
    return [(s, code, v, tuple(sats)) for s, code, v, sats in out]


def output_phase_codes(b):
    """{sys: phase codes} over every SYS / # / OBS TYPES list of an output (header and
    events)."""
    codes = defaultdict(list)
    cur = None
    listed = [(lab, c) for lab, c, ln in b.header] + [x for e in b.epochs if 2 <= e.flag <= 5 for x in e.recs]
    for lab, c in listed:
        if lab == "SYS / # / OBS TYPES":
            if c[:1].strip():
                cur = c[0]
            codes[cur] += [x for x in _type_codes(c) if x[0] == "L" and x not in codes[cur]]
    codes.pop(None, None)
    return dict(codes)


def phase_compare(ein, eout, sv, tv, out_codes, report, where, header=True, out_systems=None,
                  dropped=None):
    """One scope (the header, or one event) of SYS / PHASE SHIFT, input entries ein against
    output entries eout. What the output may hold (PLAN §3.3; rinex305.txt §5.2.12 p.25-26):
      - RINEX 2 / 3.00 target, or RINEX 4 target from RINEX 3: nothing (not defined;
        strongly deprecated in 4, rinex_4.00.txt Table A2 p.61);
      - carried (3.01-3.05 <-> 3.01-3.05, 4 -> 4, and every event): each output entry is an
        input entry with the same value and satellites, the code the same signal
        (tokens.signal_class: only the BeiDou B1I band digit differs between versions); an
        input entry left out names a code the output does not list, and a non-zero value
        left out is claimed phase-shift-entry-dropped:<sys>:<code>; the system-only form
        ('unknown', rinex302.txt p.42) where nothing of the input could be carried;
      - generated (header, from RINEX 2/3.00 or RINEX 4): no satellite lists; the
        system-only 'unknown' form, or zero values for the output's phase codes when the
        source is RINEX 4 (aligned) or --assume-phase-aligned is reported."""
    from .tokens import signal_class
    p = []
    losses = _losses(report)
    if tv < "3.01" or (tv >= "4" and sv < "4"):
        if eout:
            p.append(f"{where}: output writes SYS / PHASE SHIFT, which a RINEX {sv} -> {tv} "
                     "conversion leaves out")
        return p
    if header and (sv < "3.01" or (sv >= "4" and tv < "4")):
        assumed = {x["detail"] for x in report.get("assumptions", []) or []
                   if x["category"] == "phase-alignment" and "assume-phase-aligned" in x.get("source", "")}
        zeros = defaultdict(set)
        for s, code, v, sats in eout:
            if sats:
                p.append(f"{where}: generated SYS / PHASE SHIFT {s} {code} lists satellites {sats}")
            if not code:
                if sv >= "4" and any(out_codes.values()):
                    p.append(f"{where}: aligned RINEX {sv} phases written as 'unknown' ({s})")
                continue
            if v != 0:
                p.append(f"{where}: generated SYS / PHASE SHIFT {s} {code} has value {v}, not 0")
            if sv < "3.01" and s not in assumed:
                p.append(f"{where}: {s} {code} written as aligned (0) from a RINEX {sv} source without "
                         "an --assume-phase-aligned assumption")
            if code not in out_codes.get(s, ()):
                p.append(f"{where}: SYS / PHASE SHIFT {s} {code} names no phase type of the output")
            zeros[s].add(code)
        for s in zeros:
            missing = [c for c in out_codes.get(s, ()) if c not in zeros[s]]
            if missing:
                p.append(f"{where}: the zero form for {s} leaves out phase types {missing}")
        bare = sorted(s for s, cs in out_codes.items() if cs and s not in {e[0] for e in eout})
        if bare:
            p.append(f"{where}: no SYS / PHASE SHIFT for {bare}, which have phase types")
        return p
    vin, vout = sv, tv

    def cls(vk, s, code):
        return signal_class(vk, s, code, exact=True) if code else ""

    pool = Counter((s, cls(vin, s, c), v, sats) for s, c, v, sats in ein)
    raw = defaultdict(list)
    for s, c, v, sats in ein:
        raw[(s, cls(vin, s, c), v, sats)].append(c)
    fallback = []
    matched = 0
    for e in eout:
        k = (e[0], cls(vout, e[0], e[1]), e[2], e[3])
        if pool[k] > 0:
            pool[k] -= 1
            matched += 1
        elif header and not e[1] and e[2] is None and not e[3]:
            fallback.append(e[0])
        else:
            p.append(f"{where}: output SYS / PHASE SHIFT {e[0]} {e[1]} {e[2]} {list(e[3])} is no input "
                     "entry (value, satellites and signal must be kept)")
    if fallback and matched:
        p.append(f"{where}: 'unknown' SYS / PHASE SHIFT for {fallback} written next to carried entries")
    out_cls = {s: {cls(vout, s, c) for c in cs} for s, cs in out_codes.items()}
    systems = out_codes if out_systems is None else out_systems
    for k, n in (+pool).items():
        s, c_cls, v, sats = k
        if s not in systems:
            continue                       # the system is not in the output
        code = raw[k][0]
        if c_cls and c_cls in out_cls.get(s, ()):
            p.append(f"{where}: input SYS / PHASE SHIFT {s} {code} {v} left out although the output "
                     f"lists that signal")
        elif v not in (None, 0):
            if f"phase-shift-entry-dropped:{s}:{code}" not in losses:
                p.append(f"{where}: input SYS / PHASE SHIFT {s} {code} {v} dropped without a "
                         f"phase-shift-entry-dropped:{s}:{code} claim")
            if dropped is not None:
                dropped[(s, code)] += n
    return p


def _held_systems(b):
    """Systems an output holds: those with an observation type list (RINEX 3/4)."""
    return output_systems(b)


def _sys_records(a, b, tv, report):
    """SYS / DCBS APPLIED and SYS / PCVS APPLIED name a system (A1,1X,A17,1X,A40: rinex305.txt
    Table A2; 3.00 allows G/R/E/S: rinex300.txt Table A1 p.29): to another RINEX 3/4 version a
    record of a system the output does not hold has no room and is claimed
    sys-record-not-representable:<sys>:<LABEL>, header and events alike (Sol round 21). Returns
    (problems, the input without those records, for the checks after)."""
    p = []
    labels = ("SYS / DCBS APPLIED", "SYS / PCVS APPLIED")
    if tv < "3" or a.version == tv:
        return p, a
    held = _held_systems(b)
    want = Counter()

    def gone(lab, c):
        if lab in labels and c[:1].strip() and c[:1] not in held:
            want[f"{c[:1]}:{lab}"] += 1
            return True
        return False
    g = copy.copy(a)
    g.header = [h for h in a.header if not gone(h[0], h[1])]
    g.epochs = [ObsEpoch(e.time, e.flag, e.sats, e.clock, [x for x in e.recs if not gone(x[0], x[1])], e.line)
                if 2 <= e.flag <= 5 else e for e in a.epochs]
    got = Counter({k.split(":", 1)[1]: e["count"] for k, e in _losses(report).items()
                   if k.startswith("sys-record-not-representable:")})
    if +want != +got:
        p.append(f"SYS / DCBS / PCVS APPLIED records of systems the output lacks {dict(want)}, report "
                 f"claims {dict(got)} sys-record-not-representable")
    return p, g


def _phasecenter_checks(a, b, tv, report):
    """ANTENNA: PHASECENTER names a system and an observation code (A1,1X,A3,F9.4,2F14.4:
    rinex305.txt Table A2 p.53). Between RINEX 3/4 versions each record must come out with the
    same system and values and a code of the same signal (the BDS B1I band digit differs
    between versions: tokens.signal_class), or, when the target has no code of that signal or
    lacks the system, be claimed antenna-phasecenter-code-not-representable:<sys>:<code>; to
    the file's own version, or from RINEX 2 (where it is a foreign plain record), it is
    carried as written; to RINEX 2 it is claimed header-record-not-representable (Sol round
    20: a 3.02 'C L1X', B1I, stayed 'L1X', B1C in 3.05)."""
    from . import codes as _codes
    from .tokens import signal_class
    p = []
    sv = a.version
    lab = "ANTENNA: PHASECENTER"

    def pc(recs):
        return [c.ljust(60) for x, c in recs if x == lab]
    # each record within its own scope, the header or one event: a value holds until a later
    # event changes it (rinex305.txt section 6.5 p.42), so records pooled across scopes could
    # trade places unnoticed (Sol round 22); only the claims add up over the file
    scopes = [("header", pc((x, c) for x, c, ln in a.header), pc((x, c) for x, c, ln in b.header))]
    pairs, emptied, extra = event_pairs(a, b, tv)
    scopes += [(f"event at {ei.time}", pc(ei.recs), pc(eo.recs)) for ei, eo in pairs]
    scopes += [(f"event at {ei.time}", pc(ei.recs), []) for ei in emptied]
    scopes += [(f"output event at {eo.time}", [], pc(eo.recs)) for eo in extra]
    claims = Counter({k.split(":", 1)[1]: e["count"] for k, e in _losses(report).items()
                      if k.startswith("antenna-phasecenter-code-not-representable:")})
    if tv < "3":
        if any(rout for w, rin, rout in scopes):
            p.append(f"output keeps ANTENNA: PHASECENTER, which RINEX {tv} does not define")
        nh = len(scopes[0][1])
        ne = sum(len(rin) for w, rin, rout in scopes[1:])
        for where, n in (("header", nh), ("event", ne)):
            c = _count(report, f"{where}-record-not-representable:ANTENNA: PHASECENTER")
            if c != n:
                p.append(f"{n} {where} ANTENNA: PHASECENTER records dropped, report claims {c}")
        return p
    if sv < "3" or sv == tv:
        for where, rin, rout in scopes:
            if Counter(x.rstrip() for x in rin) != Counter(x.rstrip() for x in rout):
                p.append(f"{where}: ANTENNA: PHASECENTER records not carried as written")
        return p
    vk_in, vk_out = "%.2f" % float(sv), "%.2f" % float(tv)

    def values(c):
        return tuple(_dec(c[k:k + w]) for k, w in ((5, 9), (14, 14), (28, 14)))
    want = Counter()
    held_sys = _held_systems(b)
    for where, rin, rout in scopes:
        pool = Counter((c[0], signal_class(vk_out, c[0], c[2:5], True), values(c)) for c in rout)
        for c in rin:
            sysc, code = c[0], c[2:5]
            cls = signal_class(vk_in, sysc, code, True)
            key = (sysc, cls, values(c))
            if pool[key] > 0:
                pool[key] -= 1
                continue
            held = sysc in held_sys and sysc in _codes.systems(tv) and any(
                signal_class(vk_out, sysc, x, True) == cls for x in _codes.codes(tv, sysc))
            if held:
                p.append(f"{where}: ANTENNA: PHASECENTER {sysc} {code}: no output record of that "
                         "signal with its values")
            else:
                want[f"{sysc}:{code}"] += 1
        if +pool:
            p.append(f"{where}: output ANTENNA: PHASECENTER records not in the input: "
                     f"{list((+pool).elements())[:2]}")
    if +want != +claims:
        p.append(f"ANTENNA: PHASECENTER codes with no room {dict(want)}, report claims {dict(claims)}")
    return p


def event_pairs(a, b, tv):
    """Input events (flags 2-5) matched in order with the output's by (time, flag): (pairs,
    input events the output lacks, output events the input lacks)."""
    key = _floor7 if tv < "4.02" else (lambda t: t)
    ev_in = [e for e in a.epochs if 2 <= e.flag <= 5]
    ev_out = [e for e in b.epochs if 2 <= e.flag <= 5]
    pairs, emptied = [], []
    j = 0
    for e in ev_in:
        if j < len(ev_out) and (key(e.time), e.flag) == (key(ev_out[j].time), ev_out[j].flag):
            pairs.append((e, ev_out[j]))
            j += 1
        else:
            emptied.append(e)
    return pairs, emptied, ev_out[j:]


def glonass_claims(a, b, tv, report):
    """GLONASS SLOT / FRQ # (optional in 3.01, rinex301.txt p.32; mandatory from 3.02) and
    GLONASS COD/PHS/BIS (from 3.02, rinex302.txt Table A2) have no room before that: with
    GLONASS in the output, an input record is claimed header-record-not-representable once,
    a COD/PHS/BIS record only when not blank. Both are regenerated records, so the generic
    header check skips them (was not compared: Sol round 13 audit)."""
    p = []
    sats = {s[0] for e in b.epochs for s in e.sats}
    if sats:
        has_r = "R" in sats
    else:
        # no data: the systems are those the input declares (its type lists; a RINEX 2 file's
        # header letter, M read as G) that are not claimed lost
        declared = output_systems(a) if a.version >= "3" else {a.single}
        has_r = "R" in declared and not any(k.split(":")[1:2] == ["R"] for k in _losses(report)
                                            if k.startswith(("system-not-representable:",
                                                             "system-removed-unresolvable:")))
    slot = bool(a.recs("GLONASS SLOT / FRQ #"))
    cpb = bool(a.recs("GLONASS COD/PHS/BIS")[:1] and a.recs("GLONASS COD/PHS/BIS")[0].strip())
    want = {"GLONASS SLOT / FRQ #": slot and has_r and tv < "3.01",
            "GLONASS COD/PHS/BIS": cpb and has_r and tv < "3.02"}
    for lab, lost in want.items():
        c = _count(report, f"header-record-not-representable:{lab}")
        if c != int(lost):
            p.append(f"header {lab} {'lost' if lost else 'not lost'} for RINEX {tv}, report claims {c} "
                     f"header-record-not-representable:{lab}")
    return p


def output_systems(b):
    """Systems with an observation type list in an output (header or events)."""
    out = set()
    for lab, c in [(lab, c) for lab, c, ln in b.header] + [x for e in b.epochs if 2 <= e.flag <= 5 for x in e.recs]:
        if lab == "SYS / # / OBS TYPES" and c[:1].strip():
            out.add(c[0])
        elif lab == "# / TYPES OF OBSERV":
            out |= {s[0] for e in b.epochs for s in e.sats}
            break
    return out


def phase_claims(ein, sv, tv, out_systems, dropped, report):
    """The SYS / PHASE SHIFT losses, counted exactly (Sol round 13: a deleted claim, or a count
    of 999, passed). The header record has no room in 2.x / 3.00 (it exists from 3.01,
    rinex301.txt §9.1): one phase-shift-record-not-representable per entry when any entry
    names a code. From RINEX 3 to 4 it is strongly deprecated (rinex_4.00.txt Table A2 p.61):
    one phase-shift-record-deprecated per entry of an output system when any entry has a
    value. Entries left out elsewhere (header and events, `dropped`) are one
    phase-shift-entry-dropped:<sys>:<code> each."""
    p = []
    want = {"phase-shift-record-not-representable": 0, "phase-shift-record-deprecated": 0}
    if tv < "3.01" and any(e[1] for e in ein):
        want["phase-shift-record-not-representable"] = len(ein)
    elif tv >= "4" and sv < "4" and any(e[2] is not None for e in ein):
        want["phase-shift-record-deprecated"] = len([e for e in ein if e[0] in out_systems])
    for cat, n in want.items():
        c = _count(report, cat)
        if c != n:
            p.append(f"{n} header SYS / PHASE SHIFT entries lost ({cat}), report claims {c}")
    claims = Counter({tuple(k.split(":", 2)[1:]): e["count"] for k, e in _losses(report).items()
                      if k.startswith("phase-shift-entry-dropped:")})
    if +claims != +dropped:
        diff = sorted(set(claims) | set(dropped))
        p.append("SYS / PHASE SHIFT entries left out " + str({f"{s}:{c}": dropped[(s, c)] for s, c in diff})
                 + ", report claims phase-shift-entry-dropped " + str({f"{s}:{c}": claims[(s, c)] for s, c in diff}))
    return p


def _time_of(content):
    tok = content[:43].split()
    try:
        y, mo, d, h, mi = (int(x) for x in tok[:5])
        return (y, mo, d, h, mi, Decimal(tok[5]).normalize())
    except (ValueError, IndexError, InvalidOperation):
        return None


_TSYS_DEFAULT = {"G": "GPS", "R": "GLO", "E": "GAL", "C": "BDT", "J": "QZS", "I": "IRN"}


def _sampling(times):
    """The most frequent positive step between successive epochs (ties: the smaller), to the
    millisecond of INTERVAL's F10.3 (rinex305.txt Table A2), or None."""
    import datetime

    def secs(t):
        d = datetime.datetime(t[0], t[1], t[2], t[3], t[4]) - datetime.datetime(1980, 1, 6)
        return Decimal(d.days * 86400 + d.seconds) + Decimal(t[5])
    steps = Counter()
    ts = [t for t in times if t is not None]
    for x, y in zip(ts, ts[1:]):
        dt = secs(y) - secs(x)
        if dt > 0:
            steps[dt] += 1
    if not steps:
        return None
    best = max(steps.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return best.quantize(Decimal("0.001"))


def _glo_pairs(contents):
    pairs = set()
    for c in contents:
        for m in re.finditer(r"R([ \d]\d)\s+([+-]?\d{1,2})(?!\d)", c[3:60]):
            pairs.add(("R%02d" % int(m.group(1)), int(m.group(2))))
    return pairs


def _obs_regenerated(f, a, b, report, tv, repaired):
    """Checks for records the converter regenerates: only what can be checked."""
    p = []
    rin, rout = a.recs(f), b.recs(f)
    data_out = [e for e in b.epochs if e.flag in (0, 1) and e.time is not None]
    if f in ("TIME OF FIRST OBS", "TIME OF LAST OBS"):
        if rin and data_out and not rout:
            p.append(f"header {f} dropped")
        if rin and rout and f not in repaired and "TIME SYSTEM" not in " ".join(
                r.get("rule", "") for r in report.get("repairs", []) or []).replace("-", " "):
            ti, to = rin[0][48:51].strip(), rout[0][48:51].strip()
            # QZS, IRN and GAL time the target cannot name are aligned with GPS time: written
            # GPS, reported as an assumption (BDT inputs are shifted before comparison: compare)
            relabel = ti in ("QZS", "IRN", "GAL") and to == "GPS" and ti not in TIME_SYSTEMS_IN(tv) and any(
                x["category"] == "time-system" and x["detail"] == f"{ti}->GPS" for x in report.get("assumptions", []) or [])
            if ti and ti != to and not relabel:
                p.append(f"header {f}: time system {ti!r} in the input, {to!r} in the output")
            if not ti and to:
                ok = to == _TSYS_DEFAULT.get(a.single) and len({s[0] for e in a.epochs for s in e.sats}) <= 1
                ok = ok or any(x["category"] == "time-system" and x["detail"] == to
                               for x in report.get("assumptions", []) or [])
                if not ok:
                    p.append(f"header {f}: output sets time system {to!r}, the input has none and "
                             "no time-system assumption is reported")
    elif f == "INTERVAL":
        if rin and not rout and f not in repaired:
            p.append("header INTERVAL dropped")
        elif rin and rout and f not in repaired and _dec(rin[0][:10]) != _dec(rout[0][:10]):
            # epochs left out (each claimed) may change the sampling: then INTERVAL is the
            # output's own, which is checked against the output's epochs (Sol round 22)
            own = _sampling([e.time for e in data_out])
            if not ("OBS.INTERVAL.FROM-KEPT-EPOCHS" in (report.get("rules") or {})
                    and own is not None and own == _dec(rout[0][:10])):
                p.append(f"header INTERVAL {rin[0][:10].strip()} -> {rout[0][:10].strip()} without "
                         f"a repair (output data sampling {own})")
    elif f in ("# OF SATELLITES", "PRN / # OF OBS"):
        # (PRN / # OF OBS has one line per satellite: none when no satellite is left, e.g. a
        # NavIC-only file to 3.02; Sonnet round 24)
        left = any(e.sats for e in b.epochs if e.flag in (0, 1, 6))
        if rin and not rout and (left or f == "# OF SATELLITES"):
            p.append(f"header {f} dropped")
    elif f == "LEAP SECONDS":
        if rin and not rout:
            p.append("header LEAP SECONDS dropped")
        elif rin and rout:
            q, _ = check_leap(rin[0], rout[0], a.version, tv, report)
            p += q
    elif f == "GLONASS SLOT / FRQ #":
        has_r = any(s[0] == "R" for e in b.epochs for s in e.sats)
        if rin and not rout and has_r and "GLONASS SLOT / FRQ #" in OBS_LABELS.get(tv, ()):
            p.append(f"header GLONASS SLOT / FRQ # dropped although RINEX {tv} defines it and the "
                     "output has GLONASS")
        if rin and rout:
            miss = _glo_pairs(rin) - _glo_pairs(rout)
            if miss:
                p.append(f"GLONASS SLOT / FRQ #: input slot/channel pairs missing or changed in the "
                         f"output: {sorted(miss)}")
    elif f == "GLONASS COD/PHS/BIS":
        has_r = any(s[0] == "R" for e in b.epochs for s in e.sats)
        cin = rin[0].strip() if rin else ""
        if cin and not rout and has_r and "3.02" <= tv < "4":
            p.append(f"header GLONASS COD/PHS/BIS {cin!r} dropped for RINEX {tv}")
        if rin and rout and cin and norm(f, rin[0]) != norm(f, rout[0]):
            p.append(f"GLONASS COD/PHS/BIS changed: {rin[0].rstrip()!r} -> {rout[0].rstrip()!r}")
    return p


def _input_counts_repaired(a, report):
    """An input whose # OF SATELLITES or PRN / # OF OBS disagree with its own data gets them
    recomputed, which is a repair the report names (HDR.COUNTS: PLAN section 1 clause 9), for
    every target (Sonnet round 21: RINEX 3 -> 2 corrected them unreported). Inputs whose
    counts fit the data under either reading of flag-6 records are not required to have one."""
    nsat, rin = a.recs("# OF SATELLITES"), a.recs("PRN / # OF OBS")
    if not (nsat or rin) or a.counts is None or a.types_changed:
        return []
    sats = {s for e in a.epochs for s in e.sats}
    wrong = bool(nsat) and _int(nsat[0][:6]) != len(sats)
    if rin and not wrong:
        listed = set()
        for c in rin:
            s = c[3:6]
            if s.strip():
                listed.add((s[0] if s[0] != " " else a.single) + "%02d" % int(s[1:3]))
        wrong = listed != sats or bool(_check_prn_counts(rin, a))
    if wrong and not any((r.get("rule") or "") == "HDR.COUNTS" for r in report.get("repairs", []) or []):
        return ["the input's # OF SATELLITES / PRN / # OF OBS disagree with its data, and no HDR.COUNTS "
                "repair is reported"]
    return []


def _check_prn_counts(recs, b):
    """PRN / # OF OBS (3X,A1,I2,9I6; continuation 6X,9I6: rinex211.txt Table A1, rinex305.txt
    Table A2) against a recount of the output's non-missing values per type. Epochs with
    flag 6 may or may not be counted (the specs do not say); I6 cannot exceed 999999. From
    3.01 '99999 indicates >= 99999 observations' (rinex301.txt Table A2 l.2157); 2.x and 3.00
    give the actual count."""
    sat_ok = b.version >= "3.01"

    def same(got, want):
        return all(g == w or (sat_ok and g == 99999 and w >= 99999) for g, w in zip(got, want))
    listed = {}
    cur = None
    for c in recs:
        s = c[3:6]
        if s.strip():
            cur = (s[0] if s[0] != " " else b.single) + "%02d" % int(s[1:3])
            listed[cur] = []
        if cur is not None:
            # a blank I6 is a zero count (e.g. a type never observed by this satellite)
            listed[cur] += [_int(c[6 + 6 * k:12 + 6 * k]) or 0 for k in range(9)]
    bad = []
    for sat in listed:
        listed[sat] = listed[sat][:b.ntypes(sat[0])]
    for sat, got in listed.items():
        c01, c6 = b.counts["01"].get(sat, Counter()), b.counts["6"].get(sat, Counter())
        n = len(got)
        w1 = [c01[j] for j in range(n)]
        w2 = [c01[j] + c6[j] for j in range(n)]
        if not (same(got, w1) or same(got, w2)):
            bad.append(f"{sat}: {got} vs recount {w1}")
    return [f"output PRN / # OF OBS disagrees with the output data for {len(bad)} satellites: {bad[:3]}"] if bad else []


def _obs_output_consistency(a, b, report, tv):
    """Records of the output that describe the output's own data."""
    p = []
    data = [e for e in b.epochs if e.flag in (0, 1) and e.time is not None]
    for f, pick in (("TIME OF FIRST OBS", 0), ("TIME OF LAST OBS", -1)):
        r = b.recs(f)
        if r and data:
            t = _time_of(r[0])
            want = _floor7(data[pick].time)
            if t is None or _floor7(t) != want:
                p.append(f"output {f} {r[0][:43].strip()!r} is not the output's "
                         f"{'first' if pick == 0 else 'last'} epoch {want}")
    if not b.recs("TIME OF FIRST OBS") and data:
        p.append("output has no TIME OF FIRST OBS (mandatory in every version)")
    r = b.recs("# OF SATELLITES")
    sats = {s for e in b.epochs if e.flag in (0, 1, 6) for s in e.sats}
    if r and _int(r[0][:6]) != len(sats):
        p.append(f"output # OF SATELLITES {r[0][:6].strip()} but the output data hold {len(sats)} satellites")
    r = b.recs("PRN / # OF OBS")
    if r:
        listed = set()
        for c in r:
            s = c[3:6]
            if s.strip():
                listed.add((s[0] if s[0] != " " else b.single) + "%02d" % int(s[1:3]))
        if listed != sats:
            p.append(f"output PRN / # OF OBS lists {len(listed)} satellites, the output data hold "
                     f"{len(sats)} (differ: {sorted(listed ^ sats)[:5]})")
        if b.counts is not None and not b.types_changed:
            p += _check_prn_counts(r, b)
    # GLONASS channels the input did not give must come from a reported companion
    rout, rin = b.recs("GLONASS SLOT / FRQ #"), a.recs("GLONASS SLOT / FRQ #")
    # channels the input's own flag-4 events give are the file's too (Sol round 22), from
    # that event on (rinex305.txt section 6.5 p.42): for the header, only those of
    # satellites with no record before the event (Sol round 23: a later channel was applied
    # to earlier observations)
    have = _glo_pairs(rin)
    seen = set()
    for e in a.epochs:
        if 2 <= e.flag <= 5:
            have |= {(s, k) for s, k in _glo_pairs([c for lab, c in e.recs if lab == "GLONASS SLOT / FRQ #"])
                     if s not in seen}
        else:
            seen.update(e.sats)
    if rout:
        new = _glo_pairs(rout) - have
        told = {x["detail"] for x in report.get("assumptions", []) or [] if x["category"] == "glonass-fcn"}
        bad = [f"{s}={k}" for s, k in sorted(new) if f"{s}={k}" not in told]
        if bad:
            p.append(f"output GLONASS SLOT / FRQ # has channels neither in the input nor in a "
                     f"glonass-fcn assumption: {bad[:5]}")
    rout = b.recs("GLONASS COD/PHS/BIS")
    if rout and rout[0].strip() and not a.recs("GLONASS COD/PHS/BIS"):
        p.append(f"output GLONASS COD/PHS/BIS {rout[0].rstrip()!r} has values the input does not have")
    return p


def _own_defined(head, sv, tv, labels, known, report, kind, p):
    """The labels the target defines, and in a same-version conversion the file's own records
    another version defines (a DOI in a 3.05 file), carried as written with rule
    <kind>.HDR.NONSTANDARD-CARRIED (as compare_obs_meta does; Sol round 16)."""
    defined = labels.get(tv, set())
    if sv != tv:
        return defined
    own = {r[0] for r in head if r[0] in known} - defined
    if own and not (report.get("rules") or {}).get(f"{kind}.HDR.NONSTANDARD-CARRIED"):
        p.append(f"header: {sorted(own)} carried in a same-version conversion without rule "
                 f"{kind}.HDR.NONSTANDARD-CARRIED in the report")
    return defined | own


def generic_header(hin, houts, tv, defined, known, regen, report, repaired, where="header"):
    """hin: [(label, content, line)]; houts: list of such lists (one per output file).
    Records the target defines must survive with their content (in some output), records
    it does not define must be claimed header-record-not-representable:<LABEL> and absent
    from every output, COMMENT lines must all be kept in order."""
    p = []
    gin = defaultdict(list)
    for lab, c, ln in hin:
        gin[_family(lab)].append((lab, c))
    gouts = []
    for h in houts:
        g = defaultdict(list)
        for lab, c, ln in h:
            g[_family(lab)].append((lab, c))
        gouts.append(g)
    cin = [c.rstrip() for lab, c in gin.get("COMMENT", [])]
    if cin and not any(_subsequence(cin, [c.rstrip() for lab, c in g.get("COMMENT", [])]) for g in gouts):
        allout = Counter(c.rstrip() for g in gouts for lab, c in g.get("COMMENT", []))
        lost = list((Counter(cin) - allout).elements())
        p.append(f"{where}: COMMENT lines lost or reordered" + (f": {lost[:3]}" if lost else " (order changed)"))
    claims = {}
    for k, e in _losses(report).items():
        if k.startswith("header-record-not-representable:"):
            claims[k.split(":", 1)[1]] = e["count"]
    for f, lst in gin.items():
        if f in ("COMMENT", "END OF HEADER") or f in regen:
            continue
        raw = lst[0][0]
        if raw in known and raw not in defined:
            if any(g.get(f) for g in gouts):
                p.append(f"{where}: output keeps {f}, which RINEX {tv} does not define")
            if claims.get(f, 0) != len(lst) and not any(k.startswith(f + ":") for k in claims):
                p.append(f"{where}: {len(lst)} {f} records dropped (RINEX {tv} does not define it), "
                         f"report claims {claims.get(f, 0)} header-record-not-representable:{f}")
            continue
        if f in repaired:
            continue
        a_n = [norm(f, c) for lab, c in lst]
        if not any([norm(f, c) for lab, c in g.get(f, [])] == a_n for g in gouts):
            got = [[norm(f, c) for lab, c in g.get(f, [])] for g in gouts]
            p.append(f"{where}: record {f} did not survive: input {a_n}, output {got if len(got) > 1 else got[0]}")
    for g in gouts:
        for f, lst in g.items():
            if f in gin or f in regen or f in ("COMMENT", "END OF HEADER"):
                continue
            if f == "APPROX POSITION XYZ" and len(lst) == 1 and any(
                    a.get("category") == "approx-position" and a.get("source") == "user"
                    and a.get("detail", "").split() == lst[0][1].split()
                    for a in report.get("assumptions", []) or []):
                continue          # the user's value (clause 8 source 1), reported as such
            if f == "APPROX POSITION XYZ" and len(lst) == 1 and lst[0][1][:42].split() == ["0.0000"] * 3 \
                    and any(a.get("category") == "approx-position" and a.get("source") == "teqc-convention"
                            for a in report.get("assumptions", []) or []):
                continue          # --approx-position-zero: teqc's placeholder, reported as such
            p.append(f"{where}: output adds record {f} {[c.rstrip() for lab, c in lst][:2]} not in the input")
        for f, lst in g.items():
            raw = lst[0][0]
            if raw in known and raw not in defined and raw not in {lab for lab, c, ln in hin}:
                p.append(f"{where}: output writes {raw}, which RINEX {tv} does not define")
    for lab, n in claims.items():
        # 'LABEL' or 'LABEL:<detail>' (labels may themselves contain ':')
        f = lab
        if lab not in known and ":" in lab and lab.rsplit(":", 1)[0] in known:
            f = lab.rsplit(":", 1)[0]
        sub = f != lab
        f = _family(f)
        nin = len(gin.get(f, []))
        nout = max([len(g.get(f, [])) for g in gouts] or [0])
        if nin == 0 or nout >= nin:
            p.append(f"report claims header-record-not-representable:{lab}, but the input has {nin} "
                     f"and the output {nout} such records")
        elif f not in regen and not sub and n != nin - nout:
            p.append(f"report claims {n} header-record-not-representable:{lab}, {nin - nout} records "
                     "are missing")
        if f not in regen and f in defined and not sub:
            p.append(f"report claims header-record-not-representable:{lab}, but RINEX {tv} defines {f}")
    return p


# Records a converter interprets, and the version that defines each first (rinex300.txt Table
# A1: SYS / SCALE FACTOR; rinex301.txt Table A1: SYS / PHASE SHIFTS, GLONASS SLOT / FRQ #;
# rinex302.txt Table A2: GLONASS COD/PHS/BIS). In an older version such a record means nothing
# to its readers: it must not be interpreted (Sol round 16).
_INTERPRETED_SINCE = {"SYS / SCALE FACTOR": "3.00", "SYS / PHASE SHIFT": "3.01", "GLONASS SLOT / FRQ #": "3.01",
                      "GLONASS COD/PHS/BIS": "3.02"}


def TIME_SYSTEMS_IN(version):
    """Time systems TIME OF FIRST OBS allows: GPS, GLO in 2.10 (rinex210.txt), + GAL in
    2.11-3.01 (rinex211.txt Table A1 l.1185, rinex301.txt Table A1 l.2035), + QZS, BDT in 3.02
    (rinex302.txt Table A2), + IRN from 3.03 (rinex303.txt l.2942, rinex304.txt l.3228)."""
    if version < "2.11":
        return {"GPS", "GLO"}
    if version < "3.02":
        return {"GPS", "GLO", "GAL"}
    if version < "3.03":
        return {"GPS", "GLO", "GAL", "QZS", "BDT"}
    return {"GPS", "GLO", "GAL", "QZS", "BDT", "IRN"}


def _is_foreign(label, version):
    since = _INTERPRETED_SINCE.get(_family(label))
    return since is not None and version < since


def _without_foreign(f, version):
    head = [h for h in f.header if not _is_foreign(h[0], version)]
    eps = [ObsEpoch(e.time, e.flag, e.sats, e.clock, [x for x in e.recs if not _is_foreign(x[0], version)], e.line)
           if 2 <= e.flag <= 5 else e for e in f.epochs]
    g = copy.copy(f)
    g.header, g.epochs = head, eps
    return g


def _foreign_records(a, b, tv, report):
    """A foreign interpreted record (above) is carried as written to its own version and
    claimed header-/event-record-foreign-dropped:<LABEL> elsewhere, one per record line."""
    p = []
    sv = a.version
    losses = _losses(report)
    hin = [(lab, c.rstrip()) for lab, c, ln in a.header if _is_foreign(lab, sv)]
    ein = [(lab, c.rstrip()) for e in a.epochs if 2 <= e.flag <= 5 for lab, c in e.recs if _is_foreign(lab, sv)]
    for where, recs, outs in (("header", hin, [(lab, c.rstrip()) for lab, c, ln in b.header]),
                              ("event", ein, [(lab, c.rstrip()) for e in b.epochs if 2 <= e.flag <= 5
                                              for lab, c in e.recs])):
        want = Counter(_family(lab) for lab, c in recs) if sv != tv else Counter()
        got = Counter({k.split(":", 1)[1]: e["count"] for k, e in losses.items()
                       if k.startswith(f"{where}-record-foreign-dropped:")})
        if +want != +got:
            p.append(f"{where} records foreign to RINEX {sv} {dict(want)} dropped, report claims {dict(got)} "
                     f"{where}-record-foreign-dropped")
        if sv == tv and +(Counter(recs) - Counter(outs)):
            p.append(f"{where} records foreign to RINEX {sv} {list((Counter(recs) - Counter(outs)).elements())[:2]} "
                     "not carried as written in a same-version conversion")
    return p


def compare_obs_meta(inp, out, report, type_emptied=None):
    """Receiver clocks, epochs, events and header records of an observation conversion."""
    a, b = parse_obs(inp, count=True), parse_obs(out, count=True)
    tv = report.get("target_version") or b.version
    p = []
    if b.version != tv:
        p.append(f"output RINEX VERSION / TYPE says {b.version}, the target is {tv}")
    p += _input_counts_repaired(a, report)
    # interpreted records the source's version does not define are checked on their own; the
    # checks below see both files without them
    p += _foreign_records(a, b, tv, report)
    # (the output's own: carried ones in a same-version conversion; elsewhere it has the
    # target's generated records only)
    a, b = _without_foreign(a, a.version), (_without_foreign(b, a.version) if a.version == tv else b)
    q, a = _sys_records(a, b, tv, report)
    p += q
    p += _epoch_checks(a, b, report, tv, type_emptied)
    dropped = Counter()                   # (sys, code) of SYS / PHASE SHIFT entries left out
    p += _event_checks(a, b, report, tv, dropped)
    repaired = repaired_labels(report, a.header, ALL_OBS_LABELS)
    defined = OBS_LABELS.get(tv, set())
    if a.version == tv:
        # the source's own version: a record another version defines (DOI in a 3.05 file)
        # is the file's own non-standard record, carried as written, as non-standard codes
        # are; the report says so (rule OBS.HDR.NONSTANDARD-CARRIED)
        own = {lab for lab, c, ln in a.header
               if lab in ALL_OBS_LABELS and _family(lab) not in OBS_REGEN} - defined
        if own and not report.get("rules", {}).get("OBS.HDR.NONSTANDARD-CARRIED"):
            p.append(f"header: {sorted(own)} carried in a same-version conversion without rule "
                     "OBS.HDR.NONSTANDARD-CARRIED in the report")
        defined = defined | own
    p += generic_header(a.header, [b.header], tv, defined, ALL_OBS_LABELS, OBS_REGEN, report, repaired)
    ein = phase_entries([(lab, c) for lab, c, ln in a.header])
    out_sys = output_systems(b)
    p += phase_compare(ein, phase_entries([(lab, c) for lab, c, ln in b.header]), a.version, tv,
                       output_phase_codes(b) if tv >= "3" else {}, report, "header",
                       out_systems=out_sys, dropped=dropped)
    p += phase_claims(ein, a.version, tv, out_sys, dropped, report)
    p += _phasecenter_checks(a, b, tv, report)
    p += glonass_claims(a, b, tv, report)
    for f in {_family(lab) for lab, c, ln in a.header} & OBS_REGEN:
        p += _obs_regenerated(f, a, b, report, tv, repaired)
    p += _obs_output_consistency(a, b, report, tv)
    if not b.recs("PGM / RUN BY / DATE"):
        p.append("output has no PGM / RUN BY / DATE")
    # LEAP SECONDS inside events (flag 4 may carry any header record): the same field rules as
    # the header's, paired in order
    # within each event (a value holds until a later event changes it: rinex305.txt section
    # 6.5 p.42, so records may not change events)
    n_dropped = 0
    pairs, emptied, extra = event_pairs(a, b, tv)
    scopes = [(ei, eo) for ei, eo in pairs] + [(ei, None) for ei in emptied] + [(None, eo) for eo in extra]
    for ei, eo in scopes:
        li = [c for lab, c in (ei.recs if ei else []) if lab == "LEAP SECONDS"]
        lo = [c for lab, c in (eo.recs if eo else []) if lab == "LEAP SECONDS"]
        if len(li) != len(lo):
            e = ei or eo
            p.append(f"event at {e.time}: {len(li)} LEAP SECONDS records in the input, {len(lo)} in the output")
        for ci, co in zip(li, lo):
            q, d = check_leap(ci, co, a.version, tv, report, where=f"event at {ei.time} LEAP SECONDS")
            p += q
            n_dropped += d
    # the claim counts the records (header and events) that lost fields (Sol round 13: a count
    # of 999 passed)
    rin, rout = a.recs("LEAP SECONDS"), b.recs("LEAP SECONDS")
    n_dropped += sum(check_leap(ci, co, a.version, tv, report)[1] for ci, co in zip(rin, rout))
    c = _count(report, "header-field-not-representable:LEAP SECONDS")
    if c != n_dropped:
        p.append(f"{n_dropped} LEAP SECONDS records lost fields, report claims {c} "
                 "header-field-not-representable:LEAP SECONDS")
    return p


# ---------------------------------------------------------------------------
# navigation files: corrections
# ---------------------------------------------------------------------------
# digits of the mantissa of each correction field (Fortran Dw.d = 0.d...d):
#   rinex211.txt Table A3: ION ALPHA/BETA 4D12.4, DELTA-UTC 2D19.12; Table A10/A15:
#   CORR TO SYSTEM TIME D19.12, D-UTC 2D19.12; rinex305.txt Table A5: IONOSPHERIC CORR
#   4D12.4, TIME SYSTEM CORR a0 D17.10, a1 D16.9; rinex_4.02.txt Tables A33-A38: E19.12.
def _item(kind, fam, src, **kw):
    d = {"kind": kind, "fam": fam, "src": src}
    d.update(kw)
    return d


def _trim(vals):
    vals = list(vals)
    while vals and vals[-1] is None:
        vals.pop()
    return vals


def _body_values(body):
    """A RINEX 4 STO/ION/EOP record body as its values, for --dedupe identity: the same record
    with D or E exponents, or other digits, is the same (Sol round 18); blank separator lines
    are no part of it (Sol round 12). Text that is no number stays text."""
    out = []
    for x in body:
        if not x.strip():
            continue
        # numbers may touch ('-5.0E-01-1.5E+00'), so read them by pattern, not by blanks
        for tok in re.findall(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[Ee][+-]?\d+)?|[+-]?\d+|[^\s\d.+-]\S*",
                              x.replace("D", "E").replace("d", "e")):
            try:
                out.append(Decimal(tok).normalize())
            except InvalidOperation:
                out.append(tok)
    return tuple(out)


def nav_corrections(payload):
    """(version, header, items, eop) with eop the (system, message, identity) of every v4 EOP record and items:
    ION  fam ('KLOB', sys) parts {'A': alpha0-3, 'B': beta0-3}; ('NEQG', 'E') parts {'N': ai0-2}
         plus 'flags'; other models fam ('V4', sys, msg, sub) or ('V3', type) part 'X';
    STO  fam = 4-letter code (GPGA read as GAGP, rinex305.txt Table A5 note), a0, a1, a2,
         T, W or a v4 reference epoch, with the fields the record has ('has')."""
    L = _lines(payload)
    v = _vstr(L[0])
    head, end = _header(L)
    ftype = L[0][20:21]
    items = []
    eop = []

    def v3_content(c):
        """A CORR TO SYSTEM TIME holding TIME SYSTEM CORR content (a time-system code in
        columns 1-4, rinex305.txt Table A5): a writer's mix-up, read as TIME SYSTEM CORR."""
        return bool(re.fullmatch(r"[A-Z]{4}", c[:4]))
    # The labels are read in any version: a correction record under another version's label
    # still holds data (Sonnet round 15: one was dropped unreported). RINEX 2 labels first.
    if True:
        alpha = beta = None
        for lab, c, ln in head:
            if lab == "ION ALPHA":
                alpha = [_dec(c[2 + 12 * k:14 + 12 * k]) for k in range(4)]
            elif lab == "ION BETA":
                beta = [_dec(c[2 + 12 * k:14 + 12 * k]) for k in range(4)]
            elif lab == "DELTA-UTC: A0,A1,T,W":
                items.append(_item("STO", "GPUT", f"{lab} (line {ln})", a0=_dec(c[3:22]), a1=_dec(c[22:41]),
                                   T=_int(c[41:50]), W=_int(c[50:59]), has={"a0", "a1", "TW"},
                                   prec={"a0": 12, "a1": 12}, label=lab))
            elif lab == "CORR TO SYSTEM TIME" and not v3_content(c):
                code = "GLUT" if ftype == "G" or (v >= "3" and L[0][40:41] == "R") else "SBUT"
                items.append(_item("STO", code, f"{lab} (line {ln})", a0=_dec(c[21:40]),
                                   ref=(_int(c[0:6]), _int(c[6:12]), _int(c[12:18])), has={"a0"},
                                   prec={"a0": 12}, label=lab))
            elif lab == "D-UTC A0,A1,T,W,S,U":
                # 2D19.12,I7,I5,1X,A5,1X,I2: ..., S (EGNOS, WAAS, MSAS), U (rinex211.txt Table A15)
                items.append(_item("STO", "SBUT", f"{lab} (line {ln})", a0=_dec(c[0:19]), a1=_dec(c[19:38]),
                                   T=_int(c[38:45]), W=_int(c[45:50]), sat=c[51:56].strip(), utc=_int(c[57:59]),
                                   has={"a0", "a1", "TW"},
                                   prec={"a0": 12, "a1": 12}, label=lab))
        if alpha or beta:
            parts = {}
            if alpha:
                parts["A"] = alpha
            if beta:
                parts["B"] = beta
            items.append(_item("ION", ("KLOB", "G"), "ION ALPHA/BETA", parts=parts, prec=4, label="ION"))
    if True:                              # RINEX 3 labels
        pending = {}
        for lab, c, ln in head:
            if lab == "IONOSPHERIC CORR":
                typ = c[0:4].strip()
                vals = [_dec(c[5 + 12 * k:17 + 12 * k]) for k in range(4)]
                # 1X,A1 time mark and 1X,I2 SV ID from 3.02 (rinex305.txt Table A5 p.64-65)
                marks = {"tmark": c[54:55].strip(), "svid": c[56:58].strip()}
                if typ == "GAL":
                    # the fourth value: "zero" in 3.00-3.02 (rinex302.txt l.3289), a placeholder,
                    # not disturbance flags; "Blank" from 3.03
                    flags = None if v < "3.03" and not vals[3] else vals[3]
                    items.append(_item("ION", ("NEQG", "E"), f"IONOSPHERIC CORR GAL (line {ln})",
                                       parts={"N": vals[:3]}, flags=flags, has_flags=False, prec=4,
                                       label="IONOSPHERIC CORR", **marks))
                elif len(typ) == 4 and typ[:3] in ("GPS", "QZS", "BDS", "IRN") and typ[3] in "AB":
                    s = {"GPS": "G", "QZS": "J", "BDS": "C", "IRN": "I"}[typ[:3]]
                    half = typ[3]
                    # alpha and beta of one message share the time mark (1X,A1 at col 54) and
                    # SV ID (1X,I2 at 56:58), rinex305.txt Table A5 p.64-65
                    # (SV ID I2: '01' and ' 1' are one satellite)
                    pk = (s, c[54:55].strip(), c[56:58].strip().lstrip("0"))
                    it = pending.get(pk)
                    if it is None or half in it["parts"]:
                        it = _item("ION", ("KLOB", s), f"IONOSPHERIC CORR {typ} (line {ln})", parts={},
                                   prec=4, label="IONOSPHERIC CORR", **marks)
                        pending[pk] = it
                        items.append(it)
                    it["parts"][half] = vals
                else:
                    items.append(_item("ION", ("V3", typ), f"IONOSPHERIC CORR {typ} (line {ln})",
                                       parts={"X": vals}, prec=4, label="IONOSPHERIC CORR", **marks))
            elif lab == "TIME SYSTEM CORR" or (lab == "CORR TO SYSTEM TIME" and v3_content(c)):
                code = c[0:4].strip()
                code = "GAGP" if code == "GPGA" else code
                a0, a1 = _dec(c[5:22]), _dec(c[22:38])
                # some writers put the values off their A4,1X,D17.10,D16.9,1X,I6,1X,I4 columns
                # (e.g. cnvtToRINEX 3.09: D19.12 from column 9): read them in order instead
                off = (a0 is None and c[5:22].strip()) or (a1 is None and c[22:38].strip()) or (
                    _int(c[38:45]) is None and c[38:45].strip())
                if off:
                    nums = re.findall(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[DdEe][+-]?\d+)?|[+-]?\d+", c[4:60])
                    a0, a1 = (_dec(nums[0]) if nums else None), (_dec(nums[1]) if len(nums) > 1 else None)
                    T = _int(nums[2]) if len(nums) > 2 else None
                    W = _int(nums[3]) if len(nums) > 3 else None
                else:
                    T, W = _int(c[38:45]), _int(c[45:50])
                # U, the UTC identifier: 1X,A5,1X,I2 after W (rinex305.txt Table A5); a record
                # with a0 and a1 only (BOR100POL SN) has no reference time
                items.append(_item("STO", code, f"{lab} {code} (line {ln})", a0=a0, a1=a1, T=T, W=W,
                                   utc=None if off else _int(c[57:59]), sat="" if off else c[51:56].strip(),
                                   has={"a0", "a1"} | ({"TW"} if T is not None or W is not None else set()),
                                   prec={"a0": 10, "a1": 9}, label="TIME SYSTEM CORR"))
    if v >= "4":
        i = end + 1
        n = len(L)
        while i < n:
            l = L[i]
            if not l.startswith(">"):
                i += 1
                continue
            l = l.ljust(19)
            kind, sysc, prn, msg, sub = l[2:5], l[6:7], l[7:9].strip(), l[10:14].strip(), l[15:19].strip()
            body = []
            j = i + 1
            while j < n and not L[j].startswith(">"):
                body.append(L[j].ljust(80))
                j += 1
            line = i + 1
            i = j
            if kind == "EOP":
                # (system, message, identity): the identity is what --dedupe compares
                eop.append((sysc, msg, (sysc, prn, msg, sub, _body_values(body))))
                continue
            if kind not in ("STO", "ION") or not body:
                continue
            b0 = body[0]
            try:
                t = (int(b0[4:8]), int(b0[9:11]), int(b0[12:14]), int(b0[15:17]), int(b0[18:20]),
                     Decimal(b0[21:23]))
            except ValueError:
                t = None
            # (blank lines left out: a separator after a record, repaired NAV.BLANKLINE, is
            # not part of it: Sol round 12)
            ident = (kind, sysc, prn, msg, sub, _body_values(body))
            if kind == "STO":
                code = b0[24:42].strip()
                code = "GAGP" if code == "GPGA" else code
                b1 = body[1] if len(body) > 1 else " " * 80
                # 4X,I4,5(1X,I2.2), then 1X,A18 each: code, SBAS ID, UTC ID (rinex_4.02.txt Table A33)
                items.append(_item("STO", code, f"> STO {sysc}{prn} {msg} {code} (line {line})",
                                   utc=b0[62:80].strip() or None, sat=(sysc + prn).strip() if prn else "",
                                   sbas=b0[43:61].strip(),
                                   a0=_dec(b1[23:42]), a1=_dec(b1[42:61]), a2=_dec(b1[61:80]), epoch=t,
                                   ttm=_dec(b1[4:23]), has={"a0", "a1", "a2", "epoch"},
                                   prec={"a0": 12, "a1": 12, "a2": 12}, label="STO", sm=(sysc, msg),
                                   ident=ident))
                continue
            vals = [_dec(b0[23 + 19 * k:42 + 19 * k]) for k in range(3)]
            for bl in body[1:]:
                vals += [_dec(bl[4 + 19 * k:23 + 19 * k]) for k in range(4)]
            vals = _trim(vals)
            src = f"> ION {sysc}{prn} {msg} {sub} (line {line})".replace("  ", " ")
            # rinex_4.02.txt Table A35 (Klobuchar: G/J/I LNAV, C D1D2, G/J CNVX), A36 (NeQuick-G:
            # E IFNV), A37 (BDGIM: C CNVX), A38 (NavIC L1NV KLOB)
            if (msg == "LNAV" and sysc in "GJI") or (msg == "D1D2" and sysc == "C") or (
                    msg == "CNVX" and sysc in "GJ"):
                vals = (vals + [None] * 8)[:8]
                parts = {}
                if any(x is not None for x in vals[:4]):
                    parts["A"] = vals[:4]
                if any(x is not None for x in vals[4:8]):
                    parts["B"] = vals[4:8]
                items.append(_item("ION", ("KLOB", sysc), src, parts=parts, prec=12, label="ION", sm=(sysc, msg),
                                   ident=ident, epoch=t, prn=prn))
            elif msg == "IFNV" and sysc == "E":
                vals = (vals + [None] * 4)[:4]
                items.append(_item("ION", ("NEQG", "E"), src, parts={"N": vals[:3]}, flags=vals[3],
                                   has_flags=True, prec=12, label="ION", sm=(sysc, msg), ident=ident,
                                   epoch=t, prn=prn))
            else:
                items.append(_item("ION", ("V4", sysc, msg, sub), src, parts={"X": vals}, prec=12, label="ION",
                                   sm=(sysc, msg), ident=ident, epoch=t, prn=prn))
    for it in items:
        it.setdefault("sm", None)
    return v, head, items, eop


def _close(vin, vout, n):
    """'eq', 'rounded' (vout is vin rounded to n mantissa digits) or 'diff'."""
    if vin is None or vout is None:
        if vin is None and vout is None:
            return "eq"
        return "diff"
    if vin == vout:
        return "eq"
    if vin == 0 or n is None:
        return "diff"
    tol = Decimal(5).scaleb(vin.adjusted() - n)
    if abs(vin - vout) <= tol and len(vout.normalize().as_tuple().digits) <= n:
        return "rounded"
    return "diff"


def _ion_slot(it):
    """(model, system, time mark, SV) of an ionospheric item: a RINEX 3.02+ header record's
    1X,A1 mark and 1X,I2 SV ID (rinex305.txt Table A5), or what a RINEX 4 record gives them:
    the transmission hour as A-X and the satellite number."""
    if it.get("epoch") is not None:
        mark = chr(ord("A") + it["epoch"][3])
        sv = (it.get("prn") or "").lstrip("0")
    else:
        mark, sv = it.get("tmark") or "", (it.get("svid") or "").lstrip("0")
    return (it["fam"], mark, sv)


def _ion_sys(it):
    """System of an ionospheric item; '?' for an unknown RINEX 3 type (no system to name)."""
    return "?" if it["fam"][0] == "V3" else it["fam"][1]


def _match_ion(i, o):
    """(ok, n_rounded, problems-if-matched) of input ION item i against output item o."""
    if i["fam"] != o["fam"]:
        return False, 0, []
    rounded = 0
    for part, vin in i["parts"].items():
        vout = o["parts"].get(part)
        if vout is None:
            return False, 0, []
        vin = list(vin) + [None] * (len(vout) - len(vin))
        vout = list(vout) + [None] * (len(vin) - len(vout))
        for x, y in zip(vin, vout):
            r = _close(x, y, o["prec"])
            if r == "diff":
                return False, 0, []
            rounded += r == "rounded"
    for part in o["parts"]:
        if part not in i["parts"] and any(x is not None for x in o["parts"][part]):
            return False, 0, []
    return True, rounded, []


def _match_sto(i, o):
    """(ok, n_rounded, field notes) of input STO item i against output item o; field notes are
    ('lost', field) for a non-zero field the output record has no room for."""
    if i["fam"] != o["fam"]:
        return False, 0, []
    rounded = 0
    notes = []
    for f in ("a0", "a1", "a2"):
        if f in i["has"] and f in o["has"]:
            r = _close(i.get(f), o.get(f), o["prec"].get(f))
            if r == "diff":
                # a blank field read as missing on one side and zero on the other is one value
                if not ({i.get(f), o.get(f)} <= {None, Decimal(0)}):
                    return False, 0, []
            rounded += r == "rounded"
        elif f in i["has"] and i.get(f) not in (None, 0):
            notes.append(("lost", f))
        elif f in o["has"] and f not in i["has"] and o.get(f) not in (None, 0):
            return False, 0, []
    code = i["fam"]
    wt_i = (i["W"], i["T"]) if "TW" in i["has"] else _ref_week(i.get("epoch"), code) if "epoch" in i["has"] else None
    wt_o = (o["W"], o["T"]) if "TW" in o["has"] else _ref_week(o.get("epoch"), code) if "epoch" in o["has"] else None
    if "epoch" in i["has"] and "epoch" in o["has"]:
        if i.get("epoch") != o.get("epoch"):
            notes.append(("ref", f"{i.get('epoch')} -> {o.get('epoch')}"))
    elif wt_i is not None and wt_o is not None and code[:2] != "GL" and tuple(wt_i) != tuple(wt_o):
        notes.append(("ref", f"(W, T) {wt_i} -> {wt_o}"))
    return True, rounded, notes


# RINEX 3 UTC identifier numbers (rinex305.txt Table A5: 1=UTC(NIST), 2=UTC(USNO), 3=UTC(SU),
# 4=UTC(BIPM), 5=UTC(Europe Lab), 6=UTC(CRL), 7=UTC(NTSC)) of the RINEX 4 UTC IDs
# (rinex_4.02.txt section 5.4.9, Table 27). Two are readings, not names: UTC(CRL) is the
# former name of UTC(NICT) (the CRL became part of NICT in 2004), and UTCGAL, Galileo's UTC,
# is taken as the "Europe Lab" entry. UTC(NPLI), UTCIRN and UTC(OP) have no number.
V3_UTC_NUMBER = {"UTC(NIST)": 1, "UTC(USNO)": 2, "UTC(SU)": 3, "UTC(BIPM)": 4, "UTCGAL": 5,
                 "UTC(NICT)": 6, "UTC(NTSC)": 7}


_IDENT_CLAIMS = ("SBAS-ID:", "STO-SAT:", "DELTA-UTC:UTC-ID:", "D-UTC:UTC-ID:", "TIME SYSTEM CORR:UTC-ID:",
                 "ION-TTM:", "ION-SAT:")
_CODE_SYS = {"GP": "G", "GL": "R", "GA": "E", "BD": "C", "QZ": "J", "IR": "I", "SB": "S"}
# RINEX 3 UTC numbers as RINEX 4 UTC IDs (the reading of V3_UTC_NUMBER, the other way):
# Galileo's 'Europe Lab' is UTCGAL; for another system no 4.02 ID names it
_V4_UTC_NAME = {1: "UTC(NIST)", 2: "UTC(USNO)", 3: "UTC(SU)", 4: "UTC(BIPM)", 5: "UTC(Europe Lab)",
                6: "UTC(NICT)", 7: "UTC(NTSC)"}


def _sat_or_provider(field):
    """(satellite, provider) of a 2.11 D-UTC / RINEX 3 TIME SYSTEM CORR 1X,A5,1X field: a
    satellite id ('G10', 'Snn' for the SBAS satellite broadcasting MT12) or a provider name
    'derived from MT17' (EGNOS, WAAS, MSAS) (rinex211.txt Table A15, rinex305.txt Table A5)."""
    f = (field or "").strip()
    return (f, "") if re.fullmatch(r"[A-Z]\d\d", f) else ("", f)


def _ion_fields(i, o, tv, lost):
    """The transmission time and satellite of an ionospheric record. RINEX 4 ION records carry
    the transmission epoch and satellite (rinex_4.02.txt Table A35); 3.02+ IONOSPHERIC CORR
    keeps the hour as a time mark A-X and the PRN as SV ID (rinex305.txt Table A5 p.64-65);
    3.00/3.01 and RINEX 2 ION ALPHA/BETA keep neither. What has no room is counted under its
    claim name (Sol round 15)."""
    p = []
    s = i["fam"][1] if i["fam"][0] != "V3" else "?"
    marks = "3.02" <= tv < "4"
    if "epoch" in i:                                        # from RINEX 4
        prn = i.get("prn") or ""
        if "tmark" in o:                                    # to RINEX 3
            lost[f"ION-TTM:{s}"] += 1                       # the date, minutes and seconds
            want_tm = chr(ord("A") + i["epoch"][3]) if marks and i.get("epoch") else ""
            want_sv = prn if marks else ""
            if o["tmark"] != want_tm or (o["svid"] or "").lstrip("0") != want_sv.lstrip("0"):
                p.append(f"{i['src']}: time mark / SV ID {o['tmark']!r}/{o['svid']!r} in the output, "
                         f"{want_tm!r}/{want_sv!r} expected")
            if prn and not marks:
                lost[f"ION-SAT:{s}"] += 1
        elif "epoch" not in o:                              # to RINEX 2
            lost[f"ION-TTM:{s}"] += 1
            if prn:
                lost[f"ION-SAT:{s}"] += 1
    elif "tmark" in i:                                      # from RINEX 3
        tm, sv = i["tmark"], i["svid"]
        if "tmark" in o:
            want = (tm, sv) if marks else ("", "")
            if (o["tmark"], o["svid"]) != want:
                p.append(f"{i['src']}: time mark / SV ID {o['tmark']!r}/{o['svid']!r} in the output, {want} expected")
        if not marks and "epoch" not in o:
            if tm:
                lost[f"ION-TTM:{s}"] += 1
            if sv:
                lost[f"ION-SAT:{s}"] += 1
        if "epoch" in o:                                    # to RINEX 4
            if sv and (o.get("prn") or "").lstrip("0") != sv.lstrip("0"):
                p.append(f"{i['src']}: SV ID {sv} written as satellite {o.get('prn')!r}")
            if tm and o.get("epoch") and chr(ord("A") + o["epoch"][3]) != tm:
                p.append(f"{i['src']}: time mark {tm} written as hour {o['epoch'][3]}")
    return p


def _sto_fields(it, o, lost, field_lost):
    """The identifier fields of a time correction written into another record type (one
    carried with its own label keeps them as written). RINEX 4 STO line 1 holds the
    broadcasting satellite, an SBAS ID (A18) and a UTC ID (A18), and line 2 the transmission
    time t_tm (rinex_4.02.txt Table A33), which no RINEX 2/3 header record has. 2.11 D-UTC and
    RINEX 3 TIME SYSTEM CORR hold one 1X,A5,1X field, the SBAS provider (EGNOS, WAAS, MSAS:
    'derived from MT17') or else the broadcasting satellite ('Snn'), and an I2 UTC
    identifier, 1-6 in 2.11 and 1-7 in 3.05 (rinex211.txt Table A15, rinex305.txt Table A5);
    GPS DELTA-UTC holds neither (Table A3; GPS UTC is UTC(USNO)). RINEX 2 CORR TO SYSTEM TIME
    is checked as T-W-S-U. What has no room is counted in `lost` under its claim name
    (Sol round 14: A-SBAS ran into the UTC identifier's columns, t_tm and the satellite
    went unclaimed)."""
    p = []
    olab = o.get("label")
    if it.get("label") == olab:
        return p
    if it.get("ttm") is not None and "ttm" not in o:
        field_lost["ttm"] += 1
    sbas, sat, ui = it.get("sbas") or "", it.get("sat") or "", it.get("utc")
    if "sbas" not in it:                  # RINEX 2/3: one field, a satellite or a provider
        sat, sbas = _sat_or_provider(sat)
    if olab == "STO":
        # to RINEX 4 (Table A33): the satellite of the code's system, the provider for SBUT
        # (another code has no provider field), the UTC number as a UTC ID for 'UT' offsets
        code = it["fam"]
        sysc = _CODE_SYS.get(code[:2], "")
        want_sat = sysc + sat[1:] if sat else ""
        want_sbas = sbas if code == "SBUT" else ""
        if sbas and not want_sbas:
            lost[f"SBAS-ID:{sbas}"] += 1
        want_utc = ""
        if code.endswith("UT") and isinstance(ui, int) and ui:
            want_utc = "UTCGAL" if code == "GAUT" and ui == 5 else _V4_UTC_NAME.get(ui, "")
        got = ((o.get("sat") or ""), (o.get("sbas") or ""), (o.get("utc") or ""))
        if got != (want_sat, want_sbas, want_utc):
            p.append(f"{it['src']}: STO satellite / SBAS ID / UTC ID {got} in the output, "
                     f"{(want_sat, want_sbas, want_utc)} expected")
        return p
    if olab not in ("DELTA-UTC: A0,A1,T,W", "D-UTC A0,A1,T,W,S,U", "TIME SYSTEM CORR"):
        return p                          # CORR TO SYSTEM TIME (checked as T-W-S-U)
    if olab == "DELTA-UTC: A0,A1,T,W":
        want = ""
        if ui not in (None, "", 0, 2, "UTC(USNO)"):
            lost[f"DELTA-UTC:UTC-ID:{ui}"] += 1
    else:
        want = sbas if sbas and len(sbas) <= 5 else (sat if len(sat) <= 5 else "")
        if (o.get("sat") or "") != want:
            p.append(f"{it['src']}: satellite/provider field {o.get('sat')!r} in the output, {want!r} expected")
        top, lab = (6, "D-UTC") if olab == "D-UTC A0,A1,T,W,S,U" else (7, "TIME SYSTEM CORR")
        num = ui if isinstance(ui, int) else (V3_UTC_NUMBER.get(ui) if ui else 0)
        uo = o.get("utc") or 0
        if ui and (not num or num > top):
            lost[f"{lab}:UTC-ID:{ui}"] += 1
            if uo:
                p.append(f"{it['src']}: UTC id {ui} has no number in {lab}, the output writes {uo}")
        elif (num or 0) != uo:
            p.append(f"{it['src']}: UTC id {ui!r} is {num or 0} in {lab}, the output writes {uo}")
    if sbas and sbas != want:
        lost[f"SBAS-ID:{sbas}"] += 1
    if sat and sat != want:
        lost[f"STO-SAT:{it['fam']}"] += 1
    return p


def _leap_gps(c, version, basis=None):
    """[current, future, week, day] of a LEAP SECONDS content in GPS terms (a BDT or BDS
    record, or one with no identifier on a BDS basis, converted: + 14 s, week + 1356, day + 1,
    as check_leap derives it), fields beyond the version's columns left out."""
    a = _leap_fields(c)
    if basis == "BDS" and _bds_count(a):
        a[4] = "BDT"
    if a[4] in _BEIDOU_LEAP:
        a = _to_gps(a)
    n = {6: 1, 24: 4, 27: 4}[_leap_width(version)]
    # (only known fields are reconciled: 0 or blank is "not known"; a day with its week)
    a = [x if x not in (None, 0) else None for x in a[:4]]
    if a[2] is None:
        a[3] = None
    return list(a[:n]) + [None] * (4 - n)


def _merged_header(hin, sv, extra, tv, bases=None):
    """What a --merge output's header must hold of every input's records, and the records
    with no room (claimed merge-header-record-dropped:<LABEL>). COMMENT lines are kept in
    order; LICENSE OF USE and STATION INFORMATION are 'Line(s)' and DOI and REC # / TYPE /
    VERS one record (rinex_4.02.txt Table A7 p.75-76): to RINEX 4 another input's line is
    kept once and a different single record has no room; to RINEX 2/3 each is claimed not
    representable, as the first input's are. LEAP SECONDS is one record: inputs that agree in
    GPS terms combine, one that disagrees has no room. Returns (header, leap, dropped, basis_used) with
    leap the (content, version) the output's record must match (Sol round 17)."""
    head = list(hin)
    have = {(lab, c.rstrip()) for lab, c, ln in head}
    dropped = Counter()
    for msv, mh in extra:
        for lab, c, ln in mh:
            if lab == "COMMENT":
                head.append((lab, c, ln))
            elif lab == "PGM / RUN BY / DATE":
                # one per navigation file (rinex_4.02.txt section 5.2.2: only observation files
                # add PGM lines)
                if (lab, c.rstrip()) not in have:
                    dropped[lab] += 1
            elif lab == "REC # / TYPE / VERS" and tv >= "4":
                continue                          # below
            elif lab in ("LICENSE OF USE", "STATION INFORMATION", "DOI", "REC # / TYPE / VERS"):
                if tv < "4":
                    head.append((lab, c, ln))
                elif (lab, c.rstrip()) in have:
                    continue
                elif lab == "DOI" and any(x[0] == lab for x in head):
                    dropped[lab] += 1
                else:
                    head.append((lab, c, ln))
                    have.add((lab, c.rstrip()))
    if tv >= "4":
        # "Merged navigation files from multiple stations are not to include this header line"
        # (Table A7, REC # / TYPE / VERS note 2): only one receiver record common to every
        # input stays; otherwise each input's is claimed
        recv = [[c.rstrip() for lab, c, ln in h if lab == "REC # / TYPE / VERS"]
                for h in [hin] + [mh for msv, mh in extra]]
        if any(recv) and not (all(len(x) == 1 for x in recv) and len({x[0] for x in recv}) == 1):
            head = [h for h in head if h[0] != "REC # / TYPE / VERS"]
            dropped["REC # / TYPE / VERS"] += sum(len(x) for x in recv)
    # MERGED FILE, "Number of files merged (BNK)" (Table A7; section 6.11): to RINEX 4 each
    # input counts as its own number or 1, a blank number makes it unknown; to RINEX 2/3 every
    # input's record is claimed not representable
    if tv >= "4":
        total = 0
        for h in [hin] + [mh for msv, mh in extra]:
            mf = [c for lab, c, ln in h if lab == "MERGED FILE"]
            if not mf:
                total = None if total is None else total + 1
            elif mf[0][:9].strip().isdigit() and total is not None:
                total += int(mf[0][:9])
            else:
                total = None
        head = [h for h in head if h[0] != "MERGED FILE"] + [
            ("MERGED FILE", f"{total:9d}" if total is not None else "", None)]
    else:
        head += [(lab, c, ln) for msv, mh in extra for lab, c, ln in mh if lab == "MERGED FILE"]
    # bases: each input's leap basis (None, or 'BDS' for a BeiDou-only 3.02 navigation file:
    # rinex302.txt Table A5 p.63), primary first (Sol round 25)
    bases = bases or [None] * (1 + len(extra))
    # (the basis applies to a record without identifier only)
    def eff(c, b):
        return b if not c.ljust(60)[24:27].strip() else None
    recs = ([(c, sv, eff(c, bases[0])) for lab, c, ln in hin if lab == "LEAP SECONDS"]
            + [(c, msv, eff(c, bases[1 + i])) for i, (msv, mh) in enumerate(extra) for lab, c, ln in mh
               if lab == "LEAP SECONDS"])
    basis_used = any(bs == "BDS" and _bds_count(_leap_fields(c)) for c, v, bs in recs)
    best, leap = None, None
    for c, v, bs in recs:
        g = _leap_gps(c, v, bs)
        if all(x is None for x in g):
            continue                              # a blank record says nothing
        if best is None:
            # (a BDS-basis record is written in GPS terms: the merged file is not BeiDou only)
            best, leap = g, ((c, v) if (c, v, bs) == recs[0] and not (bs == "BDS" and _bds_count(_leap_fields(c)))
                             and any(lab == "LEAP SECONDS" for lab, c2, ln in hin) else None)
        elif all(x is None or y is None or x == y for x, y in zip(best, g)):
            if any(x is None and y is not None for x, y in zip(best, g)):
                best, leap = [x if x is not None else y for x, y in zip(best, g)], None
        else:
            dropped["LEAP SECONDS"] += 1
    if best is not None and leap is None:
        leap = ("".join(" " * 6 if x is None else f"{x:6d}" for x in best) + "GPS"
                if any(x is not None for x in best[1:]) else f"{best[0]:6d}", "4.02")
    return ([h for h in head if h[0] != "LEAP SECONDS"] + ([("LEAP SECONDS", leap[0], None)] if leap else []),
            leap, dropped, basis_used)


def _nav_systems(payload):
    """Systems of a RINEX 3 navigation file's records: the satellite letter starting each
    record (rinex305.txt Table A6 'SV / EPOCH / SV CLK': A1,I2.2)."""
    text = payload.decode("latin-1") if isinstance(payload, (bytes, bytearray)) else payload
    body = text.split("END OF HEADER", 1)[-1].split("\n")[1:]
    return {l[0] for l in body if l[:1].isalpha() and l[1:3].strip().isdigit()}


def compare_nav_meta(inp, outs, report, merged=None):
    """Ionospheric / time-system corrections, EOP records, LEAP SECONDS and the other header
    records of a navigation conversion (outs: every output payload; merged: the other inputs
    of a --merge, in order)."""
    p = []
    tv = report.get("target_version")
    sv, hin, iin, eop_in = nav_corrections(inp)
    hin_own = hin                         # the first input's own records (same-version rule)
    merge_drop = Counter()
    leap_sv = sv
    def basis_of(version, payload):
        # 3.02-3.05 BeiDou-only files (a record without identifier: check_leap; rinex302.txt
        # Table A5 p.63, rinex303-305 'When BDS only file ... weeks since 1-Jan-2006')
        return "BDS" if "3.02" <= version < "4" and _nav_systems(payload) == {"C"} else None
    leap_basis = basis_of(sv, inp)
    if merged is not None:
        extra = []
        bases = [leap_basis]
        for m in merged:
            msv, mh, mi, me = nav_corrections(m)
            iin, eop_in = iin + mi, eop_in + me
            extra.append((msv, mh))
            bases.append(basis_of(msv, m))
        hin, leap_rec, merge_drop, basis_used = _merged_header(hin, sv, extra, tv, bases)
        if leap_rec:
            leap_sv = leap_rec[1]
            # the output's record is the primary's as written only if it came from it unchanged
            if leap_rec[1] != sv:
                leap_basis = None
        if basis_used and not any(
                x["category"] == "leap-seconds-basis" for x in report.get("assumptions", []) or []):
            p.append("a merge with a BeiDou-only 3.02 navigation file without a leap-seconds-basis "
                     "BDS assumption")
    c_merge = Counter({k.split(":", 1)[1]: e["count"] for k, e in _losses(report).items()
                       if k.startswith("merge-header-record-dropped:")})
    if +c_merge != +merge_drop:
        p.append(f"merged inputs' records with no room {dict(merge_drop)}, report claims {dict(c_merge)} "
                 "merge-header-record-dropped")
    parsed = [nav_corrections(o) for o in outs]
    iout = [it for x in parsed for it in x[2]]
    eop_out = [sm for x in parsed for sm in x[3]]
    losses = _losses(report)
    # a RINEX 4 record whose message type the target lacks (e.g. 4.02 L1NV/LXOC to 4.00) is
    # claimed nav-message-not-representable:<sys>:<msg>; compare_nav checks that count
    lost_msgs = {tuple(k.split(":")[1:3]) for k in losses if k.startswith("nav-message-not-representable:")}
    used = set()
    rounded = 0
    unmatched = []
    field_lost = Counter()
    utc_lost = Counter()                  # RINEX 4 UTC IDs a RINEX 3 header record cannot number
    pairs = []                            # (output index, input item) matched
    # --dedupe drops exact duplicate RINEX 4 records (compare_nav counts them against the
    # claim): an input record identical to one already matched is not a loss here
    dedupe = "nav-duplicate-removed" in losses and tv >= "4"
    matched_ids = set()
    for it in iin:
        hit = None
        # the first output record that matches with its reference time too, else the first that
        # matches at all: records of equal values at other epochs (a merge sorts the inputs'
        # records by epoch) must not pair off out of order (Sonnet round 18: a false alarm)
        # (an ionospheric set first with the output set in its own place, type, time mark and
        # SV, from 3.02: sets of equal values at other hours must not pair off out of order;
        # Sonnet round 27, BRD400DLR 2026-001 G24)
        same_place = it["kind"] == "ION" and "3.02" <= tv < "4"
        for k, o in enumerate(iout):
            if k in used or o["kind"] != it["kind"]:
                continue
            ok, r, notes = (_match_ion if it["kind"] == "ION" else _match_sto)(it, o)
            if ok and same_place and _ion_slot(o) == _ion_slot(it):
                hit = (k, r, notes)
                break
            if ok and not same_place and not any(w == "ref" for w, f in notes):
                hit = (k, r, notes)
                break
            if ok and hit is None and not same_place:
                hit = (k, r, notes)
        if hit is None:
            if dedupe and it.get("ident") is not None and it["ident"] in matched_ids:
                continue
            if it["sm"] not in lost_msgs:
                unmatched.append(it)
            continue
        k, r, notes = hit
        used.add(k)
        pairs.append((k, it))
        if it.get("ident") is not None:
            matched_ids.add(it["ident"])
        rounded += r
        if it["kind"] == "STO":
            p += _sto_fields(it, iout[k], utc_lost, field_lost)
        else:
            p += _ion_fields(it, iout[k], tv, utc_lost)
        for what, f in notes:
            if what == "lost":
                field_lost[f] += 1
            elif not any(x["category"] == "time-corr-reference" and x["detail"].split(":")[0] in
                         (it["fam"], "GPGA" if it["fam"] == "GAGP" else it["fam"])
                         for x in report.get("assumptions", []) or []):
                # (W, T) = (0, 0) read as "unknown": the reference the target needs is then a
                # reported assumption (PLAN §1 clause 8), not a change
                p.append(f"{it['src']}: reference time changed {f}")
        if it["kind"] == "ION" and it.get("flags") not in (None, 0) and not iout[k].get("has_flags"):
            field_lost["flags"] += 1
        if it["kind"] == "ION" and it.get("has_flags") and iout[k].get("has_flags") and \
                it.get("flags") != iout[k].get("flags") and not ({it.get("flags"), iout[k].get("flags")} <= {None, 0}):
            p.append(f"{it['src']}: disturbance flags {it.get('flags')} -> {iout[k].get('flags')}")
        if it["kind"] == "ION" and not it.get("has_flags") and iout[k].get("has_flags") and \
                iout[k].get("flags") is not None and it.get("flags") is None and not any(
                    x["category"] == "ion-galileo-disturbance-flags" for x in report.get("assumptions", []) or []):
            p.append(f"{iout[k]['src']}: disturbance flags {iout[k].get('flags')} written, the input has none "
                     "and no assumption is reported")
    for k, o in enumerate(iout):
        if k not in used:
            p.append(f"output correction {o['src']} matches no input correction (invented or changed value)")
    # unmatched input items must be claimed: nav-correction-not-representable (no place for
    # that type in the target) or nav-correction-extra (its one header slot already used)
    lost_ion = Counter(_ion_sys(it) for it in unmatched if it["kind"] == "ION")
    lost_sto = Counter(it["fam"] for it in unmatched if it["kind"] == "STO")
    c_ion, c_sto = Counter(), Counter()
    for cat, e in losses.items():
        parts = cat.split(":")
        if parts[0] not in ("nav-correction-not-representable", "nav-correction-extra"):
            continue
        if parts[1] == "ION":
            s = parts[-1] if len(parts) > 3 and len(parts[-1]) == 1 else "?"
            c_ion[s] += e["count"]
        elif parts[1] == "STO":
            c_sto["GAGP" if parts[2] == "GPGA" else parts[2]] += e["count"]
    # nav-correction-extra says the type's one header slot (rinex305.txt Table A5; rinex211.txt
    # Table A3) is taken: a kept correction of that type must be in the output, and the input
    # must have had more of them than the output keeps. RINEX 4 holds any number of records.
    for cat, e in losses.items():
        parts = cat.split(":")
        if parts[0] != "nav-correction-extra" or len(parts) < 3:
            continue
        if tv >= "4":
            p.append(f"report claims {cat}, but RINEX {tv} holds any number of {parts[1]} records")
        elif parts[1] == "STO":
            fam = "GAGP" if parts[2] == "GPGA" else parts[2]
            kept = sum(1 for o in iout if o["kind"] == "STO" and o["fam"] == fam)
            had = sum(1 for it in iin if it["kind"] == "STO" and it["fam"] == fam)
            if not kept or had - kept < e["count"]:
                p.append(f"report claims {e['count']} {cat}, but the output keeps {kept} and the input "
                         f"has {had} {fam} corrections")
        elif parts[1] == "ION":
            s = parts[-1]
            kept = sum(1 for o in iout if o["kind"] == "ION" and _ion_sys(o) == s)
            had = sum(1 for it in iin if it["kind"] == "ION" and _ion_sys(it) == s)
            if not kept or had - kept < e["count"]:
                p.append(f"report claims {e['count']} {cat}, but the output keeps {kept} and the input "
                         f"has {had} system-{s} ionospheric corrections")
            if "3.02" <= tv < "4":
                # from 3.02 a set has a place per type, time mark and SV (rinex305.txt Table A5
                # p.64-66): one with no room must find its place taken (Sol round 26)
                taken = {_ion_slot(o) for o in iout if o["kind"] == "ION"}
                # (sets of the claim's own model: a BeiDou BDGIM, C CNVX, is no Klobuchar set)
                free = [it["src"] for it in unmatched if it["kind"] == "ION" and _ion_sys(it) == s
                        and it["fam"][0] == parts[2] and _ion_slot(it) not in taken]
                if free:
                    p.append(f"report claims {cat}, but {free[:2]} would have a free place "
                             "(type, time mark, SV) in the output header")
    # one set per place (type; from 3.02 also time mark and SV: rinex305.txt Table A5): two
    # sets in one place cannot be told apart (round 27: 3.05 sets marked A/01 and B/02 were
    # written unmarked into 3.01); the file's own version carries what it has
    if "3" <= tv < "4" and tv != sv:
        places = Counter(_ion_slot(o) for o in iout if o["kind"] == "ION")
        twice = sorted(k for k, n in places.items() if n > 1)
        if twice:
            p.append(f"output header holds more than one ionospheric set in one place: {twice[:2]}")
    if lost_ion != c_ion:
        p.append(f"ionospheric corrections lost per system {dict(lost_ion)} "
                 f"({[it['src'] for it in unmatched if it['kind'] == 'ION'][:4]}), report claims {dict(c_ion)}")
    if lost_sto != c_sto:
        p.append(f"time-system corrections lost per code {dict(lost_sto)} "
                 f"({[it['src'] for it in unmatched if it['kind'] == 'STO'][:4]}), report claims {dict(c_sto)}")
    # EOP has no RINEX 2/3 form (rinex_4.02.txt Table A34)
    c_eop = _count(report, "nav-correction-not-representable:EOP")
    kept_in = [e for e in eop_in if e[:2] not in lost_msgs]
    n_in = len(kept_in)
    if dedupe:
        # identical EOP records removed by --dedupe are not lost (compare_nav counts every
        # duplicate removal against nav-duplicate-removed); a unique record still is
        n_in -= len(kept_in) - len({e[2] for e in kept_in})
    if n_in - len(eop_out) != c_eop or len(eop_out) > n_in:
        p.append(f"{n_in} EOP records in the input (of message types the target has), {len(eop_out)} in "
                 f"the output, report claims {c_eop} nav-correction-not-representable:EOP")
    # precision: rounded values must be claimed, and claimed roundings must have happened
    c_prec = sum(e["count"] for k, e in losses.items() if k.startswith("nav-correction-precision:"))
    if rounded != c_prec:
        p.append(f"{rounded} correction values rounded to the target's precision, report claims {c_prec} "
                 "nav-correction-precision")
    # RINEX 2 CORR TO SYSTEM TIME (g files, 2.10 h files) holds the reference date and a0 only
    # (rinex211.txt Table A10 l.1689, Table A15 l.1908): a reference time T, a satellite or
    # SBAS id and a UTC identifier of the record it was written from go, one claim per record
    n_tswu = 0
    for k, it in pairs:
        o = iout[k]
        if o.get("label") == "CORR TO SYSTEM TIME" and it.get("label") != "CORR TO SYSTEM TIME" and (
                ("TW" in it["has"] and it.get("T")) or it.get("sat") or it.get("sbas") or it.get("utc")):
            n_tswu += 1
    c = _count(report, "header-field-not-representable:CORR TO SYSTEM TIME:T-W-S-U")
    if c != n_tswu:
        p.append(f"{n_tswu} corrections lost their T, satellite, SBAS or UTC id to RINEX {tv} CORR TO SYSTEM "
                 f"TIME, report claims {c} header-field-not-representable:CORR TO SYSTEM TIME:T-W-S-U")
    # each such UTC ID is claimed once per header record written from it (Sol round 13 audit)
    c_utc = Counter({k.split(":", 1)[1]: e["count"] for k, e in losses.items()
                     if k.startswith(tuple("header-field-not-representable:" + x for x in _IDENT_CLAIMS))})
    if +c_utc != +utc_lost:
        p.append(f"satellite, SBAS and UTC ids with no room {dict(utc_lost)}, report claims {dict(c_utc)} "
                 "header-field-not-representable:*")
    # fields with no room in the target record: claimed header-field-not-representable:*
    kinds = {"a1": "a1", "a2": "A2", "flags": "flags", "ttm": "STO-TTM"}
    c_field = Counter()
    for cat, e in losses.items():
        if cat.startswith("header-field-not-representable:") and "LEAP SECONDS" not in cat:
            rest = cat.split(":", 1)[1]
            kind = next((k for k, w in kinds.items() if w.lower() in rest.lower()), rest)
            c_field[kind] += e["count"]
    for k in set(field_lost) | set(c_field):
        if k in kinds and field_lost[k] != c_field[k]:
            p.append(f"{field_lost[k]} non-zero {kinds[k]} correction fields have no room in RINEX {tv}, "
                     f"report claims {c_field[k]} header-field-not-representable:*{kinds[k]}*")
    # LEAP SECONDS
    lin = [c for lab, c, ln in hin if lab == "LEAP SECONDS"]
    louts = [[c for lab, c, ln in x[1] if lab == "LEAP SECONDS"] for x in parsed]
    dropped_any = False
    n_dropped = 0
    # a 3.02 file of BeiDou records only counts from 2006, as the BDS almanac (rinex302.txt
    # Table A5 p.63): read so, and only with that assumption reported (Sol round 24)
    basis = leap_basis
    if merged is None and basis == "BDS":
        if tv != sv and lin and _bds_count(_leap_fields(lin[0])) and not any(x["category"] == "leap-seconds-basis" and x["detail"] == "BDS"
                                        for x in report.get("assumptions", []) or []):
            p.append("LEAP SECONDS of a BeiDou-only 3.02 navigation file converted without a "
                     "leap-seconds-basis BDS assumption")
    # and a BeiDou-only 3.02 output is read so too (Sol round 26: written GPS 18, read back 32)
    out_basis = "BDS" if "3.02" <= tv < "4" and outs and _nav_systems(outs[0]) == {"C"} else None
    # (a 3.02 output, which has no identifier, is written in BDS terms: the assumption)
    if out_basis and tv == "3.02" and tv != sv and lin and not any(
            x["category"] == "leap-seconds-basis" for x in report.get("assumptions", []) or []):
        p.append("LEAP SECONDS written for a BeiDou-only 3.02 output without a leap-seconds-basis "
                 "BDS assumption")
    if lin:
        if not any(louts):
            p.append("LEAP SECONDS dropped from every output")
        for lo in louts:
            if lo:
                q, d = check_leap(lin[0], lo[0], leap_sv, tv, report, basis=basis, out_basis=out_basis)
                p += q
                dropped_any |= d
        # counted once per input record, however many RINEX 2 files it is split into
        first = next((lo for lo in louts if lo), [])
        n_dropped = sum(check_leap(ci, co, leap_sv, tv, report, basis=basis, out_basis=out_basis)[1]
                        for ci, co in zip(lin, first))
    else:
        told = {x["detail"] for x in report.get("assumptions", []) or [] if x["category"] == "leap-seconds"}
        for lo in louts:
            if lo and str(_int(lo[0][:6])) not in told:
                p.append(f"output LEAP SECONDS {lo[0][:6].strip()} not in the input and not a reported "
                         "leap-seconds assumption")
    c = _count(report, "header-field-not-representable:LEAP SECONDS")
    if c != n_dropped:
        p.append(f"{n_dropped} LEAP SECONDS records lost fields, report claims {c} "
                 "header-field-not-representable:LEAP SECONDS")
    # other header records (corrections are compared above)
    keep = lambda h: [r for r in h if r[0] not in NAV_CORR_LABELS and r[0] not in
                      ("LEAP SECONDS", "RINEX VERSION / TYPE")]
    regen = {"PGM / RUN BY / DATE"}
    repaired = repaired_labels(report, hin, ALL_NAV_LABELS)
    p += generic_header(keep(hin), [keep(x[1]) for x in parsed], tv,
                        _own_defined(keep(hin_own), sv, tv, NAV_LABELS, ALL_NAV_LABELS, report, "NAV", p),
                        ALL_NAV_LABELS - NAV_CORR_LABELS, regen, report, repaired)
    for x in parsed:
        if x[0] != tv:
            p.append(f"output RINEX VERSION / TYPE says {x[0]}, the target is {tv}")
        if not any(lab == "PGM / RUN BY / DATE" for lab, c, ln in x[1]):
            p.append("an output has no PGM / RUN BY / DATE")
    return p


# ---------------------------------------------------------------------------
# meteorological files
# ---------------------------------------------------------------------------
# met types added in 2.11 (rinex211.txt Table A5 line 1463-1469; rinex210.txt Table A5 lists
# only PR TD HR ZW ZD ZT)
MET_TYPES_211 = {"WD", "WS", "RI", "HI"}


def _met_types(head):
    types = []
    for lab, c, ln in head:
        if lab == "# / TYPES OF OBSERV":
            if c[:6].strip():
                types = []
            types += c[6:60].split()
    return types


def compare_met_meta(inp, out, report):
    """Sensor, marker, comment and type-list records of a met conversion."""
    p = []
    tv = report.get("target_version")
    La, Lb = _lines(inp), _lines(out)
    ha, _ = _header(La)
    hb, _ = _header(Lb)
    if _vstr(Lb[0]) != tv:
        p.append(f"output RINEX VERSION / TYPE says {_vstr(Lb[0])}, the target is {tv}")
    losses = _losses(report)
    lost_types = {k.split(":")[1] for k in losses if k.startswith("met-type-not-representable:")}
    want = [t for t in _met_types(ha) if t not in lost_types]
    if _met_types(hb) != want:
        p.append(f"met types {_met_types(ha)} -> {_met_types(hb)}, expected {want} "
                 f"(claimed lost: {sorted(lost_types)})")
    # sensor records: kept, or claimed header-record-not-representable:<LABEL>[:<type>] when
    # their observation type is not representable
    for lab in ("SENSOR MOD/TYPE/ACC", "SENSOR POS XYZ/H"):
        sin = [c for l, c, ln in ha if l == lab]
        sout = Counter(norm(lab, c) for l, c, ln in hb if l == lab)
        miss = Counter()
        for c in sin:
            k = norm(lab, c)
            if sout[k] > 0:
                sout[k] -= 1
            else:
                miss[c[57:59].strip()] += 1
        for t, n in miss.items():
            cl = _count(report, f"header-record-not-representable:{lab}:{t}")
            # a sensor record may describe a type the file holds no values of: then only the
            # type's absence from the target's type list justifies dropping it
            unrep = t in lost_types or (tv < "2.11" and t in MET_TYPES_211)
            if cl != n or not unrep:
                p.append(f"{n} {lab} record(s) for type {t!r} lost or changed, report claims {cl} "
                         f"header-record-not-representable:{lab}:{t}" + ("" if unrep else
                                                                          f"; RINEX {tv} has type {t}"))
        if +sout:
            p.append(f"output {lab} records not in the input: {list((+sout).elements())[:2]}")
        for cat, e in losses.items():
            if cat.startswith(f"header-record-not-representable:{lab}:"):
                t = cat.split(":")[2]
                if miss.get(t, 0) != e["count"]:
                    p.append(f"report claims {e['count']} {cat}, {miss.get(t, 0)} such records are missing")
    keep = lambda h: [r for r in h if r[0] not in ("SENSOR MOD/TYPE/ACC", "SENSOR POS XYZ/H")]
    clean = dict(report)
    clean["losses"] = {k: e for k, e in losses.items()
                       if not k.startswith(("header-record-not-representable:SENSOR MOD/TYPE/ACC:",
                                            "header-record-not-representable:SENSOR POS XYZ/H:"))}
    regen = {"RINEX VERSION / TYPE", "# / TYPES OF OBSERV"}
    # PGM / RUN BY / DATE is mandatory: an input without one gets exactly one in the output,
    # and the report must say so (a repair); an input with one keeps it (checked below)
    if not [r for r in ha if r[0] == "PGM / RUN BY / DATE"]:
        added = [r for r in hb if r[0] == "PGM / RUN BY / DATE"]
        if len(added) != 1 or not any(x.get("rule") == "HDR.PGM.ADDED" for x in report.get("repairs", [])):
            p.append("the input has no PGM / RUN BY / DATE: the output must add exactly one, "
                     "reported as repair HDR.PGM.ADDED")
        hb = [r for r in hb if r[0] != "PGM / RUN BY / DATE"]
    repaired = repaired_labels(report, ha, ALL_MET_LABELS)
    p += generic_header(keep(ha), [keep(hb)], tv,
                        _own_defined(ha, _vstr(La[0]), tv, MET_LABELS, ALL_MET_LABELS, report, "MET", p),
                        ALL_MET_LABELS, regen, clean, repaired)
    return p
