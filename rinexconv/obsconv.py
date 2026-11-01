"""Observation conversion between any two RINEX versions (PLAN §3.5).

The engine works in two passes over the parsed model:
  pass 1  collects which observation types actually carry data per system and
          per obs-type state (flag-4 events can redefine types mid-file);
  pass 2  fixes the target obs-type lists, writes the header, and rebuilds
          every satellite record by copying the 16-character fields.

Values are copied as text (both layouts use F14.3), so a value is never
re-rounded except when a scale factor has to be applied for RINEX 2.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_EVEN

from rinexcore.errors import CorruptError, MissingInformationError, NotRepresentableError
from rinexcore.header import HeaderRecord, fmt_f
from rinexcore.obs import (_ZERO_CHARS, BLANK, FIELD, Epoch, ObsFile, ObsTypes, is_missing_value,
                           parse_v2_types, parse_v3_types)

BLANK14 = " " * 14
_Q3 = Decimal("0.001")

from rinexcore.spec import obsheader

from . import codemap

SYS_ORDER = "GRECJIS"
SYS_NAMES = {"G": "GPS", "R": "GLONASS", "E": "GALILEO", "S": "SBAS", "C": "BEIDOU",
             "J": "QZSS", "I": "NAVIC", "M": "MIXED", "T": "TRANSIT"}
TIME_SYS_DEFAULT = {"G": "GPS", "R": "GLO", "E": "GAL", "C": "BDT", "J": "QZS", "I": "IRN",
                    "S": "GPS"}


# Records the converter interprets (values, alignment, channels, biases): one in a version that
# does not define it means nothing to that version's readers (rinex211.txt Table A1 has none
# of them; SYS / PHASE SHIFT and GLONASS SLOT / FRQ # are from 3.01, GLONASS COD/PHS/BIS from
# 3.02: rinexcore/spec/obsheader.py), so it is never interpreted: carried as written to the
# file's own version, claimed elsewhere (Sol round 16: a 2.11 SYS / SCALE FACTOR vanished and
# was reported "applied"). WAVELENGTH FACT L1/2 in a RINEX 3 file keeps its own handling.
INTERPRETED = ("SYS / SCALE FACTOR", "SYS / PHASE SHIFT", "GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS")


def _sampling(times):
    """The most frequent positive step between successive epochs, in INTERVAL's F10.3, or
    None with fewer than two epochs."""
    diffs = {}
    for a, b in zip(times, times[1:]):
        dt = _tdiff(a, b)
        if dt > 0:
            diffs[dt] = diffs.get(dt, 0) + 1
    if not diffs:
        return None
    mode = max(diffs.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return mode.quantize(Decimal("0.001"), rounding="ROUND_HALF_EVEN")


def _add_seconds(t, s):
    """An epoch (y, mo, d, h, mi, Decimal sec) plus s whole seconds."""
    if not s or t is None:
        return t
    import datetime
    y, mo, d, h, mi, sec = t
    sec = sec + s
    carry = int((sec / 60).to_integral_value(rounding="ROUND_FLOOR"))      # (// truncates)
    dt = datetime.datetime(y, mo, d, h, mi) + datetime.timedelta(minutes=carry)
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, sec - 60 * carry)


class Crx1EventError(NotRepresentableError):
    """A RINEX 2 epoch with event flag 6 that Compact RINEX 1.0 cannot hold. The engine catches
    it and writes the file as plain RINEX 2, with a warning (the user's choice, 2026-10-31:
    no data lost, rather than refusing or dropping the epoch)."""


# Header records only RINEX 3/4 defines (rinex305.txt Table A2) and only 4.x defines
# (rinex_4.02.txt Table A2).
V3_ONLY = {"MARKER TYPE", "ANTENNA: DELTA X/Y/Z", "ANTENNA: PHASECENTER", "ANTENNA: B.SIGHT XYZ",
           "ANTENNA: ZERODIR AZI", "ANTENNA: ZERODIR XYZ", "CENTER OF MASS: XYZ",
           "SIGNAL STRENGTH UNIT", "SYS / DCBS APPLIED", "SYS / PCVS APPLIED"}
V4_ONLY = {"DOI", "LICENSE OF USE", "STATION INFORMATION"}
COMMON = {"PGM / RUN BY / DATE", "COMMENT", "MARKER NAME", "MARKER NUMBER", "OBSERVER / AGENCY",
          "REC # / TYPE / VERS", "ANT # / TYPE", "APPROX POSITION XYZ", "ANTENNA: DELTA H/E/N",
          "INTERVAL", "RCV CLOCK OFFS APPL"}
GENERATED = {"RINEX VERSION / TYPE", "# / TYPES OF OBSERV", "SYS / # / OBS TYPES", "TIME OF FIRST OBS",
             "TIME OF LAST OBS", "# OF SATELLITES", "PRN / # OF OBS", "SYS / PHASE SHIFT",
             "SYS / PHASE SHIFTS", "GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS", "LEAP SECONDS",
             "SYS / SCALE FACTOR", "WAVELENGTH FACT L1/2"}
KNOWN = V3_ONLY | V4_ONLY | COMMON | GENERATED

CANON = ["RINEX VERSION / TYPE", "PGM / RUN BY / DATE", "COMMENT", "MARKER NAME", "MARKER NUMBER",
         "MARKER TYPE", "OBSERVER / AGENCY", "REC # / TYPE / VERS", "ANT # / TYPE",
         "APPROX POSITION XYZ", "ANTENNA: DELTA H/E/N", "ANTENNA: DELTA X/Y/Z",
         "ANTENNA: PHASECENTER", "ANTENNA: B.SIGHT XYZ", "ANTENNA: ZERODIR AZI",
         "ANTENNA: ZERODIR XYZ", "CENTER OF MASS: XYZ", "DOI", "LICENSE OF USE",
         "STATION INFORMATION", "WAVELENGTH FACT L1/2", "# / TYPES OF OBSERV",
         "SYS / # / OBS TYPES", "SIGNAL STRENGTH UNIT", "INTERVAL", "TIME OF FIRST OBS",
         "TIME OF LAST OBS", "RCV CLOCK OFFS APPL", "SYS / DCBS APPLIED", "SYS / PCVS APPLIED",
         "SYS / SCALE FACTOR", "SYS / PHASE SHIFT", "GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS",
         "LEAP SECONDS", "# OF SATELLITES", "PRN / # OF OBS"]
_CANON_IDX = {k: i for i, k in enumerate(CANON)}


@dataclass
class ObsOptions:
    lenient: bool = False
    strict: bool = False
    overrides: dict = field(default_factory=dict)     # "G:L2" -> "L2L"
    glo_fcn: dict = None                              # "R01" -> int, from --glo-fcn / --nav
    glo_fcn_source: str = None
    drop_unresolvable: bool = False
    assume_phase_aligned: bool = False
    keep_v2_nonstandard: bool = False                 # write C/J/I into RINEX 2.11 (flagged)
    keep_lli_bit2: bool = False                       # carry LLI bit 2 even where it changes meaning
    approx_position: tuple = None                     # user X Y Z (m) when the target needs one
    approx_position_zero: bool = False                # else teqc's 0 0 0 placeholder (reported)
    crx1: bool = False                                # output goes on to Compact RINEX 1.0


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def presurvey(src):
    """Run pass 1 over a freshly read file: it parses (and so checks) every epoch and
    caches what the conversions need."""
    _ObsConverter(src, "3.05", ObsOptions(), None).survey()


def convert_obs(src, target, opts, report):
    conv = _ObsConverter(src, target, opts, report)
    return conv.run()


class _ObsConverter:
    def __init__(self, src, target, opts, report):
        self.src = src
        self.target = target
        self.opts = opts
        self.r = report
        self.tlayout = "v2" if target < "3" else "v3"
        self.slayout = src.layout
        self.time_shift = 0               # seconds added to every epoch (time_records)
        self.out_tsys = None
        # the source header without interpreted records its version does not define
        self.own_header = [r for r in src.header if not self.foreign(r.label)]

    def foreign(self, label):
        canon = obsheader.canonical_label(label)
        # (2.00/2.01 have no table of their own; none of these RINEX 3 records is in them,
        # as in 2.10: rinex210.txt section 0.4)
        ver = self.src.version if self.src.version >= "2.10" else "2.10"
        return canon in INTERPRETED and obsheader.status(ver, canon) is None

    def _foreign_record(self, rec, where="header"):
        """Carry a foreign interpreted record to its own version (True), or claim it."""
        if self.target == self.src.version:
            self.r.rule("OBS.HDR.NONSTANDARD-CARRIED" if where == "header" else "OBS.EVENT.NONSTANDARD-CARRIED")
            return True
        self.r.loss(f"{where}-record-foreign-dropped:{obsheader.canonical_label(rec.label)}", 1)
        return False

    # -- pass 1 ---------------------------------------------------------------
    def survey(self):
        """One pass over the source: per (obs-type state, satellite) the number of
        non-missing values of each type (flags 0/1), the same for flag-6 records, and the
        fields that carry only LLI/SSI. Everything else (which types carry data, loss
        counts, PRN / # OF OBS) is derived from these counts. The result depends only on
        the source, so it is cached on the source model for further targets."""
        cached = getattr(self.src, "_survey", None)
        if cached is not None:
            (self.states, self.used, self.counts, self.slip_counts, self.nrec,
             self.data_systems, self.ep_info, self.sat_seen, self.wl_events, self.phase_seq,
             self.scaled_zero, self.flag_counts, self.event_slots) = cached
            return
        event_slots = []     # (sat, channel) of events (flags 2-5) before the sat's first record
        ep_info = []         # (time, frozenset(systems), type-list key) of every flag 0/1 epoch
        sat_seen = {}        # sys -> set(sats), flags 0/1/6
        wl_events = False
        # the phase metadata over time: ("phase", records, line) for an event's SYS / PHASE
        # SHIFT, ("types", sid) at the first data epoch after it or after a type change
        phase_seq = []
        last_sid = None
        states = {}          # types.key -> state
        nrec = {}            # sys -> number of satellite records
        order = []
        counts = {}          # (sid, sat) -> [n per index], flags 0 and 1
        slips = {}           # (sid, sat) -> [n per index], flag 6
        flagonly = {}        # (sid, sys, idx) -> n: missing value but LLI/SSI set (flags 0/1/6)
        # RINEX 3 SYS / SCALE FACTOR in effect, and the flag 0/1 values it divides to 0.000:
        # missing in a RINEX 2 target (which has no factors), so not counted there
        scale = parse_scale_factors(self.src.header) if self.slayout == "v3" else {}
        scaled_zero = {}     # (sid, sat) -> [n per index]
        for ep in self.src.iter_epochs():
            st = ep.types
            sid = st.key
            if sid not in states:
                states[sid] = st
            if ep.flag > 1 and ep.flag != 6:
                if not wl_events and any(r.label == "WAVELENGTH FACT L1/2" for r in ep.records):
                    wl_events = True
                # a channel holds from its event on (rinex305.txt section 6.5 p.42): it may
                # serve the header only for satellites not observed before it (Sol round 23:
                # one given at 00:00:15 was applied to an observation at 00:00:00)
                ev = parse_glonass_slots([r for r in ep.records if r.label == "GLONASS SLOT / FRQ #"])
                seen_r = sat_seen.get("R", ())
                event_slots += [(s, k) for s, k in ev.items() if s not in seen_r]
                ph = [r for r in ep.records if r.label in ("SYS / PHASE SHIFT", "SYS / PHASE SHIFTS")]
                if ph:
                    phase_seq.append(("phase", ph, ep.lineno))
                    last_sid = None
                if self.slayout == "v3" and ep.flag in (3, 4) and any(
                        r.label == "SYS / SCALE FACTOR" for r in ep.records):
                    scale = merge_scale(scale, parse_scale_factors(ep.records))   # as convert_epochs
                continue
            if sid != last_sid:
                phase_seq.append(("types", sid))
                last_sid = sid
            if ep.flag <= 1:
                ep_info.append((ep.time, frozenset(x[0] for x in ep.sats), sid))
            for x in ep.sats:
                sat_seen.setdefault(x[0], set()).add(x)
            table = counts if ep.flag <= 1 else slips
            for sat, rec in zip(ep.sats, ep.data):
                s = sat[0]
                nrec[s] = nrec.get(s, 0) + 1
                key = (sid, sat)
                c = table.get(key)
                if c is None:
                    c = table[key] = [0] * (len(rec) // FIELD)
                    if s not in order:
                        order.append(s)
                o = 0
                for i in range(len(c)):
                    if rec[o:o + 14].strip(_ZERO_CHARS):
                        c[i] += 1
                    elif rec[o + 14:o + 16].strip():
                        k = (sid, s, i)
                        flagonly[k] = flagonly.get(k, 0) + 1
                    o += FIELD
                if scale and ep.flag <= 1:
                    codes = st.codes(s)
                    for i in range(min(len(c), len(codes))):
                        fac = scale.get((s, codes[i])) or scale.get((s, "*"))
                        v = rec[i * FIELD:i * FIELD + 14]
                        if not (fac and fac != 1 and v.strip(_ZERO_CHARS)):
                            continue
                        try:
                            q = (Decimal(v.strip()) / fac).quantize(_Q3, rounding=ROUND_HALF_EVEN)
                        except ArithmeticError:
                            continue      # unreadable: data damage, refused (engine._refuse_damage)
                        if q == 0:
                            z = scaled_zero.setdefault(key, [0] * len(c))
                            z[i] += 1
        if self.src.types.key not in states:
            states[self.src.types.key] = self.src.types
        used = {sid: {} for sid in states}
        for table in (counts, slips):
            for (sid, sat), c in table.items():
                u = used[sid].setdefault(sat[0], set())
                u.update(i for i, n in enumerate(c) if n)
        for sid, s, i in flagonly:
            used[sid].setdefault(s, set()).add(i)
        self.states = states
        self.used = used
        self.counts = counts
        self.slip_counts = slips
        self.nrec = nrec
        self.data_systems = order
        self.ep_info = ep_info
        self.sat_seen = sat_seen
        self.wl_events = wl_events
        self.phase_seq = phase_seq
        self.scaled_zero = scaled_zero
        self.flag_counts = flagonly
        self.event_slots = event_slots
        self.src._survey = (states, used, counts, slips, nrec, order, ep_info, sat_seen, wl_events,
                            phase_seq, scaled_zero, flagonly, event_slots)

    def _has_types(self, sid, s):
        """System s has target types under source type list sid (a record with none is left
        out: convert_epochs). Before the target states exist, every kept system has."""
        tst = getattr(self, "tstates", None)
        return tst is None or bool(tst[sid].codes(s))

    def kept_times(self):
        """Times of the flag 0/1 epochs the output keeps: one with a satellite record the
        output writes (of a kept system with target types under the epoch's list: Sol round
        21), or one without satellites."""
        keep = set(self.systems)
        return [t for t, syss, sid in self.ep_info if t is not None
                and (not syss or any(x in keep and self._has_types(sid, x) for x in syss))]

    def source_times(self):
        """Times of every flag 0/1 epoch of the source: what its own header describes."""
        return [t for t, syss, sid in self.ep_info if t is not None]

    def present_sats(self):
        """Satellites the output data hold: some record of theirs is written (flags 0, 1 and
        6; a kept system with target types under that record's list)."""
        keep = set(self.systems)
        return {sat for table in (self.counts, self.slip_counts) for (sid, sat) in table
                if sat[0] in keep and self._has_types(sid, sat[0])}

    # -- systems --------------------------------------------------------------
    def choose_systems(self):
        keep = []
        cand = list(self.data_systems)
        if self.slayout == "v3" and (self.tlayout == "v3" or not self.data_systems):
            # the systems every type list declares, a flag-4 event's too (Sol round 14: a
            # system declared only by an event, without observations, vanished unreported)
            for st in [self.src.types] + list(self.states.values()):
                cand += [s for s in st.sys if s not in cand]
        if self.slayout == "v2" and not cand:
            # no data: the header's system letter says which system the types belong to
            hs = self.src.system.strip()
            cand = [hs if hs and hs != "M" else "G"]
        for s in sorted(cand, key=lambda c: SYS_ORDER.find(c) if c in SYS_ORDER else 99):
            if self.tlayout == "v2" and s in "CJI" and not self.opts.keep_v2_nonstandard:
                self.r.loss(f"system-not-representable:{s}", self.nrec.get(s, 0), records=self.nrec.get(s, 0))
                self.r.rule(f"OBS.V3V2.DROP-SYSTEM.{s}")
                continue
            if not codemap.system_valid(self.target, s) and not (
                    self.tlayout == "v2" and s in "CJI" and self.opts.keep_v2_nonstandard):
                self.r.loss(f"system-not-representable:{s}", self.nrec.get(s, 0), records=self.nrec.get(s, 0))
                self.r.rule(f"OBS.DROP-SYSTEM.{s}")
                continue
            keep.append(s)
        if self.data_systems and not keep:
            raise NotRepresentableError(
                f"RINEX {self.target} cannot hold any system of this file "
                f"({', '.join(self.data_systems)}); nothing to write")
        self.systems = keep

    # -- code mapping ---------------------------------------------------------
    def map_state(self, st, used):
        """For one source obs-type state: per system, [(src_idx, target code)] and the
        resulting target ObsTypes (built later once every state is mapped)."""
        out = {}
        if not hasattr(self, "_data_sids"):
            self._data_sids = {sid for table in (self.counts, self.slip_counts) for sid, sat in table}
        for s in self.systems:
            src_codes = st.codes(s)
            have = used.get(s, set())
            if self.tlayout == self.slayout or not self.data_systems or st.key not in self._data_sids:
                # same layout, a file without data, or a list no data epoch uses (a flag-4
                # list replaces it first): keep the declared types
                have = set(range(len(src_codes)))
            cand = []
            for i, c in enumerate(src_codes):
                if i not in have:
                    continue
                tc = self.map_code(s, c, st, i)
                if tc is None:
                    continue
                cand.append((i, c, tc))
            # collisions: several source codes onto one target code
            best = {}
            kept_twice = []
            for i, c, tc in cand:
                if tc in best:
                    j, cj = best[tc]
                    if c == cj and self.slayout == self.tlayout == "v3" and (
                            self._count_col(st, s, i) or self._count_flags(st, s, i)):
                        # the source lists this code twice and the later column holds values
                        # or flags: RINEX 3/4 lists per system, so both columns are kept as written
                        kept_twice.append((i, tc))
                        self.r.warn("OBS.DUPLICATE-CODE-KEPT", f"{s} {c} is listed twice and both "
                                    "columns hold values or flags; both kept")
                    elif self._rank(s, c) < self._rank(s, cj):
                        best[tc] = (i, c)
                        self._collapsed(s, cj, tc, st, j)
                    else:
                        self._collapsed(s, c, tc, st, i)
                else:
                    best[tc] = (i, c)
            pairs = sorted([(i, tc) for tc, (i, c) in best.items()] + kept_twice, key=lambda p: p[0])
            out[s] = pairs
        return out

    def _rank(self, s, code):
        if len(code) == 3:
            return codemap.collapse_rank(s, code)
        return 0

    def _collapsed(self, s, code, tc, st, i):
        if self._count_col(st, s, i) or self._count_flags(st, s, i):
            self._lose_col(f"obs-code-collapsed:{s}:{code}", st, s, i, into=tc)
        else:
            # the column holds no value and no flag under this obs-type list (e.g. a code
            # listed twice with the second column always blank): nothing is lost
            self.r.normalise(f"obs-code-collapsed-empty:{s}:{code}")
        self.r.rule("OBS.V3V2.COLLAPSE" if self.tlayout == "v2" else "OBS.COLLAPSE")

    def _lose_col(self, category, st, s, i, **detail):
        """A dropped column: its values and its flag-only fields (a blank value with LLI or
        SSI, which the output would otherwise carry) are lost; the count holds both, and
        detail flag_only the second (Sol round 10)."""
        f = self._count_flags(st, s, i)
        if f:
            detail["flag_only"] = f
        self.r.loss(category, self._count_col(st, s, i) + f, **detail)

    def _count_flags(self, st, s, i):
        """Flag-only fields (flags 0, 1, 6) in column i of system s under obs-type list st."""
        return self.flag_counts.get((st.key, s, i), 0)

    def _count_col(self, st, s, i):
        """Non-missing values (flags 0, 1, 6) in column i of system s under obs-type list st.
        Counted per column and per list: a code may be listed twice, and map_state runs once
        per list, so a count by code name would credit one column with another's values or
        count a value once per list."""
        cache = getattr(self, "_col_counts", None)
        if cache is None:
            cache = self._col_counts = {}
            for table in (self.counts, self.slip_counts):
                for (sid, sat), c in table.items():
                    for k, n in enumerate(c):
                        if n:
                            key = (sid, sat[0], k)
                            cache[key] = cache.get(key, 0) + n
        return cache.get((st.key, s, i), 0)

    def map_code(self, s, c, st, i):
        tgt = self.target
        if self.slayout == "v2" and self.tlayout == "v3":
            v3, how = codemap.v2_to_v3(s, c, st.v2, tgt, self.opts.overrides)
            if v3 is None:
                if self._count_col(st, s, i) or self._count_flags(st, s, i):
                    self._lose_col(f"obs-code-not-representable:{s}:{c}", st, s, i)
                return None
            g, why = codemap.gate_v3(s, v3, "3.05", tgt)
            if g is None:
                self._lose_col(f"obs-code-not-representable:{s}:{c}", st, s, i, as_v3=v3)
                return None
            src_name = "override" if how == "override" else "table"
            self.r.assume(f"obs-code-attribute:{s}", f"{c}->{g}", src_name if how != "L2-follows-code"
                          else "receiver-rule:L2-follows-code")
            self.r.rule(f"OBS.V2V3.CODEMAP.{s}.{c}")
            return g
        if self.slayout == "v3" and self.tlayout == "v2":
            v2 = codemap.v3_to_v2(s, c)
            if v2 is None or not (codemap.code_valid(tgt, s, v2) or
                                  (s in "CJI" and self.opts.keep_v2_nonstandard)):
                self._lose_col(f"obs-code-not-representable:{s}:{c}", st, s, i)
                return None
            self.r.rule(f"OBS.V3V2.CODEMAP.{s}.{c}")
            return v2
        if self.slayout == "v2":
            if not codemap.code_valid(tgt, s, c) and not (s in "CJI" and self.opts.keep_v2_nonstandard):
                if tgt == self.src.version:
                    return self._nonstandard(s, c)
                # RINEX 2's one list names every code for every system; one the source version
                # does not define for this system either (SBAS P2: rinex211.txt section 10.1.1)
                # is lost only where its column holds something (as from RINEX 2 to 3, above)
                if codemap.source_defines(self.src.version, s, c) or self._count_col(st, s, i) \
                        or self._count_flags(st, s, i):
                    self._lose_col(f"obs-code-not-representable:{s}:{c}", st, s, i)
                return None
            return c
        g, why = codemap.gate_v3(s, c, self.src.version, tgt)
        if s == "C" and codemap.bds_nonstandard_band(c, self.src.version) and g is not None:
            self.r.repair("OBS.BDS-B1I-BAND", f"BeiDou B1I code {c} uses the band digit of another "
                          f"version than {self.src.version}; read as B1I")
        if g is None:
            if tgt == self.src.version:
                return self._nonstandard(s, c)
            self._lose_col(f"obs-code-not-representable:{s}:{c}", st, s, i)
            return None
        if why:
            self.r.rule(why)
        return g

    def _nonstandard(self, s, c):
        """A code the source version does not define: carried verbatim when the target is
        the source's own version (the file said so; dropping it would lose data)."""
        self.r.rule("OBS.NONSTANDARD-CODE-CARRIED")
        self.r.warn("OBS.NONSTANDARD-CODE", f"{s} {c} is not defined in RINEX {self.target}; "
                    "carried verbatim")
        return c

    def build_target_states(self):
        """Target ObsTypes per source state, and per-(state, system) source offsets."""
        self.tstates = {}
        self.offsets = {}
        self.code_of = {}
        self._check_types_left = True
        for sid, st in self.states.items():
            pairs = self.map_state(st, self.used.get(sid, {}))
            for s, pl in pairs.items():
                self.code_of[(sid, s)] = {st.codes(s)[i]: tc for i, tc in pl}
            if self.tlayout == "v3":
                tsys = {}
                for s in self.systems:
                    codes = [tc for i, tc in pairs.get(s, [])]
                    if codes:
                        tsys[s] = codes
                # keep systems with records but no used codes as empty lists only if they had data
                tst = ObsTypes("v3", sys=tsys)
                for s in self.systems:
                    self.offsets[(sid, s)] = [i * FIELD for i, tc in pairs.get(s, [])]
            else:
                glob = []
                for s in self.systems:
                    for i, tc in pairs.get(s, []):
                        if tc not in glob:
                            glob.append(tc)
                glob = self._v2_order(glob)
                tst = ObsTypes("v2", v2=glob)
                for s in self.systems:
                    m = {tc: i for i, tc in pairs.get(s, [])}
                    self.offsets[(sid, s)] = [m[c] * FIELD if c in m else -1 for c in glob]
            self.tstates[sid] = tst

    @staticmethod
    def _v2_order(codes):
        return codes

    # -- the epochs ------------------------------------------------------------
    def convert_epochs(self):
        """Pass 2: the converted epochs, one at a time (the report entries that count over
        the whole file are added when the generator is exhausted)."""
        keep = set(self.systems)
        dropped_empty = 0
        zero_norm = 0
        wl = self._wavelength_rule()
        scale = self._scale_rule()
        clear_b2 = (lli_bit2_meaning(self.src.version) != lli_bit2_meaning(self.target)
                    and not self.opts.keep_lli_bit2)
        b2 = 0
        crx1 = self.opts.crx1 and self.tlayout == "v2"
        crx1_flags = 0
        for ep in self.src.iter_epochs():
            sid = ep.types.key
            tst = self.tstates[sid]
            if 2 <= ep.flag <= 5:
                if wl is not None and ep.flag in (3, 4):
                    update_wavelength(wl, ep.records)
                if self.tlayout == "v2" and self.slayout == "v3" and ep.flag in (3, 4) and any(
                        r.label == "SYS / SCALE FACTOR" for r in ep.records):
                    scale = merge_scale(scale, parse_scale_factors(ep.records))
                    self.r.rule("OBS.V3V2.EVENT-SCALE-APPLIED")
                recs = self.convert_event_records(ep, tst)
                if recs is None:
                    continue
                if ep.time is not None and self.target < "4.02" and (ep.time[5] * 10 ** 7) % 1:
                    self.r.loss("epoch-precision", 1)     # as for observation epochs, below
                yield Epoch(_add_seconds(ep.time, self.time_shift), ep.flag, None, records=recs, types=tst,
                            lineno=ep.lineno)
                continue
            sats = []
            data = []
            for sat, rec in zip(ep.sats, ep.data):
                s = sat[0]
                if s not in keep:
                    continue
                offs = self.offsets[(sid, s)]
                if not offs:
                    # none of the system's types under this list exists in the target (each
                    # value claimed obs-code-not-representable): a record with no field is no
                    # record (round 20: it was written, and the output failed its own check)
                    continue
                parts = [rec[o:o + FIELD] if o >= 0 else BLANK for o in offs]
                for k, f in enumerate(parts):
                    # a zero value is "missing" and is written blank; only fields whose
                    # last value column is a 0 or a point can be zero
                    if f[13] in "0." and not f[:14].strip(_ZERO_CHARS):
                        f = parts[k] = BLANK14 + f[14:16]
                        zero_norm += 1
                    if clear_b2 and f[14] in "4567":
                        parts[k] = f[:14] + _CLEAR_B2[f[14]] + f[15]
                        b2 += 1          # flag-only fields too: their LLI changes (Sol round 10)
                if (wl is not None and ep.flag <= 1) or scale is not None:
                    parts = self._field_rules(s, sat, sid, offs, parts,
                                              wl if ep.flag <= 1 else None, scale)
                if crx1:
                    # after the value rules, which can blank a value (a scaled one rounding
                    # to 0.000): Compact RINEX 1.0 cannot hold LLI/SSI on a blank value
                    # (rnx2crx.c; docs/HATANAKA.md); the flags describe no observation
                    for k, f in enumerate(parts):
                        if f[14:16] != "  " and not f[:14].strip():
                            parts[k] = BLANK
                            crx1_flags += 1
                sats.append(sat)
                data.append("".join(parts))
            if crx1 and ep.flag == 6 and (len(sats) > 12 or any(len(d) > 80 for d in data)):
                # after an event flag above 1 (flag 6 included) RNX2CRX and CRX2RNX copy as
                # many lines as the epoch line counts (rnx2crx.c put_event_data), one per
                # satellite; a RINEX 2 record of more than 5 types, or a satellite list
                # continued past 12, needs more (Sonnet round 11); the engine then writes
                # plain RINEX 2
                raise Crx1EventError(
                    f"Compact RINEX 1.0 cannot hold the RINEX 2 epoch with event flag 6 (cycle slip "
                    f"records) at input line {ep.lineno}: after an event flag it copies one line per "
                    "satellite, and these records take "
                    f"{'more than one line (more than 5 observation types)' if any(len(d) > 80 for d in data) else 'a satellite list continued past 12'}")
            if not sats and ep.sats:
                dropped_empty += 1
                continue
            clock = ep.clock
            if clock is not None and self.tlayout == "v2":
                clock = self._clock_v2(clock)
            if ep.time is not None and self.target < "4.02" and (ep.time[5] * 10 ** 7) % 1:
                # sub-0.1-us epoch digits exist only in 4.02 (rinex_4.02.txt Table A3)
                self.r.loss("epoch-precision", 1)
            yield Epoch(_add_seconds(ep.time, self.time_shift), ep.flag, clock, sats, data, types=tst,
                        lineno=ep.lineno)
        if zero_norm:
            self.r.normalise("missing-zero-written-blank", zero_norm)
        if crx1_flags:
            self.r.loss("flags-on-missing-value-dropped", crx1_flags)
        if b2:
            self.r.loss("lli-bit2-meaning-differs", b2,
                        source=lli_bit2_meaning(self.src.version) or "undefined",
                        target=lli_bit2_meaning(self.target) or "undefined")
        if dropped_empty:
            self.r.loss("epoch-emptied-by-system-removal", dropped_empty)

    def _clock_v2(self, clock):
        q = clock.quantize(Decimal("1e-9"), rounding=ROUND_HALF_EVEN)
        try:
            fmt_f(q, 12, 9)
        except OverflowError:
            self.r.loss("clock-overflow", 1)
            return None              # dropped: its rounding is not a second loss (Sol round 13 audit)
        if q != clock:
            self.r.loss("clock-precision", 1)
        return q

    def _wavelength_rule(self):
        """RINEX 2 WAVELENGTH FACT L1/2 <-> RINEX 3 LLI bit 1 (half-cycle ambiguity).

        rinex211.txt Table A1/A2: factor 2 = half-wavelength (squaring); LLI bit 1 =
        opposite factor for the current epoch. RINEX 3 (rinex305.txt §5.2.x LLI) has no
        factor record; bit 1 means half-cycle ambiguity. So, for GPS L1/L2 phase only:
          v3 bit1 = v2 bit1 XOR (factor == 2).
        Returns {sat or '*': (f1, f2)} when some factor is 2, else None.
        """
        if not (self.slayout == "v2" and self.tlayout == "v3"):
            return None
        facs = {"*": (1, 1)}
        update_wavelength(facs, self.src.header)
        any2 = any(2 in v for v in facs.values()) or self.wl_events
        if not any2:
            return None
        self.r.rule("OBS.V2V3.WAVELENGTH-TO-LLI")
        return facs

    def _scale_rule(self):
        """RINEX 3 SYS / SCALE FACTOR -> RINEX 2 (no such record): values divided."""
        if not (self.slayout == "v3" and self.tlayout == "v2"):
            return None
        sf = parse_scale_factors(self.src.header)
        return sf or None

    def _field_rules(self, s, sat, sid, offs, parts, wl, scale):
        st = self.states[sid]
        tst = self.tstates[sid]
        tcodes = tst.codes(s)
        src_codes = st.codes(s)
        out = list(parts)
        for k, o in enumerate(offs):
            if o < 0:
                continue
            code = src_codes[o // FIELD]
            f = out[k]
            if wl is not None and s == "G" and code in ("L1", "L2") and f[:14].strip():
                # only a phase that was observed: a missing one has nothing to flag (zeros are
                # already blank here), so no LLI is created on it, and a flag-only field keeps
                # its flags as written
                band = int(code[1]) - 1
                fac = wl.get(sat, wl["*"])
                if fac[band] == 2:
                    lli = f[14]
                    b = int(lli) if lli.strip() else 0
                    b ^= 2
                    # a written LLI stays written: 0 is '0', not blank (both mean no
                    # flag, rinex305.txt §6.7.1; the checker applies the same rule)
                    f = f[:14] + (str(b) if b or lli.strip() else " ") + f[15]
                    out[k] = f
            if scale is not None:
                fac = scale.get((s, code)) or scale.get((s, "*"))
                if fac and fac != 1 and f[:14].strip():
                    try:
                        v = Decimal(f[:14].strip()) / fac
                    except ArithmeticError:
                        # --lenient carries damage as read, but an unreadable value cannot be
                        # divided by its factor, and carried undivided it would change meaning
                        raise CorruptError(f"{sat} {code} value {f[:14].strip()!r} cannot be divided by "
                                           f"its SYS / SCALE FACTOR {fac} for RINEX {self.target}",
                                           rule="OBS.DATA.SCALE") from None
                    q = v.quantize(_Q3, rounding=ROUND_HALF_EVEN)
                    if q != v:
                        self.r.loss(f"scale-factor-rounding:{s}:{code}", 1)
                    # a value that rounds to zero is missing (rinex305.txt §6.7): written
                    # blank, and not counted in PRN / # OF OBS (survey: scaled_zero)
                    out[k] = (fmt_f(q, 14, 3) if q else BLANK14) + f[14:16]
        return out

    # -- events -----------------------------------------------------------------
    def convert_event_records(self, ep, tst):
        recs = []
        phase = []
        for r in ep.records:
            lab = r.label
            if self.foreign(lab):
                if self._foreign_record(r, "event"):
                    recs.append(r)
                continue
            if lab == "COMMENT" or lab in COMMON:
                recs.append(r)
            elif lab in ("# / TYPES OF OBSERV", "SYS / # / OBS TYPES"):
                pass  # replaced below
            elif lab in ("# OF SATELLITES", "PRN / # OF OBS"):
                pass  # regenerated below
            elif lab in V3_ONLY and self.tlayout == "v3":
                # as in the header: codes mapped, records of systems the output lacks claimed
                # (Sol round 21: event copies were written unchanged)
                if lab == "ANTENNA: PHASECENTER" and self.slayout == "v3":
                    kept = self._phasecenter(r)
                else:
                    kept = self._filter_sys_record(r)
                if kept is not None:
                    recs.append(kept)
            elif lab in V4_ONLY and self.target >= "4":
                recs.append(r)
            elif lab in V3_ONLY | V4_ONLY and self.target == self.src.version:
                recs.append(r)                # the source's own non-standard record, as written
                self.r.rule("OBS.EVENT.NONSTANDARD-CARRIED")
            elif lab == "SYS / SCALE FACTOR":
                if self.tlayout == "v3":
                    pass                      # rebuilt below with this state's code map
                # RINEX 2: the factor is applied to the following values (convert_epochs)
            elif lab in ("SYS / PHASE SHIFT", "SYS / PHASE SHIFTS", "GLONASS COD/PHS/BIS"):
                defined = self.target >= ("3.02" if lab == "GLONASS COD/PHS/BIS" else "3.01")
                if defined and (self.target < "4" or self.src.version >= "4"):
                    if lab in ("SYS / PHASE SHIFT", "SYS / PHASE SHIFTS"):
                        if lab == "SYS / PHASE SHIFTS" and self.src.version != "3.01":
                            self.r.repair("HDR.PHASESHIFT.LABEL", "label SYS / PHASE SHIFTS (the 3.01 "
                                          "spelling) read as SYS / PHASE SHIFT", r.lineno)
                        phase.append(r)       # codes renamed as in the header, below
                    else:
                        recs.append(r)
                elif defined and lab == "GLONASS COD/PHS/BIS" and _cpb_known_nonzero(r):
                    recs.append(r)            # known non-zero biases are kept, as in the header
                elif defined:
                    # RINEX 3 -> 4: defined but strongly deprecated, "should be ignored by RINEX
                    # decoders and encoders" (rinex_4.00.txt Table A2 p.61); the header drops
                    # the same records (phase_records, glonass_records)
                    self.r.loss(f"event-record-deprecated:{obsheader.canonical_label(lab)}", 1)
                else:
                    self.r.loss(f"event-record-not-representable:{lab}", 1)
            elif lab == "LEAP SECONDS":
                recs.append(self._leap(r))    # as in the header (fields the target lacks reported)
            elif lab in ("TIME OF FIRST OBS", "TIME OF LAST OBS"):
                # 5I6,F13.7,5X,A3 in every version; in the header's time system, shifted with it
                t = _parse_time_rec(r)
                if t is not None and (self.time_shift or (self.out_tsys and r.content[48:51].strip()
                                                          not in ("", self.out_tsys))):
                    recs.append(self._time_rec(lab, _add_seconds(t, self.time_shift), self.out_tsys, None))
                else:
                    recs.append(r)
            elif lab == "GLONASS SLOT / FRQ #" and self.tlayout == "v3" and self.target >= "3.01":
                recs.append(r)                # optional in 3.01, defined from 3.02
            elif lab == "WAVELENGTH FACT L1/2":
                if self.tlayout == "v2":
                    recs.append(r)
                else:
                    # its effect moves into LLI bit 1 of the following epochs (_wavelength_rule)
                    self.r.rule("OBS.V2V3.WAVELENGTH-EVENT-TO-LLI")
            elif lab not in KNOWN:
                recs.append(r)
                self.r.rule("OBS.EVENT.NONSTANDARD-CARRIED")
            else:
                self.r.loss(f"event-record-not-representable:{lab}", 1)
        if phase:
            lab = obsheader.label_text(self.target, "SYS / PHASE SHIFT")
            recs.extend(HeaderRecord(lab, x.content, x.lineno)
                        for x in self._carry_phase(self._parse_phase(phase)))
        had_types = any(r.label in ("# / TYPES OF OBSERV", "SYS / # / OBS TYPES") for r in ep.records)
        if had_types:
            recs.extend(self.types_records(tst))
        if self.tlayout == "v3" and any(r.label == "SYS / SCALE FACTOR" and not self.foreign(r.label)
                                        for r in ep.records):
            recs.extend(self._scale_for(ep.records, ep.types.key))
        if any(r.label in ("# OF SATELLITES", "PRN / # OF OBS") for r in ep.records):
            recs.extend(self.count_records())
        if not recs and ep.records:
            if ep.flag == 4:
                self.r.loss("event-emptied", 1)
                return None
        return recs

    # -- header -------------------------------------------------------------------
    def types_records(self, tst):
        if self.tlayout == "v2":
            codes = list(tst.v2)
            out = []
            for k in range(0, max(1, len(codes)), 9):
                chunk = codes[k:k + 9]
                head = f"{len(codes):6d}" if k == 0 else " " * 6
                out.append(HeaderRecord("# / TYPES OF OBSERV",
                                        head + "".join(f"    {c:>2s}" for c in chunk)))
            return out
        out = []
        order = [s for s in self.sys_order() if s in tst.sys]
        for s in order:
            codes = tst.sys[s]
            for k in range(0, len(codes), 13):
                chunk = codes[k:k + 13]
                head = f"{s}  {len(codes):3d}" if k == 0 else " " * 6
                out.append(HeaderRecord("SYS / # / OBS TYPES", head + "".join(f" {c}" for c in chunk)))
        return out

    def sys_order(self):
        """Systems in the source's own order when it had per-system lists, else canonical."""
        if self.slayout == "v3":
            src_order = list(self.src.types.sys.keys())
            rest = [s for s in self.systems if s not in src_order]
            return [s for s in src_order if s in self.systems] + rest
        return list(self.systems)

    def count_records(self):
        """# OF SATELLITES and PRN / # OF OBS recomputed from the output (repairs PLAN §1.9)."""
        # Output values are copies of source fields (zero -> blank keeps "missing"), so
        # the output counts follow from the survey counts through the field mapping.
        counts = {}
        keep = set(self.systems)
        present = self.present_sats()
        for (sid, sat), c in self.counts.items():
            if sat[0] not in keep or sat not in present:
                continue
            tst = self.tstates[sid]
            if not tst.codes(sat[0]):
                continue                  # no types in the target: no record (convert_epochs)
            offs = self.offsets[(sid, sat[0])]
            codes = _occurrences(tst.codes(sat[0]))
            d = counts.setdefault(sat, {})
            # RINEX 3 -> 2 divides scaled values: those that round to 0.000 become missing
            z = self.scaled_zero.get((sid, sat)) if self.tlayout == "v2" else None
            for k, o in enumerate(offs):
                n = c[o // FIELD] - (z[o // FIELD] if z else 0) if o >= 0 else 0
                if n:
                    d[codes[k]] = d.get(codes[k], 0) + n
        # a satellite seen only in cycle-slip records (flag 6) is in the data too: listed,
        # with the flag 0/1 counts it has (none)
        for sat in present:
            counts.setdefault(sat, {})
        out = [HeaderRecord("# OF SATELLITES", f"{len(counts):6d}")]
        final = self.final_types
        # '99999 indicates >= 99999 observations' from 3.01 (rinex301.txt Table A2 l.2157);
        # 2.x and 3.00 give the actual count in I6 (rinex211.txt Table A1, rinex300.txt Table A2)
        saturate = self.target >= "3.01"
        if not saturate and any(n > 999999 for d in counts.values() for n in d.values()):
            # an I6 overflow: the record is optional in every version, so it is left out
            self.r.warn("OBS.PRN-COUNT-OVERFLOW", f"a PRN / # OF OBS count exceeds I6 in RINEX "
                        f"{self.target}: the optional record is left out")
            self.r.normalise("prn-counts-omitted-overflow")
            return out
        for sat in sorted(counts, key=lambda x: (SYS_ORDER.find(x[0]), x)):
            codes = _occurrences(final.codes(sat[0]))
            vals = [counts[sat].get(c, 0) for c in codes]
            if saturate:
                vals = [min(99999, v) for v in vals]
            satid = f"{sat[0]}{int(sat[1:]):2d}" if self.tlayout == "v2" else sat
            for k in range(0, max(1, len(vals)), 9):
                chunk = vals[k:k + 9]
                head = f"   {satid}" if k == 0 else " " * 6
                out.append(HeaderRecord("PRN / # OF OBS", head + "".join(f"{v:6d}" for v in chunk)))
        return out

    def version_record(self):
        syss = self.out_systems()
        letter = syss[0] if len(syss) == 1 else "M"
        src_first = self.src.header[0] if self.src.header else None
        src_letter = src_first.content[40:41].upper() if src_first is not None else ""
        if src_letter == "M" and letter != "M":
            letter = "M"          # a mixed file that happens to hold one system stays mixed
        if src_first is not None and src_letter == letter:
            sysfield = src_first.content[40:60]
        else:
            name = SYS_NAMES.get(letter, "")
            sysfield = f"{letter} ({name})" if name else letter
        content = f"{self.target:>9s}" + " " * 11 + "OBSERVATION DATA".ljust(20) + sysfield.ljust(20)
        return HeaderRecord("RINEX VERSION / TYPE", content)

    def out_systems(self):
        written = {x[0] for x in self.present_sats()}
        seen = [s for s in self.data_systems if s in self.systems and s in written]
        if not seen:
            seen = list(self.systems) or [self.src.system.strip() or "G"]
        return seen

    def time_records(self):
        """TIME OF FIRST OBS (mandatory) and TIME OF LAST OBS (if present in source)."""
        times = self.kept_times()
        first = times[0] if times else None
        last = times[-1] if times else None
        own = self.source_times()                 # the source header is checked against these
        own_first, own_last = (own[0], own[-1]) if own else (None, None)
        src_first = self.src.first("TIME OF FIRST OBS")
        src_last = self.src.first("TIME OF LAST OBS")
        tsys = None
        for r in (src_first, src_last):
            if r is not None and r.content[48:51].strip():
                t = r.content[48:51].strip()
                if t in TIME_SYSTEMS:
                    tsys = t
                    break
                self.r.repair("HDR.TIME-SYSTEM", f"unknown time system {t!r} in {r.label} ignored",
                              r.lineno)
        syss = self.out_systems()
        if tsys is None:
            if len(syss) == 1:
                tsys = TIME_SYS_DEFAULT.get(syss[0], "GPS")
                if self.tlayout == "v3" or len(syss) > 1:
                    self.r.assume("time-system", tsys, "default:single-system")
            else:
                tsys = "GPS"
                self.r.assume("time-system", tsys, "default:mixed-file-gps")
        tsys = self._target_time_system(tsys)
        first, last = _add_seconds(first, self.time_shift), _add_seconds(last, self.time_shift)
        recs = {}
        if first is not None:
            recs["TIME OF FIRST OBS"] = self._time_rec("TIME OF FIRST OBS", first, tsys, src_first, own_first)
        elif src_first is not None:
            recs["TIME OF FIRST OBS"] = src_first
        if src_last is not None and last is not None:
            recs["TIME OF LAST OBS"] = self._time_rec("TIME OF LAST OBS", last, tsys, src_last, own_last)
        elif src_last is not None:
            recs["TIME OF LAST OBS"] = src_last       # no data epochs: nothing to check it against
        return recs

    def _target_time_system(self, tsys):
        """The time system the target can hold. TIME OF FIRST OBS allows GPS and GLO in 2.10,
        also GAL in 2.11-3.01, QZS and BDT from 3.02, IRN from 3.03 (rinex211.txt Table A1
        l.1185, rinex301.txt Table A1 l.2035, rinex304.txt Table A2 l.3228; validate
        TIME_SYSTEMS). BDT is 14 s behind GPS time (rinex305.txt l.805): its epochs become GPS
        epochs + 14 s (Sol round 18: a 3.05 BDT file went to 2.11 still tagged BDT). QZS,
        IRN and GAL are aligned with GPS time within tens of ns, below the 0.1 us of an epoch,
        so only the label changes (an assumption)."""
        from rinexcore.validate import TIME_SYSTEMS as ALLOWED
        self.out_tsys = tsys
        if tsys in ALLOWED.get(self.target, {tsys}):
            return tsys
        if tsys == "BDT":
            self.time_shift = 14
            self.r.rule("OBS.TIME-SYSTEM.BDT-TO-GPS")
            self.r.warn("OBS.TIME-SYSTEM.BDT-TO-GPS", f"RINEX {self.target} has no BDT time system: every "
                        "epoch is written in GPS time, 14 s later (BDT is 14 s behind GPS time)")
        elif tsys in ("QZS", "IRN", "GAL"):
            self.r.assume("time-system", f"{tsys}->GPS", "spec:aligned-with-GPS-time")
        else:
            return tsys
        self.out_tsys = "GPS"
        return "GPS"

    def _time_rec(self, label, t, tsys, src, own=None):
        """The record for output time t. A source record is checked against own, the source
        data's own time (unshifted and of all its epochs: Sol round 19, a BDT header against
        BDT epochs; round 21, epochs the output leaves out still count), and kept as written
        when it is the output's too."""
        def f13_7(x):
            # F13.7: compare at 0.1 us (a 4.02 picosecond epoch is floored, rinex_4.02.txt Table A3)
            return x[:5] + (x[5].quantize(Decimal("1e-7"), rounding="ROUND_FLOOR"),)
        y, mo, d, h, mi, sec = t
        t = f13_7(t)
        sec = t[5]
        if src is not None:
            st = _parse_time_rec(src)
            ref = f13_7(own) if own is not None else _add_seconds(t, -self.time_shift)
            if st is not None and st == ref:
                if not self.time_shift and st == t and (src.content[48:51].strip() == tsys
                                                         or self.tlayout == "v2" and not src.content[48:51].strip()):
                    return src
            elif st is not None:
                self.r.repair(f"HDR.{label.replace(' ', '-')}", f"{label} {st} does not match the data, "
                              f"set to {t}", src.lineno)
        units = int((sec * 10 ** 7).to_integral_value(rounding="ROUND_FLOOR"))
        whole, frac = divmod(units, 10 ** 7)
        content = f"{y:6d}{mo:6d}{d:6d}{h:6d}{mi:6d}{whole:5d}.{frac:07d}     {tsys:3s}"
        return HeaderRecord(label, content)

    def interval_record(self):
        src = self.src.first("INTERVAL")
        if src is None:
            return None
        try:
            v = Decimal(src.content[0:10].strip())
        except Exception:
            self.r.repair("HDR.INTERVAL", "unreadable INTERVAL dropped", src.lineno)
            return None
        own, kept = _sampling(self.source_times()), _sampling(self.kept_times())
        if own is not None and own != v and v != 0:
            # the source's own header against its own data (Sol round 21: epochs the output
            # leaves out changed the sampling and looked like a wrong INTERVAL)
            self.r.repair("HDR.INTERVAL", f"INTERVAL {v} does not match the data sampling {own}",
                          src.lineno)
        if kept is None or v == 0:
            return src if own is None or own == v or v == 0 else HeaderRecord("INTERVAL", fmt_f(own, 10, 3))
        if kept == v:
            return src
        if kept != own:
            self.r.rule("OBS.INTERVAL.FROM-KEPT-EPOCHS")      # epochs left out (claimed) changed it
        return HeaderRecord("INTERVAL", fmt_f(kept, 10, 3))

    def leap_record(self):
        src = self.src.first("LEAP SECONDS")
        return None if src is None else self._leap(src)

    def _leap(self, src):
        """A LEAP SECONDS record (header or event) for the target (leap.for_target: BDT values
        in GPS terms where the target cannot hold BDT, then the target's width)."""
        from . import leap
        return leap.for_target(src, self.src.version, self.target, self.r)

    def phase_records(self):
        """SYS / PHASE SHIFT for the target, from the alignment state (PLAN §3.3)."""
        entries = self._parse_phase(self.own_header)
        sv = self.src.version
        tv = self.target
        systems = ([s for s in self.sys_order() if any(st.codes(s) for st in self.tstates.values())]
                   if self.tlayout == "v3" else self.systems)
        state = self._phase_state_of(entries)
        self.phase_state = state
        has_values = any(e[2] is not None for e in entries)
        if tv < "3.01":
            if entries and any(e[1] for e in entries):
                self.r.loss("phase-shift-record-not-representable", len(entries))
            return []
        if tv >= "4":
            if "3.01" <= sv < "4":
                where = self._unknown_phase_periods(entries)
            else:
                where = {s: "the header" for s in self.systems
                         if state[s] == "unknown" and self._has_phase(s)}
            unknown = [s for s in self.systems if s in where]
            if unknown:
                if not self.opts.assume_phase_aligned:
                    raise MissingInformationError(
                        "RINEX 4 requires aligned phases (rinex_4.00.txt §5.2.12) but the phase "
                        f"alignment of {', '.join(unknown)} is unknown in the RINEX {sv} source ("
                        + "; ".join(f"{s}: {where[s]}" for s in unknown) + "); "
                        "pass --assume-phase-aligned if the receiver delivered aligned phases",
                        missing="phase-alignment:" + ",".join(unknown))
                for s in unknown:
                    self.r.assume("phase-alignment", s, "override:--assume-phase-aligned")
            if sv >= "4":
                out = []
                for e in entries:
                    if e[0] in self.systems:
                        out.extend(_phase_lines(*e[:4]) if e[6] else e[5])
                return out
            if has_values:
                # entries of systems the output holds (a type list, header or event); a system
                # left without types has its values claimed already (generator round 27: a
                # BeiDou L1N entry, no 4.02 code, was counted too)
                held = {s for s in self.systems if any(st.codes(s) for st in self.tstates.values())}
                self.r.loss("phase-shift-record-deprecated", len([e for e in entries if e[0] in held]))
            return []
        # 3.01 .. 3.05
        if "3.01" <= sv < "4":
            out = self._carry_phase(entries)
            if not out and any(r.label in ("SYS / PHASE SHIFT", "SYS / PHASE SHIFTS")
                               for r in self.own_header):
                # the source has the record but nothing of it can be carried (an empty line,
                # or only systems the target drops): it is mandatory from 3.01, so each
                # system gets the form for 'applied corrections ... unknown' (rinex301.txt
                # Table A2 l.2113, rinex302.txt p.42), as a RINEX 2 source does. A source
                # without the record keeps that (inherited) gap: nothing is synthesised.
                # --assume-phase-aligned does not apply: it is for 4.x targets (PLAN §3.3
                # rule 2), and a source's explicit 'unknown' record is carried as written.
                out = self._phase_from_state([], systems, {s: "unknown" for s in systems}, assume=False)
            return out
        return self._phase_from_state(entries, systems, state)

    def _unknown_phase_periods(self, entries):
        """{sys: where} for systems whose phases are of unknown alignment while the type
        list in effect holds phase types. Header SYS / PHASE SHIFT holds until an event's
        record for the same system changes it ('each value remains valid until changed by an
        additional header record', rinex305.txt §6.5 p.41); the type list is that of the data
        epochs that follow (pass 1, phase_seq)."""
        eff = {s: [e for e in entries if e[0] == s] for s in self.systems}
        src_where = {s: "the header" for s in self.systems}
        out = {}
        for item in self.phase_seq:
            if item[0] == "phase":
                ev = parse_phase_shift(item[1])
                for s in {e[0] for e in ev}:
                    eff[s] = [e for e in ev if e[0] == s]
                    src_where[s] = f"the event at input line {item[2]}"
                continue
            st = self._phase_state_of([e for lst in eff.values() for e in lst])
            tcodes = self.tstates[item[1]]
            for s in self.systems:
                if s not in out and st[s] == "unknown" and any(c[0] == "L" for c in tcodes.codes(s)):
                    out[s] = src_where[s]
        return out

    def _phase_state_of(self, entries):
        """Per system: 'aligned' (RINEX 4 source), 'recorded' (entries with codes and, before
        3.03, values) or 'unknown' (RINEX 2/3.00 source, no entry, the system-only form, or
        a 3.01/3.02 entry without values)."""
        sv = self.src.version
        state = {}
        for s in self.systems:
            mine = [e for e in entries if e[0] == s]
            if sv >= "4":
                state[s] = "aligned"
            elif sv < "3.01":
                state[s] = "unknown"
            elif not mine:
                state[s] = "unknown"
            elif all(e[1] == "" for e in mine):
                state[s] = "unknown"
            elif sv < "3.03" and all(e[2] is None for e in mine):
                state[s] = "unknown"
            else:
                state[s] = "recorded"
        return state

    def _parse_phase(self, records):
        empty = []
        entries = parse_phase_shift(records, empty)
        for r in empty:
            self.r.repair("HDR.PHASESHIFT.EMPTY", "empty SYS / PHASE SHIFT record (no system, code or "
                          "satellites) left out: it records nothing, so the phase alignment reads as "
                          "not recorded (rinex302.txt Table A2)", r.lineno)
        for e in entries:
            if e[6] is not None:
                self.r.repair("HDR.PHASESHIFT.CODE", f"SYS / PHASE SHIFT code {e[6]!r} read as {e[1]} "
                              "(the record holds carrier phase codes only, rinex305.txt p.57)",
                              e[5][0].lineno)
        return entries

    def _carry_phase(self, entries):
        """Same family: carry what the source recorded, renaming codes the target version
        spells differently (BDS B1I band) and dropping entries the target cannot hold.
        Nothing is synthesised (PLAN §3.3 rule 1). Also used for the records of events."""
        sv, tv = self.src.version, self.target
        out = []
        for e in entries:
            s = e[0]
            if s not in self.systems:
                continue
            if not e[1]:
                out.extend(e[5])
                continue
            code, why = codemap.gate_v3(s, e[1], sv, tv) if len(e[1]) == 3 else (None, None)
            if code is None and tv == sv and not e[6]:
                out.extend(e[5])          # the source's own entry, carried as written
                self.r.warn("OBS.PHASESHIFT.NONSTANDARD", f"SYS / PHASE SHIFT entry {s} {e[1]} uses "
                            f"a code RINEX {tv} does not define; carried verbatim")
                continue
            if code is None:
                if e[2] not in (None, Decimal(0)):
                    self.r.loss(f"phase-shift-entry-dropped:{s}:{e[1]}", 1)
                continue
            if code == e[1] and not e[6]:
                out.extend(e[5])
            else:
                out.extend(_phase_lines(s, code, e[2], e[3]))
                if code != e[1]:
                    self.r.rule(why or "OBS.PHASESHIFT.RENAMED")
        return out

    def _phase_from_state(self, entries, systems, state, assume=None):
        """Another family (RINEX 2/3.00 or 4 source): records from the alignment state.
        assume=False ignores --assume-phase-aligned (the same-family fallback)."""
        sv, tv = self.src.version, self.target
        assume = self.opts.assume_phase_aligned if assume is None else assume
        out = []
        for s in systems:
            st = state.get(s, "unknown")
            phase_codes = self._phase_codes(s)
            if st == "recorded":
                for e in entries:
                    if e[0] != s:
                        continue
                    if not e[1]:
                        continue
                    code, why = codemap.gate_v3(s, e[1], sv, tv) if len(e[1]) == 3 else (None, None)
                    if code is None or code not in phase_codes:
                        if e[2] not in (None, Decimal(0)):
                            self.r.loss(f"phase-shift-entry-dropped:{s}:{e[1]}", 1)
                        continue
                    out.extend(_phase_lines(s, code, e[2], e[3]))
            elif st == "aligned" or (st == "unknown" and assume and self._has_phase(s)):
                if st == "unknown":
                    self.r.assume("phase-alignment", s, "override:--assume-phase-aligned")
                else:
                    self.r.rule("OBS.V4V3.PHASE-ZERO-FORM")
                for c in phase_codes:
                    out.extend(_phase_lines(s, c, Decimal(0), []))
            else:
                if self._has_phase(s):
                    self.r.assume("phase-alignment", f"{s}:unknown", "spec-unknown-form")
                    if tv >= "3.03":
                        self.r.warn("OBS.PHASE-UNKNOWN", f"phase alignment of {s} unknown: written as a "
                                    "fully blank SYS / PHASE SHIFT (rinex305.txt §5.2.12 says such data "
                                    "should not be published)")
                out.append(HeaderRecord("SYS / PHASE SHIFT", s))
        if not out and systems:
            # no phase type anywhere (a code-only RINEX 4 file): the record is mandatory from
            # 3.01 and every form names a system; the system-only form claims nothing about
            # phases the file does not have
            self.r.rule("OBS.PHASESHIFT.NO-PHASE-TYPES")
            out = [HeaderRecord("SYS / PHASE SHIFT", s) for s in systems]
        return out

    def _phase_codes(self, s):
        """Phase codes of system s in the target's type lists: the header's first, then those
        a flag-4 list adds. The header record stays valid until an additional header record
        changes it (rinex305.txt §6.5 p.41), so it covers codes a later list introduces."""
        out = [c for c in self.final_types.codes(s) if c[0] == "L"]
        for st in self.tstates.values():
            out += [c for c in st.codes(s) if c[0] == "L" and c not in out]
        return out

    def _has_phase(self, s):
        """System s has a phase type in any obs-type list of the file (header or flag 4)."""
        return any(c[0] == "L" for st in self.tstates.values() for c in st.codes(s))

    def glonass_records(self):
        """GLONASS SLOT / FRQ # (3.02+) and GLONASS COD/PHS/BIS (3.02-3.05; deprecated in 4)."""
        tv = self.target
        has_r = "R" in self.out_systems() and "R" in self.systems
        src_slot = [r for r in self.own_header if r.label == "GLONASS SLOT / FRQ #"]
        src_cpb = next((r for r in self.own_header if r.label == "GLONASS COD/PHS/BIS"), None)
        out = []
        if tv == "3.01" and has_r:
            # optional in 3.01 (rinex301.txt p.32): carried when the source has it, not made up
            out.extend(src_slot)
            if src_cpb is not None and src_cpb.content.strip():
                self.r.loss("header-record-not-representable:GLONASS COD/PHS/BIS", 1)
            return out
        if tv < "3.02" or not has_r:
            if src_slot and not has_r:
                pass
            elif src_slot:
                self.r.loss("header-record-not-representable:GLONASS SLOT / FRQ #", 1)
            if src_cpb is not None and src_cpb.content.strip() and has_r:
                self.r.loss("header-record-not-representable:GLONASS COD/PHS/BIS", 1)
            return out
        src_fcn = parse_glonass_slots(src_slot)
        observed = sorted(x for x in self.present_sats() if x[0] == "R")
        # a flag-4 event may give channels of satellites the header's record lacks (rinex305.txt
        # section 6.5: header records in events hold from there on): the file's own channels,
        # written into the header's record (Sol round 22: refused for want of a channel), for
        # satellites first observed after that event (the survey keeps only those; one
        # observed before needs a companion: Sol round 23); the first event's channel wins
        # (not in a file whose version does not define the record: foreign, as in the header)
        ev_fcn = {}
        if not self.foreign("GLONASS SLOT / FRQ #"):
            for s, k in self.event_slots:
                if s not in src_fcn and s not in ev_fcn:
                    ev_fcn[s] = k
        if ev_fcn:
            src_fcn = {**src_fcn, **ev_fcn}
        missing = [s for s in observed if s not in src_fcn]
        if not missing and src_slot and (not ev_fcn or tv == self.src.version):
            out.extend(src_slot)          # (the file's own version: carried as written)
        else:
            if ev_fcn:
                self.r.rule("OBS.GLONASS-SLOTS-FROM-EVENTS")
            fcn = dict(src_fcn)
            comp = self.opts.glo_fcn or {}
            for s in missing:
                if s in comp:
                    fcn[s] = comp[s]
            still = [s for s in observed if s not in fcn]
            if still and src_slot and self.src.version >= "3.02":
                # the source already broke its own mandatory record: carry what it says
                self.r.warn("OBS.GLONASS-SLOTS-INCOMPLETE", "GLONASS SLOT / FRQ # of the source "
                            f"lacks {', '.join(still)}; carried as it is")
                still = []
            if still:
                # caller decides between refusing and --drop-unresolvable
                raise MissingInformationError(
                    f"RINEX {tv} needs GLONASS SLOT / FRQ # (mandatory from 3.02 when GLONASS is "
                    f"present) but no source gives the frequency channel of {', '.join(still)}; "
                    "pass --nav with a GLONASS navigation file of the same day, or --glo-fcn",
                    missing="glonass-fcn:" + ",".join(still))
            for s in missing:
                if s in fcn:
                    self.r.assume("glonass-fcn", f"{s}={fcn[s]}", self.opts.glo_fcn_source or "companion")
            out.extend(format_glonass_slots(fcn))
        if tv < "4":
            if src_cpb is not None:
                out.append(src_cpb)
            else:
                out.append(HeaderRecord("GLONASS COD/PHS/BIS", ""))
                self.r.assume("glonass-cod-phs-bis", "unknown", "spec-unknown-form")
        else:
            if src_cpb is not None and (self.src.version >= "4" or _cpb_known_nonzero(src_cpb)):
                out.append(src_cpb)
        return out

    def scale_records(self):
        if self.tlayout == "v2":
            if parse_scale_factors(self.own_header):
                self.r.rule("OBS.V3V2.SCALE-APPLIED")
            return []
        return self._scale_for(self.own_header, self.src.types.key)

    def _scale_for(self, records, sid):
        """SYS / SCALE FACTOR records for a v3/v4 target: codes renamed as the data were
        (e.g. BeiDou B1I band), codes and systems the target lost dropped. The records are
        kept verbatim when nothing changes (rinex305.txt Table A2: factor per code)."""
        src = [r for r in records if r.label == "SYS / SCALE FACTOR"]
        if not src:
            return []
        groups = []
        for s, fac, codes in parse_scale_groups(src):
            if s not in self.systems:
                groups.append(None)
                continue
            cmap = self.code_of.get((sid, s), {})
            tgt = self.tstates[sid].codes(s)
            if not codes:
                groups.append((s, fac, []))
                continue
            new = [cmap[c] for c in codes if c in cmap and cmap[c] in tgt]
            groups.append((s, fac, new) if new else None)
        same = all(g is not None for g in groups) and [
            (s, fac, codes) for s, fac, codes in parse_scale_groups(src)] == groups
        if same:
            return src
        self.r.rule("OBS.SCALE-FACTOR.REMAPPED")
        out = []
        for g in groups:
            if g is not None:
                out.extend(format_scale(*g))
        return out

    def build_header(self):
        tst = self.final_types
        r = self.r
        tlay = self.tlayout
        generated = {}
        generated["RINEX VERSION / TYPE"] = [self.version_record()]
        generated["OBS TYPES"] = self.types_records(tst)
        times = self.time_records()
        generated["TIME OF FIRST OBS"] = [times["TIME OF FIRST OBS"]] if "TIME OF FIRST OBS" in times else []
        generated["TIME OF LAST OBS"] = [times["TIME OF LAST OBS"]] if "TIME OF LAST OBS" in times else []
        iv = self.interval_record()
        generated["INTERVAL"] = [iv] if iv is not None else []
        lp = self.leap_record()
        generated["LEAP SECONDS"] = [lp] if lp is not None else []
        if tlay == "v3":
            ps = self.phase_records()
            if ps:
                lab = obsheader.label_text(self.target, "SYS / PHASE SHIFT")
                ps = [HeaderRecord(lab, x.content, x.lineno) for x in ps]
            generated["SYS / PHASE SHIFT"] = ps
        else:
            self.phase_records()
            generated["SYS / PHASE SHIFT"] = []
        glo = self.glonass_records()
        generated["GLONASS"] = [x for x in glo if x.label == "GLONASS SLOT / FRQ #"]
        generated["GLONASS CPB"] = [x for x in glo if x.label == "GLONASS COD/PHS/BIS"]
        generated["SYS / SCALE FACTOR"] = self.scale_records()
        src_has_counts = (self.src.first("PRN / # OF OBS") is not None
                          or self.src.first("# OF SATELLITES") is not None)
        generated["COUNTS"] = self.count_records() if src_has_counts else []
        if src_has_counts and self._check_counts(generated["COUNTS"]) and self.tlayout == self.slayout \
                and self._same_columns():
            # numerically equal and the same columns: keep the source's own formatting (blank
            # vs 0). The comparison ignores trailing zero counts, so a dropped type whose counts
            # were all 0 would otherwise keep its column.
            generated["COUNTS"] = [x for x in self.src.header
                                   if x.label in ("# OF SATELLITES", "PRN / # OF OBS")]

        slot_of = {
            "RINEX VERSION / TYPE": "RINEX VERSION / TYPE",
            "# / TYPES OF OBSERV": "OBS TYPES", "SYS / # / OBS TYPES": "OBS TYPES",
            "TIME OF FIRST OBS": "TIME OF FIRST OBS", "TIME OF LAST OBS": "TIME OF LAST OBS",
            "INTERVAL": "INTERVAL", "LEAP SECONDS": "LEAP SECONDS",
            "SYS / PHASE SHIFT": "SYS / PHASE SHIFT", "SYS / PHASE SHIFTS": "SYS / PHASE SHIFT",
            "GLONASS SLOT / FRQ #": "GLONASS", "GLONASS COD/PHS/BIS": "GLONASS CPB",
            "SYS / SCALE FACTOR": "SYS / SCALE FACTOR",
            "# OF SATELLITES": "COUNTS", "PRN / # OF OBS": "COUNTS",
        }
        out = []
        placed = set()
        for rec in self.src.header:
            lab = rec.label
            if self.foreign(lab):
                if self._foreign_record(rec):
                    out.append(rec)
                continue
            if lab == "SYS / PHASE SHIFTS" and self.src.version != "3.01":
                r.repair("HDR.PHASESHIFT.LABEL", "label SYS / PHASE SHIFTS (the 3.01 spelling) read "
                         "as SYS / PHASE SHIFT", rec.lineno)
            slot = slot_of.get(lab)
            if slot is not None:
                if slot not in placed:
                    out.extend(generated[slot])
                    placed.add(slot)
                continue
            if lab == "WAVELENGTH FACT L1/2":
                if tlay == "v2" and self.slayout == "v2":
                    out.append(rec)
                elif tlay == "v3" and self.slayout == "v3":
                    out.append(rec)          # non-standard in v3: carried verbatim
                    r.rule("OBS.HDR.NONSTANDARD-CARRIED")
                elif tlay == "v3":
                    r.rule("OBS.V2V3.WAVELENGTH-RECORD-DROPPED")
                continue
            if lab in COMMON:
                out.append(rec)
                continue
            if lab in V3_ONLY or lab in V4_ONLY:
                if lab == "ANTENNA: PHASECENTER" and tlay == "v3" and self.slayout == "v3":
                    pc = self._phasecenter(rec)
                    if pc is not None:
                        out.append(pc)
                elif lab in V3_ONLY and tlay == "v3":
                    kept = self._filter_sys_record(rec)
                    if kept is not None:
                        out.append(kept)
                elif lab in V4_ONLY and self.target >= "4":
                    out.append(rec)
                elif self.target == self.src.version:
                    # a record another version defines, in the source's own version (e.g. DOI
                    # in a 3.05 file): carried as written, as non-standard codes are
                    out.append(rec)
                    r.rule("OBS.HDR.NONSTANDARD-CARRIED")
                else:
                    r.loss(f"header-record-not-representable:{lab}", 1)
                continue
            # unknown / non-standard label: verbatim
            out.append(rec)
            r.rule("OBS.HDR.NONSTANDARD-CARRIED")
        # APPROX POSITION XYZ is mandatory in RINEX 2 (rinex211.txt Table A1, no "optional"
        # mark) but optional for moving platforms from 3.00: a RINEX 3/4 file without one has
        # no value to carry. Clause 8: the user gives it (--approx-position) or we stop.
        # --approx-position-zero writes teqc's 0 0 0 instead: the spec gives zeros no meaning,
        # so it is a placeholder, reported as one (the user's choice, 2026-10-31).
        if tlay == "v2" and self.slayout == "v3" and self.src.first("APPROX POSITION XYZ") is None:
            xyz = self.opts.approx_position
            if xyz is None and not self.opts.approx_position_zero:
                raise MissingInformationError(
                    f"RINEX {self.target} needs APPROX POSITION XYZ (mandatory in RINEX 2) but the "
                    "input has none (allowed in RINEX 3/4 for moving platforms); pass "
                    "--approx-position X Y Z (WGS84, metres), or --approx-position-zero for "
                    "teqc's 0 0 0 placeholder", missing="approx-position")
            rec = HeaderRecord("APPROX POSITION XYZ", "".join(fmt_f(Decimal(str(v)), 14, 4)
                                                              for v in xyz or (0, 0, 0)))
            _insert_canon(out, rec)
            if xyz is not None:
                r.assume("approx-position", rec.content.strip(), "user")
            else:
                r.assume("approx-position", "0 0 0 (unknown)", "teqc-convention")
                r.warn("OBS.APPROX-POSITION-ZERO", "APPROX POSITION XYZ written as 0 0 0: the input "
                       "has no position, and zeros are a placeholder (teqc's), not a position")
        # RINEX 2: WAVELENGTH FACT L1/2 is mandatory in 2.10 and optional in 2.11
        # (rinex210.txt / rinex211.txt Table A1). From RINEX 3 the default (full cycles) is
        # written, since RINEX 3 LLI bit 1 already flags half-cycle epochs.
        if tlay == "v2" and self.slayout == "v3":
            generated["WAVELENGTH"] = [HeaderRecord("WAVELENGTH FACT L1/2", "     1     1")]
            r.rule("OBS.V3V2.WAVELENGTH-DEFAULT")
        # mandatory or generated records the source did not have
        for slot in ("RINEX VERSION / TYPE", "OBS TYPES", "TIME OF FIRST OBS", "SYS / PHASE SHIFT",
                     "GLONASS", "GLONASS CPB", "WAVELENGTH"):
            if slot not in placed and generated.get(slot):
                for g in generated[slot]:
                    _insert_canon(out, g)
                placed.add(slot)
        out = [x for x in out if x is not None]
        return out

    def _check_counts(self, recs):
        """Report a repair when the source's # OF SATELLITES / PRN / # OF OBS disagree with the
        source's own data, counted in its own type list (Sol round 20: they were compared with
        the output's, so a type the target cannot hold looked like a wrong count and --strict
        refused a valid file). True when they equal the output's (recs), so the source's
        records can be kept as written."""
        src = [x for x in self.src.header if x.label in ("# OF SATELLITES", "PRN / # OF OBS")]
        # for every target: a wrong source count is a repair whatever the output's layout
        # (Sonnet round 21: RINEX 3 -> 2 corrected it unreported)
        if src and not _counts_agree(src, self._source_count_records()):
            self.r.repair("HDR.COUNTS", "# OF SATELLITES / PRN / # OF OBS recomputed from the data: "
                          "every satellite of the data (flags 0, 1 and 6), observations counted in "
                          "flag 0/1 epochs (rinex305.txt Table A2: 'number of observations')")
        return _count_table(src) == _count_table(recs)

    def _source_count_records(self):
        """# OF SATELLITES / PRN / # OF OBS of the source's own data, in the source header's
        type list (as count_records counts the output's)."""
        counts = {}
        for (sid, sat), c in self.counts.items():
            codes = _occurrences(self.states[sid].codes(sat[0]))
            d = counts.setdefault(sat, {})
            for k, n in enumerate(c):
                if n and k < len(codes):
                    d[codes[k]] = d.get(codes[k], 0) + n
        for sats in self.sat_seen.values():
            for sat in sats:
                counts.setdefault(sat, {})
        out = [HeaderRecord("# OF SATELLITES", f"{len(counts):6d}")]
        saturate = self.src.version >= "3.01"
        for sat in sorted(counts):
            vals = [counts[sat].get(c, 0) for c in _occurrences(self.src.types.codes(sat[0]))]
            if saturate:
                vals = [min(99999, v) for v in vals]
            for k in range(0, max(1, len(vals)), 9):
                head = f"   {sat}" if k == 0 else " " * 6
                out.append(HeaderRecord("PRN / # OF OBS", head + "".join(f"{v:6d}" for v in vals[k:k + 9])))
        return out

    def _same_columns(self):
        """Every output system has as many observation types as in the source."""
        src, out = self.src.types, self.final_types
        if out.layout == "v2" or src.layout == "v2":
            return out.layout == src.layout and len(out.v2) == len(src.v2)
        return all(len(out.codes(s)) == len(src.codes(s)) for s in out.sys)

    def _holds(self, s):
        """The output holds system s: kept, with target types in some type list."""
        return s in self.systems and any(st.codes(s) for st in self.tstates.values())

    def _filter_sys_record(self, rec):
        """SYS / DCBS APPLIED and SYS / PCVS APPLIED name a system (A1,1X,A17,1X,A40:
        rinex305.txt Table A2; 3.00 allows G/R/E/S: rinex300.txt Table A1 p.29): one of a
        system the output does not hold has no room and is claimed (Sol round 21: a BeiDou
        record stayed in 3.00). Other records pass."""
        if rec.label not in ("SYS / DCBS APPLIED", "SYS / PCVS APPLIED"):
            return rec
        s = rec.content[:1]
        if s.strip() and not self._holds(s) and self.target != self.src.version:
            self.r.loss(f"sys-record-not-representable:{s}:{rec.label}", 1)
            return None
        return rec

    def _phasecenter(self, rec):
        """ANTENNA: PHASECENTER names a system and an observation code (A1,1X,A3,F9.4,2F14.4:
        rinex305.txt Table A2 p.53): the code is renamed as the data's are (BDS B1I is band 1 in
        3.02, band 2 from 3.03: Sol round 20, a 3.02 'C L1X' kept in 3.05 named B1C); one the
        target cannot hold, or of a system it drops, is claimed. Carried as written to the
        file's own version."""
        c = rec.content.ljust(60)
        s, code = c[0], c[2:5]
        if self.target == self.src.version:
            return rec
        g = None
        if self._holds(s):
            g, why = codemap.gate_v3(s, code, self.src.version, self.target)
        if g is None:
            self.r.loss(f"antenna-phasecenter-code-not-representable:{s}:{code}", 1)
            return None
        if g != code:
            self.r.rule(why or "OBS.HDR.PHASECENTER-RENAMED")
            return HeaderRecord(rec.label, c[:2] + g + c[5:60].rstrip(), rec.lineno)
        return rec

    # -- run ---------------------------------------------------------------------
    def run(self):
        self.survey()
        self.choose_systems()
        snap = self.r.snapshot()          # the drop-unresolvable retry starts from here
        self.build_target_states()
        self._types_left()
        try:
            self.final_types = self._header_types()
            header = self.build_header()
        except MissingInformationError as e:
            if self.opts.drop_unresolvable and e.missing and e.missing.startswith("glonass-fcn") \
                    and "R" in self.systems:
                self.r.restore(snap)          # the first attempt's entries would count twice
                self.r.loss("system-removed-unresolvable:R", self.nrec.get("R", 0), missing=e.missing)
                self.r.outcome_removal = True
                self.systems = [s for s in self.systems if s != "R"]
                if not self.systems:
                    # (was a CorruptError 'no SYS / # / OBS TYPES record' from the output check:
                    # Sonnet round 24)
                    raise NotRepresentableError(
                        f"--drop-unresolvable would remove GLONASS, the only system of this file "
                        f"({e}); nothing to write") from None
                self.build_target_states()
                self.final_types = self._header_types()
                header = self.build_header()
            else:
                raise
        out = ObsFile()
        out.version = self.target
        out.version_str = self.target
        out.header = header
        out.types = self.final_types
        out._epochs = None
        out._gen = self.convert_epochs()        # pass 2 runs as the writer consumes it
        out.eol = self.src.eol
        out.out_systems = self.out_systems()
        kt = self.kept_times()
        out.first_time = _add_seconds(kt[0], self.time_shift) if kt else None
        return out

    def _header_types(self):
        """The target obs-type list of the output header: the header's own, unless none of
        its types exists in the target (e.g. only 'X1 ', or 2.11 C2/C5 to 2.10), replaced by
        a flag-4 list; then the first list that holds data (else the first with a type),
        which the following event declares again. Records under the header's own list then
        have no target column and are left out, their values claimed (convert_epochs). An
        empty header list is not a valid file (VAL.HDR.OBSTYPES.COUNT; it used to be written
        when data epochs used it: an AssertionError, round 22)."""
        own = self.tstates[self.src.types.key]

        def has(st):
            return bool(st.v2) if self.tlayout == "v2" else any(st.sys.get(s) for s in self.systems)
        if has(own):
            return own
        for want_data in (True, False):
            for sid, st in self.tstates.items():
                if has(st) and (sid in self._data_sids or not want_data):
                    self.r.rule("OBS.HDR.TYPES-FROM-FIRST-DATA-LIST")
                    return st
        return own

    def _types_left(self):
        """Refuse when no observation type of the file exists in the target: over every
        obs-type list (header and flag 4), since a list may be replaced before any data."""
        has_src = any(st.codes(s) for st in self.states.values() for s in self.data_systems or self.systems)
        if self.tlayout == "v2":
            empty = not any(st.v2 for st in self.tstates.values())
        else:
            empty = not any(st.sys.get(s) for st in self.tstates.values() for s in self.systems)
        if has_src and empty:
            raise NotRepresentableError(
                f"none of this file's observation types has a RINEX {self.target} code; "
                "nothing to write")

    def _merge_header_types(self):
        """The header's obs types: those of the header state (pass 2 of the plan)."""
        return self.tstates[self.src.types.key]


# ---------------------------------------------------------------------------
# helpers shared with the validator
# ---------------------------------------------------------------------------

TIME_SYSTEMS = {"GPS", "GLO", "GAL", "BDT", "QZS", "IRN", "UTC", "TAI"}
_CLEAR_B2 = {"4": "0", "5": "1", "6": "2", "7": "3"}


def lli_bit2_meaning(version):
    """LLI bit 2: 'observation under anti-spoofing' in RINEX 2 (rinex211.txt Table A2),
    undefined in 3.00 (rinex300.txt ~1970), 'BOC tracking of an MBOC-modulated signal' from
    3.01 (rinex301.txt ~2227; rinex305.txt §6.7)."""
    if version < "3":
        return "anti-spoofing"
    if version < "3.01":
        return None
    return "boc-tracking"


def parse_scale_groups(records):
    """[(sys, factor, [codes] or [] for all)] in record order (A1,1X,I4,2X,I2,12(1X,A3);
    continuation 10X,12(1X,A3): rinex305.txt Table A2)."""
    out = []
    for r in records:
        if r.label != "SYS / SCALE FACTOR":
            continue
        c = r.content.ljust(60)
        if c[0:1].strip():
            try:
                fac = Decimal(c[2:6].strip() or "1")
            except ArithmeticError:
                raise CorruptError("bad SYS / SCALE FACTOR", line=r.lineno, rule="HDR.SCALE") from None
            out.append((c[0:1], fac, _a3_codes(c[10:60])))
        elif out:
            out[-1][2].extend(_a3_codes(c[10:60]))
    return out


def _a3_codes(text):
    """Observation codes of a record's 1X,A3 fields, as the type lists read them
    (rinexcore.obs._v3_codes): a code with a blank attribute ('L1 ', 3.00/3.01) stays three
    characters, so it matches its type (Sol round 12: split codes never matched it)."""
    return [x if len(x) == 3 else x.ljust(3) if len(x) == 2 else x for x in text.split()]


def format_scale(s, fac, codes):
    out = []
    head = f"{s} {int(fac):4d}  {len(codes):2d}" if codes else f"{s} {int(fac):4d}"
    if not codes:
        return [HeaderRecord("SYS / SCALE FACTOR", head)]
    for k in range(0, len(codes), 12):
        chunk = codes[k:k + 12]
        out.append(HeaderRecord("SYS / SCALE FACTOR", (head if k == 0 else " " * 10)
                                + "".join(f" {c}" for c in chunk)))
    return out


def update_wavelength(facs, records):
    """Apply WAVELENGTH FACT L1/2 records (format 2I6,I6,7(3X,A1,I2), rinex211.txt Table A1)
    to {sat or '*': (f1, f2)}: a record without satellites sets the default."""
    for r in records:
        if r.label != "WAVELENGTH FACT L1/2":
            continue
        c = r.content.ljust(60)
        try:
            f1 = int(c[0:6]) if c[0:6].strip() else 1
            f2 = int(c[6:12]) if c[6:12].strip() else 0
            n = int(c[12:18]) if c[12:18].strip() else 0
        except ValueError:
            raise CorruptError("bad WAVELENGTH FACT L1/2 record", line=r.lineno,
                               rule="HDR.WAVELENGTH") from None
        if n == 0:
            facs["*"] = (f1, f2)
            continue
        for k in range(min(n, 7)):
            item = c[18 + 6 * k + 3:18 + 6 * k + 6]
            if not item.strip():
                continue
            sysc = item[0] if item[0] != " " else "G"
            try:
                facs[f"{sysc}{int(item[1:3]):02d}"] = (f1, f2)
            except ValueError:
                raise CorruptError(f"bad satellite {item!r} in WAVELENGTH FACT L1/2", line=r.lineno,
                                   rule="HDR.WAVELENGTH") from None


def _tdiff(a, b):
    """b - a in seconds (Decimal), calendar arithmetic without floats."""
    import datetime
    da = datetime.datetime(a[0], a[1], a[2], a[3], a[4])
    db = datetime.datetime(b[0], b[1], b[2], b[3], b[4])
    return Decimal(int((db - da).total_seconds())) + (b[5] - a[5])


def _parse_time_rec(r):
    c = r.content
    try:
        return (int(c[0:6]), int(c[6:12]), int(c[12:18]), int(c[18:24]), int(c[24:30]),
                Decimal(c[30:43].strip()))
    except (ValueError, ArithmeticError):
        return None


def _counts_agree(src, data):
    """The source's count records agree with counts of its data, for the records it has: both
    are optional (rinex305.txt Table A2), so a file with # OF SATELLITES alone is checked on
    that alone (Sol round 21: the missing PRN / # OF OBS read as wrong counts)."""
    (n_src, rows_src), (n_data, rows_data) = _count_table(src), _count_table(data)
    has_n = any(r.label == "# OF SATELLITES" for r in src)
    has_rows = any(r.label == "PRN / # OF OBS" for r in src)
    return (not has_n or n_src == n_data) and (not has_rows or rows_src == rows_data)


def _count_table(recs):
    """# OF SATELLITES / PRN / # OF OBS as numbers (blank count = 0), trailing zeros dropped."""
    nsat = None
    rows = []
    for r in recs:
        c = r.content.ljust(60)
        if r.label == "# OF SATELLITES":
            nsat = int(c[0:6]) if c[0:6].strip() else 0
            continue
        sat = c[3:6]
        vals = [int(c[6 + 6 * k:12 + 6 * k]) if c[6 + 6 * k:12 + 6 * k].strip() else 0
                for k in range(9)]
        if sat.strip():
            rows.append([f"{sat[0]}{int(sat[1:]):02d}", vals])
        elif rows:
            rows[-1][1].extend(vals)
    out = []
    for sat, v in rows:
        while v and v[-1] == 0:
            v.pop()
        out.append((sat, tuple(v)))
    return nsat, sorted(out)              # (a file may list its satellites in any order)


def _occurrences(codes):
    """[(code, n)] where n counts earlier columns of the same code: counts merge across
    obs-type lists by code, and a code listed twice keeps its columns apart."""
    seen = {}
    out = []
    for c in codes:
        out.append((c, seen.get(c, 0)))
        seen[c] = seen.get(c, 0) + 1
    return out


def parse_phase_shift(header, empty=None):
    """[(sys, code, Decimal|None, [sats], content, [records], raw code or None)] from
    SYS / PHASE SHIFT(S). The last item is set when a code was written without its type
    letter ('1C' for L1C, as some receiver exports do): the record holds carrier phase codes
    only (rinex305.txt p.57), so the meaning is unambiguous; the caller reports the repair.
    A wholly blank record (no system, code or satellites; CMUM00THA, JAXA dconv) records
    nothing: every form the spec defines starts with the system (rinex302.txt Table A2 and
    p.41-42, where even 'unknown' names it), and a continuation line lists satellites. It is
    left out and appended to `empty`, for the caller to report the repair."""
    out = []
    cur = None
    for r in header:
        if r.label not in ("SYS / PHASE SHIFT", "SYS / PHASE SHIFTS"):
            continue
        c = r.content.ljust(60)
        if not c[:60].strip():
            if empty is not None:
                empty.append(r)
            continue
        if c[0:1].strip():
            s = c[0:1].upper()
            code = c[2:5].strip()
            if len(code) == 2 and code[0] == "L" and c[4:5] == " ":
                code = code + " "             # 'L1 ': blank attribute (3.00/3.01), A3 as in the type list
            raw = None
            if len(code) == 2 and code[0].isdigit() and code[1].isalpha():
                raw, code = code, "L" + code
            val = c[6:14].strip()
            try:
                v = Decimal(val) if val else None
            except ArithmeticError:
                raise CorruptError(f"bad SYS / PHASE SHIFT value {val!r}", line=r.lineno,
                                   rule="HDR.PHASESHIFT") from None
            sats = c[18:60].split()
            cur = [s, code, v, sats, r.content, [r], raw]
            out.append(cur)
        elif cur is not None:
            cur[3].extend(c[18:60].split())
            cur[5].append(r)
        else:
            raise CorruptError("SYS / PHASE SHIFT continuation without a first line",
                               line=r.lineno, rule="HDR.PHASESHIFT")
    return [tuple(e) for e in out]


def _phase_lines(s, code, value, sats):
    val = fmt_f(value, 8, 5) if value is not None else " " * 8
    if not sats:
        return [HeaderRecord("SYS / PHASE SHIFT", f"{s} {code} {val}")]
    out = []
    for k in range(0, len(sats), 10):
        chunk = sats[k:k + 10]
        if k == 0:
            head = f"{s} {code} {val}  {len(sats):02d}"
        else:
            head = " " * 18
        out.append(HeaderRecord("SYS / PHASE SHIFT", head + "".join(f" {x}" for x in chunk)))
    return out


def parse_glonass_slots(records):
    """{'R01': fcn} from GLONASS SLOT / FRQ # records (format I3,1X,8(A1,I2.2,1X,I2,1X):
    rinex305.txt Table A2). Each entry must sit in its columns: an event's record is not
    checked by the validator, and one a column off read 'R02-4' as channel +4 (round 25)."""
    out = {}
    for r in records:
        c = r.content.ljust(60)
        for k in range(8):
            item = c[4 + 7 * k:4 + 7 * k + 7]
            if not item.strip():
                continue
            sat, sep, fr, end = item[0:3], item[3], item[4:6], item[6]
            num = sat[1:3].strip()
            if sat[0] != "R" or not num.isdigit() or sep != " " or end != " " \
                    or not re.fullmatch(r" ?-?\d|-?\d\d", fr):
                raise CorruptError(f"bad GLONASS SLOT / FRQ # entry {item!r} (A1,I2.2,1X,I2,1X)",
                                   line=r.lineno, rule="HDR.GLOSLOT")
            out[f"R{int(num):02d}"] = int(fr)
    return out


def format_glonass_slots(fcn):
    sats = sorted(fcn)
    out = []
    for k in range(0, max(1, len(sats)), 8):
        chunk = sats[k:k + 8]
        head = f"{len(sats):3d} " if k == 0 else " " * 4
        out.append(HeaderRecord("GLONASS SLOT / FRQ #",
                                head + "".join(f"{s} {fcn[s]:2d} " for s in chunk)))
    return out


def _cpb_known_nonzero(r):
    vals = []
    c = r.content.ljust(60)
    for k in range(4):
        v = c[k * 13 + 5:k * 13 + 13].strip()
        if v:
            try:
                vals.append(Decimal(v))
            except ArithmeticError:
                return True
    return any(v != 0 for v in vals)


def merge_scale(scale, new):
    """The factors after an event's SYS / SCALE FACTOR: a factor for every type of a system
    replaces that system's factors; one for listed types changes only those ('each value
    remains valid until changed by an additional header record', rinex305.txt §6.5)."""
    scale = dict(scale or {})
    for (s, code), fac in new.items():
        if code == "*":
            for k in [k for k in scale if k[0] == s]:
                del scale[k]
        scale[(s, code)] = fac
    return scale


def parse_scale_factors(header):
    """{(sys, code or '*'): Decimal factor} from SYS / SCALE FACTOR."""
    out = {}
    cur = None
    for r in header:
        if r.label != "SYS / SCALE FACTOR":
            continue
        c = r.content.ljust(60)
        if c[0:1].strip():
            s = c[0:1]
            try:
                fac = Decimal(c[2:6].strip() or "1")
            except ArithmeticError:
                raise CorruptError("bad SYS / SCALE FACTOR", line=r.lineno, rule="HDR.SCALE") from None
            codes = _a3_codes(c[10:60])
            cur = (s, fac)
            if not codes:
                out[(s, "*")] = fac
            for code in codes:
                out[(s, code)] = fac
        elif cur is not None:
            for code in _a3_codes(c[10:60]):
                out[(cur[0], code)] = cur[1]
    return out


def _insert_canon(out, rec):
    k = _CANON_IDX.get(rec.label, len(CANON))
    pos = len(out)
    for i, x in enumerate(out):
        if x is None:
            continue
        if _CANON_IDX.get(x.label, -1) > k:
            pos = i
            break
    out.insert(pos, rec)
