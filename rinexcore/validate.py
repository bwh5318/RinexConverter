"""Output validator: a per-version RINEX linter (PLAN.md section 1 clause 2, section 3.8).

    findings = validate(payload)        # payload: plain RINEX bytes (no gzip/.Z/CRX)

``validate`` sniffs the RINEX version and the file kind (observation,
navigation, meteorological) from the first line itself and returns a list of
:class:`Finding`. It raises nothing but :class:`rinexcore.errors.CorruptError`,
and only when the input cannot be read as RINEX at all (empty, compressed, no
``RINEX VERSION / TYPE`` first line, unreadable version or file type).

Each finding has

``severity``  ``"error"``: the file breaks a rule of its own version's spec;
              ``"warning"``: readable but off spec, deprecated or non-standard.
``rule``      a stable identifier, ``VAL.<area>.<what>`` (listed in RULES).
``message``   plain-language text, naming the spec table it comes from.
``line``      1-based line number (``None`` for file-level findings).
``column``    1-based column, or ``None``.
``scope``     ``"header"`` or ``"data"`` (PLAN section 3.8: header-only findings
              are the repairable class, data-level ones are not).
``repairable`` (property) True for the header count/time records that PLAN
              section 1 clause 9 repairs by default (TIME OF FIRST/LAST OBS,
              # OF SATELLITES, PRN / # OF OBS).

The data section is scanned with slicing and precompiled regular expressions,
without building a model, so that a 90 MB observation file takes seconds.
Repeated findings of one rule are capped (``max_per_rule``); a final
``VAL.FINDINGS.SUPPRESSED`` warning says how many were not listed.

Spec sources (pages are the ``===== page N =====`` markers of
``specs/text/*.txt``; the RINEX 2 texts have none and are cited by line):

* observation header: ``rinexcore.spec.obsheader`` (Table A1 of 2.10/2.11/3.00/
  3.01, Table A2 from 3.02) and ``rinexcore.spec.obscodes``;
* observation data: rinex210.txt Table A2 l.959; rinex211.txt Table A2 l.1229;
  rinex300.txt Table A2 p.29; rinex301.txt Table A2 p.33; rinex302.txt Table A3
  p.58; rinex303_update1.txt Table A3 p.62; rinex304.txt Table A3 p.67;
  rinex305.txt Table A3 p.59; rinex_4.00.txt Table A3 p.63; rinex_4.01.txt
  Table A3 p.67; rinex_4.02.txt Table A3 p.69-70;
* navigation: the tables cited at NAV_HEADER, NAV_LINES_V2/V3 and V4_EPH_LINES;
* meteorological: the tables cited at MET_HEADER and MET_TYPES.

Not checked (see docs/DECISIONS.md, "Validator"): INTERVAL against the data
sampling, the contents of free-text records, SYS / PHASE SHIFT, SYS / SCALE
FACTOR, DCBS/PCVS APPLIED and ANTENNA: records beyond their numeric fields,
navigation parameter values (only that they are numbers), the STO text
fields, and anything that needs a second file.

Standard library only (PLAN.md section 0).
"""

import datetime
import re

from rinexcore.errors import CorruptError
from rinexcore.rinexfile import sniff
from rinexcore.spec import obscodes, obsheader

ERROR = "error"
WARNING = "warning"
HEADER = "header"
DATA = "data"

# Header-only findings that PLAN section 1 clause 9 repairs by default.
REPAIRABLE = frozenset((
    "VAL.HDR.TIME-OF-FIRST-OBS",
    "VAL.HDR.TIME-OF-LAST-OBS",
    "VAL.HDR.NUM-SATELLITES",
    "VAL.HDR.PRN-NUM-OBS",
))

RULES = {
    # file and header, all kinds
    "VAL.VERSION.UNSUPPORTED": "version is not one of the 11 write versions; checked against the nearest table",
    "VAL.HDR.VERSION.FORMAT": "RINEX VERSION / TYPE version field is not F9.2",
    "VAL.HDR.TYPE": "file type or satellite-system letter of RINEX VERSION / TYPE not defined",
    "VAL.HDR.END": "no END OF HEADER record",
    "VAL.HDR.BLANK-LINE": "blank line in the header",
    "VAL.HDR.LINE-LENGTH": "header line longer than 80 columns",
    "VAL.HDR.LABEL.MISSING": "header line without a label in columns 61-80",
    "VAL.HDR.LABEL.PLACEMENT": "label not at columns 61-80",
    "VAL.HDR.LABEL.UNKNOWN": "label defined by no RINEX version for this file kind",
    "VAL.HDR.LABEL.VERSION": "label not defined in this version (defined in others)",
    "VAL.HDR.LABEL.SPELLING": "another version's spelling of a label",
    "VAL.HDR.MANDATORY": "mandatory header record missing",
    "VAL.HDR.CONDITIONAL": "conditional header record missing while its condition may hold",
    "VAL.HDR.DEPRECATED": "record the version calls (strongly) deprecated",
    "VAL.HDR.REPEATED": "record that occurs once appears more than once",
    "VAL.HDR.ORDER": "PGM / RUN BY / DATE is not the second header line",
    "VAL.HDR.NUMBER": "numeric header field unreadable",
    "VAL.HDR.SYSTEM.MISMATCH": "satellite-system letter of RINEX VERSION / TYPE disagrees with the data",
    # observation header
    "VAL.HDR.OBSTYPES.COUNT": "declared number of observation types differs from the list",
    "VAL.HDR.OBSTYPES.LAYOUT": "observation types not in their columns",
    "VAL.HDR.OBSTYPES.CONTINUATION": "continuation line without a preceding count line",
    "VAL.HDR.OBSTYPES.CODE": "observation code not defined for this version and system",
    "VAL.HDR.OBSTYPES.DUPLICATE": "observation code or system listed twice",
    "VAL.HDR.OBSTYPES.SYSTEM": "satellite system not defined for this version",
    "VAL.HDR.TIME-SYSTEM": "time system field unknown or missing where compulsory",
    "VAL.HDR.TIME-OF-FIRST-OBS": "TIME OF FIRST OBS differs from the first observation epoch",
    "VAL.HDR.TIME-OF-LAST-OBS": "TIME OF LAST OBS differs from the last observation epoch",
    "VAL.HDR.NUM-SATELLITES": "# OF SATELLITES differs from the data",
    "VAL.HDR.PRN-NUM-OBS": "PRN / # OF OBS differs from the data",
    "VAL.HDR.GLONASS-SLOTS": "GLONASS SLOT / FRQ # count or coverage inconsistent",
    "VAL.HDR.PHASESHIFT": "SYS / PHASE SHIFT entry without a carrier-phase code or unreadable",
    # observation data
    "VAL.OBS.EPOCH.START": "line where an epoch record was expected",
    "VAL.OBS.EPOCH.SYNTAX": "epoch record field unreadable or out of its columns",
    "VAL.OBS.EPOCH.PAD": "zero-padded field (I2.2) written without its zero",
    "VAL.OBS.EPOCH.FORMAT": "readable epoch field not in its printed format (F11.7, F12.9, F15.12)",
    "VAL.OBS.EPOCH.FLAG": "epoch flag not 0-6",
    "VAL.OBS.EPOCH.TIME": "epoch date or time out of range",
    "VAL.OBS.EPOCH.PICOSECONDS": "picosecond field outside RINEX 4.02 or malformed",
    "VAL.OBS.EPOCH.NSAT": "fewer satellite records than the epoch declares",
    "VAL.OBS.EPOCH.SATLIST": "RINEX 2 satellite list malformed",
    "VAL.OBS.EPOCH.ORDER": "epoch not later than the previous one",
    "VAL.OBS.EVENT.COUNT": "number of special records differs from the event's count",
    "VAL.OBS.EVENT.RECORD": "special record without a header label",
    "VAL.OBS.EVENT.MARKER": "new-site event (flag 3) without MARKER NAME",
    "VAL.OBS.DATA.FIELD": "observation field unreadable",
    "VAL.OBS.DATA.FORMAT": "readable observation value not in F14.3 layout",
    "VAL.OBS.DATA.LLI": "loss-of-lock indicator outside 0-7",
    "VAL.OBS.DATA.EXTRA": "more observation fields than the type list declares",
    "VAL.OBS.DATA.SYSTEM": "satellite of a system without an observation-type list",
    "VAL.OBS.DATA.SATID": "satellite identifier malformed or non-standard",
    "VAL.OBS.DATA.DUPLICATE-SAT": "satellite listed twice in one epoch",
    "VAL.OBS.TRUNCATED": "file ends inside a record",
    "VAL.OBS.BLANK-LINE": "blank line between records",
    # navigation
    "VAL.NAV.RECORD.START": "line that cannot start or continue a navigation record",
    "VAL.NAV.RECORD.HEAD": "RINEX 4 record header line malformed",
    "VAL.NAV.RECORD.TYPE": "record or message type not defined for this version and system",
    "VAL.NAV.RECORD.LINES": "record has a different number of lines than its table defines",
    "VAL.NAV.EPOCH": "epoch field of a navigation record unreadable",
    "VAL.NAV.EPOCH.PAD": "zero-padded field (I2.2) written without its zero",
    "VAL.NAV.LAYOUT": "text outside the defined columns of a navigation line",
    "VAL.NAV.NUMBER": "navigation number unreadable",
    "VAL.NAV.NUMBER.EXPONENT": "exponent not zero-padded to two digits",
    "VAL.NAV.NUMBER.FORMAT": "readable number without an exponent (not D19.12)",
    "VAL.NAV.EXPONENT.MIXED": "more than one exponent letter in the file",
    "VAL.NAV.EXPONENT.DEPRECATED": "exponent letter D/d in RINEX 4 (strongly deprecated)",
    "VAL.NAV.SYSTEM": "satellite system not defined for this version or file type",
    "VAL.NAV.BLANK-LINE": "blank line between records",
    # meteorological
    "VAL.MET.TYPES.COUNT": "declared number of met types differs from the list",
    "VAL.MET.TYPES.LAYOUT": "met types not in their columns",
    "VAL.MET.TYPES.CODE": "met observation type not defined in this version",
    "VAL.MET.SENSOR": "SENSOR MOD/TYPE/ACC or SENSOR POS XYZ/H missing for a type",
    "VAL.MET.EPOCH": "met epoch unreadable or out of range",
    "VAL.MET.EPOCH.LAYOUT": "met epoch in the other layout (2-digit vs 4-digit year)",
    "VAL.MET.EPOCH.PAD": "zero-padded year (I2.2) written without its zero",
    "VAL.MET.EPOCH.ORDER": "met epoch not later than the previous one",
    "VAL.MET.VALUE": "met value unreadable",
    "VAL.MET.VALUE.FORMAT": "readable met value not in F7.1 layout, or blank",
    "VAL.MET.CONTINUATION": "missing, extra or malformed continuation line",
    "VAL.MET.BLANK-LINE": "blank line between records",
    "VAL.FINDINGS.SUPPRESSED": "more findings of a rule than listed",
}

DEFAULT_MAX_PER_RULE = 50


class Finding:
    """One validator finding. See the module docstring for the fields."""

    __slots__ = ("severity", "rule", "message", "line", "column", "scope")

    def __init__(self, severity, rule, message, line=None, column=None, scope=DATA):
        self.severity = severity
        self.rule = rule
        self.message = message
        self.line = line
        self.column = column
        self.scope = scope

    @property
    def repairable(self):
        return self.rule in REPAIRABLE

    def as_dict(self):
        return {"severity": self.severity, "rule": self.rule, "message": self.message,
                "line": self.line, "column": self.column, "scope": self.scope,
                "repairable": self.repairable}

    def __repr__(self):
        where = ""
        if self.line is not None:
            where = f" line {self.line}" + (f" col {self.column}" if self.column else "")
        return f"<{self.severity} {self.rule}{where}: {self.message}>"

    def __eq__(self, other):
        return isinstance(other, Finding) and self.as_dict() == other.as_dict()

    def __hash__(self):
        return hash((self.severity, self.rule, self.line, self.column))


def errors(findings):
    """The findings of severity "error"."""
    return [f for f in findings if f.severity == ERROR]


def rules(findings, severity=None):
    """{rule: count} of the findings (optionally of one severity)."""
    out = {}
    for f in findings:
        if severity is None or f.severity == severity:
            out[f.rule] = out.get(f.rule, 0) + 1
    return out


class _Out:
    """Collects findings, at most `cap` per rule."""

    def __init__(self, cap):
        self.items = []
        self.count = {}
        self.cap = cap
        self.over = {}

    def add(self, severity, rule, message, line=None, column=None, scope=DATA):
        n = self.count.get(rule, 0) + 1
        self.count[rule] = n
        if n > self.cap:
            self.over[rule] = (severity, scope)
            return
        self.items.append(Finding(severity, rule, message, line, column, scope))

    def err(self, rule, message, line=None, column=None, scope=DATA):
        self.add(ERROR, rule, message, line, column, scope)

    def warn(self, rule, message, line=None, column=None, scope=DATA):
        self.add(WARNING, rule, message, line, column, scope)

    def finish(self):
        for rule, (severity, scope) in self.over.items():
            extra = self.count[rule] - self.cap
            self.items.append(Finding(WARNING, "VAL.FINDINGS.SUPPRESSED",
                                      f"{extra} more {severity} finding(s) of {rule} not listed",
                                      None, None, scope))
        return self.items


# ---------------------------------------------------------------------------
# lines
# ---------------------------------------------------------------------------
class _Reader:
    """Lines of a payload, decoded latin-1 a chunk at a time (CR before LF dropped).
    `n` is the 1-based number of the last line returned."""

    __slots__ = ("_it", "n", "_back")

    CHUNK = 1 << 22

    def __init__(self, payload):
        self._it = self._lines(payload)
        self.n = 0
        self._back = None

    @classmethod
    def _lines(cls, p):
        pos = 0
        n = len(p)
        while pos < n:
            stop = min(n, pos + cls.CHUNK)
            if stop < n:
                j = p.rfind(b"\n", pos, stop)
                if j < 0:
                    j = p.find(b"\n", stop)
                stop = n if j < 0 else j + 1
            text = p[pos:stop].decode("latin-1")
            pos = stop
            if "\r" in text:
                text = text.replace("\r\n", "\n")
            parts = text.split("\n")
            if parts[-1] == "":
                parts.pop()
            yield from parts

    def next(self):
        if self._back is not None:
            line = self._back
            self._back = None
            self.n += 1
            return line
        line = next(self._it, None)
        if line is not None:
            self.n += 1
        return line

    def back(self, line):
        """Return `line` to the reader (one line of look-ahead)."""
        self._back = line
        self.n -= 1


# ---------------------------------------------------------------------------
# small parsers
# ---------------------------------------------------------------------------
_INT = re.compile(r" *-?\d+ *")
_DEC = re.compile(r" *[+-]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][+-]?\d+)? *")


def _int_or_none(s):
    """int of a blank-padded integer field; None if blank; raises ValueError if not an integer."""
    if not s.strip():
        return None
    if not _INT.fullmatch(s):
        raise ValueError(s)
    return int(s)


