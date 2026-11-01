"""RINEX meteorological files (rinex211.txt Tables A5/A6, rinex305.txt A16-A18,
rinex_4.02.txt A42-A44).

Epoch:  RINEX 2  1X,I2.2,5(1X,I2)     RINEX 3/4  1X,I4,5(1X,I2)
Values: mF7.1, 8 on the epoch line, continuation lines 4X,10F7.1.
Values are kept as their 7-character text fields.
"""

from decimal import Decimal, InvalidOperation

from .errors import CorruptError
from .header import END, read_header
from .obs import year4


class MetEpoch:
    __slots__ = ("time", "vals", "lineno")

    def __init__(self, time, vals, lineno=None):
        self.time = time
        self.vals = vals
        self.lineno = lineno


class MetFile:
    def __init__(self):
        self.version = None
        self.version_str = None
        self.header = []
        self.types = []
        self.epochs = []
        self.eol = "lf"
        self.notes = []

    def first(self, label):
        for r in self.header:
            if r.label == label:
                return r
        return None


def parse_met_types(header):
    types = None
    expected = None
    for r in header:
        if r.label != "# / TYPES OF OBSERV":
            continue
        c = r.content
        if c[0:6].strip():
            try:
                expected = int(c[0:6])
            except ValueError:
                raise CorruptError("bad # / TYPES OF OBSERV count", line=r.lineno,
                                   rule="MET.TYPES") from None
            types = []
        elif types is None:
            raise CorruptError("# / TYPES OF OBSERV continuation without count", line=r.lineno,
                               rule="MET.TYPES")
        types.extend(c[6:60].split())
    if types is None:
        raise CorruptError("no # / TYPES OF OBSERV record", rule="MET.TYPES.MISSING")
    if len(types) != expected:
        raise CorruptError(f"# / TYPES OF OBSERV declares {expected}, lists {len(types)}",
                           rule="MET.TYPES.COUNT")
    return types


def _int(s, what, lineno, col):
    t = s.strip()
    if not t.isdecimal():
        raise CorruptError(f"bad {what} {s!r}", line=lineno, column=col, rule="MET.EPOCH")
    return int(t)


def _looks_v2_epoch(line):
    return line[1:3].strip().isdecimal() and line[3:4] == " " and line[4:6].strip().isdecimal()


def _met_values(line, start, k, lineno, lenient, notes):
    """k F7.1 value fields from column `start` (rinex211.txt Table A6 l.1517: epoch, then mF7.1;
    continuation lines 4X,10F7.1). Text beyond the last field means the values are not in
    their columns (e.g. a writer's F8.2): read by the columns it would silently change them,
    so it is an error (PLAN §1 clause 9); --lenient reads the values by pattern when the
    line holds exactly k of them, and reports it."""
    line = line.ljust(start + 7 * k)
    vals = [line[start + 7 * j:start + 7 * j + 7] for j in range(k)]
    extra = line[start + 7 * k:].strip()
    if not extra:
        return vals
    if not lenient:
        raise CorruptError(f"text {extra!r} after the {k} met values of this line (columns "
                           f"{start + 1}-{start + 7 * k}): the values are not in their F7.1 "
                           "columns; --lenient reads them by pattern", line=lineno,
                           column=start + 7 * k + 1, rule="MET.DATA.COLUMNS")
    toks = line[start:].split()
    if len(toks) != k or any(len(t) > 7 for t in toks):
        raise CorruptError(f"met values off their F7.1 columns and not {k} readable numbers",
                           line=lineno, column=start + 1, rule="MET.DATA.COLUMNS")
    if not any(x["rule"] == "MET.DATA.COLUMNS" for x in notes):
        notes.append({"rule": "MET.DATA.COLUMNS", "line": lineno, "repair": True,
                      "message": "met values off their F7.1 columns read by pattern"})
    return [t.rjust(7) for t in toks]


