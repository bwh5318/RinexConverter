"""RINEX navigation files: model, readers (2, 3, 4) and writers.

Every numeric field is kept as its text token (stripped), never as a float, so a
value moves between versions unchanged except for the exponent letter.

Layouts (rinex211.txt Tables A4/A11/A16; rinex305.txt Tables A6-A14;
rinex_4.02.txt §5.4 and Tables A9-A41):
  RINEX 2  SV/EPOCH line  I2,1X,I2.2,4(1X,I2),F5.1,3D19.12   continuation 3X,4D19.12
  RINEX 3  SV/EPOCH line  A1,I2.2,1X,I4,5(1X,I2.2),3D19.12   continuation 4X,4D19.12
  RINEX 4  '> EPH G01 LNAV' (or STO/EOP/ION) record header, then a RINEX 3 style body;
           STO/EOP/ION bodies start with 4X,I4,5(1X,I2.2).
Records are found structurally: a RINEX 2/3 record starts on a line whose first
columns are not blank; a RINEX 4 record starts with '>'. The line count of
each record is then checked against the expected count by the validator.
"""

import re
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from .errors import CorruptError
from .header import END, read_header
from .obs import year4

V2_SYS = {"N": "G", "G": "R", "H": "S", "L": "E", "E": "E", "C": "C", "J": "J", "I": "I"}
_EXP = re.compile(r"[DdEe]")
_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([DdEe][+-]?\d+)?$")


class NavRecord:
    """One navigation record.

    kind  EPH, STO, EOP or ION (RINEX 2/3 hold only EPH)
    sat   'G01', or 'E  ' when a RINEX 4 STO/ION record leaves the PRN blank
    msg   RINEX 4 message type (LNAV, FDMA, INAV, ...) or None
    sub   RINEX 4 subtype (ION region/model) or ''
    time  (year, month, day, hour, minute, Decimal seconds)
    vals  numeric tokens by position: line 0 has 3 slots, every further line 4
    extra STO line 0 text after the epoch (time-offset type, SBAS id, UTC id)
    """

    __slots__ = ("kind", "sat", "msg", "sub", "time", "vals", "extra", "lineno", "nlines")

    def __init__(self, kind, sat, msg, sub, time, vals, extra="", lineno=None, nlines=0):
        self.kind = kind
        self.sat = sat
        self.msg = msg
        self.sub = sub
        self.time = time
        self.vals = vals
        self.extra = extra
        self.lineno = lineno
        self.nlines = nlines

    @property
    def system(self):
        return self.sat[0]

    def __repr__(self):
        return f"NavRecord({self.kind} {self.sat} {self.msg} {self.time} n={len(self.vals)})"


class NavFile:
    def __init__(self):
        self.version = None
        self.version_str = None
        self.ftype = "N"
        self.system = " "
        self.header = []
        self.records = []
        self.eol = "lf"
        self.notes = []

    def first(self, label):
        for r in self.header:
            if r.label == label:
                return r
        return None


def check_token(tok, lineno, column):
    if tok and not _NUM.match(tok):
        raise CorruptError(f"bad navigation number {tok!r}", line=lineno, column=column,
                           rule="NAV.NUMBER")
    return tok


def _fields(line, start, n, lineno):
    out = []
    for k in range(n):
        a = start + 19 * k
        out.append(check_token(line[a:a + 19].strip(), lineno, a + 1))
    return out


def _int(s, what, lineno, col):
    t = s.strip()
    if not t.lstrip("-").isdecimal():
        raise CorruptError(f"bad {what} {s!r}", line=lineno, column=col, rule="NAV.EPOCH")
    return int(t)


def _sec(s, lineno, col):
    t = s.strip()
    try:
        d = Decimal(t)
    except InvalidOperation:
        d = None
    if d is None or not d.is_finite() or not Decimal(0) <= d < 61:
        raise CorruptError(f"bad seconds {s!r}", line=lineno, column=col, rule="NAV.EPOCH")
    return d


