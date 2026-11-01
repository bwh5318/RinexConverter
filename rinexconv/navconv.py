"""Navigation conversion between any two RINEX versions (PLAN §3.5 "Navigation").

Ephemerides keep their values as text tokens; only the layout, the exponent
letter and, where versions differ, the number of record lines change:
  * GLONASS: 4 lines up to 3.04, 5 from 3.05 and in 4.x FDMA (rinex305.txt Table A10).
    Going down drops line 5 (loss); going up fills it with the spec's "unknown"
    values (BNK, .999999999999E+09, 1.500000000000E+01, BNK), an assumption.
  * RINEX 4 message types: assigned when going up (G/J/I LNAV, R FDMA, S SBAS,
    C D1 or D2 by GEO PRN, E INAV/FNAV derived from the data-source bitmask, which
    is carried verbatim); going down only types with a RINEX 3 form survive.
  * RINEX 2 holds one system per file (n GPS, g GLONASS, h SBAS): a mixed source
    is split, and systems RINEX 2 lacks are dropped with a loss entry.
Header corrections (ION ALPHA/BETA, DELTA-UTC, CORR TO SYSTEM TIME,
D-UTC A0,A1,T,W,S,U <-> IONOSPHERIC CORR, TIME SYSTEM CORR <-> RINEX 4 ION/STO
records) go through one canonical form in navcorr.py.
"""

from dataclasses import dataclass
from decimal import Decimal

from rinexcore.errors import CorruptError, InvocationError, NotRepresentableError
from rinexcore.header import HeaderRecord
from rinexcore.nav import NavFile, NavRecord, token_value

from . import navcorr

GLO_LINE5_UNKNOWN = ["", ".999999999999E+09", "1.500000000000E+01", ""]
BDS_GEO = {1, 2, 3, 4, 5, 59, 60, 61, 62, 63}
V3_FORM = {("G", "LNAV"), ("J", "LNAV"), ("I", "LNAV"), ("R", "FDMA"), ("E", "INAV"),
           ("E", "FNAV"), ("C", "D1"), ("C", "D2"), ("S", "SBAS")}
V2_FILETYPE = {"G": "N", "R": "G", "S": "H"}
# as the spec examples spell them (rinex211.txt lines 1620, 1755, 2049)
V2_TYPE_TEXT = {"N": "N: GPS NAV DATA", "G": "GLONASS NAV DATA", "H": "H: GEO NAV MSG DATA"}
SYS_NAME = {"G": "GPS", "R": "GLONASS", "E": "GALILEO", "C": "BEIDOU", "J": "QZSS", "I": "NAVIC",
            "S": "SBAS", "M": "MIXED"}
GAL_DATASRC = 20     # vals index of Galileo BROADCAST ORBIT 5 field 2 (data sources)

# RINEX 4 EPH record line counts (rinex_4.02.txt Tables A9-A31, checked on the corpus)
V4_LINES = {("G", "LNAV"): 8, ("G", "CNAV"): 9, ("G", "CNV2"): 10, ("J", "LNAV"): 8,
            ("J", "CNAV"): 9, ("J", "CNV2"): 10, ("E", "INAV"): 8, ("E", "FNAV"): 8,
            ("R", "FDMA"): 5, ("C", "D1"): 8, ("C", "D2"): 8, ("C", "CNV1"): 10, ("C", "CNV2"): 10,
            ("C", "CNV3"): 9, ("S", "SBAS"): 4, ("I", "LNAV"): 8}


def eph_lines(version, system, msg=None):
    """Expected lines of an EPH record (SV/EPOCH line included), or None if unknown."""
    if version < "3":
        return {"G": 8, "R": 4, "S": 4, "E": 8}.get(system)
    if version < "4":
        if system == "R":
            return 5 if version >= "3.05" else 4
        if system == "S":
            return 4
        return 8
    return V4_LINES.get((system, msg))


