"""Satellite systems and observation codes, per RINEX version and system.

Data only, transcribed by hand from ``specs/text/``. Citations give the spec
file, the page from its ``===== page N =====`` marker (``p.N``) and the printed
table number. The RINEX 2 texts have no page markers, so they are cited by line
number (``l.N``). For 3.03 the cited text is ``rinex303_update1.txt`` (3.03
Update 1, 25 Jan 2017); its observation-code tables are identical to the
original 3.03 text ``rinex303.txt`` (only the page numbers of some later
sections shift by one), and the unit tests check every code against both.

Contents
--------
``VERSIONS``
    The version keys, normalised to ``"X.YY"``.
``SYSTEMS``
    Version -> satellite-system letters allowed in OBSERVATION files. ``M``
    (mixed) is a file-type value, not a satellite system, so it is not listed.
``SIGNAL_ROWS``
    RINEX 3/4 only: version -> system -> rows of the printed observation-code
    table, as ``(band, attribute, types, signal)``. ``types`` is the subset of
    ``"CLDS"`` that the row gives a code for; codeless rows (attribute ``N``)
    have no pseudorange, so their types are ``"LDS"``.
``OBS_CODES``
    Version -> system -> frozenset of valid observation codes: 2-character for
    RINEX 2 (``"C1"``), 3-character for RINEX 3/4 (``"C1C"``). Built from
    ``SIGNAL_ROWS`` for RINEX 3/4.
``V2_HEADER_CODES``
    RINEX 2 only: the codes allowed in ``# / TYPES OF OBSERV`` (one list for
    the whole file, not per system).
``PSEUDO_OBS``
    RINEX 3/4: the pseudo-observables ``I`` (ionosphere phase delay, 3.00 to
    3.04 only) and ``X`` (receiver channel number), with their band digits.
``BLANK_ATTRIBUTE``
    RINEX 3/4: whether a blank attribute ("unknown tracking mode") is allowed.
``BDS_B1_READ_RULE``
    The reading rule for BeiDou B1I codes in RINEX 3.02 files.
``CITATIONS``, ``SOURCE_SPANS``, ``INFERRED``
    Where each table comes from, as text and as machine-checkable spans; and
    the places where the per-system split is an inference, not spec text.

Version gates worth knowing (all verified in the text; see ``CITATIONS``)
-------------------------------------------------------------------------
- 2.10 has Transit (``T``, codes ``T1``/``T2``) and no ``C2``; 2.11 drops
  Transit, adds Galileo (``E``) and the codes C2, C5..C8, L5..L8 etc.
- BeiDou ("Compass" in 3.01) B1I: ``C2I`` in 3.01, ``C1I`` in 3.02, ``C2I``
  again from 3.03 on.
- BDS-3 signals (B1C, B2a, B2b, B2a+b) appear in 3.04. 3.05 re-codes B1A and
  B3A: 3.04 ``C1A``/``C6A`` and BDS codeless ``L1N`` exist only in 3.04, and
  3.05+ use ``1S/1L/1Z`` (B1A) and ``6D/6P/6Z`` (B3A) instead.
- GLONASS G3 (``3I/3Q/3X``) from 3.02; GLONASS CDMA G1a (``4A/4B/4X``) and G2a
  (``6A/6B/6X``) from 3.04.
- QZSS from 3.02. Block II ``5D/5P/5Z``, ``6E/6Z`` from 3.04; L1Sb ``1B`` in
  3.05 to 4.01 only (4.02 removed it from Table 14); C/B ``1E`` from 4.00.
- IRNSS/NavIC from 3.03; NavIC L1 ``1D/1P/1X`` from **4.01** (Table 16 of
  4.01, revision Jun 2023); 4.02 adds the NavIC L1 *navigation* message, not
  new observation codes.
- GPS L1C ``1S/1L/1X`` from 3.01; GPS RMP-antenna M code ``1R``/``2R`` from
  4.01.
- Pseudo-observable ``I`` exists in 3.00 to 3.04 and was removed in 3.05.
"""

VERSIONS = (
    "2.10", "2.11",
    "3.00", "3.01", "3.02", "3.03", "3.04", "3.05",
    "4.00", "4.01", "4.02",
)

# ---------------------------------------------------------------------------
# Satellite systems allowed in observation files
# ---------------------------------------------------------------------------
# Order follows the RINEX VERSION / TYPE row of each header table.
SYSTEMS = {
    # 2.10 sec. 5.1 (l.449-457): G or blank = GPS, R, S (GEO payload), T (Transit).
    "2.10": "GRST",
    # 2.11 sec. 5.1 (l.566-576) and sec. 10.1.3: E added; Transit removed
    # (sec. 10.1.1, l.989-990: "obsolete and has been removed").
    "2.11": "GRSE",
    "3.00": "GRES",
    # 3.01: Table 1 (p.8) and sec. 9.3 add C (Compass). Table A1 RINEX
    # VERSION / TYPE (p.29) still lists only G/R/E/S/M -- see docs/SPEC_TABLES.md.
    "3.01": "GRESC",
    "3.02": "GREJCS",
    "3.03": "GREJCIS",
    "3.04": "GREJCIS",
    "3.05": "GREJCIS",
    "4.00": "GREJCIS",
    "4.01": "GREJCIS",
    "4.02": "GREJCIS",
}

SYSTEMS_CITE = {
    "2.10": "rinex210.txt l.449-461 sec. 5.1; l.818-825 Table A1",
    "2.11": "rinex211.txt l.566-580 sec. 5.1; l.1073-1080 Table A1; l.1003-1006 sec. 10.1.3",
    "3.00": "rinex300.txt p.8 Table 1; p.26 Table A1",
    "3.01": "rinex301.txt p.8 Table 1; p.25 sec. 9.3; p.29 Table A1 (omits C)",
    "3.02": "rinex302.txt p.13 Figure 1; p.51 Table A2",
    "3.03": "rinex303_update1.txt p.54 Table A2 (Figure 1, p.17, is an image and not in the text)",
    "3.04": "rinex304.txt p.59 Table A2",
    "3.05": "rinex305.txt p.52 Table A2",
    "4.00": "rinex_4.00.txt p.54 Table A2",
    "4.01": "rinex_4.01.txt p.58 Table A2",
    "4.02": "rinex_4.02.txt p.60 Table A2",
}