def _check_date(t, lineno):
    import datetime
    try:
        datetime.datetime(t[0], t[1], t[2], t[3], t[4])
    except ValueError:
        raise CorruptError(f"bad epoch {t[:5]}", line=lineno, rule="NAV.EPOCH") from None
    return t


def token_value(tok):
    """Decimal of a token ('' -> None)."""
    if not tok:
        return None
    return Decimal(_EXP.sub("E", tok))


def decimal_token(value, like=""):
    """(text, exact) of a Decimal as a navigation number for a 19-column field, in the
    mantissa form of the token `like` ('0.123D+05' or '1.23E+04'; the writer sets the
    exponent letter): 12 digits after the point, 13 if that makes it exact and it fits."""
    lead0 = bool(re.match(r"^[+-]?0?\.\d*[1-9]", (like or "").strip()))
    if value == 0:
        return "0.000000000000E+00", True
    sign = "-" if value < 0 else ""
    a = abs(value)

    def form(zero_lead, digits):
        e = a.adjusted() + (1 if zero_lead else 0)          # mantissa in [0.1, 1) or [1, 10)
        q = Decimal(1).scaleb(-digits)
        m = a.scaleb(-e).quantize(q, rounding=ROUND_HALF_EVEN)
        if m >= (1 if zero_lead else 10):
            e += 1
            m = a.scaleb(-e).quantize(q, rounding=ROUND_HALF_EVEN)
        return f"{sign}{m:.{digits}f}E{'+' if e >= 0 else '-'}{abs(e):02d}"
    for zl, digits in ((lead0, 12), (lead0, 13), (not lead0, 12), (not lead0, 13)):
        txt = form(zl, digits)
        if len(txt) <= 19 and Decimal(txt) == value:
            return txt, True
    return form(False, 12), False


def negate_token(tok):
    """A token with the opposite sign ('' and zero unchanged)."""
    t = (tok or "").strip()
    if not t or token_value(t) == 0:
        return t
    if t[0] == "-":
        return t[1:]
    if t[0] == "+":
        return "-" + t[1:]
    return "-" + t