def read_met(lines, info, eol="lf", lenient=False):
    f = MetFile()
    f.version = info.version
    f.version_str = info.version_str
    f.eol = eol
    records, i = read_header(lines)
    f.header = [r for r in records if r.label not in ("", END)]
    f.types = parse_met_types(f.header)
    n = len(f.types)
    # 2-digit years up to 3.01, 4 digits from 3.02 (rinex300.txt ~2672, rinex301.txt ~2944,
    # rinex302.txt ~4218)
    v2 = info.version < "3.02"
    head = 18 if v2 else 20
    while i < len(lines):
        line = lines[i]
        lineno = i + 1
        if not line.strip():
            if any(x.strip() for x in lines[i:]):
                f.notes.append({"rule": "MET.BLANKLINE", "message": "blank line skipped",
                                "line": lineno, "repair": True})
            i += 1
            continue
        line = line.ljust(head + 7 * min(n, 8))
        if not v2 and not line[1:5].isdecimal() and _looks_v2_epoch(line) and info.version >= "3.02":
            if not lenient:
                raise CorruptError("RINEX 3/4 met epoch written with a 2-digit year (RINEX 2 layout); "
                                   "--lenient reads it", line=lineno, column=2, rule="MET.EPOCH.V2LAYOUT")
            if not any(x["rule"] == "MET.EPOCH.V2LAYOUT" for x in f.notes):
                f.notes.append({"rule": "MET.EPOCH.V2LAYOUT", "line": lineno, "repair": True,
                                "message": "epochs written in the RINEX 2 layout (2-digit year) read as such"})
            v2 = True
            head = 18
            line = line.ljust(head + 7 * min(n, 8))
        if v2:
            y = year4(_int(line[1:3], "year", lineno, 2))
            p = 3
        else:
            y = _int(line[1:5], "year", lineno, 2)
            p = 5
        mo = _int(line[p + 1:p + 3], "month", lineno, p + 2)
        d = _int(line[p + 4:p + 6], "day", lineno, p + 5)
        h = _int(line[p + 7:p + 9], "hour", lineno, p + 8)
        mi = _int(line[p + 10:p + 12], "minute", lineno, p + 11)
        s = _int(line[p + 13:p + 15], "second", lineno, p + 14)
        k = min(n, 8)
        vals = _met_values(line, head, k, lineno, lenient, f.notes)
        i += 1
        while len(vals) < n:
            if i >= len(lines):
                raise CorruptError("file ends inside a met epoch", line=len(lines), rule="MET.TRUNCATED")
            c = lines[i].ljust(4 + 70)
            if c[0:4].strip():
                raise CorruptError("expected a met continuation line", line=i + 1, rule="MET.CONT")
            k = min(10, n - len(vals))
            vals.extend(_met_values(c, 4, k, i + 1, lenient, f.notes))
            i += 1
        for k, v in enumerate(vals):
            t = v.strip()
            if t:
                try:
                    Decimal(t)
                except InvalidOperation:
                    raise CorruptError(f"bad met value {t!r}", line=lineno, rule="MET.VALUE") from None
        import datetime
        try:
            datetime.datetime(y, mo, d, h, mi, min(s, 59))
        except ValueError:
            raise CorruptError(f"bad met epoch {y} {mo} {d} {h} {mi} {s}", line=lineno,
                               rule="MET.EPOCH") from None
        f.epochs.append(MetEpoch((y, mo, d, h, mi, Decimal(s)), vals, lineno))
    return f


def write_met(f, version):
    out = [r.line() for r in f.header]
    out.append(" " * 60 + END)
    v2 = version < "3.02"
    for ep in f.epochs:
        y, mo, d, h, mi, s = ep.time
        stamp = (f" {y % 100:02d}" if v2 else f" {y:4d}") + f" {mo:2d} {d:2d} {h:2d} {mi:2d} {int(s):2d}"
        vals = [v.rjust(7)[-7:] if v.strip() else " " * 7 for v in ep.vals]
        out.append((stamp + "".join(vals[:8])).rstrip())
        for k in range(8, len(vals), 10):
            out.append(("    " + "".join(vals[k:k + 10])).rstrip())
    return out