@dataclass
class NavOptions:
    lenient: bool = False
    strict: bool = False
    dedupe: bool = False
    leap_seconds: int = None
    qzss_ion_area: str = None                         # WIDE | JAPN: the user's area for CNVX ION


def _value_or_text(tok):
    """A token's number (1.0D-08 and 0.10D-07 alike), or its text if it is not one (--lenient)."""
    try:
        return token_value(tok)
    except ArithmeticError:
        return tok


def galileo_msg(rec):
    """INAV or FNAV from the data-source bitmask (bit 0 I/NAV E1-B, bit 1 F/NAV E5a-I,
    bit 2 I/NAV E5b-I: rinex305.txt Table A8; rinex_4.02.txt Table A13). None if the
    bitmask does not decide."""
    try:
        v = token_value(rec.vals[GAL_DATASRC])
    except (IndexError, ArithmeticError):
        return None
    if v is None:
        return None
    bits = int(v)
    fnav = bool(bits & 2)
    inav = bool(bits & 5)
    if fnav and not inav:
        return "FNAV"
    if inav and not fnav:
        return "INAV"
    # Both source bits set (seen in merged IGS files, value 519): bits 8/9 say which
    # signal pair the clock parameters belong to (8: E5a,E1 = F/NAV; 9: E5b,E1 = I/NAV).
    c8, c9 = bool(bits & 256), bool(bits & 512)
    if c9 and not c8:
        return "INAV?"
    if c8 and not c9:
        return "FNAV?"
    return None


def v4_msg_for(rec, report):
    s = rec.system
    if s in "GJI":
        return "LNAV"
    if s == "R":
        return "FDMA"
    if s == "S":
        return "SBAS"
    if s == "C":
        return "D2" if int(rec.sat[1:]) in BDS_GEO else "D1"
    if s == "E":
        m = galileo_msg(rec)
        if m is None:
            raise CorruptError(f"Galileo record {rec.sat} {rec.time}: the data-source bitmask does "
                               "not tell I/NAV from F/NAV", line=rec.lineno, rule="NAV.GAL.DATASRC")
        if m.endswith("?"):
            m = m[:-1]
            report.assume("galileo-message-type", f"{m}-from-clock-bits", "derived:data-source-bits-8-9")
        return m
    return None


