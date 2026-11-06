"""Compact RINEX (Hatanaka) codec: CRINEX 1.0, 3.0 and 3.1, pure Python.

Ported from the GSI reference programs RNXCMP 4.2.0 (``crx2rnx.c`` and
``rnx2crx.c``, in ``specs/hatanaka/src/RNXCMP_4.2.0_src/source/``). The format
and the original software are by Yuki Hatanaka, Geospatial Information
Authority of Japan:

    Hatanaka, Y. (2008), A Compression Format and Tools for GNSS Observation
    Data, Bulletin of the Geospatial Information Authority of Japan, 55, 21-30.

The GSI licence requires that citation in any port or modification.

The grammar, with line references into the C sources, is in
``docs/HATANAKA.md``; read it before changing this module.

* ``crx_to_rnx`` / ``iter_crx_to_rnx`` reproduce CRX2RNX 4.2.0 byte for byte
  on valid input (LF line ends, i.e. CRX2RNX as built on Unix), including its
  number formatting (``.123`` with no leading zero), its two value quirks
  (a negative clock whose last 8 digits are zero, and the sign of
  ``-0ddddd`` fields; ``fix_clock_bug=True`` corrects the first) and the
  stale-buffer behaviour of its header label tests. Where CRX2RNX would warn,
  skip epochs or read memory it never wrote, we raise :class:`CorruptError`.
  Verified on all 299 CRX files of the corpus (tests/oracle/crx2rnx_sha256.json).
* ``rnx_to_crx`` makes the same choices as RNX2CRX 4.2.0 (difference order 3,
  arc restart on "large cycle slips", the same text differences and layout),
  but refuses (``CorruptError``) any input it cannot represent so that
  CRX2RNX gives the same values back, instead of silently altering it.

Both directions have a fast path for the common lines (every field steady or blank as in
the previous epoch: the satellite's state in columns, the line summed or differenced with
map() and printed with one %-format), which falls back to the general code on anything
else; ``_FAST = False`` turns it off, and tests/unit/test_hatanaka_speed_equivalence.py
checks the two give the same bytes and errors.

Standard library only; bytes in, bytes out (RINEX is never handled as text).
Every malformed input raises ``rinexcore.errors.CorruptError`` with a line
number and a rule id ``CRX.*`` (decoder) or ``CRX.ENC.*`` (encoder).
"""

import datetime
import re
from array import array
from itertools import accumulate, compress, islice, repeat
from operator import add, sub, truediv

from .. import __version__ as _PKG_VERSION
from ..errors import CorruptError
from . import spool

__all__ = ["is_crx", "crx_to_rnx", "iter_crx_to_rnx", "rnx_to_crx"]

# --------------------------------------------------------------------------
# constants and translate tables

_SP, _AMP, _GT, _DOT = 32, 38, 62, 46
_AMP_TO_SP = bytes.maketrans(b"&", b" ")
_SP_TO_AMP = bytes.maketrans(b" ", b"&")
_NONSP_TO_AMP = bytes(32 if i == 32 else 38 for i in range(256))
_KEEP_TBL = bytes(255 if i == 32 else 0 for i in range(256))   # 0xFF where blank
_EQ_TBL = bytes(255 if i == 0 else 0 for i in range(256))      # 0xFF where zero
_C_SPACE = b" \t\n\r\x0b\x0c"                                   # C isspace()
_FIELD_CHARS = b"0123456789-& "
_LABEL_CRX = b"CRINEX VERS   / TYP"          # strncmp(..., 19) at C:417
_LABEL_TYPES2 = b"# / TYPES OF OBSERV"       # 19 characters, C:431
_LABEL_TYPES3 = b"SYS / # / OBS TYPES"       # 19 characters, C:433
_LABEL_VERSION = b"RINEX VERSION / TYPE"     # 20 characters, C:423
_LABEL_EOH = b"END OF HEADER"                # 13 characters, C:437
_BUF = 2048                                  # MAXCLM

ARC_ORDER = 3            # rnx2crx.c ARC_ORDER
_SLIP_LIMIT = 100000     # rnx2crx.c E:648
# Table sizes of RNXCMP 4.2.0. CRX2RNX stops with an error beyond them, so we
# refuse the same inputs (decoder) and never write them (encoder).
MAXSAT = 100             # satellites per epoch (C:115, error 6)
MAXTYPE = 100            # observation types per system (C:116, error 16)
MAX_DIFF_ORDER = 5       # arc order (C:121, error 7)
MAX_LINE = 2046          # longest line fgets(.., 2048) reads whole (C:117, error 13)

# Observation values with |v| < 1000 (i.e. |obs| < 1): CRX2RNX prints them
# without a leading zero (putfield, C:794-806).
_SMALL = [(b"         -.%03d" % -v) if v < 0 else (b"          .%03d" % v)
          for v in range(-999, 1000)]
_BLANK14 = b" " * 14
_BLANK16 = b" " * 16
_NONES = (None,) * MAXTYPE
_K1000 = (1000,) * MAXTYPE   # map(truediv, values, _K1000): the fast paths' value / 1000
_SPLIT_CHUNK = 1 << 22    # bytes a chunk of _split_lines
_ONES = b"\x01" * MAXTYPE     # blank-field masks (decoder fast path)
_ZEROS = b"\x00" * MAXTYPE
_DOT_SEL = bytes(1 if i == 46 else 0 for i in range(256))   # '.' -> 1 (encoder fast path)
_DIG_DOT = bytes(46 if 48 <= i <= 57 else 32 if i == 32 else 120 for i in range(256))
# The decoder's fast path (lines whose fields are all steady order-3 arcs or blank, as in the
# previous epoch) and the encoder's (fields all steady or blank) give the same bytes, errors
# and states as the general code; tests/unit/test_hatanaka_speed_equivalence.py sets this
# False to compare the two.
_FAST = True
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _corrupt(msg, line, rule):
    return CorruptError(msg, line=line, rule=rule)


class CrxCannotHold(CorruptError):
    """A valid RINEX file that Compact RINEX cannot carry through RNXCMP 4.2.0; the caller
    may write plain RINEX instead (``plain_rule`` names the warning to give):

    * CRX.ENC.STALE-LABEL: an event line (the records of an epoch with event flag 6, copied
      line by line: E:491-528) shorter than the observation-type label, after a longer line
      that held the label. RNX2CRX and CRX2RNX test columns 61-79 of their line buffer for
      that label whatever the line's length (E:505, E:521; C:511-516), so they would read
      the stale label of the earlier line and take the record for a type count.
    * CRX.ENC.PICOSEC: a RINEX 4.02 picosecond field (optional per epoch: rinex_4.02.txt
      Table A3) that stops part-way through the file; CRINEX 3.1 differences it from the
      previous epoch's, so CRX2RNX would repeat the last value (section 6 of
      docs/HATANAKA.md).
    * CRX.ENC.FIELD (only for a field that reads as an F14.3 number): a value written with
      its point elsewhere than column 11 or with other than three decimals (`1050010.1`).
      RNX2CRX reads the digits around a point in column 11 (E:627-671), so it cannot take
      it; the value text is kept as written everywhere else (rinexcore.obs), so it is not
      rewritten here either (_field_error)."""

    def __init__(self, message, *, plain_rule, **kw):
        super().__init__(message, **kw)
        self.plain_rule = plain_rule


def _c_atoi(buf, i):
    """C atoi(&buf[i]) on a NUL-terminated buffer (bytes or bytearray)."""
    n = len(buf)
    while i < n and buf[i] in _C_SPACE:
        i += 1
    neg = False
    if i < n and buf[i] in b"+-":
        neg = buf[i] == 45
        i += 1
    v = 0
    while i < n and 48 <= buf[i] <= 57:
        v = v * 10 + buf[i] - 48
        i += 1
    return -v if neg else v


def _chop_blank(s):
    """CHOP_BLANK (C:111): drop trailing blanks, but an all-blank line keeps one."""
    t = s.rstrip(b" ")
    if not t and s:
        return b" "
    return t


def _repair(s, ds):
    """repair() (C:691-705): apply text difference ds to s."""
    ld = len(ds)
    if not ld:
        return s
    ls = len(s)
    if ld <= ls:
        if ds.count(32) == ld:
            return s
        n = ld
        d = ds
    else:
        if not ls:
            return ds.translate(_AMP_TO_SP)
        n = ls
        d = ds[:n]
    keep = int.from_bytes(d.translate(_KEEP_TBL), "big")
    mid = ((int.from_bytes(s[:n], "big") & keep)
           | (int.from_bytes(d.translate(_AMP_TO_SP), "big") & ~keep)).to_bytes(n, "big")
    if ld > n:
        return mid + ds[n:].translate(_AMP_TO_SP)
    return mid + s[n:]


