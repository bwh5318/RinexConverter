"""Observation-code mapping between RINEX 2 (2-char) and RINEX 3/4 (3-char) codes,
and between RINEX 3/4 minor versions.

Policy choices (PLAN §3.5, §8: "explicit, not omniscient"). Every assumed
attribute is reported by the caller; the user can override any entry with
--overrides.

v2 -> v3 defaults follow the IGS/gfzrnx conventions listed in PLAN §3.5:
  GPS:     C1->C1C P1->C1W L1->L1C  P2->C2W L2->L2W  C2->C2X  C5->C5X
  GLONASS: C1->C1C P1->C1P L1->L1C  C2->C2C P2->C2P L2->L2P
  Galileo: C1->C1X C5->C5X C7->C7X C8->C8X C6->C6X
  SBAS:    C1->C1C C5->C5X
The L/D/S attribute of band 2 follows the code: when a v2 file has no P2 but
has C2 (an L2C-only receiver), GPS L2/D2/S2 become 2X and GLONASS 2C
(rule OBS.V2V3.CODEMAP.L2-FOLLOWS-CODE).

v3 -> v2 collapses every attribute of a band onto the v2 code; when several
v3 codes of one system map to one v2 code, the first present in
COLLAPSE_PRIORITY wins and the others are reported as losses.
"""

from rinexcore.spec import obscodes as _spec

# --- RINEX 2 -> 3 -----------------------------------------------------------

_BASE_ATTR = {
    # system: {v2 code: v3 code}
    "G": {"C1": "C1C", "P1": "C1W", "L1": "L1C", "D1": "D1C", "S1": "S1C",
          "C2": "C2X", "P2": "C2W", "L2": "L2W", "D2": "D2W", "S2": "S2W",
          "C5": "C5X", "L5": "L5X", "D5": "D5X", "S5": "S5X"},
    "R": {"C1": "C1C", "P1": "C1P", "L1": "L1C", "D1": "D1C", "S1": "S1C",
          "C2": "C2C", "P2": "C2P", "L2": "L2P", "D2": "D2P", "S2": "S2P"},
    "E": {"C1": "C1X", "L1": "L1X", "D1": "D1X", "S1": "S1X",
          "C5": "C5X", "L5": "L5X", "D5": "D5X", "S5": "S5X",
          "C7": "C7X", "L7": "L7X", "D7": "D7X", "S7": "S7X",
          "C8": "C8X", "L8": "L8X", "D8": "D8X", "S8": "S8X",
          "C6": "C6X", "L6": "L6X", "D6": "D6X", "S6": "S6X"},
    "S": {"C1": "C1C", "L1": "L1C", "D1": "D1C", "S1": "S1C",
          "C5": "C5X", "L5": "L5X", "D5": "D5X", "S5": "S5X"},
    # Non-standard systems in RINEX 2 files (PLAN §2: flagged extension).
    "J": {"C1": "C1C", "L1": "L1C", "D1": "D1C", "S1": "S1C",
          "C2": "C2X", "L2": "L2X", "D2": "D2X", "S2": "S2X",
          "C5": "C5X", "L5": "L5X", "D5": "D5X", "S5": "S5X",
          "C6": "C6X", "L6": "L6X", "D6": "D6X", "S6": "S6X"},
    # BeiDou in RINEX 2 (non-standard): B1I written as band 1 or 2, B2I band 7, B3I band 6.
    "C": {"C1": "C2I", "L1": "L2I", "D1": "D2I", "S1": "S2I",
          "C2": "C2I", "L2": "L2I", "D2": "D2I", "S2": "S2I",
          "C7": "C7I", "L7": "L7I", "D7": "D7I", "S7": "S7I",
          "C6": "C6I", "L6": "L6I", "D6": "D6I", "S6": "S6I"},
    "I": {"C5": "C5A", "L5": "L5A", "D5": "D5A", "S5": "S5A",
          "C9": "C9A", "L9": "L9A", "D9": "D9A", "S9": "S9A"},
}


def v2_to_v3(system, code, v2types, target, overrides=None):
    """(v3 code or None, rule name). `v2types` is the v2 global list, used for the
    band-2 attribute rule. The code is version-gated afterwards by gate_v3()."""
    if overrides:
        o = overrides.get(f"{system}:{code}") or overrides.get(f"*:{code}")
        if o:
            return o, "override"
    table = _BASE_ATTR.get(system)
    if not table or code not in table:
        return None, None
    v3 = table[code]
    rule = "default"
    if code[1] == "2" and code[0] in "LDS" and system in "GR":
        if "P2" not in v2types and "C2" in v2types:
            v3 = v3[:2] + ("X" if system == "G" else "C")
            rule = "L2-follows-code"
    return v3, rule


# --- RINEX 3 -> 2 -----------------------------------------------------------

