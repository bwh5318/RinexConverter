"""RINEX observation files: model, readers (RINEX 2 and 3/4 layouts) and writers.

Values are never turned into floats. Each satellite record keeps its
observations as the original 16-character fields (F14.3 value, LLI, SSI),
concatenated in the order of the observation types in force at that epoch.
That makes carrying a value between versions an exact copy (both layouts use
F14.3, rinex211.txt Table A2; rinex305.txt Table A3).

Layout rules (PLAN §3.4):
  RINEX 2: 5 observations per data line, 12 satellites per epoch line
           (32X continuation), 9 obs types per header line.
  RINEX 3/4: one unwrapped line per satellite, 13 obs types per header line.
"""

import re
from decimal import Decimal, InvalidOperation

from .errors import CorruptError
from .header import END, HeaderRecord, read_header

FIELD = 16
BLANK = " " * FIELD
_ZERO_CHARS = "0.+- "
# one or more F14.3+LLI+SSI fields; a short last field (trailing blanks stripped) is fine
_FIELDS_OK = re.compile(r"(?:[ 0-9.+-]{14}[ 0-9]{2})*(?:[ 0-9.+-]{0,14}|[ 0-9.+-]{14}[ 0-9]{0,2})")
_VALUE_OK = re.compile(r" *[+-]?(?:\d+\.?\d*|\.\d+) *| *")


def _bad_field(body, lineno, col0):
    for k in range(0, len(body), FIELD):
        f = body[k:k + FIELD]
        if not _VALUE_OK.fullmatch(f[:14]) or not all(ch in " 0123456789" for ch in f[14:16]):
            raise CorruptError(f"bad observation field {f!r}", line=lineno, column=col0 + k,
                               rule="OBS.DATA.FIELD")
    raise CorruptError("bad observation field", line=lineno, rule="OBS.DATA.FIELD")


class ObsTypes:
    """Observation types in force: a RINEX 2 global list or RINEX 3/4 per-system lists."""

    __slots__ = ("layout", "v2", "sys", "_key")

    def __init__(self, layout, v2=(), sys=None):
        self.layout = layout
        self.v2 = tuple(v2)
        self.sys = {k: tuple(v) for k, v in (sys or {}).items()}
        self._key = None

    @property
    def key(self):
        """A content key: equal type lists give equal keys, whichever pass parsed them."""
        if self._key is None:
            self._key = (self.layout, self.v2, tuple(sorted(self.sys.items())))
        return self._key

    def codes(self, system):
        if self.layout == "v2":
            return self.v2
        return self.sys.get(system, ())

    def __eq__(self, other):
        return (isinstance(other, ObsTypes) and self.layout == other.layout
                and self.v2 == other.v2 and self.sys == other.sys)

    def __repr__(self):
        return f"ObsTypes({self.layout!r}, v2={self.v2!r}, sys={self.sys!r})"


class Epoch:
    """One epoch record.

    time:    (year, month, day, hour, minute, Decimal seconds) or None (event without epoch)
    flag:    0..6
    clock:   Decimal receiver clock offset, or None
    sats:    satellite ids ('G01'), for flags 0, 1 and 6
    data:    per satellite, the concatenated 16-char fields for types.codes(sat[0])
    records: header records carried by an event (flags 2-5)
    types:   the ObsTypes in force for this epoch's data
    """

    __slots__ = ("time", "flag", "clock", "sats", "data", "records", "types", "lineno")

    def __init__(self, time, flag, clock=None, sats=None, data=None, records=None,
                 types=None, lineno=None):
        self.time = time
        self.flag = flag
        self.clock = clock
        self.sats = sats if sats is not None else []
        self.data = data if data is not None else []
        self.records = records if records is not None else []
        self.types = types
        self.lineno = lineno

    def __repr__(self):
        return f"Epoch({self.time}, flag={self.flag}, nsat={len(self.sats)}, nrec={len(self.records)})"


