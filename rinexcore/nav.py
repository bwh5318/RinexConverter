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
from decimal import Decimal, InvalidOperation

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
