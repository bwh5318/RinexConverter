"""Field-by-name check of navigation records (PLAN §1 clause 5a), independent of rinexcore.

The token comparator (tokens.nav_tokens, compare.compare_nav) lines record bodies up position
by position. That cannot see a field the spec redefines between versions (GLONASS tk is
seconds of the UTC day in RINEX 2 and of the UTC week in RINEX 3/4), and it rests on its own
assumption that position k means the same field in every version. Here every field of every
EPH record (and of the RINEX 4 STO/EOP/ION records) is named from the spec text, the
version-to-version transformations the specs define are applied, and each named field held
by both the input and the output record must keep its value, to the precision of the
target's D19.12/E19.12 field.

    compare_nav_fields(in_bytes, out_bytes)   -> [problem text]        (empty: all fields kept)
    nav_field_check(in_bytes, outs)           -> ([problem dicts], stats)
    parse_nav(data)                           -> NavFile(version, ftype, records)
    layout_for(version, sys, msg, kind="EPH") -> Layout(fields, cite) or None

Payloads are plain RINEX bytes (no gzip/.Z/Hatanaka layers), read as latin-1. outs may be one
payload or a list (a RINEX 2 target splits a mixed file into N/G/H files). Fields held by one
side only, and records with no partner, are left to the token comparator and the loss report,
except records whose key fields (satellite, time of clock, message type) moved: those are
reported 'unmatched'.

Spec citations: rinex210.txt and rinex211.txt have no page markers and are cited by line;
the other texts by their `===== page N =====` markers (the PDF page, one more than the
printed footer). Ambiguities in the spec text are marked AMBIGUOUS below: where one exists
the check compares the value as it is and does not guess a transformation.
"""

import datetime
import re
from collections import defaultdict, namedtuple
from decimal import Decimal, InvalidOperation

# ----------------------------------------------------------------------------------------
# Record layouts. One tuple of field names per record line; line 0 is the SV / EPOCH / SV CLK
# line (3 values after the epoch), every further line BROADCAST ORBIT - n (4 values, 19
# columns each: 3X (RINEX 2) or 4X (RINEX 3/4) then 4D19.12). '-' is a spare/blank field,
# never compared. Names are shared across versions: the same name is the same quantity.
# ----------------------------------------------------------------------------------------

Layout = namedtuple("Layout", "fields cite")


def _L(*lines):
    return tuple(tuple(l.split()) for l in lines)


_CLK = "af0 af1 af2"                       # SV clock bias, drift, drift rate
_O2 = "Cuc e Cus sqrtA"
_O3 = "Toe Cic OMEGA0 Cis"
_O4 = "i0 Crc omega OMEGADOT"

# GPS LNAV. rinex211.txt l.1355-1416 Table A4 (2.10: rinex210.txt l.1084-1145, identical);
# rinex300.txt p.33-34 Table A5; rinex301.txt p.37 A5; rinex302.txt p.64 A6; rinex303.txt
# p.72-73 A6; rinex304.txt p.77-78 A6; rinex305.txt p.69 Table A6. BROADCAST ORBIT - 7 field 2
# "Fit interval (hours)" was added in 2.10 (rinex210.txt l.217 "Curve fit interval in GPS nav
# mess file", §6.6 l.570): formally spare in 2.00/2.01, but IGS 'brdc' files labelled 2(.00)
# hold the fit interval there, so it is compared (a writer that left it spare wrote 0/blank).
GPS_V23 = _L(_CLK, "IODE Crs DeltaN M0", _O2, _O3, _O4, "IDOT L2Codes Week L2Pflag",
             "SVaccuracy SVhealth TGD IODC", "Ttm FitInterval - -")
# RINEX 4 LNAV: BROADCAST ORBIT - 7 is 4X,2D19.12 (no spares): rinex_4.00.txt p.72-73 Table A9,
# rinex_4.01.txt p.76-77 A9, rinex_4.02.txt p.78-79 Table A9.
GPS_V4_LNAV = GPS_V23[:7] + (("Ttm", "FitInterval"),)
# CNAV / CNAV-2 (RINEX 4 only): rinex_4.02.txt p.80-81 Table A10, p.82-83 Table A11 (4.00
# p.74-77 A10/A11, 4.01 p.78-81). The last line's 'Integer flags' field is new in 4.02
# (4.00/4.01: 4X,2D19.12 t_tm, wn_op).
_CNAV_HEAD = (_CLK, "Adot Crs DeltaN0 M0", "Cuc e Cus sqrtA0", "top Cic OMEGA0 Cis", _O4,
              "IDOT DeltaN0dot URAI_NED0 URAI_NED1", "URAI_ED SVhealth TGD URAI_NED2",
              "ISC_L1CA ISC_L2C ISC_L5I5 ISC_L5Q5")
CNAV_400 = _L(*_CNAV_HEAD, "Ttm WNop")
CNAV_402 = _L(*_CNAV_HEAD, "Ttm WNop Flags")
CNV2_400 = _L(*_CNAV_HEAD, "ISC_L1Cd ISC_L1Cp", "Ttm WNop")
CNV2_402 = _L(*_CNAV_HEAD, "ISC_L1Cd ISC_L1Cp", "Ttm WNop Flags")

# Galileo. rinex300.txt p.34 Table A7; rinex301.txt p.38 A7; rinex302.txt p.66-67 A8;
# rinex303.txt p.74-75 A8; rinex304.txt p.79-80 A8; rinex305.txt p.71-72 Table A8. RINEX 4
# (rinex_4.02.txt p.84-85 Table A13; 4.00 p.78-79, 4.01 p.82-83): BROADCAST ORBIT - 5 is
# 4X,3E19.12 and - 7 4X,1E19.12 (the spares are gone).
GAL_V3 = _L(_CLK, "IODnav Crs DeltaN M0", _O2, _O3, _O4, "IDOT DataSources Week -",
            "SISA SVhealth BGDE5aE1 BGDE5bE1", "Ttm - - -")
GAL_V4 = GAL_V3[:5] + (("IDOT", "DataSources", "Week"), GAL_V3[6], ("Ttm",))

# GLONASS FDMA. RINEX 2: rinex211.txt l.1704-1736 Table A11 (2.10 l.1425-1456, identical).
# RINEX 3.00-3.04 (rinex300.txt p.36 A9; rinex301.txt p.40 A9; rinex302.txt p.69 A10;
# rinex303.txt p.78 A10; rinex304.txt p.83 A10): the same 4 lines. 3.05 adds BROADCAST
# ORBIT - 4 (rinex305.txt p.74-75 Table A10), as does RINEX 4 (rinex_4.00.txt p.81-82 A15,
# 4.01 p.85-86, rinex_4.02.txt p.87-88 Table A15). mTauN is the stored -TauN.
GLO_4L = _L("mTauN GammaN tk", "X Xdot Xacc Health", "Y Ydot Yacc FreqNum", "Z Zdot Zacc AgeOp")
GLO_5L = GLO_4L + (("StatusFlags", "DelayL1L2", "URAI", "HealthFlags"),)
# GLONASS CDMA (4.02 only): rinex_4.02.txt p.89-90 Table A16 (L1OC), p.90-91 Table A17 (L3OC)
_GLO_CDMA = ("mTauN GammaN Beta", "X Xdot Xacc SignalHealth", "Y Ydot Yacc DataValidity")
_GLO_CDMA_TAIL = ("SatType SourceFlags AODE AODC", "AttitudeFlag Tin Tau1 Tau2",
                  "Yaw SignFlag AngRate AngAccel", "MaxAngRate dXpc dYpc dZpc",
                  "URAI_orb URAI_clk - Ttm")
