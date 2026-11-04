"""LEAP SECONDS records between versions (obs and nav headers, and obs events).

From 3.03 the record is 4I6,A3: current leap seconds, future or past leap seconds, week, day,
and a time system identifier, "only GPS and BDT are valid identifiers ... All data fields must
match the indicated time system identifier" (rinex305.txt Table A2 l.3143, Table A5 l.3746).
With BDT the leap seconds count from 1-Jan-2006, the week is a BDS week and the day is 0-6;
with GPS (or blank) they count from 6-Jan-1980 and the day is 1-7. RINEX 4 allows only GPS:
"When generating the leap second record from BDS navigation data the week count and day number
must be adapted to GPS/GAL/QZS/IRN leap second conventions" (rinex_4.02.txt Table A2 l.3679,
Table A7 l.4206). Before 3.03 there is no identifier, so the fields are GPS ones.

BDT is 14 s behind GPS time, dtLS_BDS = dtLS - 14 s (rinex_4.02.txt l.943, rinex305.txt l.805),
and BDT week 0 is GPS week 1356 (rinex_4.02.txt l.871), so a BDT record converts exactly
(Sol round 16: '4 ... BDT' went to 4.02 unchanged, and to 2.11 as 4, read there as GPS).

The BeiDou identifier is spelt 'BDS' in 3.03 and 3.04 ("only GPS and BDS are valid
identifiers": rinex303.txt Table A2 p.60, rinex304.txt Table A2 p.65) and 'BDT' from 3.05: both
are read as BeiDou, and the target's spelling is written (Sol round 24: a 3.04 'BDS' record
was taken for GPS). 3.02 navigation files have no identifier, but count "since 6-Jan-1980 as
transmitted by the GPS almanac or since 1-Jan-2006 as transmitted by BDS almanac"
(rinex302.txt Table A5 p.63): the caller says which (basis="BDS" for a BeiDou-only file).
"""

import re

from rinexcore.errors import CorruptError
from rinexcore.header import HeaderRecord

BDT_LEAP_OFFSET = 14
BDT_WEEK_ZERO = 1356
BEIDOU_IDS = ("BDT", "BDS")


def beidou_id(version):
    """The BeiDou identifier a version spells: BDS in 3.03/3.04, BDT from 3.05."""
    return "BDS" if "3.03" <= version < "3.05" else "BDT"


def width(version):
    """Characters of LEAP SECONDS content a version defines: I6 in 2.x and 3.00 (rinex300.txt
    ~1898), 4I6 in 3.01/3.02 (rinex301.txt ~2137), 4I6,A3 from 3.03 (also RINEX 4)."""
    if version < "3.01":
        return 6
    if version < "3.03":
        return 24
    return 27


def holds_bdt(version):
    return "3.03" <= version < "4"


def _int(s):
    s = s.strip()
    return int(s) if re.fullmatch(r"[+-]?[0-9]+", s) else None    # (not isdigit: '²' is a digit to it)


def malformed(content):
    """Why a LEAP SECONDS content cannot be read, or None: the 4I6 fields must each be blank or
    an integer, columns 25-27 blank or a time system identifier (GPS, BDT, BDS: rinex305.txt
    Table A2/A5, rinex303.txt p.60), and nothing after them (Sonnet round 31: a record a column
    off read 'T' as its identifier and ended in an internal error going to 4.02; '4a' and
    other text in a field was dropped to blank without a word)."""
    c = content.ljust(60)[:60]
    for k in range(4):
        f = c[6 * k:6 * k + 6]
        if f.strip() and _int(f) is None:
            return f"field {k + 1} {f.strip()!r} is not a number (I6)"
    if c[24:27].strip() and c[24:27] not in ("GPS",) + BEIDOU_IDS:
        return f"columns 25-27 {c[24:27]!r} are not a time system identifier (GPS, BDT or BDS)"
    if c[27:60].strip():
        return f"text after the fields: {c[27:60].strip()!r}"
    return None