def convert_nav(src, target, opts, report, merge_with=None):
    """Returns a list of NavFile outputs (several when splitting into RINEX 2 files)."""
    sources = [src] + list(merge_with or [])
    sv = src.version
    tv = target
    recs = []
    for f in sources:
        for r in f.records:
            recs.append((f, r))
    if merge_with:
        report.rule("NAV.MERGE")

    area = opts.qzss_ion_area if tv >= "4.02" else None
    if area:
        # the option names one area for every QZSS CNVX ION set without one (sources before
        # 4.02, merged inputs included); both are broadcast (rinex_4.02.txt p.47), so two sets
        # of one satellite and time with different values contradict it
        sets = {}
        for f, r in recs:
            if f.version < "4.02" and r.kind == "ION" and r.system == "J" and r.msg == "CNVX" and not r.sub:
                sets.setdefault((r.sat, r.time), set()).add(tuple(_value_or_text(v) for v in r.vals))
        both = sorted(k for k, v in sets.items() if len(v) > 1)
        if both:
            raise InvocationError(
                f"--qzss-ion-area {area}: the input holds {len(sets[both[0]])} different QZSS CNVX "
                f"ION sets for {both[0][0]} at one time ({len(both)} such time(s)), so not every set "
                "can be that area; convert without the option (the sets are dropped and reported)")
    out_recs = []
    for f, r in recs:
        nr = _convert_record(f, r, tv, report, area)
        if nr is not None:
            out_recs.append(nr)

    if opts.dedupe:
        seen = set()
        kept = []
        dup = 0
        for r in out_recs:
            # by value: the same record written with D or E exponents, or another number of
            # digits, is a duplicate (Sol round 18: a 3.05 D and a 4.02 E record were both kept)
            key = (r.kind, r.sat, r.msg, r.sub, r.time, tuple(_dedupe_value(v) for v in r.vals), r.extra)
            if key in seen:
                dup += 1
                continue
            seen.add(key)
            kept.append(r)
        if dup:
            report.rule("NAV.DEDUPE", n=dup)
            report.loss("nav-duplicate-removed", dup)
        out_recs = kept
    if merge_with:
        order = {s: i for i, s in enumerate("GRECJIS")}
        out_recs.sort(key=lambda r: (order.get(r.system, 9), r.kind, r.sat, r.time,
                                     r.vals[3] if r.kind == "EPH" and len(r.vals) > 3 else ""))

    corr = navcorr.Corrections.from_sources(sources, report)
    if tv < "3":
        return _split_v2(src, sources, out_recs, corr, tv, report)

    src_eph = any(r.kind == "EPH" for f in sources for r in f.records)
    if src_eph and not any(r.kind == "EPH" for r in out_recs):
        syss = sorted({r.system for f in sources for r in f.records if r.kind == "EPH"})
        raise NotRepresentableError(
            f"RINEX {tv} navigation files cannot hold any record of this input "
            f"({', '.join(syss)}); nothing to write")
    nf = NavFile()
    nf.version = tv
    nf.version_str = tv
    nf.ftype = "N"
    nf.eol = src.eol
    syss = sorted({r.system for r in out_recs if r.kind == "EPH"}, key="GRECJIS".find)
    letter = syss[0] if len(syss) == 1 else "M"
    if not syss:
        letter = src.system.strip() or "M"
        if sv < "3":
            letter = {"N": "G", "G": "R", "H": "S"}.get(src.ftype, "M")
    if tv >= "4":
        extra_recs = corr.to_v4_records(tv, out_recs, report)
        out_recs = _v4_order(out_recs, extra_recs)
    nf.records = out_recs
    nf.system = letter
    nf.header = _header(src, sources, nf, tv, corr, report)
    if tv >= "4" and not any(r.label == "LEAP SECONDS" for r in nf.header):
        nf.header.append(_leap_from_table(nf, report, opts))
    return [nf]


def _leap_from_table(nf, report, opts):
    """LEAP SECONDS is compulsory in RINEX 4 nav files (rinex_4.00.txt §5.4, Table A7)."""
    from rinexcore import leapseconds
    import datetime
    from rinexcore.errors import MissingInformationError
    if getattr(opts, "leap_seconds", None) is not None:
        report.assume("leap-seconds", str(opts.leap_seconds), "override:--leap-seconds")
        return HeaderRecord("LEAP SECONDS", f"{opts.leap_seconds:6d}")
    eph = [r.time for r in nf.records if r.kind == "EPH"] or [r.time for r in nf.records]
    n = None
    if eph:
        t = min(eph)
        n = leapseconds.gps_utc(datetime.date(t[0], t[1], t[2]))
    if n is None:
        raise MissingInformationError(
            "RINEX 4 navigation files need LEAP SECONDS (rinex_4.00.txt Table A7); the source has "
            "none and the date is outside the built-in table; pass --leap-seconds",
            missing="leap-seconds")
    report.assume("leap-seconds", str(n), leapseconds.SOURCE)
    return HeaderRecord("LEAP SECONDS", f"{n:6d}")


def _v4_order(eph, extra):
    """RINEX 4 ION/STO/EOP records made from header corrections go first."""
    return list(extra) + list(eph)


# Message types RINEX 4 added after 4.00 (rinex_4.02.txt §5.4.4, §5.4.8, Tables A16, A17, A31,
# A33, A34, A38, A39; revision history Sep 2023 / Mar 2024): only 4.02 can hold them.
V402_EPH = {("R", "L1OC"), ("R", "L3OC"), ("I", "L1NV")}
V402_OTHER_MSGS = {"LXOC", "L1NV"}