# ---------------------------------------------------------------------------
# fields defined per record line
# ---------------------------------------------------------------------------
# Numeric fields each line of a RINEX 4 record defines, line 0 first (the SV / EPOCH / SV CLK
# line of an EPH record; the epoch line of STO/EOP/ION records, where STO holds text, not
# numbers). A line "4X,2E19.12" defines two fields, and the positions after them are no field
# of that version; spare fields inside a line ("Spare ... A19") are fields (rinex_4.02.txt
# section 6.4 p.48). RINEX 2 and 3 lines all hold four (line 0: three), spares included
# (rinex211.txt Tables A4/A11/A16; rinex305.txt Tables A6-A18: "4X,4D19.12"). Pages are
# rinex_4.02.txt's; rinex_4.00.txt and rinex_4.01.txt define the same counts for the types
# they have (e.g. rinex_4.01.txt Table A9 l.4296, A10 l.4419), except the CNAV/CNV2 flags.
_EPH4_FIELDS = {
    ("G", "LNAV"): (3, 4, 4, 4, 4, 4, 4, 2),            # Table A9 p.78-79: orbit 7 t_tm, fit interval
    ("J", "LNAV"): (3, 4, 4, 4, 4, 4, 4, 2),            # Table A19 p.93-94
    ("G", "CNAV"): (3, 4, 4, 4, 4, 4, 4, 4, 2),         # Table A10 p.80-81: orbit 8 t_tm, wn_op
    ("J", "CNAV"): (3, 4, 4, 4, 4, 4, 4, 4, 2),         # Table A20 p.95-96
    ("G", "CNV2"): (3, 4, 4, 4, 4, 4, 4, 4, 2, 2),      # Table A11 p.82-83: orbit 8 ISC_L1Cd/Cp, 9 t_tm, wn_op
    ("J", "CNV2"): (3, 4, 4, 4, 4, 4, 4, 4, 2, 2),      # Table A21 p.97-98
    ("E", "INAV"): (3, 4, 4, 4, 4, 3, 4, 1),            # Table A13 p.84-85: orbit 5 3 fields, orbit 7 t_tm
    ("E", "FNAV"): (3, 4, 4, 4, 4, 3, 4, 1),
    ("R", "FDMA"): (3, 4, 4, 4, 4),                     # Table A15 p.86-87
    ("R", "L1OC"): (3, 4, 4, 4, 4, 4, 4, 4, 4),         # Table A16 p.89-90 (4.02 only)
    ("R", "L3OC"): (3, 4, 4, 4, 4, 4, 4, 4, 4),         # Table A17 p.90-91 (4.02 only)
    ("C", "D1"): (3, 4, 4, 4, 4, 4, 4, 2),              # Table A23 p.99-100: orbit 7 t_tm, AODC
    ("C", "D2"): (3, 4, 4, 4, 4, 4, 4, 2),
    ("C", "CNV1"): (3, 4, 4, 4, 4, 4, 4, 4, 4, 4),      # Table A24 p.101-102 (spares inside lines)
    ("C", "CNV2"): (3, 4, 4, 4, 4, 4, 4, 4, 4, 4),      # Table A25 p.103-104
    ("C", "CNV3"): (3, 4, 4, 4, 4, 4, 4, 4, 1),         # Table A26 p.105-106: orbit 8 t_tm
    ("S", "SBAS"): (3, 4, 4, 4),                        # Table A28 p.108
    ("I", "LNAV"): (3, 4, 4, 4, 4, 4, 4, 1),            # Table A30 p.110-111: orbit 7 t_tm
}
# 4.02 adds "Integer flags encoded as decimal value (optional; blank if not provided)" as a
# third field of the last line of GPS/QZSS CNAV and CNAV-2 (rinex_4.02.txt Tables A10 p.81,
# A11 p.83, A20 p.96, A21 p.98: 4X,3E19.12); 4.00/4.01 define 4X,2E19.12 there
# (rinex_4.01.txt Tables A10 l.4419, A11 l.4545 p.79-81).
V402_FLAGS = {("G", "CNAV"), ("J", "CNAV"), ("G", "CNV2"), ("J", "CNV2")}
# Klobuchar ION records (rinex_4.02.txt Table A35 p.117; rinex_4.00.txt Table A32 p.104)
KLOBUCHAR_ION = {("G", "LNAV"), ("J", "LNAV"), ("I", "LNAV"), ("C", "D1D2"), ("G", "CNVX"),
                 ("J", "CNVX")}


def v4_line_fields(version, kind, system, msg):
    """Fields per line of a RINEX 4 record of `version` (a tuple, line 0 first), or None when
    the type is not tabled (its lines are then not cut)."""
    if version < "4":
        return None
    if kind == "EPH":
        f = _EPH4_FIELDS.get((system, msg))
        if f is not None and version >= "4.02" and (system, msg) in V402_FLAGS:
            f = f[:-1] + (f[-1] + 1,)
        return f
    if kind == "STO":
        return (0, 4)                   # Table A33 p.115: t_tm, A0, A1, A2
    if kind == "EOP":
        return (3, 4, 4)                # Table A34 p.116 (line 1: a spare, then 3 values)
    if kind == "ION":
        if (system, msg) in KLOBUCHAR_ION:
            # line 2: Beta3 only in 4.02 (Table A35 p.117: 4X,E19.12); Beta3 and the Region
            # code in 4.00/4.01 (rinex_4.00.txt Table A32 p.104, rinex_4.01.txt l.6190 p.108:
            # 4X,2D19.12 / 4X,2E19.12)
            return (3, 4, 1 if version >= "4.02" else 2)
        if (system, msg) == ("E", "IFNV"):
            return (3, 1)               # NeQuick-G, Table A36 p.118
        if (system, msg) == ("C", "CNVX"):
            return (3, 4, 2)            # BDGIM, Table A37 p.119
    return None


