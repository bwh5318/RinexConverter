"""Check report losses against tests/expectations/allowed_losses.json (PLAN §1.4).

Independent of rinexcore/rinexconv: it reads only the JSON and the report dict.
"""

import json
import os

from . import codes as _codes

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "code_expectations.json"), "rb") as _fh:
    _GROUPS = json.loads(_fh.read().decode("utf-8"))

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "expectations",
                     "allowed_losses.json")
with open(_PATH, "rb") as _fh:
    TABLE = json.loads(_fh.read().decode("utf-8"))

V3_ONLY_LABELS = {"MARKER TYPE", "SIGNAL STRENGTH UNIT", "ANTENNA: DELTA X/Y/Z", "ANTENNA: PHASECENTER",
                  "ANTENNA: B.SIGHT XYZ", "ANTENNA: ZERODIR AZI", "ANTENNA: ZERODIR XYZ",
                  "CENTER OF MASS: XYZ", "SYS / DCBS APPLIED", "SYS / PCVS APPLIED", "SYS / SCALE FACTOR",
                  "SYS / PHASE SHIFT", "SYS / PHASE SHIFTS", "GLONASS COD/PHS/BIS", "GLONASS SLOT / FRQ #"}
V4_ONLY_LABELS = {"DOI", "LICENSE OF USE", "STATION INFORMATION"}


def _match(pattern, cat):
    if pattern.endswith("*"):
        return cat.startswith(pattern[:-1])
    return cat == pattern


def _b1i(code, version):
    """BeiDou B1I in a file of `version`: band 2 I/Q/X, band 1 I/Q, band 1 X before 3.04."""
    band, attr = code[1], code[2]
    return band == "2" and attr in "IQX" or band == "1" and (attr in "IQ" or attr == "X" and version < "3.04")


def _group(sys_, code):
    """GPS/GLONASS pseudorange family of a code (C/A, P, L1C, L2C ...) from the independent
    expectations; None where attributes do not split the RINEX 2 codes."""
    if len(code) == 2:
        return _GROUPS["v2_code_groups"].get(sys_, {}).get(code) if code[0] in "CP" else None
    g = _GROUPS["v3_code_groups"].get(sys_, {}).get("C" + code[1])
    return g.get(code[2]) if g else None


def code_not_representable(src, tgt, sys_, code):
    """Is an observation code of a `src` file really impossible to write in `tgt`?"""
    if sys_ not in _codes.systems(tgt):
        return True
    if src >= "3" and tgt >= "3":
        c = code
        if sys_ == "C" and _b1i(code, src):
            c = code[0] + ("1" if tgt == "3.02" else "2") + code[2]
        elif sys_ == "C" and tgt == "3.02" and code[1] == "1":
            return True          # B1C in the source; band 1 means B1I in 3.02
        return not _codes.valid(tgt, sys_, c)
    if src < "3" and tgt >= "3":
        # a RINEX 2 code its version does not define for this system has no signal to map
        # (a GLONASS value under the one list's C6, which 2.11 defines for Galileo E6 only:
        # rinex211.txt section 10.1.1; RINEX 3.04's GLONASS band 6 is G2a, another signal).
        # Systems RINEX 2 does not define (BDS, QZSS, IRNSS in RINEX 2 files) are mapped
        # as the converter documents, so the rule does not apply to them
        if sys_ in _codes.source_systems(src) and not _codes.source_valid(src, sys_, code):
            return True
        # some RINEX 3 code of the same type and band must exist (any attribute) ...
        t = "C" if code[0] in "CP" else code[0]
        band = code[1]
        if sys_ == "C" and band in "12":
            band = "1" if tgt == "3.02" else "2"
        cands = [c for c in _codes.codes(tgt, sys_) if c[0] == t and c[1] == band]
        g = _group(sys_, code)
        if g is not None:
            cands = [c for c in cands if _group(sys_, c) == g]
        return not cands
    if src >= "3" and tgt < "3":
        band = code[1]
        if sys_ == "C" and _b1i(code, src):
            band = "2"
        if code[0] == "C" and code[2:3] in ("", " ") and \
                _GROUPS["v3_code_groups"].get(sys_, {}).get("C" + band):
            # a blank attribute (3.00/3.01: 'unknown tracking mode', rinex300.txt l.690) on a
            # band whose RINEX 2 pseudoranges each name a family (C1 C/A, P1 P): no family is
            # known, so neither code can be claimed (Sol round 13)
            return True
        g = _group(sys_, code if code[0] == "C" else "C" + code[1:])
        v2 = [c for c in _codes.codes(tgt, sys_) if c[1] == band]
        if g is None:
            return not any(c[0] == code[0] for c in v2)
        # the band's RINEX 2 codes must carry this signal family (C/A, P, L2C)
        fams = {_group(sys_, c) for c in v2 if c[0] in "CP"}
        return g not in fams
    return not _codes.valid(tgt, sys_, code)


