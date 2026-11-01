"""gzip and Unix compress (.Z) wrappers, stdlib only.

The .Z decoder is the one in tools/build_corpus.py (verified byte-identical to
unlzw3 on a 2015 CDDIS file). The encoder writes the format that decoder and
compress(1)/gzip -d read: LSB-first codes 9..16 bits wide in block mode, with
the rest of the current 8-code group padded whenever the width changes or a
CLEAR is sent.
"""

import gzip
import zlib

from ..errors import CorruptError
from . import spool

GZIP_MAGIC = b"\x1f\x8b"
Z_MAGIC = b"\x1f\x9d"
BZ2_MAGIC = b"BZh"
ZIP_MAGIC = b"PK\x03\x04"


def detect(data):
    """'gz', 'Z', 'bz2', 'zip' or None from the magic bytes."""
    if data[:2] == GZIP_MAGIC:
        return "gz"
    if data[:2] == Z_MAGIC:
        return "Z"
    if data[:3] == BZ2_MAGIC and data[3:4] in b"123456789":
        return "bz2"
    if data[:4] == ZIP_MAGIC:
        return "zip"
    return None


def bunzip2(data):
    import bz2
    try:
        return bz2.decompress(data)
    except (OSError, ValueError, EOFError) as e:
        raise CorruptError(f"bzip2 stream is damaged: {e}", rule="IO.BZ2") from None


