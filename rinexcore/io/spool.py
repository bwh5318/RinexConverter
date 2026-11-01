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


class Spool:
    def __init__(self):
        self._pieces = []
        self._size = 0
        self._file = None

    def append(self, piece):
        if not piece:
            return
        self._size += len(piece)
        if self._file is None and self._size > SPILL_BYTES:
            self._file = tempfile.TemporaryFile(buffering=0)
            for p in self._pieces:
                self._file.write(p)
            self._pieces = []
        if self._file is None:
            self._pieces.append(piece)
        else:
            self._file.write(piece)

    def __len__(self):
        return self._size

    def getvalue(self):
        """The bytes appended so far, once; the spool is closed after."""
        if self._file is None:
            out = b"".join(self._pieces)
            self._pieces = []
            return out
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


def join_bytes(pieces):
    """b"".join(pieces) for an iterable, held about once (see the module docstring)."""
    sp = Spool()
    try:
        for p in pieces:
            sp.append(p)
        return sp.getvalue()
    finally:
        sp.close()