SYSTEM_NAMES = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "S": "SBAS (GEO payload)",
    "J": "QZSS",
    "C": "BeiDou (Compass in 3.01)",
    "I": "NavIC/IRNSS",
    "T": "Transit (NNSS), RINEX 2.10 only",
}

# ---------------------------------------------------------------------------
# RINEX 2: two-character codes
# ---------------------------------------------------------------------------
# 2.10 Table A1, # / TYPES OF OBSERV (l.886-897): one list for the file:
#   L1, L2; C1; P1, P2; D1, D2; T1, T2 (Transit, 150/400 MHz); S1, S2.
# There is no C2 in 2.10 (added in 2.11, l.952-978).
_V2_210 = frozenset(("L1", "L2", "C1", "P1", "P2", "D1", "D2", "T1", "T2", "S1", "S2"))

# 2.11 sec. 10.1.1 table (l.961-980), repeated as the frequency-code table in
# Table A1 (l.1158-1165). Per system:
_V2_211_G = frozenset((
    "C1", "P1", "L1", "D1", "S1",       # L1 1575.42
    "C2", "P2", "L2", "D2", "S2",       # L2 1227.60
    "C5", "L5", "D5", "S5",             # L5 1176.45
))
_V2_211_R = frozenset((
    "C1", "P1", "L1", "D1", "S1",       # G1
    "C2", "P2", "L2", "D2", "S2",       # G2
))
_V2_211_E = frozenset((
    "C1", "L1", "D1", "S1",             # E2-L1-E1
    "C5", "L5", "D5", "S5",             # E5a
    "C7", "L7", "D7", "S7",             # E5b
    "C8", "L8", "D8", "S8",             # E5a+b
    "C6", "L6", "D6", "S6",             # E6
))
_V2_211_S = frozenset((
    "C1", "L1", "D1", "S1",             # L1
    "C5", "L5", "D5", "S5",             # L5
))

V2_HEADER_CODES = {
    "2.10": _V2_210,
    "2.11": _V2_211_G | _V2_211_R | _V2_211_E | _V2_211_S,
}

_V2_CODES = {
    "2.10": {
        # INFERRED split: 2.10 gives one global list (see INFERRED below).
        "G": frozenset(("L1", "L2", "C1", "P1", "P2", "D1", "D2", "S1", "S2")),
        "R": frozenset(("L1", "L2", "C1", "P1", "P2", "D1", "D2", "S1", "S2")),
        "S": frozenset(("C1", "L1", "D1", "S1")),
        "T": frozenset(("T1", "T2")),
    },
    "2.11": {
        "G": _V2_211_G,
        "R": _V2_211_R,
        "E": _V2_211_E,
        "S": _V2_211_S,
    },
}

# ---------------------------------------------------------------------------
# RINEX 3 and 4: rows of the printed observation-code tables
# ---------------------------------------------------------------------------
# Each row: (band digit, attribute, types given a code, signal as printed).
_ALL = "CLDS"
_NO_CODE = "LDS"    # codeless: the table prints "--" (or nothing) for the pseudorange

# GPS ------------------------------------------------------------------------
# 3.00 Table 5, rinex300.txt p.10.
_GPS_300 = (
    ("1", "C", _ALL, "L1 C/A"),
    ("1", "P", _ALL, "L1 P"),
    ("1", "W", _ALL, "L1 Z-tracking and similar (AS on)"),
    ("1", "Y", _ALL, "L1 Y"),
    ("1", "M", _ALL, "L1 M"),
    ("1", "N", _NO_CODE, "L1 codeless"),
    ("2", "C", _ALL, "L2 C/A"),
    ("2", "D", _ALL, "L2 L1(C/A)+(P2-P1) semi-codeless"),
    ("2", "S", _ALL, "L2C (M)"),
    ("2", "L", _ALL, "L2C (L)"),
    ("2", "X", _ALL, "L2C (M+L)"),
    ("2", "P", _ALL, "L2 P"),
    ("2", "W", _ALL, "L2 Z-tracking and similar (AS on)"),
    ("2", "Y", _ALL, "L2 Y"),
    ("2", "M", _ALL, "L2 M"),
    ("2", "N", _NO_CODE, "L2 codeless"),
    ("5", "I", _ALL, "L5 I"),
    ("5", "Q", _ALL, "L5 Q"),
    ("5", "X", _ALL, "L5 I+Q"),
)
# 3.01 Table 5 (rinex301.txt p.10-11) adds L1C. 3.01 names the channels
# L1C (M)/(L)/(M+L); 3.02 renames them L1C (D)/(P)/(D+P) with the same codes.
# Unchanged through 4.00 (3.02 Table 2 p.17, 3.03 Table 4 p.21, 3.04 Table 4
# p.22, 3.05 Table 14 p.30, 4.00 Table 10 p.27).
_GPS_301 = (
    ("1", "C", _ALL, "L1 C/A"),
    ("1", "S", _ALL, "L1C (D) [3.01: L1C (M)]"),
    ("1", "L", _ALL, "L1C (P) [3.01: L1C (L)]"),
    ("1", "X", _ALL, "L1C (D+P) [3.01: L1C (M+L)]"),
) + _GPS_300[1:]
# 4.01 Table 10 (rinex_4.01.txt p.29) adds "M (RMP antenna)" on L1 and L2.
# Same in 4.02 Table 10 (p.30).
_GPS_401 = _GPS_301 + (
    ("1", "R", _ALL, "L1 M (RMP antenna)"),
    ("2", "R", _ALL, "L2 M (RMP antenna)"),
)