def _sec_units(text):
    """Seconds text -> integer units of 1e-7 s (F11.7 / F13.7 have 7 decimals; extra
    decimals are floored). Raises ValueError."""
    t = text.strip()
    if not t:
        raise ValueError(text)
    if "." in t:
        a, b = t.split(".", 1)
    else:
        a, b = t, ""
    if (a and not a.isdecimal()) or (b and not b.isdecimal()) or not (a or b):
        raise ValueError(text)
    return int(a or "0") * 10_000_000 + int((b + "0000000")[:7])


def _fmt_key(key):
    y, mo, d, h, mi, u = key
    return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{u // 10_000_000:02d}.{u % 10_000_000:07d}"


def _year4(y2):
    # rinex211.txt sec. 6.5: 80-99 -> 1980-1999, 00-79 -> 2000-2079
    return 1900 + y2 if y2 >= 80 else 2000 + y2


def _date_ok(y, mo, d, h, mi, units):
    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= units < 61 * 10_000_000):
        return False
    try:
        datetime.date(y, mo, d)
    except ValueError:
        return False
    return True


def _key_ok(key, cache):
    """_date_ok with the last valid (y, mo, d) cached in cache[0]."""
    if not (0 <= key[3] <= 23 and 0 <= key[4] <= 59 and 0 <= key[5] < 61 * 10_000_000):
        return False
    if key[:3] == cache[0]:
        return True
    try:
        datetime.date(key[0], key[1], key[2])
    except ValueError:
        return False
    cache[0] = key[:3]
    return True


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------
TABLE_VERSIONS = obsheader.VERSIONS       # the 11 write versions 2.10 ... 4.02


def _table_version(version):
    """The spec table a file of `version` is checked against."""
    if version in TABLE_VERSIONS:
        return version
    major = version[0]
    if major < "2":
        return "2.10"
    if major > "4":
        return "4.02"
    same = [v for v in TABLE_VERSIONS if v[0] == major]
    lower = [v for v in same if v <= version]
    return lower[-1] if lower else same[0]


# ---------------------------------------------------------------------------
# header labels (navigation and meteorological files; obs labels: obsheader)
# ---------------------------------------------------------------------------
# status: "M" mandatory, "O" optional, "C" conditional, "O-deprecated".
_NAV_V2_GPS = {   # rinex210.txt Table A3 l.1048; rinex211.txt Table A3 l.1319
    "RINEX VERSION / TYPE": "M", "PGM / RUN BY / DATE": "M", "COMMENT": "O", "ION ALPHA": "O",
    "ION BETA": "O", "DELTA-UTC: A0,A1,T,W": "O", "LEAP SECONDS": "O", "END OF HEADER": "M"}
_NAV_V2_GLO = {   # rinex210.txt Table A10 l.1395; rinex211.txt Table A10 l.1674
    "RINEX VERSION / TYPE": "M", "PGM / RUN BY / DATE": "M", "COMMENT": "O",
    "CORR TO SYSTEM TIME": "O", "LEAP SECONDS": "O", "END OF HEADER": "M"}
_NAV_V2_GEO_210 = dict(_NAV_V2_GLO)      # rinex210.txt Table A15 l.1614
_NAV_V2_GEO_211 = {   # rinex211.txt Table A15 l.1893: CORR TO SYSTEM TIME "Obsolete in RINEX
    # Version 2.11", replaced by D-UTC A0,A1,T,W,S,U
    "RINEX VERSION / TYPE": "M", "PGM / RUN BY / DATE": "M", "COMMENT": "O",
    "CORR TO SYSTEM TIME": "O-deprecated", "D-UTC A0,A1,T,W,S,U": "O", "LEAP SECONDS": "O",
    "END OF HEADER": "M"}
_NAV_V3 = {   # rinex300.txt Table A4 p.32; rinex301.txt Table A4 p.36; rinex302.txt Table A5
    # p.62; rinex303_update1.txt Table A5 p.68; rinex304.txt Table A5 p.73; rinex305.txt
    # Table A5 p.65
    "RINEX VERSION / TYPE": "M", "PGM / RUN BY / DATE": "M", "COMMENT": "O",
    "IONOSPHERIC CORR": "O", "TIME SYSTEM CORR": "O", "LEAP SECONDS": "O", "END OF HEADER": "M"}
_NAV_V4 = {   # rinex_4.00.txt Table A7 p.69; rinex_4.01.txt Table A7 p.73; rinex_4.02.txt
    # Table A7 p.75-76 (LEAP SECONDS unstarred, i.e. mandatory)
    "RINEX VERSION / TYPE": "M", "PGM / RUN BY / DATE": "M", "REC # / TYPE / VERS": "O",
    "COMMENT": "O", "MERGED FILE": "O", "DOI": "O", "LICENSE OF USE": "O",
    "STATION INFORMATION": "O", "LEAP SECONDS": "M", "END OF HEADER": "M"}
NAV_HEADER = {"v2-N": _NAV_V2_GPS, "v2-G": _NAV_V2_GLO, "v2-H-2.10": _NAV_V2_GEO_210,
              "v2-H-2.11": _NAV_V2_GEO_211, "v3": _NAV_V3, "v4": _NAV_V4}
_NAV_ALL = set().union(*NAV_HEADER.values())

_MET_V2V3 = {   # rinex210.txt Table A5 l.1154; rinex211.txt Table A5 l.1425; rinex300.txt
    # Table A13 p.38; rinex301.txt Table A13 p.42; rinex302.txt Table A16 p.77;
    # rinex303_update1.txt Table A20 p.89; rinex304.txt Table A20 p.94; rinex305.txt
    # Table A20 p.86. SENSOR POS XYZ/H: "Record required for barometer, recommended
    # for other sensors" (C).
    "RINEX VERSION / TYPE": "M", "PGM / RUN BY / DATE": "M", "COMMENT": "O", "MARKER NAME": "M",
    "MARKER NUMBER": "O", "# / TYPES OF OBSERV": "M", "SENSOR MOD/TYPE/ACC": "M",
    "SENSOR POS XYZ/H": "C", "END OF HEADER": "M"}
_MET_V4 = dict(_MET_V2V3, **{"DOI": "O", "LICENSE OF USE": "O", "STATION INFORMATION": "O"})
# rinex_4.00.txt Table A36 p.108; rinex_4.01.txt Table A36 p.112; rinex_4.02.txt Table A42 p.125
MET_HEADER = {"v2v3": _MET_V2V3, "v4": _MET_V4}
_MET_ALL = set(_MET_V4)

# Met observation types: rinex210.txt l.1184-1191 (PR TD HR ZW ZD ZT); rinex211.txt
# l.1455-1468 adds WD WS RI HI; the same ten in 3.00 (p.38) to 4.02 (p.125-126).
MET_TYPES = {"2.10": frozenset("PR TD HR ZW ZD ZT".split())}
for _v in TABLE_VERSIONS[1:]:
    MET_TYPES[_v] = frozenset("PR TD HR ZW ZD ZT WD WS RI HI".split())

# Labels that may legitimately appear more than once (continuations, per-system or
# per-type records, comments); every other label once.
_REPEATABLE = frozenset((
    "COMMENT", "# / TYPES OF OBSERV", "SYS / # / OBS TYPES", "PRN / # OF OBS",
    "SYS / PHASE SHIFT", "GLONASS SLOT / FRQ #", "WAVELENGTH FACT L1/2", "SYS / DCBS APPLIED",
    "SYS / PCVS APPLIED", "SYS / SCALE FACTOR", "ANTENNA: PHASECENTER", "LICENSE OF USE",
    "STATION INFORMATION", "IONOSPHERIC CORR", "TIME SYSTEM CORR", "SENSOR MOD/TYPE/ACC",
    "SENSOR POS XYZ/H"))

# Obs-label spellings the reader meets that obsheader.canonical_label does not map:
# docs/SPEC_TABLES.md items 10 and 12.
_OBS_ALIASES = {"GLONASS COD/PHS/BIS#": "GLONASS COD/PHS/BIS",
                "ANTENNA:PHASECENTER": "ANTENNA: PHASECENTER"}
_OBS_ALL = set(obsheader.OBS_HEADER)
for _e in obsheader.OBS_HEADER.values():
    _OBS_ALL.update(_e["spelling"].values())
_OBS_ALL.update(_OBS_ALIASES)

# Time systems of TIME OF FIRST OBS: obsheader notes (2.10 l.916-922, 2.11 l.1183-1191,
# 3.00/3.01 Table A1, 3.02 Table A2, 3.03+ Table A2).
TIME_SYSTEMS = {"2.10": {"GPS", "GLO"}, "2.11": {"GPS", "GLO", "GAL"},
                "3.00": {"GPS", "GLO", "GAL"}, "3.01": {"GPS", "GLO", "GAL"},
                "3.02": {"GPS", "GLO", "GAL", "QZS", "BDT"}}
for _v in ("3.03", "3.04", "3.05", "4.00", "4.01", "4.02"):
    TIME_SYSTEMS[_v] = {"GPS", "GLO", "GAL", "QZS", "BDT", "IRN"}

# MARKER TYPE values of fixed markers, for which APPROX POSITION XYZ is required
# (3.05 Table A2 p.53: "Optional for moving platforms"; marker types sec. 5.2.4).
_STATIC_MARKERS = {"GEODETIC", "NON_GEODETIC", "FIXED_BUOY"}

# Numeric header fields: label -> [(start, end, kind)], kind I (integer) or F (decimal), or
# B: a 1X separator that must be blank.
_F3_14 = [(0, 14, "F"), (14, 28, "F"), (28, 42, "F")]
_OBS_NUMERIC = {
    "APPROX POSITION XYZ": _F3_14, "ANTENNA: DELTA H/E/N": _F3_14, "ANTENNA: DELTA X/Y/Z": _F3_14,
    "ANTENNA: B.SIGHT XYZ": _F3_14, "ANTENNA: ZERODIR XYZ": _F3_14, "CENTER OF MASS: XYZ": _F3_14,
    "ANTENNA: ZERODIR AZI": [(0, 14, "F")], "INTERVAL": [(0, 10, "F")],
    "RCV CLOCK OFFS APPL": [(0, 6, "I")], "# OF SATELLITES": [(0, 6, "I")],
    "WAVELENGTH FACT L1/2": [(0, 6, "I"), (6, 12, "I"), (12, 18, "I")],
    "LEAP SECONDS": [(0, 6, "I"), (6, 12, "I"), (12, 18, "I"), (18, 24, "I")],
}
_NAV_NUMERIC_V2 = {   # rinex211.txt Tables A3, A10, A15
    "ION ALPHA": [(2, 14, "F"), (14, 26, "F"), (26, 38, "F"), (38, 50, "F")],
    "ION BETA": [(2, 14, "F"), (14, 26, "F"), (26, 38, "F"), (38, 50, "F")],
    "DELTA-UTC: A0,A1,T,W": [(3, 22, "F"), (22, 41, "F"), (41, 50, "I"), (50, 59, "I")],
    "CORR TO SYSTEM TIME": [(0, 6, "I"), (6, 12, "I"), (12, 18, "I"), (21, 40, "F")],
    # 2D19.12,I7,I5,X,A5,X,I2,2X: the separators around S must be blank, or a provider id
    # longer than A5 runs into U (Sol round 14)
    "D-UTC A0,A1,T,W,S,U": [(0, 19, "F"), (19, 38, "F"), (38, 45, "I"), (45, 50, "I"), (50, 51, "B"),
                            (56, 57, "B"), (57, 59, "I"), (59, 60, "B")],
    "LEAP SECONDS": [(0, 6, "I")],
}
_NAV_NUMERIC_V3 = {   # rinex305.txt Table A5 p.65-67 (same columns 3.00-3.05)
    "IONOSPHERIC CORR": [(5, 17, "F"), (17, 29, "F"), (29, 41, "F"), (41, 53, "F")],
    # A4,1X,D17.10,D16.9,1X,I6,1X,I4,1X,A5,1X,I2,1X
    "TIME SYSTEM CORR": [(5, 22, "F"), (22, 38, "F"), (38, 45, "I"), (45, 50, "I"), (50, 51, "B"),
                         (56, 57, "B"), (57, 59, "I"), (59, 60, "B")],
    "LEAP SECONDS": [(0, 6, "I"), (6, 12, "I"), (12, 18, "I"), (18, 24, "I")],
}
_NAV_NUMERIC_V4 = {   # rinex_4.02.txt Table A7 p.75-76
    "LEAP SECONDS": [(0, 6, "I"), (6, 12, "I"), (12, 18, "I"), (18, 24, "I")],
    "MERGED FILE": [(0, 9, "I")],
}


def _check_leap_system(recs, version, out):
    """LEAP SECONDS time system identifier (A3, columns 25-27, from 3.03): 'only GPS and BDS
    are valid identifiers' in 3.03 and 3.04 (rinex303.txt Table A2 p.60, rinex304.txt Table A2
    p.65), 'only GPS and BDT' in 3.05 (rinex305.txt Table A2 l.3143, Table A5 l.3746), 'only
    GPS' in RINEX 4 (rinex_4.02.txt Table A2 l.3679, Table A7 l.4206); blank means GPS. The
    other version's BeiDou spelling is unambiguous, so it is a warning (Sol round 24)."""
    if version < "3.03":
        return
    bds = "BDS" if version < "3.05" else "BDT"
    valid = {"", "GPS"} if version >= "4" else {"", "GPS", bds}
    for lineno, label, content in recs:
        if label == "LEAP SECONDS":
            ts = content.ljust(60)[24:27].strip()
            if version < "4" and ts in ("BDS", "BDT") and ts != bds:
                out.warn("VAL.HDR.LEAP.SYSTEM", f"LEAP SECONDS time system {ts!r}: RINEX {version} spells "
                         f"BeiDou {bds!r}", lineno, 25, HEADER)
            elif ts not in valid:
                out.err("VAL.HDR.LEAP.SYSTEM", f"LEAP SECONDS time system {ts!r}: RINEX {version} allows "
                        f"{' or '.join(sorted(x for x in valid if x))} (or blank)", lineno, 25, HEADER)


