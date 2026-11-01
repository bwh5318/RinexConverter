"""Companion inputs (PLAN §1 clause 8, source 2): GLONASS frequency channels.

A channel number is a physical value, so it is never invented: it comes from a
navigation file (GLONASS record, BROADCAST ORBIT 2 field 4 "frequency number":
rinex211.txt Table A11, rinex305.txt Table A10, rinex_4.02.txt Table A15), from
the GLONASS SLOT / FRQ # header of a RINEX >= 3.02 observation file, or from a
plain table with lines 'R01 1'.
"""

from collections import Counter

from rinexcore.errors import InvocationError, RinexError
from rinexcore.nav import token_value
from rinexcore.rinexfile import open_container, read_path, sniff, split_lines

FCN_INDEX = 10


def _from_nav(model):
    votes = {}
    for r in model.records:
        if r.kind != "EPH" or r.system != "R" or len(r.vals) <= FCN_INDEX:
            continue
        if r.msg not in (None, "FDMA"):
            continue                       # CDMA (L1OC/L3OC) records carry no FDMA channel
        v = token_value(r.vals[FCN_INDEX])
        if v is None:
            continue
        votes.setdefault(r.sat, Counter())[int(v)] += 1
    return {s: c.most_common(1)[0][0] for s, c in votes.items()}


def _from_obs(model):
    from .obsconv import parse_glonass_slots
    return parse_glonass_slots([r for r in model.header if r.label == "GLONASS SLOT / FRQ #"])


def _from_table(text):
    out = {}
    for line in text.splitlines():
        t = line.split("#", 1)[0].split()
        if len(t) < 2:
            continue
        s = t[0].upper()
        if s[0] != "R":
            s = "R" + s
        try:
            out[f"R{int(s[1:]):02d}"] = int(t[1])
        except ValueError:
            raise InvocationError(f"bad GLONASS channel table line {line!r}") from None
    return out


def glonass_channels(nav_paths, glo_fcn_path):
    """({'R01': 1, ...}, description of the source) or (None, None)."""
    key = (tuple(nav_paths or ()), glo_fcn_path)
    if key not in _CACHE:
        _CACHE[key] = _glonass_channels(nav_paths, glo_fcn_path)
    fcn, src = _CACHE[key]
    return (dict(fcn) if fcn else None), src


_CACHE = {}


def _glonass_channels(nav_paths, glo_fcn_path):
    from .engine import load_bytes
    fcn = {}
    srcs = []
    paths = list(nav_paths or [])
    if glo_fcn_path:
        paths.insert(0, glo_fcn_path)      # the user's explicit table takes precedence
    for p in paths:
        data = read_path(p)
        try:
            c = open_container(data)
            lines, _ = split_lines(c.payload)
            is_rinex = lines and lines[0][60:80].strip() == "RINEX VERSION / TYPE"
        except RinexError:
            is_rinex = False
        if not is_rinex:
            got = _from_table(data.decode("latin-1"))
            srcs.append(f"table:{p}")
        else:
            try:
                info = sniff(lines)
                if info.kind == "obs":
                    # only the header is needed (GLONASS SLOT / FRQ #): don't parse the data
                    from rinexcore.header import read_header
                    from rinexcore.obs import header_lines
                    hl, _ = header_lines(c.payload)
                    recs, _ = read_header(hl)
                    from .obsconv import parse_glonass_slots
                    got = parse_glonass_slots([r for r in recs if r.label == "GLONASS SLOT / FRQ #"])
                    srcs.append(f"companion-obs:{p}")
                elif info.kind == "nav":
                    ld = load_bytes(data, lenient=True)    # only the channel numbers are used
                    got = _from_nav(ld.model)
                    srcs.append(f"companion-nav:{p}")
                else:
                    got = {}
            except RinexError as e:
                raise InvocationError(f"companion file {p} is unreadable: {e}") from None
        for k, v in got.items():
            fcn.setdefault(k, v)
    if not fcn:
        return None, None
    return fcn, ";".join(srcs)