def check(rec, sv, tv):
    """Refuse (CorruptError HDR.LEAP) a LEAP SECONDS record that cannot be read when it has to
    be rewritten for another version; a same-version conversion carries it as written."""
    why = malformed(rec.content)
    if why and tv != sv:
        raise CorruptError(f"LEAP SECONDS cannot be read: {why}; it cannot be converted to RINEX {tv}",
                           line=getattr(rec, "lineno", None), rule="HDR.LEAP")
    return why is None


def known(x, zero_is_value=False):
    """A LEAP SECONDS field that says something: "Zero or blank if not known" (rinex302.txt
    Table A5 p.63), so 0 and blank are unknown (Sol round 28: 0 became 14, '4 0 0 0' became
    '18 14 1356 1'), except where zero_is_value(): there only blank is."""
    return x is not None and (zero_is_value or x != 0)


def zero_is_value(version, bds_terms):
    """True where a 0 in a LEAP SECONDS field is a value: a field in BeiDou terms of a 3.03-3.05
    record. 3.01/3.02 say "Zero or blank if not known" (rinex302.txt Table A2 p.55, Table A5
    p.63). From 3.03 the fields after the count are "(BNK)", Blank if Not Known, a BeiDou day
    is 0-6, and BDS weeks count from 1-Jan-2006 (rinex303.txt p.60, rinex304.txt p.65,
    rinex305.txt Table A2 p.65 / Table A5); BDT-UTC was 0 s from 2006 to the end of 2008 (Sol
    round 29: a 2007 '0 ... BDT' went to 4.02 as GPS 0, not 14). In GPS terms a 0 is never a
    value of a GNSS-era file (GPS-UTC has been 1 s or more since 1981, GPS days are 1-7), so it
    stays "not known" in every version."""
    return bds_terms and "3.03" <= version < "4"


def _shift(content, ds, dw, dd, zero_value=False):
    """The four fields shifted by ds seconds, dw weeks and dd days; an unknown field is kept as
    written. Each field on its own: the fields are optional one by one (BNK), and a day is
    BeiDou 0-6 against GPS 1-7 whether or not the week is given (rinex305.txt Table A5; Sol
    round 30: '4 3 _ 2BDT' gave GPS day 2, not 3)."""
    c = content.ljust(60)
    cur, fut, wk, dn = (_int(c[6 * k:6 * k + 6]) for k in range(4))
    kn = lambda x: known(x, zero_value)
    vals = (cur + ds if kn(cur) else cur, fut + ds if kn(fut) else fut,
            wk + dw if kn(wk) else wk, dn + dd if kn(dn) else dn)
    return "".join(" " * 6 if v is None else f"{v:6d}" for v in vals)


def _blank_zeros(content):
    """The four fields with each 0 written blank, each field on its own."""
    c = content.ljust(60)
    f = [_int(c[6 * k:6 * k + 6]) for k in range(4)]
    f = [None if x == 0 else x for x in f]
    return "".join(" " * 6 if v is None else f"{v:6d}" for v in f) + c[24:60].rstrip()


def as_gps(content, zero_value=False):
    """The content of a BDT LEAP SECONDS record in GPS terms, or None if it is not BDT.
    zero_value: its zeros are values (zero_is_value), shifted like any other."""
    c = content.ljust(60)
    if c[24:27].strip() not in BEIDOU_IDS:
        return None
    return _shift(c, BDT_LEAP_OFFSET, BDT_WEEK_ZERO, 1, zero_value) + "GPS"


def from_gps(content):
    """A LEAP SECONDS content in GPS terms (identifier GPS or none) in BDS terms, without an
    identifier: leap seconds - 14, week - 1356, day - 1 (the inverse of as_gps); unknown
    fields (0 or blank) stay as written. A week before 2006 is negative, which I6 holds and
    as_gps gives back (Sol round 27: it was left blank, the week lost unreported)."""
    return _shift(content, -BDT_LEAP_OFFSET, -BDT_WEEK_ZERO, -1)