# Spare fields inside RINEX 4 record lines, as value positions (BROADCAST ORBIT k starts at
# 3 + 4 (k - 1)): "Spare fields are to be left blank so as to avoid confusion" (rinex_4.02.txt
# section 6.4 p.48; rinex_4.00.txt p.43, rinex_4.01.txt p.46 the same). rinex_4.02.txt Tables
# A16/A17 p.90-91 (GLONASS L1OC/L3OC orbit 8 field 3), A23 p.100 (BDS D1/D2 orbit 5 fields 2
# and 4), A24 p.102 (CNV1 orbit 7 field 2, orbit 9 fields 2-3), A25 p.104 (CNV2 orbit 7 field 1,
# orbit 9 fields 2-3), A30 p.110-111 (NavIC LNAV orbit 5 fields 2 and 4, orbit 6 field 4), A31
# p.112 (NavIC L1NV orbit 5 field 3), A34 p.116 (EOP line 1 field 1); the same in rinex_4.00.txt
# (l.5035-5037, 5172, 5187, 5287, 5307, 5686-5690, 5725, 5847) for the types it has.
_V4_SPARES = {
    ("EPH", "R", "L1OC"): {33}, ("EPH", "R", "L3OC"): {33},
    ("EPH", "C", "D1"): {20, 22}, ("EPH", "C", "D2"): {20, 22},
    ("EPH", "C", "CNV1"): {28, 36, 37}, ("EPH", "C", "CNV2"): {27, 36, 37},
    ("EPH", "I", "LNAV"): {20, 22, 26}, ("EPH", "I", "L1NV"): {21},
}


# Spare fields of RINEX 2/3 records (all lines 4X/3X,4D19.12; BROADCAST ORBIT k starts at
# 3 + 4 (k - 1)), by system:
#  G  orbit 7 fields 3-4 'spare' (rinex210.txt l.1140-1141, rinex211.txt l.1411-1412 Table A4;
#     rinex300.txt l.2251-2252 Table A5 ... rinex305.txt Table A6 p.69)
#  S  2.10: orbit 3 field 4 'spare' (rinex210.txt Table A16 l.1671); 2.11+ it is the IODN
#     (rinex211.txt Table A16 l.1976, l.932-935; rinex305.txt Table A16 p.81): no spare
#  E  orbit 5 field 4, orbit 7 fields 2-4 (rinex300.txt l.2349, l.2365-2367 Table A7;
#     rinex305.txt Table A8 p.71-72)
#  J  3.02: orbit 5 field 4 'Spare' (rinex302.txt Table A12 l.3402-3403 p.71-72; from 3.03 the
#     L2 P data flag, rinex303.txt Table A12 p.80), orbit 7 fields 3-4
#  C  orbit 5 fields 2 and 4, orbit 7 fields 3-4 (rinex302.txt Table A13 l.3540-3542 p.73;
#     rinex305.txt Table A14 p.79-80)
#  I  orbit 5 fields 2 and 4 ('Blank'/'Spare'), orbit 6 field 4, orbit 7 fields 2-4
#     (rinex303.txt Table A18 p.86-87; rinex305.txt Table A18 p.83-84)
#  R  none (rinex211.txt Table A11; rinex305.txt Table A10)
_V2V3_SPARES = {"G": {29, 30}, "E": {22, 28, 29, 30}, "C": {20, 22, 29, 30},
                "I": {20, 22, 26, 28, 29, 30}, "J": {29, 30}}


def spare_positions(version, kind, system, msg=None):
    """vals positions of the spare fields of a record of `version` (empty set: none)."""
    if version >= "4":
        if kind == "EOP":
            return {3}
        return set(_V4_SPARES.get((kind, system, msg), ()))
    if kind != "EPH":
        return set()
    if system == "S":
        return {14} if version < "2.11" else set()
    if system == "J" and version < "3.03":
        return {22, 29, 30}
    return set(_V2V3_SPARES.get(system, ()))