def _check_numeric(recs, table, out):
    for lineno, label, content in recs:
        spec = table.get(label)
        if not spec:
            continue
        c = content.ljust(60)
        for a, b, kind in spec:
            s = c[a:b]
            if kind == "B":
                if s.strip():
                    out.err("VAL.HDR.SEPARATOR", f"{label}: column {a + 1} {s!r} must be blank (a field "
                            "before or after it is too wide)", lineno, a + 1, HEADER)
                continue
            if not s.strip():
                continue
            ok = _INT.fullmatch(s) if kind == "I" else _DEC.fullmatch(s)
            if not ok:
                out.err("VAL.HDR.NUMBER", f"{label}: columns {a + 1}-{b} {s.strip()!r} is not "
                        f"{'an integer' if kind == 'I' else 'a number'}", lineno, a + 1, HEADER)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def validate(payload, max_per_rule=DEFAULT_MAX_PER_RULE):
    """Lint plain RINEX bytes against the spec of their own version. Returns findings."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise CorruptError(f"validate() needs bytes, not {type(payload).__name__}", rule="VAL.INPUT")
    payload = bytes(payload)
    if not payload:
        raise CorruptError("empty file", line=1, rule="VAL.INPUT")
    if payload[:2] in (b"\x1f\x8b", b"\x1f\x9d"):
        raise CorruptError("compressed (gzip/.Z) payload: unwrap it first", line=1, rule="VAL.INPUT")
    rd = _Reader(payload)
    first = rd.next()
    if first[60:80].startswith("CRINEX VERS"):
        raise CorruptError("Hatanaka-compressed payload: expand it first", line=1, rule="VAL.INPUT")
    info = sniff([first])          # raises CorruptError for an unreadable first line
    out = _Out(max(1, int(max_per_rule)))
    tv = _table_version(info.version)
    if tv != info.version:
        out.warn("VAL.VERSION.UNSUPPORTED", f"RINEX {info.version} is not a write version; checked "
                 f"against the RINEX {tv} tables", 1, 1, HEADER)
    if not re.fullmatch(r" *\d\.\d\d", first[0:9]):
        out.warn("VAL.HDR.VERSION.FORMAT", f"version field {first[0:9].strip()!r} is not F9.2 "
                 "(e.g. '     3.05')", 1, 1, HEADER)
    if info.kind == "obs":
        _Obs(rd, first, info, tv, out).run()
    elif info.kind == "nav":
        _Nav(rd, first, info, tv, out).run()
    else:
        _Met(rd, first, info, tv, out).run()
    return out.finish()


# ---------------------------------------------------------------------------
# header reading, shared
# ---------------------------------------------------------------------------
def _read_header(rd, first, out, defined, all_known, canon, spelling):
    """Header lines through END OF HEADER as [(lineno, label, content)], label canonical.
    Returns (records, end_seen). Checks label placement and that each label is defined."""
    recs = [(1, "RINEX VERSION / TYPE", first[:60])]
    _line_length(first, 1, out)
    while True:
        line = rd.next()
        if line is None:
            out.err("VAL.HDR.END", "no END OF HEADER record (every version's header table ends "
                    "with it)", rd.n or None, None, HEADER)
            return recs, False
        lineno = rd.n
        if not line.strip():
            out.warn("VAL.HDR.BLANK-LINE", "blank line in the header", lineno, None, HEADER)
            continue
        raw = line[60:80]
        lab = raw.strip()
        _line_length(line, lineno, out)
        if not lab or (lab not in all_known and canon(lab) not in all_known):
            moved = _find_label(line, all_known)
            if moved is not None:
                lab_m, col = moved
                out.err("VAL.HDR.LABEL.PLACEMENT", f"label {lab_m!r} starts at column {col}, not 61",
                        lineno, col, HEADER)
                lab = lab_m
            elif not lab:
                out.err("VAL.HDR.LABEL.MISSING", "header line without a label in columns 61-80",
                        lineno, 61, HEADER)
                continue
        elif raw[0] == " ":
            out.warn("VAL.HDR.LABEL.PLACEMENT", f"label {lab!r} does not start at column 61",
                     lineno, 61, HEADER)
        c = canon(lab)
        if c in defined:
            want = spelling(c)
            if lab != want:
                out.warn("VAL.HDR.LABEL.SPELLING", f"label {lab!r}: this version spells it {want!r}",
                         lineno, 61, HEADER)
        elif c in all_known:
            out.warn("VAL.HDR.LABEL.VERSION", f"{lab!r} is not a header record of this version",
                     lineno, 61, HEADER)
        else:
            out.warn("VAL.HDR.LABEL.UNKNOWN", f"unknown header label {lab!r}", lineno, 61, HEADER)
        recs.append((lineno, c, line[:60]))
        if c == "END OF HEADER":
            return recs, True


def _line_length(line, lineno, out):
    if len(line) > 80 and line[80:].strip():
        out.warn("VAL.HDR.LINE-LENGTH", "header line longer than 80 columns", lineno, 81, HEADER)


def _find_label(line, known):
    """(label, 1-based column) of a known label that ends the line but does not start at
    column 61. Text before it in columns 61+ (e.g. an overflowing A2 field) is taken as
    shifted content, so 'XYZ COMMENT' also reads as a misplaced COMMENT."""
    best = None
    for lab in known:
        p = line.find(lab, 40)
        if p >= 0 and p != 60 and not line[p + len(lab):].strip():
            if best is None or len(lab) > len(best[0]):
                best = (lab, p + 1)
    return best


def _header_common(recs, out, statuses, tv, kind):
    """Mandatory/repeated/order/deprecated checks from a {label: status} table.
    Conditional labels ("C") are the caller's business."""
    labels = [r[1] for r in recs]
    present = set(labels)
    for lab, st in statuses.items():
        if st == "M" and lab not in present:
            out.err("VAL.HDR.MANDATORY", f"mandatory record {lab!r} missing (RINEX {tv} {kind} "
                    "header table)", None, None, HEADER)
    seen = {}
    for lineno, lab, _ in recs:
        if lab in seen and lab not in _REPEATABLE and lab in statuses:
            if lab == "PGM / RUN BY / DATE" and tv >= "4":
                continue
            out.warn("VAL.HDR.REPEATED", f"{lab!r} appears more than once (first at line "
                     f"{seen[lab]})", lineno, 61, HEADER)
        seen.setdefault(lab, lineno)
    # PGM / RUN BY / DATE "must be the second record(line) in all RINEX files"
    # (rinex_4.00.txt p.22 sec. 5.2.1-5.2.2, Table A2 p.54). RINEX 3 only describes it as
    # "the second header record" (rinex300.txt p.13 sec. 5.8, rinex305.txt p.23 sec. 5.2.2)
    # and its own examples put a COMMENT first (rinex300.txt p.31), so 3.x is not checked.
    if len(recs) > 1 and tv >= "4" and recs[1][1] != "PGM / RUN BY / DATE" \
            and "PGM / RUN BY / DATE" in present:
        out.err("VAL.HDR.ORDER", "PGM / RUN BY / DATE is not the second header line",
                recs[1][0], 61, HEADER)
    if tv >= "4":
        pos = [i for i, r in enumerate(recs) if r[1] == "PGM / RUN BY / DATE"]
        if pos and pos[-1] - pos[0] + 1 != len(pos):
            out.warn("VAL.HDR.ORDER", "additional PGM / RUN BY / DATE lines must follow the second "
                     "line together (rinex_4.00.txt Table A2 p.54)", recs[pos[-1]][0], 61, HEADER)
    for lineno, lab, _ in recs:
        if statuses.get(lab) == "O-deprecated":
            out.warn("VAL.HDR.DEPRECATED", f"{lab!r} is deprecated in RINEX {tv}", lineno, 61, HEADER)


def _system_letter_check(first, allowed, out, what):
    s = first[40:41]
    if s.strip() and s.upper() not in allowed:
        out.warn("VAL.HDR.TYPE", f"satellite system {s!r} in RINEX VERSION / TYPE column 41 is not "
                 f"defined for {what}", 1, 41, HEADER)


# ---------------------------------------------------------------------------
# observation files
# ---------------------------------------------------------------------------
# One F14.3 value right-justified in 14 columns (or blank), then LLI (0-7) and SSI.
_F14 = r"(?: {14}|(?= {0,10}-?\d{0,10}\.\d{3})[ \-\d]{10}\.\d{3})"
_OBS_FIELDS = re.compile(rf"(?:{_F14}[ 0-7][ \d])*(?:{_F14}(?:[ 0-7][ \d]?)?| {{0,13}})?").fullmatch
_F14_STRICT = re.compile(_F14).fullmatch
_VALUE_LENIENT = re.compile(r" *[+-]?(?:\d+\.?\d*|\.\d+) *").fullmatch     # what the reader accepts
# digit columns of an F14.3 value (point at offset 10), and a byte map 1-9 -> 1, else 0
_DIGIT_OFFSETS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13)
_NONZERO = bytes(1 if 0x31 <= c <= 0x39 else 0 for c in range(256))

# epoch records: rinex211.txt Table A2 l.1229 (1X,I2.2,4(1X,I2),F11.7,2X,I1,I3,12(A1,I2),F12.9);
# rinex305.txt Table A3 p.59 / rinex_4.02.txt Table A3 p.69 ('>',1X,I4,4(1X,I2.2),F11.7,2X,I1,I3,
# 6X,F15.12[,1X,I5.5 in 4.02]).
_I3 = r"(?:  \d| \d\d|\d{3})"                     # I3, right-justified
_V2_EPOCH = re.compile(r" \d\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d (?: \d|\d\d|  )\.\d{7}  [0-6]" + _I3).match
_V2_EPOCH_LOOSE = re.compile(r"(?: [ \d]\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d[ \d.]{11}  \d| {26}  [2-5])"
                             + _I3).match
_V3_EPOCH = re.compile(r"> \d{4} \d\d \d\d \d\d \d\d [ \d]\d\.\d{7}  [0-6]" + _I3).match
_V2_CLOCK = re.compile(r" *-?\d*\.\d{9}").fullmatch
_V3_CLOCK = re.compile(r" *-?\d*\.\d{12}").fullmatch
_SEC_F11_7 = re.compile(r" *\d{0,3}\.\d{7}").fullmatch
_V2_SATID = re.compile(r"[A-Z ][ \d]\d").fullmatch

_BATCH = 1024