# GLONASS --------------------------------------------------------------------
# 3.00 Table 5 (p.10-11); 3.01 Table 5 (p.11) identical.
_GLO_300 = (
    ("1", "C", _ALL, "G1 C/A"),
    ("1", "P", _ALL, "G1 P"),
    ("2", "C", _ALL, "G2 C/A (GLONASS M)"),
    ("2", "P", _ALL, "G2 P"),
)
# 3.02 Table 3 (p.18) adds G3; 3.03 Table 5 (p.22) identical.
_GLO_302 = _GLO_300 + (
    ("3", "I", _ALL, "G3 I"),
    ("3", "Q", _ALL, "G3 Q"),
    ("3", "X", _ALL, "G3 I+Q"),
)
# 3.04 Table 5 (p.23) adds the CDMA bands G1a (band 4) and G2a (band 6).
# Identical in 3.05 Table 15 (p.31), 4.00 Table 11 (p.28), 4.01 Table 11
# (p.30), 4.02 Table 11 (p.31).
_GLO_304 = (
    ("1", "C", _ALL, "G1 C/A"),
    ("1", "P", _ALL, "G1 P"),
    ("4", "A", _ALL, "G1a L1OCd"),
    ("4", "B", _ALL, "G1a L1OCp"),
    ("4", "X", _ALL, "G1a L1OCd+L1OCp"),
    ("2", "C", _ALL, "G2 C/A (GLONASS M)"),
    ("2", "P", _ALL, "G2 P"),
    ("6", "A", _ALL, "G2a L2CSI"),
    ("6", "B", _ALL, "G2a L2OCp"),
    ("6", "X", _ALL, "G2a L2CSI+L2OCp"),
    ("3", "I", _ALL, "G3 I"),
    ("3", "Q", _ALL, "G3 Q"),
    ("3", "X", _ALL, "G3 I+Q"),
)

# Galileo --------------------------------------------------------------------
# 3.00 Table 5 (p.11). The codes are identical in every later version: 3.01
# Table 5 p.11, 3.02 Table 4 p.18, 3.03 Table 6 p.22, 3.04 Table 6 p.24, 3.05
# Table 16 p.32, 4.00 Table 12 p.29, 4.01 Table 12 p.31, 4.02 Table 12 p.32.
# (3.05 renames E1 B/C as "OS data"/"OS pilot"; the codes do not change.)
# Band 7 is E5b and band 8 is E5a+b (note below each table).
_GAL_300 = (
    ("1", "A", _ALL, "E1 A PRS"),
    ("1", "B", _ALL, "E1 B I/NAV OS/CS/SoL (3.05+: OS data)"),
    ("1", "C", _ALL, "E1 C no data (3.05+: OS pilot)"),
    ("1", "X", _ALL, "E1 B+C"),
    ("1", "Z", _ALL, "E1 A+B+C"),
    ("5", "I", _ALL, "E5a I F/NAV OS"),
    ("5", "Q", _ALL, "E5a Q no data"),
    ("5", "X", _ALL, "E5a I+Q"),
    ("7", "I", _ALL, "E5b I I/NAV OS/CS/SoL"),
    ("7", "Q", _ALL, "E5b Q no data"),
    ("7", "X", _ALL, "E5b I+Q"),
    ("8", "I", _ALL, "E5 (E5a+E5b) I"),
    ("8", "Q", _ALL, "E5 (E5a+E5b) Q"),
    ("8", "X", _ALL, "E5 (E5a+E5b) I+Q"),
    ("6", "A", _ALL, "E6 A PRS"),
    ("6", "B", _ALL, "E6 B C/NAV CS"),
    ("6", "C", _ALL, "E6 C no data"),
    ("6", "X", _ALL, "E6 B+C"),
    ("6", "Z", _ALL, "E6 A+B+C"),
)

# SBAS -----------------------------------------------------------------------
# 3.00 Table 5 (p.11); identical in every later version (3.01 p.11, 3.02
# Table 5 p.19, 3.03 Table 7 p.23, 3.04 Table 7 p.24, 3.05 Table 17 p.32,
# 4.00 Table 13 p.29, 4.01 Table 13 p.31, 4.02 Table 13 p.32).
_SBAS_300 = (
    ("1", "C", _ALL, "L1 C/A"),
    ("5", "I", _ALL, "L5 I"),
    ("5", "Q", _ALL, "L5 Q"),
    ("5", "X", _ALL, "L5 I+Q"),
)

# QZSS -----------------------------------------------------------------------
# 3.02 Table 6 (p.19); 3.03 Table 8 (p.23) identical.
_QZS_302 = (
    ("1", "C", _ALL, "L1 C/A"),
    ("1", "S", _ALL, "L1C (D)"),
    ("1", "L", _ALL, "L1C (P)"),
    ("1", "X", _ALL, "L1C (D+P)"),
    ("1", "Z", _ALL, "L1-SAIF"),
    ("2", "S", _ALL, "L2C (M)"),
    ("2", "L", _ALL, "L2C (L)"),
    ("2", "X", _ALL, "L2C (M+L)"),
    ("5", "I", _ALL, "L5 I"),
    ("5", "Q", _ALL, "L5 Q"),
    ("5", "X", _ALL, "L5 I+Q"),
    ("6", "S", _ALL, "LEX(6) S"),
    ("6", "L", _ALL, "LEX(6) L"),
    ("6", "X", _ALL, "LEX(6) S+L"),
)
# 3.04 Table 8 (p.25): Block II L5S (5D/5P/5Z) and L6E (6E/6Z) added; L1Z is
# now "L1S/L1-SAIF"; band 6 rows renamed L6D/L6P/L6(D+P).
_QZS_304_L1 = (
    ("1", "C", _ALL, "L1 C/A"),
    ("1", "S", _ALL, "L1C (D)"),
    ("1", "L", _ALL, "L1C (P)"),
    ("1", "X", _ALL, "L1C (D+P)"),
    ("1", "Z", _ALL, "L1S/L1-SAIF"),
)
_QZS_304_REST = (
    ("2", "S", _ALL, "L2C (M)"),
    ("2", "L", _ALL, "L2C (L)"),
    ("2", "X", _ALL, "L2C (M+L)"),
    ("5", "I", _ALL, "L5 I"),
    ("5", "Q", _ALL, "L5 Q"),
    ("5", "X", _ALL, "L5 I+Q"),
    ("5", "D", _ALL, "L5S (I) [3.04: L5D] (Block II)"),
    ("5", "P", _ALL, "L5S (Q) [3.04: L5P] (Block II)"),
    ("5", "Z", _ALL, "L5S (I+Q) [3.04: L5(D+P)] (Block II)"),
    ("6", "S", _ALL, "L6D"),
    ("6", "L", _ALL, "L6P (Block I)"),
    ("6", "X", _ALL, "L6(D+P) (Block I)"),
    ("6", "E", _ALL, "L6E (Block II)"),
    ("6", "Z", _ALL, "L6(D+E) (Block II)"),
)
_QZS_304 = _QZS_304_L1 + _QZS_304_REST
# 3.05 Table 18 (p.33) adds L1Sb (1B).
_QZS_305 = _QZS_304_L1 + (("1", "B", _ALL, "L1Sb"),) + _QZS_304_REST
# 4.00 Table 14 (p.30) adds C/B (1E); 4.01 Table 14 (p.32) identical.
_QZS_400 = (
    ("1", "C", _ALL, "L1 C/A"),
    ("1", "E", _ALL, "L1 C/B"),
) + _QZS_304_L1[1:] + (("1", "B", _ALL, "L1Sb"),) + _QZS_304_REST
# 4.02 Table 14 (p.33): the L1Sb row prints "-" for every code, with footnote
# 1: removed "as already covered by the SBAS Observation Codes in Table 13"
# (and revision Jun 2025, p.11). So J 1B is not valid in 4.02.
_QZS_402 = (
    ("1", "C", _ALL, "L1 C/A"),
    ("1", "E", _ALL, "L1 C/B"),
) + _QZS_304_L1[1:] + _QZS_304_REST