def _convert_record(f, r, tv, report, area=None):
    sv = f.version
    s = r.system
    if tv >= "4" and tv < "4.02" and ((r.kind == "EPH" and (s, r.msg) in V402_EPH)
                                     or (r.kind != "EPH" and r.msg in V402_OTHER_MSGS)):
        report.loss(f"nav-message-not-representable:{s}:{r.msg}", 1)
        return None
    if r.kind == "EPH":
        want = eph_lines(sv, s, r.msg)
        if want is not None and r.nlines != want and not report_lenient(report):
            raise CorruptError(f"{r.sat} {r.msg or ''} record has {r.nlines} lines, RINEX {sv} "
                               f"defines {want}", line=r.lineno, rule="NAV.RECORD.LINES")
    if r.kind != "EPH":
        if tv >= "4":
            if r.kind == "ION" and s == "J" and r.msg == "CNVX" and not r.sub and tv >= "4.02" > sv:
                # 4.02 requires the area, WIDE or JAPN (rinex_4.02.txt Table 25 p.40, Table A35
                # note 3*); a 4.00/4.01 record does not say which it is, and it is not invented:
                # the user names it (--qzss-ion-area) or the record goes
                if area:
                    report.assume("qzss-ion-area", area, "user")
                    return NavRecord(r.kind, r.sat, r.msg, area, r.time, r.vals, r.extra, r.lineno, r.nlines)
                report.loss("nav-correction-not-representable:ION:CNVX-area-unknown:J", 1)
                return None
            if r.sub and tv < "4.02":
                # subtypes exist from 4.02 only (rinex_4.02.txt Table 25 p.40); the values are kept
                report.loss(f"nav-subtype-not-representable:{r.kind}:{s}:{r.msg}", 1)
                return NavRecord(r.kind, r.sat, r.msg, "", r.time, r.vals, r.extra, r.lineno, r.nlines)
            return r
        # STO/ION/EOP: handled by navcorr (header corrections) when going below 4
        return None
    msg = r.msg
    if sv >= "4" and tv < "4":
        if (s, msg) not in V3_FORM:
            report.loss(f"nav-message-not-representable:{s}:{msg}", 1)
            return None
        report.rule("NAV.V4V3.EPH")
    vals = list(r.vals)
    if tv < "3" and s not in V2_FILETYPE:
        report.loss(f"system-not-representable:{s}", 1)
        return None
    if tv >= "3" and not _system_in(tv, s):
        report.loss(f"system-not-representable:{s}", 1)
        return None
    # GLONASS fifth line
    if s == "R":
        n_have = 1 + (len(vals) - 3 + 3) // 4
        want = eph_lines(tv, "R", "FDMA")
        if want == 5 and len(vals) < 19:
            vals = vals + [""] * (15 - len(vals)) + list(GLO_LINE5_UNKNOWN)
            report.assume("glonass-nav-line5", "spec-unknown-values", "spec-default")
            report.rule("NAV.GLO.LINE5-FILLED")
        elif want == 4 and len(vals) > 15:
            line5 = (vals[15:19] + [""] * 4)[:4]
            if [token_value(x) for x in line5] != [token_value(x) for x in GLO_LINE5_UNKNOWN]:
                report.loss("glonass-nav-line5-dropped", 1)
            else:
                report.rule("NAV.GLO.LINE5-DEFAULT-DROPPED")   # only the "unknown" values: nothing lost
            vals = vals[:15]
            report.rule("NAV.GLO.LINE5-DROPPED")
    # pad to the full record length so short last lines keep their positions
    want = eph_lines(tv, s, msg if tv >= "4" else None)
    if tv >= "4":
        nmsg = msg if sv >= "4" else v4_msg_for(r, report)
        if sv < "4":
            report.rule(f"NAV.V3V4.MSGTYPE.{s}.{nmsg}")
        want = eph_lines(tv, s, nmsg)
    else:
        nmsg = None
    sec = r.time[5]
    if tv < "3" or sv < "3":
        if sec != sec.to_integral_value() and tv >= "3":
            report.loss("nav-epoch-precision", 1)
    t = r.time
    if tv >= "3" and sec != sec.to_integral_value():
        t = t[:5] + (sec.to_integral_value(rounding="ROUND_FLOOR"),)
    return NavRecord("EPH", r.sat, nmsg, r.sub if tv >= "4" else "", t, vals, "", r.lineno, r.nlines)


