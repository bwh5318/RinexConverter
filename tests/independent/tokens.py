"""Naive, independent tokeniser for RINEX obs, nav and met files (PLAN §1.5a).

Deliberately does NOT import rinexcore or rinexconv: it re-reads the formats
with its own simple code so that a shared mistake cannot hide. It knows only
what it needs to say "this value, at this epoch, for this satellite and this
signal".

Obs token:  (epoch, sat, signal-class, value-text, lli, ssi)
Nav token:  per record key (kind, sat, epoch) -> multiset of numeric values
Met token:  (epoch, met-type, value)
"""

import json
import os
from collections import Counter
from decimal import ROUND_HALF_EVEN, Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "code_expectations.json"), "rb") as _fh:
    EXPECT = json.loads(_fh.read().decode("utf-8"))


def lines_of(payload):
    t = payload.decode("latin-1").replace("\r\n", "\n")
    out = t.split("\n")
    if out and out[-1] == "":
        out.pop()
    return out


def _version(lines):
    return float(lines[0][:9])


def _vkey(lines):
    return "%.2f" % _version(lines)


def _hdr_end(lines):
    for i, l in enumerate(lines):
        if l[60:80].strip() == "END OF HEADER":
            return i
    raise ValueError("no END OF HEADER")


def _year(y):
    y = int(y)
    if y < 100:
        y += 1900 if y >= 80 else 2000
    return y


def _epoch(y, mo, d, h, mi, s):
    return (_year(y), int(mo), int(d), int(h), int(mi), Decimal(s.strip()).normalize())


def signal_class(vkey, sysc, code, exact=False):
    """Class of an observation code; independent of the converter's code map. With exact
    (both files RINEX 3/4) the attribute is kept, so swapped attributes are caught; only the
    BeiDou B1I band digit, which the versions spell differently, is normalised."""
    if exact and len(code) == 3:
        if sysc == "C":
            band, attr = code[1], code[2]
            b1i = EXPECT["bds_b1i_band"].get(vkey, EXPECT["bds_b1i_band"]["default"])
            if (band == b1i and attr in "IQX") or (band == "1" and (attr in "IQ" or (attr == "X" and vkey < "3.04"))) \
                    or (band == "2" and attr in "IQX" and EXPECT.get("bds_band2_IQX_always_b1i")):
                return f"C:{code[0]}:B1I:{attr}"
        return f"{sysc}:{code}"
    if len(code) == 2:
        t, band = code[0], code[1]
        if t == "P":
            return f"{sysc}:C:{band}:P"
        if t == "C" and sysc in EXPECT["v2_code_groups"]:
            g = EXPECT["v2_code_groups"][sysc].get(code)
            if g:
                return f"{sysc}:C:{band}:{g}"
        if sysc == "C" and band in "12":
            return f"C:{t}:B1I"
        return f"{sysc}:{t}:{band}"
    t, band, attr = code[0], code[1], code[2]
    if sysc == "C":
        b1i = EXPECT["bds_b1i_band"].get(vkey, EXPECT["bds_b1i_band"]["default"])
        if band == b1i and attr in "IQX":
            return f"C:{t}:B1I"
        if EXPECT.get("bds_band1_IQ_always_b1i") and band == "1" and (attr in "IQ" or (attr == "X" and vkey < "3.04")):
            return f"C:{t}:B1I"
        if EXPECT.get("bds_band2_IQX_always_b1i") and band == "2" and attr in "IQX":
            return f"C:{t}:B1I"
    groups = EXPECT["v3_code_groups"].get(sysc, {}).get("C" + band)
    if t == "C" and groups:
        return f"{sysc}:C:{band}:{groups.get(attr, attr)}"
    return f"{sysc}:{t}:{band}"


def _lead0(v):
    """'.097' -> '0.097', '-.097' -> '-0.097': the same F14.3 value, as CRX2RNX prints it
    (docs/HATANAKA.md section 9) and as other writers do."""
    if v.startswith("."):
        return "0" + v
    if v.startswith("-."):
        return "-0" + v[1:]
    return v