# BeiDou ---------------------------------------------------------------------
# 3.01 Table 5 (p.11), "Compass". The E1 (1589.74 MHz) row prints "?" for the
# channel and every code, so it defines no codes and is omitted here.
_BDS_301 = (
    ("2", "I", _ALL, "E2 (B1, 1561.098) I"),
    ("2", "Q", _ALL, "E2 (B1, 1561.098) Q"),
    ("2", "X", _ALL, "E2 (B1, 1561.098) I+Q"),
    ("7", "I", _ALL, "E5b (B2, 1207.14) I"),
    ("7", "Q", _ALL, "E5b (B2, 1207.14) Q"),
    ("7", "X", _ALL, "E5b (B2, 1207.14) I+Q"),
    ("6", "I", _ALL, "E6 (B3, 1268.52) I"),
    ("6", "Q", _ALL, "E6 (B3, 1268.52) Q"),
    ("6", "X", _ALL, "E6 (B3, 1268.52) I+Q"),
)
# 3.02 Table 7 (p.20): B1 is band 1 (C1I/C1Q/C1X) -- 3.02 only.
_BDS_302 = (
    ("1", "I", _ALL, "B1 I"),
    ("1", "Q", _ALL, "B1 Q"),
    ("1", "X", _ALL, "B1 I+Q"),
    ("7", "I", _ALL, "B2 I"),
    ("7", "Q", _ALL, "B2 Q"),
    ("7", "X", _ALL, "B2 I+Q"),
    ("6", "I", _ALL, "B3 I"),
    ("6", "Q", _ALL, "B3 Q"),
    ("6", "X", _ALL, "B3 I+Q"),
)
# 3.03 Table 9 (p.24): B1 back to band 2 (C2I/C2Q/C2X).
_BDS_303 = (
    ("2", "I", _ALL, "B1 I"),
    ("2", "Q", _ALL, "B1 Q"),
    ("2", "X", _ALL, "B1 I+Q"),
) + _BDS_302[3:]
# 3.04 Table 9 (p.26): BDS-3 signals added.
_BDS_304 = (
    ("2", "I", _ALL, "B1-2 I"),
    ("2", "Q", _ALL, "B1-2 Q"),
    ("2", "X", _ALL, "B1-2 I+Q"),
    ("1", "D", _ALL, "B1 (BDS-3) Data"),
    ("1", "P", _ALL, "B1 (BDS-3) Pilot"),
    ("1", "X", _ALL, "B1 (BDS-3) Data+Pilot"),
    ("1", "A", _ALL, "B1A (BDS-3)"),
    ("1", "N", _NO_CODE, "B1 (BDS-3) Codeless"),
    ("5", "D", _ALL, "B2a (BDS-3) Data"),
    ("5", "P", _ALL, "B2a (BDS-3) Pilot"),
    ("5", "X", _ALL, "B2a (BDS-3) Data+Pilot"),
    ("7", "I", _ALL, "B2b (BDS-2) I"),
    ("7", "Q", _ALL, "B2b (BDS-2) Q"),
    ("7", "X", _ALL, "B2b (BDS-2) I+Q"),
    ("7", "D", _ALL, "B2b (BDS-3) Data"),
    ("7", "P", _ALL, "B2b (BDS-3) Pilot"),
    ("7", "Z", _ALL, "B2b (BDS-3) Data+Pilot"),
    ("8", "D", _ALL, "B2 (B2a+B2b, BDS-3) Data"),
    ("8", "P", _ALL, "B2 (B2a+B2b, BDS-3) Pilot"),
    ("8", "X", _ALL, "B2 (B2a+B2b, BDS-3) Data+Pilot"),
    ("6", "I", _ALL, "B3 I"),
    ("6", "Q", _ALL, "B3 Q"),
    ("6", "X", _ALL, "B3 I+Q"),
    ("6", "A", _ALL, "B3A"),
)
# 3.05 Table 19 (p.34): B1A becomes 1S/1L/1Z and B3A becomes 6D/6P/6Z; the
# 3.04 rows 1A, 1N (codeless) and 6A are gone. Identical in 4.00 Table 15
# (p.31), 4.01 Table 15 (p.33), 4.02 Table 15 (p.34).
_BDS_305 = (
    ("2", "I", _ALL, "B1 (B1I, BDS-2/3) I"),
    ("2", "Q", _ALL, "B1 (B1I, BDS-2/3) Q"),
    ("2", "X", _ALL, "B1 (B1I, BDS-2/3) I+Q"),
    ("1", "D", _ALL, "B1C (BDS-3) Data"),
    ("1", "P", _ALL, "B1C (BDS-3) Pilot"),
    ("1", "X", _ALL, "B1C (BDS-3) Data+Pilot"),
    ("1", "S", _ALL, "B1A (BDS-3) Data"),
    ("1", "L", _ALL, "B1A (BDS-3) Pilot"),
    ("1", "Z", _ALL, "B1A (BDS-3) Data+Pilot"),
    ("5", "D", _ALL, "B2a (BDS-3) Data"),
    ("5", "P", _ALL, "B2a (BDS-3) Pilot"),
    ("5", "X", _ALL, "B2a (BDS-3) Data+Pilot"),
    ("7", "I", _ALL, "B2 (B2I, BDS-2) I"),
    ("7", "Q", _ALL, "B2 (B2I, BDS-2) Q"),
    ("7", "X", _ALL, "B2 (B2I, BDS-2) I+Q"),
    ("7", "D", _ALL, "B2b (BDS-3) Data"),
    ("7", "P", _ALL, "B2b (BDS-3) Pilot"),
    ("7", "Z", _ALL, "B2b (BDS-3) Data+Pilot"),
    ("8", "D", _ALL, "B2 (B2a+B2b, BDS-3) Data"),
    ("8", "P", _ALL, "B2 (B2a+B2b, BDS-3) Pilot"),
    ("8", "X", _ALL, "B2 (B2a+B2b, BDS-3) Data+Pilot"),
    ("6", "I", _ALL, "B3 (BDS-2/3) I"),
    ("6", "Q", _ALL, "B3 (BDS-2/3) Q"),
    ("6", "X", _ALL, "B3 (BDS-2/3) I+Q"),
    ("6", "D", _ALL, "B3A (BDS-3) Data"),
    ("6", "P", _ALL, "B3A (BDS-3) Pilot"),
    ("6", "Z", _ALL, "B3A (BDS-3) Data+Pilot"),
)

