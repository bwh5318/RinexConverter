"""Bytes built from pieces without holding them twice.

b"".join(pieces) holds the pieces and their join at once, twice the output: 3 GB for a 24 h
1 Hz file of 1.5 GB (docs/DECISIONS.md, 24 h 1 Hz test). A Spool keeps small outputs in
memory; past SPILL_BYTES it writes the pieces to a temporary file (stdlib tempfile, deleted
on close) and getvalue() reads them back in one read of known size, which allocates the
result once. Growing one buffer instead (BytesIO, bytearray) measured the same 2x peak on
Windows. A single read is capped at 2 GB on Windows, so a larger output is joined from its
reads, with one extra copy.
"""

import tempfile

SPILL_BYTES = 64 << 20
WRITE_BYTES = 1 << 20          # once spilled, small pieces are written this many at a time


class Spool:
    def __init__(self):
        self._pieces = []
        self._size = 0
        self._file = None
        self._wbuf = []            # pieces not yet written to the file (spilled), < WRITE_BYTES
        self._wsize = 0

    def append(self, piece):
        if not piece:
            return
        self._size += len(piece)
        if self._file is None and self._size > SPILL_BYTES:
            self._file = tempfile.TemporaryFile(buffering=0)
            pieces, self._pieces = self._pieces, []
            for p in pieces:
                self._write(p)
        if self._file is None:
            self._pieces.append(piece)
        else:
            self._write(piece)

    def _write(self, piece):
        """Write to the file, small pieces gathered to about WRITE_BYTES first (the file is
        unbuffered: a write per piece was a system call per hatanaka epoch, 5,800 for a 90 MB
        file); the bytes and their order are those of a write per piece."""
        if len(piece) >= WRITE_BYTES:
            self._flush()
            self._file.write(piece)
            return
        self._wbuf.append(piece)
        self._wsize += len(piece)
        if self._wsize >= WRITE_BYTES:
            self._flush()

    def _flush(self):
        if self._wbuf:
            self._file.write(b"".join(self._wbuf))
            self._wbuf = []
            self._wsize = 0

    def __len__(self):
        return self._size

    def getvalue(self):
        """The bytes appended so far, once; the spool is closed after."""
        if self._file is None:
            out = b"".join(self._pieces)
            self._pieces = []
            return out
        self._flush()
        f, self._file = self._file, None
        try:
            f.seek(0)
            out = f.read(self._size)
            if len(out) < self._size:
                parts = [out]
                got = len(out)
                while got < self._size:
                    parts.append(f.read(self._size - got))
                    if not parts[-1]:
                        raise OSError(f"temporary file holds {got} of {self._size} bytes")
                    got += len(parts[-1])
                out = b"".join(parts)
            return out
        finally:
            f.close()

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None
        self._pieces = []
        self._wbuf = []


def join_bytes(pieces):
    """b"".join(pieces) for an iterable, held about once (see the module docstring)."""
    sp = Spool()
    try:
        for p in pieces:
            sp.append(p)
        return sp.getvalue()
    finally:
        sp.close()