# Which correction types each target can hold, from the specs (independent of navcorr.py):
# RINEX 2: GPS ION ALPHA/BETA + DELTA-UTC in the n file, CORR TO SYSTEM TIME (GLONASS) in g,
# D-UTC / CORR TO SYSTEM TIME (SBAS) in h (rinex211.txt Tables A3, A10, A15);
# RINEX 3: IONOSPHERIC CORR GAL, GPSA/B, and QZSA/B, BDSA/B from 3.02, IRNA/B from 3.03;
# TIME SYSTEM CORR GPUT GLUT GAUT SBUT GLGP GAGP(GPGA), and BDUT QZUT QZGP from 3.02, IRUT IRGP
# from 3.03 (rinex305.txt Table A5 and the 3.02/3.03 change notes); RINEX 4: every type as
# ION/STO/EOP records, except Klobuchar sets missing alpha or beta (Table A35).
_V3_STO = {"GPUT": "3.00", "GLUT": "3.00", "GAUT": "3.00", "SBUT": "3.00", "GLGP": "3.00",
           "GAGP": "3.00", "GPGA": "3.00", "BDUT": "3.02", "QZUT": "3.02", "QZGP": "3.02",
           "IRUT": "3.03", "IRGP": "3.03"}
_V3_ION = {("KLOB", "G"): "3.00", ("NEQG", "E"): "3.00", ("KLOB", "J"): "3.02",
           ("KLOB", "C"): "3.02", ("KLOB", "I"): "3.03"}
_V2_HOME = {"GPUT": "n", "GLUT": "g", "SBUT": "h"}


def nav_corr_not_representable(src, tgt, cat, report):
    parts = cat.split(":")
    what = parts[1]
    if what == "EOP":
        return tgt < "4"
    # RINEX 2 output file types written, from the names: ssssDDDf.YYt[.gz|.Z] -> t
    v2_types = {p.split(".")[1][-1:].lower() for p in map(str, report.get("output", {}).get("paths") or [])
                if "." in p}
    if what == "STO":
        code = parts[2]
        if tgt >= "4":
            return False
        if tgt < "3":
            # only in its home file, and only if that file was written
            return _V2_HOME.get(code) not in v2_types
        v = _V3_STO.get(code)
        return v is None or tgt < v
    if what == "ION":
        model, sys_ = parts[2], parts[3] if len(parts) > 3 else ""
        if model.startswith("KLOB-incomplete"):
            return True
        if model == "CNVX-area-unknown":
            # QZSS CNVX ION needs WIDE/JAPN from 4.02 (rinex_4.02.txt Table 25); 4.00/4.01 have none
            return src < "4.02" <= tgt
        if tgt >= "4":
            return False
        if tgt < "3":
            return not (model == "KLOB" and sys_ == "G" and "n" in v2_types)
        v = _V3_ION.get((model, sys_))
        return v is None or tgt < v
    return True