GLO_L1OC = _L(*_GLO_CDMA, "Z Zdot Zacc TGD_L2OCp", *_GLO_CDMA_TAIL)
GLO_L3OC = _L(*_GLO_CDMA, "Z Zdot Zacc ISC_L3OCp", *_GLO_CDMA_TAIL)

# SBAS / GEO. RINEX 2.10: rinex210.txt l.1643-1673 Table A16: line 0 field 3 is "message frame
# time (sec of day GPS)" and BROADCAST ORBIT - 3 field 4 is spare. 2.11 (rinex211.txt
# l.1946-1978 Table A16) redefines field 3 as the transmission time in GPS seconds of the
# week (rinex211.txt l.915 "It is a redefinition of the Version 2.10 Message frame time")
# and makes field 4 IODN. RINEX 3/4 as 2.11: rinex300.txt p.37 A11; rinex301.txt p.41 A11;
# rinex302.txt p.75 A14; rinex303.txt p.84 A16; rinex304.txt p.89 A16; rinex305.txt p.81
# Table A16; rinex_4.00.txt p.98 A26; rinex_4.01.txt p.102 A26; rinex_4.02.txt p.108 Table A28.
SBAS_210 = _L("aGf0 aGf1 Ttm", "X Xdot Xacc Health", "Y Ydot Yacc URA", "Z Zdot Zacc -")
SBAS_211 = SBAS_210[:3] + (("Z", "Zdot", "Zacc", "IODN"),)

# QZSS LNAV. rinex302.txt p.71-72 Table A12: BROADCAST ORBIT - 5 field 4 is spare (3.03+: L2P
# flag, set to 1), and BROADCAST ORBIT - 7 field 2 reads "Fit interval (hours) ... Zero - one
# hour, 1 - more than 2 hours" -- AMBIGUOUS (hours or flag); 3.03 makes it a flag (rinex303.txt
# l.652-654, p.81 Table A12). Both are named FitInterval and compared as they are (no
# transformation is defined). The 3.02 table also prints a RINEX 2 style epoch (2-digit year,
# F5.1): a spec error, the 3.02 example and every later version use the RINEX 3 epoch.
# rinex303.txt p.80-81 A12; rinex304.txt p.85-86 A12; rinex305.txt p.77-78 Table A12;
# RINEX 4 LNAV: rinex_4.00.txt p.83-84 A17, 4.01 p.87-88, rinex_4.02.txt p.93-94 Table A19
# (4.02 renames field 2 of BROADCAST ORBIT - 5 "Reserved & Ephemerides Status flags",
# "previously known as Code on L2": the same bits, kept as L2Codes).
QZS_302 = _L(_CLK, "IODE Crs DeltaN M0", _O2, _O3, _O4, "IDOT L2Codes Week -",
             "SVaccuracy SVhealth TGD IODC", "Ttm FitInterval - -")
QZS_303 = GPS_V23
QZS_V4_LNAV = GPS_V4_LNAV

# BeiDou D1/D2. rinex302.txt p.73 Table A13 (IODE/IODC: renamed AODE/AODC from 3.03, the same
# fields; 3.02 also prints "-Cis", read as a typo for Cis); rinex303.txt p.82 A14;
# rinex304.txt p.87 A14; rinex305.txt p.79-80 Table A14; RINEX 4 D1/D2 (BROADCAST ORBIT - 7
# 4X,2E19.12): rinex_4.00.txt p.89-90 A21, 4.01 p.93-94, rinex_4.02.txt p.99-100 Table A23.
BDS_V3 = _L(_CLK, "AODE Crs DeltaN M0", _O2, _O3, _O4, "IDOT - Week -",
            "SVaccuracy SatH1 TGD1 TGD2", "Ttm AODC - -")
BDS_V4_D12 = BDS_V3[:7] + (("Ttm", "AODC"),)
# BeiDou CNAV-1/2/3 (RINEX 4): rinex_4.02.txt p.101-102 Table A24, p.103-104 A25,
# p.105-106 A26 (4.00 p.91-96 A22-A24; 4.01 p.95-100)
_BDS_C_HEAD = (_CLK, "Adot Crs DeltaN0 M0", "Cuc e Cus sqrtA0", "Toe Cic OMEGA0 Cis", _O4,
               "IDOT DeltaN0dot SatType top", "SISAI_oe SISAI_ocb SISAI_oc1 SISAI_oc2")
BDS_CNV1 = _L(*_BDS_C_HEAD, "ISC_B1Cd - TGD_B1Cp TGD_B2ap", "SISMAI Health IntegrityFlags IODC",
              "Ttm - - IODE")
BDS_CNV2 = _L(*_BDS_C_HEAD, "- ISC_B2ad TGD_B1Cp TGD_B2ap", "SISMAI Health IntegrityFlags IODC",
              "Ttm - - IODE")
BDS_CNV3 = _L(*_BDS_C_HEAD, "SISMAI Health IntegrityFlags TGD_B2bI", "Ttm")

# NavIC/IRNSS LNAV. rinex303.txt p.86-87 Table A18; rinex304.txt p.91-92 A18; rinex305.txt
# p.83-84 Table A18; RINEX 4 (BROADCAST ORBIT - 7 4X,D19.12): rinex_4.00.txt p.100-101 A28,
# 4.01 p.104-105, rinex_4.02.txt p.110-111 Table A30.
IRN_V3 = _L(_CLK, "IODEC Crs DeltaN M0", _O2, _O3, _O4, "IDOT - Week -", "URA SVhealth TGD -",
            "Ttm - - -")
IRN_V4_LNAV = IRN_V3[:7] + (("Ttm",),)
# NavIC L1NV (4.02 only): rinex_4.02.txt p.112-113 Table A31. BROADCAST ORBIT - 5 is printed
# "2X,E19.12, A19, E19.12" for four fields -- read as the usual 4X,4(19) grid with the spare
# third (spec typo). BROADCAST ORBIT - 3 starts with IODEC (no Toe in this message).
IRN_L1NV = _L(_CLK, "Adot Crs DeltaN0 M0", "Cuc e Cus sqrtA", "IODEC Cic OMEGA0 Cis", _O4,
              "IDOT DeltaN0dot - RSF", "URAI L1SPSHealth TGD_L1P_L5 TGD_S_L5",
              "ISC_S_L1P ISC_L1D_L1P ISC_L1P_S ISC_L1D_S", "Ttm")

