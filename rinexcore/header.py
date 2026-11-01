"""Header records: columns 1-60 content, 61-80 label (all RINEX versions)."""

from decimal import Decimal, InvalidOperation

from .errors import CorruptError

END = "END OF HEADER"


class HeaderRecord:
    __slots__ = ("label", "content", "lineno")

    def __init__(self, label, content, lineno=None):
        self.label = label
        self.content = content
        self.lineno = lineno

    @classmethod
    def from_line(cls, line, lineno=None):
        return cls(line[60:80].strip(), line[:60], lineno)

    def line(self):
        return (self.content.ljust(60)[:60] + self.label).rstrip()

    def __repr__(self):
        return f"HeaderRecord({self.label!r}, {self.content!r})"

    def __eq__(self, other):
        return (isinstance(other, HeaderRecord) and self.label == other.label
                and self.content.rstrip() == other.content.rstrip())

    def __hash__(self):
        return hash((self.label, self.content.rstrip()))


def rec(label, content):
    return HeaderRecord(label, content)


def read_header(lines, start=0):
    """Header records up to and including END OF HEADER. Returns (records, next index)."""
    records = []
    i = start
    n = len(lines)
    while i < n:
        line = lines[i]
        r = HeaderRecord.from_line(line, i + 1)
        if not r.label and not line.strip():
            # A blank line inside the header: tolerated, dropped (reported by the caller).
            i += 1
            records.append(HeaderRecord("", "", i))
            continue
        records.append(r)
        i += 1
        if r.label == END:
            return records, i
    raise CorruptError("no END OF HEADER record", line=n, rule="HDR.END")


def ffield(s, what, lineno=None, column=None):
    """Decimal from a fixed-width numeric field; None if blank. Accepts D/d exponents."""
    t = s.strip()
    if not t:
        return None
    try:
        return Decimal(t.replace("D", "E").replace("d", "e"))
    except InvalidOperation:
        raise CorruptError(f"bad number {t!r} in {what}", line=lineno, column=column,
                           rule="HDR.NUMBER") from None


def ifield(s, what, lineno=None, column=None):
    t = s.strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        raise CorruptError(f"bad integer {t!r} in {what}", line=lineno, column=column,
                           rule="HDR.INTEGER") from None


def fmt_f(value, width, decimals):
    """Fortran Fw.d of a Decimal, rounding half-even; None -> blanks. Raises OverflowError."""
    if value is None:
        return " " * width
    q = Decimal(1).scaleb(-decimals)
    s = f"{Decimal(value).quantize(q):.{decimals}f}"
    if s.startswith("-") and Decimal(s) == 0:
        s = s[1:]
    if len(s) > width:
        # Fortran drops a leading zero before the point when that makes it fit.
        if s.startswith("0."):
            s = s[1:]
        elif s.startswith("-0."):
            s = "-" + s[2:]
    if len(s) > width:
        raise OverflowError(f"{value} does not fit F{width}.{decimals}")
    return s.rjust(width)
