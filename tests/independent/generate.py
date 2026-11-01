"""Seeded random generator of valid RINEX observation files (round 22).

Each seed gives one file: a random version (2.10-4.02), systems and observation types taken
from the independent code tables (tests/independent/codes.py), and 3-10 epochs with flags
0, 1 and 6, events with flags 2-5 (comments, LEAP SECONDS, ANTENNA: PHASECENTER, SYS / PCVS
APPLIED, a GLONASS channel given late, WAVELENGTH FACT L1/2, new type lists), receiver clock
offsets, LLI bits 0-2, SSI, blank fields, RINEX 3.00/3.01 blank attributes and SYS / SCALE
FACTOR. tests/unit/test_generated.py converts each file to every version, plain and Compact
RINEX, and checks the result with the validator, compare_obs, the loss table, a decode of the
Compact RINEX and, when present, CRX2RNX.

The files are written from the specs' record formats (rinex211.txt Tables A1/A2,
rinex305.txt Tables A2/A3), not by our writer; a seed whose file our validator rejects is a
generator fault, reported as such.
"""

import random

from . import codes as C

VERSIONS = ["2.10", "2.11", "3.00", "3.01", "3.02", "3.03", "3.04", "3.05", "4.00", "4.01", "4.02"]
# the versions files are written in: also the read-only 2.00 and 2.01 (Sol round 23)
SOURCES = ["2.00", "2.01"] + VERSIONS
SYSTEMS = "GRECJSI"
NAMES = {"G": "G (GPS)", "R": "R (GLONASS)", "E": "E (GALILEO)", "C": "C (BEIDOU)", "J": "J (QZSS)",
         "S": "S (SBAS)", "I": "I (NavIC)", "M": "M (MIXED)"}
# GLONASS frequency channels used by the files and by the channel table given to the converter
FCN_OF = {f"R{p:02d}": ((p * 5) % 14) - 7 for p in range(1, 25)}
FCN_TABLE = "".join(f"{s} {k}\n" for s, k in FCN_OF.items())
# what the validator says about a file whose header counts are wrong on purpose: real
# files often have them wrong (CLAUDE.md "Real-file damage"); the converter repairs them
DAMAGE_RULES = {"VAL.HDR.NUM-SATELLITES", "VAL.HDR.PRN-NUM-OBS"}


def hdr(content, label):
    assert len(content) <= 60, content
    return content.ljust(60) + label


def _value(rng, code):
    t = code[0]
    if t == "C":
        return rng.uniform(1.9e7, 2.6e7)
    if t == "L":
        return rng.uniform(-3e7, 1.4e8)
    if t == "D":
        return rng.uniform(-4000, 4000)
    if t == "S":
        return rng.uniform(25, 52)
    return rng.uniform(0, 100)