def report_lenient(report):
    return getattr(report, "lenient", False)


# Systems with a navigation data record per version: 3.00/3.01 GPS, Galileo, GLONASS, SBAS
# (rinex300.txt and rinex301.txt Tables A5-A11); QZSS and BDS from 3.02 (rinex302.txt Tables
# A12, A13); NavIC/IRNSS from 3.03 (rinex303.txt).
NAV_SYSTEMS = {"3.00": "GRES", "3.01": "GRES", "3.02": "GRESCJ"}


def _system_in(version, s):
    return s in NAV_SYSTEMS.get(version, "GRESCJI")


def _split_v2(src, sources, recs, corr, tv, report):
    outs = []
    for s in ("G", "R", "S"):
        mine = [r for r in recs if r.system == s and r.kind == "EPH"]
        if not mine and not (len(sources) == 1 and src.version < "3"
                             and V2_FILETYPE.get(s) == src.ftype):
            continue
        nf = NavFile()
        nf.version = tv
        nf.version_str = tv
        nf.ftype = V2_FILETYPE[s]
        nf.system = " "
        nf.eol = src.eol
        nf.records = mine
        nf.header = _header(src, sources, nf, tv, corr, report, v2sys=s, count_losses=not outs)
        outs.append(nf)
    corr.lose_unused_all(report)
    if not outs:
        # (system and message type: GPS CNAV is no RINEX 2 record although GPS LNAV is: Sonnet
        # round 25)
        kinds = sorted({f"{r.system} {r.msg}" if r.msg else r.system
                        for f in sources for r in f.records if r.kind == "EPH"})
        has = (f"ephemerides of {', '.join(kinds)} only" if kinds
               else "no ephemerides (only STO/EOP/ION records)")
        raise NotRepresentableError(
            f"RINEX {tv} navigation files hold only GPS LNAV (n), GLONASS FDMA (g) and SBAS (h) "
            f"ephemerides (rinex211.txt Tables A3, A10, A15); this input has {has}: nothing to write")
    return outs


V3_HDR_DROP_TO_V2 = {"IONOSPHERIC CORR", "TIME SYSTEM CORR"}
V2_CORR_LABELS = {"ION ALPHA", "ION BETA", "DELTA-UTC: A0,A1,T,W", "CORR TO SYSTEM TIME",
                  "D-UTC A0,A1,T,W,S,U"}
V4_ONLY = {"MERGED FILE", "DOI", "LICENSE OF USE", "STATION INFORMATION"}
KNOWN_NAV = V2_CORR_LABELS | V3_HDR_DROP_TO_V2 | V4_ONLY | {
    "RINEX VERSION / TYPE", "PGM / RUN BY / DATE", "COMMENT", "LEAP SECONDS", "REC # / TYPE / VERS"}


def _version_line(nf, tv, src):
    first = src.header[0] if src.header else None
    if tv < "3":
        text = V2_TYPE_TEXT[nf.ftype]
        if first is not None and src.version < "3" and src.ftype == nf.ftype:
            text = first.content[20:60]       # same file type: keep the writer's own text
        content = f"{tv:>9s}" + " " * 11 + text.ljust(40)
    else:
        if first is not None and src.version >= "3" and first.content[40:41] == "M":
            nf.system = "M"                   # a mixed file that happens to hold one system stays mixed
        sysfield = nf.system
        name = SYS_NAME.get(sysfield, "")
        if first is not None and src.version >= "3" and first.content[40:41] == sysfield:
            sf = first.content[40:60]
        else:
            sf = f"{sysfield}: {name}" if name else sysfield
        ftext = "N: GNSS NAV DATA"
        if first is not None and src.version >= "3" and first.content[20:21] == "N":
            ftext = first.content[20:40]          # the writer's own file-type text
        content = f"{tv:>9s}" + " " * 11 + ftext.ljust(20) + sf.ljust(20)
    return HeaderRecord("RINEX VERSION / TYPE", content)