def v3_to_v2(system, code, source_version=None):
    """The v2 code a v3 code collapses onto, or None if it has no v2 form. With the source
    file's version, a BeiDou B1I code is read in that version's band convention first (C1I
    in 3.02, C2I from 3.03: bds_is_b1i), so the same signal gets the same RINEX 2 code from
    every version (round 32: a 3.02 C1I was dropped where a 3.03 C2I became C2)."""
    if system == "C" and source_version and bds_is_b1i(code, source_version):
        code = code[0] + "2" + code[2]
    t, band, attr = code[0], code[1], code[2]
    if t not in "CLDS":
        return None
    if system == "G":
        if band == "1":
            if t == "C":
                if attr == "C":
                    return "C1"
                if attr in "WPYM":
                    return "P1"
                return None          # L1C signal (S/L/X) has no v2 code
            if attr in "LSX":
                return None
            return t + "1"
        if band == "2":
            if t == "C":
                if attr in "WPYMD":
                    return "P2"
                if attr in "CSLX":
                    return "C2"
                return None
            return t + "2"
        if band == "5":
            return t + "5"
        return None
    if system == "R":
        if band in "12":
            if t == "C":
                if attr == "C":
                    return "C" + band
                if attr == "P":
                    return "P" + band
                return None
            return t + band
        return None
    if system == "E":
        if band in "15786":
            return t + band
        return None
    if system == "S":
        if band in "15":
            return t + band
        return None
    if system == "J":
        if band == "1" and attr in "CSLX" or band in "256":
            if band == "1" and attr in "SLX":
                return None
            return t + band
        return None
    if system == "C":
        # BeiDou B1I: band 1 (3.02) or 2 (3.03+); B2I band 7; B3I band 6.
        if band in "2" and attr in "IQX":
            return t + "2"
        if band == "7" and attr in "IQX":
            return t + "7"
        if band == "6" and attr in "IQX":
            return t + "6"
        return None
    if system == "I":
        if band in "59" and attr in "ABCX":
            return t + band
        return None
    return None


# For each (system, band): attribute priority when several v3 codes of one
# system collapse onto one v2 code. Band 2 of GPS/GLONASS prefers the P(Y)
# family so L2 stays consistent with P2.
COLLAPSE_PRIORITY = {
    ("G", "1"): "CWPYMLSXN",
    ("G", "2"): "WPYDMNCLSX",
    ("G", "5"): "QXI",
    ("R", "1"): "CP",
    ("R", "2"): "PC",
    ("E", "1"): "CXBAZ",
    ("E", "5"): "QXI",
    ("E", "7"): "QXI",
    ("E", "8"): "QXI",
    ("E", "6"): "CXBAZ",
    ("S", "1"): "C",
    ("S", "5"): "IXQ",
    ("J", "1"): "C",
    ("J", "2"): "LXS",
    ("J", "5"): "QXI",
    ("J", "6"): "LXSEZ",
    ("C", "2"): "IXQ",
    ("C", "7"): "IXQ",
    ("C", "6"): "IXQ",
    ("I", "5"): "AXBC",
    ("I", "9"): "AXBC",
}


def collapse_rank(system, code):
    pr = COLLAPSE_PRIORITY.get((system, code[1]), "")
    i = pr.find(code[2])
    return i if i >= 0 else len(pr) + ord(code[2])


# --- RINEX 3/4 minor-version gates -----------------------------------------

def b1i_band(version):
    """BeiDou B1I band digit: 2 in 3.01, 1 in 3.02, 2 from 3.03 (rinex301.txt p.11,
    rinex302.txt p.20, rinex303.txt p.24; docs/SPEC_TABLES.md)."""
    return "1" if version == "3.02" else "2"


def bds_is_b1i(code, version):
    """True if a BeiDou code is the B1I signal, whichever band convention the writer used.

    Band 2 with I/Q/X is B1I in 3.01 and 3.03+ (and a 3.02 file using it can only mean
    B1I); band 1 with I/Q is B1I in 3.02 (and only ever B1I); band 1 X is B1I before
    3.04 and B1C (D+P) from 3.04 (rinex304.txt p.26)."""
    band, attr = code[1], code[2]
    if band == "2":
        return attr in "IQX"
    if band == "1":
        return attr in "IQ" or (attr == "X" and version < "3.04")
    return False


def gate_v3(system, code, source_version, target_version):
    """Rename a v3 code for the target minor version. Returns (code, rule) or
    (None, reason) when the target cannot hold it."""
    c = code
    rule = None
    if system == "C" and source_version >= "3" and target_version >= "3":
        tb = b1i_band(target_version)
        if bds_is_b1i(c, source_version):
            if c[1] != tb:
                c = c[0] + tb + c[2]
                rule = "OBS.V3V3.BDS-B1I-BAND"
        elif c[1] == tb:
            # band 1 is B1C (3.04+) in the source but B1I in the 3.02 target: no 3.02 code
            return None, "obs-code-not-representable"
    if not code_valid(target_version, system, c):
        return None, "obs-code-not-representable"
    return c, rule


def bds_nonstandard_band(code, version):
    """A B1I code written with the other version's band digit (e.g. C1I in a 3.01 file)."""
    return bds_is_b1i(code, version) and code[1] != b1i_band(version)


def system_valid(version, system):
    return system in _spec.SYSTEMS.get(_spec.normalize_version(version), "")


def source_defines(version, system, code):
    """Does a source file's RINEX `version` define `code` for `system`? It also answers for
    the read-only 2.00 and 2.01, which have no code table of their own: their types are
    those of 2.10 without S1 and S2, and without SBAS, which 2.10 added (rinex210.txt
    section 0.4, l.204-214)."""
    v = _spec.normalize_version(version)
    if v < "2.10":
        return system != "S" and code not in ("S1", "S2") and code_valid("2.10", system, code)
    return code_valid(v, system, code)


def code_valid(version, system, code):
    """A listed code, a pseudo-observable of the version (channel numbers 'Xn ', ionosphere
    'In ': rinex305.txt §5.3.4, rinex300.txt), or a blank-attribute code where the version
    allows an unknown tracking mode (3.00/3.01: rinex301.txt §5.1) for a listed type and band."""
    if _spec.is_valid(version, system, code):
        return True
    if len(code) == 3 and version >= "3":
        if code in _spec.pseudo_obs_codes(version):
            return True
        if code[2] == " " and _spec.blank_attribute_allowed(version):
            return any(c[:2] == code[:2] for c in _spec.valid_codes(version, system))
    return False
