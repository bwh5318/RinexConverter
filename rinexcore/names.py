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


# Windows' rules for one file name ("Naming Files, Paths, and Namespaces", as Python 3.13's
# ntpath.isreserved applies them): no <>:"|?*\/ or control character, no trailing dot or
# blank, and no device name, also with an extension or blanks before it ('nul .txt'),
# including the superscript forms COM¹ COM² COM³ LPT¹ LPT² LPT³ and CONIN$ / CONOUT$.
_WIN_CHARS = frozenset('<>:"|?*\\/') | frozenset(chr(i) for i in range(32))
_WIN_DEVICES = (frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"})
                | frozenset(f"{p}{c}" for p in ("COM", "LPT") for c in "123456789¹²³"))
MAX_NAME = 255                    # the longest file name NTFS and the common POSIX file systems hold


def unsafe_file_name(name):
    """Why `name` cannot be written as one plain file name in a folder, on Windows or POSIX, or
    None if it can (a leading blank is refused too). Output, report and archive-member names
    are made from file names and header content (MARKER NAME), which a file may fill with
    anything, so every name is checked before it is used (Sol rounds 29-30)."""
    if not name or name in (".", ".."):
        return "no file name"
    if len(name) > MAX_NAME:
        return f"longer than {MAX_NAME} characters"
    if _WIN_CHARS.intersection(name):
        return 'a character a file name cannot hold (<>:"|?*\\/ or a control character)'
    if name[-1] in ". " or name[0] == " ":
        return "a leading blank, or a trailing dot or blank"
    if name.partition(".")[0].rstrip(" ").upper() in _WIN_DEVICES:
        return "a Windows device name"
    return None


def shown(name, n=80):
    """A name short enough for a message."""
    return repr(name) if len(name) <= n else repr(name[:n - 25] + "..." + name[-20:])


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
