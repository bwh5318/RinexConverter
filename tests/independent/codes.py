"""Observation-code validity from tests/expectations/code_validity.json (PLAN §1.5).

Independent of rinexcore/rinexconv: the JSON was transcribed straight from specs/text/*.txt,
and this module reads only that JSON. Use it as the second transcription that the converter's
own code tables are compared against.

    valid("3.05", "C", "C2I")   -> True
    valid("3.02", "C", "C2I")   -> False   (3.02 puts BeiDou B1I on band 1: C1I)
    valid("2.11", " ", "C2")    -> True    (blank system = GPS in RINEX 2)
"""

import json
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "expectations",
                     "code_validity.json")
with open(_PATH, "rb") as _fh:
    TABLE = json.loads(_fh.read().decode("utf-8"))

_V = TABLE["versions"]


def version_key(version):
    """3.05 or '3.05' -> '3.05'; '2.1' -> '2.10'; '4' -> '4.00'. KeyError if the table has no such version."""
    key = "%.2f" % float(version)
    if key not in _V:
        raise KeyError("no code table for RINEX version %r" % (version,))
    return key


def versions():
    return list(_V)


def systems(version):
    return list(_V[version_key(version)]["systems"])


def _system(entry, system):
    if system in ("", " ") and entry.get("blank_system_is"):
        return entry["blank_system_is"]
    return system


def codes(version, system):
    """Full codes ('C1C', or 'C1' for RINEX 2) for ordinary observables, without pseudo-observables."""
    entry = _V[version_key(version)]
    by_type = entry["codes"].get(_system(entry, system), {})
    return frozenset(t + rest for t, rests in by_type.items() for rest in rests)


def pseudo_codes(version, system):
    """Pseudo-observable codes ('X1 ', 'I2 ', ...) for this version and system; empty if none."""
    entry = _V[version_key(version)]
    s = _system(entry, system)
    out = set()
    for name, p in entry["pseudo"].items():
        if name.startswith("_"):
            continue
        out.update(p["codes"].get(s, ()))
    return frozenset(out)


def blank_attribute_allowed(version):
    """True/False for RINEX 3/4; None for RINEX 2 (no attribute)."""
    return _V[version_key(version)]["blank_attribute"]["allowed"]


def valid(version, system, code, pseudo=True):
    """True if `code` is a valid observation code for `system` in RINEX `version`.

    RINEX 3/4: a 2-character code is read as a blank attribute ('L2' == 'L2 '). A blank
    attribute is valid only for a pseudo-observable that the version defines with a blank
    attribute, or, where the version allows unknown tracking modes (3.00, 3.01), when the
    type and band exist for the system. Pseudo-observables count unless pseudo=False.
    """
    entry = _V[version_key(version)]
    s = _system(entry, system)
    if s not in entry["systems"]:
        return False
    n = entry["code_length"]
    if n == 3 and len(code) == 2:
        code = code + " "
    if len(code) != n:
        return False
    if code in codes(version, s):
        return True
    if pseudo and code in pseudo_codes(version, s):
        return True
    if n == 3 and code[2] == " " and entry["blank_attribute"]["allowed"] is True:
        return any(c[:2] == code[:2] for c in codes(version, s))
    return False


# The read-only RINEX 2.00 and 2.01 have no table here: 2.10 added the S1 and S2 types and
# the SBAS ('S', Inmarsat GPS payloads) system to them (rinex210.txt section 0.4, l.204-214).
_V20X_NOT = {"S1", "S2"}


def source_systems(version):
    """Systems a source file of `version` (2.00-4.02) can define."""
    if float(version) < 2.1:
        return [s for s in systems("2.10") if s != "S"]
    return systems(version)


def source_codes(version, system):
    """Codes a source file of `version` (2.00-4.02) defines for `system`."""
    if float(version) < 2.1:
        return frozenset() if system == "S" else codes("2.10", system) - _V20X_NOT
    return codes(version, system)


def source_valid(version, system, code):
    """valid() for a source version, 2.00 and 2.01 included."""
    if float(version) < 2.1:
        return system != "S" and code not in _V20X_NOT and valid("2.10", system, code)
    return valid(version, system, code)