def unzip_single(data):
    """The one member of a .zip archive (a RINEX file); more than one member is refused."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            if len(names) != 1:
                raise CorruptError(f".zip holds {len(names)} files; expected one RINEX file",
                                   rule="IO.ZIP")
            return z.read(names[0])
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, NotImplementedError) as e:
        raise CorruptError(f".zip archive is damaged: {e}", rule="IO.ZIP") from None


def gunzip(data):
    """Decompress gzip data; concatenated members are all decoded. Decoded in 16 MB pieces
    into a spool, so the result is held once (a bytearray grown and copied to bytes was
    twice the 1.5 GB of a 24 h 1 Hz file)."""
    out = spool.Spool()
    try:
        while data:
            d = zlib.decompressobj(31)
            try:
                buf = data
                # stop at the member's end: zlib then holds what follows in unused_data,
                # and (when the piece limit was reached) the same bytes in unconsumed_tail,
                # which further calls would never empty (Sol round 10)
                while buf and not d.eof:
                    out.append(d.decompress(buf, 1 << 24))
                    buf = d.unconsumed_tail
                if not d.eof:
                    out.append(d.flush())          # after the end it would decode the tail again
            except zlib.error as e:
                raise CorruptError(f"gzip stream is damaged: {e}", rule="IO.GZIP") from None
            if not d.eof:
                raise CorruptError("gzip stream is truncated", rule="IO.GZIP")
            # zero padding after a member is skipped, between members and at the end, as
            # gzip(1) and Python's gzip module do
            data = d.unused_data.lstrip(b"\x00")
        return out.getvalue()
    finally:
        out.close()


def gzip_bytes(data, level=9):
    """Deterministic gzip (mtime 0, no file name)."""
    return gzip.compress(data, compresslevel=level, mtime=0)


def unlzw(data):
    """Decode Unix compress (.Z) data.

    Codes are LSB-first, 9..maxbits wide. The compressor writes codes in groups
    of eight; whenever the width changes (growth or CLEAR) the rest of the
    current group is padding, so the reader skips to the group boundary.
    """
    if data[:2] != Z_MAGIC:
        raise CorruptError("not a .Z stream", rule="IO.LZW")
    if len(data) < 3:
        raise CorruptError(".Z stream has no header byte", rule="IO.LZW")
    maxbits = data[2] & 0x1F
    block = bool(data[2] & 0x80)
    if not 9 <= maxbits <= 16:
        raise CorruptError(f".Z stream has bad maxbits {maxbits}", rule="IO.LZW")
    stream = data[3:]
    total_bits = len(stream) * 8
    first_free = 257 if block else 256
    table = [bytes([i]) for i in range(256)] + ([b""] if block else [])
    nbits, pos, seg_start = 9, 0, 0
    prev = None
    out = bytearray()
    limit = 1 << maxbits

    while pos + nbits <= total_bits:
        byte, bit = divmod(pos, 8)
        word = int.from_bytes(stream[byte:byte + 3], "little")
        code = (word >> bit) & ((1 << nbits) - 1)
        pos += nbits
        if block and code == 256:
            group = nbits * 8
            pos = seg_start + -(-(pos - seg_start) // group) * group
            seg_start = pos
            del table[first_free:]
            nbits, prev = 9, None
            continue
        if prev is None:
            if code >= 256:
                raise CorruptError(".Z stream has a bad first code", rule="IO.LZW")
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            if len(table) < limit:
                table.append(table[prev] + entry[:1])
        elif code == len(table):
            entry = table[prev] + table[prev][:1]
            table.append(entry)
        else:
            raise CorruptError(f".Z stream has a bad code {code} at bit {pos}", rule="IO.LZW")
        out += entry
        prev = code
        if len(table) > (1 << nbits) - 1 and nbits < maxbits:
            group = nbits * 8
            pos = seg_start + -(-(pos - seg_start) // group) * group
            seg_start = pos
            nbits += 1
    return bytes(out)


class _BitWriter:
    __slots__ = ("out", "acc", "nacc", "seg_bits")

    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.nacc = 0
        self.seg_bits = 0

    def put(self, code, nbits):
        self.acc |= code << self.nacc
        self.nacc += nbits
        self.seg_bits += nbits
        while self.nacc >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.nacc -= 8

    def pad_group(self, nbits):
        """Pad with zero bits to the end of the current 8-code group."""
        group = nbits * 8
        rem = self.seg_bits % group
        if rem:
            self.put(0, group - rem)
        self.seg_bits = 0

    def flush(self):
        if self.nacc:
            self.out.append(self.acc & 0xFF)
            self.acc = 0
            self.nacc = 0
        return bytes(self.out)


def lzw(data, maxbits=16):
    """Encode as Unix compress (.Z), block mode, with compress(1)'s ratio check."""
    w = _BitWriter()
    header = Z_MAGIC + bytes([0x80 | maxbits])
    if not data:
        return header
    limit = 1 << maxbits
    table = {}
    free = 257
    nbits = 9
    checkpoint = 10000
    ratio = 0
    in_count = 0
    out_bits_at_clear = 0
    total_out_bits = 0
    ent = data[0]
    in_count = 1
    for c in data[1:]:
        in_count += 1
        key = (ent << 8) | c
        code = table.get(key)
        if code is not None:
            ent = code
            continue
        w.put(ent, nbits)
        total_out_bits += nbits
        if free > (1 << nbits) - 1 and nbits < maxbits:
            w.pad_group(nbits)
            nbits += 1
        if free < limit:
            table[key] = free
            free += 1
        elif in_count >= checkpoint:
            checkpoint = in_count + 10000
            out_bytes = max(1, (total_out_bits - out_bits_at_clear) // 8)
            rat = (in_count << 8) // out_bytes
            if rat > ratio:
                ratio = rat
            else:
                ratio = 0
                w.put(256, nbits)
                w.pad_group(nbits)
                table.clear()
                free = 257
                nbits = 9
                out_bits_at_clear = total_out_bits
                in_count = 0
                checkpoint = 10000
        ent = c
    w.put(ent, nbits)
    return header + w.flush()


def unwrap(data):
    """Strip any number of gzip/.Z layers. Returns (payload, [layers outermost first])."""
    layers = []
    while True:
        kind = detect(data)
        if kind == "gz":
            data = gunzip(data)
        elif kind == "Z":
            data = unlzw(data)
        elif kind == "bz2":
            data = bunzip2(data)
        elif kind == "zip":
            data = unzip_single(data)
        else:
            return data, layers
        layers.append(kind)
        if len(layers) > 4:
            raise CorruptError("too many nested compression layers", rule="IO.WRAP")