class ObsFile:
    """An observation file. Epochs are read lazily: `iter_epochs()` parses them from the
    source bytes each time it is called (the converter makes two passes, PLAN §3.4), so a
    large file is never held as a model. `epochs` materialises the list for small files."""

    def __init__(self):
        self.version = None
        self.version_str = None
        self.system = " "        # RINEX VERSION / TYPE col 41
        self.header = []         # HeaderRecords, END OF HEADER excluded
        self.types = None        # ObsTypes from the header
        self.eol = "lf"
        self.notes = []          # reader repairs/warnings: dicts(rule, message, line)
        self.skipped_text = 0    # data-section lines with text no field covers (_skipped)
        self._epochs = []        # a materialised list, or None while only the source is held
        self._source = None      # (payload bytes, data byte offset, data line number, lenient)
        self._read_once = False
        self._gen = None         # a one-shot epoch generator (converter output)

    @property
    def epochs(self):
        if self._epochs is None:
            self._epochs = list(self.iter_epochs())
        return self._epochs

    @epochs.setter
    def epochs(self, value):
        self._epochs = value

    def iter_epochs(self):
        """Epochs in file order; parsed from the source bytes when the file was read."""
        if self._gen is not None:
            g, self._gen = self._gen, None
            yield from g
            return
        if self._epochs is not None:
            yield from self._epochs
            return
        payload, pos, lineno, lenient = self._source
        cur = LineCursor(payload, pos, lineno)
        notes = None if self._read_once else self.notes
        gen = _iter_v2 if self.version < "3" else _iter_v3
        yield from gen(self, cur, lenient, notes)
        self._read_once = True

    @property
    def layout(self):
        return "v2" if self.version < "3" else "v3"

    def records(self, label):
        return [r for r in self.header if r.label == label]

    def first(self, label):
        for r in self.header:
            if r.label == label:
                return r
        return None


class LineCursor:
    """Lines of a payload (bytes) from byte offset `pos`, decoded latin-1 a chunk at a time;
    a CR before the LF is dropped. `lineno` is the 1-based number of the last line read."""

    CHUNK = 1 << 22

    def __init__(self, payload, pos=0, lineno=0):
        self.p = payload
        self.pos = pos
        self.buf = []
        self.k = 0
        self.lineno = lineno

    def _fill(self):
        p = self.p
        n = len(p)
        if self.pos >= n:
            return False
        stop = min(n, self.pos + self.CHUNK)
        if stop < n:
            j = p.rfind(b"\n", self.pos, stop)
            if j < 0:
                j = p.find(b"\n", stop)
            stop = n if j < 0 else j + 1
        text = p[self.pos:stop].decode("latin-1")
        self.pos = stop
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if "\r" in text:
            lines = [x[:-1] if x.endswith("\r") else x for x in lines]
        self.buf = self.buf[self.k:] + lines
        self.k = 0
        return True

    def next(self):
        """The next line, or None at the end."""
        if self.k >= len(self.buf) and not self._fill():
            return None
        line = self.buf[self.k]
        self.k += 1
        self.lineno += 1
        return line

    def has(self, m):
        """True if at least m more lines remain."""
        while len(self.buf) - self.k < m:
            if not self._fill():
                return False
        return True


def header_lines(payload):
    """(header lines through END OF HEADER, byte offset of the first data line)."""
    out = []
    pos = 0
    n = len(payload)
    while pos < n:
        j = payload.find(b"\n", pos)
        end = n if j < 0 else j
        line = payload[pos:end].decode("latin-1")
        if line.endswith("\r"):
            line = line[:-1]
        out.append(line)
        pos = end + 1
        if line[60:80].strip() == END:
            return out, min(pos, n)
    return out, n


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def is_missing_value(field):
    """True if the F14.3 value part of a field is blank or zero (both mean missing:
    rinex211.txt ~1288, rinex305.txt §6.7)."""
    # blank, or only zeros, a point and a sign: "0.000", ".000", "-0.000"
    return not field[:14].strip(_ZERO_CHARS)