def for_target(rec, sv, tv, report, basis=None, out_basis=None):
    """A LEAP SECONDS record (header or event) for target version tv: BDT values converted to
    GPS where tv cannot hold BDT, the BeiDou identifier spelt as tv spells it, then cut to the
    fields tv defines (fields cut off that hold something are claimed). basis="BDS": a record
    with no identifier (3.02) counted from 2006 by BDS (reported as an assumption).
    out_basis="BDS": the output is a BeiDou-only 3.02 navigation file, whose count is read on
    the BDS basis (rinex302.txt Table A5 p.63; navconv._leap_basis), so it is written so (Sol
    round 26: two BeiDou-only 3.02 files merged into 3.02 were written GPS 18, read back as
    BDS, so 32 in 4.02)."""
    if not check(rec, sv, tv):
        return rec                                 # unreadable, same version: as written
    c = rec.content
    ident = c.ljust(60)[24:27].strip()
    bds_terms = ident in BEIDOU_IDS or (basis == "BDS" and not ident)
    zv = zero_is_value(sv, bds_terms)
    if basis == "BDS" and tv != sv and not ident:
        report.assume("leap-seconds-basis", "BDS", "rinex302-bds-only-navigation-file")
    if out_basis == "BDS" and tv != sv:
        if bds_terms and zv and any(_int(c.ljust(24)[6 * k:6 * k + 6]) == 0 for k in range(4)):
            # a known 0 in BeiDou terms (3.03-3.05) reads "not known" in 3.02: written in GPS
            # terms, whose count (14 or more) navconv._leap_basis reads back as GPS
            c = as_gps(c.ljust(24)[:24] + "BDT", True)
            report.rule("LEAP.BDT-TO-GPS")
        elif not bds_terms:
            b = from_gps(c)
            g = [_int(c.ljust(24)[6 * k:6 * k + 6]) for k in range(4)]
            if any(known(x) and _int(b[6 * k:6 * k + 6]) == 0 for k, x in enumerate(g)):
                # a known field would become 0, which reads "not known": the GPS terms stay
                # (a count of 14 or more reads as GPS: navconv._leap_basis)
                b = c
            else:
                report.rule("LEAP.GPS-TO-BDS")
            c = b
        if not (basis == "BDS" and tv == sv):
            report.assume("leap-seconds-basis", "BDS", "rinex302-bds-only-navigation-file")
        c = c.ljust(24)[:24]                       # 3.02 has no identifier (4I6)
        return rec if c == rec.content else HeaderRecord("LEAP SECONDS", c, getattr(rec, "lineno", None))
    if basis == "BDS" and tv != sv and not ident:
        c = c.ljust(24)[:24] + "BDT"
    ident = c.ljust(60)[24:27].strip()
    if holds_bdt(tv) and ident in BEIDOU_IDS and ident != beidou_id(tv) and tv != sv:
        c = c.ljust(24)[:24] + beidou_id(tv) + c.ljust(60)[27:60].rstrip()
        report.rule("LEAP.BEIDOU-ID-SPELLING")
    if holds_bdt(tv) and ident in BEIDOU_IDS and not zv and tv != sv:
        # BeiDou terms whose zeros meant "not known" (a 3.02 BeiDou-only file) into a version
        # where a BeiDou 0 is a value (zero_is_value): the zeros are written blank
        if 0 in [_int(c.ljust(24)[6 * k:6 * k + 6]) for k in range(4)]:
            c = _blank_zeros(c)
            report.rule("LEAP.UNKNOWN-ZERO-BLANK")
    if not holds_bdt(tv):
        g = as_gps(c, zv)
        if g is not None:
            if c != g and not any(w["rule"] == "LEAP.BDT-TO-GPS" for w in report.warnings):
                report.warn("LEAP.BDT-TO-GPS", f"LEAP SECONDS in BDT written in GPS terms for RINEX {tv}: "
                            "leap seconds + 14, week + 1356, day + 1 (BDT is 14 s behind GPS time, its "
                            "week 0 is GPS week 1356: rinex_4.02.txt l.871, l.943), so a BDT week 0 "
                            "becomes GPS week 1356")
            c = g
            report.rule("LEAP.BDT-TO-GPS")
    w = width(tv)
    if w < width(sv) and c[w:60].strip():
        # a GPS identifier cut off loses nothing: without one the fields are GPS ones
        if c[w:60].strip() != "GPS":
            report.loss("header-field-not-representable:LEAP SECONDS", 1)
        c = c[:w]
    return rec if c == rec.content else HeaderRecord("LEAP SECONDS", c, getattr(rec, "lineno", None))