def v4_spare_positions(version, kind, system, msg):
    """vals positions of the spare fields of a RINEX 4 record (empty set: none)."""
    return spare_positions(version, kind, system, msg) if version >= "4" else set()


def cut_positions(fields):
    """The value positions (indexes into NavRecord.vals) a line-fields tuple leaves out:
    {position: line}, up to the end of the last line."""
    out = {}
    pos = 0
    for line, n in enumerate(fields):
        width = 3 if line == 0 else 4
        for k in range(n, width):
            out[pos + k] = line
        pos += width
    return out, pos


_DRAFT_V4_HEAD = re.compile(r"^([A-Z])(\d\d) ([A-Z0-9]{2,4})\s*\*?\s*$")


def read_nav(lines, info, eol="lf", lenient=False):
    f = NavFile()
    f.version = info.version
    f.version_str = info.version_str
    f.ftype = info.ftype
    f.system = info.system or " "
    f.eol = eol
    records, i = read_header(lines)
    f.header = [r for r in records if r.label not in ("", END)]
    if info.major == 2:
        _read_v2(f, lines, i)
    elif info.major == 3:
        _read_v3(f, lines, i)
    else:
        _read_v4(f, lines, i, lenient)
    return f


def _blank_note(f, lines, i):
    if any(ln.strip() for ln in lines[i:]):
        f.notes.append({"rule": "NAV.BLANKLINE", "message": "blank line skipped", "line": i + 1,
                        "repair": True})


def _read_v2(f, lines, i):
    n = len(lines)
    dsys = V2_SYS.get(f.ftype, "G")
    while i < n:
        line = lines[i]
        lineno = i + 1
        if not line.strip():
            _blank_note(f, lines, i)
            i += 1
            continue
        if not line[0:2].strip():
            raise CorruptError("expected a PRN / EPOCH / SV CLK line", line=lineno, column=1,
                               rule="NAV.RECORD.START")
        line = line.ljust(79)
        c0 = line[0:1]
        if c0.isalpha():
            sysc = c0.upper()
            prn = _int(line[1:3], "PRN", lineno, 2)
            off = 1
        else:
            sysc = dsys
            prn = _int(line[0:2], "PRN", lineno, 1)
            off = 0
        yy = _int(line[off + 3:off + 5], "year", lineno, 4)
        t = (year4(yy), _int(line[off + 6:off + 8], "month", lineno, 7),
             _int(line[off + 9:off + 11], "day", lineno, 10),
             _int(line[off + 12:off + 14], "hour", lineno, 13),
             _int(line[off + 15:off + 17], "minute", lineno, 16),
             _sec(line[off + 17:off + 22], lineno, 18))
        _check_date(t, lineno)
        vals = _fields(line, off + 22, 3, lineno)
        i += 1
        nl = 1
        while i < n:
            nxt = lines[i]
            if not nxt.strip():
                break
            if nxt[0:2].strip():
                break
            nxt = nxt.ljust(79)
            vals.extend(_fields(nxt, 3, 4, i + 1))
            i += 1
            nl += 1
        f.records.append(NavRecord("EPH", f"{sysc}{prn:02d}", None, "", t, vals, "", lineno, nl))


def _v3_epoch(line, lineno, start):
    return _check_date(_v3_epoch_raw(line, lineno, start), lineno)


def _v3_epoch_raw(line, lineno, start):
    return (_int(line[start:start + 4], "year", lineno, start + 1),
            _int(line[start + 5:start + 7], "month", lineno, start + 6),
            _int(line[start + 8:start + 10], "day", lineno, start + 9),
            _int(line[start + 11:start + 13], "hour", lineno, start + 12),
            _int(line[start + 14:start + 16], "minute", lineno, start + 15),
            _sec(line[start + 17:start + 19], lineno, start + 18))


