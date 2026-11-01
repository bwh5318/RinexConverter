"""Meteorological conversion (PLAN §3.5 "Meteorological").

Only the epoch's year field (2 <-> 4 digits) and the version-gated header
records change. Met observation types (PR TD HR ZW ZD ZT, and WD WS RI HI from
2.11: rinex211.txt §10.3) are checked against the target version.
"""

from rinexcore.errors import NotRepresentableError
from rinexcore.header import HeaderRecord
from rinexcore.met import MetEpoch, MetFile

V211_TYPES = {"WD", "WS", "RI", "HI"}
V4_ONLY = {"DOI", "LICENSE OF USE", "STATION INFORMATION"}


def convert_met(src, target, report):
    out = MetFile()
    out.version = target
    out.version_str = target
    out.eol = src.eol
    keep = []
    for k, t in enumerate(src.types):
        if target < "2.11" and t in V211_TYPES:
            report.loss(f"met-type-not-representable:{t}", sum(1 for e in src.epochs if e.vals[k].strip()))
            continue
        keep.append(k)
    if src.types and not keep:
        # nothing of the file can be written (Sol round 20: an empty type list failed the
        # output check as an internal error), as for obs and nav files
        raise NotRepresentableError(
            f"RINEX {target} has none of this file's meteorological types ({', '.join(src.types)}; "
            "WD, WS, RI and HI exist from 2.11: rinex211.txt section 10.3); nothing to write")
    out.types = [src.types[k] for k in keep]
    hdr = []
    placed = False
    for r in src.header:
        lab = r.label
        if lab == "RINEX VERSION / TYPE":
            hdr.append(HeaderRecord(lab, f"{target:>9s}" + " " * 11 + "METEOROLOGICAL DATA".ljust(40)))
            continue
        if lab == "# / TYPES OF OBSERV":
            if not placed:
                placed = True
                codes = out.types
                for k in range(0, max(1, len(codes)), 9):
                    chunk = codes[k:k + 9]
                    head = f"{len(codes):6d}" if k == 0 else " " * 6
                    rec = HeaderRecord(lab, head + "".join(f"    {c:>2s}" for c in chunk))
                    hdr.append(rec)
                if len(keep) == len(src.types):
                    # keep the source lines verbatim when nothing changed
                    src_lines = [x for x in src.header if x.label == lab]
                    hdr[-len(range(0, max(1, len(codes)), 9)):] = src_lines
            continue
        if lab == "SENSOR MOD/TYPE/ACC" or lab == "SENSOR POS XYZ/H":
            t = r.content[57:59].strip()
            if t and target < "2.11" and t in V211_TYPES:
                report.loss(f"header-record-not-representable:{lab}:{t}", 1)
                continue
            hdr.append(r)
            continue
        if lab in V4_ONLY and target < "4":
            if target == src.version:
                # a record another version defines, in the file's own version: carried as
                # written (Sol round 16: claimed, a loss the table refuses for a same-version
                # conversion)
                report.rule("MET.HDR.NONSTANDARD-CARRIED")
                hdr.append(r)
            else:
                report.loss(f"header-record-not-representable:{lab}", 1)
            continue
        hdr.append(r)
    out.header = hdr
    for e in src.epochs:
        out.epochs.append(MetEpoch(e.time, [e.vals[k] for k in keep], e.lineno))
    if (target < "3.02") != (src.version < "3.02"):
        report.rule("MET.YEAR-DIGITS")
    return out