def _is_missing(v):
    """Blank or zero: both mean "missing" (rinex211.txt ~1288, rinex305.txt §6.7)."""
    return not v.strip(" 0.+-")


def _wl_update(state, line):
    """RINEX 2 WAVELENGTH FACT L1/2 (2I6,I6,7(3X,A1,I2); rinex211.txt Table A1)."""
    c = line[:60].ljust(60)
    f1 = int(c[0:6]) if c[0:6].strip() else 1
    f2 = int(c[6:12]) if c[6:12].strip() else 0
    n = int(c[12:18]) if c[12:18].strip() else 0
    if n == 0:
        state["*"] = (f1, f2)
    for k in range(min(n, 7)):
        it = c[21 + 6 * k:24 + 6 * k]
        if it.strip():
            state[(it[0] if it[0] != " " else "G") + "%02d" % int(it[1:3])] = (f1, f2)


def has_half_wavelength(lines):
    for l in lines:
        if l[60:80].strip() == "WAVELENGTH FACT L1/2" and "2" in l[0:12]:
            return True
    return False


def _a3(text):
    """RINEX 3/4 observation codes of a record's 1X,A3 fields: a two-character token is a code
    with a blank attribute ('L1 ', allowed in 3.00/3.01: rinex300.txt l.690), which stays
    three characters, so a claim or scale factor naming 'L1 ' finds it."""
    return [x + " " if len(x) == 2 else x for x in text.split()]


def _scale_update(scale, lines):
    """SYS / SCALE FACTOR lines (A1,1X,I4,2X,I2,12(1X,A3), continuation 10X,12(1X,A3):
    rinex305.txt Table A2 p.56-57, 'factor to divide stored observations with before use',
    '0 or blank: all observation types'). The lines of one place (the header, or one event)
    are one group: in it a listed code's factor beats its system's 'all types' one in either
    record order, as the lookup in obs_tokens tries (sys, code) first (the spec gives no
    precedence for overlapping records, rinex305.txt section 5.2.11: an inference, the same
    for the header and for events). A later group holds from there on for what it names
    (rinex305.txt section 6.5): a system it gives an 'all types' factor loses its earlier
    factors, otherwise only the listed codes change (round 32: the lines were applied one by
    one, so 'G 100 1 L1C' then 'G 10' in an event lost L1C=100)."""
    grp = {}
    cur = None
    for l in lines:
        c = l[:60].ljust(60)
        if c[0] != " ":
            fac = int(c[2:6]) if c[2:6].strip() else 1
            codes = _a3(c[10:60])
            cur = (c[0], fac)
            if not codes:
                grp[(c[0], "*")] = fac
            for code in codes:
                grp[(c[0], code)] = fac
        elif cur is not None:
            for code in _a3(c[10:60]):
                grp[(cur[0], code)] = cur[1]
    for s in {k[0] for k in grp if k[1] == "*"}:
        for k in [k for k in scale if k[0] == s]:
            del scale[k]
    scale.update(grp)
    return grp


def _v2_scale_update(scale, lines):
    """RINEX 2 OBS SCALE FACTOR lines: the unofficial RINEX 2.20 record (Gurtner and Estey 2002,
    cited in rinex300.txt l.1583) of which SYS / SCALE FACTOR 'is a modification' (rinex300.txt
    section 5.5): I6 factor to divide the stored observations with, I6 number of types (0 or
    blank: all types), 8(4X,A2) types; a line with no factor continues the types before it.
    UNVERIFIED: the 2.20 document is not in specs/; this is the layout the round-32 brief gives.
    RINEX 2 has one type list for every system, so the keys are ('', code) and ('', '*').
    The lines of one place are one group, as in _scale_update (listed beats 'all types')."""
    grp = {}
    cur = None
    for l in lines:
        c = l[:60].ljust(60)
        if c[0:6].strip():
            fac = int(c[0:6])
            codes = c[12:60].split()
            cur = fac
            if not codes:
                grp[("", "*")] = fac
            for code in codes:
                grp[("", code)] = fac
        elif cur is not None:
            for code in c[6:60].split():
                grp[("", code)] = cur
    if ("", "*") in grp:
        for k in [k for k in scale if k[0] == ""]:
            del scale[k]
    scale.update(grp)