class _Obs:
    def __init__(self, rd, first, info, tv, out):
        self.rd = rd
        self.first = first
        self.info = info
        self.tv = tv
        self.out = out
        self.v2 = tv < "3"
        self.dsys = info.system.strip() or "G"
        if self.dsys == "M":
            self.dsys = "G"
        self.systems = obscodes.SYSTEMS[tv]
        # results of the data scan
        self.first_key = None
        self.last_key = None
        self.sats = set()            # flags 0/1/6
        self.data_systems = set()
        self.clock_seen = False
        self.types_changed = False
        self.acc = {}                # (sat, state) -> [count per type]
        self.batches = {}            # (sat, state) -> [bodies]
        self.state_width = []        # state -> (width, nfields)
        self.count_obs = False
        self.complete = True         # False if the data scan stopped early

    # -- header ------------------------------------------------------------
    def run(self):
        tv = self.tv
        defined = set(obsheader.labels_for(tv))

        def canon(lab):
            return obsheader.canonical_label(_OBS_ALIASES.get(lab, lab))

        def spelling(c):
            return obsheader.label_text(tv, c)

        recs, end = _read_header(self.rd, self.first, self.out, defined, _OBS_ALL, canon, spelling)
        self.recs = recs
        allowed = set(self.systems) | {"M"}
        _system_letter_check(self.first, allowed, self.out, f"RINEX {tv} observation files")
        _check_numeric(recs, _OBS_NUMERIC, self.out)
        _check_leap_system(recs, tv, self.out)
        self.header_types(recs)
        self.prn_rec = self.parse_prn(recs)
        self.count_obs = self.prn_rec is not None and self.types_ok
        if end and self.types_ok:
            if self.v2:
                self.scan_v2()
            else:
                self.scan_v3()
        else:
            self.complete = False
        self.header_vs_data(recs, end)

    def header_types(self, recs):
        out = self.out
        if self.v2:
            lines = [(n, c) for n, lab, c in recs if lab == "# / TYPES OF OBSERV"]
            self.v2types = self.parse_v2_types(lines, HEADER) if lines else None
            self.types_ok = bool(self.v2types)
            if self.types_ok:
                self.state_width.append((16 * len(self.v2types), len(self.v2types)))
        else:
            lines = [(n, c) for n, lab, c in recs if lab == "SYS / # / OBS TYPES"]
            self.v3types = self.parse_v3_types(lines, HEADER) if lines else {}
            self.types_ok = bool(self.v3types)
            self.v3state = {s: len(self.state_width) + k for k, s in enumerate(self.v3types)}
            for s, codes in self.v3types.items():
                self.state_width.append((16 * len(codes), len(codes)))
        if not self.types_ok and lines:
            out.err("VAL.HDR.OBSTYPES.COUNT", "no usable observation-type list; data not checked",
                    lines[0][0], 1, HEADER)

    def parse_v2_types(self, lines, scope):
        """# / TYPES OF OBSERV, I6,9(4X,A2) + 6X,9(4X,A2) (rinex210.txt l.879, rinex211.txt
        l.1135-1142)."""
        out = self.out
        lists = []
        cur = None
        for lineno, c in lines:
            c = c.ljust(60)
            if c[0:6].strip():
                try:
                    n = _int_or_none(c[0:6])
                except ValueError:
                    out.err("VAL.HDR.NUMBER", f"# / TYPES OF OBSERV count {c[0:6].strip()!r} is not an "
                            "integer", lineno, 1, scope)
                    n = None
                cur = [lineno, n, []]
                lists.append(cur)
            elif cur is None:
                out.err("VAL.HDR.OBSTYPES.CONTINUATION", "# / TYPES OF OBSERV continuation line without "
                        "a count line before it", lineno, 1, scope)
                cur = [lineno, None, []]
                lists.append(cur)
            gap = False
            for k in range(9):
                slot = c[6 + 6 * k:12 + 6 * k]
                if not slot.strip():
                    gap = True
                    continue
                if slot[0:4].strip() or slot[4] == " " or gap:
                    out.err("VAL.HDR.OBSTYPES.LAYOUT", f"observation type {slot.strip()!r} not in the "
                            f"4X,A2 field at columns {11 + 6 * k}-{12 + 6 * k}", lineno, 7 + 6 * k, scope)
                    cur[2].append(slot.strip())
                else:
                    cur[2].append(slot[4:6])
        if not lists:
            return None
        for lineno, n, codes in lists:
            if n is not None and n != len(codes):
                out.err("VAL.HDR.OBSTYPES.COUNT", f"# / TYPES OF OBSERV declares {n} types, lists "
                        f"{len(codes)}", lineno, 1, scope)
        if len(lists) > 1:
            out.warn("VAL.HDR.REPEATED", "# / TYPES OF OBSERV defined more than once; the last "
                     "definition is used", lists[1][0], 1, scope)
        codes = lists[-1][2]
        valid = obscodes.V2_HEADER_CODES[self.tv]
        for code in codes:
            if code not in valid:
                # rinex210.txt l.886-897; rinex211.txt l.952-980 (obscodes.V2_HEADER_CODES)
                out.warn("VAL.HDR.OBSTYPES.CODE", f"observation type {code!r} is not defined in RINEX "
                         f"{self.tv} (# / TYPES OF OBSERV, Table A1)", lists[-1][0], 1, scope)
        dup = sorted({c for c in codes if codes.count(c) > 1})
        if dup:
            out.warn("VAL.HDR.OBSTYPES.DUPLICATE", f"observation type(s) {', '.join(dup)} listed twice",
                     lists[-1][0], 1, scope)
        return codes

    def parse_v3_types(self, lines, scope):
        """SYS / # / OBS TYPES, A1,2X,I3,13(1X,A3) + 6X,13(1X,A3) (rinex305.txt Table A2 p.53;
        same in 3.00-4.02)."""
        out = self.out
        tv = self.tv
        lists = {}
        order = []
        cur = None
        for lineno, c in lines:
            c = c.ljust(60)
            s = c[0]
            if s != " ":
                if c[1:3].strip():
                    out.err("VAL.HDR.OBSTYPES.LAYOUT", "SYS / # / OBS TYPES: columns 2-3 must be blank",
                            lineno, 2, scope)
                try:
                    n = _int_or_none(c[3:6])
                except ValueError:
                    out.err("VAL.HDR.NUMBER", f"SYS / # / OBS TYPES count {c[3:6].strip()!r} is not an "
                            "integer", lineno, 4, scope)
                    n = None
                if s in lists:
                    out.err("VAL.HDR.OBSTYPES.DUPLICATE", f"SYS / # / OBS TYPES for system {s} defined "
                            f"twice (first at line {lists[s][0]})", lineno, 1, scope)
                elif s not in self.systems:
                    out.warn("VAL.HDR.OBSTYPES.SYSTEM", f"satellite system {s!r} is not defined in "
                             f"RINEX {tv} ({obscodes.SYSTEMS_CITE.get(tv, '')})", lineno, 1, scope)
                cur = [lineno, n, []]
                lists[s] = cur
                order.append(s)
            else:
                if c[1:6].strip():
                    out.err("VAL.HDR.OBSTYPES.LAYOUT", "SYS / # / OBS TYPES continuation: columns 1-6 "
                            "must be blank (6X,13(1X,A3))", lineno, 2, scope)
                if cur is None:
                    out.err("VAL.HDR.OBSTYPES.CONTINUATION", "SYS / # / OBS TYPES continuation line "
                            "without a system line before it", lineno, 1, scope)
                    continue
            gap = False
            for k in range(13):
                cell = c[6 + 4 * k:10 + 4 * k]
                if not cell.strip():
                    gap = True
                    continue
                if cell[0] != " " or cell[1] == " " or gap:
                    out.err("VAL.HDR.OBSTYPES.LAYOUT", f"observation code {cell.strip()!r} not in the "
                            f"1X,A3 field at columns {8 + 4 * k}-{10 + 4 * k}", lineno, 7 + 4 * k, scope)
                    cur[2].append(cell.strip().ljust(3)[:3])
                else:
                    cur[2].append(cell[1:4])
        result = {}
        valid_pseudo = obscodes.pseudo_obs_codes(tv)
        blank_ok = obscodes.blank_attribute_allowed(tv)
        bds_302 = set(obscodes.BDS_B1_READ_RULE["codes"].values()) if tv == "3.02" else set()
        for s in order:
            lineno, n, codes = lists[s]
            if n is not None and n != len(codes):
                out.err("VAL.HDR.OBSTYPES.COUNT", f"SYS / # / OBS TYPES for {s} declares {n} types, "
                        f"lists {len(codes)}", lineno, 4, scope)
            valid = obscodes.valid_codes(tv, s) if s in self.systems else frozenset()
            if s in self.systems:
                bands = {v[:2] for v in valid}
                for code in codes:
                    if code in valid or code in valid_pseudo:
                        continue
                    if s == "C" and code in bds_302:
                        continue      # rinex303_update1.txt p.24 note: accept 2I/Q/X in 3.02
                    if blank_ok and code[2] == " " and code[:2] in bands:
                        continue      # 3.00/3.01 "unknown tracking mode" (rinex301.txt p.12)
                    out.warn("VAL.HDR.OBSTYPES.CODE", f"observation code {code!r} is not defined for "
                             f"system {s} in RINEX {tv} ({obscodes.CITATIONS.get(tv, {}).get(s, '')})",
                             lineno, 1, scope)
            dup = sorted({c for c in codes if codes.count(c) > 1})
            if dup:
                out.warn("VAL.HDR.OBSTYPES.DUPLICATE", f"system {s}: code(s) {', '.join(dup)} listed "
                         "twice", lineno, 1, scope)
            result[s] = codes
        return result

    def parse_prn(self, recs):
        """PRN / # OF OBS: 3X,A1,I2(.2),9I6 + 6X,9I6. Returns {sat: (lineno, [counts])} or None."""
        lines = [(n, c) for n, lab, c in recs if lab == "PRN / # OF OBS"]
        if not lines:
            return None
        res = {}
        cur = None
        out = self.out
        for lineno, c in lines:
            c = c.ljust(60)
            if c[3:6].strip():
                raw = c[3:6]
                if not _V2_SATID(raw) or not raw[1:].strip().isdecimal():
                    out.err("VAL.HDR.NUMBER", f"PRN / # OF OBS satellite {raw!r} unreadable", lineno, 4,
                            HEADER)
                    cur = None
                    continue
                sat = (raw[0] if raw[0] != " " else self.dsys) + f"{int(raw[1:]):02d}"
                if sat in res:
                    out.err("VAL.HDR.PRN-NUM-OBS", f"PRN / # OF OBS lists {sat} twice", lineno, 4, HEADER)
                cur = res[sat] = (lineno, [])
            elif cur is None:
                out.err("VAL.HDR.PRN-NUM-OBS", "PRN / # OF OBS continuation without a satellite",
                        lineno, 1, HEADER)
                continue
            for k in range(9):
                s = c[6 + 6 * k:12 + 6 * k]
                try:
                    v = _int_or_none(s)
                except ValueError:
                    out.err("VAL.HDR.NUMBER", f"PRN / # OF OBS count {s.strip()!r} is not an integer",
                            lineno, 7 + 6 * k, HEADER)
                    v = None
                cur[1].append(v)
        return res

    # -- data: shared helpers ------------------------------------------------
    def epoch_time(self, key, lineno, flag, prev):
        """Order and first/last bookkeeping for one epoch with a time."""
        if flag <= 1:
            if self.first_key is None:
                self.first_key = key
            self.last_key = key
        if flag <= 1 or flag == 6:
            if prev is not None and key <= prev[0] and not (key == prev[0] and (flag == 6) != (prev[1] == 6)):
                self.out.warn("VAL.OBS.EPOCH.ORDER", f"epoch {_fmt_key(key)} is not later than the "
                              f"previous epoch {_fmt_key(prev[0])}", lineno, 2)
            return (key, flag)
        return prev

    def event_records(self, nrec, flag, lineno):
        """Read `nrec` special records (header lines) after an event epoch (flags 2-5)."""
        rd = self.rd
        out = self.out
        recs = []
        for k in range(nrec):
            x = rd.next()
            if x is None:
                out.err("VAL.OBS.TRUNCATED", f"file ends inside the {nrec} special records of the event "
                        f"at line {lineno}", rd.n, None)
                return recs, False
            if self.looks_like_epoch(x):
                out.err("VAL.OBS.EVENT.COUNT", f"event at line {lineno} announces {nrec} special "
                        f"records, {k} follow", rd.n, 30 if self.v2 else 33)
                rd.back(x)
                return recs, True
            lab = x[60:80].strip()
            if not lab:
                out.err("VAL.OBS.EVENT.RECORD", "special record of an event without a header label "
                        "in columns 61-80", rd.n, 61)
            else:
                c = obsheader.canonical_label(_OBS_ALIASES.get(lab, lab))
                if c not in _OBS_ALL:
                    out.warn("VAL.HDR.LABEL.UNKNOWN", f"unknown label {lab!r} in an event record", rd.n, 61)
                recs.append((rd.n, c, x[:60]))
        if flag == 3 and not any(r[1] == "MARKER NAME" for r in recs):
            # "new site occupation (end of kinem. data) (at least MARKER NAME record follows)"
            # (rinex211.txt Table A2 l.1253; rinex_4.02.txt Table A3 p.69)
            out.err("VAL.OBS.EVENT.MARKER", "new-site event (flag 3) without a MARKER NAME record",
                    lineno, 29 if self.v2 else 32)
        # more records than announced: the next line is a labelled header line, not an epoch
        x = rd.next()
        if x is not None:
            if not self.looks_like_epoch(x) and x[60:80].strip() in _OBS_ALL:
                out.err("VAL.OBS.EVENT.COUNT", f"event at line {lineno} announces {nrec} special "
                        "records, more follow", rd.n, 61)
            rd.back(x)
        return recs, True

    def looks_like_epoch(self, x):
        if self.v2:
            # an epoch line with more than 9 satellites has text in columns 61-68, so
            # "no header label there" is the test, not "columns 61-80 blank"
            return bool(_V2_EPOCH_LOOSE(x)) and x[60:80].strip() not in _OBS_ALL
        return x[:1] == ">"

    def count_body(self, sat, state, body, width):
        key = (sat, state)
        b = self.batches.get(key)
        if b is None:
            b = self.batches[key] = []
        b.append(body.ljust(width))
        if len(b) >= _BATCH:
            self.flush(key)

    def flush(self, key):
        """Count the non-missing values of a batch of records of equal width.

        Every record here passed the fast field check, so each value is blank or an
        F14.3 number right-justified with its point at offset 10. Such a value is an
        observation (not blank, not 0.000: rinex305.txt sec. 6.7) exactly when one of
        its 13 digit columns holds 1-9. Each digit column of the batch is sliced out,
        mapped to bytes 0/1 and OR-ed as a big integer; the popcount is the count."""
        b = self.batches.pop(key, None)
        if not b:
            return
        width, nf = self.state_width[key[1]]
        acc = self.acc.get(key)
        if acc is None:
            acc = self.acc[key] = [0] * nf
        s = "".join(b).encode("latin-1")
        frm = int.from_bytes
        for k in range(nf):
            base = 16 * k
            x = 0
            for off in _DIGIT_OFFSETS:
                x |= frm(s[base + off::width].translate(_NONZERO), "big")
            acc[k] += x.bit_count()

    def count_exact(self, sat, state, body, nf):
        """Per-field count for a record that failed the fast field check."""
        key = (sat, state)
        acc = self.acc.get(key)
        if acc is None:
            acc = self.acc[key] = [0] * nf
        for k in range(nf):
            v = body[16 * k:16 * k + 14]
            if v.strip(" 0.+-"):
                acc[k] += 1

    def fields_slow(self, body, lineno, col0):
        """Diagnose the observation fields of `body` (fast check failed)."""
        out = self.out
        bad = False
        for k in range(0, len(body), 16):
            f = body[k:k + 16]
            v = f[:14]
            col = col0 + k
            if v.strip():
                if len(v) == 14 and _F14_STRICT(v):
                    pass
                elif _VALUE_LENIENT(v):
                    out.warn("VAL.OBS.DATA.FORMAT", f"observation value {v.strip()!r} is not F14.3 "
                             "(right-justified, 3 decimals)", lineno, col)
                else:
                    out.err("VAL.OBS.DATA.FIELD", f"observation value {v.strip()!r} unreadable "
                            "(F14.3)", lineno, col)
                    bad = True
            lli = f[14:15]
            if lli and lli != " ":
                if lli in "89":
                    out.warn("VAL.OBS.DATA.LLI", f"loss-of-lock indicator {lli!r} outside 0-7",
                             lineno, col + 14)
                elif not lli.isdecimal() or not lli.isascii():
                    out.err("VAL.OBS.DATA.FIELD", f"loss-of-lock indicator {lli!r} is not a digit",
                            lineno, col + 14)
                    bad = True
            ssi = f[15:16]
            if ssi and ssi != " " and not (ssi.isdecimal() and ssi.isascii()):
                out.err("VAL.OBS.DATA.FIELD", f"signal-strength indicator {ssi!r} is not a digit",
                        lineno, col + 15)
                bad = True
        return bad

    # -- data: RINEX 3/4 -------------------------------------------------------
    def scan_v3(self):
        rd = self.rd
        out = self.out
        tv = self.tv
        nxt = rd.next
        types = dict(self.v3types)
        state = dict(self.v3state)
        widths = {s: 16 * len(c) for s, c in types.items()}
        ps_ok = tv >= "4.02"
        fields_ok = _OBS_FIELDS
        idmap = {}
        prev = None
        no_types_reported = set()
        dcache = [None]
        count = self.count_obs
        sats_all = self.sats
        while True:
            line = nxt()
            if line is None:
                break
            lineno = rd.n
            if not line.strip():
                out.warn("VAL.OBS.BLANK-LINE", "blank line between epochs", lineno)
                continue
            if line[0] != ">":
                out.err("VAL.OBS.EPOCH.START", "expected an epoch record starting with '>' (more "
                        "satellite records than the epoch declares, or a damaged line)", lineno, 1)
                while True:      # resynchronise on the next epoch
                    line = nxt()
                    if line is None or line[:1] == ">":
                        break
                if line is None:
                    break
                lineno = rd.n
            if _V3_EPOCH(line):
                flag = ord(line[31]) - 48
                nsat = int(line[32:35])
                key = (int(line[2:6]), int(line[7:9]), int(line[10:12]), int(line[13:15]),
                       int(line[16:18]), _sec_units(line[18:29]))
                if not _key_ok(key, dcache):
                    out.err("VAL.OBS.EPOCH.TIME", f"epoch {line[2:29].strip()!r} out of range", lineno, 3)
                    key = None
            else:
                r = self.epoch_slow_v3(line, lineno)
                if r is None:
                    # unusable epoch line: skip to the next one
                    while True:
                        x = nxt()
                        if x is None or x[:1] == ">":
                            break
                    if x is None:
                        break
                    rd.back(x)
                    continue
                flag, nsat, key = r
            if len(line) > 35:
                self.epoch_tail_v3(line, lineno, ps_ok)
            if key is not None:
                prev = self.epoch_time(key, lineno, flag, prev)
            if 2 <= flag <= 5:
                recs, ok = self.event_records(nsat, flag, lineno)
                if not ok:
                    self.complete = False
                    return
                if flag in (3, 4):
                    lines = [(n, c) for n, lab, c in recs if lab == "SYS / # / OBS TYPES"]
                    if lines:
                        new = self.parse_v3_types(lines, DATA)
                        if new:
                            self.types_changed = True
                            if any(c[:1] == "L" for codes in new.values() for c in codes):
                                self.event_phase = True        # for policy 6 (header_vs_data)
                            for s, codes in new.items():
                                types[s] = codes
                                widths[s] = 16 * len(codes)
                                state[s] = len(self.state_width)
                                self.state_width.append((16 * len(codes), len(codes)))
                continue
            counting = count and flag <= 1
            seen = set()
            for k in range(nsat):
                rec = nxt()
                if rec is None:
                    out.err("VAL.OBS.TRUNCATED", f"file ends inside the epoch at line {lineno} "
                            f"({k} of {nsat} satellite records)", rd.n, None)
                    self.complete = False
                    return
                if rec[:1] == ">":
                    out.err("VAL.OBS.EPOCH.NSAT", f"epoch at line {lineno} declares {nsat} satellites, "
                            f"{k} records follow", lineno, 33)
                    rd.back(rec)
                    break
                raw = rec[0:3]
                sat = idmap.get(raw)
                if sat is None:
                    sat = self.satid_v3(raw, rd.n)
                    idmap[raw] = sat
                if not sat:
                    continue
                s = sat[0]
                w = widths.get(s)
                if w is None:
                    if s not in no_types_reported:
                        no_types_reported.add(s)
                        out.err("VAL.OBS.DATA.SYSTEM", f"satellite {sat} of system {s}, which has no "
                                "SYS / # / OBS TYPES record", rd.n, 1)
                    continue
                if sat in seen:
                    out.err("VAL.OBS.DATA.DUPLICATE-SAT", f"{sat} appears twice in the epoch at line "
                            f"{lineno}", rd.n, 1)
                seen.add(sat)
                body = rec[3:]
                if len(body) > w:
                    if body[w:].strip():
                        out.err("VAL.OBS.DATA.EXTRA", f"{sat}: more observation fields than the "
                                f"{w // 16} types of SYS / # / OBS TYPES", rd.n, 4 + w)
                    body = body[:w]
                if fields_ok(body):
                    if counting:
                        self.count_body(sat, state[s], body, w)
                else:
                    self.fields_slow(body, rd.n, 4)
                    if counting:
                        self.count_exact(sat, state[s], body.ljust(w), w // 16)
            if flag <= 1 or flag == 6:
                sats_all.update(seen)
                self.data_systems.update(x[0] for x in seen)

    def satid_v3(self, raw, lineno):
        """Normalised satellite id ('' if unusable) for a RINEX 3/4 record (A1,I2.2)."""
        out = self.out
        s, num = raw[0:1], raw[1:3]
        if not s.isalpha() or not num.strip().isdecimal() or len(num) != 2 or num[1] == " ":
            out.err("VAL.OBS.DATA.SATID", f"satellite identifier {raw!r} unreadable (A1,I2.2)",
                    lineno, 1)
            return ""
        if num[0] == " ":
            out.warn("VAL.OBS.DATA.SATID", f"satellite number {raw!r} not zero-padded (I2.2)", lineno, 2)
        if s not in self.systems:
            out.warn("VAL.OBS.DATA.SATID", f"satellite system {s!r} is not defined in RINEX {self.tv}",
                     lineno, 1)
        return f"{s}{int(num):02d}"

    def epoch_slow_v3(self, line, lineno):
        """Diagnose a RINEX 3/4 epoch line that failed the fast pattern.
        Returns (flag, nsat, key or None), or None if the line is unusable."""
        out = self.out
        x = line.ljust(35)
        bad = False
        fl = x[31]
        if not fl.isdecimal() or not fl.isascii() or x[29:31].strip():
            out.err("VAL.OBS.EPOCH.FLAG", f"epoch flag {x[29:32].strip()!r} is not one of 0-6 in "
                    "column 32", lineno, 32)
            return None
        flag = int(fl)
        if flag > 6:
            out.err("VAL.OBS.EPOCH.FLAG", f"epoch flag {flag} is not one of 0-6", lineno, 32)
            return None
        try:
            nsat = _int_or_none(x[32:35])
        except ValueError:
            nsat = None
        if nsat is None or nsat < 0:
            out.err("VAL.OBS.EPOCH.SYNTAX", f"number of satellites/records {x[32:35]!r} unreadable "
                    "(I3, columns 33-35)", lineno, 33)
            return None
        if not x[1:29].strip():
            if flag < 2:
                out.err("VAL.OBS.EPOCH.SYNTAX", "epoch time missing (allowed only for events, flags "
                        "2-5)", lineno, 3)
            return flag, nsat, None
        for a, b, what in ((1, 2, None), (6, 7, None), (9, 10, None), (12, 13, None), (15, 16, None)):
            if x[a] != " ":
                out.err("VAL.OBS.EPOCH.SYNTAX", f"column {a + 1} of the epoch record must be blank",
                        lineno, a + 1)
                bad = True
        y = x[2:6]
        if not (y.isdecimal() and y.isascii()):
            out.err("VAL.OBS.EPOCH.SYNTAX", f"year {y!r} is not I4 (columns 3-6)", lineno, 3)
            bad = True
        vals = []
        for a, what in ((7, "month"), (10, "day"), (13, "hour"), (16, "minute")):
            f = x[a:a + 2]
            if f.isdecimal() and f.isascii():
                vals.append(int(f))
            elif f[0] == " " and f[1:].isdecimal():
                out.warn("VAL.OBS.EPOCH.PAD", f"{what} {f!r} not zero-padded (I2.2)", lineno, a + 1)
                vals.append(int(f))
            else:
                out.err("VAL.OBS.EPOCH.SYNTAX", f"{what} {f!r} unreadable (I2.2)", lineno, a + 1)
                bad = True
        sec = x[18:29]
        if not _SEC_F11_7(sec):
            if _VALUE_LENIENT(sec) and sec.strip():
                out.warn("VAL.OBS.EPOCH.FORMAT", f"seconds {sec.strip()!r} not F11.7", lineno, 19)
            else:
                out.err("VAL.OBS.EPOCH.SYNTAX", f"seconds {sec.strip()!r} unreadable (F11.7, columns "
                        "19-29)", lineno, 19)
                bad = True
        if bad:
            return flag, nsat, None
        try:
            key = (int(y), vals[0], vals[1], vals[2], vals[3], _sec_units(sec))
        except ValueError:
            out.err("VAL.OBS.EPOCH.SYNTAX", f"seconds {sec.strip()!r} unreadable", lineno, 19)
            return flag, nsat, None
        if not _date_ok(*key):
            out.err("VAL.OBS.EPOCH.TIME", f"epoch {x[2:29].strip()!r} out of range", lineno, 3)
            return flag, nsat, None
        return flag, nsat, key

    def epoch_tail_v3(self, line, lineno, ps_ok):
        out = self.out
        if line[35:41].strip():
            out.err("VAL.OBS.EPOCH.SYNTAX", "columns 36-41 of the epoch record are reserved (6X) and "
                    "must be blank", lineno, 36)
        clk = line[41:56]
        if clk.strip():
            self.clock_seen = True
            if not _V3_CLOCK(clk):
                if _VALUE_LENIENT(clk):
                    out.warn("VAL.OBS.EPOCH.FORMAT", f"receiver clock offset {clk.strip()!r} not F15.12",
                             lineno, 42)
                else:
                    out.err("VAL.OBS.EPOCH.SYNTAX", f"receiver clock offset {clk.strip()!r} unreadable "
                            "(F15.12, columns 42-56)", lineno, 42)
        ps = line[56:62]
        if ps.strip():
            if not ps_ok:
                out.err("VAL.OBS.EPOCH.PICOSECONDS", f"text in columns 57-62 ({ps.strip()!r}); the "
                        "picosecond field exists only from RINEX 4.02 (rinex_4.02.txt Table A3 p.69)",
                        lineno, 57)
            elif not (ps[0] == " " and len(ps) == 6 and ps[1:].isdecimal() and ps.isascii()):
                out.err("VAL.OBS.EPOCH.PICOSECONDS", f"picosecond field {ps!r} is not 1X,I5.5",
                        lineno, 57)
        if line[62:].strip():
            out.err("VAL.OBS.EPOCH.SYNTAX", "text after the last field of the epoch record", lineno, 63)

    # -- data: RINEX 2 ----------------------------------------------------------
    def scan_v2(self):
        rd = self.rd
        out = self.out
        nxt = rd.next
        types = self.v2types
        state = 0
        ntypes = len(types)
        nl = max(1, -(-ntypes // 5))
        last_w = 16 * (ntypes - 5 * (nl - 1))
        width = 16 * ntypes
        fields_ok = _OBS_FIELDS
        prev = None
        dcache = [None]
        count = self.count_obs
        pure_gps = self.info.system.strip() in ("", "G")
        idmap = {}
        while True:
            line = nxt()
            if line is None:
                break
            lineno = rd.n
            if not line.strip():
                out.warn("VAL.OBS.BLANK-LINE", "blank line where an epoch record was expected", lineno)
                continue
            if _V2_EPOCH(line):
                flag = ord(line[28]) - 48
                nsat = int(line[29:32])
                y2 = int(line[1:3])
                key = (_year4(y2), int(line[3:6]), int(line[6:9]), int(line[9:12]), int(line[12:15]),
                       _sec_units(line[15:26]))
                if not _key_ok(key, dcache):
                    out.err("VAL.OBS.EPOCH.TIME", f"epoch {line[1:26].strip()!r} out of range", lineno, 2)
                    key = None
            else:
                r = self.epoch_slow_v2(line, lineno)
                if r is None:
                    out.err("VAL.OBS.EPOCH.START", "expected an epoch record (more data lines than the "
                            "epoch declares, or a damaged line)", lineno, 1)
                    while True:
                        x = nxt()
                        if x is None or self.looks_like_epoch(x):
                            break
                    if x is None:
                        break
                    rd.back(x)
                    continue
                flag, nsat, key = r
            if key is not None:
                prev = self.epoch_time(key, lineno, flag, prev)
            if 2 <= flag <= 5:
                if line[32:].strip():
                    out.err("VAL.OBS.EPOCH.SYNTAX", "event record: text after the record count", lineno, 33)
                recs, ok = self.event_records(nsat, flag, lineno)
                if not ok:
                    self.complete = False
                    return
                if flag in (3, 4):
                    lines = [(n, c) for n, lab, c in recs if lab == "# / TYPES OF OBSERV"]
                    if lines:
                        new = self.parse_v2_types(lines, DATA)
                        if new:
                            self.types_changed = True
                            types = new
                            ntypes = len(types)
                            nl = max(1, -(-ntypes // 5))
                            last_w = 16 * (ntypes - 5 * (nl - 1))
                            width = 16 * ntypes
                            state = len(self.state_width)
                            self.state_width.append((width, ntypes))
                continue
            # satellite list, 12(A1,I2) per line, 32X continuation lines
            ids = []
            ln = line
            ln_no = lineno
            k = 0
            while True:
                field = ln[32:68]
                m = min(12, nsat - k)
                for j in range(m):
                    raw = field[3 * j:3 * j + 3]
                    sat = idmap.get(raw)
                    if sat is None:
                        sat = self.satid_v2(raw, ln_no, 33 + 3 * j, pure_gps)
                        idmap[raw] = sat
                    ids.append(sat)
                if field[3 * m:].strip():
                    out.err("VAL.OBS.EPOCH.SATLIST", f"satellite list longer than the {nsat} the epoch "
                            "declares", ln_no, 33 + 3 * m)
                k += m
                tail = ln[68:]
                if ln is line:
                    if tail[:12].strip():
                        self.clock_seen = True
                        clk = tail[:12]
                        if not _V2_CLOCK(clk):
                            if _VALUE_LENIENT(clk):
                                out.warn("VAL.OBS.EPOCH.FORMAT", f"receiver clock offset {clk.strip()!r} "
                                         "not F12.9", ln_no, 69)
                            else:
                                out.err("VAL.OBS.EPOCH.SYNTAX", f"receiver clock offset {clk.strip()!r} "
                                        "unreadable (F12.9, columns 69-80)", ln_no, 69)
                    if tail[12:].strip():
                        out.err("VAL.OBS.EPOCH.SYNTAX", "text after column 80 of the epoch record",
                                ln_no, 81)
                elif tail.strip():
                    out.err("VAL.OBS.EPOCH.SATLIST", "text after column 68 of a satellite-list "
                            "continuation line (32X,12(A1,I2))", ln_no, 69)
                if k >= nsat:
                    break
                ln = nxt()
                if ln is None:
                    out.err("VAL.OBS.TRUNCATED", f"file ends inside the satellite list of the epoch at "
                            f"line {lineno}", rd.n, None)
                    self.complete = False
                    return
                ln_no = rd.n
                if ln[0:32].strip():
                    out.err("VAL.OBS.EPOCH.SATLIST", f"epoch at line {lineno} declares {nsat} "
                            "satellites: expected a continuation line (32X,12(A1,I2))", ln_no, 1)
                    rd.back(ln)
                    ids = None
                    break
            if ids is None:
                continue
            counting = count and flag <= 1
            seen = set()
            for sat in ids:
                rec_lines = []
                for j in range(nl):
                    x = nxt()
                    if x is None:
                        out.err("VAL.OBS.TRUNCATED", f"file ends inside the epoch at line {lineno}",
                                rd.n, None)
                        self.complete = False
                        return
                    xn = rd.n
                    lim = last_w if j == nl - 1 else 80
                    if len(x) > lim:
                        if x[lim:].strip():
                            out.err("VAL.OBS.DATA.EXTRA", f"{sat or '?'}: more observation fields than "
                                    f"the {ntypes} types of # / TYPES OF OBSERV (5 per line)", xn, lim + 1)
                        x = x[:lim]
                    if not fields_ok(x):
                        self.fields_slow(x, xn, 1)
                        rec_lines.append((x, False))
                    else:
                        rec_lines.append((x, True))
                if not sat:
                    continue
                if sat in seen:
                    out.err("VAL.OBS.DATA.DUPLICATE-SAT", f"{sat} appears twice in the epoch at line "
                            f"{lineno}", lineno, 33)
                seen.add(sat)
                if counting:
                    body = "".join(x.ljust(80) for x, _ in rec_lines)[:width]
                    if all(ok for _, ok in rec_lines):
                        self.count_body(sat, state, body, width)
                    else:
                        self.count_exact(sat, state, body.ljust(width), ntypes)
            if flag <= 1 or flag == 6:
                self.sats.update(seen)
                self.data_systems.update(x[0] for x in seen)

    def satid_v2(self, raw, lineno, col, pure_gps):
        """Normalised satellite id ('' if unusable) from a RINEX 2 epoch line (A1,I2)."""
        out = self.out
        if not _V2_SATID(raw) or not raw[1:].strip().isdecimal():
            out.err("VAL.OBS.EPOCH.SATLIST", f"satellite {raw!r} unreadable (A1,I2)", lineno, col)
            return ""
        s = raw[0]
        if s == " ":
            if not pure_gps:
                # "A blank satellite identifier is allowed in pure GPS files only"
                # (rinex211.txt sec. 5.1 l.184)
                out.warn("VAL.OBS.DATA.SATID", f"blank system identifier {raw!r} in a file that is not "
                         "pure GPS", lineno, col)
            s = self.dsys
        elif s not in self.systems:
            out.warn("VAL.OBS.DATA.SATID", f"satellite system {s!r} is not defined in RINEX {self.tv} "
                     f"({obscodes.SYSTEMS_CITE[self.tv]})", lineno, col)
        return f"{s}{int(raw[1:]):02d}"

    def epoch_slow_v2(self, line, lineno):
        """Diagnose a RINEX 2 epoch line that failed the fast pattern. Returns
        (flag, nsat, key or None), or None if the line is not an epoch line at all."""
        out = self.out
        x = line.ljust(32)
        if not self.looks_like_epoch(x):
            return None
        flag = ord(x[28]) - 48
        if flag > 6:
            out.err("VAL.OBS.EPOCH.FLAG", f"epoch flag {flag} is not one of 0-6", lineno, 29)
            return None
        nsat = int(x[29:32])
        if not x[0:26].strip():
            if flag < 2:
                out.err("VAL.OBS.EPOCH.SYNTAX", "epoch time missing (allowed only for events, flags "
                        "2-5)", lineno, 2)
            return flag, nsat, None
        bad = False
        yy = x[1:3]
        if yy[0] == " ":
            out.warn("VAL.OBS.EPOCH.PAD", f"year {yy!r} not zero-padded (I2.2)", lineno, 2)
        sec = x[15:26]
        if not _SEC_F11_7(sec):
            if _VALUE_LENIENT(sec):
                out.warn("VAL.OBS.EPOCH.FORMAT", f"seconds {sec.strip()!r} not F11.7", lineno, 16)
            else:
                out.err("VAL.OBS.EPOCH.SYNTAX", f"seconds {sec.strip()!r} unreadable (F11.7, columns "
                        "16-26)", lineno, 16)
                bad = True
        if bad:
            return flag, nsat, None
        try:
            key = (_year4(int(yy)), int(x[3:6]), int(x[6:9]), int(x[9:12]), int(x[12:15]),
                   _sec_units(sec))
        except ValueError:
            out.err("VAL.OBS.EPOCH.SYNTAX", "epoch time unreadable", lineno, 2)
            return flag, nsat, None
        if not _date_ok(*key):
            out.err("VAL.OBS.EPOCH.TIME", f"epoch {x[1:26].strip()!r} out of range", lineno, 2)
            return flag, nsat, None
        return flag, nsat, key

    # -- header against data -------------------------------------------------------
    def header_vs_data(self, recs, end):
        out = self.out
        tv = self.tv
        present = {r[1] for r in recs}
        statuses = {lab: e["versions"][tv] for lab, e in obsheader.OBS_HEADER.items()
                    if tv in e["versions"]}
        glo = "R" in self.data_systems
        cond = {}
        # GLONASS SLOT / FRQ # (M from 3.02) and GLONASS COD/PHS/BIS (M 3.02-3.05) are
        # required here only when GLONASS data are present: docs/SPEC_TABLES.md item 17
        # (the tables have no "if GLONASS" condition; docs/DECISIONS.md policy).
        for lab in ("GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS"):
            if statuses.get(lab) == "M":
                statuses = dict(statuses)
                statuses[lab] = "M" if glo else "O"
        # SYS / PHASE SHIFT (M in 3.01-3.05) describes phase alignment; rinex305.txt §5.2.12
        # defines its content for files with phases (values, reference signals only, unknown)
        # but none for a file without any phase type: then there is nothing to record and it
        # is not required (docs/DECISIONS.md, Validator policy 6).
        has_phase = any(c[:1] == "L" for codes in (getattr(self, "v3types", None) or {}).values()
                        for c in codes) or getattr(self, "event_phase", False)
        for lab in ("SYS / PHASE SHIFT", "SYS / PHASE SHIFTS"):
            if statuses.get(lab) == "M" and not self.v2 and not has_phase:
                statuses = dict(statuses)
                statuses[lab] = "O"
        for lab, st in statuses.items():
            if st == "C":
                cond[lab] = st
        _header_common(recs, out, statuses, tv, "observation")
        # conditional records
        if "RCV CLOCK OFFS APPL" in cond and self.clock_seen and "RCV CLOCK OFFS APPL" not in present:
            out.warn("VAL.HDR.CONDITIONAL", "receiver clock offsets are reported in the epoch records "
                     "but RCV CLOCK OFFS APPL is missing ('Record required if clock offsets are "
                     "reported'; the table also stars it optional with default 0)", None, None, HEADER)
        if cond.get("APPROX POSITION XYZ") and "APPROX POSITION XYZ" not in present:
            mt = next((c[0:20].strip().upper() for n, lab, c in recs if lab == "MARKER TYPE"), None)
            if mt in _STATIC_MARKERS:
                out.err("VAL.HDR.MANDATORY", f"APPROX POSITION XYZ missing for marker type {mt} (optional "
                        "only for moving platforms)", None, None, HEADER)
            else:
                out.warn("VAL.HDR.CONDITIONAL", "APPROX POSITION XYZ missing (optional only for moving "
                         "platforms)", None, None, HEADER)
        # RINEX VERSION / TYPE system letter vs data
        letter = self.info.system.strip() or ("G" if self.v2 else "")
        if letter and letter != "M" and self.data_systems - {letter}:
            others = "".join(sorted(self.data_systems - {letter}))
            out.err("VAL.HDR.SYSTEM.MISMATCH", f"RINEX VERSION / TYPE says {letter!r} but the data "
                    f"hold satellites of {others} (use 'M' for mixed files)", 1, 41, HEADER)
        if not self.v2 and letter and letter != "M":
            extra = sorted(set(self.v3types) - {letter})
            if extra:
                out.err("VAL.HDR.SYSTEM.MISMATCH", f"RINEX VERSION / TYPE says {letter!r} but SYS / # / "
                        f"OBS TYPES defines {''.join(extra)}", 1, 41, HEADER)
        self.check_times(recs)
        self.check_counts(recs)
        self.check_glonass_slots(recs)
        self.check_phase_shift(recs)

    def check_phase_shift(self, recs):
        """SYS / PHASE SHIFT first lines: A1,1X,A3 carrier phase observation code,1X,F8.5
        (rinex305.txt p.57; the same columns from 3.01). A system with a blank code is the
        3.03+ 'unknown' form; any other code must be a phase code (L + band + attribute)."""
        if self.v2:
            return
        first = False
        for lineno, lab, c in recs:
            if lab not in ("SYS / PHASE SHIFT", "SYS / PHASE SHIFTS"):
                first = False
                continue
            c = c.ljust(60)
            if not c[:60].strip():
                # every defined form names the system, 'unknown' included (rinex302.txt
                # Table A2, p.41-42); a continuation lists satellites (18X,10(1X,A3))
                self.out.err("VAL.HDR.PHASESHIFT", "empty SYS / PHASE SHIFT record: no system, code "
                             "or satellites (rinex302.txt Table A2)", lineno, 1, HEADER)
                continue
            if not c[0:1].strip():
                if not first:
                    self.out.err("VAL.HDR.PHASESHIFT", "SYS / PHASE SHIFT continuation line without "
                                 "a first line", lineno, 1, HEADER)
                continue
            first = True
            code = c[2:5]
            # a blank attribute ('L1 ') where the version allows one (3.00/3.01; Sol round 12)
            blank_ok = code[2] == " " and code[1] != " " and obscodes.blank_attribute_allowed(self.tv)
            if code.strip() and not (code[0] == "L" and code[1:3].strip() and (len(code.strip()) == 3 or blank_ok)):
                self.out.err("VAL.HDR.PHASESHIFT", f"SYS / PHASE SHIFT code {code.strip()!r} is not a "
                             "carrier phase observation code (A3, e.g. 'L1C'; rinex305.txt p.57)",
                             lineno, 3, HEADER)
            val = c[6:14]
            if val.strip() and not _DEC.fullmatch(val):
                self.out.err("VAL.HDR.NUMBER", f"SYS / PHASE SHIFT correction {val.strip()!r} is not a "
                             "number (F8.5)", lineno, 7, HEADER)

    def check_times(self, recs):
        out = self.out
        tv = self.tv
        tsys = {}
        for lab in ("TIME OF FIRST OBS", "TIME OF LAST OBS"):
            rec = next(((n, c) for n, l, c in recs if l == lab), None)
            if rec is None:
                continue
            lineno, c = rec
            c = c.ljust(60)
            try:
                y, mo, d, h, mi = (int(c[6 * k:6 * k + 6]) for k in range(5))
                units = _sec_units(c[30:43])
            except ValueError:
                out.err("VAL.HDR.NUMBER", f"{lab} unreadable (5I6,F13.7,5X,A3)", lineno, 1, HEADER)
                continue
            ts = c[48:51].strip()
            tsys[lab] = (ts, lineno)
            if ts and ts not in TIME_SYSTEMS[tv]:
                out.warn("VAL.HDR.TIME-SYSTEM", f"{lab}: time system {ts!r} is not one of "
                         f"{', '.join(sorted(TIME_SYSTEMS[tv]))} (RINEX {tv})", lineno, 49, HEADER)
            if c[43:48].strip() or c[51:60].strip():
                out.err("VAL.HDR.NUMBER", f"{lab}: text outside the 5I6,F13.7,5X,A3 fields", lineno, 44,
                        HEADER)
            key = (y, mo, d, h, mi, units)
            want = self.first_key if lab == "TIME OF FIRST OBS" else self.last_key
            if self.complete and want is not None and key != want:
                rule = "VAL.HDR.TIME-OF-FIRST-OBS" if lab == "TIME OF FIRST OBS" else "VAL.HDR.TIME-OF-LAST-OBS"
                which = "first" if lab == "TIME OF FIRST OBS" else "last"
                out.err(rule, f"{lab} {_fmt_key(key)} differs from the {which} observation epoch "
                        f"{_fmt_key(want)}", lineno, 1, HEADER)
        first = tsys.get("TIME OF FIRST OBS")
        last = tsys.get("TIME OF LAST OBS")
        if first and last and first[0] != last[0] and last[0]:
            out.warn("VAL.HDR.TIME-SYSTEM", "TIME OF LAST OBS time system differs from TIME OF FIRST "
                     "OBS ('Same value as in TIME OF FIRST OBS record')", last[1], 49, HEADER)
        if first and not first[0]:
            syss = self.data_systems or set(getattr(self, "v3types", {}))
            if self.info.system.strip() == "M" and len(syss) > 1:
                # "Compulsory in mixed GPS/GLONASS files" (rinex211.txt l.1183-1191;
                # 3.x/4.x Table A2: "compulsory in mixed files")
                out.warn("VAL.HDR.TIME-SYSTEM", "TIME OF FIRST OBS has no time system, which is "
                         "compulsory in mixed files", first[1], 49, HEADER)

    def check_counts(self, recs):
        out = self.out
        if not self.complete:
            return        # the data scan stopped early: counts would be partial
        nrec = next(((n, c) for n, l, c in recs if l == "# OF SATELLITES"), None)
        if nrec is not None:
            try:
                n = _int_or_none(nrec[1].ljust(6)[0:6])
            except ValueError:
                n = "bad"
            if n != "bad" and (n or 0) != len(self.sats):
                out.err("VAL.HDR.NUM-SATELLITES", f"# OF SATELLITES says {n}, the data hold "
                        f"{len(self.sats)} satellites", nrec[0], 1, HEADER)
        prn = self.prn_rec
        if prn is None:
            return
        for key in list(self.batches):
            self.flush(key)
        data = {}
        for (sat, state), acc in self.acc.items():
            data.setdefault(sat, {})[state] = acc
        listed = set(prn)
        missing = sorted(self.sats - listed)
        extra = sorted(listed - self.sats)
        if missing:
            out.err("VAL.HDR.PRN-NUM-OBS", f"PRN / # OF OBS has no line for {len(missing)} observed "
                    f"satellite(s): {' '.join(missing[:12])}{' ...' if len(missing) > 12 else ''}",
                    None, None, HEADER)
        if extra:
            out.err("VAL.HDR.PRN-NUM-OBS", f"PRN / # OF OBS lists {len(extra)} satellite(s) without "
                    f"observations: {' '.join(extra[:12])}{' ...' if len(extra) > 12 else ''}",
                    prn[extra[0]][0], 4, HEADER)
        if self.types_changed or not self.types_ok:
            return        # the counts refer to type lists that change inside the file
        for sat in sorted(listed & self.sats):
            lineno, vals = prn[sat]
            if self.v2:
                codes = self.v2types
                acc = data.get(sat, {}).get(0)
            else:
                codes = self.v3types.get(sat[0], [])
                acc = data.get(sat, {}).get(self.v3state.get(sat[0]))
            have = acc or [0] * len(codes)
            vals = list(vals)
            if any(v is not None for v in vals[len(codes):]):
                out.err("VAL.HDR.PRN-NUM-OBS", f"PRN / # OF OBS for {sat} has more counts than the "
                        f"{len(codes)} observation types", lineno, 7, HEADER)
            vals = (vals + [None] * len(codes))[:len(codes)]
            for k, code in enumerate(codes):
                v = vals[k] or 0             # a blank count means 0
                n = have[k]
                # 99999 means '>= 99999' from 3.01 (rinex301.txt Table A2 l.2157); 2.x and
                # 3.00 count exactly (rinex211.txt Table A1)
                if v != n and not (v == 99999 and n >= 99999 and self.tv >= "3.01"):
                    out.err("VAL.HDR.PRN-NUM-OBS", f"PRN / # OF OBS for {sat} {code}: header says {v}, "
                            f"the data hold {n}", lineno, 7 + 6 * k if k < 9 else None, HEADER)
                    break

    def check_glonass_slots(self, recs):
        lines = [(n, c) for n, l, c in recs if l == "GLONASS SLOT / FRQ #"]
        if not lines:
            return
        out = self.out
        declared = None
        listed = set()
        for lineno, c in lines:
            c = c.ljust(60)
            if c[0:3].strip():
                try:
                    declared = (_int_or_none(c[0:3]), lineno)
                except ValueError:
                    out.err("VAL.HDR.NUMBER", "GLONASS SLOT / FRQ # count unreadable", lineno, 1, HEADER)
            for k in range(8):
                cell = c[4 + 7 * k:4 + 7 * k + 7]
                if not cell.strip():
                    continue
                sat = cell[0:3]
                if not (sat[0] == "R" and sat[1:].strip().isdecimal()):
                    out.err("VAL.HDR.NUMBER", f"GLONASS SLOT / FRQ # entry {cell.strip()!r} unreadable "
                            "(A1,I2.2,1X,I2)", lineno, 5 + 7 * k, HEADER)
                    continue
                if not _INT.fullmatch(cell[4:6]):
                    out.err("VAL.HDR.NUMBER", f"GLONASS SLOT / FRQ # frequency {cell[4:6]!r} unreadable",
                            lineno, 9 + 7 * k, HEADER)
                listed.add(f"R{int(sat[1:]):02d}")
        if declared and declared[0] is not None and declared[0] != len(listed):
            out.warn("VAL.HDR.GLONASS-SLOTS", f"GLONASS SLOT / FRQ # declares {declared[0]} satellites, "
                     f"lists {len(listed)}", declared[1], 1, HEADER)
        unlisted = sorted(s for s in self.sats if s[0] == "R" and s not in listed)
        if unlisted:
            out.warn("VAL.HDR.GLONASS-SLOTS", f"GLONASS satellites observed but not in GLONASS SLOT / "
                     f"FRQ #: {' '.join(unlisted)}", lines[0][0], 1, HEADER)


# ---------------------------------------------------------------------------
# navigation files
# ---------------------------------------------------------------------------
# Record lines (the SV / EPOCH / SV CLK line included).
# RINEX 2: rinex210.txt Tables A4 l.1084, A11 l.1425, A16 l.1643; rinex211.txt Tables A4
# l.1355 (GPS: BROADCAST ORBIT 1-7), A11 l.1704 (GLONASS: 1-3), A16 l.1946 (GEO: 1-3).
NAV_LINES_V2 = {"N": 8, "G": 4, "H": 4}
# Non-standard RINEX 2 nav file types the reader accepts (rinexfile.NAV_TYPES_V2): lines by
# the satellite system, as in RINEX 3.
_NAV_V2_SYS = {"N": "G", "G": "R", "H": "S", "L": "E", "E": "E", "C": "C", "J": "J", "I": "I", "P": None}
# RINEX 3: rinex300.txt Tables A5 (GPS 1-7), A7 (Galileo 1-7), A9 (GLONASS 1-3), A11 (SBAS 1-3)
# p.33-37; rinex302.txt Tables A6/A8/A10/A12/A14 and BDS (p.73: 1-7); rinex303.txt Table A18
# IRNSS (1-7, p.86-87); rinex305.txt Table A10 p.74: GLONASS BROADCAST ORBIT 1-4 (5 lines).
NAV_LINES_V3 = {"G": 8, "E": 8, "J": 8, "C": 8, "I": 8, "S": 4, "R": 4}
NAV_SYSTEMS = {   # nav header RINEX VERSION / TYPE system lists
    "3.00": "GRES", "3.01": "GRES",                  # rinex300.txt p.32, rinex301.txt p.36
    "3.02": "GRECJS",                                # rinex302.txt Table A5 p.62
    "3.03": "GRECJIS", "3.04": "GRECJIS", "3.05": "GRECJIS",
    "4.00": "GRECJIS", "4.01": "GRECJIS", "4.02": "GRECJIS",
}
# RINEX 4 EPH lines after the '> EPH' header line (SV / EPOCH line + BROADCAST ORBIT lines):
# rinex_4.02.txt Tables A9 GPS LNAV (orbit 1-7) p.78, A10 CNAV (1-8) p.80, A11 CNV2 (1-9) p.82,
# A13 Galileo INAV/FNAV (1-7) p.84, A15 GLONASS FDMA (1-4) p.87, A16 L1OC (1-8) p.89, A17 L3OC
# (1-8) p.90, A19-A21 QZSS LNAV/CNAV/CNV2 p.93-97, A23 BDS D1/D2 (1-7) p.99, A24 CNV1 (1-9)
# p.101, A25 CNV2 (1-9) p.103, A26 CNV3 (1-8) p.105, A28 SBAS (1-3) p.108, A30 NavIC LNAV
# (1-7) p.110, A31 L1NV (1-8) p.112. Same counts in rinex_4.00.txt Tables A9-A28 p.72-100
# and rinex_4.01.txt p.76-104 for the types they define.
V4_EPH_LINES = {
    ("G", "LNAV"): 8, ("G", "CNAV"): 9, ("G", "CNV2"): 10,
    ("J", "LNAV"): 8, ("J", "CNAV"): 9, ("J", "CNV2"): 10,
    ("E", "INAV"): 8, ("E", "FNAV"): 8,
    ("R", "FDMA"): 5, ("R", "L1OC"): 9, ("R", "L3OC"): 9,
    ("C", "D1"): 8, ("C", "D2"): 8, ("C", "CNV1"): 10, ("C", "CNV2"): 10, ("C", "CNV3"): 9,
    ("S", "SBAS"): 4,
    ("I", "LNAV"): 8, ("I", "L1NV"): 9,
}
V402_ONLY_EPH = {("R", "L1OC"), ("R", "L3OC"), ("I", "L1NV")}   # rinex_4.02.txt Table 20 p.39
# STO/EOP/ION message types: rinex_4.00.txt / rinex_4.01.txt Table 21 (p.35 / p.37-38);
# rinex_4.02.txt Table 21 p.39-40 adds L1NV and LXOC.
V4_OTHER_MSGS = {"LNAV", "FDMA", "IFNV", "D1D2", "SBAS", "CNVX"}
V402_OTHER_MSGS = {"L1NV", "LXOC"}
# STO 2 lines (rinex_4.02.txt Table A33 p.115), EOP 3 lines (Table A34 p.116).
# ION by model: Klobuchar 3 (Table A35 p.117: G/C/J/I LNAV, D1D2, CNVX), NeQuick-G 2
# (Table A36 p.118: E IFNV), BDGIM 3 (Table A37 p.119: C CNVX), NavIC KLOB 4 (Table A38
# p.120), NavIC NeQuick-N 7 (Table A39 p.121), GLONASS LXOC 1 (Table A40 p.122).
_ION_LINES = {("E", "IFNV", ""): 2, ("C", "CNVX", ""): 3, ("I", "L1NV", "KLOB"): 4,
              ("I", "L1NV", "NEQN"): 7, ("R", "LXOC", ""): 1}
_ION_SUBTYPES = {("J", "CNVX"): {"WIDE", "JAPN"}, ("I", "L1NV"): {"KLOB", "NEQN"}}   # Table 25

_NAV_TOKEN = re.compile(r"-?\d?\.\d+[DdEe][+-]\d\d").fullmatch
_NAV_LENIENT = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:([DdEe])([+-]?)(\d+))?").fullmatch
_V2_NAV_HEAD = re.compile(r"[ \d]\d \d\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d[ \d]{2}\d\.\d").match
_V3_NAV_HEAD = re.compile(r"[A-Z]\d\d \d{4} \d\d \d\d \d\d \d\d \d\d").match
_V4_EPOCH = re.compile(r"    \d{4} \d\d \d\d \d\d \d\d \d\d").match


class _Nav:
    def __init__(self, rd, first, info, tv, out):
        self.rd = rd
        self.first = first
        self.info = info
        self.tv = tv
        self.out = out
        self.letters = {}           # exponent letter -> first line

    def run(self):
        tv = self.tv
        ft = self.info.ftype
        if tv < "3":
            key = {"N": "v2-N", "G": "v2-G", "H": "v2-H-2.10" if tv == "2.10" else "v2-H-2.11"}.get(ft)
            if key is None:
                self.out.warn("VAL.HDR.TYPE", f"file type {ft!r} is not a RINEX 2 navigation file type "
                              "(N GPS, G GLONASS, H GEO: rinex211.txt Tables A3, A10, A15)", 1, 21, HEADER)
                statuses = {**_NAV_V2_GPS, **_NAV_V2_GLO, **_NAV_V2_GEO_211}
            else:
                statuses = NAV_HEADER[key]
            numeric = _NAV_NUMERIC_V2
        elif tv < "4":
            statuses = _NAV_V3
            numeric = _NAV_NUMERIC_V3
        else:
            statuses = _NAV_V4
            numeric = _NAV_NUMERIC_V4
        if tv >= "3":
            _system_letter_check(self.first, set(NAV_SYSTEMS[tv]) | {"M"}, self.out,
                                 f"RINEX {tv} navigation files")
        defined = set(statuses)
        recs, end = _read_header(self.rd, self.first, self.out, defined, _NAV_ALL, lambda x: x,
                                 lambda x: x)
        _header_common(recs, self.out, statuses, tv, "navigation")
        _check_numeric(recs, numeric, self.out)
        _check_leap_system(recs, tv, self.out)
        if not end:
            return
        self.systems = set()
        if tv < "3":
            self.scan_v2(ft)
        elif tv < "4":
            self.scan_v3()
        else:
            self.scan_v4()
        self.exponents()
        letter = self.first[40:41].strip().upper()
        if tv >= "3" and letter and letter != "M" and self.systems - {letter}:
            out = self.out
            out.err("VAL.HDR.SYSTEM.MISMATCH", f"RINEX VERSION / TYPE says {letter!r} but the file holds "
                    f"records of {''.join(sorted(self.systems - {letter}))} (use 'M' for mixed files)",
                    1, 41, HEADER)

    # -- numbers -------------------------------------------------------------
    def numbers(self, line, starts, lineno):
        out = self.out
        for a in starts:
            f = line[a:a + 19]
            t = f.strip()
            if not t:
                continue
            if _NAV_TOKEN(t):
                letter = t[-4]
            else:
                m = _NAV_LENIENT(t)
                if not m:
                    out.err("VAL.NAV.NUMBER", f"{t!r} is not a number (D19.12, columns {a + 1}-{a + 19})",
                            lineno, a + 1)
                    continue
                letter = m.group(1)
                if letter is None:
                    out.warn("VAL.NAV.NUMBER.FORMAT", f"{t!r} has no exponent (D19.12)", lineno, a + 1)
                    continue
                if len(m.group(3)) != 2:
                    # "Zero-padded two-digit exponents are required" (rinex211.txt l.1421;
                    # rinex305.txt p.44 sec. 6.8; rinex_4.02.txt p.50 sec. 6.8)
                    out.err("VAL.NAV.NUMBER.EXPONENT", f"{t!r}: exponent must have two digits",
                            lineno, a + 1)
            if letter not in self.letters:
                self.letters[letter] = lineno

    def exponents(self):
        tv = self.tv
        out = self.out
        if len(self.letters) > 1:
            where = ", ".join(f"{k!r} first at line {v}" for k, v in sorted(self.letters.items(),
                                                                         key=lambda kv: kv[1]))
            # "The same exponent indicator will be used throughout a navigation file (station
            # or merged)" (rinex_4.00.txt p.45, rinex_4.01.txt p.48, rinex_4.02.txt p.50 sec. 6.8);
            # 3.05: "throughout a station navigation file" (rinex305.txt p.44 sec. 6.8).
            if tv >= "4":
                out.err("VAL.NAV.EXPONENT.MIXED", f"more than one exponent letter: {where}", None, None)
            elif tv == "3.05":
                out.warn("VAL.NAV.EXPONENT.MIXED", f"more than one exponent letter ({where}); 3.05 "
                         "requires one letter in a station navigation file", None, None)
        if tv >= "4":
            dd = [k for k in self.letters if k in "Dd"]
            if dd:
                # "D, and d are allowed but strongly deprecated" (rinex_4.02.txt p.50 sec. 6.8)
                out.warn("VAL.NAV.EXPONENT.DEPRECATED", f"exponent letter {dd[0]!r} is strongly "
                         "deprecated in RINEX 4; E or e is recommended", self.letters[dd[0]], None)

    def layout(self, line, end, lineno):
        if len(line) > end and line[end:].strip():
            self.out.err("VAL.NAV.LAYOUT", f"text after column {end} of a navigation record line",
                         lineno, end + 1)

    # -- RINEX 2 -------------------------------------------------------------------
    def scan_v2(self, ft):
        rd = self.rd
        out = self.out
        dsys = _NAV_V2_SYS.get(ft) or "G"
        cur = None          # [lineno, nlines, system, expected lines]
        while True:
            line = rd.next()
            if line is None or (line.strip() and line[0:2].strip()):
                if cur is not None:
                    self.close(cur)
                    cur = None
            if line is None:
                return
            lineno = rd.n
            if not line.strip():
                out.warn("VAL.NAV.BLANK-LINE", "blank line in the data section", lineno)
                continue
            if line[0:3] == "   ":
                if cur is None:
                    out.err("VAL.NAV.RECORD.START", "continuation line without a PRN / EPOCH / SV CLK "
                            "line", lineno, 1)
                    continue
                cur[1] += 1
                self.numbers(line, (3, 22, 41, 60), lineno)
                self.layout(line, 79, lineno)
                continue
            if not line[0:2].strip():
                out.err("VAL.NAV.RECORD.START", f"line starts with {line[0:3]!r}: neither a PRN / EPOCH "
                        "/ SV CLK line (I2 PRN) nor a 3X continuation line", lineno, 1)
                continue
            off = 0
            sysc = dsys
            want = NAV_LINES_V2.get(ft)
            if line[0].isalpha():
                sysc = line[0].upper()
                off = 1
                want = 4 if sysc == "R" else NAV_LINES_V3.get(sysc)
                out.warn("VAL.NAV.SYSTEM", f"satellite identifier {line[0:3]!r} with a system letter: "
                         "not part of the RINEX 2 layout (I2 PRN)", lineno, 1)
            elif want is None:
                want = 4 if sysc == "R" else NAV_LINES_V3.get(sysc)
            self.systems.add(sysc)
            cur = [lineno, 1, sysc, want]
            head = line[off:off + 22]
            if not _V2_NAV_HEAD(head):
                self.epoch_slow_v2(head, lineno, off)
            self.numbers(line, (off + 22, off + 41, off + 60), lineno)
            self.layout(line, 79 + off, lineno)

    def epoch_slow_v2(self, head, lineno, off):
        out = self.out
        h = head.ljust(22)
        if h[3] == " " and h[4].isdecimal():
            out.warn("VAL.NAV.EPOCH.PAD", f"year {h[3:5]!r} not zero-padded (I2.2)", lineno, off + 4)
        ok = (re.fullmatch(r"[ \d]\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d", h[0:17])
              and _VALUE_LENIENT(h[17:22]) is not None)
        if not ok:
            out.err("VAL.NAV.EPOCH", f"PRN / EPOCH / SV CLK {h.strip()!r} unreadable "
                    "(I2,1X,I2.2,4(1X,I2),F5.1)", lineno, off + 1)

    def close(self, cur):
        lineno, n, sysc, want = cur
        if want is not None and n != want:
            self.out.err("VAL.NAV.RECORD.LINES", f"{sysc} record has {n} lines; RINEX {self.tv} "
                         f"defines {want}", lineno, 1)

    # -- RINEX 3 -------------------------------------------------------------------
    def scan_v3(self):
        rd = self.rd
        out = self.out
        tv = self.tv
        cur = None
        allowed = NAV_SYSTEMS[tv]
        glo = 5 if tv >= "3.05" else 4
        while True:
            line = rd.next()
            if line is None or (line.strip() and line[0:4] != "    "):
                if cur is not None:
                    self.close(cur)
                    cur = None
            if line is None:
                return
            lineno = rd.n
            if not line.strip():
                out.warn("VAL.NAV.BLANK-LINE", "blank line in the data section", lineno)
                continue
            if line[0:4] == "    ":
                if cur is None:
                    out.err("VAL.NAV.RECORD.START", "continuation line without an SV / EPOCH / SV CLK "
                            "line", lineno, 1)
                    continue
                cur[1] += 1
                self.numbers(line, (4, 23, 42, 61), lineno)
                self.layout(line, 80, lineno)
                continue
            s = line[0]
            if not s.isalpha():
                out.err("VAL.NAV.RECORD.START", f"line starts with {line[0:4]!r}: neither an SV / EPOCH "
                        "/ SV CLK line nor a 4X continuation", lineno, 1)
                continue
            s = s.upper()
            if s not in allowed:
                out.warn("VAL.NAV.SYSTEM", f"system {s!r} is not defined in RINEX {tv} navigation files",
                         lineno, 1)
            self.systems.add(s)
            cur = [lineno, 1, s, glo if s == "R" else NAV_LINES_V3.get(s)]
            if not _V3_NAV_HEAD(line):
                self.epoch_slow_v3(line, lineno, 0, True)
            self.numbers(line, (23, 42, 61), lineno)
            self.layout(line, 80, lineno)

    def epoch_slow_v3(self, line, lineno, start, with_sat):
        """Diagnose 'A1,I2.2,1X,I4,5(1X,I2.2)' (with_sat) or '4X,I4,5(1X,I2.2)'."""
        out = self.out
        x = line.ljust(23)
        if with_sat:
            num = x[1:3]
            if num[0] == " " and num[1].isdecimal():
                out.warn("VAL.NAV.EPOCH.PAD", f"satellite number {x[0:3]!r} not zero-padded (I2.2)",
                         lineno, 2)
            elif not (num.isdecimal() and num.isascii()):
                out.err("VAL.NAV.EPOCH", f"satellite {x[0:3]!r} unreadable (A1,I2.2)", lineno, 1)
                return
        elif x[0:4].strip():
            out.err("VAL.NAV.EPOCH", "columns 1-4 must be blank (4X,I4,...)", lineno, 1)
            return
        if x[3] != " " or not (x[4:8].isdecimal() and x[4:8].isascii()):
            out.err("VAL.NAV.EPOCH", f"year {x[4:8]!r} unreadable (I4, columns 5-8)", lineno, 5)
            return
        for a in (8, 11, 14, 17, 20):
            f = x[a + 1:a + 3]
            if x[a] != " " or not f.strip().isdecimal():
                out.err("VAL.NAV.EPOCH", f"epoch field {x[a:a + 3]!r} unreadable (1X,I2.2) at columns "
                        f"{a + 1}-{a + 3}", lineno, a + 1)
                return
            if f[0] == " ":
                out.warn("VAL.NAV.EPOCH.PAD", f"epoch field {f!r} not zero-padded (I2.2)", lineno, a + 2)

    # -- RINEX 4 -------------------------------------------------------------------
    def scan_v4(self):
        rd = self.rd
        out = self.out
        tv = self.tv
        cur = None        # [lineno, nlines, want, label]
        body_first = False
        kind = sat = None
        while True:
            line = rd.next()
            if line is None or line[:1] == ">":
                if cur is not None:
                    n = cur[1]
                    if cur[2] is not None and n != cur[2]:
                        out.err("VAL.NAV.RECORD.LINES", f"{cur[3]} record has {n} lines after its "
                                f"header line; RINEX {tv} defines {cur[2]}", cur[0], 1)
                    cur = None
            if line is None:
                return
            lineno = rd.n
            if not line.strip():
                out.warn("VAL.NAV.BLANK-LINE", "blank line in the data section", lineno)
                continue
            if line[:1] == ">":
                kind, sat, msg, sub, want = self.record_head(line, lineno)
                cur = [lineno, 0, want, f"{kind} {sat} {msg}".strip()]
                body_first = True
                continue
            if cur is None:
                out.err("VAL.NAV.RECORD.START", "data line before the first '>' record header", lineno, 1)
                continue
            cur[1] += 1
            if body_first:
                body_first = False
                if kind == "EPH":
                    if len(sat) == 3 and line[0:3] != sat:
                        out.err("VAL.NAV.RECORD.HEAD", f"EPH body starts with {line[0:3]!r}, the header "
                                f"line names {sat}", lineno, 1)
                    if not _V3_NAV_HEAD(line):
                        self.epoch_slow_v3(line, lineno, 0, True)
                    self.numbers(line, (23, 42, 61), lineno)
                else:
                    if not _V4_EPOCH(line):
                        self.epoch_slow_v3(line, lineno, 0, False)
                    if kind != "STO":
                        self.numbers(line, (23, 42, 61), lineno)
                self.layout(line, 80, lineno)
                continue
            if line[0:4].strip():
                out.err("VAL.NAV.RECORD.START", f"line starts with {line[0:4]!r}: not a 4X continuation "
                        "line nor a '>' record header", lineno, 1)
                continue
            self.numbers(line, (4, 23, 42, 61), lineno)
            self.layout(line, 80, lineno)

    def record_head(self, line, lineno):
        """Check a '> EPH G01 LNAV' line (rinex_4.02.txt sec. 5.4.1 p.38-40, Tables 19-25).
        Returns (kind, sat, msg, subtype, expected lines or None)."""
        out = self.out
        tv = self.tv
        x = line.rstrip().ljust(19)
        kind = x[2:5]
        s = x[6]
        prn = x[7:9]
        msg = x[10:14].strip()
        sub = x[15:19].strip()
        ok = (x[1] == " " and x[5] == " " and x[9] == " " and x[14] == " " and not x[19:].strip()
              and kind in ("EPH", "STO", "EOP", "ION") and s.isalpha() and s.isupper()
              and (prn == "  " or (prn.isdecimal() and prn.isascii()))
              and re.fullmatch(r"[A-Z0-9]{2,4} *", x[10:14]) is not None
              and re.fullmatch(r"[A-Z0-9]* *", x[15:19]) is not None)
        if not ok:
            out.err("VAL.NAV.RECORD.HEAD", f"record header {line.strip()!r} is not '> TYP S## MSG "
                    "[SUB]' (A1,1X,A3,1X,A1,A2,1X,A4,1X,A4; rinex_4.02.txt Tables A9-A40)", lineno, 1)
            tok = line[1:].split()
            kind = tok[0].upper() if tok else ""
            sat = tok[1] if len(tok) > 1 else ""
            msg = tok[2] if len(tok) > 2 else ""
            if kind == "EPH" and sat[:1].isalpha():
                self.systems.add(sat[0].upper())
            return kind, sat, msg, "", None
        if kind == "EPH":
            self.systems.add(s)
        if s not in NAV_SYSTEMS[tv]:
            out.err("VAL.NAV.SYSTEM", f"system {s!r} is not defined in RINEX {tv}", lineno, 7)
        sat = s + prn if prn.strip() else s
        if kind == "EPH":
            if not prn.strip():
                out.err("VAL.NAV.RECORD.HEAD", "EPH record without a satellite number", lineno, 8)
            want = V4_EPH_LINES.get((s, msg))
            if want is None or ((s, msg) in V402_ONLY_EPH and tv < "4.02"):
                out.err("VAL.NAV.RECORD.TYPE", f"EPH message type {msg!r} is not defined for system {s} "
                        f"in RINEX {tv} (Table 20)", lineno, 11)
                want = None
            if sub:
                out.warn("VAL.NAV.RECORD.TYPE", f"EPH records have no subtypes (Table 22); {sub!r} "
                         "given", lineno, 16)
            return kind, sat, msg, sub, want
        allowed = V4_OTHER_MSGS | (V402_OTHER_MSGS if tv >= "4.02" else set())
        if msg not in allowed:
            out.err("VAL.NAV.RECORD.TYPE", f"{kind} message type {msg!r} is not defined in RINEX {tv} "
                    "(Table 21)", lineno, 11)
            return kind, sat, msg, sub, None
        if kind == "STO":
            want = 2
        elif kind == "EOP":
            want = 3
        else:
            # Subtypes exist only from 4.02 (rinex_4.02.txt Table 25 p.40 and Table A35 note
            # 3*: QZSS CNVX "must have a subtype indicator (WIDE or JAPN) ... for the other
            # types the subtype shall be left blank"); 4.00 and 4.01 define none.
            subs = _ION_SUBTYPES.get((s, msg)) if tv >= "4.02" else None
            if subs is not None and sub not in subs:
                out.err("VAL.NAV.RECORD.TYPE", f"ION {s} {msg} needs a subtype {sorted(subs)} "
                        "(rinex_4.02.txt Table 25)", lineno, 16)
            elif subs is None and sub:
                out.warn("VAL.NAV.RECORD.TYPE", f"ION {s} {msg} has no subtypes in RINEX {tv} "
                         f"(the field shall be left blank); {sub!r} given", lineno, 16)
            want = _ION_LINES.get((s, msg, sub if s == "I" else ""), 3)
        if sub and kind != "ION":
            out.warn("VAL.NAV.RECORD.TYPE", f"{kind} records have no subtypes (Tables 23-24); {sub!r} "
                     "given", lineno, 16)
        return kind, sat, msg, sub, want


# ---------------------------------------------------------------------------
# meteorological files
# ---------------------------------------------------------------------------
# EPOCH / MET: 1X,I2.2,5(1X,I2) + mF7.1 (8 per line), continuation 4X,10F7.1 up to 3.01
# (rinex211.txt Table A6 l.1500; rinex300.txt Table A14 p.39 l.2672; rinex301.txt Table A14
# p.43 l.2944); 1X,I4,5(1X,I2) from 3.02 (rinex302.txt Table A17 p.79 l.4218; rinex_4.02.txt
# Table A43 p.127).
_MET_E2 = re.compile(r" \d\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d").match
_MET_E4 = re.compile(r" \d{4} [ \d]\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d").match
_MET_E2_PAD = re.compile(r"  \d [ \d]\d [ \d]\d [ \d]\d [ \d]\d [ \d]\d").match
_F7_1 = re.compile(r" *-?\d*\.\d").fullmatch


class _Met:
    def __init__(self, rd, first, info, tv, out):
        self.rd = rd
        self.first = first
        self.info = info
        self.tv = tv
        self.out = out

    def run(self):
        tv = self.tv
        out = self.out
        statuses = MET_HEADER["v4" if tv >= "4" else "v2v3"]
        defined = {k for k in statuses}
        recs, end = _read_header(self.rd, self.first, out, defined, _MET_ALL, lambda x: x, lambda x: x)
        _header_common(recs, out, {k: v for k, v in statuses.items() if v != "C"}, tv,
                       "meteorological")
        types = self.types(recs)
        self.sensors(recs, types)
        if end and types:
            self.scan(types)

    def types(self, recs):
        """# / TYPES OF OBSERV I6,9(4X,A2) + 6X,9(4X,A2)."""
        out = self.out
        lines = [(n, c) for n, lab, c in recs if lab == "# / TYPES OF OBSERV"]
        if not lines:
            return None
        n = None
        codes = []
        first_line = lines[0][0]
        for lineno, c in lines:
            c = c.ljust(60)
            if c[0:6].strip():
                if n is not None:
                    out.warn("VAL.HDR.REPEATED", "# / TYPES OF OBSERV count line repeated", lineno, 1,
                             HEADER)
                try:
                    n = _int_or_none(c[0:6])
                except ValueError:
                    out.err("VAL.HDR.NUMBER", "# / TYPES OF OBSERV count unreadable", lineno, 1, HEADER)
            for k in range(9):
                slot = c[6 + 6 * k:12 + 6 * k]
                if not slot.strip():
                    continue
                if slot[0:4].strip() or slot[4] == " ":
                    out.err("VAL.MET.TYPES.LAYOUT", f"met type {slot.strip()!r} not in the 4X,A2 field at "
                            f"columns {11 + 6 * k}-{12 + 6 * k}", lineno, 7 + 6 * k, HEADER)
                    codes.append(slot.strip())
                else:
                    codes.append(slot[4:6])
        if n is not None and n != len(codes):
            out.err("VAL.MET.TYPES.COUNT", f"# / TYPES OF OBSERV declares {n} types, lists {len(codes)}",
                    first_line, 1, HEADER)
        for code in codes:
            if code not in MET_TYPES[self.tv]:
                out.warn("VAL.MET.TYPES.CODE", f"met type {code!r} is not defined in RINEX {self.tv}",
                         first_line, 1, HEADER)
        return codes

    def sensors(self, recs, types):
        if not types:
            return
        out = self.out
        mod = {c.ljust(60)[57:59] for n, lab, c in recs if lab == "SENSOR MOD/TYPE/ACC"}
        pos = {c.ljust(60)[57:59] for n, lab, c in recs if lab == "SENSOR POS XYZ/H"}
        for lineno, lab, c in recs:
            if lab == "SENSOR MOD/TYPE/ACC":
                if c.ljust(60)[46:53].strip() and not _DEC.fullmatch(c.ljust(60)[46:53]):
                    out.err("VAL.HDR.NUMBER", "SENSOR MOD/TYPE/ACC accuracy unreadable (F7.1)", lineno, 47,
                            HEADER)
            elif lab == "SENSOR POS XYZ/H":
                cc = c.ljust(60)
                for a in (0, 14, 28, 42):
                    if cc[a:a + 14].strip() and not _DEC.fullmatch(cc[a:a + 14]):
                        out.err("VAL.HDR.NUMBER", "SENSOR POS XYZ/H coordinate unreadable (F14.4)",
                                lineno, a + 1, HEADER)
        missing = [t for t in types if t not in mod]
        if missing and mod:
            # "Record is repeated for each observation type found in # / TYPES OF OBSERV"
            out.warn("VAL.MET.SENSOR", f"no SENSOR MOD/TYPE/ACC for {', '.join(missing)}", None, None,
                     HEADER)
        if "PR" in types and "PR" not in pos:
            # "Record required for barometer, recommended for other sensors"
            out.err("VAL.MET.SENSOR", "no SENSOR POS XYZ/H for the barometer (PR): 'Record required "
                    "for barometer'", None, None, HEADER)

    def scan(self, types):
        rd = self.rd
        out = self.out
        n = len(types)
        v2 = self.tv < "3.02"
        head = 18 if v2 else 20
        fast = _MET_E2 if v2 else _MET_E4
        other = _MET_E4 if v2 else _MET_E2
        pad = _MET_E2_PAD if v2 else (lambda x: None)
        ncont = max(0, -(-(n - 8) // 10))
        prev = None
        while True:
            line = rd.next()
            if line is None:
                return
            lineno = rd.n
            if not line.strip():
                out.warn("VAL.MET.BLANK-LINE", "blank line in the data section", lineno)
                continue
            if line[0:4] == "    " and not fast(line):
                out.err("VAL.MET.CONTINUATION", "continuation line where an epoch was expected (more "
                        "values than # / TYPES OF OBSERV declares?)", lineno, 1)
                continue
            if not fast(line) and pad(line):
                out.warn("VAL.MET.EPOCH.PAD", f"year {line[1:3]!r} not zero-padded (I2.2)", lineno, 2)
                line = line[:1] + "0" + line[2:]
            if not fast(line):
                if other(line):
                    out.err("VAL.MET.EPOCH.LAYOUT", f"epoch written with a {'4' if v2 else '2'}-digit year; "
                            f"RINEX {self.tv} met epochs are {'1X,I2.2' if v2 else '1X,I4'},5(1X,I2)",
                            lineno, 2)
                    key = None
                    h = 20 if v2 else 18
                else:
                    out.err("VAL.MET.EPOCH", f"epoch {line[:head].strip()!r} unreadable "
                            f"({'1X,I2.2' if v2 else '1X,I4'},5(1X,I2))", lineno, 1)
                    key = None
                    h = head
            else:
                h = head
                if v2:
                    y = _year4(int(line[1:3]))
                    p = 3
                else:
                    y = int(line[1:5])
                    p = 5
                key = (y, int(line[p:p + 3]), int(line[p + 3:p + 6]), int(line[p + 6:p + 9]),
                       int(line[p + 9:p + 12]), int(line[p + 12:p + 15]) * 10_000_000)
                if not _date_ok(*key):
                    out.err("VAL.MET.EPOCH", f"epoch {line[:head].strip()!r} out of range", lineno, 2)
                    key = None
            if key is not None:
                if prev is not None and key <= prev:
                    out.warn("VAL.MET.EPOCH.ORDER", f"epoch {_fmt_key(key)} is not later than "
                             f"{_fmt_key(prev)}", lineno, 2)
                prev = key
            self.values(line, h, min(n, 8), lineno)
            for j in range(ncont):
                c = rd.next()
                if c is None:
                    out.err("VAL.MET.CONTINUATION", f"file ends inside the epoch at line {lineno}", rd.n)
                    return
                if c[0:4].strip():
                    out.err("VAL.MET.CONTINUATION", f"expected a continuation line (4X,10F7.1) for the "
                            f"epoch at line {lineno}", rd.n, 1)
                    rd.back(c)
                    break
                k = min(10, n - 8 - 10 * j)
                self.values(c, 4, k, rd.n)

    def values(self, line, start, k, lineno):
        out = self.out
        for j in range(k):
            a = start + 7 * j
            f = line[a:a + 7]
            if not f.strip():
                out.warn("VAL.MET.VALUE.FORMAT", "blank met value (no missing-value convention is "
                         "defined for met files)", lineno, a + 1)
            elif not _F7_1(f):
                if _VALUE_LENIENT(f) and len(f) == 7:
                    out.warn("VAL.MET.VALUE.FORMAT", f"met value {f.strip()!r} not F7.1", lineno, a + 1)
                else:
                    out.err("VAL.MET.VALUE", f"met value {f.strip()!r} unreadable (F7.1, columns "
                            f"{a + 1}-{a + 7})", lineno, a + 1)
        end = start + 7 * k
        if line[end:].strip():
            out.err("VAL.MET.CONTINUATION", "values beyond those # / TYPES OF OBSERV declares",
                    lineno, end + 1)