# RINEX 4 STO / EOP / ION records (lower priority; compared between RINEX 4 versions only:
# below RINEX 4 they are header records, checked by headers.compare_nav_meta). The STO line 0
# holds three A18 text fields after the epoch (code, SBAS id, UTC id), read separately.
# STO: rinex_4.02.txt p.115-116 Table A33 (4.00 p.102 A30, 4.01 p.106 A30)
STO = _L("", "Ttm A0 A1 A2")
# EOP: rinex_4.02.txt p.116 Table A34 (4.00 p.103 A31, 4.01 p.107 A31)
EOP = _L("Xp dXp d2Xp", "- Yp dYp d2Yp", "Ttm dUT1 ddUT1 d2dUT1")
# ION Klobuchar: rinex_4.02.txt p.117 Table A35 (line 2: Beta3 only, the area is the subtype
# WIDE/JAPN); 4.00 p.104 A32 / 4.01 p.108 A32: line 2 "Beta3, Region code: 0 or blank (wide
# area parameters), 1 (QZSS only - Japan area coefficients)", 4X,2D19.12
ION_KLOB_400 = _L("alpha0 alpha1 alpha2", "alpha3 beta0 beta1 beta2", "beta3 RegionCode")
ION_KLOB_402 = _L("alpha0 alpha1 alpha2", "alpha3 beta0 beta1 beta2", "beta3")
# NeQuick-G: rinex_4.02.txt p.118 Table A36 (4.00 p.105 A33, 4.01 p.109 A33)
ION_NEQG = _L("ai0 ai1 ai2", "DisturbanceFlags")
# BDGIM: rinex_4.02.txt p.119 Table A37 (4.00 p.106 A34, 4.01 p.110 A34)
ION_BDGIM = _L("bd1 bd2 bd3", "bd4 bd5 bd6 bd7", "bd8 bd9")
# NavIC L1NV Klobuchar / NeQuick-N, GLONASS CDMA (4.02 only): p.120 A38, p.121 A39, p.122 A40
ION_NAVIC_KLOB = _L("IODK", "alpha0 alpha1 alpha2 alpha3", "beta0 beta1 beta2 beta3",
                    "LonMin LonMax LatMin LatMax")
ION_NAVIC_NEQN = _L("IODN", "a0_1 a1_1 a2_1 IDF_1", "LonMin_1 LonMax_1 MODIPmin_1 MODIPmax_1",
                    "a0_2 a1_2 a2_2 IDF_2", "LonMin_2 LonMax_2 MODIPmin_2 MODIPmax_2",
                    "a0_3 a1_3 a2_3 IDF_3", "LonMin_3 LonMax_3 MODIPmin_3 MODIPmax_3")
ION_GLO = _L("cA cF107 cAp")

V2 = ("2.00", "2.01", "2.10", "2.11")
V3 = ("3.00", "3.01", "3.02", "3.03", "3.04", "3.05")
V4 = ("4.00", "4.01", "4.02")

# (kind, system, message type or '' (RINEX 2/3), versions, layout, citation)
_REGISTRY = [
    ("EPH", "G", "", V2, GPS_V23, "rinex211.txt l.1355 Table A4 (2.10: rinex210.txt l.1084)"),
    ("EPH", "R", "", V2, GLO_4L, "rinex211.txt l.1704 Table A11 (2.10: rinex210.txt l.1425)"),
    ("EPH", "S", "", ("2.10",), SBAS_210, "rinex210.txt l.1643 Table A16"),
    ("EPH", "S", "", ("2.11",), SBAS_211, "rinex211.txt l.1946 Table A16"),
    ("EPH", "G", "", V3, GPS_V23, "rinex305.txt p.69 Table A6 (3.00 p.33 A5 ... 3.04 p.77 A6)"),
    ("EPH", "E", "", V3, GAL_V3, "rinex305.txt p.71-72 Table A8 (3.00 p.34 A7 ... 3.04 p.79 A8)"),
    ("EPH", "R", "", V3[:5], GLO_4L, "rinex304.txt p.83 Table A10 (3.00 p.36 A9 ... 3.03 p.78 A10)"),
    ("EPH", "R", "", ("3.05",), GLO_5L, "rinex305.txt p.74-75 Table A10"),
    ("EPH", "S", "", V3, SBAS_211, "rinex305.txt p.81 Table A16 (3.00 p.37 A11 ... 3.04 p.89 A16)"),
    ("EPH", "J", "", ("3.02",), QZS_302, "rinex302.txt p.71-72 Table A12"),
    ("EPH", "J", "", V3[3:], QZS_303, "rinex305.txt p.77-78 Table A12 (3.03 p.80, 3.04 p.85)"),
    ("EPH", "C", "", V3[2:], BDS_V3, "rinex305.txt p.79-80 Table A14 (3.02 p.73 A13, 3.03 p.82, 3.04 p.87)"),
    ("EPH", "I", "", V3[3:], IRN_V3, "rinex305.txt p.83-84 Table A18 (3.03 p.86, 3.04 p.91)"),
    ("EPH", "G", "LNAV", V4, GPS_V4_LNAV, "rinex_4.02.txt p.78-79 Table A9"),
    ("EPH", "G", "CNAV", V4[:2], CNAV_400, "rinex_4.01.txt p.78-79 Table A10 (4.00 p.74)"),
    ("EPH", "G", "CNAV", ("4.02",), CNAV_402, "rinex_4.02.txt p.80-81 Table A10"),
    ("EPH", "G", "CNV2", V4[:2], CNV2_400, "rinex_4.01.txt p.80-81 Table A11 (4.00 p.76)"),
    ("EPH", "G", "CNV2", ("4.02",), CNV2_402, "rinex_4.02.txt p.82-83 Table A11"),
    ("EPH", "E", "INAV", V4, GAL_V4, "rinex_4.02.txt p.84-85 Table A13"),
    ("EPH", "E", "FNAV", V4, GAL_V4, "rinex_4.02.txt p.84-85 Table A13"),
    ("EPH", "R", "FDMA", V4, GLO_5L, "rinex_4.02.txt p.87-88 Table A15"),
    ("EPH", "R", "L1OC", ("4.02",), GLO_L1OC, "rinex_4.02.txt p.89-90 Table A16"),
    ("EPH", "R", "L3OC", ("4.02",), GLO_L3OC, "rinex_4.02.txt p.90-91 Table A17"),
    ("EPH", "J", "LNAV", V4, QZS_V4_LNAV, "rinex_4.02.txt p.93-94 Table A19"),
    ("EPH", "J", "CNAV", V4[:2], CNAV_400, "rinex_4.01.txt p.89-90 Table A18 (4.00 p.85)"),
    ("EPH", "J", "CNAV", ("4.02",), CNAV_402, "rinex_4.02.txt p.95-96 Table A20"),
    ("EPH", "J", "CNV2", V4[:2], CNV2_400, "rinex_4.01.txt p.91-92 Table A19 (4.00 p.87)"),
    ("EPH", "J", "CNV2", ("4.02",), CNV2_402, "rinex_4.02.txt p.97-98 Table A21"),
    ("EPH", "C", "D1", V4, BDS_V4_D12, "rinex_4.02.txt p.99-100 Table A23"),
    ("EPH", "C", "D2", V4, BDS_V4_D12, "rinex_4.02.txt p.99-100 Table A23"),
    ("EPH", "C", "CNV1", V4, BDS_CNV1, "rinex_4.02.txt p.101-102 Table A24"),
    ("EPH", "C", "CNV2", V4, BDS_CNV2, "rinex_4.02.txt p.103-104 Table A25"),
    ("EPH", "C", "CNV3", V4, BDS_CNV3, "rinex_4.02.txt p.105-106 Table A26"),
    ("EPH", "S", "SBAS", V4, SBAS_211, "rinex_4.02.txt p.108 Table A28"),
    ("EPH", "I", "LNAV", V4, IRN_V4_LNAV, "rinex_4.02.txt p.110-111 Table A30"),
    ("EPH", "I", "L1NV", ("4.02",), IRN_L1NV, "rinex_4.02.txt p.112-113 Table A31"),
]
_EPH = {}
for _k, _s, _m, _vs, _lay, _c in _REGISTRY:
    for _v in _vs:
        _EPH[(_k, _s, _m, _v)] = Layout(_lay, _c)