def _read_v3(f, lines, i):
    n = len(lines)
    while i < n:
        line = lines[i]
        lineno = i + 1
        if not line.strip():
            _blank_note(f, lines, i)
            i += 1
            continue
        if not line[0:1].isalpha():
            raise CorruptError("expected an SV / EPOCH / SV CLK line", line=lineno, column=1,
                               rule="NAV.RECORD.START")
        line = line.ljust(80)
        sat = line[0:1].upper() + f"{_int(line[1:3], 'satellite number', lineno, 2):02d}"
        t = _v3_epoch(line, lineno, 4)
        vals = _fields(line, 23, 3, lineno)
        i += 1
        nl = 1
        while i < n:
            nxt = lines[i]
            if not nxt.strip() or nxt[0:1] != " ":
                break
            nxt = nxt.ljust(80)
            vals.extend(_fields(nxt, 4, 4, i + 1))
            i += 1
            nl += 1
        f.records.append(NavRecord("EPH", sat, None, "", t, vals, "", lineno, nl))


def _read_v4(f, lines, i, lenient=False):
    n = len(lines)
    while i < n:
        line = lines[i]
        lineno = i + 1
        if not line.strip():
            _blank_note(f, lines, i)
            i += 1
            continue
        if line[0:1] != ">":
            m = _DRAFT_V4_HEAD.match(line)
            if not (lenient and m):
                raise CorruptError("expected a '>' record header", line=lineno, column=1,
                                   rule="NAV.RECORD.START")
            # Pre-release RINEX 4 dialect (e.g. DLR BRDX 2020): 'G01 LNAV ... *'.
            f.notes.append({"rule": "NAV.V4.DRAFT-HEADER", "line": lineno, "repair": True,
                            "message": "pre-release RINEX 4 record header read as '> EPH'"})
            line = f"> EPH {m.group(1)}{m.group(2)} {m.group(3)}"
        tok = line[1:].split()
        if len(tok) < 3:
            raise CorruptError("incomplete record header", line=lineno, rule="NAV.RECORD.HEAD")
        kind = tok[0].upper()
        s = tok[1]
        if kind not in ("EPH", "STO", "EOP", "ION"):
            raise CorruptError(f"unknown record type {kind!r}", line=lineno, column=3,
                               rule="NAV.RECORD.TYPE")
        if len(s) == 1:
            sat = s.upper() + "  "
        elif len(s) == 3 and s[0].isalpha() and s[1:].strip().isdecimal():
            sat = s[0].upper() + f"{int(s[1:]):02d}"
        else:
            raise CorruptError(f"bad satellite {s!r}", line=lineno, column=7, rule="NAV.RECORD.HEAD")
        msg = tok[2]
        sub = " ".join(tok[3:])
        i += 1
        if i >= n:
            raise CorruptError("file ends after a record header", line=n, rule="NAV.TRUNCATED")
        body0 = lines[i].ljust(80)
        b0 = i + 1
        if kind == "EPH":
            if body0[0:1].upper() != sat[0]:
                raise CorruptError("EPH body does not start with the satellite", line=b0, column=1,
                                   rule="NAV.RECORD.BODY")
            t = _v3_epoch(body0, b0, 4)
            vals = _fields(body0, 23, 3, b0)
            extra = ""
        else:
            t = _v3_epoch(body0, b0, 4)
            if kind == "STO":
                vals = ["", "", ""]
                extra = body0[23:80].rstrip()
            else:
                vals = _fields(body0, 23, 3, b0)
                extra = ""
        i += 1
        nl = 1
        while i < n:
            nxt = lines[i]
            if not nxt.strip() or nxt[0:1] == ">":
                break
            nxt = nxt.ljust(80)
            vals.extend(_fields(nxt, 4, 4, i + 1))
            i += 1
            nl += 1
        f.records.append(NavRecord(kind, sat, msg, sub, t, vals, extra, lineno, nl))


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------

def exp_letter(version):
    """D19.12 up to 4.00, E19.12 from 4.01 (rinex_4.02.txt §6.8)."""
    return "E" if version >= "4.01" else "D"


