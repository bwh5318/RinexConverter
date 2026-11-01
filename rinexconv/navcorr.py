"""Ionosphere and time-system corrections across RINEX nav versions.

Canonical items:
  iono  {'model': 'KLOB'|'NEQG'|other, 'sys', 'p': [tokens], 'tmark', 'svid', 'rec', 'origin'}
        KLOB p = alpha0..3 + beta0..3; NEQG p = ai0..ai2 + disturbance flags
  time  {'code', 'a0', 'a1', 'a2', 'T', 'W', 'sat', 'utc', 'sbas', 'ref', 'ttm', 'rec', 'origin'}

Sources and targets (with spec references):
  v2 GPS   ION ALPHA / ION BETA (2X,4D12.4), DELTA-UTC: A0,A1,T,W (3X,2D19.12,2I9)
           (rinex211.txt Table A3)
  v2 GLO   CORR TO SYSTEM TIME (3I6,3X,D19.12; -TauC)                 (Table A10)
  v2 SBAS  D-UTC A0,A1,T,W,S,U (2D19.12,I7,I5,X,A5,X,I2), 2.10 CORR TO SYSTEM TIME (W0)  (A15)
  v3       IONOSPHERIC CORR (A4,1X,4D12.4,1X,A1,1X,I2),
           TIME SYSTEM CORR (A4,1X,D17.10,D16.9,1X,I6,1X,I4,1X,A5,1X,I2)  (rinex305.txt Table A5)
           GPGA was renamed GAGP in 3.04 (same value and sign, Table A5 note).
  v4       '> ION' and '> STO' records (rinex_4.02.txt Tables A33-A37); EOP has no v3 form.
Precision changes are reported as losses; reference/transmission times that a
target needs but the source does not hold are reported as assumptions.
"""

import datetime
import re
from decimal import Decimal, ROUND_HALF_EVEN
from types import SimpleNamespace

from rinexcore.errors import CorruptError
from rinexcore.header import HeaderRecord
from rinexcore.nav import NavRecord, fmt_token, token_value

GPS0 = datetime.datetime(1980, 1, 6)
BDS0 = datetime.datetime(2006, 1, 1)
UTC_IDS = {1: "UTC(NIST)", 2: "UTC(USNO)", 3: "UTC(SU)", 4: "UTC(BIPM)", 5: "UTC(Europe Lab)",
           6: "UTC(NICT)", 7: "UTC(NTSC)"}
UTC_IDS_REV = {v: k for k, v in UTC_IDS.items()}
UTC_IDS_REV.update({"UTC(CRL)": 6, "UTCGAL": 5})
def _sat_or_provider(field):
    """(satellite, SBAS provider) of the 1X,A5,1X field of a 2.11 D-UTC or RINEX 3 TIME SYSTEM
    CORR record: a satellite id ('G10', or 'Snn' for the SBAS satellite broadcasting MT12)
    or a provider name 'derived from MT17' (EGNOS, WAAS, MSAS ...) (rinex211.txt Table A15,
    rinex305.txt Table A5). RINEX 4 keeps them in separate fields (rinex_4.02.txt Table A33),
    so which one it is decides where it goes (Sol round 15: EGNOS was written as no provider,
    S27 as a provider)."""
    f = field.strip()
    return (f, "") if re.fullmatch(r"[A-Z]\d\d", f) else ("", f)


def _tswu(t):
    """A time correction written as RINEX 2 CORR TO SYSTEM TIME (GLONASS g file, 2.10 GEO h
    file) keeps the reference date and a0 only (rinex211.txt Table A10 l.1689, Table A15
    l.1908): a reference time T, a satellite or SBAS id and a UTC identifier go. T and W are
    zero for GLONASS (rinex305.txt Table A5); a RINEX 4 STO record always names the
    broadcasting satellite (Sol round 13 audit: the satellite and RINEX 4 UTC ID strings
    went unclaimed, and nothing was claimed for GLONASS)."""
    return bool(t["T"] or t["sat"] or t["sbas"] or t["utc"])


V2_LABELS = {"ION ALPHA", "ION BETA", "DELTA-UTC: A0,A1,T,W", "CORR TO SYSTEM TIME", "D-UTC A0,A1,T,W,S,U"}
V3_LABELS = {"IONOSPHERIC CORR", "TIME SYSTEM CORR"}
IONO_V3 = {("KLOB", "G"): ("GPSA", "GPSB"), ("KLOB", "J"): ("QZSA", "QZSB"),
           ("KLOB", "C"): ("BDSA", "BDSB"), ("KLOB", "I"): ("IRNA", "IRNB")}
IONO_V3_REV = {}
for (_m, _s), (_a, _b) in IONO_V3.items():
    IONO_V3_REV[_a] = (_s, 0)
    IONO_V3_REV[_b] = (_s, 1)
V3_TIME_CODES = {"GPUT", "GLUT", "GAUT", "BDUT", "QZUT", "IRUT", "SBUT", "GLGP", "GAGP", "QZGP",
                 "IRGP", "GPGA"}
CODE_SYS = {"GP": "G", "GL": "R", "GA": "E", "BD": "C", "QZ": "J", "IR": "I", "SB": "S"}
STO_MSG = {"G": "LNAV", "R": "FDMA", "E": "IFNV", "C": "D1D2", "J": "LNAV", "I": "LNAV", "S": "SBAS"}
ION_MSG = {"G": "LNAV", "J": "LNAV", "C": "D1D2", "I": "LNAV", "E": "IFNV"}