# The RINEX 2/3 record of each system is the RINEX 4 message of this family: a RINEX 4 record
# of another type (CNAV, CNV1, L1OC, ...) has no RINEX 2/3 form. rinex_4.02.txt §5.4.1 and
# the A tables: GPS/QZSS/NavIC 'LNAV' (Tables A9, A19, A30), Galileo 'INAV'/'FNAV' (A13),
# GLONASS 'FDMA' (A15), BeiDou 'D1'/'D2' (A23), SBAS 'SBAS' (A28).
LEGACY = {"G": ("LNAV",), "J": ("LNAV",), "I": ("LNAV",), "E": ("INAV", "FNAV"), "R": ("FDMA",),
          "C": ("D1", "D2"), "S": ("SBAS",)}


def norm_version(v):
    """'2' / 2.1 / '3.05' -> one of V2+V3+V4 (2.12 reads as 2.11; a later 3.x/4.x as the last
    known one of its major version)."""
    v = float(v)
    for known in reversed(V2 + V3 + V4):
        if v + 1e-9 >= float(known) and int(v) == int(float(known)):
            return known
    return "%.2f" % v


def layout_for(version, sys, msg="", kind="EPH", sub=""):
    """The Layout of a record, or None when the spec defines none (RINEX 2 files carrying E/C/J
    records, an unknown message type, ...)."""
    version = norm_version(version)
    if kind == "EPH":
        return _EPH.get(("EPH", sys, msg if version >= "4" else "", version))
    if version < "4":
        return None
    if kind == "STO":
        return Layout(STO, "rinex_4.02.txt p.115-116 Table A33 (4.00 p.102 A30)")
    if kind == "EOP":
        return Layout(EOP, "rinex_4.02.txt p.116 Table A34 (4.00 p.103 A31)")
    if kind == "ION":
        if sys == "E":
            return Layout(ION_NEQG, "rinex_4.02.txt p.118 Table A36")
        if sys == "C" and msg == "CNVX":
            return Layout(ION_BDGIM, "rinex_4.02.txt p.119 Table A37")
        if sys == "I" and msg == "L1NV":
            if sub == "NEQN":
                return Layout(ION_NAVIC_NEQN, "rinex_4.02.txt p.121 Table A39")
            return Layout(ION_NAVIC_KLOB, "rinex_4.02.txt p.120 Table A38")
        if sys == "R":
            return Layout(ION_GLO, "rinex_4.02.txt p.122 Table A40")
        if version >= "4.02":
            return Layout(ION_KLOB_402, "rinex_4.02.txt p.117 Table A35")
        return Layout(ION_KLOB_400, "rinex_4.01.txt p.108 Table A32 (4.00 p.104)")
    return None


# ----------------------------------------------------------------------------------------
# Numbers and the tolerant record splitter
# ----------------------------------------------------------------------------------------

class Raw(str):
    """A non-blank field that is not a number (compared as text)."""


_FORTRAN_EXP = re.compile(r"([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d{2,3})")


def num(text):
    """Field text -> Decimal (D/E/d/e exponents, rinex211.txt l.1418 note *); None for blank;
    Raw for anything else. A Fortran exponent without its letter ('0.12-123') is read too."""
    t = text.strip()
    if not t:
        return None
    u = t.replace("D", "E").replace("d", "e")
    try:
        return Decimal(u)
    except InvalidOperation:
        m = _FORTRAN_EXP.fullmatch(u)
        if m:
            return Decimal(m.group(1) + "E" + m.group(2))
        return Raw(t)


class Record:
    """One navigation record. vals[i][k]: field k of line i (Decimal / None / Raw)."""
    __slots__ = ("kind", "sys", "prn", "toc", "msg", "sub", "text", "vals", "line", "v2", "_named")

    def __init__(self, kind, sys, prn, toc, msg, sub, line, v2):
        self.kind, self.sys, self.prn, self.toc, self.msg, self.sub = kind, sys, prn, toc, msg, sub
        self.text = ()          # STO: (code, SBAS id, UTC id)
        self.vals = []
        self.line = line        # 0-based index of the first body line in the payload
        self.v2 = v2
        self._named = None

    @property
    def sat(self):
        return f"{self.sys}{self.prn:02d}" if self.prn is not None else self.sys

    def __repr__(self):
        return f"<{self.kind} {self.sat} {fmt_toc(self.toc)} {self.msg}>"


NavFile = namedtuple("NavFile", "version ftype records")


def _lines(data):
    if isinstance(data, bytes):
        data = data.decode("latin-1")
    return data.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _epoch(y, mo, d, h, mi, s, two_digit):
    try:
        y = int(y)
        if two_digit:
            # rinex211.txt l.1722-1724 (Table A11): 80-99 -> 1980-1999, 00-79 -> 2000-2079
            y += 1900 if y >= 80 else 2000
        return (y, int(mo), int(d), int(h), int(mi), Decimal(s.strip() or "0"))
    except (ValueError, InvalidOperation):
        return None


def fmt_toc(t):
    if t is None:
        return "?"
    s = t[5]
    s = "%02d" % s if s == s.to_integral_value() else ("0" if s < 10 else "") + str(s)
    return "%04d-%02d-%02d %02d:%02d:%s" % (t[0], t[1], t[2], t[3], t[4], s)


def _values(line, start, n):
    l = line.ljust(start + 19 * n)
    vals = [num(l[start + 19 * k:start + 19 * (k + 1)]) for k in range(n)]
    if any(isinstance(v, Raw) for v in vals):
        # tolerant fallback: a line whose numbers are not on the 19-column grid is read token
        # by token (blank fields are then lost; only the order survives)
        toks = re.findall(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[DEde][+-]?\d+)?", line[start:])
        vals = [num(t) for t in toks][:n] + [None] * max(0, n - len(toks))
    return vals


