"""Conversion engine: load -> convert -> write -> validate, with the run outcome.

Every call ends in one of the four outcomes of PLAN §1 clause 1; refusals are
RinexError subclasses. Invocation/I-O failures raise InvocationError and are
never reported as refused-corrupt.
"""

import contextlib
import dataclasses
import hashlib
import os
import re
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from rinexcore import names
from rinexcore.errors import (CONVERTED, CONVERTED_WITH_REMOVAL, CorruptError, InvocationError,
                              NotRepresentableError, RinexError)
from rinexcore.io import compress
from rinexcore.io.hatanaka import CrxCannotHold
from rinexcore.met import read_met, write_met
from rinexcore.nav import read_nav, write_nav
from rinexcore.obs import iter_obs_lines, read_obs_payload
from rinexcore.rinexfile import (eol_of, first_line, join_lines, open_container, read_path, sniff,
                                  split_lines)

from . import companion
from .metconv import convert_met
from .navconv import NavOptions, convert_nav
from .obsconv import Crx1EventError, ObsOptions, convert_obs, presurvey
from .report import Report

# warnings that describe the input being off spec (refused under --strict)
STRICT_WARNINGS = {"OBS.NONSTANDARD-CODE", "OBS.GLONASS-SLOTS-INCOMPLETE", "OBS.PHASESHIFT.NONSTANDARD",
                   "NAV.HDR.TIMECORR.LAYOUT", "NAV.GLO.TK-DAY-BASIS", "OBS.CLOCK.NOT-F12.9"}
WRITE_VERSIONS = ("2.10", "2.11", "3.00", "3.01", "3.02", "3.03", "3.04", "3.05", "4.00", "4.01", "4.02")
READ_VERSIONS = ("2.00", "2.01", "2.10", "2.11", "2.12") + WRITE_VERSIONS[2:]


@dataclass
class Options:
    target: str
    lenient: bool = False
    strict: bool = False
    nav: list = field(default_factory=list)          # companion nav files (GLONASS channels)
    glo_fcn: str = None                              # nav file, RINEX >= 3.02 obs, or 'R01 1' table
    overrides: dict = field(default_factory=dict)
    drop_unresolvable: bool = False
    assume_phase_aligned: bool = False
    align_phases: bool = False                       # PLAN 3.3 rules 2/3: 3.00, 3.02-3.05 targets
    dedupe: bool = False
    crx: bool = None                                 # None: keep the input's Hatanaka state
    compression: str = "keep"                        # keep | none | gz | Z
    eol: str = "lf"
    keep_v2_nonstandard: bool = False
    keep_lli_bit2: bool = False
    leap_seconds: int = None
    approx_position: tuple = None
    approx_position_zero: bool = False               # teqc's 0 0 0 placeholder (reported)
    qzss_ion_area: str = None                        # WIDE | JAPN: QZSS ION sets without an area, to 4.00/4.01
    auto_nav: bool = True                           # CLI: same-day GLONASS nav next to the input
    merge: list = field(default_factory=list)        # extra nav inputs merged into one output


@dataclass
class Output:
    name: str
    data: bytes
    report: Report
    model: object = None


@dataclass
class Loaded:
    kind: str
    model: object
    info: object
    container: object
    raw: bytes
    input_findings: list = None
    pgm_stamp: str = None        # one creation time per input, for every output made from it


def load_bytes(data, lenient=False):
    c = open_container(data)
    # the version line decides the kind; an obs payload is never decoded or split whole (it
    # streams), which for a 1.6 GB 24 h 1 Hz file was 4 GB of text and line objects
    info = sniff(first_line(c.payload))
    if info.version not in READ_VERSIONS:
        raise CorruptError(f"RINEX version {info.version} is not supported", line=1, column=1,
                           rule="HDR.VERSION.UNSUPPORTED")
    if info.kind == "obs":
        model = read_obs_payload(c.payload, info, eol_of(c.payload), lenient=lenient)
        presurvey(model)                   # pass 1: checks the data and caches the survey
        return Loaded(info.kind, model, info, c, data)
    lines, eol = split_lines(c.payload)
    if info.kind == "nav":
        model = read_nav(lines, info, eol, lenient=lenient)
    else:
        model = read_met(lines, info, eol, lenient=lenient)
    return Loaded(info.kind, model, info, c, data)


def _norm_target(t):
    try:
        v = f"{float(t):.2f}"
    except ValueError:
        raise InvocationError(f"bad target version {t!r}") from None
    if v not in WRITE_VERSIONS:
        raise InvocationError(f"target version {v} is not a write version ({', '.join(WRITE_VERSIONS)})")
    return v