# NavIC / IRNSS --------------------------------------------------------------
# 3.03 Table 10 (p.24); identical in 3.04 Table 10 (p.27), 3.05 Table 20
# (p.35), 4.00 Table 16 (p.32). Band 9 is S-band (2492.028 MHz).
_IRN_303 = (
    ("5", "A", _ALL, "L5 A SPS"),
    ("5", "B", _ALL, "L5 B RS (D)"),
    ("5", "C", _ALL, "L5 C RS (P)"),
    ("5", "X", _ALL, "L5 B+C"),
    ("9", "A", _ALL, "S A SPS"),
    ("9", "B", _ALL, "S B RS (D)"),
    ("9", "C", _ALL, "S C RS (P)"),
    ("9", "X", _ALL, "S B+C"),
)
# 4.01 Table 16 (p.34) adds L1 (revision Jun 2023, p.9); 4.02 Table 16 (p.35)
# identical.
_IRN_401 = (
    ("1", "D", _ALL, "L1 Data"),
    ("1", "P", _ALL, "L1 Pilot"),
    ("1", "X", _ALL, "L1 Data+Pilot"),
) + _IRN_303

SIGNAL_ROWS = {
    "3.00": {"G": _GPS_300, "R": _GLO_300, "E": _GAL_300, "S": _SBAS_300},
    "3.01": {"G": _GPS_301, "R": _GLO_300, "E": _GAL_300, "S": _SBAS_300,
             "C": _BDS_301},
    "3.02": {"G": _GPS_301, "R": _GLO_302, "E": _GAL_300, "S": _SBAS_300,
             "J": _QZS_302, "C": _BDS_302},
    "3.03": {"G": _GPS_301, "R": _GLO_302, "E": _GAL_300, "S": _SBAS_300,
             "J": _QZS_302, "C": _BDS_303, "I": _IRN_303},
    "3.04": {"G": _GPS_301, "R": _GLO_304, "E": _GAL_300, "S": _SBAS_300,
             "J": _QZS_304, "C": _BDS_304, "I": _IRN_303},
    "3.05": {"G": _GPS_301, "R": _GLO_304, "E": _GAL_300, "S": _SBAS_300,
             "J": _QZS_305, "C": _BDS_305, "I": _IRN_303},
    "4.00": {"G": _GPS_301, "R": _GLO_304, "E": _GAL_300, "S": _SBAS_300,
             "J": _QZS_400, "C": _BDS_305, "I": _IRN_303},
    "4.01": {"G": _GPS_401, "R": _GLO_304, "E": _GAL_300, "S": _SBAS_300,
             "J": _QZS_400, "C": _BDS_305, "I": _IRN_401},
    "4.02": {"G": _GPS_401, "R": _GLO_304, "E": _GAL_300, "S": _SBAS_300,
             "J": _QZS_402, "C": _BDS_305, "I": _IRN_401},
}


def _expand(rows):
    """Turn table rows into the set of 3-character codes they define."""
    return frozenset(t + band + attr for band, attr, types, _signal in rows for t in types)


OBS_CODES = dict(_V2_CODES)
for _ver, _by_sys in SIGNAL_ROWS.items():
    OBS_CODES[_ver] = {_sys: _expand(_rows) for _sys, _rows in _by_sys.items()}
del _ver, _by_sys

# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------
# SOURCE_SPANS gives the same places in machine-checkable form: the spec file,
# the inclusive page range from its "===== page N =====" markers (None for the
# RINEX 2 texts, which have none), and the inclusive line range that holds
# exactly that system's table (its caption, header rows, code rows and the
# notes printed under it). The unit tests check that the codes found in each
# line range are exactly the codes listed here, apart from a few signal names
# that look like codes (see SIGNAL_NAME_TOKENS).
def _span(file, pages, lines):
    return {"file": file, "pages": pages, "lines": lines}