class _NoLosses:
    """A report view that records everything except losses (they are counted once, on the
    first of several RINEX 2 files split from one input)."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def loss(self, *a, **k):
        pass


def _header(src, sources, nf, tv, corr, report, v2sys=None, count_losses=True):
    """count_losses: False for the second and later RINEX 2 file split from one input, so a
    header record lost from all of them is counted once. The corrections are different in
    each file (ION/DELTA-UTC in n, CORR TO SYSTEM TIME in g, D-UTC in h): their losses are
    always counted, against the real report."""
    full = report
    if not count_losses:
        report = _NoLosses(report)
    out = [_version_line(nf, tv, src)]
    placed_corr = False
    for f in sources[:1]:
        for rec in f.header:
            lab = rec.label
            if lab == "RINEX VERSION / TYPE":
                continue
            if lab in V2_CORR_LABELS or lab in V3_HDR_DROP_TO_V2:
                if not placed_corr:
                    out.extend(corr.header_records(tv, v2sys, full))
                    placed_corr = True
                continue
            if lab == "LEAP SECONDS":
                if not placed_corr:
                    out.extend(corr.header_records(tv, v2sys, full))
                    placed_corr = True
                # merged inputs: reconciled and converted once, below (_merge_leap)
                out.append(_leap(rec, tv, report, src.version, _leap_basis(src, rec), _out_basis(nf, tv))
                           if len(sources) == 1 else rec)
                continue
            if lab in V4_ONLY or (lab == "REC # / TYPE / VERS" and tv < "4"):
                if tv >= "4":
                    out.append(rec)
                elif tv == src.version:
                    # a record another version defines, in the file's own version: carried as
                    # written (Sol round 16)
                    report.rule("NAV.HDR.NONSTANDARD-CARRIED")
                    out.append(rec)
                else:
                    report.loss(f"header-record-not-representable:{lab}", 1)
                continue
            out.append(rec)
    if not placed_corr:
        recs = corr.header_records(tv, v2sys, full)
        # before LEAP SECONDS / END OF HEADER
        out.extend(recs)
    if len(sources) > 1:
        # the other inputs' records (Sol round 16: all but COMMENT went unreported). LICENSE OF
        # USE and STATION INFORMATION are "Line(s)" and DOI one record (rinex_4.02.txt Table A7
        # p.75-76), as REC # / TYPE / VERS is: another input's lines are added, a different
        # single record is claimed (the file can hold one), and records the target does not
        # define are claimed as for the first input. Corrections and LEAP SECONDS come from
        # every input already (Corrections); PGM / RUN BY / DATE describes each input's maker.
        _merge_leap(out, sources, tv, report, _out_basis(nf, tv))
        _merge_count(out, sources, tv, report)
        have = {(r.label, r.content.rstrip()) for r in out}
        for f in sources[1:]:
            for rec in f.header:
                lab = rec.label
                if lab == "COMMENT":
                    out.append(rec)
                    continue
                if lab == "PGM / RUN BY / DATE":
                    # one per navigation file (rinex_4.02.txt section 5.2.2: only observation
                    # files may add PGM lines): another input's maker has no room (Sol round 18)
                    if (lab, rec.content.rstrip()) not in have:
                        report.loss(f"merge-header-record-dropped:{lab}", 1)
                    continue
                if lab == "MERGED FILE" and tv < "4":
                    report.loss(f"header-record-not-representable:{lab}", 1)
                    continue
                if lab not in V4_ONLY - {"MERGED FILE"} and lab != "REC # / TYPE / VERS":
                    continue
                if tv < "4":
                    report.loss(f"header-record-not-representable:{lab}", 1)
                elif lab == "REC # / TYPE / VERS" or (lab, rec.content.rstrip()) in have:
                    continue                  # (receivers: below)
                elif lab == "DOI" and any(r.label == lab for r in out):
                    report.loss(f"merge-header-record-dropped:{lab}", 1)
                else:
                    out.append(rec)
                    have.add((lab, rec.content.rstrip()))
        if tv >= "4":
            # "Merged navigation files from multiple stations are not to include this header
            # line" (rinex_4.02.txt Table A7, REC # / TYPE / VERS note 2): kept only when every
            # input has the same receiver record, else every input's is claimed
            recv = [[r.content.rstrip() for r in f.header if r.label == "REC # / TYPE / VERS"] for f in sources]
            if any(recv) and not (all(len(x) == 1 for x in recv) and len({x[0] for x in recv}) == 1):
                out[:] = [r for r in out if r.label != "REC # / TYPE / VERS"]
                report.loss("merge-header-record-dropped:REC # / TYPE / VERS", sum(len(x) for x in recv))
    return out


def _dedupe_value(v):
    """A record value for --dedupe: its number, or its text if it is not one."""
    if not str(v).strip():
        return None
    try:
        return token_value(v).normalize()
    except Exception:                     # noqa: BLE001 - damaged tokens compare as text
        return ("text", v)


def _merge_count(out, sources, tv, report):
    """MERGED FILE, "Number of files merged (BNK)" (rinex_4.02.txt Table A7; section 6.11:
    "Merged navigation files should indicate it ... and if known include the number of files
    merged"): each input counts as its own MERGED FILE number, or 1; one with a blank number
    makes the total unknown (blank). RINEX 4 only (Sonnet round 18: the first input's 105 was
    kept for 105 + 85 merged files)."""
    if tv < "4":
        return
    total = 0
    for f in sources:
        mf = [r for r in f.header if r.label == "MERGED FILE"]
        if not mf:
            total = None if total is None else total + 1
        elif mf[0].content[:9].strip().isdigit() and total is not None:
            total += int(mf[0].content[:9])
        else:
            total = None
    rec = HeaderRecord("MERGED FILE", f"{total:9d}" if total is not None else "")
    i = next((k for k, r in enumerate(out) if r.label == "MERGED FILE"), None)
    if i is not None:
        out[i] = rec
    else:
        j = max((k for k, r in enumerate(out) if r.label == "PGM / RUN BY / DATE"), default=0)
        out.insert(j + 1, rec)
    report.rule("NAV.MERGE.COUNT")


def _merge_leap(out, sources, tv, report, out_basis=None):
    """One LEAP SECONDS record from every merged input's (Sol round 17: the other inputs' were
    ignored). Fields are compared in GPS terms (leap.as_gps); records that agree combine
    (one may give the future leap second the other leaves blank); a record that disagrees
    (e.g. inputs on either side of a leap second) has no room, the file holding one, and is
    claimed merge-header-record-dropped:LEAP SECONDS. The result goes where the first
    input's was, or before END OF HEADER."""
    from . import leap

    def fields(rec, version, basis):
        # each input in its own terms: BDS/BDT records, and a BeiDou-only 3.02 file's
        # (_leap_basis), in GPS terms before they are compared (Sol round 25: a 3.02 BeiDou 4
        # merged with a GPS 18 was written as GPS 4, or claimed lost the other way round)
        c = rec.content.ljust(60)
        if basis == "BDS" and not c[24:27].strip():
            c = c[:24] + "BDT" + c[27:]
        c = (leap.as_gps(c) or c)[:leap.width(version)].ljust(24)
        v = [leap._int(c[6 * k:6 * k + 6]) for k in range(4)]
        # only known fields are reconciled: 0 or blank is "not known" (rinex302.txt Table A5
        # p.63), and a day goes with its week (Sol round 28: an unknown 0 overrode a GPS 18)
        v = [x if leap.known(x) else None for x in v]
        if v[2] is None:
            v[3] = None
        return v
    best, first, src_rec = None, None, None
    for f in sources:
        for r in f.header:
            if r.label != "LEAP SECONDS":
                continue
            rb = _leap_basis(f, r)        # (a record without identifier counted from 2006)
            v = fields(r, f.version, rb)
            if all(x is None for x in v):
                continue                  # a blank record says nothing (Sol round 18: TypeError)
            if rb == "BDS":
                # reconciled in GPS terms (below), then written in the output's own terms:
                # BDS for a BeiDou-only 3.02 output (out_basis), GPS otherwise
                report.assume("leap-seconds-basis", "BDS", "rinex302-bds-only-navigation-file")
            if best is None:
                best, first, src_rec = v, (f is sources[0] and rb is None), (r, f.version, rb)
            elif all(a is None or b is None or a == b for a, b in zip(best, v)):
                if any(a is None and b is not None for a, b in zip(best, v)):
                    best = [a if a is not None else b for a, b in zip(best, v)]
                    first = False
            else:
                report.loss("merge-header-record-dropped:LEAP SECONDS", 1)
    if best is None:
        return
    if first:                             # the first input's record as it is
        rec = _leap(src_rec[0], tv, report, src_rec[1], src_rec[2], out_basis)
    else:
        if any(x is not None for x in best[1:]):
            txt = "".join(" " * 6 if x is None else f"{x:6d}" for x in best) + "GPS"
        else:
            txt = f"{best[0]:6d}"
        rec = _leap(HeaderRecord("LEAP SECONDS", txt), tv, report, "4.02", None, out_basis)
    i = next((k for k, r in enumerate(out) if r.label == "LEAP SECONDS"), None)
    if i is not None:
        out[i] = rec
    else:
        j = next((k for k, r in enumerate(out) if r.label == "END OF HEADER"), len(out))
        out.insert(j, rec)


