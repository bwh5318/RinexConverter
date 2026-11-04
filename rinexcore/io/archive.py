"""Tar archives of RINEX files: .tar, and a tar inside gzip, .Z, bzip2 or a one-file zip
(.tar.gz, .tgz, .tar.Z, .tar.bz2), read with the standard library's tarfile.

The user's choice (2026-11-01, docs/DECISIONS.md): every RINEX member is converted as if it
had been given on the command line, other members are skipped and listed, and nothing asks
first. The archive is held in memory like any other input and nothing is unpacked to disk.
A member is handed on under its name without the folder part, so a member called '../x' or
'C:\\x' cannot place an output outside the output folder.
"""

import bz2
import io
import posixpath
import tarfile
import zlib

from ..errors import CorruptError
from . import compress

_PEEK = 1024        # decoded bytes enough for a tar header block (512) or a RINEX first line
_RINEX_LABELS = (b"RINEX VERSION / TYPE", b"CRINEX VERS   / TYPE")


def peek(data, n=_PEEK):
    """The first n bytes of `data` with its compression layers removed, decoding only a
    prefix of each layer (a one-file zip is read whole). b'' where a layer cannot be read:
    the full read reports that."""
    for _ in range(5):
        kind = compress.detect(data)
        try:
            if kind == "gz":
                data = zlib.decompressobj(wbits=31).decompress(data[:1 << 16], 1 << 16)
            elif kind == "Z":
                data = compress.unlzw(data[:1 << 16])
            elif kind == "bz2":
                # a bzip2 block (up to 900 kB before compression) decodes only when complete
                data = bz2.BZ2Decompressor().decompress(data[:1 << 21], 1 << 16)
            elif kind == "zip":
                data = compress.unzip_single(data)
            else:
                return data[:n]
        except (zlib.error, OSError, ValueError, EOFError, CorruptError):
            return b""
    return b""


def _tar_block(block):
    """True for a POSIX/GNU tar header block: the 'ustar' magic at offset 257 and a checksum
    that adds up (tarfile.TarInfo.frombuf), so that a RINEX header with 'ustar' in those
    columns is never taken for an archive. Old v7 archives, which have no magic, are not
    recognised."""
    if len(block) < 512 or block[257:262] != b"ustar":
        return False
    try:
        tarfile.TarInfo.frombuf(block[:512], "utf-8", "surrogateescape")
    except tarfile.HeaderError:
        return False
    return True


def is_tar(data):
    """True if `data`, once uncompressed, is a tar archive."""
    return _tar_block(peek(data, 512))


def is_tar_payload(payload):
    """True if `payload` (already uncompressed) is a tar archive."""
    return _tar_block(payload[:512])


def is_rinex(data):
    """True if `data`, once uncompressed, starts like a RINEX or Compact RINEX file: the
    label of its first line (columns 61-80) is RINEX VERSION / TYPE or CRINEX VERS   / TYPE."""
    first = peek(data).split(b"\n", 1)[0].rstrip(b"\r")
    return first[60:80].rstrip() in _RINEX_LABELS


def members(data):
    """Yield (path in the archive, file name, bytes, why) for each member of the tar archive
    `data` (compressed or not), in archive order: bytes and why=None for a regular file;
    bytes=None and why for anything else (folders, links, devices, a member with no file
    name). Raises CorruptError (IO.TAR) for a damaged archive, after the members before the
    damage."""
    payload, _ = compress.unwrap(data)
    last = None
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tf:
            for m in tf:
                last = m.name
                base = posixpath.basename(m.name.replace("\\", "/"))
                if not m.isreg():
                    yield m.name, base, None, "not a regular file"
                elif not _usable(base):
                    yield m.name, base, None, "no usable file name"
                else:
                    yield m.name, base, tf.extractfile(m).read(), None
            end = tf.offset
    except (tarfile.TarError, OSError, EOFError) as e:
        raise CorruptError(f"tar archive is damaged: {e}", rule="IO.TAR") from None
    _check_end(payload, end, last)


def _usable(base):
    """A member's file name usable for the output and report names made from it
    (names.unsafe_file_name: Windows' rules, device names such as CON, NUL.26o or COM¹)."""
    from .. import names
    return names.unsafe_file_name(base) is None


def _check_end(payload, end, last):
    """tarfile ends its listing quietly at a header it cannot read after the first member: a
    bad checksum, a header cut short, or no end-of-archive block (Sol round 29: the members
    after a damaged second header vanished with no error). So what follows the last member
    must be the end of the archive: a zero block (POSIX ustar ends with two), and only zeros
    after it. Anything else is damage, or a second archive appended, refused either way."""
    after = f" after member {last!r}" if last else ""
    block = payload[end:end + 512]
    if len(block) < 512:
        raise CorruptError(f"tar archive is cut short{after}: no end-of-archive block", rule="IO.TAR")
    if block.strip(b"\0"):
        raise CorruptError(f"tar archive is damaged{after}: the next header cannot be read",
                           rule="IO.TAR")
    if payload[end + 512:].strip(b"\0"):
        raise CorruptError(f"tar archive has data after its end{after} (a damaged or appended "
                           "archive)", rule="IO.TAR")
