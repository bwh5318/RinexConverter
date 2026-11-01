"""Conversion engine: load -> convert -> write -> validate, with the run outcome.

Every call ends in one of the four outcomes of PLAN §1 clause 1; refusals are
RinexError subclasses. Invocation/I-O failures raise InvocationError and are
never reported as refused-corrupt.
"""

import dataclasses
import hashlib
import os
import re
import tempfile
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
                   "NAV.HDR.TIMECORR.LAYOUT"}
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
    dedupe: bool = False
    crx: bool = None                                 # None: keep the input's Hatanaka state
    compression: str = "keep"                        # keep | none | gz | Z
    eol: str = "lf"
    keep_v2_nonstandard: bool = False
    keep_lli_bit2: bool = False
    leap_seconds: int = None
    approx_position: tuple = None
    approx_position_zero: bool = False               # teqc's 0 0 0 placeholder (reported)
    qzss_ion_area: str = None                        # WIDE | JAPN for 4.00/4.01 -> 4.02 CNVX ION
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
    _norm_target(opts.target)
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
            except RinexError as e:
                raise CorruptError(f"merge input {p}: {e}", rule="NAV.MERGE.INPUT") from None
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
    for r in getattr(model, "header", []):
        if r.label == "MARKER NAME":
            v = r.content[:60].strip()
            return v if full else v[:4]
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


def write_output(out, out_dir, force=False, inputs=()):
    """Write atomically; a partial output is never left looking complete (PLAN §1.1)."""
    d = Path(out_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise InvocationError(f"cannot create output directory {d}: {e}") from None
    target = d / out.name
    for i in inputs:
        try:
            if target.resolve() == Path(i).resolve():
                raise InvocationError(f"output {target} would overwrite its input")
        except OSError:
            pass
    if target.exists() and not force:
        raise InvocationError(f"output {target} exists (use --force to overwrite)")
    fd, tmp = tempfile.mkstemp(prefix=".rinexconv-", dir=str(d))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(out.data)
        os.replace(tmp, target)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise InvocationError(f"cannot write {target}: {e}") from None
    return target