def fmt_token(tok, letter, width=19):
    """Right-justify a numeric token with the target exponent letter and a
    zero-padded two-digit exponent (rinex211.txt Table A16 note; rinex_4.02.txt §6.8)."""
    if not tok:
        return " " * width
    m = _EXP.search(tok)
    if m:
        mant = tok[:m.start()]
        e = tok[m.end():]
        sign = "-" if e.startswith("-") else "+"
        digits = e.lstrip("+-") or "0"
        if len(digits) < 2:
            digits = digits.rjust(2, "0")
        elif len(digits) > 2 and digits.startswith("0"):
            digits = digits.lstrip("0").rjust(2, "0")
        t = f"{mant}{letter}{sign}{digits}"
    else:
        t = tok
    if len(t) > width:
        raise OverflowError(f"value {tok!r} does not fit {width} columns")
    return t.rjust(width)


def _sec_int(sec):
    return int(sec)


def write_nav(f, version):
    """Lines of a navigation file in the layout of `version`."""
    letter = exp_letter(version)
    out = [r.line() for r in f.header]
    out.append(" " * 60 + END)
    major = version[0]
    for r in f.records:
        y, mo, d, h, mi, sec = r.time
        v = r.vals
        if r.kind == "EPH" and major != "4":
            # never a value in a spare field (navconv blanks and claims them); a zero spare is
            # carried in RINEX 2/3 (zero and blank both say nothing there)
            bad = [k for k in spare_positions(version, "EPH", r.sat[0])
                   if k < len(v) and v[k] and token_value(v[k]) != 0]
            if bad:
                raise AssertionError(f"{r.sat}: value {v[bad[0]]!r} in spare position {bad[0]} of RINEX {version}")
        if major == "2":
            if r.sat[0] in ("G", "R", "S", "E") and f.ftype in ("N", "G", "H", "L"):
                head = f"{int(r.sat[1:]):2d}"
            else:
                head = f"{r.sat[0]}{int(r.sat[1:]):02d}"[:3]
            first = (f"{head} {y % 100:02d} {mo:2d} {d:2d} {h:2d} {mi:2d}{sec:5.1f}"
                     + "".join(fmt_token(x, letter) for x in v[0:3]))
            out.append(first.rstrip())
            for k in range(3, len(v), 4):
                out.append(("   " + "".join(fmt_token(x, letter) for x in v[k:k + 4])).rstrip())
            continue
        if major == "4":
            # never a field the target line does not define, nor a value in a spare field
            # (navconv cuts and claims them)
            fields = v4_line_fields(version, r.kind, r.sat[0], r.msg)
            bad = [k for k in v4_spare_positions(version, r.kind, r.sat[0], r.msg) if k < len(v) and v[k]]
            if fields is not None:
                bad += [k for k in cut_positions(fields)[0] if k < len(v) and v[k]]
            if bad:
                raise AssertionError(f"{r.kind} {r.sat} {r.msg}: value {v[bad[0]]!r} at position "
                                     f"{bad[0]}, a field RINEX {version} does not define or leaves blank")
            head = f"> {r.kind} {r.sat} {r.msg}" + (f" {r.sub}" if r.sub else "")
            out.append(head.rstrip())
        stamp = f"{y:4d} {mo:02d} {d:02d} {h:02d} {mi:02d} {_sec_int(sec):02d}"
        if r.kind == "EPH":
            first = f"{r.sat} {stamp}" + "".join(fmt_token(x, letter) for x in v[0:3])
        elif r.kind == "STO":
            first = f"    {stamp}{r.extra}"
        else:
            first = f"    {stamp}" + "".join(fmt_token(x, letter) for x in v[0:3])
        out.append(first.rstrip())
        for k in range(3, len(v), 4):
            out.append(("    " + "".join(fmt_token(x, letter) for x in v[k:k + 4])).rstrip())
    return out