def norm_sat(s, default_sys="G", lineno=None):
    """'G 1', 'G01', ' 1' -> 'G01'."""
    sysc = s[0:1]
    num = s[1:3].strip()
    if sysc == " " or sysc == "":
        sysc = default_sys
    if not num.isdecimal():
        raise CorruptError(f"bad satellite id {s!r}", line=lineno, rule="OBS.SAT")
    return f"{sysc.upper()}{int(num):02d}"


def _dec(s, what, lineno, column):
    t = s.strip()
    if not t:
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        d = None
    if d is None or not d.is_finite():
        raise CorruptError(f"bad number {t!r} in {what}", line=lineno, column=column,
                           rule="OBS.NUMBER")
    return d


def _int(s, what, lineno, column):
    t = s.strip()
    if not t:
        return None
    if not (t.isdecimal() or (t[0] == "-" and t[1:].isdecimal())):
        raise CorruptError(f"bad integer {t!r} in {what}", line=lineno, column=column,
                           rule="OBS.INTEGER")
    return int(t)


def year4(y2):
    """2-digit year -> 4-digit: 80-99 -> 19xx, 00-79 -> 20xx (rinex211.txt §6.5)."""
    return 1900 + y2 if y2 >= 80 else 2000 + y2


# ---------------------------------------------------------------------------
# header parsing
# ---------------------------------------------------------------------------

def parse_v2_types(records):
    """The # / TYPES OF OBSERV list from a sequence of header records, or None."""
    types = None
    expected = None
    for r in records:
        if r.label != "# / TYPES OF OBSERV":
            continue
        cnt = r.content[0:6].strip()
        if cnt:
            if types is not None and expected is not None and len(types) >= expected:
                # A second, complete definition: the later one wins.
                pass
            expected = _int(cnt, "# / TYPES OF OBSERV", r.lineno, 1)
            types = []
        elif types is None:
            raise CorruptError("# / TYPES OF OBSERV continuation without count", line=r.lineno,
                               rule="HDR.OBSTYPES")
        types.extend(r.content[6:60].split())
    if types is None:
        return None
    if len(types) != expected:
        raise CorruptError(f"# / TYPES OF OBSERV declares {expected} types, lists {len(types)}",
                           line=None, rule="HDR.OBSTYPES.COUNT")
    return types


def _v3_codes(c, want, lineno):
    """The A3 codes of one SYS / # / OBS TYPES line, read as 13(1X,A3) from column 7
    (rinex305.txt Table A2), so a blank attribute ('L1 ' in 3.00/3.01, rinex301.txt §5.1)
    survives. A line whose codes are not on that grid is read by blanks instead."""
    c = c.ljust(60)
    n = min(13, max(want, 0))
    grid = [c[7 + 4 * k:10 + 4 * k] for k in range(n)]
    on_grid = all(c[6 + 4 * k] == " " and g[0:2].strip() and g[0] != " " for k, g in enumerate(grid))
    rest = c[7 + 4 * n:60].strip() if n < 13 else ""
    if on_grid and not rest:
        return grid
    return [x if len(x) == 3 else x.ljust(3) if len(x) == 2 else x for x in c[6:60].split()]


def parse_v3_types(records):
    """{system: [codes]} from SYS / # / OBS TYPES records (a subset of systems is allowed)."""
    out = {}
    cur = None
    expected = 0
    for r in records:
        if r.label != "SYS / # / OBS TYPES":
            continue
        c = r.content
        s = c[0:1]
        if s.strip():
            if cur is not None and len(out[cur]) != expected:
                raise CorruptError(f"SYS / # / OBS TYPES for {cur} declares {expected} types, "
                                   f"lists {len(out[cur])}", line=r.lineno, rule="HDR.OBSTYPES.COUNT")
            cur = s.upper()
            expected = _int(c[3:6], "SYS / # / OBS TYPES", r.lineno, 4) or 0
            out[cur] = []
        elif cur is None:
            raise CorruptError("SYS / # / OBS TYPES continuation without system", line=r.lineno,
                               rule="HDR.OBSTYPES")
        out[cur].extend(_v3_codes(c, expected - len(out[cur]), r.lineno))
    if cur is not None and len(out[cur]) != expected:
        raise CorruptError(f"SYS / # / OBS TYPES for {cur} declares {expected} types, "
                           f"lists {len(out[cur])}", rule="HDR.OBSTYPES.COUNT")
    for s, codes in out.items():
        for code in codes:
            if len(code) != 3 or not code[0:2].strip() or " " in code[0:2]:
                raise CorruptError(f"bad observation code {code!r} for system {s}",
                                   rule="HDR.OBSTYPES.CODE")
    return out


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------