def parse_nav(data):
    """Split a RINEX 2/3/4 navigation payload into records. Record starts: RINEX 2 a line with
    a satellite number in columns 1-2 (rinex211.txt Table A4 'I2'); RINEX 3 a line with a
    system letter in column 1 (rinex305.txt Table A6 'A1,I2.2'); RINEX 4 a '>' line
    (rinex_4.02.txt Table A9 'TYPE / SV / MSSG'), its body the RINEX 3 record that follows
    (STO/EOP/ION bodies start with 4 blanks: Tables A33-A40)."""
    L = _lines(data)
    if not L or not L[0][:9].strip():
        return NavFile(None, None, [])
    try:
        version = norm_version(L[0][:9])
    except ValueError:
        return NavFile(None, None, [])
    ftype = L[0][20:21]
    end = next((i for i, l in enumerate(L) if l[60:80].strip() == "END OF HEADER"), None)
    if end is None:
        return NavFile(version, ftype, [])
    recs = []
    v2 = version < "3"
    # RINEX 2 file type -> system: N GPS, G GLONASS, H GEO (rinex211.txt Tables A3/A10/A15);
    # one real 2.11 file writes 'S' for GEO (CLAUDE.md gotchas)
    dsys = {"N": "G", "G": "R", "H": "S", "S": "S"}.get(ftype, "G")
    cur = None
    i = end + 1
    while i < len(L):
        l = L[i]
        if not l.strip():
            i += 1
            continue
        if version >= "4":
            if l.startswith(">"):
                t = l[1:].split()
                kind = t[0] if t else "?"
                sat = t[1] if len(t) > 1 else "?"
                msg = t[2] if len(t) > 2 else ""
                sub = t[3] if len(t) > 3 else ""
                sys = sat[0]
                prn = int(sat[1:]) if sat[1:].isdigit() else None
                body = L[i + 1] if i + 1 < len(L) else ""
                ep = _epoch(body[4:8], body[9:11], body[12:14], body[15:17], body[18:20], body[21:23], False)
                cur = Record(kind, sys, prn, ep, msg, sub, i + 1, False)
                recs.append(cur)
                if kind == "STO":
                    b = body.ljust(80)
                    cur.text = (b[24:42].strip(), b[43:61].strip(), b[62:80].strip())
                    cur.vals.append([])
                else:
                    cur.vals.append(_values(body, 23, 3))
                i += 2
                continue
            if cur is not None:
                cur.vals.append(_values(l, 4, 4))
            i += 1
            continue
        if v2:
            if l[0:2].strip():
                if l[0].isalpha():
                    sys, prn = l[0], l[1:3]
                else:
                    sys, prn = dsys, l[0:2]
                try:
                    prn = int(prn)
                except ValueError:
                    prn = None
                ep = _epoch(l[3:5], l[6:8], l[9:11], l[12:14], l[15:17], l[17:22], True)
                cur = Record("EPH", sys, prn, ep, "", "", i, True)
                cur.vals.append(_values(l, 22, 3))
                recs.append(cur)
            elif cur is not None:
                cur.vals.append(_values(l, 3, 4))
        else:
            if l[0] != " ":
                prn = int(l[1:3]) if l[1:3].strip().isdigit() else None
                ep = _epoch(l[4:8], l[9:11], l[12:14], l[15:17], l[18:20], l[21:23], False)
                cur = Record("EPH", l[0], prn, ep, "", "", i, False)
                cur.vals.append(_values(l, 23, 3))
                recs.append(cur)
            elif cur is not None:
                cur.vals.append(_values(l, 4, 4))
        i += 1
    return NavFile(version, ftype, recs)


def field_columns(version, rec, name, layout=None):
    """(payload line index, first column, end column) of a named field of a parsed record, for
    tests that edit one field in place; None when the layout has no such field."""
    lay = layout or layout_for(version, rec.sys, rec.msg, rec.kind, rec.sub)
    v2 = norm_version(version) < "3"
    for i, names in enumerate(lay.fields):
        for k, n in enumerate(names):
            if n == name:
                start = (22 if v2 else 23) if i == 0 else (3 if v2 else 4)
                return rec.line + i, start + 19 * k, start + 19 * (k + 1)
    return None


def named(rec, version):
    """{field name: value} of the non-blank, non-spare fields (cached on the record)."""
    if rec._named is None:
        lay = layout_for(version, rec.sys, rec.msg, rec.kind, rec.sub)
        d = {}
        if lay is not None:
            for names, vals in zip(lay.fields, rec.vals):
                for n, x in zip(names, vals):
                    if n != "-" and x is not None:
                        d[n] = x
        rec._named = d
    return rec._named


# ----------------------------------------------------------------------------------------
# Transformations the specs define between versions, and the precision rule
# ----------------------------------------------------------------------------------------

DAY = Decimal(86400)
WEEK = Decimal(604800)
# 'Transmission time of message unknown': "Set value to 0.9999E9 if not known" (rinex300.txt
# p.34 note **, ... rinex304.txt p.78), ".999999999999E+09" from 3.05 (rinex305.txt p.70 note
# **) and in RINEX 4 (rinex_4.02.txt p.79 note 3*). Either spelling stands for the other.
TTM_UNKNOWN = (Decimal("0.9999E9"), Decimal(".999999999999E+09"))


def tol(x):
    """Half a unit of the 12th significant digit of x: what a D19.12 / E19.12 field
    (0.dddddddddddd, 12 mantissa digits: rinex211.txt Table A4 'D19.12', rinex_4.02.txt
    Table A9 'E19.12') can lose in rounding. Zero for zero."""
    if not x:
        return Decimal(0)
    return Decimal(5).scaleb(x.adjusted() - 12)


def close(want, got):
    return abs(got - want) <= tol(want)


def _mod(x, m):
    r = x % m
    return r + m if r < 0 else r


def _sow(toc):
    """Seconds of the week of an epoch (Y, M, D, h, m, s), the week starting at Sunday 00:00
    (GPS/UTC week alike), or None."""
    try:
        d = datetime.date(toc[0], toc[1], toc[2])
    except (TypeError, ValueError):
        return None
    dow = (d.weekday() + 1) % 7
    return Decimal(dow * 86400 + toc[3] * 3600 + toc[4] * 60) + toc[5]


def glonass_tk_kind(version):
    """'day' or 'week'. GLONASS message frame time tk: RINEX 2 "(0 .le. tk .lt. 86400 sec of
    day UTC)" (rinex211.txt l.1718-1719, rinex210.txt l.1439-1440); RINEX 3 and 4 "Message
    frame time (tk+nd*86400) in seconds of the UTC week" (rinex300.txt p.36 Table A9;
    rinex305.txt p.74 Table A10; rinex_4.02.txt p.87 Table A15)."""
    return "day" if norm_version(version) < "3" else "week"