class ObsGen:
    def __init__(self, seed):
        self.seed = seed
        self.rng = rng = random.Random(seed)
        self.v = v = rng.choice(SOURCES)
        avail = [s for s in SYSTEMS if s in C.source_systems(v)]
        k = rng.choice([1, 1, 2, 2, 3, 4])
        self.sys = sorted(rng.sample(avail, min(k, len(avail))), key=SYSTEMS.index)
        self.types = {}
        self.v2 = []
        if v < "3":
            self.v2 = self._v2_list()
        else:
            for s in self.sys:
                self.types[s] = self._v3_list(s)
        self.sats = {s: [f"{s}{p:02d}" for p in sorted(rng.sample(range(1, 25 if s != "S" else 40),
                                                                  rng.randint(2, 6)))]
                     for s in self.sys}
        self.clock = rng.random() < 0.3
        # 4.02 picosecond extension of the epoch second (1X,I5.5 after the clock field:
        # rinex_4.02.txt Table A3), on some data epochs after the first
        self.ps = v == "4.02" and rng.random() < 0.3
        self.scale = {}
        self.slot_late = None
        self.damaged = False          # wrong header counts written on purpose (DAMAGE_RULES)

    def _v2_list(self):
        pool = sorted({c for s in self.sys for c in C.source_codes(self.v, s)})
        return self.rng.sample(pool, self.rng.randint(1, min(12, len(pool))))

    def _v3_list(self, s):
        rng, v = self.rng, self.v
        pool = sorted(c for c in C.codes(v, s) if c[2:3].strip())
        out = rng.sample(pool, rng.randint(1, min(15, len(pool))))
        if C.blank_attribute_allowed(v) and rng.random() < 0.15:
            # 3.00/3.01 'unknown tracking mode' (rinex300.txt l.690)
            blank = out[0][:2] + " "
            if blank not in out and C.valid(v, s, blank):
                out.append(blank)
        return out

    # -- header ---------------------------------------------------------------------
    def header(self):
        v, rng = self.v, self.rng
        single = self.sys[0] if len(self.sys) == 1 else "M"
        h = [hdr(f"{v:>9}           OBSERVATION DATA    {NAMES[single]}", "RINEX VERSION / TYPE"),
             hdr("GENOBS 1.0          TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
             hdr("TEST", "MARKER NAME")]
        if v >= "3":
            h.append(hdr("GEODETIC", "MARKER TYPE"))
        h += [hdr("OBSERVER            AGENCY", "OBSERVER / AGENCY"),
              hdr("1                   TESTRCV             1.0", "REC # / TYPE / VERS"),
              hdr("1                   TESTANT         NONE", "ANT # / TYPE"),
              hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ"),
              hdr("        0.0000        0.0000        0.0000", "ANTENNA: DELTA H/E/N")]
        if v < "3":
            h.append(hdr("     1     1", "WAVELENGTH FACT L1/2"))
            h += self.v2_types(self.v2)
        else:
            h += self.v3_types(self.types)
            if rng.random() < 0.15:
                s = rng.choice(self.sys)
                f = rng.choice([10, 100, 1000])
                cs = self.types[s][:min(12, len(self.types[s]))]
                self.scale[s] = (f, set(cs))
                h.append(hdr(f"{s} {f:4d}  {len(cs):2d}" + "".join(f" {c}" for c in cs), "SYS / SCALE FACTOR"))
            if v >= "3.01":
                lab = "SYS / PHASE SHIFTS" if v == "3.01" else "SYS / PHASE SHIFT"
                n0 = len(h)
                for s in self.sys:
                    for c in self.types[s]:
                        if c[0] == "L":
                            h.append(hdr(f"{s} {c}  0.00000" if rng.random() < 0.7 else f"{s} {c}", lab))
                if len(h) == n0:
                    h.append(hdr(self.sys[0], lab))
            if "R" in self.sys and (v >= "3.02" or (v == "3.01" and rng.random() < 0.5)):
                sl = list(self.sats["R"])
                if rng.random() < 0.3 and len(sl) > 1:
                    self.slot_late = sl.pop()              # given later, in a flag-4 event
                h.append(hdr(f"{len(sl):3d} " + "".join(f"{x} {FCN_OF[x]:2d} " for x in sl),
                             "GLONASS SLOT / FRQ #"))
            if "R" in self.sys and v >= "3.02":
                h.append(hdr(" C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000", "GLONASS COD/PHS/BIS"))
            if rng.random() < 0.3:
                s = rng.choice(self.sys)
                h.append(hdr(f"{s} {self.types[s][0]}   0.1234        0.0000        0.0567", "ANTENNA: PHASECENTER"))
            if rng.random() < 0.3:
                h.append(hdr(f"{rng.choice(self.sys)} RTKLIB              https://example.org/dcb",
                             "SYS / DCBS APPLIED"))
        if self.clock:
            h.append(hdr("     0", "RCV CLOCK OFFS APPL"))
        if rng.random() < 0.5:
            h.append(hdr("    30.000", "INTERVAL"))
        if rng.random() < 0.4:
            line = "    18" if v < "3.01" or rng.random() < 0.5 else "    18    18  2185     7GPS"
            if "3.03" <= v < "4" and rng.random() < 0.4:
                # in BeiDou terms: 14 s fewer, BDS weeks from 2006 (GPS week 1356), days 0-6;
                # spelt BDS in 3.03/3.04, BDT in 3.05 (Sol round 24)
                line = "     4     4   829     6" + ("BDS" if v < "3.05" else "BDT")
            h.append(hdr(line[:24] if "3.01" <= v < "3.03" else line, "LEAP SECONDS"))
        h.append(hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"))
        h.append(hdr("", "END OF HEADER"))
        return h

    @staticmethod
    def v2_types(codes):
        out = []
        for k in range(0, max(1, len(codes)), 9):
            head = f"{len(codes):6d}" if k == 0 else " " * 6
            out.append(hdr(head + "".join(f"    {c}" for c in codes[k:k + 9]), "# / TYPES OF OBSERV"))
        return out

    def v3_types(self, types):
        out = []
        for s in self.sys:
            cs = types[s]
            for k in range(0, len(cs), 13):
                head = f"{s}  {len(cs):3d}" if k == 0 else " " * 6
                out.append(hdr(head + "".join(f" {c}" for c in cs[k:k + 13]), "SYS / # / OBS TYPES"))
        return out

    # -- data -------------------------------------------------------------------------
    def _clock(self):
        # F12.9 (RINEX 2) / F15.12 (RINEX 3/4); random digits (a negative value ending in
        # eight zeros is the CRX2RNX 4.2.0 clock quirk the encoder refuses: docs/HATANAKA.md)
        x = self.rng.uniform(-0.0009, 0.0009)
        return ("%12.9f" if self.v < "3" else "%15.12f") % x

    def epoch(self, sec, flag, sats_or_n, clock=False, ps=None):
        t = (sec // 60, sec % 60)
        if self.v >= "3":
            n = sats_or_n if isinstance(sats_or_n, int) else len(sats_or_n)
            line = "> 2026 10 01 00 %02d %10.7f  %d%3d" % (t[0], t[1], flag, n)
            if clock or ps is not None:
                line += " " * 6 + (self._clock() if clock else " " * 15)
            if ps is not None:
                line += " %05d" % ps
            return [line]
        if isinstance(sats_or_n, int):
            return [" 26 10  1  0 %2d %10.7f  %d%3d" % (t[0], t[1], flag, sats_or_n)]
        sats = sats_or_n
        first = " 26 10  1  0 %2d %10.7f  %d%3d" % (t[0], t[1], flag, len(sats)) + "".join(sats[:12])
        if clock:
            first = first.ljust(68) + self._clock()
        return [first] + [" " * 32 + "".join(sats[k:k + 12]) for k in range(12, len(sats), 12)]

    def field(self, code):
        rng = self.rng
        if rng.random() < 0.12:
            if rng.random() < 0.25:
                # a missing value with flags: no observation, but LLI/SSI the converter keeps
                # (Compact RINEX 1.0 cannot: flags-on-missing-value-dropped; Sol round 23)
                lli = "1" if code[0] == "L" and rng.random() < 0.6 else " "
                return " " * 14 + lli + (str(rng.randint(1, 9)) if lli == " " or rng.random() < 0.5 else " ")
            return " " * 16
        v = "%14.3f" % _value(rng, code)
        lli = " "
        if code[0] == "L" and rng.random() < 0.12:
            lli = rng.choice("1124")
        ssi = str(rng.randint(1, 9)) if rng.random() < 0.4 else " "
        return v + lli + ssi

    def record(self, sat, types, count=True):
        fs = [self.field(c) for c in types]
        if not count:
            self.slip_sats.add(sat)
        else:
            n = self.n_obs.setdefault(sat, [])
            n.extend([0] * (len(types) - len(n)))
            for i, f in enumerate(fs):
                if f[:14].strip():
                    n[i] += 1
        if self.v >= "3":
            return [(sat + "".join(fs)).rstrip()]
        return ["".join(fs[k:k + 5]).rstrip() for k in range(0, len(fs), 5)] or [""]

    def body(self):
        rng, v = self.rng, self.v
        out = []
        sec = -15
        types = dict(self.types)
        v2 = list(self.v2)
        late = self.slot_late
        self.n_obs = {}               # per satellite, values per type (flags 0 and 1)
        self.slip_sats = set()        # satellites of flag-6 records
        self.types_changed = False
        self.last = None
        for k in range(rng.randint(3, 10)):
            r = rng.random()
            sec += 15
            if k > 0 and r < 0.3:
                flag = 4 if r < 0.22 else rng.choice([2, 3, 5])
                recs = [hdr("EVENT %d" % k, "COMMENT")]
                if flag == 3:
                    recs.append(hdr("TEST2", "MARKER NAME"))
                if flag == 4:
                    if rng.random() < 0.3:
                        recs.append(hdr("    18", "LEAP SECONDS"))
                    if v >= "3" and rng.random() < 0.3:
                        s = rng.choice(self.sys)
                        recs.append(hdr(f"{s} {types[s][0]}   0.2345        0.0000        0.0678",
                                        "ANTENNA: PHASECENTER"))
                    if v >= "3" and rng.random() < 0.2:
                        recs.append(hdr(f"{rng.choice(self.sys)} RTKLIB              https://example.org/pcv",
                                        "SYS / PCVS APPLIED"))
                    if late:
                        recs.append(hdr(f"  1 {late} {FCN_OF[late]:2d}", "GLONASS SLOT / FRQ #"))
                        late = None
                    if v < "3" and rng.random() < 0.2:
                        recs.append(hdr("     1     1", "WAVELENGTH FACT L1/2"))
                    if rng.random() < 0.15:
                        self.types_changed = True
                        if v >= "3":
                            types = {s: self._v3_list(s) for s in self.sys}
                            recs += self.v3_types(types)
                            if self.scale:
                                # a new list ends the scale factors of the old one: restated
                                s, (f, cs) = next(iter(self.scale.items()))
                                cs2 = [c for c in types[s] if c in cs][:12]
                                if cs2:
                                    recs.append(hdr(f"{s} {f:4d}  {len(cs2):2d}" + "".join(f" {c}" for c in cs2),
                                                    "SYS / SCALE FACTOR"))
                        else:
                            v2 = self._v2_list()
                            recs += self.v2_types(v2)
                out += self.epoch(sec, flag, len(recs)) + recs
                continue
            flag = 0 if k == 0 else (6 if r > 0.9 else (1 if r > 0.82 else 0))
            pick = [s for sy in self.sys for s in self.sats[sy] if rng.random() < 0.6 and s != late]
            if not pick:
                pick = [next(s for sy in self.sys for s in self.sats[sy] if s != late)]
            ps = rng.randint(0, 99999) if self.ps and k > 0 and flag != 6 and rng.random() < 0.7 else None
            out += self.epoch(sec, flag, pick, clock=self.clock and flag != 6 and rng.random() < 0.8, ps=ps)
            if flag != 6:
                self.last = sec
            for s in pick:
                out += self.record(s, types[s[0]] if v >= "3" else v2, count=flag != 6)
        return out

    def counts(self):
        """# OF SATELLITES, PRN / # OF OBS (3X,A1,I2,9I6, continuation 6X,9I6: rinex211.txt
        Table A1, rinex305.txt Table A2) and TIME OF LAST OBS, from the data; with a chance
        of a wrong count, which the converter must repair and report (HDR.COUNTS)."""
        rng = self.rng
        extra = 1 if rng.random() < 0.25 else 0
        self.damaged = self.damaged or bool(extra)
        out = [hdr(f"{len(self.n_obs) + extra:6d}", "# OF SATELLITES")]
        for sat in sorted(self.n_obs):
            n = list(self.n_obs[sat])
            if rng.random() < 0.05:
                n[0] += 1
                self.damaged = True
            for k in range(0, len(n), 9):
                head = f"   {sat}" if k == 0 else " " * 6
                out.append(hdr(head + "".join(f"{x:6d}" for x in n[k:k + 9]), "PRN / # OF OBS"))
        return out

    def data(self):
        h = self.header()
        b = self.body()
        extra = []
        # (not when a satellite has flag-6 records only: whether those count, the specs do
        # not say)
        if not self.types_changed and self.n_obs and not (self.slip_sats - set(self.n_obs)) \
                and self.rng.random() < 0.35:
            extra += self.counts()
        if self.last is not None and self.rng.random() < 0.4:
            extra.append(hdr("  2026    10     1     0    %2d   %10.7f     GPS" % (self.last // 60, self.last % 60),
                             "TIME OF LAST OBS"))
        h = h[:-1] + extra + h[-1:]
        return ("\n".join(h + b) + "\n").encode("latin-1")


# --- meteorological files (rinex211.txt Tables A5/A6, rinex305.txt A16-A18, rinex_4.02.txt
# A42-A44): types PR TD HR ZW ZD ZT, and WD WS RI HI from 2.11 (rinex211.txt section 10.3);
# epochs 1X,I2.2,5(1X,I2) up to 3.01 and 1X,I4,5(1X,I2) from 3.02; values mF7.1, 8 on the
# epoch line, continuation lines 4X,10F7.1

MET_BASE = ["PR", "TD", "HR", "ZW", "ZD", "ZT"]
MET_211 = ["WD", "WS", "RI", "HI"]
MET_RANGE = {"PR": (900, 1050), "TD": (-30, 45), "HR": (5, 100), "ZW": (0, 500), "ZD": (2000, 2400),
             "ZT": (2000, 2700), "WD": (0, 359.9), "WS": (0, 40), "RI": (0, 200), "HI": (0, 50)}


def met_file(seed):
    """(version, bytes) of one valid met file."""
    rng = random.Random(seed)
    v = rng.choice(SOURCES)
    pool = MET_BASE + (MET_211 if v >= "2.11" else [])
    types = rng.sample(pool, rng.randint(1, len(pool)))
    h = [hdr(f"{v:>9}           METEOROLOGICAL DATA", "RINEX VERSION / TYPE"),
         hdr("GENMET 1.0          TEST                20261030 120000 UTC", "PGM / RUN BY / DATE")]
    if rng.random() < 0.5:
        h.append(hdr("GENERATED MET FILE", "COMMENT"))
    h.append(hdr("TEST", "MARKER NAME"))
    if rng.random() < 0.5:
        h.append(hdr("12345M001", "MARKER NUMBER"))
    for lab, text in (("DOI", "https://doi.org/10.1234/test"), ("LICENSE OF USE", "CC BY 4.0"),
                      ("STATION INFORMATION", "https://example.org/station")):
        if v >= "4" and rng.random() < 0.3:
            h.append(hdr(text, lab))
    for k in range(0, len(types), 9):
        head = f"{len(types):6d}" if k == 0 else " " * 6
        h.append(hdr(head + "".join(f"    {t}" for t in types[k:k + 9]), "# / TYPES OF OBSERV"))
    for t in types:
        h.append(hdr(f"{'MODEL':<20}{'TYPE':<20}{'':6}{0.1:7.1f} {t}", "SENSOR MOD/TYPE/ACC"))
    for t in types:
        if t == "PR" or rng.random() < 0.4:
            h.append(hdr(f"{4027894.006:14.4f}{307045.6:14.4f}{4919474.91:14.4f}{158.117:14.4f} {t}",
                         "SENSOR POS XYZ/H"))
    h.append(hdr("", "END OF HEADER"))
    body = []
    y4 = v >= "3.02"
    for e in range(rng.randint(2, 8)):
        mi, s = divmod(30 * e, 60)
        ep = (" 2026" if y4 else " 26") + " 10  1  0 %2d %2d" % (mi, s)
        vals = [" " * 7 if rng.random() < 0.08 else "%7.1f" % rng.uniform(*MET_RANGE[t]) for t in types]
        line = ep + "".join(vals[:8])
        body.append(line.rstrip() if rng.random() < 0.5 else line)
        for k in range(8, len(vals), 10):
            body.append(("    " + "".join(vals[k:k + 10])).rstrip())
    return v, ("\n".join(h + body) + "\n").encode("latin-1")


# --- navigation files: real corpus files cut into random record subsets, with header
# corrections dropped at random (data/corpus is gitignored; without it these are skipped)

NAV_CORR = {"ION ALPHA", "ION BETA", "DELTA-UTC: A0,A1,T,W", "CORR TO SYSTEM TIME", "D-UTC A0,A1,T,W,S,U",
            "IONOSPHERIC CORR", "TIME SYSTEM CORR", "LEAP SECONDS"}


def nav_records(payload):
    """(header lines, [record lines]) of a nav file: a record starts with a satellite (RINEX
    2: the PRN in columns 1-2; RINEX 3: column 1 not blank) or, in RINEX 4, a '>' line."""
    lines = payload.decode("latin-1").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    k = next(i for i, l in enumerate(lines) if l[60:80].strip() == "END OF HEADER")
    head, body = lines[:k + 1], lines[k + 1:]
    v = float(head[0][:9])
    recs = []
    for l in body:
        start = l[:1] == ">" if v >= 4 else (l[:1] != " " if v >= 3 else bool(l[:2].strip()))
        if start or not recs:
            recs.append([l])
        else:
            recs[-1].append(l)
    return head, recs


def nav_cut(rng, payload):
    head, recs = nav_records(payload)
    keep = sorted(rng.sample(range(len(recs)), min(len(recs), rng.randint(1, 25))))
    h = [l for l in head if not (l[60:80].strip() in NAV_CORR and rng.random() < 0.3)]
    return ("\n".join(h + [l for i in keep for l in recs[i]]) + "\n").encode("latin-1")