SOURCE_SPANS = {
    "2.10": {s: _span("rinex210.txt", None, (886, 897)) for s in "GRST"},
    "2.11": {   # one table, rows per system (sec. 10.1.1, l.961-980)
        "G": _span("rinex211.txt", None, (965, 967)),
        "R": _span("rinex211.txt", None, (969, 970)),
        "E": _span("rinex211.txt", None, (972, 976)),
        "S": _span("rinex211.txt", None, (978, 979)),
    },
    "3.00": {
        "G": _span("rinex300.txt", (10, 10), (609, 633)),
        "R": _span("rinex300.txt", (10, 11), (634, 651)),
        "E": _span("rinex300.txt", (11, 11), (652, 670)),
        "S": _span("rinex300.txt", (11, 11), (671, 676)),
    },
    "3.01": {
        "G": _span("rinex301.txt", (10, 11), (599, 640)),
        "R": _span("rinex301.txt", (11, 11), (641, 644)),
        "E": _span("rinex301.txt", (11, 11), (645, 663)),
        "S": _span("rinex301.txt", (11, 11), (664, 667)),
        "C": _span("rinex301.txt", (11, 11), (668, 679)),
    },
    "3.02": {
        "G": _span("rinex302.txt", (17, 17), (785, 814)),
        "R": _span("rinex302.txt", (18, 18), (841, 854)),
        "E": _span("rinex302.txt", (18, 18), (857, 880)),
        "S": _span("rinex302.txt", (19, 19), (894, 902)),
        "J": _span("rinex302.txt", (19, 19), (905, 923)),
        "C": _span("rinex302.txt", (20, 20), (948, 962)),
    },
    "3.03": {
        "G": _span("rinex303_update1.txt", (21, 21), (985, 1014)),
        "R": _span("rinex303_update1.txt", (22, 22), (1039, 1052)),
        "E": _span("rinex303_update1.txt", (22, 22), (1055, 1078)),
        "S": _span("rinex303_update1.txt", (23, 23), (1091, 1099)),
        "J": _span("rinex303_update1.txt", (23, 23), (1102, 1120)),
        "C": _span("rinex303_update1.txt", (24, 24), (1145, 1161)),
        "I": _span("rinex303_update1.txt", (24, 24), (1165, 1178)),
    },
    "3.04": {
        "G": _span("rinex304.txt", (22, 22), (1036, 1065)),
        "R": _span("rinex304.txt", (23, 23), (1090, 1109)),
        "E": _span("rinex304.txt", (24, 24), (1147, 1170)),
        "S": _span("rinex304.txt", (24, 24), (1176, 1184)),
        "J": _span("rinex304.txt", (25, 25), (1202, 1230)),
        "C": _span("rinex304.txt", (26, 26), (1256, 1287)),
        "I": _span("rinex304.txt", (27, 27), (1308, 1321)),
    },
    "3.05": {
        "G": _span("rinex305.txt", (30, 30), (1583, 1612)),
        "R": _span("rinex305.txt", (31, 31), (1634, 1651)),
        "E": _span("rinex305.txt", (32, 32), (1692, 1714)),
        "S": _span("rinex305.txt", (32, 32), (1717, 1724)),
        "J": _span("rinex305.txt", (33, 33), (1750, 1778)),
        "C": _span("rinex305.txt", (34, 34), (1809, 1841)),
        "I": _span("rinex305.txt", (35, 35), (1865, 1876)),
    },
    "4.00": {
        "G": _span("rinex_4.00.txt", (27, 27), (1374, 1403)),
        "R": _span("rinex_4.00.txt", (28, 28), (1423, 1441)),
        "E": _span("rinex_4.00.txt", (29, 29), (1476, 1498)),
        "S": _span("rinex_4.00.txt", (29, 29), (1503, 1510)),
        "J": _span("rinex_4.00.txt", (30, 30), (1533, 1562)),
        "C": _span("rinex_4.00.txt", (31, 31), (1592, 1625)),
        "I": _span("rinex_4.00.txt", (32, 32), (1643, 1654)),
    },
    "4.01": {
        "G": _span("rinex_4.01.txt", (29, 29), (1501, 1555)),
        "R": _span("rinex_4.01.txt", (30, 30), (1556, 1618)),
        "E": _span("rinex_4.01.txt", (31, 31), (1619, 1645)),
        "S": _span("rinex_4.01.txt", (31, 31), (1646, 1675)),
        "J": _span("rinex_4.01.txt", (32, 32), (1676, 1734)),
        "C": _span("rinex_4.01.txt", (33, 33), (1735, 1785)),
        "I": _span("rinex_4.01.txt", (34, 34), (1786, 1800)),
    },
    "4.02": {
        "G": _span("rinex_4.02.txt", (30, 30), (1556, 1610)),
        "R": _span("rinex_4.02.txt", (31, 31), (1611, 1673)),
        "E": _span("rinex_4.02.txt", (32, 32), (1674, 1700)),
        "S": _span("rinex_4.02.txt", (32, 32), (1701, 1730)),
        "J": _span("rinex_4.02.txt", (33, 33), (1731, 1787)),
        "C": _span("rinex_4.02.txt", (34, 34), (1788, 1837)),
        "I": _span("rinex_4.02.txt", (35, 35), (1838, 1853)),
    },
}

# The original 3.03 text (14 Jul 2015) has the same tables a few lines later.
# Used only to cross-check that Update 1 changed no observation code.
ALT_SOURCE_SPANS = {
    "3.03": {
        "G": _span("rinex303.txt", (21, 21), (988, 1017)),
        "R": _span("rinex303.txt", (22, 22), (1042, 1055)),
        "E": _span("rinex303.txt", (22, 22), (1058, 1081)),
        "S": _span("rinex303.txt", (23, 23), (1094, 1102)),
        "J": _span("rinex303.txt", (23, 23), (1105, 1123)),
        "C": _span("rinex303.txt", (24, 24), (1149, 1164)),
        "I": _span("rinex303.txt", (24, 24), (1169, 1181)),
    },
}

