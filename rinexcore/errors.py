"""Errors and run outcomes (PLAN.md §1 clause 1).

Every conversion ends in one of four named outcomes. The two refusals are
RinexError subclasses; nothing else may escape the engine. Invocation and I/O
failures are a separate class (InvocationError) and are never reported as
refused-corrupt.
"""

CONVERTED = "converted"
CONVERTED_WITH_REMOVAL = "converted-with-removal"
REFUSED_MISSING = "refused-missing-information"
REFUSED_CORRUPT = "refused-corrupt"
# Not one of PLAN §1's four: the input is valid and complete, but the target
# version cannot hold any of its data (e.g. a BeiDou-only nav file to RINEX 2).
REFUSED_NOT_REPRESENTABLE = "refused-not-representable"

# Process exit codes. 0/1 are the converted outcomes; refusals and invocation
# failures each get their own code so scripts can tell them apart.
EXIT_CODES = {
    CONVERTED: 0,
    CONVERTED_WITH_REMOVAL: 1,
    REFUSED_MISSING: 3,
    REFUSED_CORRUPT: 4,
    REFUSED_NOT_REPRESENTABLE: 6,
    "invocation-error": 2,
    "io-error": 5,
    "internal-error": 7,
}


class RinexError(Exception):
    """Base class for the two refusal outcomes."""

    outcome = REFUSED_CORRUPT


class CorruptError(RinexError):
    """Data-level corruption the validator can point to (file, line, column, rule)."""

    outcome = REFUSED_CORRUPT

    def __init__(self, message, *, line=None, column=None, rule=None, path=None):
        self.line = line
        self.column = column
        self.rule = rule
        self.path = path
        where = []
        if path:
            where.append(str(path))
        if line is not None:
            where.append(f"line {line}")
        if column is not None:
            where.append(f"col {column}")
        if rule:
            where.append(rule)
        super().__init__(f"{message} ({', '.join(where)})" if where else message)


class MissingInformationError(RinexError):
    """The target needs a value no source supplied (PLAN §1 clause 8)."""

    outcome = REFUSED_MISSING

    def __init__(self, message, *, missing=None):
        self.missing = missing
        super().__init__(message)


class NotRepresentableError(RinexError):
    """The target version can hold none of the input's data; nothing is written."""

    outcome = REFUSED_NOT_REPRESENTABLE


class InvocationError(Exception):
    """Bad arguments or an unusable input/output path: not a RINEX outcome."""