def sbas_ttm_kind(version):
    """'day' or 'week'. SBAS line 0 field 3: 2.10 "message frame time (sec of day GPS)"
    (rinex210.txt l.1656); from 2.11 the transmission time "in GPS seconds of the week ... a
    redefinition of the Version 2.10 Message frame time" (rinex211.txt l.909-915, Table A16
    l.1957-1959; rinex305.txt p.41 §5.4.4; rinex_4.02.txt p.108 Table A28)."""
    return "day" if norm_version(version) == "2.10" else "week"


def day_to_week(day_value, toc_sow):
    """The seconds-of-week values a seconds-of-day value may become: day_value + nd*86400.
    RINEX does not define nd (AMBIGUOUS: rinex305.txt p.74 Table A10 writes tk+nd*86400 and
    nothing more). The checker requires the congruence (exact, a spec fact) and reports
    separately ('tk-day', an inference) a value that is not the candidate nearest to the
    time of clock, circularly in the week (a frame is transmitted within minutes of its
    ephemeris epoch; at a week start the previous week's Saturday is as near as -x)."""
    if toc_sow is None:
        return None
    # counted from the start of Toc's week: the GEO tables say so ('has to refer to the same
    # GPS week as the Epoch of Ephemerides ... adjusted by - or + 604800', rinex211.txt
    # l.910-915), and for GLONASS it is the user's decision of 2026-11-02 ('Toc week'), so the
    # frame of a Sunday 00:15 epoch sent on Saturday 23:59:30 is -30, not 604770
    return min((day_value + k * DAY for k in range(-1, 8)), key=lambda c: abs(c - toc_sow))


def cdist(a, b):
    """Distance of two seconds-of-week values around the week (|a - b| modulo 604800)."""
    return abs(_mod(a - b + WEEK / 2, WEEK) - WEEK / 2)


def glonass_gammaN_sign(version_in, ftype_in, version_out, ftype_out):
    """-1 when GammaN changes sign: RINEX 2.00 GLONASS nav files stored "-TauN, -GammaN,
    +TauC", from 2.01 (the version number introduced to tell the two apart) "-TauN, +GammaN,
    -TauC" (rinex210.txt l.170-178 §0.3; rinex210.txt l.720-725 §8.2). RINEX 3/4 keep the 2.01
    convention (rinex305.txt p.39 §5.4.2 "-TauN, +GammaN, -TauC")."""
    def old(v, ft):
        return norm_version(v) < "2.01" and ft == "G"
    return -1 if old(version_in, ftype_in) != old(version_out, ftype_out) else 1


def congruent(x, y, m):
    """y = x + k*m for an integer k, to the precision of y's D19.12 field."""
    d = _mod(y - x, m)
    return d <= tol(y) or m - d <= tol(y)


# ----------------------------------------------------------------------------------------
# Matching and comparison
# ----------------------------------------------------------------------------------------

class _Ctx:
    def __init__(self, fin, fout):
        self.vin, self.vout = fin.version, fout.version
        self.fin, self.fout = fin, fout
        self.gamma = glonass_gammaN_sign(fin.version, fin.ftype, fout.version, fout.ftype)


def _sec_floor(t):
    return None if t is None else t[:5] + (int(t[5]),)


def _family_ok(a, b):
    """Message types of a pair compatible? Both RINEX 4: equal. One RINEX 4: its type is the
    legacy message of the system (LEGACY). Neither: no type."""
    if a.msg and b.msg:
        return a.msg == b.msg
    m = a.msg or b.msg
    return not m or m in LEGACY.get(a.sys, ())


def _ds(rec, version):
    if rec.sys != "E" or rec.kind != "EPH":
        return None
    x = named(rec, version).get("DataSources")
    return int(x) if isinstance(x, Decimal) and x == x.to_integral_value() else None


def _strict(a, b, ctx):
    if not _family_ok(a, b):
        return False
    if a.msg and b.msg and ctx.vin >= "4.02" and ctx.vout >= "4.02" and a.sub != b.sub:
        return False
    if a.kind == "STO" and a.text[:1] != b.text[:1]:
        return False
    da, db = _ds(a, ctx.vin), _ds(b, ctx.vout)
    return da is None or db is None or da == db


def _compare(a, b, ctx, out=None):
    """Compare the named fields of input record a and output record b. Returns (n_equal,
    n_diff); with out (a list), appends a problem dict per differing field."""
    na, nb = named(a, ctx.vin), named(b, ctx.vout)
    eq = diff = 0
    base = {"sys": a.sys, "msg_in": a.msg, "msg_out": b.msg, "kind": "field", "sat": a.sat,
            "toc": fmt_toc(a.toc), "line_in": a.line + 1, "line_out": b.line + 1}
    for name in na.keys() & nb.keys():
        x, y = na[name], nb[name]
        note = None
        if isinstance(x, Raw) or isinstance(y, Raw):
            ok = str(x) == str(y)
            want = x
        elif name == "Ttm" and x in TTM_UNKNOWN and y in TTM_UNKNOWN:
            ok, want = True, x
        else:
            want = x
            src = dst = None
            if a.sys == "R" and name == "tk" and a.kind == "EPH" and (a.msg or "FDMA") == "FDMA":
                src, dst = glonass_tk_kind(ctx.vin), glonass_tk_kind(ctx.vout)
                toc = b.toc
            elif a.sys == "S" and name == "Ttm" and a.kind == "EPH":
                src, dst = sbas_ttm_kind(ctx.vin), sbas_ttm_kind(ctx.vout)
                toc = b.toc
            if name == "GammaN" and a.sys == "R" and ctx.gamma == -1:
                want = -x
                note = "GammaN sign: RINEX 2.00 GLONASS stores -GammaN (rinex210.txt l.170-178)"
            if src == "day" and dst == "week":
                sow = _sow(toc)
                near = day_to_week(x, sow)
                # a seconds-of-week value must be x + nd*86400 (exact), and nd a day of the
                # frame: within a day of the time of clock whichever day nd counts (that of
                # tk or of the ephemeris epoch tb) -- beyond that no reading of nd gives it
                # (Toc's week: the distance is not taken around the week, see day_to_week)
                far = sow is not None and abs(y - sow) > DAY + 3600
                ok = congruent(x, y, DAY) and not far
                if not ok:
                    want, note = near, f"{name}: seconds of day -> seconds of week (+nd*86400) " + (
                        "(rinex211.txt l.1718 vs rinex305.txt p.74; Toc's week: user 2026-11-02)"
                        if name == "tk" else "(rinex210.txt l.1656 vs rinex211.txt l.909-915)")
                elif near is not None and abs(y - sow) > abs(near - sow) + tol(y):
                    if out is not None:
                        out.append(dict(base, kind="tk-day", field=name, inp=str(x), out=str(y),
                                        expected=str(near), note="congruent mod 86400 but not the "
                                        "day nearest the time of clock (nd is not defined by the "
                                        "spec: an inference, see day_to_week)"))
            elif src == "week" and dst == "day":
                want = _mod(x, DAY)
                ok = congruent(x, y, DAY) and -tol(y) <= y < DAY
                note = f"{name}: seconds of week -> seconds of day (mod 86400)"
            else:
                ok = close(want, y)
        if ok:
            eq += 1
        else:
            diff += 1
            if out is not None:
                out.append(dict(base, field=name, inp=str(x), out=str(y), expected=str(want), note=note))
    if a.kind == "STO" and a.text[1:] != b.text[1:]:
        diff += 1
        if out is not None:
            out.append(dict(base, field="STO ids", inp=" / ".join(a.text), out=" / ".join(b.text),
                            expected=" / ".join(a.text), note=None))
    if a.v2 and b.v2 and a.toc and b.toc and a.toc[5] != b.toc[5]:
        diff += 1          # both F5.1 seconds (rinex211.txt Table A4): the tenths must stay
        if out is not None:
            out.append(dict(base, field="Toc seconds", inp=str(a.toc[5]), out=str(b.toc[5]),
                            expected=str(a.toc[5]), note=None))
    return eq, diff