# Tokens inside the observation-code tables that look like codes but are
# signal names in the "Channel or Code" column, not codes of that system.
SIGNAL_NAME_TOKENS = {
    "J": frozenset(("L2C",          # "L2C (M)", "L2C (L)": QZSS has no L2 C/A
                    "L5S",          # "Block II L5S" (3.04+)
                    "L6D", "L6P")),  # QZSS L6 channel names (3.04+); codes are 6S, 6L
}

# Printed table number per version and system (RINEX 3/4).
_TABLES = {
    "3.00": dict.fromkeys("GRES", "Table 5"),
    "3.01": dict.fromkeys("GRESC", "Table 5"),
    "3.02": {"G": "Table 2", "R": "Table 3", "E": "Table 4", "S": "Table 5",
             "J": "Table 6", "C": "Table 7"},
    "3.03": {"G": "Table 4", "R": "Table 5", "E": "Table 6", "S": "Table 7",
             "J": "Table 8", "C": "Table 9", "I": "Table 10"},
    "3.04": {"G": "Table 4", "R": "Table 5", "E": "Table 6", "S": "Table 7",
             "J": "Table 8", "C": "Table 9", "I": "Table 10"},
    "3.05": {"G": "Table 14", "R": "Table 15", "E": "Table 16", "S": "Table 17",
             "J": "Table 18", "C": "Table 19", "I": "Table 20"},
    "4.00": {"G": "Table 10", "R": "Table 11", "E": "Table 12", "S": "Table 13",
             "J": "Table 14", "C": "Table 15", "I": "Table 16"},
    "4.01": {"G": "Table 10", "R": "Table 11", "E": "Table 12", "S": "Table 13",
             "J": "Table 14", "C": "Table 15", "I": "Table 16"},
    "4.02": {"G": "Table 10", "R": "Table 11", "E": "Table 12", "S": "Table 13",
             "J": "Table 14", "C": "Table 15", "I": "Table 16"},
}


def _cite(ver, sys_):
    span = SOURCE_SPANS[ver][sys_]
    if span["pages"] is None:
        a, b = span["lines"]
        return f"{span['file']} l.{a}-{b}"
    a, b = span["pages"]
    pages = f"p.{a}" if a == b else f"p.{a}-{b}"
    return f"{span['file']} {pages} {_TABLES[ver][sys_]}"


CITATIONS = {ver: {s: _cite(ver, s) for s in SOURCE_SPANS[ver]} for ver in SOURCE_SPANS}
# Human-readable detail for RINEX 2, where the location is a list, not a table.
CITATIONS["2.10"] = {
    s: "rinex210.txt l.886-897 Table A1 (# / TYPES OF OBSERV list)" for s in "GRST"
}
CITATIONS["2.10"]["S"] += "; l.750-753 sec. 9.1 (GEO payloads single frequency)"
CITATIONS["2.11"] = {
    s: f"rinex211.txt l.{SOURCE_SPANS['2.11'][s]['lines'][0]}-"
       f"{SOURCE_SPANS['2.11'][s]['lines'][1]} sec. 10.1.1 table (l.961-980); "
       "l.1158-1165 Table A1 frequency codes"
    for s in "GRSE"
}
del _cite, _span

# Per-system splits that are inference, not spec text.
INFERRED = {
    "2.10": {
        "G": "2.10 gives one global list (l.886-897), not per system. G gets the list "
             "minus the Transit codes T1/T2.",
        "R": "2.10 sec. 8 (l.627-704) adds GLONASS without new codes, so R gets the same "
             "list as G. Inference.",
        "S": "Inferred from sec. 9.1 (l.750-753): GEO payloads are single frequency and "
             "their second-frequency fields stay blank, and GEO transmits C/A only (no P). "
             "So S gets C1 L1 D1 S1.",
        "T": "T1/T2 are stated to be Transit (l.893-894); no other code is tied to Transit.",
    },
}

# ---------------------------------------------------------------------------
# Pseudo-observables (RINEX 3/4)
# ---------------------------------------------------------------------------
# "bands" lists the band digits allowed for that type; "attribute" is always
# blank. Codes are type + band + " " (three characters, A3 field).
PSEUDO_OBS = {
    "3.00": {
        "I": {"bands": "12345678", "attribute": " ",
              "cite": "rinex300.txt p.15 sec. 5.12; p.28 Table A1"},
        "X": {"bands": "0", "attribute": " ",
              "cite": "rinex300.txt p.15 sec. 5.13; p.28 Table A1 ('0 for type X')"},
    },
    "3.01": {
        "I": {"bands": "12345678", "attribute": " ",
              "cite": "rinex301.txt p.15 sec. 5.12; p.31 Table A1"},
        "X": {"bands": "0", "attribute": " ",
              "cite": "rinex301.txt p.15 sec. 5.13; p.31 Table A1 ('0 for type X')"},
    },
    "3.02": {
        "I": {"bands": "12345678", "attribute": " ",
              "cite": "rinex302.txt p.25 sec. 5.12"},
        "X": {"bands": "01", "attribute": " ",
              "cite": "rinex302.txt p.25 sec. 5.13 (band 1); p.53 Table A2 (band 0)",
              "note": "Self-contradiction: sec. 5.13 says band 1, Table A2 says '0 for "
                      "type X'. Both are listed; which one a writer uses is a policy choice."},
    },
    "3.03": {
        "I": {"bands": "12345678", "attribute": " ",
              "cite": "rinex303_update1.txt p.29 sec. 5.12 Table 15"},
        "X": {"bands": "01", "attribute": " ",
              "cite": "rinex303_update1.txt p.29 sec. 5.13 (band 1); p.56 Table A2 (band 0)",
              "note": "Same contradiction as 3.02."},
    },
    "3.04": {
        "I": {"bands": "123456789", "attribute": " ",
              "cite": "rinex304.txt p.32 sec. 5.12 Table 15 (1..9, revision 22-Oct-2018 p.13)"},
        "X": {"bands": "01", "attribute": " ",
              "cite": "rinex304.txt p.32 sec. 5.13 (band 1); p.62 Table A2 (band 0)",
              "note": "Same contradiction as 3.02."},
    },
    # 3.05 removed the ionosphere pseudo-observable (revision 26-Aug-2020, p.9)
    # and Band value 0 (revision 14-Sep-2020, p.9: "this value is not allowed").
    "3.05": {
        "X": {"bands": "123456789", "attribute": " ",
              "cite": "rinex305.txt p.37 sec. 5.3.4; p.9 revision history"},
    },
    "4.00": {
        "X": {"bands": "123456789", "attribute": " ",
              "cite": "rinex_4.00.txt p.34 sec. 5.3.4"},
    },
    "4.01": {
        "X": {"bands": "123456789", "attribute": " ",
              "cite": "rinex_4.01.txt p.36 sec. 5.3.4"},
    },
    "4.02": {
        "X": {"bands": "123456789", "attribute": " ",
              "cite": "rinex_4.02.txt p.37 sec. 5.3.4"},
    },
}