def _strdiff(a, b):
    """strdiff() (E:673-694) without its trailing-blank trim and LF."""
    if a == b:
        return b""
    la, lb = len(a), len(b)
    n = la if la < lb else lb
    if n:
        x = (int.from_bytes(a[:n], "big") ^ int.from_bytes(b[:n], "big")).to_bytes(n, "big")
        eq = int.from_bytes(x.translate(_EQ_TBL), "big")
        b2 = int.from_bytes(b[:n].translate(_SP_TO_AMP), "big")
        sp = int.from_bytes(b" " * n, "big")
        mid = ((b2 & ~eq) | (sp & eq)).to_bytes(n, "big")
    else:
        mid = b""
    if la > n:
        return mid + a[n:].translate(_NONSP_TO_AMP)
    return mid + b[n:]


class _CBuf:
    """A reused 2048-byte C line buffer (CRX2RNX's ``line``/``dline``).

    The header and event label tests of CRX2RNX read columns 61-79 of the
    buffer even when the current line is shorter, i.e. they see what earlier
    lines left there. Keeping the buffer reproduces that exactly.
    """

    __slots__ = ("b",)

    def __init__(self):
        self.b = bytearray(_BUF)

    def fgets(self, raw, nl, content):
        """fgets() of raw (+LF if nl), then the LF/CR of content set to NUL."""
        b = self.b
        if nl:
            n = len(raw)
            b[0:n + 2] = raw + b"\n\x00"
            b[len(content)] = 0
        else:
            b[0:len(raw) + 1] = raw + b"\x00"

    def nul(self, i):
        self.b[i] = 0

    def at(self, i):
        b = self.b
        return b[i] if i < len(b) else 0

    def label(self, i, lab):
        return bytes(self.b[i:i + len(lab)]) == lab


def _types_update(buf, state, line_no, rule):
    """The # / TYPES OF OBSERV and SYS / # / OBS TYPES tests (C:431-436, C:511-516).

    More than MAXTYPE (100) types is an error, as in CRX2RNX (error 16); for
    RINEX 2 CRX2RNX has no test and would overrun its arrays.
    """
    lab = bytes(buf.b[60:79])
    if lab == _LABEL_TYPES2 and buf.at(5) != _SP:
        n = state[0] = _c_atoi(buf.b, 0)
    elif lab == _LABEL_TYPES3:
        c0 = buf.at(0)
        if c0 == _SP:
            return
        n = state[1][c0] = _c_atoi(buf.b, 3)
    else:
        return
    if n > MAXTYPE:
        raise _corrupt(f"more than {MAXTYPE} observation types", line_no, rule)


def is_crx(data):
    """True if the first line carries the label ``CRINEX VERS   / TYPE`` (col 61)."""
    data = bytes(data[:4096])
    first = data.split(b"\n", 1)[0]
    if first.endswith(b"\r"):
        first = first[:-1]
    return first[60:80] == b"CRINEX VERS   / TYPE"


# --------------------------------------------------------------------------
# decoder


class _Lines:
    """The lines of data (without LF; with strip_cr, without the CR before it) by index, from
    an array of line starts: 8 bytes a line instead of one bytes object each, which for a
    24 h 1 Hz file (6 million lines) was more than the file itself. Indexing, len() and
    slices, as a list of lines would give."""

    __slots__ = ("data", "starts", "n", "n_full", "strip_cr")

    def __init__(self, data, starts, n, n_full, strip_cr=False):
        self.data, self.starts, self.n, self.n_full, self.strip_cr = data, starts, n, n_full, strip_cr

    def __len__(self):
        return self.n

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[k] for k in range(*i.indices(self.n))]
        if i < 0:
            i += self.n
        if not 0 <= i < self.n:
            raise IndexError(i)
        a = self.starts[i]
        b = self.starts[i + 1] - 1 if i + 1 < len(self.starts) else len(self.data)
        if self.strip_cr and i < self.n_full and b > a and self.data[b - 1] == 13:
            b -= 1
        return self.data[a:b]


def _split_lines(data, rule_prefix):
    """(raw lines, CR-stripped lines, number of lines that end with LF)."""
    nul = data.find(b"\x00")
    if nul >= 0:
        raise _corrupt("NUL byte in the data", data.count(b"\n", 0, nul) + 1,
                       rule_prefix + "NUL")
    starts = array("q", [0])
    # The line starts by split() and accumulate() over chunks that end with an LF (C speed;
    # one chunk's lines held at a time). A chunk with a line longer than MAX_LINE, or a
    # window without LF, is left to the loop below, which goes on from the chunk's start.
    a = 0
    while True:
        q = data.rfind(b"\n", a, a + _SPLIT_CHUNK)
        if q < 0:
            break
        lens = list(map(len, data[a:q].split(b"\n")))
        if max(lens) > MAX_LINE:
            break
        starts.extend(islice(accumulate(map(add, lens, repeat(1)), initial=a), 1, None))
        a = q + 1
    pos = data.find(b"\n", a)
    while pos >= 0:
        if pos - starts[-1] > MAX_LINE:
            raise _corrupt(f"line longer than {MAX_LINE} characters", len(starts),
                           rule_prefix + "LINE_TOO_LONG")
        starts.append(pos + 1)
        pos = data.find(b"\n", pos + 1)
    if data.endswith(b"\n") or not data:
        n = n_full = len(starts) - 1          # (the last start is the end of the data)
    else:
        n = len(starts)
        n_full = n - 1
        if len(data) - starts[-1] > MAX_LINE:
            raise _corrupt(f"line longer than {MAX_LINE} characters", n,
                           rule_prefix + "LINE_TOO_LONG")
    lines = _Lines(data, starts, n, n_full)
    cont = _Lines(data, starts, n, n_full, strip_cr=True) if b"\r" in data else lines
    return lines, cont, n_full


def _parse_clock(t, line_no):
    """read_clock (C:440-467) on the digits after an optional N&: value."""
    neg = t[:1] == b"-"
    digits = t[1:] if neg else t
    if not digits or not digits.isdigit():
        raise _corrupt(f"receiver clock field {t!r} is not an integer", line_no, "CRX.CLOCK")
    if len(digits) < 9:
        return int(t)
    lower = int(t[-8:])
    upper = int(t[:-8])
    if upper < 0:
        lower = -lower
    return upper * 100000000 + lower


def _fmt_clock(v, shift, line_no, fix_bug):
    """print_clock (C:809-848), including CRX2RNX 4.2.0's sign quirk."""
    yu = abs(v) // 100000000
    if v < 0:
        yu = -yu
    yl = v - yu * 100000000
    if fix_bug:
        sgn = -1 if v < 0 else 1
    else:
        sgn = -1 if yl < 0 else 1
    tmp = b"%.*d" % (shift + 1, yu * 10 + sgn)
    n = len(tmp) - 1
    digits = tmp[n - shift:n]
    b0 = b1 = b" "
    if n > shift:
        b1 = tmp[n - shift - 1:n - shift]
        if n > shift + 1:
            b0 = tmp[n - shift - 2:n - shift - 1]
            if n > shift + 2:
                raise _corrupt("clock offset is out of the RINEX range", line_no, "CRX.RANGE")
    return b0 + b1 + b"." + digits + b"%08d" % abs(yl)


def _num_field(f, line_no):
    """The value of one numeric field (getdiff, C:754-765)."""
    try:
        v = int(f)
    except ValueError:
        raise _corrupt(f"observation field {f!r} is not an integer", line_no,
                       "CRX.FIELD") from None
    # C splits off the lower 5 digits; "-0ddddd..." then loses its sign.
    if v <= 0 and len(f) > 6 and f[1] == 48 and f[0] == 45:
        upper = int(f[:-5])
        if upper == 0:
            v = int(f[-5:])
    return v


def _bad_value(v, line_no):
    raise _corrupt(f"observation value {v} is out of the F14.3 range", line_no, "CRX.RANGE")