_Q3 = Decimal("0.001")


def _physical(text, fac):
    """A stored value divided by its scale factor, as text: F14.3 style when it has at most 3
    decimals (as an unscaled field would read), else every digit (it needs rounding to fit a
    target without factors; compare_obs checks that against the report)."""
    v = Decimal(text) / fac
    q = v.quantize(_Q3)
    return f"{q:.3f}" if q == v else f"{v.normalize():f}"


class _Counts(Counter):
    """Counter of values per (sys, code), with ``later``: values in repeated columns;
    ``lists``: the obs-type lists in force, in order (0 = the header's, then each flag-4
    list), each {sys: [codes]} ('*' for RINEX 2's one list); ``by_state`` and
    ``later_by_state``: the same counts per (list index, sys, code); ``flags``,
    ``flags_by_state`` and ``flags_later_by_state``: fields with no value but an LLI or SSI
    flag."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.later = Counter()
        self.lists = []
        self.by_state = Counter()
        self.later_by_state = Counter()
        self.flags = Counter()
        self.flags_by_state = Counter()
        self.flags_later_by_state = Counter()
        self.records = Counter()          # satellite records per system (data epochs)
        self.records_by_list = Counter()  # satellite records per obs-type list index
        self.record_lists = []            # ((epoch, flag), satellite, list index) of every record
        # data-section lines with non-blank text in columns no field covers (a --lenient
        # converter drops it and claims data-text-dropped, one per line: compare_obs)
        self.skipped = 0
        # (sys, code, delta) -> phase values moved back by delta (obs_tokens adjust)
        self.adjusted = Counter()
        self.adjust_rounded = Counter()   # (sys, target code): shifted values rounded to 3 decimals
        self.adjust_clipped = Counter()   # (sys, target code): shifted values clipped by 1e9


def obs_tokens(lines, v3_lli=False, exact=False, drop=None, adjust=None, norm=None, factors=None):
    """({(epoch, sat, flag): sorted tuple of (signal-class, value, lli, ssi)},
    {(sys, code): count of non-missing values}). A missing value (blank or zero) with an LLI
    or SSI flag is an item with value '' (flags kept, no observation counted); one without
    flags is no item. The counter's ``later`` attribute counts the
    values in a code's second and further columns, for a code a type list names twice.

    drop: {(sys, source code): 'all' | 'later'}: leave out those columns (all of them, or
    those after a code's first column), so that what remains must match the output exactly:
    the values of a signal claimed lost must be that signal's, not another's of the same
    class (L1W instead of L1C).

    v3_lli: express a RINEX 2 file's LLI as RINEX 3 would. RINEX 2 bit 1 means "opposite
    wavelength factor"; RINEX 3 bit 1 means half-cycle ambiguity, so for GPS L1/L2 phase
    with factor 2 the bit flips (flags 0/1 only; rinex211.txt Tables A1/A2, rinex305.txt §6.7).

    adjust(sys, code, sat, epoch, stored value, input factor, slip, scope) -> (shift in cycles,
    target code, output factor or None) or None (scope: 0 for the header's factor, else the
    line of the last event whose SYS / SCALE FACTOR names the code or all its system's types): the value a converter applying that shift must write,
    made from this (input) phase value of a flag 0/1 record and stored under the output's factor
    (rounded, clipped: see add), counted in ``adjusted`` (sys, target code, shift),
    ``adjust_rounded`` and ``adjust_clipped``; with adjust or norm, every phase value of flags
    0/1 is written as a normalised number, so a shifted value and the output's compare by value
    (--align-phases: compare_obs). A flag 6 (cycle slip) phase value is shown to adjust with
    slip=True and kept as it is.

    factors: a dict filled with {(epoch, sat, code, is flag 6): the factor} for every phase
    value of flags 0, 1 and 6 (the output's: compare_obs gives them to adjust).

    Records are keyed by epoch and satellite so that identical records compare in one
    step; the comparator expands only records that differ."""
    vkey = _vkey(lines)
    v3 = _version(lines) >= 3
    end = _hdr_end(lines)
    head = lines[:end]
    single = lines[0][40:41].strip() or "G"
    if single == "M":
        single = "G"
    types = {}
    v2types = []
    cur = None
    for l in head:
        lab = l[60:80].strip()
        if lab == "# / TYPES OF OBSERV":
            if l[:6].strip():
                v2types = []
            v2types += l[6:60].split()
        elif lab == "SYS / # / OBS TYPES":
            if l[0] != " ":
                cur = l[0]
                types[cur] = []
            types[cur] += _a3(l[7:60])
    recs = {}
    codes = _Counts()
    sidx = [0]                     # index of the obs-type list in force (codes.lists)

    def snap():
        """The list now in force: an identical earlier one is the same state (the converter
        keys its states by content too: Sol round 11, a flag-4 event repeating a list)."""
        lst = {s: list(c) for s, c in types.items()} if v3 else {"*": list(v2types)}
        for k, old in enumerate(codes.lists):
            if old == lst:
                sidx[0] = k
                return
        codes.lists.append(lst)
        sidx[0] = len(codes.lists) - 1
    snap()
    classes = {}
    wl = {"*": (1, 1)}
    scale = {}
    scope_at = {}                  # (sys, code or '*') -> line of the last event with its factor
    if v3:
        _scale_update(scale, [l for l in head if l[60:80].strip() == "SYS / SCALE FACTOR"])
    else:
        _v2_scale_update(scale, [l for l in head if l[60:80].strip() == "OBS SCALE FACTOR"])
    if v3_lli:
        for l in head:
            if l[60:80].strip() == "WAVELENGTH FACT L1/2":
                _wl_update(wl, l)

    def cls(sysc, code):
        k = (sysc, code)
        c = classes.get(k)
        if c is None:
            c = classes[k] = signal_class(vkey, sysc, code, exact)
        return c

    def add(key, sysc, clist, body, start):
        codes.records[sysc] += 1
        codes.records_by_list[sidx[0]] += 1
        codes.record_lists.append(((key[0], key[2]), key[1], sidx[0]))
        items = []
        o = start
        fac = wl.get(key[1], wl["*"]) if v3_lli and sysc == "G" and key[2] <= 1 else None
        seen = set()
        for code in clist:
            f = body[o:o + 16]
            o += 16
            again = code in seen
            seen.add(code)
            if drop:
                d = drop.get((sidx[0], sysc, code)) or drop.get((None, sysc, code))
                if d == "all" or (d == "later" and again):
                    continue
            v = f[:14]
            f = f.ljust(16)
            if _is_missing(v):
                if f[14:16].strip():
                    # a flag on a missing value: no observation, but flags the converter keeps
                    # (or claims flags-on-missing-value-dropped); compared, counted apart
                    codes.flags[(sysc, code)] += 1
                    codes.flags_by_state[(sidx[0], sysc, code)] += 1
                    if again:
                        codes.flags_later_by_state[(sidx[0], sysc, code)] += 1
                    items.append((cls(sysc, code), "", f[14], f[15]))
                continue
            codes[(sysc, code)] += 1
            codes.by_state[(sidx[0], sysc, code)] += 1
            if again:
                codes.later[(sysc, code)] += 1
                codes.later_by_state[(sidx[0], sysc, code)] += 1
            lli = f[14]
            if fac is not None and code in ("L1", "L2") and fac[int(code[1]) - 1] == 2:
                b = (int(lli) if lli.strip() else 0) ^ 2
                lli = str(b) if b or lli.strip() else " "     # a written LLI stays written ('0')
            sf = (scale.get((sysc, code)) or scale.get((sysc, "*")) or scale.get(("", code))
                  or scale.get(("", "*"))) if scale else None
            val = _physical(v.strip(), sf) if sf and sf != 1 else _lead0(v.strip())
            if code[:1] == "L" and factors is not None and (key[2] <= 1 or key[2] == 6):
                factors[(key[0], key[1], code, key[2] == 6)] = Decimal(sf) if sf else Decimal(1)
            # the scope of a code's factor: the header (0), then from each event whose SYS / SCALE
            # FACTOR names the code or all its system's types (rinex305.txt section 6.5)
            scope = max(scope_at.get((sysc, code), 0), scope_at.get((sysc, "*"), 0)) if scope_at else 0
            if code[:1] == "L" and key[2] == 6 and adjust is not None:
                adjust(sysc, code, key[1], key[0], Decimal(v.strip()), sf or Decimal(1), True, scope)
            if code[:1] == "L" and key[2] <= 1 and (adjust is not None or norm):
                # --align-phases: the value the output must hold, from this (input) value moved by
                # a known shift (cycles), stored under the output's own factor for it (its SYS /
                # SCALE FACTOR, from the output's tokens), rounded half-even to F14.3's 3 decimals,
                # and past F14.3 clipped by 1e9 with LLI bit 0 set (rinex305.txt section 6.7;
                # rinex211.txt Table A2); phases compare as numbers
                fin = sf if sf else Decimal(1)
                r = (adjust(sysc, code, key[1], key[0], Decimal(v.strip()), fin, False, scope)
                     if adjust is not None else None)
                if r:
                    d, tcode, fout = r
                    fo = fout or fin
                    x = (Decimal(v.strip()) / fin + d) * fo
                    q = x.quantize(_Q3, rounding=ROUND_HALF_EVEN)
                    if q != x:
                        codes.adjust_rounded[(sysc, tcode)] += 1
                    t = f"{q:.3f}"
                    if len(t.replace("0.", ".", 1) if t.lstrip("-").startswith("0.") else t) > 14:
                        q = q - 10 ** 9 if q > 0 else q + 10 ** 9
                        lli = str((int(lli) if lli.strip() else 0) | 1)
                        codes.adjust_clipped[(sysc, tcode)] += 1
                    if d:
                        codes.adjusted[(sysc, tcode, d)] += 1
                    val = str(q / fo)
                val = f"{Decimal(val).normalize():f}"
            items.append((cls(sysc, code), val, lli, f[15]))
        items.sort()
        old = recs.get(key)
        recs[key] = tuple(items) if old is None else tuple(sorted(old + tuple(items)))

    i = end + 1
    n = len(lines)
    while i < n:
        l = lines[i]
        if not l.strip():
            i += 1
            continue
        if v3:
            flag = int(l[29:32])
            ns = int(l[32:35])
            # EPOCH record (rinex305.txt Table A3 p.59, rinex_4.02.txt Table A3): 6X reserved
            # at columns 36-41, nothing after column 62 (the 4.02 picosecond field), and
            # before 4.02 nothing after column 56 (no picosecond field there)
            ps4 = vkey >= "4.02"
            if l[35:41].strip() or l[62:].strip() or (not ps4 and l[56:62].strip()):
                codes.skipped += 1
            ep = None if not l[2:29].strip() else _epoch(l[2:6], l[7:9], l[10:12], l[13:15], l[16:18],
                                                         l[18:29])
            if ep is not None and ps4 and l[57:62].strip():
                ep = ep[:5] + ((ep[5] + Decimal(l[57:62]) * Decimal("1e-12")).normalize(),)
            i += 1
            if 2 <= flag <= 5:
                changed = False
                for k in range(ns):
                    hl = lines[i + k]
                    if hl[60:80].strip() == "SYS / # / OBS TYPES":
                        changed = True
                        if hl[0] != " ":
                            cur = hl[0]
                            types[cur] = []
                        types[cur] += _a3(hl[7:60])
                if changed:
                    snap()
                sf_lines = [lines[i + k] for k in range(ns) if lines[i + k][60:80].strip() == "SYS / SCALE FACTOR"]
                if sf_lines and 2 <= flag <= 5:
                    for g in _scale_update(scale, sf_lines):
                        scope_at[g] = i          # (sys, code or '*'): this event's from here on
                i += ns
                continue
            for k in range(ns):
                d = lines[i + k]
                sat = d[0] + "%02d" % int(d[1:3])
                if d[3 + 16 * len(types.get(sat[0], [])):].strip():
                    codes.skipped += 1            # past the last declared field
                add((ep, sat, flag), sat[0], types.get(sat[0], []), d, 3)
            i += ns
        else:
            l = l.ljust(80)
            flag = int(l[26:29])
            ns = int(l[29:32]) if l[29:32].strip() else 0
            ep = None if not l[0:26].strip() else _epoch(l[1:3], l[4:6], l[7:9], l[10:12], l[13:15],
                                                         l[15:26])
            # EPOCH/SAT or EVENT FLAG record (rinex211.txt Table A2): 80 columns; an event has
            # no satellite list (columns 33-68), only the optional clock at 69-80
            if l[80:].strip() or (2 <= flag <= 5 and l[32:68].strip()):
                codes.skipped += 1
            i += 1
            if 2 <= flag <= 5:
                changed = False
                for k in range(ns):
                    hl = lines[i + k]
                    if hl[60:80].strip() == "# / TYPES OF OBSERV":
                        changed = True
                        if hl[:6].strip():
                            v2types = []
                        v2types += hl[6:60].split()
                    elif v3_lli and hl[60:80].strip() == "WAVELENGTH FACT L1/2":
                        _wl_update(wl, hl)
                sf_lines = [lines[i + k] for k in range(ns) if lines[i + k][60:80].strip() == "OBS SCALE FACTOR"]
                if sf_lines and 2 <= flag <= 5:
                    _v2_scale_update(scale, sf_lines)
                if changed:
                    snap()
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
                    sl = lines[i].ljust(80)
                    if sl[68:].strip():
                        codes.skipped += 1        # continuation: 32X,12(A1,I2) ends at 68
                    i += 1
            per = max(1, (len(v2types) + 4) // 5)
            last = 16 * len(v2types) - 80 * (per - 1)
            for sat in sats:
                # 5 fields of 16 columns per line; the last line ends after the last type's
                codes.skipped += sum(1 for k in range(per)
                                     if lines[i + k][80 if k < per - 1 else last:].strip())
                rec = "".join(lines[i + k][:80].ljust(80) for k in range(per))
                i += per
                add((ep, sat, flag), sat[0], v2types, rec, 0)
    return recs, codes


def _num(t):
    t = t.strip()
    if not t:
        return None
    return Decimal(t.replace("D", "E").replace("d", "e")).normalize()


def nav_tokens(lines):
    """{(kind, sat, epoch): [(msg, values), ...]}: every record's numeric fields by position
    (None for a blank field, trailing blanks trimmed). Line 0 holds 3 positions, every
    further line 4; RINEX 2, 3 and 4 EPH bodies line up position for position."""
    v = _version(lines)
    end = _hdr_end(lines)
    ftype = lines[0][20:21]
    dsys = {"N": "G", "G": "R", "H": "S"}.get(ftype, "G")
    recs = {}
    cur = None
    i = end + 1
    n = len(lines)

    def start(key, msg, vals, parsed=None):
        nonlocal cur
        cur = parsed if parsed is not None else [_num(x) for x in vals]
        recs.setdefault(key, []).append((msg, cur))

    while i < n:
        l = lines[i]
        if not l.strip():
            i += 1
            continue
        if v >= 4 and l.startswith(">"):
            t = l[1:].split()
            kind = t[0]
            sat = t[1][0] + ("%02d" % int(t[1][1:]) if len(t[1]) > 1 else "  ")
            body = lines[i + 1].ljust(80)
            ep = _epoch(body[4:8], body[9:11], body[12:14], body[15:17], body[18:20], body[21:23])
            # message type, with the 4.02 subtype when there is one (e.g. 'CNVX WIDE': the
            # coefficient area, rinex_4.02.txt Table 25 p.40)
            msg = " ".join(t[2:4])
            if kind == "STO":
                # line 0 after the epoch: time-offset code, SBAS ID and UTC ID, 1X,A18 each
                # (rinex_4.02.txt Table A33 p.115), held in the three line-0 positions as text
                # (None: blank), so a changed or added identifier is a difference (round 32)
                start((kind, sat, ep), msg, None,
                      [body[24 + 19 * k:42 + 19 * k].strip() or None for k in range(3)])
            else:
                bsat = body[0:1] + ("%02d" % int(body[1:3]) if body[1:3].strip().isdigit() else body[1:3])
                if kind == "EPH" and bsat != sat:
                    # the body's own satellite (A1,I2.2: Table A9) must be the header line's;
                    # a mismatch is kept in the message type, so it shows as a difference
                    msg += f" !BODY:{body[0:3]}"
                start((kind, sat, ep), msg, [body[23 + 19 * k:42 + 19 * k] for k in range(3)])
            i += 2
            continue
        l = l.ljust(80)
        if v < 3:
            if l[0:2].strip():
                sat = (l[0] if l[0].isalpha() else dsys) + "%02d" % int(l[0:2] if not l[0].isalpha() else l[1:3])
                ep = _epoch(l[3:5], l[6:8], l[9:11], l[12:14], l[15:17], l[17:22])
                start(("EPH", sat, ep), "", [l[22 + 19 * k:41 + 19 * k] for k in range(3)])
            else:
                cur.extend(_num(l[3 + 19 * k:22 + 19 * k]) for k in range(4))
        else:
            if l[0] != " ":
                sat = l[0] + "%02d" % int(l[1:3])
                ep = _epoch(l[4:8], l[9:11], l[12:14], l[15:17], l[18:20], l[21:23])
                start(("EPH", sat, ep), "", [l[23 + 19 * k:42 + 19 * k] for k in range(3)])
            else:
                cur.extend(_num(l[4 + 19 * k:23 + 19 * k]) for k in range(4))
        i += 1
    for key, lst in recs.items():
        for msg, vals in lst:
            while vals and vals[-1] is None:
                vals.pop()
    return recs


def met_tokens(lines):
    # 4-digit met years from 3.02 (rinex302.txt ~4218); 2 digits in 2.x, 3.00, 3.01
    v3 = _version(lines) >= 3.02
    end = _hdr_end(lines)
    types = []
    for l in lines[:end]:
        if l[60:80].strip() == "# / TYPES OF OBSERV":
            if l[:6].strip():
                types = []
            types += l[6:60].split()
    tok = Counter()
    i = end + 1
    h = 20 if v3 else 18
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            i += 1
            continue
        p = 5 if v3 else 3
        ep = _epoch(l[1:p], l[p + 1:p + 3], l[p + 4:p + 6], l[p + 7:p + 9], l[p + 10:p + 12], l[p + 13:p + 15])
        vals = [l.ljust(h + 56)[h + 7 * k:h + 7 * k + 7] for k in range(min(8, len(types)))]
        i += 1
        while len(vals) < len(types):
            c = lines[i].ljust(74)
            vals += [c[4 + 7 * k:11 + 7 * k] for k in range(min(10, len(types) - len(vals)))]
            i += 1
        for t, x in zip(types, vals):
            if x.strip():
                tok[(ep, t, Decimal(x.strip()).normalize())] += 1
    return tok
