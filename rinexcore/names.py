"""RINEX file names: RINEX 2 short names <-> RINEX 3/4 long names.

Short (rinex211.txt §4):  ssssdddf.yyt        daily (f = 0) or hourly (f = a..x)
                          ssssdddhmm.yyt      high-rate (h = a..x, mm = start minute)
Long (rinex305.txt §4):   SSSSMRCCC_S_YYYYDDDHHMM_PPU_FFU_TT.FMT[.cmp]
"""

import re

SHORT = re.compile(r"^(?P<s>[a-z0-9]{4})(?P<ddd>\d{3})(?P<f>[0a-x])(?P<mm>\d{2})?\.(?P<yy>\d{2})(?P<t>[a-z])"
                   r"(?:\.(?P<cmp>Z|gz))?$", re.I)
LONG = re.compile(r"^(?P<id>[A-Z0-9]{9})_(?P<src>[RSU])_(?P<y>\d{4})(?P<ddd>\d{3})(?P<hh>\d{2})(?P<mi>\d{2})_"
                  r"(?P<per>\d{2}[MHDYU])(?:_(?P<frq>\d{2}[CZSMHDU]))?_(?P<tt>[A-Z]{2})\.(?P<fmt>rnx|crx)"
                  r"(?:\.(?P<cmp>gz|Z|bz2|zip))?$", re.I)


def parse(name):
    m = LONG.match(name)
    if m:
        d = m.groupdict()
        d["style"] = "long"
        return d
    m = SHORT.match(name)
    if m:
        d = m.groupdict()
        d["style"] = "short"
        return d
    return None


def strip_compression(name):
    for ext in (".gz", ".Z", ".z", ".bz2", ".zip"):
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def _interval_code(sec):
    if sec is None:
        return "00U"
    sec = float(sec)
    if sec >= 1 and sec == int(sec):
        s = int(sec)
        if s < 100:
            return f"{s:02d}S"
        if s % 60 == 0 and s // 60 < 100:
            return f"{s // 60:02d}M"
        return "00U"
    if sec > 0:
        hz = round(1 / sec)
        if hz < 100:
            return f"{hz:02d}Z"
    return "00U"


def short_name(kind, site, year, doy, hour=None, minute=None, period=None, crx=False, nav_type="n"):
    site = (site or "xxxx")[:4].lower().ljust(4, "x")
    if kind == "obs":
        t = "d" if crx else "o"
    elif kind == "met":
        t = "m"
    else:
        t = nav_type
    if period in (None, "01D") or hour is None:
        f = "0"
        return f"{site}{doy:03d}{f}.{year % 100:02d}{t}"
    h = chr(ord("a") + hour)
    if period == "01H":
        return f"{site}{doy:03d}{h}.{year % 100:02d}{t}"
    return f"{site}{doy:03d}{h}{minute or 0:02d}.{year % 100:02d}{t}"


def long_name(kind, ident, src, year, doy, hour, minute, period, interval, content, crx=False):
    fmt = "crx" if crx else "rnx"
    if kind == "obs":
        return f"{ident}_{src}_{year:04d}{doy:03d}{hour:02d}{minute:02d}_{period}_{interval}_{content}.{fmt}"
    return f"{ident}_{src}_{year:04d}{doy:03d}{hour:02d}{minute:02d}_{period}_{content}.{fmt}"