def check_options(opts):
    """Option values the writers cannot take are invocation errors, not internal ones (Sol
    round 15: --approx-position NaN or 1e9 escaped as AssertionError / OverflowError).
    APPROX POSITION XYZ is 3F14.4 (rinex305.txt Table A2, rinex211.txt Table A1)."""
    target = _norm_target(opts.target)
    if opts.align_phases:
        # the user's decision (2026-11-02, 'old versions only'): only the RINEX 3 versions with
        # a shift table (3.02 Table A19, 3.03-3.05 Table A23) and 3.00 (undoing recorded shifts,
        # PLAN 3.3 rule 3); 3.01 has no table, RINEX 4 tables no values, RINEX 2 no record
        if target != "3.00" and not "3.02" <= target <= "3.05":
            raise InvocationError(f"--align-phases works for RINEX 3.00 and 3.02-3.05 targets, not {target} "
                                  "(the user's decision, 2026-11-02: 3.01 has no shift table, the RINEX 4 "
                                  "tables give no values); for RINEX 4, --assume-phase-aligned is the option")
        if opts.assume_phase_aligned:
            raise InvocationError("--align-phases (the source is unaligned: apply the table's shifts) and "
                                  "--assume-phase-aligned (the source is aligned) contradict each other")
    if opts.approx_position is not None:
        import math
        xyz = tuple(opts.approx_position)
        if len(xyz) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) and len(f"{v:14.4f}") <= 14
                                    for v in xyz):
            raise InvocationError(f"--approx-position {xyz}: three finite numbers that fit F14.4 "
                                  "(|value| below 1e9 m) are needed")