def _leap(rec, tv, report, sv, basis=None, out_basis=None):
    from . import leap
    return leap.for_target(rec, sv, tv, report, basis, out_basis)


def _out_basis(nf, tv):
    """'BDS' when the output is a 3.02 navigation file of BeiDou records only: _leap_basis
    reads such a file's count on the BDS basis, so it must be written so."""
    if tv != "3.02":
        return None
    syss = {r.system for r in nf.records if r.kind == "EPH"}
    return "BDS" if syss == {"C"} else None


def _leap_basis(src, rec=None):
    """'BDS' when a LEAP SECONDS record without an identifier, in a 3.02-3.05 navigation file
    of BeiDou records only, counts from 2006 (BDS); else None (GPS). 3.02 counts "since
    6-Jan-1980 as transmitted by the GPS almanac or since 1-Jan-2006 as transmitted by BDS
    almanac" (rinex302.txt Table A5 p.63); 3.03-3.05 say "When BDS only file leap seconds
    specified, weeks since 1-Jan-2006" but also "Blank defaults to GPS" (rinex303.txt p.60,
    rinex304.txt p.65, rinex305.txt Table A5). Real BeiDou-only files do both: ADIS00ETH 3.04
    writes '4 4 573 6', KLSQ00GRL and QAQ100GRL 3.05 write '18' (corpus, round 27). The count
    tells them apart: GPS-UTC has been 14 s or more since 2006 (BDS week 0), BDT-UTC 4 s at
    most, so a count below 14 is a BDS one (reported as an assumption by for_target)."""
    if not "3.02" <= src.version < "4":
        return None
    if {r.system for r in src.records if r.kind == "EPH"} != {"C"}:
        return None
    if rec is None:
        return "BDS"
    c = rec.content.ljust(60)
    cur = c[0:6].strip()
    if c[24:27].strip() or not cur.lstrip("-").isdigit():
        return None
    return "BDS" if 0 < int(cur) < 14 else None     # (0: "not known", rinex302.txt p.63)