# ---------------------------------------------------------------------------
# Blank attribute ("unknown tracking mode")
# ---------------------------------------------------------------------------
# (allowed, citation). When allowed, an observation may be written as type +
# band + blank, for example "L2 ", but blank and non-blank attributes must not
# be mixed for the same type, band and system ("L2S and L2 is not allowed,
# L2S and C2 is OK", 3.00 p.11). The X pseudo-observable always has a blank
# attribute and is not covered by this rule.
BLANK_ATTRIBUTE = {
    "3.00": (True, "rinex300.txt p.11 sec. 5.1 'Unknown tracking mode'; p.28 Table A1"),
    "3.01": (True, "rinex301.txt p.12 sec. 5.1 'Unknown tracking mode'; p.31 Table A1"),
    "3.02": (False, "rinex302.txt p.7 revision 29-Nov-2012 removed it from sec. 5.1. "
                    "CONTRADICTION: Table A2 p.54 still allows a blank attribute"),
    "3.03": (False, "rinex303_update1.txt p.20 sec. 5.1; p.57 Table A2 note"),
    "3.04": (False, "rinex304.txt p.21 sec. 5.1; p.63 Table A2 note"),
    "3.05": (False, "rinex305.txt p.30 sec. 5.2.17; p.55 Table A2 note"),
    "4.00": (False, "rinex_4.00.txt p.27 sec. 5.2.17; p.59 Table A2 note"),
    "4.01": (False, "rinex_4.01.txt p.28 sec. 5.2.17"),
    "4.02": (False, "rinex_4.02.txt p.29 sec. 5.2.17"),
}

# ---------------------------------------------------------------------------
# BeiDou B1I in RINEX 3.02 files
# ---------------------------------------------------------------------------
BDS_B1_READ_RULE = {
    "codes": {"C1I": "C2I", "L1I": "L2I", "D1I": "D2I", "S1I": "S2I",
              "C1Q": "C2Q", "L1Q": "L2Q", "D1Q": "D2Q", "S1Q": "S2Q",
              "C1X": "C2X", "L1X": "L2X", "D1X": "D2X", "S1X": "S2X"},
    "rule": "When reading a RINEX 3.02 file, accept both 1I/Q/X and 2I/Q/X for BDS B1 "
            "and treat them as 2I/Q/X.",
    "cite": ("rinex303_update1.txt p.24 note below Table 9; rinex304.txt p.26; "
             "rinex305.txt p.34; rinex_4.00.txt p.31 and rinex_4.01.txt p.33 (worded "
             "'When reading a RINEX file'); removed from rinex_4.02.txt Table 15 as "
             "obsolete (revision Jun 2025, p.11)"),
    "note": "Only for 3.02 input. In 3.04+ C1X/L1X... also exist as BDS-3 B1C codes, "
            "so this mapping must not be applied to 3.04+ files.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_version(version):
    """Return a RINEX version as ``"X.YY"`` ("2.1" -> "2.10", 3 -> "3.00").

    Accepts a str, int or float. Raises ValueError for anything that is not a
    number. Does not check that the version is one of ``VERSIONS``.
    """
    if isinstance(version, bool):
        raise ValueError(f"not a RINEX version: {version!r}")
    if isinstance(version, (int, float)):
        number = float(version)
    else:
        text = str(version).strip()
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"not a RINEX version: {version!r}") from None
    if not (0.0 < number < 100.0):
        raise ValueError(f"not a RINEX version: {version!r}")
    return f"{number:.2f}"


def _known_version(version):
    ver = normalize_version(version)
    if ver not in OBS_CODES:
        raise ValueError(f"no observation-code table for RINEX {ver}")
    return ver


def valid_codes(version, system):
    """Return the frozenset of observation codes for ``system`` in ``version``.

    A system the version does not define (for example ``"I"`` in 3.02) gives
    an empty frozenset. An unknown version raises ValueError. Pseudo-observable
    codes are not included; see :func:`pseudo_obs_codes`.
    """
    ver = _known_version(version)
    return OBS_CODES[ver].get(system, frozenset())


def is_valid(version, system, code):
    """True if ``code`` is a listed observation code for ``system`` in ``version``.

    The comparison is exact: RINEX 3/4 codes are three characters (``"C1C"``),
    RINEX 2 codes are two (``"C1"``). Pseudo-observables and blank-attribute
    codes are not accepted here; see :func:`pseudo_obs_codes` and
    ``BLANK_ATTRIBUTE``.
    """
    return code in valid_codes(version, system)


def pseudo_obs_codes(version):
    """Return the pseudo-observable codes of ``version`` as 3-character strings.

    For example ``"X1 "`` and ``"I5 "``. RINEX 2 has none (empty frozenset).
    """
    ver = _known_version(version)
    out = set()
    for type_, spec in PSEUDO_OBS.get(ver, {}).items():
        for band in spec["bands"]:
            out.add(type_ + band + spec["attribute"])
    return frozenset(out)


def blank_attribute_allowed(version):
    """True if ``version`` allows a blank attribute (unknown tracking mode)."""
    ver = _known_version(version)
    if ver.startswith("2."):
        return False
    return BLANK_ATTRIBUTE[ver][0]