def convert_data(data, name, opts):
    """Convert one input (bytes). Returns a list of Output; raises RinexError on refusal."""
    check_options(opts)
    try:
        ld = load_bytes(data, opts.lenient)
    except RinexError as e:
        rep = Report()
        rep.input = {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        rep.target_version = _norm_target(opts.target)
        rep.outcome = e.outcome
        rep.message = str(e)
        e.report = rep
        raise
    return convert_loaded(ld, name, opts)


def convert_loaded(ld, name, opts):
    """Convert an already loaded input (the model is not modified, so one load can
    serve several targets)."""
    check_options(opts)
    target = _norm_target(opts.target)
    rep = Report()
    rep.input = {"path": name, "sha256": hashlib.sha256(ld.raw).hexdigest(), "bytes": len(ld.raw),
                 "layers": ld.container.layers, "crx": ld.container.crx}
    rep.target_version = target
    rep.source_version = ld.info.version
    rep.file_kind = ld.kind
    for n in getattr(ld.model, "notes", []):
        rep.repair(n["rule"], n["message"], n.get("line"))
    try:
        _refuse_damage(ld, opts.lenient, rep)
        snap = rep.snapshot()
        try:
            outs = _convert_loaded(ld, name, target, opts, rep)
        except Crx1EventError as e:
            # the user's choice (2026-10-31): a RINEX 2 cycle-slip epoch that Compact RINEX 1.0
            # cannot hold makes the whole file plain RINEX 2 (a second pass; nothing is lost)
            rep.restore(snap)
            outs = _convert_loaded(ld, name, target, dataclasses.replace(opts, crx=False), rep)
            rep.warn("OBS.CRX1.EVENT-PLAIN", f"written as plain RINEX 2, not Compact RINEX 1.0: {e}")
        except CrxCannotHold as e:
            # a valid file RNXCMP cannot carry (cycle-slip records it would misread, a 4.02
            # picosecond field that stops part-way: hatanaka.CrxCannotHold): plain, the same
            # choice; a second pass from the snapshot, so that nothing only Compact RINEX
            # needed (LLI/SSI of blank values dropped for CRINEX 1.0) stays lost (Sol round 23)
            rep.restore(snap)
            outs = _convert_loaded(ld, name, target, dataclasses.replace(opts, crx=False), rep)
            rep.warn(e.plain_rule, f"written as plain RINEX, not Compact RINEX: {e} (output line {e.line})")
    except RinexError as e:
        rep.outcome = e.outcome
        rep.message = str(e)
        e.report = rep
        raise
    input_warnings = [w for w in rep.warnings if w["rule"] in STRICT_WARNINGS]
    if opts.strict and ld.kind in ("obs", "nav", "met"):
        from rinexcore import validate as V
        if ld.input_findings is None:
            ld.input_findings = V.validate(ld.container.payload)
        bad = V.errors(ld.input_findings)
        if bad:
            e = CorruptError(f"--strict: the input fails validation ({bad[0].rule}: {bad[0].message})",
                             line=bad[0].line, rule=bad[0].rule)
            rep.outcome = e.outcome
            rep.message = str(e)
            e.report = rep
            raise e
    if opts.strict and (rep.repairs or input_warnings):
        what = (rep.repairs or input_warnings)[0]
        e = CorruptError(f"--strict: the input is off spec ({what['rule']}: {what['message']})",
                         line=what.get("line"), rule=what["rule"])
        rep.outcome = e.outcome
        rep.message = str(e)
        e.report = rep
        raise e
    removal = any(k.startswith("system-removed-unresolvable") for k in rep.losses)
    rep.outcome = CONVERTED_WITH_REMOVAL if removal else CONVERTED
    return outs


def _convert_loaded(ld, name, target, opts, rep):
    eol = opts.eol
    if ld.kind == "obs":
        oo = ObsOptions(lenient=opts.lenient, strict=opts.strict, overrides=opts.overrides,
                        drop_unresolvable=opts.drop_unresolvable,
                        assume_phase_aligned=opts.assume_phase_aligned,
                        align_phases=opts.align_phases,
                        keep_v2_nonstandard=opts.keep_v2_nonstandard,
                        keep_lli_bit2=opts.keep_lli_bit2,
                        approx_position=opts.approx_position,
                        approx_position_zero=opts.approx_position_zero)
        fcn, src_name = companion.glonass_channels(opts.nav, opts.glo_fcn)
        oo.crx1 = (ld.container.crx is not None if opts.crx is None else opts.crx) and target < "3"
        oo.glo_fcn = fcn
        oo.glo_fcn_source = src_name
        out = convert_obs(ld.model, target, oo, rep)
        out.header = place_pgm(out.header, target, rep, _stamp(ld))
        payload = join_lines(iter_obs_lines(out, target), eol)
        _verify_obs(payload, target)
        _validate(payload, ld, rep)
        crx = ld.container.crx is not None if opts.crx is None else opts.crx
        if crx:
            from rinexcore.io import hatanaka
            payload = hatanaka.rnx_to_crx(payload)   # CrxCannotHold: convert_loaded retries
        data = _wrap(payload, ld.container.layers, opts.compression)
        oname = output_name(name, "obs", target, out, crx, opts, rep, data)
        rep.output = {"path": oname, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                      "crx": crx}
        return [Output(oname, data, rep, out)]
    if ld.kind == "nav":
        extra = []
        for p in opts.merge:
            try:
                mld = load_bytes(read_path(p), opts.lenient)
                # the same input policy as the primary input: damage refused unless --lenient
                # (clause 9), any validator error refused under --strict, repairs reported
                _refuse_damage(mld, opts.lenient, rep)
                if opts.strict:
                    from rinexcore import validate as V
                    bad = V.errors(_input_findings(mld))
                    if bad:
                        raise CorruptError(f"--strict: the input fails validation ({bad[0].message})",
                                           line=bad[0].line, rule=bad[0].rule)
            except CorruptError as e:
                raise CorruptError(f"merge input {p}: {e}", rule="NAV.MERGE.INPUT") from None
            except RinexError as e:
                # keep the refusal's own outcome (round 32: a missing-information or
                # not-representable refusal of a merge input was reported as refused-corrupt)
                raise _same_refusal(e, f"merge input {p}: {e}") from None
            for n in getattr(mld.model, "notes", []):
                rep.repair(n["rule"], f"merge input {p}: {n['message']}", n.get("line"))
            # each input's version: a loss of one input's records is judged by its own version
            rep.input.setdefault("merged", []).append({"path": str(p), "version": mld.info.version})
            extra.append(mld.model)
        rep.lenient = opts.lenient
        outs = convert_nav(ld.model, target, NavOptions(opts.lenient, opts.strict, opts.dedupe,
                                                        opts.leap_seconds, opts.qzss_ion_area),
                           rep, merge_with=extra)
        res = []
        for nf in outs:
            nf.header = place_pgm(nf.header, target, rep, _stamp(ld))
            payload = join_lines(write_nav(nf, target), eol)
            _verify_generic(payload, target)
            _validate(payload, ld, rep)
            data = _wrap(payload, ld.container.layers, opts.compression)
            oname = output_name(name, "nav", target, nf, False, opts, rep, data)
            res.append(Output(oname, data, rep, nf))
        rep.output = {"paths": [o.name for o in res],
                      "sha256": [hashlib.sha256(o.data).hexdigest() for o in res]}
        if res:
            rep.output["path"] = res[0].name
        return res
    out = convert_met(ld.model, target, rep)
    out.header = place_pgm(out.header, target, rep, _stamp(ld))
    payload = join_lines(write_met(out, target), eol)
    _verify_generic(payload, target)
    _validate(payload, ld, rep)
    data = _wrap(payload, ld.container.layers, opts.compression)
    oname = output_name(name, "met", target, out, False, opts, rep, data)
    rep.output = {"path": oname, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return [Output(oname, data, rep, out)]


def place_pgm(header, target, rep, stamp=None):
    """PGM / RUN BY / DATE is mandatory in every version and must be the second line in 4.x
    (rinex_4.00.txt Table A2: further PGM lines may follow it). A missing one is written for
    rinexconv, which is the program creating this file."""
    import datetime
    from rinexcore.header import HeaderRecord
    from . import __version__
    pgm = [r for r in header if r.label == "PGM / RUN BY / DATE"]
    if not pgm:
        now = stamp or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d %H%M%S UTC")
        pgm = [HeaderRecord("PGM / RUN BY / DATE", f"{'rinexconv ' + __version__:20s}{'':20s}{now:20s}")]
        rep.repair("HDR.PGM.ADDED", "no PGM / RUN BY / DATE in the source: one written for rinexconv")
    elif target < "4" or header[1:1 + len(pgm)] == pgm:
        return header
    else:
        rep.rule("HDR.PGM.SECOND-LINE")
    rest = [r for r in header[1:] if r.label != "PGM / RUN BY / DATE"]
    return header[:1] + pgm + rest


def _stamp(ld):
    """Creation time for a PGM / RUN BY / DATE written by rinexconv: fixed per loaded input
    (so every output of one input carries the same one); SOURCE_DATE_EPOCH, if set, wins."""
    import datetime
    if ld.pgm_stamp is None:
        sde = os.environ.get("SOURCE_DATE_EPOCH")
        t = (datetime.datetime.fromtimestamp(int(sde), datetime.timezone.utc) if sde and sde.isdecimal()
             else datetime.datetime.now(datetime.timezone.utc))
        ld.pgm_stamp = t.strftime("%Y%m%d %H%M%S UTC")
    return ld.pgm_stamp


# Validator rules whose messages name version-specific things (RINEX 2/3 count a nav record
# with its epoch line, RINEX 4 after its '>' line and names the message type).
_COUNTED_RULES = {"VAL.NAV.RECORD.LINES"}
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?![A-Za-z])")
# Data-level damage (PLAN §1 clause 9): values or records that cannot be read as written, or
# whose structure is broken. A well-formed record the version does not define (an unknown
# message type, a non-standard satellite id) is not damage: it is carried and reported.
_DAMAGE_RULES = {
    "VAL.OBS.EPOCH.START", "VAL.OBS.EPOCH.SYNTAX", "VAL.OBS.EPOCH.FLAG", "VAL.OBS.EPOCH.TIME",
    "VAL.OBS.EPOCH.PICOSECONDS", "VAL.OBS.EPOCH.NSAT", "VAL.OBS.EPOCH.SATLIST",
    "VAL.OBS.EVENT.COUNT", "VAL.OBS.EVENT.RECORD", "VAL.OBS.DATA.FIELD", "VAL.OBS.DATA.LLI",
    "VAL.OBS.DATA.EXTRA", "VAL.OBS.TRUNCATED",
    "VAL.NAV.RECORD.START", "VAL.NAV.RECORD.HEAD", "VAL.NAV.EPOCH", "VAL.NAV.LAYOUT", "VAL.NAV.NUMBER",
    "VAL.MET.EPOCH", "VAL.MET.VALUE", "VAL.MET.CONTINUATION"}


def _input_findings(ld):
    from rinexcore import validate as V
    if ld.input_findings is None:
        try:
            ld.input_findings = V.validate(ld.container.payload)
        except RinexError:
            ld.input_findings = []
    return ld.input_findings


def _refuse_damage(ld, lenient, rep):
    """PLAN §1 clause 9: data-level damage is an error by default (header-only inconsistencies
    are repaired). The readers refuse what they cannot read; damage they read past (a value
    such as '12.3.4' that passes the character check, text after the last column of a line)
    is caught by validating the input once (cached across targets) before converting."""
    from rinexcore import validate as V
    if ld.kind not in ("obs", "nav", "met"):
        return
    damaged = [f for f in V.errors(_input_findings(ld)) if f.rule in _DAMAGE_RULES]
    if damaged and lenient:
        rep.warn("VAL.INPUT-DAMAGE", f"--lenient: the input's data break its own format at "
                 f"{len(damaged)} place(s) ({', '.join(sorted({f.rule for f in damaged}))}; first "
                 f"line {damaged[0].line}); converted as read")
    elif damaged:
        f = damaged[0]
        raise CorruptError(f"the input's data break its own format ({f.rule}: {f.message}); "
                           "--lenient converts it as read, reported", line=f.line, rule=f.rule)


def _validate(payload, ld, rep):
    """PLAN §1 clause 2: the output must be valid for its version. An error the input did not
    already have is a converter bug (it raises, outcome internal-error); errors inherited
    from an input that broke the same rule are reported with the conversion."""
    from rinexcore import validate as V
    found = V.validate(payload)
    errs = V.errors(found)
    rep.validation = {"errors": len(errs), "warnings": len(found) - len(errs),
                      "rules": V.rules(found),
                      # the text of each finding, so a reader can judge it (first 20)
                      "findings": [{"severity": f.severity, "rule": f.rule, "message": f.message,
                                    "line": f.line} for f in found[:20]]}
    if not errs:
        return
    _input_findings(ld)
    def key(f):
        # the same violation in another version: rule and message with standalone numbers
        # (counts, line numbers, versions) blanked, digits inside a code or satellite id
        # ('1C', 'L1C', 'G05') kept; rules whose wording is version-specific by design are
        # counted per rule (the output may not hold more of them than the input)
        if f.rule in _COUNTED_RULES:
            return f.rule, ""
        return f.rule, _NUMBER.sub("#", f.message)
    have = Counter(key(f) for f in V.errors(ld.input_findings))
    got = Counter(key(f) for f in errs)
    new = got - have
    rep.validation["inherited"] = sorted({k[0] for k in got & have})
    if new:
        first = next(f for f in errs if key(f) in new)
        raise AssertionError(f"converter output fails validation ({first.rule}: {first.message}, "
                             f"line {first.line})")

    rep.warn("VAL.INHERITED", f"the output keeps {len(errs)} validator error(s) the input already "
             f"had: {', '.join(rep.validation['inherited'])}")


def _verify_obs(payload, target):
    """The output must parse with our own reader, at the target version."""
    info = sniff([payload[:82].split(b"\n", 1)[0].decode("latin-1")])
    if info.version != target:
        raise AssertionError(f"writer produced version {info.version}, wanted {target}")
    for _ in read_obs_payload(payload, info).iter_epochs():
        pass


def _verify_generic(payload, target):
    lines, eol = split_lines(payload)
    info = sniff(lines)
    if info.version != target:
        raise AssertionError(f"writer produced version {info.version}, wanted {target}")
    if info.kind == "nav":
        read_nav(lines, info, eol)
    else:
        read_met(lines, info, eol)


def _wrap(payload, layers, mode):
    if mode == "none":
        return payload
    if mode == "keep":
        want = layers[0] if layers else None
    else:
        want = mode
    if want == "gz":
        return compress.gzip_bytes(payload)
    if want == "Z":
        return compress.lzw(payload)
    if want == "bz2":
        import bz2
        return bz2.compress(payload, 9)
    return payload                       # a zip input is written plain (one file per output)


def _cmp_ext(data):
    k = compress.detect(data)
    return {"gz": ".gz", "Z": ".Z", "bz2": ".bz2"}.get(k, "")


def _shifted_name(base, p, kind, model, rep):
    """The input name with its date and time fields following a time-system shift of the
    epochs (BDT to GPS, 14 s: obsconv._target_time_system): a short name's DDD is the day of
    the first record and f its hour (rinex211.txt section 4), a long name's YYYYDDDHHMM its start
    (rinex305.txt section 4). A field is moved only if it agreed with the unshifted first
    epoch, so a name that did not follow its data keeps its fields (Sol round 19: test3660.16o
    kept day 366 for a first epoch of 2017-01-01 00:00:04 GPS)."""
    import datetime
    t1 = getattr(model, "first_time", None)
    if kind != "obs" or p is None or t1 is None or "OBS.TIME-SYSTEM.BDT-TO-GPS" not in rep.rules:
        return base, p
    from .obsconv import _add_seconds
    t0 = _add_seconds(t1, -14)

    def fields(t):
        return t[0], datetime.date(t[0], t[1], t[2]).timetuple().tm_yday, t[3], t[4]
    (y0, d0, h0, m0), (y1, d1, h1, m1) = fields(t0), fields(t1)
    q = dict(p)
    # a name whose date does not agree with the data is left as it is, all of it (Sonnet
    # round 20: only its hour moved)
    agrees = ((int(p["ddd"]), int(p["yy"])) == (d0, y0 % 100) if p["style"] == "short"
              else (int(p["y"]), int(p["ddd"])) == (y0, d0))
    if not agrees:
        return base, p
    if p["style"] == "short":
        q["ddd"], q["yy"] = f"{d1:03d}", f"{y1 % 100:02d}"
        if p["f"] != "0" and p["f"].lower() == chr(97 + h0):
            q["f"] = chr(97 + h1)
        if p.get("mm") and int(p["mm"]) == m0:
            q["mm"] = f"{m1:02d}"
        new = f"{q['s']}{q['ddd']}{q['f']}{q.get('mm') or ''}.{q['yy']}{q['t']}"
    else:
        q["y"], q["ddd"] = f"{y1:04d}", f"{d1:03d}"
        if (int(p["hh"]), int(p["mi"])) == (h0, m0):
            q["hh"], q["mi"] = f"{h1:02d}", f"{m1:02d}"
        new = (f"{q['id']}_{q['src']}_{q['y']}{q['ddd']}{q['hh']}{q['mi']}_{q['per']}"
               + (f"_{q['frq']}" if q.get("frq") else "") + f"_{q['tt']}.{q['fmt']}")
    if new != base:
        rep.rule("OBS.TIME-SYSTEM.NAME-DATE")
    return new, names.parse(new)


def output_name(name, kind, target, model, crx, opts, rep, data):
    base = names.strip_compression(os.path.basename(name))
    p = names.parse(base)
    base, p = _shifted_name(base, p, kind, model, rep)
    ext = _cmp_ext(data)
    t0 = _first_time(kind, model)
    if target < "3":
        if kind == "nav":
            letter = {"N": "n", "G": "g", "H": "h"}.get(model.ftype, "n")
        else:
            letter = None
        if p and p["style"] == "short":
            stem = base[:-1]
            t = {"obs": "d" if crx else "o", "met": "m"}.get(kind, letter)
            return stem + t + ext
        if p and p["style"] == "long":
            y, doy = int(p["y"]), int(p["ddd"])
            hh, mi = int(p["hh"]), int(p["mi"])
            return names.short_name(kind, p["id"][:4], y, doy, hh, mi, p["per"].upper(), crx,
                                    letter or "n") + ext
        if t0 is not None:
            site = _marker(model) or "xxxx"
            y, doy = t0
            return names.short_name(kind, site, y, doy, None, None, "01D", crx, letter or "n") + ext
        return base + f".v{target}" + ext
    # RINEX 3/4 long names
    content = _content_type(kind, model)
    fmt_ext = ".crx" if crx else ".rnx"
    if p and p["style"] == "long":
        stem = base.rsplit(".", 1)[0]
        parts = stem.split("_")
        parts[-1] = content
        return "_".join(parts) + fmt_ext + ext
    if p and p["style"] == "short":
        y = int(p["yy"])
        y = 1900 + y if y >= 80 else 2000 + y
        doy = int(p["ddd"])
        f = p["f"].lower()
        if f == "0":
            hh, mi, per = 0, 0, "01D"
        elif p.get("mm"):
            hh, mi, per = ord(f) - 97, int(p["mm"]), "15M"
        else:
            hh, mi, per = ord(f) - 97, 0, "01H"
        ident = _nine_char_id(model, p["s"], rep)
        interval = names._interval_code(_interval(model)) if kind == "obs" else None
        rep.assume("filename-data-source", "R", "default:receiver")
        return names.long_name(kind, ident, "R", y, doy, hh, mi, per, interval, content, crx) + ext
    return base + f".v{target}" + fmt_ext + ext


def _content_type(kind, model):
    if kind == "met":
        return "MM"
    if kind == "nav":
        s = model.system.strip() or "M"
        return f"{s}N"
    syss = getattr(model, "out_systems", None)
    if syss is None:
        syss = list({s[0] for ep in model.epochs for s in ep.sats})
    return f"{syss[0] if len(syss) == 1 else 'M'}O"


def _nine_char_id(model, site, rep):
    import re
    m = _marker(model, full=True) or ""
    if re.fullmatch(r"[A-Z0-9]{9}", m.strip()):
        rep.assume("filename-id", m.strip(), "header:MARKER NAME")
        return m.strip()
    ident = site.upper()[:4] + "00XXX"
    rep.assume("filename-id", ident, "default:country-unknown")
    return ident


def _marker(model, full=False):
    """MARKER NAME, or its first four characters as a RINEX 2 file name's station id
    ("ssss: 4-character station name designator", rinex211.txt section 4) only when they are
    letters and digits: anything else ('../x', 'A B', 'C:x') names no station, and must never
    become part of a path (Sol round 29: '../x' was written as ../x2740.26o)."""
    import re
    for r in getattr(model, "header", []):
        if r.label == "MARKER NAME":
            v = r.content[:60].strip()
            if full:
                return v
            return v[:4] if re.fullmatch(r"[A-Za-z0-9]{1,4}", v[:4]) else None
    return None


def _interval(model):
    for r in model.header:
        if r.label == "INTERVAL":
            try:
                return float(r.content[:10])
            except ValueError:
                return None
    return None


def _first_time(kind, model):
    import datetime
    if kind == "obs":
        t = getattr(model, "first_time", None)
        if t is None:
            return None
    elif kind == "nav":
        if not model.records:
            return None
        t = model.records[0].time
    else:
        if not model.epochs:
            return None
        t = model.epochs[0].time
    d = datetime.date(t[0], t[1], t[2])
    return t[0], d.timetuple().tm_yday


def _check_output_name(name, what="output"):
    """An output or report name must be one plain file name (names.unsafe_file_name: no folder
    part, drive, '..' or stream, no control character, no trailing dot or blank, no Windows
    device name such as CON, NUL.26o or COM¹). Names come from the input's name and its header
    (MARKER NAME), which a file may fill with anything (Sol rounds 29-30), so this is checked
    before anything is written."""
    why = names.unsafe_file_name(name)
    if why:
        raise InvocationError(f"unsafe {what} file name {names.shown(name)} ({why}; it comes from the "
                              "input's name or header)")


def safe_path(out_dir, name, what="output"):
    """out_dir / name, after checking that name is a safe file name and that the path resolves
    inside out_dir (which must exist)."""
    _check_output_name(name, what)
    d = Path(out_dir)
    target = d / name
    try:
        inside = target.resolve().parent == d.resolve()
    except OSError:
        inside = False
    if not inside:
        raise InvocationError(f"{what} name {names.shown(name)} would be written outside {d}")
    return target


def _same_refusal(e, message):
    """A refusal of the same class (and outcome) as `e`, with a new message."""
    from rinexcore.errors import MissingInformationError
    if isinstance(e, MissingInformationError):
        return MissingInformationError(message, missing=e.missing)
    if isinstance(e, NotRepresentableError):
        return NotRepresentableError(message)
    return CorruptError(message)


def _output_dir(out_dir):
    d = Path(out_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise InvocationError(f"cannot create output directory {d}: {e}") from None
    return d


def lock_path(d):
    """The lock file for output folder d: in the system temp folder, named by a hash of d's
    resolved path, so every process writing d uses the same file and d itself stays clean."""
    key = os.path.normcase(str(Path(d).resolve()))
    h = hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()[:32]
    return Path(tempfile.gettempdir()) / "rinexconv-locks" / (h + ".lock")


_HELD = threading.local()                 # lock paths this thread holds -> depth


@contextlib.contextmanager
def output_locks(dirs):
    """output_lock for each distinct folder of dirs, taken in one fixed order (by lock file
    name) so that two writers needing the same folders cannot deadlock. The CLI holds the
    output and the report folder this way for one input's whole transaction (round 36, Sol:
    outputs and report published separately could pair one job's outputs with another's
    report)."""
    with contextlib.ExitStack() as stack:
        for p, d in sorted({str(lock_path(d)): d for d in dirs}.items()):
            stack.enter_context(output_lock(d))
        yield


@contextlib.contextmanager
def output_lock(d):
    """Hold an exclusive operating-system lock for output folder d (lock_path; msvcrt.locking
    on Windows, fcntl.flock elsewhere) while a set is written into it. The OS drops the lock
    when the process ends, so a killed run never blocks the next one; the (empty) lock file is
    kept, since removing it would let two runs lock two different files. A thread that already
    holds the lock takes it again without waiting (re-entrant)."""
    p = lock_path(d)
    held = getattr(_HELD, "paths", None)
    if held is None:
        held = _HELD.paths = {}
    if held.get(str(p)):
        held[str(p)] += 1
        try:
            yield
        finally:
            held[str(p)] -= 1
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
    except OSError as e:
        raise InvocationError(f"cannot create the output lock {p}: {e}") from None
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)   # retries for about 10 s, then raises
                    break
                except OSError:
                    continue                                # another writer still holds it
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        held[str(p)] = 1
        try:
            yield
        finally:
            held.pop(str(p), None)
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(fd)


def _output_target(out, d, force, inputs):
    """The checked path for `out` in folder d: a safe name inside d, not one of the inputs,
    and not an existing file unless force. Something there that is not a plain file (a
    folder, say) is never replaced, --force or not (round 33: a folder with an output's name
    was moved aside with its contents)."""
    _check_output_name(out.name)
    target = safe_path(d, out.name)
    for i in inputs:
        try:
            if target.resolve() == Path(i).resolve():
                raise InvocationError(f"output {target} would overwrite its input")
        except OSError:
            pass
    if target.exists() and not target.is_file():
        raise InvocationError(f"output {names.shown(str(target), 120)} exists and is not a file")
    if target.exists() and not force:
        raise InvocationError(f"output {names.shown(str(target), 120)} exists (use --force to overwrite)")
    return target


def _unlink(p):
    try:
        os.unlink(p)
    except OSError:
        pass


def write_output(out, out_dir, force=False, inputs=()):
    """Write atomically; a partial output is never left looking complete (PLAN §1.1)."""
    return write_outputs([out], out_dir, force, inputs)[0]


def write_outputs(outs, out_dir, force=False, inputs=()):
    """Write the outputs of one input as a set (PLAN §1 clause 1: a partial output is deleted,
    never left looking complete). Every target is checked before anything is written, so one
    that exists (without --force) or has an unusable name stops the set before its first file
    (round 32: a RINEX 4 nav file split into RINEX 2 n/g/h files was left with only the n file
    when the g file existed); each file goes to a temporary file in the output folder first,
    and only when all are written are they renamed into place. If a rename fails, the files
    of the set already renamed are removed again, and a file that --force was replacing is put
    back as it was (round 33, Sol: the rollback deleted it): an existing target is first
    renamed aside, and the copies aside are deleted only when the whole set is in place.

    Without force every name is reserved first by creating it exclusively (O_EXCL), so of two
    jobs that write the same name at once (--jobs, inputs of the same name from different
    folders) one wins and the other gets "exists"; a check followed by a rename could not stop
    the second job replacing the first one's file (round 34, Sol). A reserved name is an empty
    file until its rename, and it is removed if the set fails.

    The whole transaction (checks, reservations, renames, rollback) runs under an operating-
    system lock on the output folder (output_lock), so two transactions in one folder never
    interleave, from --jobs workers or from separate runs: with --force one whole set then
    replaces the other, never a mix of the two (round 35, Sol: one job's rollback put an old
    file back over another job's finished output). An interruption (Ctrl-C) during the renames
    rolls the set back as a failed rename does (round 35, checks reviewer)."""
    for o in outs:
        _check_output_name(o.name)        # before the folder is created
    d = _output_dir(out_dir)
    with output_lock(d):
        return _write_set(outs, d, force, inputs)


def _write_set(outs, d, force, inputs):
    targets = [_output_target(o, d, force, inputs) for o in outs]
    seen = set()
    for t in targets:
        key = os.path.normcase(str(t.resolve()))
        if key in seen:
            raise InvocationError(f"two outputs of one input have the same name {names.shown(t.name)}")
        seen.add(key)
    reserved = []                         # names this call created empty (no --force)
    tmps = []
    journal = []                          # [target, old or None, tmp], one per rename step
    committed = False
    try:
        if not force:
            _reserve(targets, reserved)
        for o in outs:
            try:
                fd, tmp = tempfile.mkstemp(prefix=".rinexconv-", dir=str(d))
            except OSError as e:          # (Sol round 31: escaped as OSError)
                raise InvocationError(f"cannot write in {d}: {e}") from None
            tmps.append(tmp)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(o.data)
            except OSError as e:
                raise InvocationError(f"cannot write {d / o.name}: {e}") from None
        for tmp, target in zip(tmps, targets):
            # each step is journalled before anything is renamed, and _undo_step judges from
            # the files how far it got and is safe to repeat, so an interruption between any
            # two operations, the undo included, leaves the folder as it was (rounds 36-37, Sol)
            step = [target, None, tmp]
            journal.append(step)
            try:
                if force and target.exists():     # without force it is our own reservation
                    step[1] = tmp + ".old"        # a unique name: tmp is from mkstemp
                    os.replace(target, step[1])
                os.replace(tmp, target)
            except OSError as e:
                n = len(journal) - 1
                lost = _undo_all(journal)
                more = f"; {n} file(s) of the set already written were removed" if n else ""
                if lost:
                    more += "; could not put back " + ", ".join(f"{t} (kept as {o})" for t, o in lost)
                raise InvocationError(f"cannot write {target}: {e}{more}") from None
        committed = True
        for _, old, _ in journal:
            if old:
                _unlink(old)
    except BaseException:
        if not committed:                 # e.g. Ctrl-C between two renames
            _undo_all(journal)
            for t in reserved:            # names reserved but never filled (still empty)
                try:
                    if t.stat().st_size == 0:
                        _unlink(t)
                except OSError:
                    pass
        else:                             # the set is in place: finish removing the old copies
            for _, old, _ in journal:
                if old:
                    _unlink(old)
        raise
    finally:
        for tmp in tmps:
            if os.path.exists(tmp):
                _unlink(tmp)
    return targets


def _reserve(targets, reserved):
    """Create each target exclusively (an empty file), or raise InvocationError. Each name is
    added to `reserved` before it is created and taken out again if the create fails, so the
    caller's clean-up knows every name this call may have created, whenever it is interrupted
    (round 37); the clean-up removes only names that are still empty."""
    for t in targets:
        reserved.append(t)
        try:
            # 'x': create exclusively (O_EXCL); the with block closes the handle whatever
            # interrupts it, so the clean-up can delete the file (Windows cannot delete an
            # open one)
            with open(t, "xb"):
                pass
        except FileExistsError:
            reserved.pop()                # not ours
            raise InvocationError(f"output {names.shown(str(t), 120)} exists (use --force to overwrite)") from None
        except OSError as e:
            reserved.pop()
            raise InvocationError(f"cannot write {t}: {e}") from None


def _undo_step(step):
    """Undo one journalled rename step [target, old or None, tmp], judged only by the files, so
    that doing it twice does no harm (round 37, Sol: an interruption between recording a step
    and clearing it undid it twice and deleted the old file it had just put back). A step that
    replaced an old file: put the copy aside back if it is still aside (its 'old' path exists;
    once back, nothing is left to do). A step with no old file: remove the new file if it is in
    place (tmp is gone). Returns [(target, aside)] for an old file that could not be put back."""
    target, old, tmp = step
    try:
        if old is not None:
            if os.path.exists(old):
                os.replace(old, target)
        elif not os.path.exists(tmp):
            _unlink(target)
    except OSError:
        return [(target, old)]
    return []


def _undo_all(journal):
    """Undo every journalled step, newest first; safe to repeat."""
    lost = []
    for step in reversed(journal):
        lost += _undo_step(step)
    return lost
