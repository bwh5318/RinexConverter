"""Phase-alignment shift tables of RINEX 3.02-3.05, for --align-phases (PLAN section 3.3 rule 2).

The tables give, per carrier-phase code, the correction added to the phase as issued to align it
with the band's reference signal ("Phase Correction applied to each observed phase to obtain
aligned phase. (phiRINEX = phi original (as issued by the SV) + delta-phi)"):

    3.02  Table A19, rinex302.txt p.80-82
    3.03  Table A23, rinex303.txt p.92-94 (3.03 Update 1 identical)
    3.04  Table A23, rinex304.txt p.97-100
    3.05  Table A23, rinex305.txt p.88-91

Transcribed from those pages (checked against docs/PHASE_ALIGNMENT.md section 2, which compared
the PDFs). Values are cycles. "R" is "None (Reference Signal)", "0" is "None"; both mean no
correction. A code that is not in a version's table here has no usable number there, and the
caller refuses rather than guess (PLAN section 1 clause 8):
  - rows "Must be aligned to X" with no value (GPS L5X, Galileo L1X/L5X/L6X/L7X/L8X, ...);
  - "Restricted" and "N/A" rows (NavIC L5B/L9B, QZSS L1Z);
  - rows whose value depends on the satellite block, which RINEX does not record: GPS L2C
    (Block II/IIA/IIR 0, IIR-M/IIF/III -1/4, Note 2) and QZSS L1S in 3.04/3.05 (Block I 0,
    Block II +1/4, Note 5);
  - QZSS L5Z ("None must be aligned to L5D", ambiguous);
  - codes no table lists (all of SBAS; GPS L1Y/L1M/L2Y/L2M; Galileo L1A/L1Z/L6A/L6Z).
  - the 3.04 BDS-3 rows L1P, L5P, L7P, L8P, printed "+1/4 (preliminary)" (rinex304.txt Table A23
    p.99), withdrawn in 3.05 because "the 1/4 cycle alignment direction is implementation
    dependent" (rinex305.txt history p.10; docs/PHASE_ALIGNMENT.md section 4 item 5): applying
    them could shift the wrong way, so they are treated as 'must be aligned to' rows (the
    user's decision, 2026-11-02).
RINEX 4 tables (A39/A45) carry no values at all (4.00
history p.118), and 3.01 has no table: --align-phases is not offered for them (the user,
2026-11-02).
"""

from decimal import Decimal

_Q = {"R": "R", "0": "0", "+1/4": "+0.25", "-1/4": "-0.25", "+1/2": "+0.5", "-1/2": "-0.5"}


def _rows(text):
    """'L1C R, L1S +1/4, ...' -> {code: 'R' | '0' | '+0.25' ...}."""
    out = {}
    for item in text.split(","):
        item = item.strip()
        if item:
            code, val = item.split()
            out[code] = _Q[val]
    return out


_GPS = _rows("L1C R, L1S +1/4, L1L +1/4, L1X +1/4, L1P +1/4, L1W +1/4, L1N +1/4,"
             "L2D 0, L2W 0, L2N 0, L2S -1/4, L2L -1/4, L2X -1/4, L2P R, L5I R, L5Q -1/4")
_GAL = _rows("L1B R, L1C +1/2, L5I R, L5Q -1/4, L7I R, L7Q -1/4, L8I R, L8Q -1/4, L6B R, L6C -1/2")
_GLO_BASE = "L1C R, L1P +1/4, L2C R, L2P +1/4, L3I R"
_GLO_G1A_G2A = ", L4A R, L4B 0, L4X 0, L6A R, L6B 0, L6X 0"
_QZS_BASE = "L1C R, L1L +1/4, L1X +1/4, L2S R, L2L 0, L2X 0, L5I R, L5Q -1/4, L6S R, L6L 0, L6X 0"
_IRN = _rows("L5A R, L5C 0, L9A R, L9C 0")

TABLES = {
    "3.02": {
        "G": _GPS,
        "R": _rows(_GLO_BASE + ", L3Q -1/4"),
        "E": _GAL,
        "J": _rows(_QZS_BASE + ", L1S 0"),
        "C": _rows("L1I R, L1Q -1/4, L7I R, L7Q -1/4, L6I R, L6Q -1/4"),
    },
    "3.03": {
        "G": _GPS,
        "R": _rows(_GLO_BASE + ", L3Q -1/4"),
        "E": _GAL,
        "J": _rows(_QZS_BASE + ", L1S 0"),
        "C": _rows("L2I R, L2Q -1/4, L7I R, L7Q -1/4, L6I R, L6Q -1/4"),
        "I": _IRN,
    },
    "3.04": {
        "G": _GPS,
        "R": _rows(_GLO_BASE + ", L3Q +1/4" + _GLO_G1A_G2A),
        "E": _GAL,
        "J": _rows(_QZS_BASE + ", L5D R, L5P -1/4, L6E 0, L6Z 0"),
        # (L1P, L5P, L7P, L8P '+1/4 (preliminary)' left out: p.99, withdrawn in 3.05 p.10)
        "C": _rows("L2I R, L2Q -1/4, L1D R, L5D R, L7I R, L7Q -1/4, L7D R, L8D R, L6I R, L6Q -1/4"),
        "I": _IRN,
    },
    "3.05": {
        "G": _GPS,
        "R": _rows(_GLO_BASE + _GLO_G1A_G2A),
        "E": _GAL,
        "J": _rows(_QZS_BASE + ", L5D R, L5P -1/4, L6E 0, L6Z 0"),
        "C": _rows("L2I R, L1D R, L1S R, L5D R, L7I R, L7Q -1/4, L7D R, L8D R, L6I R, L6D R"),
        "I": _IRN,
    },
}

RULE_TABLE = {"3.02": "A19", "3.03": "A23", "3.04": "A23", "3.05": "A23"}


def shift(version, system, code):
    """The correction (Decimal cycles; 0 for a reference or 'None' row) the `version` table
    gives for a phase `code` of `system`, or None when the table has no usable number."""
    v = TABLES.get(version, {}).get(system, {}).get(code)
    if v is None:
        return None
    return Decimal(0) if v in ("R", "0") else Decimal(v)


def is_reference(version, system, code):
    return TABLES.get(version, {}).get(system, {}).get(code) == "R"