def fmt_d(tok, width, decimals, letter="D"):
    """(Fortran Dw.d text, exact?) of a numeric token, mantissa in [0.1, 1)."""
    v = token_value(tok)
    if v is None:
        return " " * width, True
    if v == 0:
        s = "0." + "0" * decimals + letter + "+00"
        return s.rjust(width), True
    e = v.adjusted() + 1
    m = abs(v).scaleb(-e).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)
    if m >= 1:
        m = m.scaleb(-1).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)
        e += 1
    digits = f"{m:.{decimals}f}"[2:]
    sign = "-" if v < 0 else ""
    s = f"{sign}0.{digits}{letter}{'+' if e >= 0 else '-'}{abs(e):02d}"
    if len(s) > width:
        s = s.replace("0.", ".", 1)
    exact = Decimal(f"{sign}0.{digits}E{e}") == v
    return s.rjust(width), exact


def _ival(s):
    t = s.strip()
    return int(t) if t.lstrip("-").isdecimal() else None


def _week_sow(t, epoch):
    dt = datetime.datetime(t[0], t[1], t[2], t[3], t[4]) + datetime.timedelta(seconds=int(t[5]))
    d = dt - epoch
    secs = d.days * 86400 + d.seconds
    return secs // 604800, secs % 604800


def _from_week(w, sow, epoch):
    dt = epoch + datetime.timedelta(weeks=w, seconds=sow)
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, Decimal(dt.second))


def _tok(s):
    return s.strip()


_NUMRE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[DdEe][+-]?\d+)?|[+-]?\d+")
_FLOAT_OK = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][+-]?\d+)?$")


def _ok(*toks):
    return all(not t or _FLOAT_OK.match(t) for t in toks)


def _timecorr_fallback(x):
    """TIME SYSTEM CORR written off its columns (e.g. cnvtToRINEX 3.09: values from col 9):
    read code, a0, a1, T, W by pattern, then the satellite and UTC id if present."""
    code = x[0:4].strip()
    rest = x[4:60]
    nums = []
    pos = 0
    for m in _NUMRE.finditer(rest):
        nums.append(m.group(0))
        pos = m.end()
        if len(nums) == 4:
            break
    if len(nums) == 2 and not rest[pos:].strip():
        return code, nums[0], nums[1], None, None, "", None     # a0, a1 only (T, W unknown)
    if len(nums) < 4:
        return None
    tail = rest[pos:].split()
    sat = next((t for t in tail if re.fullmatch(r"[A-Z]\d\d|[A-Z]{4,5}", t)), "")
    utc = next((int(t) for t in tail if t.isdecimal()), None)
    try:
        return code, nums[0], nums[1], int(nums[2]), int(nums[3]), sat, utc
    except ValueError:
        return None