def _extra_checks(a, b, ctx, out):
    """Relations between a matched pair that are not one field's value."""
    base = {"sys": a.sys, "msg_in": a.msg, "msg_out": b.msg, "sat": a.sat, "toc": fmt_toc(a.toc),
            "line_in": a.line + 1, "line_out": b.line + 1}
    # Spares ('-'): a field spare in the output's layout is blank there, and a field real in the
    # output but spare in the input at that place (and named nowhere in the input layout) is not
    # filled from the input's spare: a spare holds no defined content ('Blank or Spare fields
    # ... shall be left blank and skipped when reading/writing', rinex305.txt section 6.4 p.42;
    # rinex_4.02.txt section 6.4 p.48). E.g. the 2.10 GEO spare vs the 2.11+ IODN, the 3.02
    # QZSS spare vs the 3.03+ L2 P flag (review round 33).
    if a.kind == "EPH":
        la = layout_for(ctx.vin, a.sys, a.msg, a.kind, a.sub)
        lb = layout_for(ctx.vout, b.sys, b.msg, b.kind, b.sub)
        if la is not None and lb is not None:
            names_in = {n for line in la.fields for n in line}
            for i, (names, vals) in enumerate(zip(lb.fields, b.vals)):
                for k, (n, y) in enumerate(zip(names, vals)):
                    if y is None:
                        continue
                    src = la.fields[i][k] if i < len(la.fields) and k < len(la.fields[i]) else None
                    if n == "-":
                        if y == 0 and ctx.vout < "4":
                            continue          # RINEX 2/3: a zero spare says nothing either
                        out.append(dict(base, kind="spare", field=f"line {i} field {k + 1} (spare)", inp="",
                                        out=str(y), expected="blank",
                                        note="a spare is left blank (rinex305.txt section 6.4 p.42; "
                                             "rinex_4.02.txt section 6.4 p.48)"))
                    elif src == "-" and n not in names_in:
                        out.append(dict(base, kind="spare", field=n, inp="spare", out=str(y),
                                        expected="blank (unknown)",
                                        note=f"{n} is a spare in {ctx.vin} ({la.cite}): no value to give it"))
    # Galileo: the RINEX 4 type follows the data-source bits (rinex_4.02.txt p.84-85 Table
    # A13: bit 0 I/NAV E1-B, bit 1 F/NAV E5a-I, bit 2 I/NAV E5b-I); checked where the input
    # had no type to copy (RINEX 3 -> 4). Both I/NAV and F/NAV bits set: no type follows.
    if a.sys == "E" and a.kind == "EPH" and not a.msg and b.msg:
        ds = _ds(b, ctx.vout)
        if ds is not None:
            inav, fnav = bool(ds & 0b101), bool(ds & 0b010)
            want = "INAV" if inav and not fnav else "FNAV" if fnav and not inav else None
            if want and b.msg != want:
                out.append(dict(base, kind="msgtype", field="message type", inp=f"data sources {ds}",
                                out=b.msg, expected=want, note="rinex_4.02.txt p.84-85 Table A13"))
    # QZSS ION area: 4.00/4.01 'Region code: 0 or blank (wide area), 1 (Japan area)' on line 2
    # (rinex_4.01.txt p.108 Table A32) <-> the 4.02 subtype WIDE/JAPN (rinex_4.02.txt p.117
    # Table A35 note 3*)
    if a.kind == "ION" and a.sys == "J" and (ctx.vin >= "4.02") != (ctx.vout >= "4.02") \
            and ctx.vin >= "4" and ctx.vout >= "4":
        note = "rinex_4.01.txt p.108 Table A32 (4.00 p.104) vs rinex_4.02.txt p.117 Table A35"
        if ctx.vin < "4.02":            # region code -> subtype (a missing subtype is not ours)
            rc = named(a, ctx.vin).get("RegionCode")
            want = "JAPN" if rc == 1 else "WIDE" if rc in (None, 0) else None
            if b.sub and want and b.sub != want:
                out.append(dict(base, kind="ion-area", field="QZSS ION area", inp=f"region code {rc}",
                                out=b.sub, expected=want, note=note))
        elif a.sub in ("WIDE", "JAPN"):  # subtype -> region code: 1 Japan, 0 or blank wide
            rc = named(b, ctx.vout).get("RegionCode")
            ok = rc == 1 if a.sub == "JAPN" else rc in (None, 0)
            if not ok:
                out.append(dict(base, kind="ion-area", field="QZSS ION area", inp=a.sub,
                                out=f"region code {rc if rc is not None else 'blank'}",
                                expected="region code 1" if a.sub == "JAPN" else "region code 0 or blank",
                                note=note))


def _assign(ins, outs, ctx, score_cache, allowed=None):
    """Greedy one-to-one assignment of a candidate group, fewest differing fields first, then
    most equal. Returns [(a, b, ambiguous)]."""
    pairs = []
    for a in ins:
        for b in outs:
            if allowed is not None and not allowed(a, b):
                continue
            k = (id(a), id(b))
            if k not in score_cache:
                score_cache[k] = _compare(a, b, ctx)
            eq, diff = score_cache[k]
            pairs.append((diff, -eq, a, b))
    pairs.sort(key=lambda p: (p[0], p[1]))
    used_a, used_b, res = set(), set(), []
    for i, (diff, neq, a, b) in enumerate(pairs):
        if id(a) in used_a or id(b) in used_b:
            continue
        ties = sum(1 for d2, n2, a2, b2 in pairs if (d2, n2) == (diff, neq) and (a2 is a or b2 is b)
                   and id(a2) not in used_a and id(b2) not in used_b)
        used_a.add(id(a))
        used_b.add(id(b))
        res.append((a, b, diff > 0 and ties > 1))
    return res


_STRONG = ("M0", "e", "sqrtA", "sqrtA0", "X", "Y", "Z", "af0", "mTauN", "aGf0", "alpha0", "ai0",
           "Xp", "A0", "bd1", "cA", "IODK", "IODN")


def _fingerprints(rec, version):
    n = named(rec, version)
    out = set()
    for f in _STRONG:
        x = n.get(f)
        if isinstance(x, Decimal) and x:
            out.add((f, round(float(x), 10 - int(x.adjusted()))))
    return out