def _when(cond, kind, src, tgt, cat, report, flags):
    if cond is None:
        return True
    if cond == "nav-corr-not-in-target":
        return src != tgt and nav_corr_not_representable(src, tgt, cat, report)
    if cond == "code-not-in-target":
        _, s_, code = cat.split(":")
        return src != tgt and code_not_representable(src, tgt, s_, code)
    if cond == "source-ne-target":
        return src != tgt
    if cond == "source-ne-target-or-merge":
        # also a --merge into the inputs' own version: each input brings its own values of a
        # type (compare_nav checks which output value is whose)
        return src != tgt or "NAV.MERGE" in (report.get("rules") or {})
    if cond == "system-gone":
        # the system is not in the target, or --drop-unresolvable removed it (claimed), or
        # some of its types have no target code (claimed): whether that left it no type at all
        # is checked against the files (headers._sys_records: the output's own type lists)
        s = cat.split(":")[1]
        losses = report.get("losses", {})
        return s not in TABLE["systems"].get(tgt, "") or f"system-removed-unresolvable:{s}" in losses \
            or any(k.startswith(f"obs-code-not-representable:{s}:") for k in losses)
    if cond == "system-not-in-target":
        s = cat.split(":")[1]
        return s not in TABLE["systems"].get(tgt, "")
    if cond == "nav-system-not-in-target":
        s = cat.split(":")[1]
        if tgt < "3":
            return s not in TABLE["nav_v2_systems"]["systems"]
        return s not in TABLE["nav_systems"].get(tgt, "")
    if cond == "with-system-loss":
        return any(k.startswith(("system-not-representable:", "system-removed-unresolvable:"))
                   for k in report.get("losses", {}))
    if cond == "with-record-removal":
        # a system dropped, or types with no target code (each claimed), or, between RINEX 2
        # and 3/4, records with nothing in any column: a list is rebuilt there from the
        # columns that hold data (compare_obs), so an all-blank record has no column (round
        # 23 generator: a 2.11 'L1' list whose one record was blank). Which epochs that
        # empties is checked against the files (compare_obs type_emptied, headers._epoch_checks)
        return (src < "3") != (tgt < "3") or any(
            k.startswith(("system-not-representable:", "system-removed-unresolvable:",
                          "obs-code-not-representable:")) for k in report.get("losses", {}))
    if cond == "with-event-loss":
        # the event's records were dropped one by one (claimed per record), or they only
        # described a system or phase entry the target drops (e.g. a QZSS SYS / PHASE SHIFT,
        # 3.03 -> 3.01: QZSS is defined from 3.02), or a SYS / SCALE FACTOR that RINEX 2
        # cannot hold and that was applied to the values after it (rule
        # OBS.V3V2.EVENT-SCALE-APPLIED); headers._event_checks checks which
        return any(k.startswith(("event-record-not-representable:", "event-record-deprecated:",
                                 "system-not-representable:", "system-removed-unresolvable:",
                                 "phase-shift-entry-dropped:"))
                   for k in report.get("losses", {})) or (
            tgt < "3" and "OBS.V3V2.EVENT-SCALE-APPLIED" in (report.get("rules") or {}))
    if cond == "label-deprecated-in-target":
        # strongly deprecated in RINEX 4, "should be ignored by RINEX decoders and encoders"
        # (rinex_4.00.txt Table A2 p.61)
        return cat.split(":", 1)[1] in ("SYS / PHASE SHIFT", "GLONASS COD/PHS/BIS") and tgt >= "4"
    if cond == "label-not-in-target":
        lab = cat.split(":", 1)[1]
        if lab in V4_ONLY_LABELS:
            return tgt < "4"
        if lab in V3_ONLY_LABELS:
            return tgt < "3" or (lab.startswith("GLONASS") and tgt < "3.02") or (
                lab.startswith("SYS / PHASE") and (tgt < "3.01" or tgt >= "4"))
        if lab == "WAVELENGTH FACT L1/2":
            return tgt >= "3"
        return False
    if cond == "lli-bit2-meaning":
        def meaning(v):
            return "AS" if v < "3" else (None if v < "3.01" else "BOC")
        return meaning(src) != meaning(tgt)
    if cond == "drop-unresolvable":
        return flags.get("drop_unresolvable", False)
    if cond == "dedupe":
        # --dedupe was given (the caller says so, or the report's rule NAV.DEDUPE does)
        return flags.get("dedupe", False) or "NAV.DEDUPE" in (report.get("rules") or {})
    if cond == "merge":
        return "NAV.MERGE" in (report.get("rules") or {})          # --merge was given
    raise ValueError(f"unknown condition {cond}")


def check(report, flags=None):
    """List of loss categories in the report that no rule allows."""
    flags = flags or {}
    kind = report["file_kind"]
    tgt = report["target_version"]
    # a --merge has several inputs, each of its own version: a loss is allowed if some input's
    # version allows it (Sol round 18: a 4.02 input's CNAV removal was judged as a 3.05 one's)
    srcs = [report["source_version"]] + [m["version"] for m in (report.get("input") or {}).get("merged", [])]
    bad = []
    for cat in report.get("losses", {}):
        ok = False
        for r in TABLE["rules"]:
            if r["kind"] != kind or not _match(r["category"], cat):
                continue
            if "target" in r and not (r["target"][0] <= tgt <= r["target"][1]):
                continue
            if any(("source" not in r or r["source"][0] <= src <= r["source"][1])
                   and _when(r.get("when"), kind, src, tgt, cat, report, flags) for src in srcs):
                ok = True
                break
        if not ok:
            bad.append(cat)
    return bad