class Corrections:
    def __init__(self):
        self.iono = []
        self.time = []
        self.eop = []
        self.first_eph = {}
        self.repairs = []
        self.source_version = {}
        self.used_all = set()

    # ------------------------------------------------------------------ read
    @classmethod
    def from_sources(cls, sources, report):
        c = cls()
        for i, f in enumerate(sources):
            n_ion, n_time = len(c.iono), len(c.time)
            c._read_source(f)
            # which input each value came from (a --merge: _v3_header keeps one per type)
            for it in c.iono[n_ion:] + c.time[n_time:]:
                it["input"] = i
                it["version"] = f.version
        c._validate()
        for rule, msg, line in c.repairs:
            report.repair(rule, msg, line)
        return c

    def _read_source(self, f):
        for r in f.records:
            if r.kind == "EPH":
                s = r.system
                if s not in self.first_eph or r.time < self.first_eph[s]:
                    self.first_eph[s] = r.time
        if f.version < "3":
            self._read_v2(f)
            self._read_foreign(f, V3_LABELS)
        elif f.version < "4":
            self._read_v3(f)
            self._read_foreign(f, V2_LABELS)
        else:
            self._read_v4(f)
            self._read_foreign(f, V2_LABELS | V3_LABELS)

    def _validate(self):
        """Every correction value must be a number before anything formats it."""
        def line_of(it):
            r = it.get("rec")
            if isinstance(r, list):
                r = r[0] if r else None
            return getattr(r, "lineno", None)
        for it in self.iono:
            if not _ok(*it["p"]):
                raise CorruptError(f"bad ionospheric correction value in {it['p']}", line=line_of(it),
                                   rule="NAV.HDR.IONCORR")
        for t in self.time:
            if not _ok(t["a0"], t["a1"], t["a2"], t.get("ttm") or ""):
                raise CorruptError(f"bad time-system correction value in {t['code']}", line=line_of(t),
                                   rule="NAV.HDR.TIMECORR")

    def _read_v2(self, f):
        alpha = beta = None
        recs = []
        for r in f.header:
            x = r.content.ljust(60)
            if r.label == "ION ALPHA":
                alpha = [_tok(x[2 + 12 * k:14 + 12 * k]) for k in range(4)]
                recs.append(r)
            elif r.label == "ION BETA":
                beta = [_tok(x[2 + 12 * k:14 + 12 * k]) for k in range(4)]
                recs.append(r)
            elif r.label == "DELTA-UTC: A0,A1,T,W":
                self.time.append({"code": "GPUT", "a0": _tok(x[3:22]), "a1": _tok(x[22:41]), "a2": "",
                                  "T": _ival(x[41:50]), "W": _ival(x[50:59]), "sat": "", "utc": None,
                                  "sbas": "", "ref": None, "ttm": None, "rec": r, "origin": "v2"})
            elif r.label == "CORR TO SYSTEM TIME":
                y, mo, d = _ival(x[0:6]), _ival(x[6:12]), _ival(x[12:18])
                code = "GLUT" if f.ftype == "G" else "SBUT"
                ref = (y, mo, d, 0, 0, Decimal(0)) if y and mo and d else None
                self.time.append({"code": code, "a0": _tok(x[21:40]), "a1": "", "a2": "",
                                  "T": None, "W": None, "sat": "", "utc": None, "sbas": "",
                                  "ref": ref, "ttm": None, "rec": r, "origin": "v2"})
            elif r.label == "D-UTC A0,A1,T,W,S,U":
                sat, sbas = _sat_or_provider(x[51:56])
                self.time.append({"code": "SBUT", "a0": _tok(x[0:19]), "a1": _tok(x[19:38]), "a2": "",
                                  "T": _ival(x[38:45]), "W": _ival(x[45:50]), "sat": sat,
                                  "utc": _ival(x[57:59]), "sbas": sbas, "ref": None,
                                  "ttm": None, "rec": r, "origin": "v2"})
        if alpha or beta:
            self.iono.append({"model": "KLOB", "sys": "G", "p": (alpha or [""] * 4) + (beta or [""] * 4),
                              "tmark": "", "svid": "", "rec": recs, "origin": "v2"})

    def _read_v3(self, f):
        pending = {}
        for r in f.header:
            x = r.content.ljust(60)
            if r.label == "IONOSPHERIC CORR":
                typ = x[0:4].strip()
                p = [_tok(x[5 + 12 * k:17 + 12 * k]) for k in range(4)]
                if not _ok(*p):
                    nums = _NUMRE.findall(x[4:60])
                    if len(nums) < 3:
                        raise CorruptError(f"unreadable IONOSPHERIC CORR {x.rstrip()!r}",
                                           line=r.lineno, rule="NAV.HDR.IONCORR")
                    p = (nums + ["", "", "", ""])[:4]
                    self.repairs.append(("NAV.HDR.IONCORR.LAYOUT",
                                         "IONOSPHERIC CORR values off their columns, read by pattern",
                                         r.lineno))
                tmark = x[54:55].strip()
                svid = x[56:58].strip()
                if typ == "GAL":
                    self.iono.append({"model": "NEQG", "sys": "E", "p": p, "tmark": tmark, "svid": svid,
                                      "rec": [r], "origin": "v3", "version": f.version})
                elif typ in IONO_V3_REV:
                    s, half = IONO_V3_REV[typ]
                    # the SV ID is I2: '01' and ' 1' are one satellite (Sol round 27: alpha and
                    # beta read as two half sets)
                    key = (s, tmark, svid.lstrip("0") or svid)
                    item = pending.get(key)
                    if item is None or item["p"][4 * half] != "":
                        item = {"model": "KLOB", "sys": s, "p": [""] * 8, "tmark": tmark, "svid": svid,
                                "rec": [], "origin": "v3", "have": [False, False]}
                        pending[key] = item
                        self.iono.append(item)
                    item["p"][4 * half:4 * half + 4] = p
                    item["have"][half] = True
                    item["rec"].append(r)
                else:
                    self.iono.append({"model": "V3:" + typ, "sys": "?", "p": p, "tmark": tmark,
                                      "svid": svid, "rec": [r], "origin": "v3"})
            elif r.label == "TIME SYSTEM CORR":
                self._time_v3(r, f.version)

    def _time_v3(self, r, version, relabelled=False):
        """A TIME SYSTEM CORR record (A4,1X,D17.10,D16.9,1X,I6,1X,I4,1X,A5,1X,I2: rinex305.txt
        Table A5), read by pattern when its values are off their columns."""
        x = r.content.ljust(60)
        item = {"code": x[0:4].strip(), "a0": _tok(x[5:22]), "a1": _tok(x[22:38]),
                "a2": "", "T": _ival(x[38:45]), "W": _ival(x[45:50]),
                "sat": x[51:56].strip(), "utc": _ival(x[57:59]), "sbas": "",
                "ref": None, "ttm": None, "rec": r, "origin": "v3-repaired" if relabelled else "v3"}
        if not _ok(item["a0"], item["a1"]) or item["T"] is None and x[38:45].strip():
            fb = _timecorr_fallback(x)
            if fb is None:
                raise CorruptError(f"unreadable TIME SYSTEM CORR {x.rstrip()!r}", line=r.lineno,
                                   rule="NAV.HDR.TIMECORR")
            code, a0, a1, T, W, sat, utc = fb
            item.update(code=code, a0=a0, a1=a1, T=T, W=W, sat=sat, utc=utc, origin="v3-repaired")
            self.repairs.append(("NAV.HDR.TIMECORR.LAYOUT",
                                 "TIME SYSTEM CORR values off their columns, read by pattern"
                                 + ("; no T and W given: written 0 0, meaning unknown" if T is None else ""),
                                 r.lineno))
        item["sat"], item["sbas"] = _sat_or_provider(item["sat"])
        if item["origin"] == "v3-repaired":
            self.source_version[id(item)] = version    # same version: carried as written
        self.time.append(item)

    def _read_foreign(self, f, labels):
        """Correction records under a label the file's version does not define, e.g. a
        RINEX 3.02 SBUT TIME SYSTEM CORR written under the RINEX 2 label CORR TO SYSTEM TIME
        (cnvtToRINEX 3.09, corpus BOR100POL_..._SN). The header writer consumes every
        correction label, so these were dropped unreported (Sonnet round 15). Each is read by
        its own label's layout, a CORR TO SYSTEM TIME whose first four columns are a
        time-system code (rinex305.txt Table A5) as TIME SYSTEM CORR, and reported as a
        repair; a same-version conversion carries it as written."""
        v2, v3 = [], []
        n_iono, n_time = len(self.iono), len(self.time)
        for r in f.header:
            if r.label not in labels:
                continue
            if r.label == "CORR TO SYSTEM TIME" and re.fullmatch(r"[A-Z]{4}", r.content[:4]):
                self._time_v3(r, f.version, relabelled=True)
                what = "TIME SYSTEM CORR content under the RINEX 2 label CORR TO SYSTEM TIME; read as TIME SYSTEM CORR"
            else:
                (v3 if r.label in V3_LABELS else v2).append(r)
                what = f"{r.label} is not a RINEX {f.version} label; read by its own layout"
            self.repairs.append(("NAV.HDR.FOREIGN-LABEL", what, r.lineno))
        if v3:
            self._read_v3(SimpleNamespace(header=v3, version=f.version))
        if v2:
            ftype = {"R": "G", "S": "H"}.get(f.system.strip(), f.ftype if f.version < "3" else "N")
            self._read_v2(SimpleNamespace(header=v2, version=f.version, ftype=ftype))
        for it in self.iono[n_iono:] + self.time[n_time:]:
            it["foreign"] = True
            self.source_version[id(it)] = f.version

    def _as_written(self, it, tv):
        """A correction read from under a foreign label is carried as written to its own
        file's version (that conversion changes nothing), and converted elsewhere."""
        return bool(it.get("foreign")) and tv == self.source_version.get(id(it))

    def _read_v4(self, f):
        for r in f.records:
            if r.kind == "STO":
                ex = (" " * 23 + r.extra).ljust(80)    # extra = line 0 from column 24
                code = ex[24:42].strip()
                sbas = ex[43:61].strip()
                utc = ex[62:80].strip()
                self.time.append({"code": code, "a0": r.vals[4] if len(r.vals) > 4 else "",
                                  "a1": r.vals[5] if len(r.vals) > 5 else "",
                                  "a2": r.vals[6] if len(r.vals) > 6 else "",
                                  "T": None, "W": None, "sat": r.sat.strip() if r.sat[1:].strip() else "",
                                  "utc": utc, "sbas": sbas, "ref": r.time,
                                  "ttm": r.vals[3] if len(r.vals) > 3 else "", "rec": r, "origin": "v4"})
            elif r.kind == "ION":
                s = r.system
                v = r.vals
                if (r.msg in ("LNAV", "D1D2") and s in "GJCI") or (r.msg == "CNVX" and s in "GJ"):
                    model = "KLOB"
                    p = (v + [""] * 11)[:3] + (v + [""] * 11)[3:7] + (v + [""] * 11)[7:8]
                elif r.msg == "IFNV" and s == "E":
                    model = "NEQG"
                    p = (v + [""] * 4)[:4]
                else:
                    model = f"V4:{s}:{r.msg}:{r.sub}"
                    p = list(v)
                self.iono.append({"model": model, "sys": s, "p": p, "tmark": "",
                                  "svid": r.sat[1:].strip(), "rec": r, "origin": "v4",
                                  "msg": r.msg, "sub": r.sub, "ttm": r.time})
            elif r.kind == "EOP":
                self.eop.append(r)

    # ----------------------------------------------------------------- write
    def header_records(self, tv, v2sys, report):
        if tv >= "4":
            return []
        if tv < "3":
            return self._v2_header(tv, v2sys, report)
        return self._v3_header(tv, report)

    def _lose_unused(self, used, report, why="nav-correction-not-representable"):
        # a value of a kind the target can hold, but only once (one header record per type):
        # "nav-correction-extra"; a kind the target cannot hold at all: "...not-representable"
        used_ion = {(it["model"], it["sys"]) for it in self.iono if id(it) in used}
        used_sto = {it["code"] for it in self.time if id(it) in used}
        for it in self.iono:
            if id(it) not in used:
                kind = "nav-correction-extra" if (it["model"], it["sys"]) in used_ion else why
                report.loss(f"{kind}:ION:{it['model']}:{it['sys']}", 1)
        for it in self.time:
            if id(it) not in used:
                kind = "nav-correction-extra" if it["code"] in used_sto else why
                report.loss(f"{kind}:STO:{it['code']}", 1)
        if self.eop:
            report.loss(f"{why}:EOP", len(self.eop))

    def _v2_header(self, tv, v2sys, report):
        out = []
        used = set()
        if v2sys == "G":
            k = next((i for i in self.iono if i["model"] == "KLOB" and i["sys"] == "G"), None)
            if k is not None and (k["origin"] == "v2" or self._as_written(k, tv)):
                used.add(id(k))
                out.extend(k["rec"])
            elif k is not None:
                used.add(id(k))
                for lab, half in (("ION ALPHA", 0), ("ION BETA", 1)):
                    vals = k["p"][4 * half:4 * half + 4]
                    if any(vals):
                        txt = "  " + "".join(self._d(v, 12, 4, "D", report, lab) for v in vals)
                        out.append(HeaderRecord(lab, txt))
                self._ion_meta(k, tv, report)
            t = self._pick("GPUT", report, used)
            if t is not None and (t["origin"] == "v2" or self._as_written(t, tv)):
                out.append(t["rec"])
            elif t is not None:
                T, W = self._tw(t, report)
                txt = ("   " + self._d(t["a0"], 19, 12, "D", report, "DELTA-UTC")
                       + self._d(t["a1"], 19, 12, "D", report, "DELTA-UTC")
                       + f"{T if T is not None else 0:9d}{W if W is not None else 0:9d}")
                # A0,A1,T,W only (rinex211.txt Table A3): the broadcasting satellite goes; GPS
                # UTC is UTC(USNO), so only another UTC id would be lost
                if t["sat"]:
                    report.loss(f"header-field-not-representable:STO-SAT:{t['code']}", 1)
                if t["utc"] not in (None, "", 0, 2, "UTC(USNO)"):
                    report.loss(f"header-field-not-representable:DELTA-UTC:UTC-ID:{t['utc']}", 1)
                self._v4_fields(t, report)
                out.append(HeaderRecord("DELTA-UTC: A0,A1,T,W", txt))
        elif v2sys == "R":
            t = self._pick("GLUT", report, used)
            if t is not None and (t["origin"] == "v2" or self._as_written(t, tv)):
                out.append(t["rec"])
            elif t is not None:
                ref = self._ref(t, "R", report)
                txt = (f"{ref[0]:6d}{ref[1]:6d}{ref[2]:6d}   "
                       + self._d(t["a0"], 19, 12, "D", report, "CORR TO SYSTEM TIME"))
                if t["a1"] and token_value(t["a1"]) != 0:
                    report.loss("header-field-not-representable:CORR TO SYSTEM TIME:a1", 1)
                if _tswu(t):
                    report.loss("header-field-not-representable:CORR TO SYSTEM TIME:T-W-S-U", 1)
                self._v4_fields(t, report)
                out.append(HeaderRecord("CORR TO SYSTEM TIME", txt))
        elif v2sys == "S":
            t = self._pick("SBUT", report, used)
            want = "D-UTC A0,A1,T,W,S,U" if tv >= "2.11" else "CORR TO SYSTEM TIME"
            if t is not None and (t["origin"] == "v2" and t["rec"].label == want or self._as_written(t, tv)):
                out.append(t["rec"])
            elif t is not None:
                if tv >= "2.11":
                    T, W = self._tw(t, report)
                    utc = self._utc(t, 6, "D-UTC", report)     # 2.11: '>6 = reserved' (Table A15)
                    sb = self._ident(t, report)
                    txt = (self._d(t["a0"], 19, 12, "D", report, "D-UTC")
                           + self._d(t["a1"], 19, 12, "D", report, "D-UTC")
                           + f"{T or 0:7d}{W or 0:5d} {sb:5s} {utc or 0:2d}")
                    out.append(HeaderRecord("D-UTC A0,A1,T,W,S,U", txt))
                else:
                    # 2.10 GEO CORR TO SYSTEM TIME holds the date and W0 only (rinex211.txt Table A15)
                    ref = self._ref(t, "S", report)
                    txt = (f"{ref[0]:6d}{ref[1]:6d}{ref[2]:6d}   "
                           + self._d(t["a0"], 19, 12, "D", report, "CORR TO SYSTEM TIME"))
                    if t["a1"] and token_value(t["a1"]) != 0:
                        report.loss("header-field-not-representable:CORR TO SYSTEM TIME:a1", 1)
                    if _tswu(t):
                        report.loss("header-field-not-representable:CORR TO SYSTEM TIME:T-W-S-U", 1)
                    out.append(HeaderRecord("CORR TO SYSTEM TIME", txt))
                self._v4_fields(t, report)
        self.used_all |= used          # losses are counted once over all split outputs
        return out

    def lose_unused_all(self, report):
        self._lose_unused(self.used_all, report)

    def _v3_header(self, tv, report):
        out = []
        used = set()
        # ionosphere
        seen_models = set()
        # a --merge: a RINEX 3 header holds one set per type (rinex305.txt Table A5; BDS may
        # repeat it per time mark and SV), so a type another input already gave is left out,
        # claimed nav-correction-extra by _lose_unused (round 24: one input's GPSA and the
        # other's GPSB were written as one Klobuchar set, two GPUT records); RINEX 4 targets
        # keep every input's as its own ION/STO record
        given = {}

        def other_input(key, it):
            first = given.setdefault(key, it.get("input", 0))
            return first != it.get("input", 0)

        def slot(it):
            # the header's place for a set: one per type before 3.02; from 3.02 one per type,
            # time mark and SV, which BDS must give and the others may (rinex305.txt Table A5
            # p.64-66, Note 1: several IONOSPHERIC CORR records). Sol rounds 25, 26: a RINEX 4
            # file's C11 hour-00 and C12 hour-01 sets, then G11/G12, kept only the first
            if tv >= "3.02":
                return (it["model"], it["sys"], self._marks(it, tv))
            return (it["model"], it["sys"])
        for it in self.iono:
            # (a header set of another version too: 3.05 sets marked A/01 and B/02 became two
            # unmarked GPSA/GPSB pairs in 3.01, which has one place per type; the file's own
            # version carries what it has)
            if slot(it) in seen_models and (it["origin"] == "v4" or it.get("version") != tv):
                continue
            if other_input(slot(it) + (it.get("tmark") or "", it.get("svid") or ""), it):
                continue
            if it["model"] == "NEQG":
                if it["origin"] == "v3" or self._as_written(it, tv):
                    out.extend(self._carry_iono(it, tv, report))
                else:
                    p = it["p"]
                    # fourth slot: "zero" in 3.00-3.02 (rinex302.txt l.3289), "Blank" from 3.03
                    # (rinex305.txt l.3641)
                    txt = "GAL  " + "".join(self._d(v, 12, 4, "D", report, "IONOSPHERIC CORR")
                                            for v in p[:3]) + (fmt_d("0", 12, 4, "D")[0] if tv < "3.03" else " " * 12)
                    if len(p) > 3 and p[3] and token_value(p[3]) != 0:
                        report.loss("header-field-not-representable:IONOSPHERIC CORR:GAL-flags", 1)
                    out.append(HeaderRecord("IONOSPHERIC CORR", txt + self._marks(it, tv)))
                    self._ion_meta(it, tv, report)
                    report.rule("NAV.V4V3.ION-TO-HEADER")
                used.add(id(it))
                seen_models.add(slot(it))
            elif (it["model"], it["sys"]) in IONO_V3:
                if it["sys"] == "I" and tv < "3.03" or it["sys"] == "C" and tv < "3.02" \
                        or it["sys"] == "J" and tv < "3.01":
                    continue
                a, b = IONO_V3[(it["model"], it["sys"])]
                if it["origin"] == "v3" or self._as_written(it, tv):
                    out.extend(self._carry_iono(it, tv, report))
                else:
                    p = it["p"]
                    for lab, half in ((a, 0), (b, 1)):
                        vals = p[4 * half:4 * half + 4]
                        if not any(vals):
                            continue
                        txt = f"{lab} " + "".join(self._d(v, 12, 4, "D", report, "IONOSPHERIC CORR")
                                                  for v in vals)
                        out.append(HeaderRecord("IONOSPHERIC CORR", txt + self._marks(it, tv)))
                    self._ion_meta(it, tv, report)
                    if it["origin"] == "v4":
                        report.rule("NAV.V4V3.ION-TO-HEADER")
                        if it.get("sub"):
                            # the 4.02 area (QZSS CNVX WIDE/JAPN, rinex_4.02.txt Table 25 p.40)
                            # has no RINEX 3 field: the values are kept, the subtype is not
                            report.loss(f"nav-subtype-not-representable:ION:{it['sys']}:{it['msg']}", 1)
                    else:
                        report.rule("NAV.V2V3.ION")
                used.add(id(it))
                seen_models.add(slot(it))
            elif it["origin"] == "v3":
                out.extend(self._carry_iono(it, tv, report))
                used.add(id(it))
        # time systems
        seen_codes = set()
        for t in self.time:
            code = t["code"]
            if code == "GPGA" and tv >= "3.04":
                code = "GAGP"
            elif code == "GAGP" and tv < "3.04":
                code = "GPGA"
            if code not in V3_TIME_CODES:
                if t["origin"] == "v3":
                    out.append(t["rec"])          # non-standard in the source: carried as is
                    used.add(id(t))
                    report.rule("NAV.HDR.NONSTANDARD-CARRIED")
                continue
            if t["origin"] == "v4" and code in seen_codes:
                continue
            if other_input(("STO", code), t):
                continue
            sysc = CODE_SYS.get(code[:2], "")
            if sysc == "I" and tv < "3.03" or sysc == "C" and tv < "3.02" or sysc == "J" and tv < "3.01":
                continue
            seen_codes.add(code)
            used.add(id(t))
            if t["origin"] == "v3" and code == t["code"]:
                out.append(t["rec"])
                continue
            if (t["origin"] == "v3-repaired" or t.get("foreign")) and tv == self.source_version.get(id(t)):
                # same version: the off-column record is carried as written (reformatting
                # it would round the values)
                out.append(t["rec"])
                report.warn("NAV.HDR.TIMECORR.LAYOUT", "TIME SYSTEM CORR off its columns, carried as is")
                continue
            if t["origin"] == "v3" and code != t["code"]:
                out.append(HeaderRecord("TIME SYSTEM CORR", code + t["rec"].content[4:]))
                report.rule("NAV.V3V3.GPGA-GAGP")
                continue
            T, W = self._tw(t, report)
            utc = self._utc(t, 7, "TIME SYSTEM CORR", report)   # 3.05: '>7 = not assigned yet'
            sat = self._ident(t, report)
            txt = (f"{code} " + self._d(t["a0"], 17, 10, "D", report, "TIME SYSTEM CORR")
                   + self._d(t["a1"], 16, 9, "D", report, "TIME SYSTEM CORR")
                   + f" {T if T is not None else 0:6d} {W if W is not None else 0:4d} {sat:5s} {utc or 0:2d}")
            self._v4_fields(t, report)
            out.append(HeaderRecord("TIME SYSTEM CORR", txt))
            report.rule("NAV.V4V3.STO-TO-HEADER" if t["origin"] == "v4" else "NAV.V2V3.TIMECORR")
        self._lose_unused(used, report)
        return out

    def _marks(self, it, tv):
        """The 1X,A1 time mark (hour of the transmission time, A-X) and 1X,I2 SV ID of a
        RINEX 3.02+ IONOSPHERIC CORR record (rinex305.txt Table A5 p.64-65: mandatory for BDS,
        optional for the others). A RINEX 4 ION record's transmission epoch gives the mark for
        every system (Sol round 15: only BDS got one)."""
        if tv < "3.02":
            return ""
        tm = it.get("tmark") or ""
        sv = it.get("svid") or ""
        if not tm and it.get("ttm") is not None:
            tm = chr(ord("A") + it["ttm"][3])
        return f" {tm:1s} {sv:>2s}".rstrip() if (tm or sv) else ""

    def _ion_meta(self, it, tv, report):
        """Claims for what a RINEX 2/3 header keeps of an ionospheric record's transmission
        time and satellite. RINEX 4 ION records carry the transmission epoch and satellite
        (rinex_4.02.txt Table A35); 3.02+ IONOSPHERIC CORR keeps the hour (time mark) and the
        PRN (SV ID), 3.00/3.01 and RINEX 2 ION ALPHA/BETA neither (Sol round 15)."""
        s = it["sys"]
        marks = tv >= "3.02" and tv < "4"
        if it["origin"] == "v4":
            report.loss(f"header-field-not-representable:ION-TTM:{s}", 1)   # the date, minutes, seconds
            if it.get("svid") and not marks:
                report.loss(f"header-field-not-representable:ION-SAT:{s}", 1)
        elif it["origin"] == "v3" and not marks:
            if it.get("tmark"):
                report.loss(f"header-field-not-representable:ION-TTM:{s}", 1)
            if it.get("svid"):
                report.loss(f"header-field-not-representable:ION-SAT:{s}", 1)

    def _carry_iono(self, it, tv, report):
        """A RINEX 3 IONOSPHERIC CORR set as written; to 3.00/3.01, which have no time mark
        or SV ID columns, without them (claimed)."""
        if tv < "3.02" and (it.get("tmark") or it.get("svid")) and not self._as_written(it, tv):
            self._ion_meta(it, tv, report)
            return [HeaderRecord(r.label, r.content[:53], r.lineno) for r in it["rec"]]
        return list(it["rec"])

    def to_v4_records(self, tv, eph, report):
        """ION/STO records from RINEX 2/3 header corrections (v4 records pass through)."""
        out = []
        for it in self.iono:
            if it["origin"] == "v4":
                continue
            s = it["sys"]
            if it["model"] == "KLOB" and s in ION_MSG:
                p = (it["p"] + [""] * 8)[:8]
                if not all(p):
                    # a RINEX 4 Klobuchar record needs all eight coefficients (rinex_4.02.txt
                    # Table A35); a source with only alpha or only beta cannot fill one
                    report.loss(f"nav-correction-not-representable:ION:KLOB-incomplete:{s}", 1)
                    continue
                vals = p[0:3] + p[3:7] + [p[7]]
            elif it["model"] == "NEQG":
                p = (it["p"] + [""] * 4)[:4]
                # the fourth GAL parameter is "zero" in 3.00-3.02 (rinex302.txt l.3289), a
                # placeholder and not disturbance flags, and "Blank" from 3.03 (rinex305.txt
                # l.3641): either way the flags are unknown (Sol round 16: a 3.0x zero became
                # flags 0 without the assumption a blank gets)
                placeholder = it.get("version", "3.05") < "3.03" and not (p[3] and token_value(p[3]) != 0)
                flags = "" if placeholder else p[3]
                vals = p[0:3] + [flags if flags and token_value(flags) != 0 else "0.000000000000E+00"]
                if not flags:
                    report.assume("ion-galileo-disturbance-flags", "0",
                                  "default:zero-placeholder-in-v3.00-3.02" if placeholder else "default:blank-in-v3")
            else:
                report.loss(f"nav-correction-not-representable:ION:{it['model']}", 1)
                continue
            ttm = self._ttm_assumed(it, s, report)
            sv = it.get("svid") or ""
            sat = f"{s}{int(sv):02d}" if sv.isdecimal() else f"{s}  "
            out.append(NavRecord("ION", sat, ION_MSG[s], "", ttm, vals, "", None, 0))
            report.rule("NAV.V3V4.HEADER-ION-TO-RECORD")
        for t in self.time:
            if t["origin"] == "v4":
                continue
            code = "GAGP" if t["code"] == "GPGA" else t["code"]
            s = CODE_SYS.get(code[:2])
            if s is None:
                report.loss(f"nav-correction-not-representable:STO:{code}", 1)
                continue
            ref = self._ref(t, s, report)
            T, W = self._tw(t, report)
            ttm = f"{Decimal(T):.12E}" if T is not None else ""
            report.assume("sto-transmission-time", f"{code}:t_tm=T", "assumed:reference-time")
            utc = t["utc"]
            utcs = UTC_IDS.get(utc, "") if isinstance(utc, int) and code.endswith("UT") else ""
            if code == "GAUT" and utc == 5:
                utcs = "UTCGAL"          # Galileo's UTC realisation in the 4.02 list (Table A33)
            if utcs:
                report.assume("sto-utc-id", f"{code}:{utc}->{utcs}", "table:rinex305-A5")
            sbas = t["sbas"] if code == "SBUT" else ""
            if t["sbas"] and not sbas:
                report.loss(f"header-field-not-representable:SBAS-ID:{t['sbas']}", 1)
            sat = t["sat"]
            if len(sat) == 3 and sat[1:].isdecimal() and sat[0] != s:
                # the satellite must belong to the system of the offset code (e.g. 'B10' for
                # BDUT in the 3.05 Table A9 example is a BeiDou satellite, 'C10')
                report.repair("NAV.STO.SATELLITE", f"{code} satellite {sat} written as {s}{sat[1:]}")
                sat = s + sat[1:]
            satid = sat if len(sat) == 3 and sat[1:].isdecimal() else f"{s}  "
            extra = f" {code:18s} {sbas:18s} {utcs:18s}".rstrip()
            vals = ["", "", "", ttm, t["a0"], t["a1"], t["a2"] or "0.000000000000E+00"]
            out.append(NavRecord("STO", satid, STO_MSG[s], "", ref, vals, extra, None, 0))
            report.rule("NAV.V3V4.HEADER-STO-TO-RECORD")
        return out

    # ----------------------------------------------------------- helpers
    def _d(self, tok, w, d, letter, report, what):
        txt, exact = fmt_d(tok, w, d, letter)
        if not exact:
            report.loss(f"nav-correction-precision:{what}", 1)
        return txt

    def _v4_fields(self, t, report):
        """Fields of a RINEX 4 STO record no RINEX 2/3 header record has (rinex_4.02.txt Table
        A33): A2, and the transmission time t_tm (Sol round 14: it went unclaimed)."""
        if t.get("a2") and token_value(t["a2"]) != 0:
            report.loss(f"header-field-not-representable:STO-A2:{t['code']}", 1)
        if t["origin"] == "v4" and str(t.get("ttm") or "").strip():
            report.loss(f"header-field-not-representable:STO-TTM:{t['code']}", 1)

    @staticmethod
    def _ident(t, report):
        """The 1X,A5,1X field of a 2.11 D-UTC or RINEX 3 TIME SYSTEM CORR record: the SBAS
        provider (EGNOS, WAAS, MSAS ..., 'derived from MT17') when there is one that fits five
        columns, else the broadcasting satellite ('Snn', the MT12 satellite) (rinex211.txt
        Table A15, rinex305.txt Table A5). What has no room is claimed (Sol round 14: A-SBAS
        ran into the UTC identifier's columns)."""
        prov, sat = t["sbas"] or "", t["sat"] or ""
        field = prov if prov and len(prov) <= 5 else (sat if len(sat) <= 5 else "")
        if prov and prov != field:
            report.loss(f"header-field-not-representable:SBAS-ID:{prov}", 1)
        if sat and sat != field:
            report.loss(f"header-field-not-representable:STO-SAT:{t['code']}", 1)
        return field

    @staticmethod
    def _utc(t, top, label, report):
        """The I2 UTC identifier of a 2.11 D-UTC (1-6) or RINEX 3 TIME SYSTEM CORR (1-7)
        record from a number or a RINEX 4 UTC ID (UTC_IDS_REV); one with no number in the
        target is written 0 ('unknown') and claimed."""
        u = t["utc"] if isinstance(t["utc"], int) else UTC_IDS_REV.get(t["utc"] or "", 0)
        if (t["utc"] and not u) or (u and u > top):
            report.loss(f"header-field-not-representable:{label}:UTC-ID:{t['utc']}", 1)
            return 0
        return u

    def _pick(self, code, report, used):
        cands = [t for t in self.time if t["code"] == code]
        if not cands:
            return None
        used.add(id(cands[0]))
        if len(cands) > 1:
            report.rule(f"NAV.CORR.CHOOSE-FIRST.{code}")
        return cands[0]

    def _tw(self, t, report):
        if t["T"] is not None and t["W"] is not None:
            return t["T"], t["W"]
        if t["ref"] is not None:
            epoch = BDS0 if t["code"].startswith("BD") else GPS0
            w, sow = _week_sow(t["ref"], epoch)
            if t["code"] in ("GLUT", "GLGP") and t["origin"] == "v2":
                report.assume("glonass-time-corr-week", f"{t['code']}:W/T from reference date",
                              "computed")
            return sow, w
        return 0, 0

    def _ref(self, t, s, report):
        if t["ref"] is not None:
            return t["ref"]
        if t["W"] or t["T"]:
            epoch = BDS0 if t["code"].startswith("BD") else GPS0
            return _from_week(t["W"] or 0, t["T"] or 0, epoch)
        fe = self.first_eph.get(s) or (min(self.first_eph.values()) if self.first_eph else None)
        if fe is None:
            report.assume("time-corr-reference", f"{t['code']}:unknown", "default:1980-01-06")
            return (1980, 1, 6, 0, 0, Decimal(0))
        report.assume("time-corr-reference", f"{t['code']}:first-ephemeris-day", "assumed")
        return (fe[0], fe[1], fe[2], 0, 0, Decimal(0))

    def _ttm_assumed(self, it, s, report):
        fe = self.first_eph.get(s) or (min(self.first_eph.values()) if self.first_eph else None)
        if fe is None:
            fe = (1980, 1, 6, 0, 0, Decimal(0))
        tm = it.get("tmark") or ""
        if tm and "A" <= tm <= "X":
            t = (fe[0], fe[1], fe[2], ord(tm) - ord("A"), 0, Decimal(0))
            report.assume("ion-transmission-time", f"{s}:time-mark-{tm}", "derived:time-mark")
            return t
        report.assume("ion-transmission-time", f"{s}:first-ephemeris-epoch", "assumed")
        return fe