def read_obs(lines, info, eol="lf", lenient=False):
    """Parse an observation file from a list of lines (small files, tests)."""
    payload = ("\n".join(lines) + "\n").encode("latin-1") if lines else b""
    return read_obs_payload(payload, info, eol, lenient)


def read_obs_payload(payload, info, eol="lf", lenient=False, materialise=False):
    """An ObsFile over plain RINEX bytes: the header is parsed now, the epochs on demand
    (`iter_epochs`). The data are checked once, here, so that a corrupt file is refused
    before any conversion starts."""
    f = ObsFile()
    f.version = info.version
    f.version_str = info.version_str
    f.system = info.system or " "
    f.eol = eol
    hlines, pos = header_lines(payload)
    records, i = read_header(hlines)
    blank = [r for r in records if r.label == "" and not r.content.strip()]
    if blank:
        f.notes.append({"rule": "HDR.BLANKLINE", "message": f"{len(blank)} blank header line(s) dropped",
                        "line": blank[0].lineno, "repair": True})
    f.header = [r for r in records if r.label not in ("", END)]
    if info.major == 2:
        v2 = parse_v2_types(f.header)
        if v2 is None:
            raise CorruptError("no # / TYPES OF OBSERV record", rule="HDR.OBSTYPES.MISSING")
        f.types = ObsTypes("v2", v2=v2)
    else:
        v3 = parse_v3_types(f.header)
        if not v3:
            raise CorruptError("no SYS / # / OBS TYPES record", rule="HDR.OBSTYPES.MISSING")
        f.types = ObsTypes("v3", sys=v3)
    f._source = (payload, pos, len(hlines), lenient)
    f._epochs = None
    if materialise:
        f._epochs = list(f.iter_epochs())
    return f


def _default_sys(f):
    s = f.system.strip()
    return s if s and s != "M" else "G"


def _note(notes, rule, message, line):
    if notes is not None:
        notes.append({"rule": rule, "message": message, "line": line, "repair": True})


def _skipped(f, notes, lineno):
    """A data-section line holds non-blank text in columns no field of its record covers
    (RINEX 2: past column 80, past the last declared observation field, columns 33-68 of an
    event line, past column 68 of a satellite-list continuation: rinex211.txt Table A2;
    RINEX 3/4: past the last field of a satellite record, the reserved columns 36-41 or past
    column 62 of an EPOCH record, before 4.02 past column 56: rinex305.txt / rinex_4.02.txt
    Table A3, the picosecond field being 4.02's). Only --lenient
    gets this far (the validator calls it damage: engine._refuse_damage); the text is
    dropped, every such line is counted once (ObsFile.skipped_text, claimed by the converter
    as data-text-dropped) and the first is noted as a repair (PLAN section 1 clause 9:
    '--lenient repairs what it can and reports each repair'; round 32)."""
    if notes is None:
        return                       # counted on the first read only
    f.skipped_text += 1
    if f.skipped_text == 1:
        _note(notes, "OBS.DATA.SKIPPED-TEXT", "text in columns no field of the record covers "
              "dropped (each such line is counted in loss data-text-dropped)", lineno)