def _fmt_value(v, line_no):
    """putfield (C:772-807): F14.3 with no leading zero; error 17 out of range."""
    if -1000 < v < 1000:
        return _SMALL[v + 999]
    if v > 0:
        if v >= 10000000000000:
            _bad_value(v, line_no)
        return b"%10d.%03d" % divmod(v, 1000)
    if v <= -1000000000000:
        _bad_value(v, line_no)
    return b"%10d.%03d" % (-(-v // 1000), -v % 1000)


def _out_template(pairs, mask, sid, rv2):
    """The decoder fast path's printed lines of one satellite: (mask, fmt, n, exact).

    fmt is a %-format with one %14.3f per non-blank field (mask: None when no field is
    blank, else bytes with 0 at the blank fields) and the flag pairs, blank fields, line
    breaks and trailing-blank trims of the general code (C:633-682) as literal text; n is
    the length of fmt % values when every value fits F14.3 (|v| < 10**13 / 10**12 for a
    negative, putfield's range: a longer output means one does not). %14.3f of v / 1000
    prints the digits of _fmt_value (v < 2**53, and division and printing are correctly
    rounded) except for |v| < 1000, where it prints `0.ddd` / `-0.ddd` for _SMALL's
    `.ddd` / `-.ddd`: the caller replaces b" 0." and b"-0.", which a printed value holds
    only there (its one point has 10 columns of integer part, a digit before and after
    it), and which cannot span a value and the text beside it (a value starts with a
    blank, '-' or a digit, never '.', and ends with two digits). exact is False when the
    literal text holds either pattern itself (blank field + flags `0.`): no fast path."""
    if mask is None:
        # no blank field (the common case): the literal text between two values is one
        # flag pair, or a trimmed pair + LF, too short to hold a pattern; only the id can
        nt = len(pairs)
        lit = sid + b"".join(pairs)
        if 37 in lit:                                    # '%'
            sid = sid.replace(b"%", b"%%")
            pairs = [p.replace(b"%", b"%%") for p in pairs]
        if rv2:
            fmt = b"".join([(b"%14.3f" + b"%14.3f".join(pairs[k:k + 5])).rstrip(b" ") + b"\n"
                            for k in range(0, nt, 5)])
        else:
            fmt = (sid + b"%14.3f" + b"%14.3f".join(pairs)).rstrip(b" ") + b"\n"
        return (None, fmt, len(fmt) + 8 * nt - lit.count(b"%"),
                sid != b" 0." and sid != b"-0.")
    segs = []
    run = sid
    last = len(pairs) - 1
    for j, p in enumerate(pairs):
        if mask[j]:
            segs.append(run)
            run = p
        else:
            run += _BLANK14 + p
        if rv2 and (j % 5 == 4 or j == last):      # RINEX 2: 5 fields a line
            run = run.rstrip(b" ") + b"\n"           # (values end in a digit: the trim
    if not rv2:                                      #  stops at the last value)
        run = run.rstrip(b" ") + b"\n"
    segs.append(run)
    lit = b"\x00".join(segs)                         # (no NUL in the data: _split_lines)
    return (mask, b"%14.3f".join([s.replace(b"%", b"%%") for s in segs]),
            len(lit) - (len(segs) - 1) + 14 * (len(segs) - 1),
            b" 0." not in lit and b"-0." not in lit)


def iter_crx_to_rnx(data, *, chunk_size=1 << 20, fix_clock_bug=False):
    """Decode Compact RINEX bytes; yield RINEX bytes in chunks of ~chunk_size.

    On malformed input the chunks yielded so far are exactly what CRX2RNX
    would have printed before stopping, then CorruptError is raised.
    ``fix_clock_bug=True`` prints negative clocks whose last 8 digits are zero
    correctly instead of the way CRX2RNX 4.2.0 does (docs/HATANAKA.md §5).
    """
    buf = []
    size = 0
    try:
        for piece in _decode(bytes(data), fix_clock_bug):
            buf.append(piece)
            size += len(piece)
            if size >= chunk_size:
                yield b"".join(buf)
                buf = []
                size = 0
    except CorruptError:
        if buf:
            yield b"".join(buf)
        raise
    if buf:
        yield b"".join(buf)


def crx_to_rnx(data, *, fix_clock_bug=False):
    """Decode a whole Compact RINEX file (bytes) to RINEX observation bytes (held once: io.spool)."""
    return spool.join_bytes(_decode(bytes(data), fix_clock_bug))


def _decode(data, fix_clock_bug):
    lines, cont, n_full = _split_lines(data, "CRX.")
    nlines = len(lines)
    pos = 0

    # ---------------- header (C:411-438)
    hbuf = _CBuf()

    def hread():
        nonlocal pos
        if pos >= n_full:
            raise _corrupt("the file ends inside the header", pos + 1, "CRX.TRUNCATED")
        c = cont[pos]
        hbuf.fgets(lines[pos], True, c)
        pos += 1
        return c

    c = hread()
    if bytes(hbuf.b[0:3]) not in (b"1.0", b"3.0", b"3.1") or not hbuf.label(60, _LABEL_CRX):
        raise _corrupt("not a Compact RINEX 1.0, 3.0 or 3.1 file", 1, "CRX.NOT_CRINEX")
    crinex_version = _c_atoi(c, 0)
    crinex_full = (c[0] - 48) * 10 + (c[2] - 48)
    hread()                                   # CRINEX PROG / DATE: not printed
    c = _chop_blank(hread())
    hbuf.nul(len(c))
    yield c + b"\n"
    if not hbuf.label(60, _LABEL_VERSION) or hbuf.at(5) not in b"234":
        raise _corrupt("line 3 is not a RINEX 2.x, 3.x or 4.x VERSION / TYPE line", 3,
                       "CRX.RINEX_VERSION")
    rinex_version = _c_atoi(c, 0)
    types = [0, [-1] * 256]                   # ntype (RINEX 2), ntype_gnss[]
    hdr = []
    try:
        while True:
            c = _chop_blank(hread())
            hbuf.nul(len(c))
            hdr.append(c + b"\n")
            _types_update(hbuf, types, pos, "CRX.MAXTYPE")
            if hbuf.label(60, _LABEL_EOH):
                break
    except CorruptError:
        yield b"".join(hdr)            # CRX2RNX has printed these lines already
        raise
    yield b"".join(hdr)
    del hdr

    # ---------------- data section (C:200-337)
    rv2 = rinex_version == 2
    rv3 = rinex_version >= 3
    crx1 = crinex_version == 1
    crx3 = crinex_version == 3
    crx31 = crinex_full > 30
    if rv2:
        ep_from, ep_to = b"&", b" "
        p_event, p_nsat, p_sat, shift, offset = 28, 29, 32, 1, 3
    else:
        ep_from, ep_to = b">", b">"
        p_event, p_nsat, p_sat, shift, offset = 31, 32, 41, 4, 6
    ep_to_i = ep_to[0]
    dbuf = _CBuf()
    line = b""                 # repaired epoch text (C: static line[])
    old_ids = {}               # satellite id -> index in the previous epoch
    dy0 = []                   # per previous satellite: list of field states
    flag1 = []                 # per previous satellite: 2*ntype flag bytes
    clk_order = 0
    clk_arc = 0
    clk_hist = [0]
    picosec = b""
    small = _SMALL
    blank14 = _BLANK14
    blank16 = _BLANK16
    field_chars = _FIELD_CHARS
    data, starts = lines.data, lines.starts
    strip_cr = cont is not lines
    # Fast path (see _out_template): RINEX 2 and 3/4 layouts with at least one type. A
    # satellite whose fields are all steady order-3 arcs or blank is kept in column form,
    # the tuple (mask, values, d1s, d2s, ntype) (mask None: no blank field; else 0 at the
    # blanks, the lists holding the non-blank fields only), instead of the list of field
    # states; a line with the same blanks and a plain difference in every other field is
    # then summed with map() and printed with one %-format.
    fast = _FAST and (rv2 or rv3)
    tmpl_of = _out_template
    tcache = {}                # (id, mask, fl) -> _out_template(...)
    rcache = {}                # (fl, flag diff) -> fl repaired
    pmasks = {}                # nt * 256 + n -> mask of n fields then nt - n blank ones

    while pos < nlines:
        c = cont[pos]
        dbuf.fgets(lines[pos], pos < n_full, c)
        pos += 1
        # ---- SKIP: (C:221-239)
        eof = False
        while True:
            if crx3:
                while c[:1] == b"&":                     # escape lines
                    if pos >= nlines:
                        eof = True
                        break
                    c = cont[pos]
                    dbuf.fgets(lines[pos], pos < n_full, c)
                    pos += 1
                if eof:
                    break
            first = c[:1]
            if first == ep_from:
                dbuf.b[0] = ep_to_i
                c = ep_to + c[1:]
                ev = dbuf.at(p_event)
                if ev != 48 and ev != 49:
                    # ---- put_event_data (C:494-533)
                    while True:
                        dbuf.b[0] = ep_to_i
                        c = _chop_blank(ep_to + c[1:])
                        dbuf.nul(len(c))
                        ev_out = [c + b"\n"]
                        if len(c) > 29:
                            nrec = _c_atoi(dbuf.b, p_event + 1)
                            for _ in range(nrec):
                                if pos >= n_full:
                                    yield b"".join(ev_out)
                                    raise _corrupt("the file ends inside an event record",
                                                   pos + 1, "CRX.TRUNCATED")
                                h = cont[pos]
                                dbuf.fgets(lines[pos], True, h)
                                pos += 1
                                h = _chop_blank(h)
                                dbuf.nul(len(h))
                                ev_out.append(h + b"\n")
                                try:
                                    _types_update(dbuf, types, pos, "CRX.MAXTYPE")
                                except CorruptError:
                                    yield b"".join(ev_out)
                                    raise
                        yield b"".join(ev_out)
                        while True:
                            if pos >= nlines:
                                eof = True
                                break
                            raw = lines[pos]
                            nl = pos < n_full
                            if nl:
                                dbuf.b[0:len(raw) + 2] = raw + b"\n\x00"
                            else:
                                dbuf.b[0:len(raw) + 1] = raw + b"\x00"
                            pos += 1
                            if crx3 and raw[:1] == b"&":
                                continue
                            break
                        if eof:
                            break
                        c = cont[pos - 1]
                        if nl:
                            dbuf.nul(len(c))
                        evc = dbuf.at(p_event)
                        if c[:1] != ep_from or len(c) < 29 or not 48 <= evc <= 57:
                            raise _corrupt("an event record must be followed by an "
                                           "initialised epoch", pos, "CRX.EVENT")
                        if evc == 48 or evc == 49:
                            break
                    if eof:
                        break
                    continue                              # goto SKIP
                line = b""
                old_ids = {}
            elif first == b"\x1a":
                eof = True                                # DOS EOF
            break
        if eof:
            break
        ep_line_no = pos

        # ---- epoch line (C:241-254)
        line = _repair(line, c)
        nline = len(line)
        if (line[:1] != ep_to or nline < 26 + offset or line[offset + 23] != _SP
                or line[offset + 24] != _SP or not 48 <= line[offset + 25] <= 57):
            raise _corrupt("malformed epoch line (CRX2RNX would skip to the next "
                           "initialised epoch)", ep_line_no, "CRX.EPOCH")
        line = line.rstrip(b" ")
        nsat = _c_atoi(line, p_nsat)
        if nsat < 0:
            raise _corrupt("negative number of satellites", ep_line_no, "CRX.EPOCH")
        if nsat > MAXSAT:
            raise _corrupt(f"more than {MAXSAT} satellites in one epoch", ep_line_no,
                           "CRX.MAXSAT")
        sl = line[p_sat:p_sat + 3 * nsat]
        if len(sl) < 3 * nsat:
            raise _corrupt(f"the satellite list is shorter than {nsat} satellites",
                           ep_line_no, "CRX.SATLIST")
        ids = [sl[k:k + 3] for k in range(0, 3 * nsat, 3)]
        if rv2:
            if types[0] > MAXTYPE:
                raise _corrupt(f"more than {MAXTYPE} observation types", ep_line_no,
                               "CRX.MAXTYPE")
            nts = [types[0]] * nsat
        else:
            tg = types[1]
            nts = [tg[s[0]] for s in ids]
            if nsat and min(nts) < 0:                 # (the first such satellite)
                k = next(k for k in range(nsat) if nts[k] < 0)
                raise _corrupt(f"satellite {ids[k]!r}: GNSS type not defined in the "
                               "header", ep_line_no, "CRX.SYS")
        if old_ids:
            sattbl = [old_ids.get(s, -1) for s in ids]
        else:
            sattbl = [-1] * nsat

        # ---- clock line (C:255-266, C:440-467, C:878-927)
        if pos >= n_full:
            raise _corrupt("the file ends after an epoch line", pos + 1, "CRX.TRUNCATED")
        cl = cont[pos]
        dbuf.fgets(lines[pos], True, cl)
        pos += 1
        have_ps = False
        if crx31:
            sp = cl.find(b" ")
            if sp >= 0:
                ct, pt = cl[:sp], cl[sp + 1:]
            else:
                ct, pt = cl, b""
            if len(ct) >= 32:
                raise _corrupt("clock record is too long", pos, "CRX.CLOCK")
            if len(pt) >= 6:
                raise _corrupt("picosecond record is too long", pos, "CRX.PICOSEC")
            have_ps = bool(pt)
        else:
            ct = cl
        have_clock = bool(ct)
        if not have_clock:
            clk_order = -1
        else:
            t = ct
            if len(t) > 1 and t[1] == _AMP:
                a = t[0] - 48
                if not 0 <= a <= MAX_DIFF_ORDER:
                    raise _corrupt(f"bad arc order in clock record {ct!r}", pos, "CRX.ARC_ORDER")
                clk_arc = a
                clk_order = -1
                t = t[2:]
            clk_d = _parse_clock(t, pos)
            if not crx31 and len(t) - (t[:1] == b"-") >= 9:
                dbuf.nul(len(cl) - 8)                     # read_clock writes '\0'

        # ---- observation lines (getdiff C:707-770, data C:617-683)
        # Field states: a steady arc of order 3 is the 3-tuple (v, d1, d2) (d3 is
        # not needed for the next epoch); anything else is the 1-tuple
        # ((arc, v, d1, ..., d_order),); a blank field None. The state of a satellite is
        # the list of its field states, or the column form of the fast path:
        # (mask, values, d1s, d2s, ntype) when every field is steady or blank.
        new_dy = [None] * nsat
        new_fl = [None] * nsat
        sat_out = []
        # the nsat observation lines, cut in one split (cont[k] of each: one CR before
        # the LF dropped) unless the file ends first (then line by line, as C reads)
        end = pos + nsat
        if end <= n_full:
            obs = data[starts[pos]:starts[end]]
            if strip_cr:
                obs = obs.replace(b"\r\n", b"\n")
            obs = obs.split(b"\n")
        else:
            obs = [cont[k] for k in range(pos, n_full)]
        for i in range(nsat):
            if pos >= n_full:
                raise _corrupt("the file ends inside an epoch", pos + 1, "CRX.TRUNCATED")
            dl = obs[i]
            pos += 1
            nt = nts[i]
            parts = dl.split(b" ", nt)
            if len(parts) > nt:
                dflag = parts.pop()
                region = dl[:len(dl) - len(dflag)]
            else:
                dflag = b""
                region = dl
            np_ = len(parts)
            if region.translate(None, field_chars):
                raise _corrupt("observation fields contain characters other than digits, "
                               "'-' and '&'", pos, "CRX.FIELD")
            i0 = sattbl[i]
            # flags (C:642-653). The flag state of a satellite is (fl, its 2-byte pairs or
            # None until they are needed, the fast path's template for fl or None).
            if i0 < 0:
                n2 = nt + nt
                prev = None
                tmpl = None
                fl = dflag.translate(_AMP_TO_SP)
                if rv3:
                    if len(fl) < n2:
                        raise _corrupt("flags of a new satellite are shorter than "
                                       "2 x the number of types", pos, "CRX.FLAGS")
                    fl = fl[:n2]
                else:
                    fl = fl.ljust(n2)[:n2]
                pairs = None
            else:
                prev = dy0[i0]
                if (prev[4] if prev.__class__ is tuple else len(prev)) != nt:
                    raise _corrupt("number of observation types changed without an "
                                   "initialised epoch", pos, "CRX.NTYPE")
                fl, pairs, tmpl = flag1[i0]
                if dflag:
                    # (fl, dflag) -> repaired flags: the same changes recur (SSI 7 -> 8 -> 7)
                    key = (fl, dflag)
                    fn = rcache.get(key)
                    if fn is None:
                        n2 = nt + nt                # == len(fl)
                        fn = _repair(fl, dflag)
                        if len(fn) != n2:
                            fn = fn[:n2]
                        if len(rcache) >= 1 << 14:
                            rcache.clear()
                        rcache[key] = fn
                    if fn != fl:
                        fl = fn
                        pairs = tmpl = None
            # values (getdiff C:729-768 and the sums of data C:657-665)
            quirk = b"-0" in region          # "-0ddddd" needs C's split (_num_field)
            if prev.__class__ is tuple:
                mask, pv, p1, p2, _ = prev
                if not quirk:
                    # ---- fast path: the same blank fields as in the previous epoch and a
                    # plain difference (no "N&", which int() refuses) in each other one.
                    # It changes no state until it has the whole line; on anything else
                    # the general code below does the line from the start (and raises
                    # its errors).
                    if b"" in parts:
                        m = bytes(map(bool, parts))
                        if np_ < nt:
                            m += _ZEROS[:nt - np_]
                        vp = list(filter(None, parts))
                    else:                            # blank fields only after the last
                        vp = parts
                        if np_ == nt:
                            m = None
                        else:
                            m = pmasks.get(nt * 256 + np_)
                            if m is None:
                                m = pmasks[nt * 256 + np_] = _ONES[:np_] + _ZEROS[:nt - np_]
                    if m == mask:
                        try:
                            h2 = list(map(add, map(int, vp), p2))
                        except ValueError:
                            h2 = None
                        if h2 is not None:
                            h1 = list(map(add, h2, p1))
                            vv = list(map(add, h1, pv))
                            fl_f = fl
                            tmpl_f = tmpl
                            if tmpl_f is None or tmpl_f[0] != m:
                                if crx1 and m is not None:
                                    # CRINEX 1: a blank field prints and keeps blank flags
                                    # (the general code's `blanks`)
                                    fr = bytearray(fl)
                                    for j in range(nt):
                                        if not m[j]:
                                            fr[j + j] = fr[j + j + 1] = 32
                                    if fr != fl:
                                        fl_f = bytes(fr)
                                sid = ids[i] if rv3 else b""
                                key = (sid, m, fl_f)
                                tmpl_f = tcache.get(key)
                                if tmpl_f is None:
                                    if len(tcache) >= 1 << 14:      # (a few MB)
                                        tcache.clear()
                                    tmpl_f = tcache[key] = tmpl_of(
                                        [fl_f[k:k + 2] for k in range(0, nt + nt, 2)], m, sid, rv2)
                            if tmpl_f[3]:
                                try:
                                    s = tmpl_f[1] % tuple(map(truediv, vv, _K1000))
                                except OverflowError:            # far out of range
                                    s = b""
                                if len(s) == tmpl_f[2]:          # every value in range
                                    sat_out.append(s.replace(b" 0.", b"  .")
                                                   .replace(b"-0.", b" -."))
                                    new_dy[i] = (m, vv, h1, h2, nt)
                                    new_fl[i] = (fl_f, pairs if fl_f is fl else None, tmpl_f)
                                    continue
                # general code: the field states as a list
                if mask is None:
                    prev = list(zip(pv, p1, p2))
                else:
                    it = zip(pv, p1, p2)
                    prev = [next(it) if b else None for b in mask]
            if np_ < nt:
                parts.extend([b""] * (nt - np_))
            if pairs is None:
                pairs = [fl[k:k + 2] for k in range(0, nt + nt, 2)]
            fl_in = fl
            st = []
            vs = []
            nblank = 0
            n3 = 0
            for f, p in zip(parts, prev if prev is not None else _NONES):
                if not f:                      # empty field = missing observation
                    st.append(None)
                    vs.append(None)
                    nblank += 1
                    continue
                try:
                    d = int(f)
                except ValueError:
                    if len(f) > 1 and f[1] == _AMP:          # N&value: new arc
                        a = f[0] - 48
                        if not 0 <= a <= MAX_DIFF_ORDER:
                            raise _corrupt(f"bad arc order in field {f!r}", pos,
                                           "CRX.ARC_ORDER") from None
                        v = _num_field(f[2:], pos)
                        st.append(((a, v),))
                        vs.append(_fmt_value(v, ep_line_no))
                        continue
                    raise _corrupt(f"observation field {f!r} is not an integer", pos,
                                   "CRX.FIELD") from None
                if quirk:
                    d = _num_field(f, pos)
                if p is None:
                    if prev is None:
                        raise _corrupt("new satellite, but its data arc is not initialised",
                                       pos, "CRX.NEW_SAT_NO_INIT")
                    raise _corrupt("the field was blank in the previous epoch, but its arc "
                                   "is not initialised", pos, "CRX.BLANK_NO_INIT")
                if len(p) == 3:                # steady arc of order 3
                    q0, q1, q2 = p
                    h2 = d + q2
                    h1 = h2 + q1
                    v = h1 + q0
                    st.append((v, h1, h2))
                    n3 += 1
                else:
                    a = p[0][0]
                    hist = p[0][1:]
                    o = len(hist) - 1
                    if o < a:
                        o += 1
                    h = [0] * (o + 1)
                    h[o] = d
                    for k in range(o, 0, -1):
                        h[k - 1] = h[k] + hist[k - 1]
                    v = h[0]
                    if a == 3 and o == 3:
                        st.append((h[0], h[1], h[2]))
                        n3 += 1
                    else:
                        st.append(((a, *h),))
                        if a == 3:          # order 1 or 2 of an order-3 arc (see below)
                            n3 += 1
                if -1000 < v < 1000:
                    vs.append(small[v + 999])
                elif v > 0:
                    if v >= 10000000000000:
                        _bad_value(v, ep_line_no)
                    vs.append(b"%10d.%03d" % divmod(v, 1000))
                else:
                    if v <= -1000000000000:
                        _bad_value(v, ep_line_no)
                    vs.append(b"%10d.%03d" % (-(-v // 1000), -v % 1000))
            # output (C:633-682)
            if not nblank:
                body = b"".join(map(bytes.__add__, vs, pairs))
            else:
                pieces = []
                blanks = None
                for j in range(nt):
                    s = vs[j]
                    if s is None:
                        if crx1:
                            pieces.append(blank16)
                            if blanks is None:
                                blanks = []
                            blanks.append(j)
                        else:
                            pieces.append(blank14 + pairs[j])
                    else:
                        pieces.append(s + pairs[j])
                body = b"".join(pieces)
                if blanks is not None:              # CRINEX 1: blank field, blank flags
                    pairs = list(pairs)
                    for j in blanks:
                        pairs[j] = b"  "
                    fl = b"".join(pairs)
            if rv2:
                for k in range(0, 16 * nt, 80):
                    sat_out.append(body[k:k + 80].rstrip(b" ") + b"\n")
            elif nt:
                if rv3:
                    sat_out.append((ids[i] + body).rstrip(b" ") + b"\n")
                else:
                    sat_out.append(body.rstrip(b" ") + b"\n")
            elif rv3:
                sat_out.append(ids[i])        # C prints the id and no LF (C:637-681)
            if fast and nt and n3 + nblank == nt:
                # every field blank or in an order-3 arc past its first value: column form
                # (fast path next). An arc of order 3 now at order 1, ((3, v, d1),), or 2,
                # ((3, v, d1, d2),), takes its next step (o + 1 above) exactly as the steady
                # (v, d1, 0) or (v, d1, d2) would, and gives the same state after it.
                nb = [(e if len(e) == 3 else (e[0][1], e[0][2], e[0][3] if len(e[0]) > 3 else 0))
                      for e in st if e is not None]
                st = (bytes(map(bool, parts)) if nblank else None,
                      *(zip(*nb) if nb else ((), (), ())), nt)
            new_dy[i] = st
            new_fl[i] = (fl, pairs, tmpl if fl is fl_in else None)

        # ---- clock and picosecond (C:276-277, C:469-492)
        if have_clock:
            if clk_order < clk_arc:
                clk_order += 1
            o = clk_order
            h = [0] * (o + 1)
            h[o] = clk_d
            for k in range(o, 0, -1):
                h[k - 1] = h[k] + clk_hist[k - 1]
            clk_hist = h
        if crx31 and have_ps:
            picosec = _repair(picosec, pt)

        # ---- print the epoch (C:279-325)
        out = []
        if rv2:
            if clk_order >= 0:
                out.append(line[:68].ljust(68) + _fmt_clock(clk_hist[0], shift, ep_line_no,
                                                             fix_clock_bug) + b"\n")
            else:
                out.append(line[:68] + b"\n")
            n = nsat - 12
            q = 68
            while n > 0:
                out.append(b"                                " + line[q:q + 36] + b"\n")
                n -= 12
                q += 36
        else:
            out_clock = clk_order >= 0
            out_ps = crx31 and len(picosec) > 0
            if out_clock:
                ck = _fmt_clock(clk_hist[0], shift, ep_line_no, fix_clock_bug)
                if out_ps:
                    out.append(line[:41] + ck + b" " + picosec.rjust(5) + b"\n")
                else:
                    out.append(line[:41] + ck + b"\n")
            elif out_ps:
                out.append(line[:41] + b"                " + picosec.rjust(5) + b"\n")
            else:
                out.append(line[:41].rstrip(_C_SPACE) + b"\n")

        out.extend(sat_out)
        yield b"".join(out)

        # ---- save the epoch (C:329-335); a repeated id maps to its first index, as
        # when they are assigned from the last to the first
        old_ids = dict(zip(reversed(ids), range(nsat - 1, -1, -1)))
        dy0 = new_dy
        flag1 = new_fl


# --------------------------------------------------------------------------
# encoder

_F_VALUE = rb"(?:[ \d-]{10}\.\d{3}|[ ]{14})[\x20-\x25\x27-\x7e]{2}"
_RE_F1 = re.compile(_F_VALUE)
_RE_CLOCK2 = re.compile(rb"(?:  | \d|\d\d|-\d| -)\.\d{9}")
_RE_CLOCK3 = re.compile(rb"(?:  | \d|\d\d|-\d| -)\.\d{12}")
_RE_TEXT = re.compile(rb"[\x20-\x25\x27-\x7e]*")
_FLAG_OK = bytes(c for c in range(0x20, 0x7f) if c != 0x26)


_RE_READABLE = re.compile(rb" *[+-]?(?:\d+\.?\d*|\.\d+) *| *")


def _field_error(body, line_no):
    """Raise CRX.ENC.FIELD for the first field that is not F14.3 + LLI + SSI as RNX2CRX
    writes it (point in column 11, three decimals). A field that reads as an F14.3 number
    all the same (`   1050010.1  `, `+1.5`: Fortran F14.3 input takes an explicit point
    anywhere; rinexcore.obs keeps value text as written) is valid RINEX that RNX2CRX cannot
    take: CrxCannotHold, so the converter writes plain RINEX with warning
    OBS.CRX.FIELD-PLAIN (round 32: a valid input was refused-corrupt with --crx)."""
    for k in range(0, len(body), 16):
        c = body[k:k + 16]
        bad = _RE_F1.fullmatch(c) is None
        if not bad and c[10] == _DOT:
            try:
                int(c[:10] + c[11:14])
            except ValueError:
                bad = True
        if bad:
            msg = f"abnormal data field {c!r} (not F14.3 + LLI + SSI)"
            f = c.ljust(16)
            if _RE_READABLE.fullmatch(f[:14]) and not f[14:16].strip(b" 0123456789"):
                raise CrxCannotHold(msg + ": an F14.3 value RNX2CRX cannot take (it needs the "
                                    "point in column 11 and three decimals)", line=line_no,
                                    rule="CRX.ENC.FIELD", plain_rule="OBS.CRX.FIELD-PLAIN")
            raise _corrupt(msg, line_no, "CRX.ENC.FIELD")
    raise _corrupt("abnormal data field", line_no, "CRX.ENC.FIELD")


def _enc_chop(raw):
    """read_chk_line (E:884-904): drop one CR before LF, then trailing blanks."""
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    return _chop_blank(raw)


def _trunc_div(v, d):
    return v // d if v >= 0 else -((-v) // d)


def _slip(vals_new, prev):
    """Exact RNX2CRX test (E:648): |upper part of the order-o difference| > 100000.

    RNX2CRX differences the upper parts (value / 100000, truncated) separately;
    rebuild the previous values from the stored differences and do the same.
    """
    o = len(vals_new) - 1
    seq = [prev[0]]
    dif = list(prev)
    for _ in range(o - 1):
        # step back one epoch: v(t-1) - d1(t-1) = v(t-2), etc.
        nxt = [dif[k] - dif[k + 1] for k in range(len(dif) - 1)]
        seq.append(nxt[0])
        dif = nxt
    us = [_trunc_div(vals_new[0], 100000)] + [_trunc_div(v, 100000) for v in seq]
    for _ in range(o):
        us = [us[k] - us[k + 1] for k in range(len(us) - 1)]
    return abs(us[0]) > _SLIP_LIMIT


def _crx_date(date):
    if date is None:
        date = datetime.datetime.now(datetime.timezone.utc)
    if isinstance(date, (bytes, str)):
        s = date if isinstance(date, bytes) else date.encode("latin-1")
        return s[:20]
    return ("%02d-%s-%02d %02d:%02d" % (date.day, _MONTHS[date.month - 1], date.year % 100,
                                         date.hour, date.minute)).encode("ascii")


def rnx_to_crx(data, *, program=None, date=None):
    """Compress RINEX observation bytes (2.x, 3.x, 4.x) to Compact RINEX bytes.

    ``program`` (default ``"rinexcore <version>"``) and ``date`` (a datetime,
    or the 20-character text; default: now, UTC) fill CRINEX PROG / DATE.
    """
    out = spool.Spool()                  # the output, held once (io.spool)
    try:
        return _encode(bytes(data), program, date, out)
    finally:
        out.close()                      # its temporary file goes now, on an error too


def _encode(data, program, date, out):
    lines, cont, n_full = _split_lines(data, "CRX.ENC.")
    del cont
    nlines = len(lines)
    def fail(msg, ln, rule):
        raise _corrupt(msg, ln, "CRX.ENC." + rule)

    # ---------------- header (E:373-412)
    if not lines:
        fail("empty input", 1, "HEADER")
    first = _enc_chop(lines[0])
    if first[60:80] != _LABEL_VERSION or first[20:21] != b"O":
        fail("not a RINEX observation file (line 1 must be RINEX VERSION / TYPE "
             "with type O)", 1, "HEADER")
    rinex_version = _c_atoi(first, 0)
    # RNX2CRX accepts only "d.dd" or "2" (read_version_full, E:856-882); real files
    # also say "2.1", so the F9.2 field is read as a number (CLAUDE.md).
    m = re.fullmatch(rb" *(\d)(?:\.(\d)(\d)?)? *", first[:9])
    if not m:
        fail("invalid RINEX version number", 1, "HEADER")
    full = int(m.group(1)) * 100 + int(m.group(2) or b"0") * 10 + int(m.group(3) or b"0")
    if first[5:6] not in (b"2", b"3", b"4"):
        fail("only RINEX 2, 3 and 4 can be written as Compact RINEX", 1, "HEADER")
    if full >= 402:
        crx_ver = b"3.1"
    elif rinex_version == 2:
        crx_ver = b"1.0"
    elif rinex_version in (3, 4):
        crx_ver = b"3.0"
    else:
        fail("invalid RINEX version number", 1, "HEADER")
    if program is None:
        program = "rinexcore %s" % _PKG_VERSION
    if isinstance(program, str):
        program = program.encode("latin-1")
    l1 = b"%-20.20s%-40.40s%-20.20s" % (crx_ver, b"COMPACT RINEX FORMAT",
                                        b"CRINEX VERS   / TYPE")
    l2 = b"%-40.40s%-20.20sCRINEX PROG / DATE" % (program, _crx_date(date))
    out.append(l1 + b"\n" + l2 + b"\n")
    # what CRX2RNX will see while reading this header (C:411-438)
    hsim = _CBuf()
    for x in (l1, l2):
        hsim.fgets(x, True, x)
    types = [0, [-1] * 256]
    pos = 0
    hdr = []
    while True:
        if pos >= nlines:
            fail("the file ends inside the header", pos + 1, "EOF")
        c = _enc_chop(lines[pos])
        if c.endswith(b"\r"):
            fail("a header line ends with a carriage return", pos + 1, "CR")
        pos += 1
        hdr.append(c + b"\n")
        hsim.fgets(c, True, c)
        if pos > 1:
            _types_update(hsim, types, pos, "CRX.ENC.MAXTYPE")
        if pos > 1 and hsim.label(60, _LABEL_EOH):
            break
    out.append(b"".join(hdr))
    del hdr

    # ---------------- data section
    rv2 = rinex_version == 2
    if rv2:
        p_event, p_nsat, p_clock, offset = 28, 29, 68, 3
        ep_from = b"&"
        re_clock = _RE_CLOCK2
    else:
        p_event, p_nsat, p_clock, offset = 31, 32, 41, 6
        ep_from = b">"
        re_clock = _RE_CLOCK3
    ep_to_i = 32 if rv2 else _GT
    crx31 = crx_ver == b"3.1"
    dsim = _CBuf()                  # CRX2RNX's dline while it reads our output
    oldline = b"&"
    old_ids = {}
    dy0 = []
    flag0 = []
    clk_order = -1
    clk_hist = []
    oldpsec = b""
    sp2amp = _SP_TO_AMP
    blank14 = _BLANK14
    # Fast path: a satellite whose fields are all steady (order 2 or 3) or blank is kept in
    # column form, (dots, values, d1s, d2s, ntype) (dots: column 11 of each field, '.' or
    # blank; the lists hold the non-blank fields), instead of the list of field states.
    fast = _FAST
    ffmts = {}                 # dots -> %-format of the difference fields
    data, starts = lines.data, lines.starts
    has_cr = b"\r" in data

    def check_types():
        if types[0] > MAXTYPE or max(types[1]) > MAXTYPE:
            fail(f"more than {MAXTYPE} observation types", pos, "MAXTYPE")

    check_types()

    while pos < nlines:
        raw = lines[pos]
        pos += 1
        ln = pos
        c = _enc_chop(raw)
        if c[:1] == b"\x1a":
            rest = b"".join(lines[pos - 1:])
            if not rest.strip(b"\x1a\r\n"):
                break                                  # DOS EOF (E:427)
        # get_next_epoch (E:414-461)
        if rv2:
            if (len(c) < 29 or c[0] != _SP or c[27] != _SP or not 48 <= c[28] <= 57
                    or (len(c) > 29 and c[29] != _SP and not 48 <= c[29] <= 57)):
                fail(f"expected a RINEX 2 epoch line, found {c[:40]!r}", ln, "EPOCH")
        else:
            if c[:1] != b">":
                fail(f"expected a RINEX 3/4 epoch line, found {c[:40]!r}", ln, "EPOCH")
            if len(c) < 41:
                c = c.ljust(41)
        if c.endswith(b"\r"):
            fail("an epoch line ends with a carriage return", ln, "CR")
        ev = c[p_event] - 48 if 48 <= c[p_event] <= 57 else 0
        if ev > 1:
            # ---- put_event_data (E:491-528), as CRX2RNX will read it back
            if rv2:
                if c[26] == _DOT:
                    fail("malformed event line", ln, "EVENT")
                evl = b"&" + c[1:]
                nrec = _c_atoi(c, 29) if len(c) > 29 else 0
            else:
                if c[29] == _DOT:
                    fail("malformed event line", ln, "EVENT")
                evl = c.rstrip(b" ")
                nrec = _c_atoi(evl, 32)
            dsim.fgets(evl, True, evl)
            dsim.b[0] = ep_to_i
            dl_c = _chop_blank(bytes([ep_to_i]) + evl[1:])
            dsim.nul(len(dl_c))
            out.append(evl + b"\n")
            if len(dl_c) > 29:
                if _c_atoi(dsim.b, p_event + 1) != nrec:
                    fail("event record count would be read differently", ln, "EVENT")
            elif nrec:
                fail("event line too short to carry a record count", ln, "EVENT")
            for _ in range(nrec):
                if pos >= nlines:
                    fail("the file ends inside an event record", pos + 1, "EOF")
                h = _enc_chop(lines[pos])
                pos += 1
                if h.endswith(b"\r"):
                    fail("an event record line ends with a carriage return", pos, "CR")
                out.append(h + b"\n")
                dsim.fgets(h, True, h)
                hc = _chop_blank(h)
                dsim.nul(len(hc))
                if len(hc) < 60 + len(_LABEL_TYPES2) and (
                        (rv2 and dsim.label(60, _LABEL_TYPES2) and dsim.at(5) != _SP)
                        or (not rv2 and dsim.label(60, _LABEL_TYPES3) and dsim.at(0) != _SP)):
                    raise CrxCannotHold(
                        "an event record line (cycle-slip records of an epoch with event flag "
                        "6) is shorter than column 79, and RNX2CRX/CRX2RNX would read the "
                        "observation-type label an earlier line left in their buffer as its "
                        "own and take it for a type count", line=pos, rule="CRX.ENC.STALE-LABEL",
                        plain_rule="OBS.CRX.EVENT-PLAIN")
                _types_update(dsim, types, pos, "CRX.ENC.MAXTYPE")
            check_types()
            # initialize_all (E:484-489); oldpsec is kept, as in RNX2CRX
            oldline = b"&"
            clk_order = -1
            old_ids = {}
            continue

        # ---- picosecond extension (E:228-243)
        newpsec = b""
        if full >= 402 and len(c) == 62:
            newpsec = c[57:62]
            if not newpsec.isdigit():
                fail("picosecond field is not 5 digits", ln, "PICOSEC")
            c = c[:41] + c[41:57].rstrip(_C_SPACE)
        if not newpsec and oldpsec:
            raise CrxCannotHold("the picosecond field stops part-way through the file; CRX2RNX "
                                "would repeat the last value", line=ln, rule="CRX.ENC.PICOSEC",
                                plain_rule="OBS.CRX.PICOSEC-PLAIN")

        # ---- clock (E:245-250, E:530-543)
        if len(c) > p_clock:
            ctext = c[p_clock:]
            text = c[:p_clock]
            if not re_clock.fullmatch(ctext):
                if _RE_READABLE.fullmatch(ctext):
                    # a readable value in other digits (a RINEX 2 ' 123.4567890' carried as
                    # written: rinexconv.obsconv._clock_v2): valid RINEX that RNX2CRX cannot
                    # take (read_clock wants the point in column 3 of the field, E:530-543)
                    raise CrxCannotHold(f"receiver clock {ctext!r} is not F12.9 (RINEX 2) / F15.12 "
                                        "(RINEX 3/4), which RNX2CRX needs", line=ln,
                                        rule="CRX.ENC.CLOCK", plain_rule="OBS.CRX.CLOCK-PLAIN")
                fail(f"receiver clock {ctext!r} is not F12.9 (RINEX 2) / F15.12 "
                     "(RINEX 3/4)", ln, "CLOCK")
            neg = b"-" in ctext[:2]
            cv = int(ctext[:2].replace(b"-", b" ") + ctext[3:])
            if neg:
                cv = -cv
            if cv < 0 and cv % 100000000 == 0:
                fail("CRX2RNX 4.2.0 prints a negative clock whose last 8 digits are "
                     "zero with the wrong value", ln, "CLOCKBUG")
            have_clock = True
        else:
            text = c
            have_clock = False

        nsat = _c_atoi(text, p_nsat)
        if nsat > MAXSAT:
            fail("more than 100 satellites in one epoch", ln, "MAXSAT")
        if nsat < 0:
            fail("negative number of satellites", ln, "EPOCH")

        # ---- satellite list
        if rv2:
            if nsat > 12:
                if len(text) != 68 or text[67] == _SP:
                    fail("the first epoch line must list exactly 12 satellites", ln,
                         "SATLIST")
                sats = [text[32:68]]
                n = nsat
                while n > 12:
                    n -= 12
                    if pos >= nlines:
                        fail("the file ends inside an epoch line", pos + 1, "EOF")
                    cc = _enc_chop(lines[pos])
                    pos += 1
                    if cc[2:3] == b" ":
                        if cc[:32].strip(b" "):
                            fail("continuation line has text before column 33", pos,
                                 "SATLIST")
                        chunk = cc[32:]
                    else:
                        chunk = cc                     # old 12(A1,I2) layout (E:617-621)
                    want = 3 * (n if n < 12 else 12)
                    if len(chunk) != want or chunk[-1] == _SP:
                        fail("satellite continuation line does not match the count", pos,
                             "SATLIST")
                    sats.append(chunk)
                satlist = b"".join(sats)
                etext = text[:32] + satlist
            else:
                satlist = text[32:32 + 3 * nsat]
                if len(satlist) != 3 * nsat or text[32 + 3 * nsat:].strip(b" "):
                    fail("the satellite list does not match the number of satellites", ln,
                         "SATLIST")
                if nsat and satlist[-1] == _SP:
                    fail("the last satellite id ends with a blank", ln, "SATLIST")
                etext = text if len(text) < 32 else text[:32 + 3 * nsat]
            ids = [satlist[k:k + 3] for k in range(0, 3 * nsat, 3)]
        else:
            ids = []

        # ---- observation lines (ggetline, E:696-759)
        bodies = []
        nts = []
        # the epoch's observation lines (lines[k] of each) cut in one split when they all
        # end with LF, else read one by one; _enc_chop inline
        nobs = nsat * ((types[0] + 4) // 5 if rv2 else 1)
        if pos + nobs <= n_full:
            blk = data[starts[pos]:starts[pos + nobs] - 1].split(b"\n") if nobs else []
            pos0 = pos
        else:
            blk = None
        for i in range(nsat):
            if rv2:
                nt = types[0]
                chunks = []
                for k in range(0, nt, 5):
                    nf = nt - k if nt - k < 5 else 5
                    if pos >= nlines:
                        fail("the file ends inside an epoch", pos + 1, "EOF")
                    raw = lines[pos] if blk is None else blk[pos - pos0]
                    if has_cr and raw[-1:] == b"\r":
                        raw = raw[:-1]
                    dl = raw.rstrip(b" ")
                    if not dl and raw:
                        dl = b" "
                    pos += 1
                    if len(dl) > 16 * nf:
                        fail("more data fields than observation types", pos, "NFIELD")
                    chunks.append(dl.ljust(16 * nf))
                body = b"".join(chunks)
            else:
                if pos >= nlines:
                    fail("the file ends inside an epoch", pos + 1, "EOF")
                raw = lines[pos] if blk is None else blk[pos - pos0]
                if has_cr and raw[-1:] == b"\r":
                    raw = raw[:-1]
                dl = raw.rstrip(b" ")
                if not dl and raw:
                    dl = b" "
                pos += 1
                if len(dl) < 3:
                    fail("observation line too short for a satellite id", pos, "SATLIST")
                ids.append(dl[:3])
                nt = types[1][dl[0]]
                if nt < 0:
                    fail(f"GNSS type {dl[:1]!r} is not defined in the header", pos, "SYS")
                if nt == 0:
                    fail(f"GNSS type {dl[:1]!r} has no observation types", pos, "NTYPE0")
                body = dl[3:]
                if len(body) > 16 * nt:
                    fail("more data fields than observation types", pos, "NFIELD")
                body = body.ljust(16 * nt)
            bodies.append((body, pos))
            nts.append(nt)
        if not rv2:
            etext = text[:41] + b"".join(ids)
            if nsat and ids[-1][-1] == _SP:
                fail("the last satellite id ends with a blank", ln, "SATLIST")
            if (have_clock or newpsec) and len(etext.rstrip(b" ")) < 41:
                fail("CRX2RNX cannot restore the clock of an epoch with no satellites",
                     ln, "EPOCH")

        # what CRX2RNX checks after repairing the line (C:243-244)
        if (len(etext) < 26 + offset or etext[offset + 23] != _SP
                or etext[offset + 24] != _SP or not 48 <= etext[offset + 25] <= 57):
            fail("epoch line has no blanks before / digit at the epoch flag", ln, "EPOCH")
        if not _RE_TEXT.fullmatch(etext):
            fail("epoch line contains '&' or a non-printable character", ln, "AMP")

        # set_sat_table (E:580-607)
        if len(set(ids)) != nsat:
            fail("duplicated satellite in one epoch", ln, "DUPSAT")
        if old_ids:
            sattbl = [old_ids.get(s, -1) for s in ids]
        else:
            sattbl = [-1] * nsat

        # ---- epoch line and clock line (E:277-288)
        diff = _strdiff(oldline, etext).rstrip(b" ")
        if oldline == b"&":
            if diff[:1] != ep_from:
                fail("internal: initialised epoch line does not start correctly", ln, "EPOCH")
        dsim.fgets(diff, True, diff)
        if diff[:1] == ep_from:
            dsim.b[0] = ep_to_i
        piece = [diff, b"\n"]
        if have_clock:
            if clk_order < ARC_ORDER:
                clk_order += 1
            h = [cv]
            for k in range(clk_order):
                h.append(h[k] - clk_hist[k])
            clk_hist = h
            cs = (b"3&%d" % cv) if clk_order == 0 else (b"%d" % h[clk_order])
        else:
            clk_order = -1
            cs = b""
        if newpsec:
            cline = (cs + b" " + _strdiff(oldpsec, newpsec)).rstrip(b" ")
        else:
            cline = cs
        piece.append(cline)
        piece.append(b"\n")
        dsim.fgets(cline, True, cline)
        if not crx31 and cs:
            t = cs[2:] if cs[1:2] == b"&" else cs
            if len(t) - (t[:1] == b"-") >= 9:
                dsim.nul(len(cline) - 8)

        # ---- data (E:627-671)
        # Field states: (v,) order 0, (v, d1) order 1, (v, d1, d2) order 2 or 3
        # (the next difference is computed the same way from either).
        new_dy = [None] * nsat
        new_fl = [None] * nsat
        for i in range(nsat):
            nt = nts[i]
            body, bline = bodies[i]
            i0 = sattbl[i]
            prev = dy0[i0] if i0 >= 0 else None
            fb = bytearray(nt + nt)
            fb[0::2] = body[14::16]
            fb[1::2] = body[15::16]
            flags = bytes(fb)
            # Validate with C-level slicing; on failure _field_error names the field.
            dots = body[10::16]
            nblank = dots.count(32)
            blanks = None
            if nblank + dots.count(46) != nt or flags.translate(None, _FLAG_OK):
                _field_error(body, bline)
            # Quick form of the general checks below, giving the values of the non-blank
            # fields (vp). With the flags blanked: no '.' but the nt - nblank of column 11;
            # every other value column blank, a digit or '-'; columns 12-14 digits where
            # column 11 is '.' and blanks where it is blank; then one token per non-blank
            # field and none in a blank one (which therefore holds 14 blanks) is the
            # general code's one token per field, each the same bytes (columns 1-10 and
            # 12-14). Anything else goes to the general checks, which raise or agree.
            vp = vals = None
            if fast:
                ba = bytearray(body)
                ba[14::16] = ba[15::16] = b" " * nt
            if fast and ba.count(46) == nt - nblank:
                ba = ba.translate(None, b".")
                if (not ba.translate(None, b" 0123456789-")
                        and (body[11::16] + body[12::16] + body[13::16]).translate(_DIG_DOT)
                        == dots * 3):
                    toks = ba.split()
                    if len(toks) == nt - nblank:
                        try:
                            vp = list(map(int, toks))
                        except ValueError:
                            vp = None
            if vp is None:
                # General checks. Value of a field = int(integer part + 3 decimals); blank
                # fields get a "0" placeholder so that split() keeps one token per field.
                b2 = bytearray(b" " * (14 * nt))
                for col in range(10):
                    b2[col::14] = body[col::16]
                b2[10::14] = body[11::16]
                b2[11::14] = body[12::16]
                b2[12::14] = body[13::16]
                if nblank:
                    blanks = []
                    j = dots.find(b" ")
                    while j >= 0:
                        if body[16 * j:16 * j + 14] != blank14:
                            _field_error(body, bline)
                        b2[14 * j:14 * j + 13] = b"0000000000000"
                        blanks.append(j)
                        j = dots.find(b" ", j + 1)
                toks = b2.split()
                if (len(toks) != nt or b2.translate(None, b" 0123456789-")
                        or (nt and not (b2[10::14] + b2[11::14] + b2[12::14]).isdigit())):
                    _field_error(body, bline)
                try:
                    vals = list(map(int, toks))
                except ValueError:
                    _field_error(body, bline)
                vp = vals if not nblank else list(compress(vals, dots.translate(_DOT_SEL)))
            elif nblank and rv2:
                blanks = [j for j in range(nt) if dots[j] == 32]
            fields = None
            if prev.__class__ is tuple:
                mask, pv, p1, p2, _ = prev
                if dots == mask:
                    # ---- fast path: the same blank fields as in the previous epoch and
                    # every other one steady (order 2 or 3): the differences by map(), and
                    # when none reaches the slip bound below, the general code's states and
                    # text (b" ".join(fs) + b" ": "%d " a value, " " a blank field)
                    d1 = list(map(sub, vp, pv))
                    d2 = list(map(sub, d1, p1))
                    dd = list(map(sub, d2, p2))
                    if not dd or (min(dd) > -9999200000 and max(dd) < 9999200000):
                        fmt = ffmts.get(dots)
                        if fmt is None:
                            fmt = ffmts[dots] = b"".join([b"%d " if c == _DOT else b" "
                                                          for c in dots])
                        fields = fmt % tuple(dd)
                        st = (dots, vp, d1, d2, nt)
                if fields is None:                      # general code: a list of states
                    if mask.count(32):
                        it = zip(pv, p1, p2)
                        prev = [next(it) if c == _DOT else None for c in mask]
                    else:
                        prev = list(zip(pv, p1, p2))
            if fields is None:
                if vals is None:                        # (0: placeholder of a blank field)
                    if nblank:
                        it = iter(vp)
                        vals = [next(it) if c == _DOT else 0 for c in dots]
                    else:
                        vals = vp
                st = []
                fs = []
                n3 = 0
                for v, p, dch in zip(vals, prev if prev is not None else _NONES, dots):
                    if dch == _SP:                          # blank field
                        st.append(None)
                        fs.append(b"")
                        continue
                    if p is None:                           # new satellite / after a blank
                        st.append((v,))
                        fs.append(b"3&%d" % v)
                        continue
                    if len(p) == 3:                         # order 2 or 3 -> order 3
                        q0, q1, q2 = p
                        d1 = v - q0
                        d2 = d1 - q1
                        d = d2 - q2
                        # |d| below this bound cannot have an upper part above 100000
                        # (the truncations move it by less than 8); see _slip
                        if -9999200000 < d < 9999200000:
                            st.append((v, d1, d2))
                            fs.append(b"%d" % d)
                            n3 += 1
                            continue
                        hv = (v, d1, d2, d)
                    else:
                        hv = [v]
                        for q in range(len(p)):
                            hv.append(hv[q] - p[q])
                        d = hv[-1]
                    if -9999200000 < d < 9999200000 or not _slip(hv, p):
                        t = tuple(hv[:3])
                        st.append(t)
                        fs.append(b"%d" % d)
                        if len(t) == 3:
                            n3 += 1
                    else:                                   # large cycle slip (E:648-651)
                        st.append((v,))
                        fs.append(b"3&%d" % v)
                if nt:
                    fields = b" ".join(fs) + b" "
                    if fast and n3 + nblank == nt:
                        # every field steady or blank: column form (fast path next)
                        nb = [e for e in st if e is not None]
                        st = (dots, *(zip(*nb) if nb else ((), (), ())), nt)
                else:
                    fields = b""
            if blanks is not None and rv2:
                for j in blanks:
                    if flags[2 * j] != _SP or flags[2 * j + 1] != _SP:
                        fail("a blank RINEX 2 observation carries LLI/SSI flags, which "
                             "Compact RINEX 1.0 cannot hold", bline, "FLAG2")
            else:
                blanks = None
            if i0 < 0:
                if rv2:
                    piece.append((fields + flags).rstrip(b" "))
                else:
                    piece.append(fields + flags.translate(sp2amp))
            else:
                fo = flag0[i0]
                if blanks is not None:
                    fo2 = bytearray(fo)
                    for j in blanks:
                        fo2[2 * j] = fo2[2 * j + 1] = _SP
                    fo = bytes(fo2)
                # (_strdiff of equal flags is b"")
                piece.append((fields if fo == flags else fields + _strdiff(fo, flags))
                             .rstrip(b" "))
            piece.append(b"\n")
            new_dy[i] = st
            new_fl[i] = flags
        out.append(b"".join(piece))

        # ---- save (E:293-300); a repeated id cannot occur (DUPSAT), but it would map to
        # its first index, as when assigned from the last to the first
        old_ids = dict(zip(reversed(ids), range(nsat - 1, -1, -1)))
        oldline = etext
        oldpsec = newpsec
        dy0 = new_dy
        flag0 = new_fl
    return out.getvalue()