def nav_field_check(inp, outs):
    """(problems, stats). problems: dicts with kind ('field', 'tk-day', 'unmatched', 'key',
    'msgtype', 'ion-area'), sys, msg_in, msg_out, field, sat, toc, inp, out, expected, note,
    line_in, line_out. stats: counts of records, pairs and fields compared."""
    if isinstance(outs, (bytes, str)):
        outs = [outs]
    fin = parse_nav(inp)
    problems = []
    stats = defaultdict(int)
    both4 = fin.version is not None and fin.version >= "4"
    for o in outs:
        fout = parse_nav(o)
        if fin.version is None or fout.version is None:
            problems.append(dict(kind="parse", sys="", msg_in="", msg_out="", field="", sat="", toc="",
                                 inp=str(fin.version), out=str(fout.version), expected="",
                                 note="no RINEX version line", line_in=1, line_out=1))
            continue
        ctx = _Ctx(fin, fout)
        k4 = both4 and fout.version >= "4"
        use_in = [r for r in fin.records if r.kind == "EPH" or k4]
        use_out = [r for r in fout.records if r.kind == "EPH" or k4]
        for r in use_in:
            if layout_for(fin.version, r.sys, r.msg, r.kind, r.sub) is None:
                stats["no_layout_in"] += 1
        for r in use_out:
            if layout_for(fout.version, r.sys, r.msg, r.kind, r.sub) is None:
                stats["no_layout_out"] += 1
        stats["records_in"] += len(use_in)
        stats["records_out"] += len(use_out)

        def base_key(r):
            return (r.kind, r.sys, r.prn, _sec_floor(r.toc))
        gin = defaultdict(list)
        for r in use_in:
            gin[base_key(r)].append(r)
        gout = defaultdict(list)
        for r in use_out:
            gout[base_key(r)].append(r)
        cache = {}
        matched = []
        left_out = []
        for key, bs in gout.items():
            as_ = gin.get(key, [])
            # pass 1: compatible message type (and 4.02 subtype, STO code) and Galileo data
            # source; pass 2: what is left at the same satellite and time of clock (a key
            # field moved: reported below)
            m1 = _assign(as_, bs, ctx, cache, lambda a, b: _strict(a, b, ctx))
            da = {id(a) for a, b, amb in m1}
            db = {id(b) for a, b, amb in m1}
            m2 = _assign([a for a in as_ if id(a) not in da], [b for b in bs if id(b) not in db], ctx, cache)
            matched += [(a, b, amb, False) for a, b, amb in m1] + [(a, b, amb, True) for a, b, amb in m2]
            db |= {id(b) for a, b, amb in m2}
            left_out.extend(b for b in bs if id(b) not in db)
        assigned_in = {id(a) for a, b, amb, rel in matched}
        left_in = [a for a in use_in if id(a) not in assigned_in]
        for a, b, amb, relaxed in matched:
            stats["pairs"] += 1
            before = len(problems)
            _compare(a, b, ctx, problems)
            if relaxed:
                why = []
                if not _family_ok(a, b):
                    why.append(f"message type {a.msg or '-'} -> {b.msg or '-'}")
                if a.msg and b.msg and ctx.vin >= "4.02" and ctx.vout >= "4.02" and a.sub != b.sub:
                    why.append(f"subtype {a.sub or '-'} -> {b.sub or '-'}")
                if a.kind == "STO" and a.text[:1] != b.text[:1]:
                    why.append(f"STO code {a.text[0]} -> {b.text[0]}")
                # (a changed Galileo data source is reported as the DataSources field)
                if why:
                    problems.append(dict(kind="key", sys=a.sys, msg_in=a.msg, msg_out=b.msg,
                                         field="; ".join(why), sat=a.sat, toc=fmt_toc(a.toc),
                                         inp=a.msg, out=b.msg, expected=a.msg,
                                         note="matched on satellite and time of clock only",
                                         line_in=a.line + 1, line_out=b.line + 1))
            _extra_checks(a, b, ctx, problems)
            if amb and len(problems) > before:
                for p in problems[before:]:
                    p["note"] = ((p.get("note") or "") + " [ambiguous match: several candidates "
                                 "with the same score]").strip()
            stats["fields"] += len(named(a, ctx.vin).keys() & named(b, ctx.vout).keys())
        # pass 3: output records with no partner at their key: did a key field move?
        idx = defaultdict(list)
        for a in left_in:
            for fp in _fingerprints(a, ctx.vin):
                idx[(a.kind, a.sys, fp)].append(a)
        stats["unmatched_in"] += len(left_in)
        stats["unmatched_out"] += len(left_out)
        taken = set()
        for b in left_out:
            cands = {}
            for fp in _fingerprints(b, ctx.vout):
                for a in idx.get((b.kind, b.sys, fp), ()):
                    if id(a) not in taken:
                        cands[id(a)] = a
            best = None
            for a in cands.values():
                eq, diff = _compare(a, b, ctx)
                if eq >= 5 and eq >= 2 * diff and (best is None or (eq, -diff) > best[0]):
                    best = ((eq, -diff), a)
            if best is None:
                continue
            a = best[1]
            taken.add(id(a))
            moved = [w for w, x, y in (("satellite", a.sat, b.sat), ("time of clock", _sec_floor(a.toc),
                                       _sec_floor(b.toc)), ("message type", a.msg, b.msg))
                     if x != y and not (w == "message type" and _family_ok(a, b))]
            problems.append(dict(kind="unmatched", sys=a.sys, msg_in=a.msg, msg_out=b.msg,
                                 field=", ".join(moved) or "?", sat=a.sat, toc=fmt_toc(a.toc),
                                 inp=f"{a.sat} {fmt_toc(a.toc)} {a.msg}".strip(),
                                 out=f"{b.sat} {fmt_toc(b.toc)} {b.msg}".strip(),
                                 expected=f"{a.sat} {fmt_toc(a.toc)} {a.msg}".strip(),
                                 note=f"{best[0][0]} fields equal, {-best[0][1]} differ",
                                 line_in=a.line + 1, line_out=b.line + 1))
    return problems, dict(stats)


def fmt_problem(p):
    msg = p["msg_in"] if p["msg_in"] == p["msg_out"] else f"{p['msg_in'] or '-'}->{p['msg_out'] or '-'}"
    s = (f"{p['kind']}: {p['sat']} {p['toc']} {msg} {p['field']}: input {p['inp']} -> output "
         f"{p['out']} (expected {p['expected']}; input line {p['line_in']}, output line {p['line_out']})")
    return s + (f" [{p['note']}]" if p.get("note") else "")


def compare_nav_fields(in_bytes, out_bytes):
    """Problems (text) of a navigation conversion, field by name; [] when every field held by
    both sides kept its value. out_bytes: one output payload or a list of them."""
    problems, _ = nav_field_check(in_bytes, out_bytes)
    return [fmt_problem(p) for p in problems]
