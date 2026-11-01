"""Open a RINEX file: unwrap gz/.Z/Hatanaka, split lines, sniff version and type.

Everything is bytes until split_lines(), which decodes latin-1 (one byte, one
character, so any byte survives) and records the line-ending style.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .errors import CorruptError, InvocationError
from .io import compress, spool

# RINEX VERSION / TYPE file-type letters (col 21) per kind.
# v2: O obs, N GPS nav, G GLONASS nav, H GEO/SBAS nav, M met (rinex211.txt Table A1, A3, A4, A5..);
# the non-standard L (Galileo) and P (mixed) nav letters turn up in some v2 files.
# v3/v4: O obs, N nav (system letter at col 41), M met.
NAV_TYPES_V2 = {"N": "G", "G": "R", "H": "S", "L": "E", "P": "M", "E": "E", "C": "C", "J": "J", "I": "I"}


@dataclass
class FileInfo:
    version_str: str
    version: str          # normalised "X.YY"
    major: int
    ftype: str            # O, N, G, H, M, ...
    system: str           # header system letter (col 41), may be blank
    kind: str             # obs, nav, met


@dataclass
class Container:
    payload: bytes        # plain RINEX bytes (CRX already expanded)
    layers: list = field(default_factory=list)   # outermost first: 'gz', 'Z'
    crx: str = None       # CRINEX version string if the file was Hatanaka-compressed
    crx_bytes: bytes = None


def normalise_version(s):
    """'2' -> '2.00', '2.1' -> '2.10', ' 3.05' -> '3.05' (F9.2 field read as a number)."""
    t = s.strip()
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise CorruptError(f"unreadable RINEX version field {s!r}", line=1, column=1,
                           rule="HDR.VERSION") from None
    if not d.is_finite() or d <= 0 or d >= 10:
        raise CorruptError(f"RINEX version {t!r} out of range", line=1, column=1, rule="HDR.VERSION")
    return f"{d.quantize(Decimal('0.01')):.2f}"


def read_path(path):
    p = Path(path)
    try:
        return p.read_bytes()
    except FileNotFoundError:
        raise InvocationError(f"input not found: {p}") from None
    except OSError as e:
        raise InvocationError(f"cannot read {p}: {e}") from None


def open_container(data):
    """Strip compression layers and expand Hatanaka, returning a Container."""
    payload, layers = compress.unwrap(data)
    c = Container(payload=payload, layers=layers)
    from .io import hatanaka
    if hatanaka.is_crx(payload):
        first = payload.split(b"\n", 1)[0].decode("latin-1")
        c.crx = first[:20].strip()
        c.payload = hatanaka.crx_to_rnx(payload)
    return c


def eol_of(payload):
    """'crlf' when most lines end in CR LF, else 'lf' (counted on the bytes: no decoding)."""
    crlf = payload.count(b"\r\n")
    lf = payload.count(b"\n")
    return "crlf" if lf and crlf * 2 > lf else "lf"


def first_line(payload):
    """[the first line] (or [] for an empty payload), for sniff(), without splitting the rest."""
    j = payload.find(b"\n")
    return split_lines(payload if j < 0 else payload[:j + 1])[0]


def split_lines(payload):
    """Decode latin-1 and split into lines without terminators. Returns (lines, eol)."""
    text = payload.decode("latin-1")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if "\r\n" in text:
        lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
    return lines, eol_of(payload)


def sniff(lines):
    """FileInfo from the RINEX VERSION / TYPE record (must be the first line)."""
    if not lines:
        raise CorruptError("empty file", line=1, rule="HDR.EMPTY")
    first = lines[0]
    if first[60:80].strip() != "RINEX VERSION / TYPE":
        raise CorruptError("first line is not RINEX VERSION / TYPE", line=1, column=61,
                           rule="HDR.FIRST")
    version_str = first[0:9].strip()
    version = normalise_version(first[0:9])
    major = int(version[0])
    ftype = first[20:21].upper()
    system = first[40:41].upper()
    if ftype == "O":
        kind = "obs"
    elif ftype == "M" and "MET" in first[20:40].upper():
        kind = "met"
    elif major >= 3 and ftype == "N":
        kind = "nav"
    elif major == 2 and ftype in NAV_TYPES_V2:
        kind = "nav"
    elif ftype == "M":
        kind = "met"
    else:
        raise CorruptError(f"unknown RINEX file type {ftype!r}", line=1, column=21, rule="HDR.TYPE")
    return FileInfo(version_str, version, major, ftype, system, kind)


def join_lines(lines, eol="lf"):
    """Bytes of an iterable of lines, built in chunks so a generator is never listed whole,
    and the output held about once (io.spool)."""
    sep = "\r\n" if eol == "crlf" else "\n"

    def chunks():
        buf = []
        for line in lines:
            buf.append(line)
            if len(buf) >= 50000:
                yield (sep.join(buf) + sep).encode("latin-1")
                buf = []
        if buf:
            yield (sep.join(buf) + sep).encode("latin-1")
    return spool.join_bytes(chunks())