def _iter_v2(f, cur, lenient, notes):
    types = f.types
    ntypes = len(types.v2)
    nlines = max(1, -(-ntypes // 5))
    width = FIELD * ntypes
    dsys = _default_sys(f)
    blank_at = None
    while True:
        line = cur.next()
        if line is None:
            return
        lineno = cur.lineno
        if not line.strip():
            if blank_at is None:
                blank_at = lineno
            continue
        if blank_at is not None:
            _note(notes, "OBS.BLANKLINE", "blank line between epochs skipped", blank_at)
            blank_at = None
        line = line.ljust(80)
        flag = _int(line[26:29], "epoch flag", lineno, 29)
        if flag is None or not 0 <= flag <= 6:
            raise CorruptError(f"bad epoch flag {line[26:29]!r}", line=lineno, column=29,
                               rule="OBS.EPOCH.FLAG")
        nsat = _int(line[29:32], "number of satellites", lineno, 30) or 0
        if line[0:26].strip():
            yy = _int(line[0:3], "year", lineno, 2)
            mo = _int(line[3:6], "month", lineno, 5)
            dd = _int(line[6:9], "day", lineno, 8)
            hh = _int(line[9:12], "hour", lineno, 11)
            mi = _int(line[12:15], "minute", lineno, 14)
            sec = _dec(line[15:26], "seconds", lineno, 16)
            if None in (yy, mo, dd, hh, mi, sec):
                raise CorruptError("incomplete epoch time", line=lineno, rule="OBS.EPOCH.TIME")
            _check_time(yy, mo, dd, hh, mi, sec, lineno)
            t = (year4(yy), mo, dd, hh, mi, sec)
        else:
            if flag < 2 or flag == 6:
                raise CorruptError("epoch time missing", line=lineno, rule="OBS.EPOCH.TIME")
            t = None
        if 2 <= flag <= 5:
            # the EPOCH/SAT or EVENT FLAG record keeps its receiver clock offset (F12.9,
            # columns 69-80, optional: rinex211.txt Table A2) for events too
            clock = _dec(line[68:80], "receiver clock offset", lineno, 69)
            if line[32:68].strip() or line[80:].strip():
                _skipped(f, notes, lineno)
            recs = []
            for _ in range(nsat):
                x = cur.next()
                if x is None:
                    raise CorruptError("file ends inside an event record", line=cur.lineno,
                                       rule="OBS.TRUNCATED")
                recs.append(HeaderRecord.from_line(x, cur.lineno))
            ep = Epoch(t, flag, clock, records=recs, types=types, lineno=lineno)
            # header records after every event flag 2-5 hold from there on ('Header records now
            # allowed after all epoch flags >1', rinex211.txt section 0.4 l.241-242; rinex305.txt
            # section 6.5 p.42); Astra round 39: only flags 3/4 were applied
            if 2 <= flag <= 5:
                newv2 = parse_v2_types(recs)
                if newv2 is not None:
                    types = ObsTypes("v2", v2=newv2)
                    ntypes = len(newv2)
                    nlines = max(1, -(-ntypes // 5))
                    width = FIELD * ntypes
                ep.types = types
            yield ep
            continue
        clock = _dec(line[68:80], "receiver clock offset", lineno, 69)
        if line[80:].strip():
            _skipped(f, notes, lineno)
        sats = []
        satfield = line[32:68]
        k = 0
        while True:
            for j in range(12):
                if k >= nsat:
                    break
                sats.append(norm_sat(satfield[3 * j:3 * j + 3], dsys, lineno))
                k += 1
            if k >= nsat:
                break
            cont = cur.next()
            if cont is None:
                if lenient:
                    _note(notes, "OBS.TRUNCATED", "partial last epoch dropped", lineno)
                    return
                raise CorruptError("file ends inside a satellite list", line=cur.lineno,
                                   rule="OBS.TRUNCATED")
            cont = cont.ljust(80)
            if cont[0:32].strip():
                raise CorruptError("expected a satellite-list continuation line", line=cur.lineno,
                                   rule="OBS.EPOCH.CONT")
            if cont[68:].strip():
                _skipped(f, notes, cur.lineno)
            satfield = cont[32:68]
        if not cur.has(nsat * nlines):
            if lenient:
                _note(notes, "OBS.TRUNCATED", "partial last epoch dropped", lineno)
                return
            raise CorruptError("file ends inside an epoch", line=cur.lineno, rule="OBS.TRUNCATED")
        data = []
        last_w = width - 80 * (nlines - 1)       # columns of fields on a record's last line
        for _ in range(nsat):
            if nlines == 1:
                rec = cur.next()
                if lenient and len(rec) > width and rec[width:].strip():
                    _skipped(f, notes, cur.lineno)
                    rec = rec[:width]
            else:
                parts = []
                for j in range(nlines):
                    x = cur.next()
                    lim = 80 if j < nlines - 1 else last_w
                    if len(x) > lim and x[lim:].strip():
                        if lenient:
                            # (it was cut at column 80 unreported: round 32)
                            _skipped(f, notes, cur.lineno)
                            x = x[:lim]
                        elif x[80:].strip():
                            _skipped(f, notes, cur.lineno)   # refused by the validator
                    parts.append(x[:80].ljust(80))
                rec = "".join(parts)
            if not _FIELDS_OK.fullmatch(rec):
                _bad_field(rec, cur.lineno, 1)
            if len(rec) > width:
                if rec[width:].strip():
                    raise CorruptError("more observations than # / TYPES OF OBSERV declares",
                                       line=cur.lineno, rule="OBS.DATA.EXTRA")
                rec = rec[:width]
            else:
                rec = rec.ljust(width)
            data.append(rec)
        yield Epoch(t, flag, clock, sats, data, types=types, lineno=lineno)


def _check_time(y, mo, dd, hh, mi, sec, lineno):
    import datetime
    ok = 0 <= hh <= 23 and 0 <= mi <= 59 and sec.is_finite() and Decimal(0) <= sec < Decimal(61)
    if ok:
        try:
            datetime.date(year4(y) if y < 100 else y, mo, dd)
        except ValueError:
            ok = False
    if not ok:
        raise CorruptError(f"epoch time out of range: {y} {mo} {dd} {hh} {mi} {sec}", line=lineno,
                           rule="OBS.EPOCH.TIME")


def _iter_v3(f, cur, lenient, notes):
    types = f.types
    widths = {s: FIELD * len(c) for s, c in types.sys.items()}
    ps_ok = f.version >= "4.02"
    blank_at = None
    while True:
        line = cur.next()
        if line is None:
            return
        lineno = cur.lineno
        if not line.strip():
            if blank_at is None:
                blank_at = lineno
            continue
        if blank_at is not None:
            _note(notes, "OBS.BLANKLINE", "blank line between epochs skipped", blank_at)
            blank_at = None
        if line[0:1] != ">":
            raise CorruptError("expected an epoch record starting with '>'", line=lineno, column=1,
                               rule="OBS.EPOCH.START")
        # reserved 6X, past the last field, or (before 4.02) the picosecond columns, which
        # only RINEX 4.02 defines (rinex_4.02.txt Table A3; round 32: read as picoseconds in a
        # 3.05 file under --lenient)
        if line[35:41].strip() or line[62:].strip() or (not ps_ok and line[56:62].strip()):
            _skipped(f, notes, lineno)
        line = line.ljust(62)
        if not ps_ok:
            line = line[:56] + " " * 6
        flag = _int(line[29:32], "epoch flag", lineno, 32)
        if flag is None or not 0 <= flag <= 6:
            raise CorruptError(f"bad epoch flag {line[29:32]!r}", line=lineno, column=32,
                               rule="OBS.EPOCH.FLAG")
        nsat = _int(line[32:35], "number of satellites", lineno, 33) or 0
        if line[1:29].strip():
            yy = _int(line[1:6], "year", lineno, 3)
            mo = _int(line[6:9], "month", lineno, 8)
            dd = _int(line[9:12], "day", lineno, 11)
            hh = _int(line[12:15], "hour", lineno, 14)
            mi = _int(line[15:18], "minute", lineno, 17)
            sec = _dec(line[18:29], "seconds", lineno, 19)
            if None in (yy, mo, dd, hh, mi, sec):
                raise CorruptError("incomplete epoch time", line=lineno, rule="OBS.EPOCH.TIME")
            _check_time(yy, mo, dd, hh, mi, sec, lineno)
            ps = line[56:62]
            if ps.strip():
                d = ps.strip()
                if ps[0] != " " or len(d) != 5 or not d.isdecimal():
                    raise CorruptError(f"bad picosecond extension {ps!r}", line=lineno, column=57,
                                       rule="OBS.EPOCH.PS")
                sec = sec + Decimal(int(d)).scaleb(-12)
            t = (yy, mo, dd, hh, mi, sec)
        else:
            if flag < 2 or flag == 6:
                raise CorruptError("epoch time missing", line=lineno, rule="OBS.EPOCH.TIME")
            t = None
        if 2 <= flag <= 5:
            # the EPOCH record, shared by every flag, holds the receiver clock offset (F15.12,
            # columns 42-56, optional: rinex305.txt Table A3 p.59; rinex_4.02.txt Table A3)
            clock = _dec(line[41:56], "receiver clock offset", lineno, 42)
            recs = []
            for _ in range(nsat):
                x = cur.next()
                if x is None:
                    raise CorruptError("file ends inside an event record", line=cur.lineno,
                                       rule="OBS.TRUNCATED")
                recs.append(HeaderRecord.from_line(x, cur.lineno))
            ep = Epoch(t, flag, clock, records=recs, types=types, lineno=lineno)
            if 2 <= flag <= 5:                       # (every event flag: see _iter_v2)
                new = parse_v3_types(recs)
                if new:
                    merged = dict(types.sys)
                    merged.update(new)
                    types = ObsTypes("v3", sys=merged)
                    widths = {s: FIELD * len(c) for s, c in types.sys.items()}
                ep.types = types
            yield ep
            continue
        clock = _dec(line[41:56], "receiver clock offset", lineno, 42)
        if not cur.has(nsat):
            if lenient:
                _note(notes, "OBS.TRUNCATED", "partial last epoch dropped", lineno)
                return
            raise CorruptError("file ends inside an epoch", line=cur.lineno, rule="OBS.TRUNCATED")
        sats = []
        data = []
        for _ in range(nsat):
            rec = cur.next()
            i = cur.lineno
            if rec[0:1] == ">":
                raise CorruptError(f"epoch declares {nsat} satellites but has fewer", line=i,
                                   rule="OBS.EPOCH.NSAT")
            sat = norm_sat(rec[0:3], "G", i)
            w = widths.get(sat[0])
            if w is None:
                raise CorruptError(f"satellite {sat} has no SYS / # / OBS TYPES", line=i,
                                   rule="OBS.DATA.SYS")
            body = rec[3:]
            if lenient and len(body) > w and body[w:].strip():
                _skipped(f, notes, i)
                body = body[:w]
            if not _FIELDS_OK.fullmatch(body):
                _bad_field(body, i, 4)
            if len(body) > w:
                if body[w:].strip():
                    raise CorruptError(f"{sat}: more observations than SYS / # / OBS TYPES declares",
                                       line=i, rule="OBS.DATA.EXTRA")
                body = body[:w]
            else:
                body = body.ljust(w)
            sats.append(sat)
            data.append(body)
        yield Epoch(t, flag, clock, sats, data, types=types, lineno=lineno)


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------

def fmt_seconds(sec):
    """F11.7 of the seconds, floored to 0.1 us (rinex_4.02.txt Table A3), plus the
    5-digit picosecond remainder (int)."""
    units = int((sec * 10 ** 12).to_integral_value(rounding="ROUND_FLOOR"))
    hi, ps = divmod(units, 100000)
    whole, frac = divmod(hi, 10 ** 7)
    return f"{whole:3d}.{frac:07d}", ps


def fmt_clock(clock, width, decimals, as_written=False):
    """Receiver clock offset (F12.9 / F15.12) without the leading zero below 1 s, as
    RNX2CRX/CRX2RNX write it, so plain and Hatanaka outputs of a conversion are identical.
    as_written (RINEX 2): a value with no Fw.d form is written with its own digits when they
    fit the field (a ' 123.4567890' read from a RINEX 2 file: obsconv._clock_v2)."""
    from .header import fmt_f
    try:
        s = fmt_f(clock, width, decimals).strip()
    except OverflowError:
        if not as_written:
            raise
        s = f"{Decimal(clock):f}"
        if len(s.lstrip("-")) > 1 and s.lstrip("-").startswith("0."):
            s = s.replace("0.", ".", 1)
        if len(s) > width:
            raise
        return s.rjust(width)
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s.rjust(width)


def epoch_line_v2(ep, sats):
    """The first epoch line (without satellites beyond 12) and continuation lines."""
    if ep.time is None:
        head = " " * 26
    else:
        y, mo, d, h, mi, sec = ep.time
        s, _ = fmt_seconds(sec)
        head = f" {y % 100:02d} {mo:2d} {d:2d} {h:2d} {mi:2d}{s}"
    nsat = len(sats) if ep.flag in (0, 1, 6) else len(ep.records)
    line = f"{head}  {ep.flag:1d}{nsat:3d}"
    out = []
    ids = [f"{s[0]}{int(s[1:]):2d}" for s in sats]
    first = "".join(ids[:12])
    line = line + first
    if ep.clock is not None:
        # every flag: an event line keeps its clock too (rinex211.txt Table A2 gives the
        # EPOCH/SAT or EVENT FLAG record one layout; columns 33-68 stay blank in an event)
        line = line.ljust(68) + fmt_clock(ep.clock, 12, 9, as_written=True)
    out.append(line.rstrip())
    for k in range(12, len(ids), 12):
        out.append((" " * 32 + "".join(ids[k:k + 12])).rstrip())
    return out


def epoch_line_v3(ep, version):
    if ep.time is None:
        head = ">" + " " * 28
        ps = 0
    else:
        y, mo, d, h, mi, sec = ep.time
        s, ps = fmt_seconds(sec)
        head = f"> {y:4d} {mo:02d} {d:02d} {h:02d} {mi:02d}{s}"
    nsat = len(ep.sats) if ep.flag in (0, 1, 6) else len(ep.records)
    line = f"{head}  {ep.flag:1d}{nsat:3d}"
    if ep.clock is not None:
        # every flag: the EPOCH record of an event holds it too (rinex305.txt Table A3 p.59)
        line = line + " " * 6 + fmt_clock(ep.clock, 15, 12)
    if ps and version >= "4.02":
        line = line.ljust(56) + f" {ps:05d}"
    return line.rstrip()


def write_obs(f, version):
    """Lines of an observation file in the layout of `version` (a list; see iter_obs_lines)."""
    return list(iter_obs_lines(f, version))


def iter_obs_lines(f, version):
    """The lines of an observation file in the layout of `version`, one at a time. The
    model must already be in that version's vocabulary (codes, header records)."""
    for r in f.header:
        yield r.line()
    yield " " * 60 + END
    if version < "3":
        for ep in f.iter_epochs():
            if 2 <= ep.flag <= 5:
                yield from epoch_line_v2(ep, [])
                for r in ep.records:
                    yield r.line()
                continue
            yield from epoch_line_v2(ep, ep.sats)
            for rec in ep.data:
                if not rec:
                    yield ""
                    continue
                for k in range(0, len(rec), 80):
                    yield rec[k:k + 80].rstrip()
    else:
        for ep in f.iter_epochs():
            yield epoch_line_v3(ep, version)
            if 2 <= ep.flag <= 5:
                for r in ep.records:
                    yield r.line()
                continue
            for sat, rec in zip(ep.sats, ep.data):
                yield (sat + rec).rstrip()
