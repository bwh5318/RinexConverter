"""Observation-file header labels (columns 61-80), per RINEX version.

Data only, transcribed by hand from the header tables in ``specs/text/``:
Table A1 in 2.10, 2.11, 3.00 and 3.01; Table A2 from 3.02 on. Pages are the
``===== page N =====`` markers of each text; the RINEX 2 texts have none, so
they are cited by line number (``l.N``). For 3.03 the cited text is
``rinex303_update1.txt`` (3.03 Update 1). The original ``rinex303.txt`` has
the same header table word for word (checked by diff), but its page breaks
fall a few lines earlier, so a few rows start one page earlier there (e.g.
``SYS / # / OBS TYPES`` p.55 instead of p.56, ``INTERVAL`` and
``TIME OF FIRST OBS`` p.57 instead of p.58).

``OBS_HEADER`` maps each canonical label to a dict:

``versions``     version -> status: ``"M"`` mandatory, ``"O"`` optional,
                 ``"C"`` conditional (the condition is in ``conditions``),
                 ``"O-deprecated"`` optional and deprecated. A version that is
                 missing does not define the label.
``cite``         version -> where the label's row starts in that version's
                 header table.
``format``       version -> the Fortran-style field format as printed (spaces
                 removed, wrapped cells joined). It is given for every version,
                 so a writer never has to fall back.
``continuation`` version -> format of continuation lines, where the spec
                 defines them.
``conditions``   version -> the condition, for status ``"C"``.
``notes``        version -> anything else the writer or reader needs.
``spelling``     version -> the label exactly as that version prints it, where
                 it differs from the canonical key.
``repeat``       what the spec says about repeating the record.

Status rules used for the transcription: a row marked ``*`` in the table is
``"O"``; an unmarked row is ``"M"``; a row whose table text adds a condition
("required except ...", "Optional for moving platforms", "Record required if
...") is ``"C"``, whether it is starred or not. A row the table calls
"strongly deprecated" is ``"O-deprecated"``.

What changes between versions (header)
--------------------------------------
- **2.10 -> 2.11**: ``WAVELENGTH FACT L1/2`` goes from mandatory (the default
  line, 2.10 l.852-862) to optional, GPS only (2.11 sec. 10.1.2, l.992-1001;
  Table A1 l.1107-1118). ``# / TYPES OF OBSERV`` codes become type + frequency
  characters (A1,A1), and continuation lines of it and of ``PRN / # OF OBS``
  must repeat the header label (2.11 l.1141-1142, l.1215-1216). ``GAL`` joins
  the time systems (l.1187).
- **2.x -> 3.00**: ``# / TYPES OF OBSERV`` is replaced by per-system
  ``SYS / # / OBS TYPES`` with 13 codes per line (3.00 p.11 sec. 5.2, p.27).
  ``WAVELENGTH FACT L1/2`` is dropped because half-wavelength observations get
  their own codes (p.12 sec. 5.4). New: ``MARKER TYPE``, the ``ANTENNA: ...``
  vehicle records, ``CENTER OF MASS: XYZ``, ``SIGNAL STRENGTH UNIT``,
  ``SYS / DCBS APPLIED``, ``SYS / PCVS APPLIED``, ``SYS / SCALE FACTOR``
  (p.26-29). The ``PGM / RUN BY / DATE`` date becomes
  ``yyyymmdd hhmmss zone`` (p.13 sec. 5.8). ``PRN / # OF OBS`` writes the
  satellite number as I2.2 (p.29).
- **3.01**: new mandatory ``SYS / PHASE SHIFTS`` (printed with a final S;
  p.24-25 sec. 9.1, p.32) and optional ``GLONASS SLOT / FRQ #`` (p.25-27
  sec. 9.5, p.32). ``LEAP SECONDS`` grows to four I6 fields (p.33).
- **3.02**: the label becomes ``SYS / PHASE SHIFT`` (p.7, revision 9-May-2012).
  ``GLONASS SLOT / FRQ #`` becomes mandatory and its format gains a trailing
  1X per satellite (p.7, revision 29-Nov-2012; p.56). New mandatory
  ``GLONASS COD/PHS/BIS`` (p.44 sec. 9.10, p.56-57).
- **3.03**: ``LEAP SECONDS`` gains a time-system identifier (A3; "GPS" or
  "BDS") (p.60). ``GLONASS COD/PHS/BIS`` may be left entirely blank when the
  biases are unknown (p.47 sec. 9.9, p.60).
- **3.05**: ``LEAP SECONDS`` identifier "only GPS and BDT" (p.58). No other
  header-table change; the text is restructured.
- **4.00**: ``SYS / PHASE SHIFT`` and ``GLONASS COD/PHS/BIS`` become optional
  and strongly deprecated, to be ignored by decoders and encoders (p.25 sec.
  5.2.12, p.26 sec. 5.2.16; p.60-61). New optional ``DOI``, ``LICENSE OF USE``,
  ``STATION INFORMATION`` (p.9, p.56-57). ``PGM / RUN BY / DATE`` must be the
  second line, and more lines of it may follow to keep the file's history
  (p.22 sec. 5.2.1-5.2.2, p.54). ``LEAP SECONDS``: only "GPS" is a valid
  identifier and the day number is 1-7 (p.62).
- **4.01, 4.02**: the header table is unchanged apart from wording (NavIC
  renaming); checked line by line against 4.00 (4.01 p.58-66, 4.02 p.60-68).
"""

from rinexcore.spec.obscodes import normalize_version

V2 = ("2.10", "2.11")
V3 = ("3.00", "3.01", "3.02", "3.03", "3.04", "3.05")
V4 = ("4.00", "4.01", "4.02")
VERSIONS = V2 + V3 + V4

SOURCE_FILES = {
    "2.10": "rinex210.txt",
    "2.11": "rinex211.txt",
    "3.00": "rinex300.txt",
    "3.01": "rinex301.txt",
    "3.02": "rinex302.txt",
    "3.03": "rinex303_update1.txt",
    "3.04": "rinex304.txt",
    "3.05": "rinex305.txt",
    "4.00": "rinex_4.00.txt",
    "4.01": "rinex_4.01.txt",
    "4.02": "rinex_4.02.txt",
}

HEADER_TABLE = {v: ("Table A1" if v in ("2.10", "2.11", "3.00", "3.01") else "Table A2")
                for v in VERSIONS}

STATUS_CODES = {
    "M": "mandatory",
    "O": "optional",
    "C": "conditional (see 'conditions')",
    "O-deprecated": "optional and (strongly) deprecated",
}

# ---------------------------------------------------------------------------
# Where each label's row starts: line number (2.x) or page (3.x, 4.x).
# Taken from the "===== page N =====" markers; checked by the unit tests.
# ---------------------------------------------------------------------------
_LOC = {
    "2.10": {
        "RINEX VERSION / TYPE": 818, "PGM / RUN BY / DATE": 827, "COMMENT": 831,
        "MARKER NAME": 833, "MARKER NUMBER": 835, "OBSERVER / AGENCY": 837,
        "REC # / TYPE / VERS": 839, "ANT # / TYPE": 842, "APPROX POSITION XYZ": 844,
        "ANTENNA: DELTA H/E/N": 846, "WAVELENGTH FACT L1/2": 852,
        "# / TYPES OF OBSERV": 879, "INTERVAL": 914, "TIME OF FIRST OBS": 916,
        "TIME OF LAST OBS": 924, "RCV CLOCK OFFS APPL": 929, "LEAP SECONDS": 935,
        "# OF SATELLITES": 938, "PRN / # OF OBS": 941, "END OF HEADER": 952,
    },
    "2.11": {
        "RINEX VERSION / TYPE": 1073, "PGM / RUN BY / DATE": 1082, "COMMENT": 1086,
        "MARKER NAME": 1088, "MARKER NUMBER": 1090, "OBSERVER / AGENCY": 1092,
        "REC # / TYPE / VERS": 1094, "ANT # / TYPE": 1097, "APPROX POSITION XYZ": 1099,
        "ANTENNA: DELTA H/E/N": 1101, "WAVELENGTH FACT L1/2": 1107,
        "# / TYPES OF OBSERV": 1135, "INTERVAL": 1181, "TIME OF FIRST OBS": 1183,
        "TIME OF LAST OBS": 1193, "RCV CLOCK OFFS APPL": 1198, "LEAP SECONDS": 1204,
        "# OF SATELLITES": 1207, "PRN / # OF OBS": 1210, "END OF HEADER": 1222,
    },
    "3.00": {
        "RINEX VERSION / TYPE": 26, "PGM / RUN BY / DATE": 26, "COMMENT": 26,
        "MARKER NAME": 26, "MARKER NUMBER": 26, "MARKER TYPE": 26,
        "OBSERVER / AGENCY": 26, "REC # / TYPE / VERS": 26, "ANT # / TYPE": 26,
        "APPROX POSITION XYZ": 26, "ANTENNA: DELTA H/E/N": 27,
        "ANTENNA: DELTA X/Y/Z": 27, "ANTENNA: PHASECENTER": 27,
        "ANTENNA: B.SIGHT XYZ": 27, "ANTENNA: ZERODIR AZI": 27,
        "ANTENNA: ZERODIR XYZ": 27, "CENTER OF MASS: XYZ": 27,
        "SYS / # / OBS TYPES": 27, "SIGNAL STRENGTH UNIT": 28, "INTERVAL": 28,
        "TIME OF FIRST OBS": 28, "TIME OF LAST OBS": 28, "RCV CLOCK OFFS APPL": 28,
        "SYS / DCBS APPLIED": 29, "SYS / PCVS APPLIED": 29, "SYS / SCALE FACTOR": 29,
        "LEAP SECONDS": 29, "# OF SATELLITES": 29, "PRN / # OF OBS": 29,
        "END OF HEADER": 29,
    },
    "3.01": {
        "RINEX VERSION / TYPE": 29, "PGM / RUN BY / DATE": 29, "COMMENT": 29,
        "MARKER NAME": 29, "MARKER NUMBER": 29, "MARKER TYPE": 29,
        "OBSERVER / AGENCY": 29, "REC # / TYPE / VERS": 29, "ANT # / TYPE": 29,
        "APPROX POSITION XYZ": 29, "ANTENNA: DELTA H/E/N": 30,
        "ANTENNA: DELTA X/Y/Z": 30, "ANTENNA: PHASECENTER": 30,
        "ANTENNA: B.SIGHT XYZ": 30, "ANTENNA: ZERODIR AZI": 30,
        "ANTENNA: ZERODIR XYZ": 30, "CENTER OF MASS: XYZ": 30,
        "SYS / # / OBS TYPES": 30, "SIGNAL STRENGTH UNIT": 31, "INTERVAL": 31,
        "TIME OF FIRST OBS": 31, "TIME OF LAST OBS": 31, "RCV CLOCK OFFS APPL": 32,
        "SYS / DCBS APPLIED": 32, "SYS / PCVS APPLIED": 32, "SYS / SCALE FACTOR": 32,
        "SYS / PHASE SHIFT": 32, "GLONASS SLOT / FRQ #": 32, "LEAP SECONDS": 33,
        "# OF SATELLITES": 33, "PRN / # OF OBS": 33, "END OF HEADER": 33,
    },
    "3.02": {
        "RINEX VERSION / TYPE": 51, "PGM / RUN BY / DATE": 51, "COMMENT": 51,
        "MARKER NAME": 51, "MARKER NUMBER": 51, "MARKER TYPE": 51,
        "OBSERVER / AGENCY": 52, "REC # / TYPE / VERS": 52, "ANT # / TYPE": 52,
        "APPROX POSITION XYZ": 52, "ANTENNA: DELTA H/E/N": 52,
        "ANTENNA: DELTA X/Y/Z": 52, "ANTENNA: PHASECENTER": 52,
        "ANTENNA: B.SIGHT XYZ": 52, "ANTENNA: ZERODIR AZI": 52,
        "ANTENNA: ZERODIR XYZ": 52, "CENTER OF MASS: XYZ": 52,
        "SYS / # / OBS TYPES": 53, "SIGNAL STRENGTH UNIT": 54, "INTERVAL": 55,
        "TIME OF FIRST OBS": 55, "TIME OF LAST OBS": 55, "RCV CLOCK OFFS APPL": 55,
        "SYS / DCBS APPLIED": 55, "SYS / PCVS APPLIED": 55, "SYS / SCALE FACTOR": 55,
        "SYS / PHASE SHIFT": 56, "GLONASS SLOT / FRQ #": 56, "GLONASS COD/PHS/BIS": 56,
        "LEAP SECONDS": 57, "# OF SATELLITES": 57, "PRN / # OF OBS": 57,
        "END OF HEADER": 57,
    },
    "3.03": {
        "RINEX VERSION / TYPE": 54, "PGM / RUN BY / DATE": 54, "COMMENT": 54,
        "MARKER NAME": 54, "MARKER NUMBER": 54, "MARKER TYPE": 54,
        "OBSERVER / AGENCY": 55, "REC # / TYPE / VERS": 55, "ANT # / TYPE": 55,
        "APPROX POSITION XYZ": 55, "ANTENNA: DELTA H/E/N": 55,
        "ANTENNA: DELTA X/Y/Z": 55, "ANTENNA: PHASECENTER": 55,
        "ANTENNA: B.SIGHT XYZ": 55, "ANTENNA: ZERODIR AZI": 55,
        "ANTENNA: ZERODIR XYZ": 55, "CENTER OF MASS: XYZ": 55,
        "SYS / # / OBS TYPES": 56, "SIGNAL STRENGTH UNIT": 57, "INTERVAL": 58,
        "TIME OF FIRST OBS": 58, "TIME OF LAST OBS": 58, "RCV CLOCK OFFS APPL": 58,
        "SYS / DCBS APPLIED": 58, "SYS / PCVS APPLIED": 58, "SYS / SCALE FACTOR": 58,
        "SYS / PHASE SHIFT": 59, "GLONASS SLOT / FRQ #": 59, "GLONASS COD/PHS/BIS": 59,
        "LEAP SECONDS": 60, "# OF SATELLITES": 60, "PRN / # OF OBS": 60,
        "END OF HEADER": 61,
    },
    "3.04": {
        "RINEX VERSION / TYPE": 59, "PGM / RUN BY / DATE": 59, "COMMENT": 59,
        "MARKER NAME": 59, "MARKER NUMBER": 59, "MARKER TYPE": 59,
        "OBSERVER / AGENCY": 60, "REC # / TYPE / VERS": 60, "ANT # / TYPE": 60,
        "APPROX POSITION XYZ": 60, "ANTENNA: DELTA H/E/N": 60,
        "ANTENNA: DELTA X/Y/Z": 60, "ANTENNA: PHASECENTER": 60,
        "ANTENNA: B.SIGHT XYZ": 60, "ANTENNA: ZERODIR AZI": 60,
        "ANTENNA: ZERODIR XYZ": 60, "CENTER OF MASS: XYZ": 61,
        "SYS / # / OBS TYPES": 61, "SIGNAL STRENGTH UNIT": 63, "INTERVAL": 63,
        "TIME OF FIRST OBS": 63, "TIME OF LAST OBS": 63, "RCV CLOCK OFFS APPL": 63,
        "SYS / DCBS APPLIED": 63, "SYS / PCVS APPLIED": 63, "SYS / SCALE FACTOR": 64,
        "SYS / PHASE SHIFT": 64, "GLONASS SLOT / FRQ #": 64, "GLONASS COD/PHS/BIS": 64,
        "LEAP SECONDS": 65, "# OF SATELLITES": 65, "PRN / # OF OBS": 65,
        "END OF HEADER": 66,
    },
    "3.05": {
        "RINEX VERSION / TYPE": 52, "PGM / RUN BY / DATE": 52, "COMMENT": 52,
        "MARKER NAME": 52, "MARKER NUMBER": 52, "MARKER TYPE": 52,
        "OBSERVER / AGENCY": 53, "REC # / TYPE / VERS": 53, "ANT # / TYPE": 53,
        "APPROX POSITION XYZ": 53, "ANTENNA: DELTA H/E/N": 53,
        "ANTENNA: DELTA X/Y/Z": 53, "ANTENNA: PHASECENTER": 53,
        "ANTENNA: B.SIGHT XYZ": 53, "ANTENNA: ZERODIR AZI": 53,
        "ANTENNA: ZERODIR XYZ": 53, "CENTER OF MASS: XYZ": 53,
        "SYS / # / OBS TYPES": 53, "SIGNAL STRENGTH UNIT": 55, "INTERVAL": 55,
        "TIME OF FIRST OBS": 55, "TIME OF LAST OBS": 56, "RCV CLOCK OFFS APPL": 56,
        "SYS / DCBS APPLIED": 56, "SYS / PCVS APPLIED": 56, "SYS / SCALE FACTOR": 56,
        "SYS / PHASE SHIFT": 57, "GLONASS SLOT / FRQ #": 57, "GLONASS COD/PHS/BIS": 57,
        "LEAP SECONDS": 58, "# OF SATELLITES": 58, "PRN / # OF OBS": 58,
        "END OF HEADER": 58,
    },
    "4.00": {
        "RINEX VERSION / TYPE": 54, "PGM / RUN BY / DATE": 54, "COMMENT": 54,
        "MARKER NAME": 54, "MARKER NUMBER": 55, "MARKER TYPE": 55,
        "OBSERVER / AGENCY": 55, "REC # / TYPE / VERS": 55, "ANT # / TYPE": 55,
        "APPROX POSITION XYZ": 55, "ANTENNA: DELTA H/E/N": 56,
        "ANTENNA: DELTA X/Y/Z": 56, "ANTENNA: PHASECENTER": 56,
        "ANTENNA: B.SIGHT XYZ": 56, "ANTENNA: ZERODIR AZI": 56,
        "ANTENNA: ZERODIR XYZ": 56, "CENTER OF MASS: XYZ": 56, "DOI": 56,
        "LICENSE OF USE": 56, "STATION INFORMATION": 57,
        "SYS / # / OBS TYPES": 57, "SIGNAL STRENGTH UNIT": 59, "INTERVAL": 59,
        "TIME OF FIRST OBS": 59, "TIME OF LAST OBS": 59, "RCV CLOCK OFFS APPL": 59,
        "SYS / DCBS APPLIED": 60, "SYS / PCVS APPLIED": 60, "SYS / SCALE FACTOR": 60,
        "SYS / PHASE SHIFT": 60, "GLONASS SLOT / FRQ #": 61, "GLONASS COD/PHS/BIS": 61,
        "LEAP SECONDS": 62, "# OF SATELLITES": 62, "PRN / # OF OBS": 62,
        "END OF HEADER": 62,
    },
    "4.01": {
        "RINEX VERSION / TYPE": 58, "PGM / RUN BY / DATE": 58, "COMMENT": 58,
        "MARKER NAME": 58, "MARKER NUMBER": 59, "MARKER TYPE": 59,
        "OBSERVER / AGENCY": 59, "REC # / TYPE / VERS": 59, "ANT # / TYPE": 59,
        "APPROX POSITION XYZ": 59, "ANTENNA: DELTA H/E/N": 60,
        "ANTENNA: DELTA X/Y/Z": 60, "ANTENNA: PHASECENTER": 60,
        "ANTENNA: B.SIGHT XYZ": 60, "ANTENNA: ZERODIR AZI": 60,
        "ANTENNA: ZERODIR XYZ": 60, "CENTER OF MASS: XYZ": 60, "DOI": 60,
        "LICENSE OF USE": 60, "STATION INFORMATION": 61,
        "SYS / # / OBS TYPES": 61, "SIGNAL STRENGTH UNIT": 63, "INTERVAL": 63,
        "TIME OF FIRST OBS": 63, "TIME OF LAST OBS": 63, "RCV CLOCK OFFS APPL": 63,
        "SYS / DCBS APPLIED": 64, "SYS / PCVS APPLIED": 64, "SYS / SCALE FACTOR": 64,
        "SYS / PHASE SHIFT": 64, "GLONASS SLOT / FRQ #": 65, "GLONASS COD/PHS/BIS": 65,
        "LEAP SECONDS": 66, "# OF SATELLITES": 66, "PRN / # OF OBS": 66,
        "END OF HEADER": 66,
    },
    "4.02": {
        "RINEX VERSION / TYPE": 60, "PGM / RUN BY / DATE": 60, "COMMENT": 60,
        "MARKER NAME": 60, "MARKER NUMBER": 61, "MARKER TYPE": 61,
        "OBSERVER / AGENCY": 61, "REC # / TYPE / VERS": 61, "ANT # / TYPE": 61,
        "APPROX POSITION XYZ": 61, "ANTENNA: DELTA H/E/N": 62,
        "ANTENNA: DELTA X/Y/Z": 62, "ANTENNA: PHASECENTER": 62,
        "ANTENNA: B.SIGHT XYZ": 62, "ANTENNA: ZERODIR AZI": 62,
        "ANTENNA: ZERODIR XYZ": 62, "CENTER OF MASS: XYZ": 62, "DOI": 62,
        "LICENSE OF USE": 62, "STATION INFORMATION": 63,
        "SYS / # / OBS TYPES": 63, "SIGNAL STRENGTH UNIT": 65, "INTERVAL": 65,
        "TIME OF FIRST OBS": 65, "TIME OF LAST OBS": 65, "RCV CLOCK OFFS APPL": 65,
        "SYS / DCBS APPLIED": 66, "SYS / PCVS APPLIED": 66, "SYS / SCALE FACTOR": 66,
        "SYS / PHASE SHIFT": 66, "GLONASS SLOT / FRQ #": 67, "GLONASS COD/PHS/BIS": 67,
        "LEAP SECONDS": 68, "# OF SATELLITES": 68, "PRN / # OF OBS": 68,
        "END OF HEADER": 68,
    },
}


def _v(versions, value):
    """Same value for every version in ``versions``."""
    return {v: value for v in versions}


_ALL = VERSIONS
_V3V4 = V3 + V4

# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------
OBS_HEADER = {
    "RINEX VERSION / TYPE": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "F9.2,11X,A1,19X,A1,19X"),
        "notes": {
            "2.10": "Must be the first record (sec. 5.2, l.473). System: blank or G, R, S, "
                    "T, M (l.820-825).",
            "2.11": "Must be the first record (l.596). System: blank or G, R, S, E, M "
                    "(l.1075-1080).",
            **_v(_V3V4, "Must be the first record (3.00 p.16 sec. 6.5; 4.00 p.22 sec. 5.2.1). "
                        "System letters as in obscodes.SYSTEMS, or M for mixed."),
            "3.01": "Must be the first record (p.16 sec. 6.5). Table A1 lists only "
                    "G/R/E/S/M although Table 1 (p.8) defines C (Compass); see "
                    "docs/SPEC_TABLES.md.",
        },
        "repeat": "Once, first line.",
    },
    "PGM / RUN BY / DATE": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "A20,A20,A20"),
        "notes": {
            **_v(V2, "Date of file creation, A20, no format prescribed."),
            **_v(_V3V4, "Date format 'yyyymmdd hhmmss zone', zone 3-4 characters, UTC "
                        "recommended, LCL if local time with unknown zone. See PGM_RUN_BY_DATE."),
        },
        "repeat": "See PGM_RUN_BY_DATE: allowed to repeat only from 4.00.",
    },
    "COMMENT": {
        "versions": _v(_ALL, "O"),
        "format": _v(_ALL, "A60"),
        "repeat": "Any number of lines ('Comment line(s)').",
    },
    "MARKER NAME": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "A60"),
        "notes": _v(V4, "Free text; the 9-character station ID (XXXXMRCCC) is expected in "
                        "large networks (4.00 p.54)."),
    },
    "MARKER NUMBER": {
        "versions": _v(_ALL, "O"),
        "format": _v(_ALL, "A20"),
        "notes": _v(V4, "Free text; the IERS DOMES number is expected in large networks "
                        "(4.00 p.55)."),
    },
    "MARKER TYPE": {
        "versions": _v(_V3V4, "C"),
        "format": _v(_V3V4, "A20,40X"),
        "conditions": _v(_V3V4, "Unstarred, but 'Record required except for GEODETIC and "
                                "NON_GEODETIC marker types'. Users may define other keywords."),
    },
    "OBSERVER / AGENCY": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "A20,A40"),
    },
    "REC # / TYPE / VERS": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "3A20"),
    },
    "ANT # / TYPE": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "2A20"),
    },
    "APPROX POSITION XYZ": {
        "versions": {**_v(V2, "M"), **_v(_V3V4, "C")},
        "format": _v(_ALL, "3F14.4"),
        "conditions": _v(_V3V4, "Unstarred, but 'Optional for moving platforms'."),
        "notes": {**_v(V2, "WGS84 (l.844 / l.1099)."),
                  **_v(V3, "ITRS recommended."), **_v(V4, "ITRF recommended.")},
    },
    "ANTENNA: DELTA H/E/N": {
        "versions": _v(_ALL, "M"),
        "format": {**_v(V2, "3F14.4"), **_v(_V3V4, "F14.4,2F14.4")},
        "notes": _v(_V3V4, "Same layout as 3F14.4: height, then east/north eccentricity."),
    },
    "ANTENNA: DELTA X/Y/Z": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "3F14.4"),
    },
    "ANTENNA: PHASECENTER": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "A1,1X,A3,F9.4,2F14.4"),
        "notes": {
            **_v(("3.02", "3.03", "3.04"),
                 "The Table A2 text prints 'ANTENNA:PHASECENTER' (no space, 19 characters); "
                 "the body text and all other versions have the 20-character "
                 "'ANTENNA: PHASECENTER'. Check the PDF."),
        },
        "repeat": "Not stated. The record is per satellite system and observation code "
                  "(3.00 p.14 sec. 5.9), which implies one line per system/code.",
    },
    "ANTENNA: B.SIGHT XYZ": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "3F14.4"),
    },
    "ANTENNA: ZERODIR AZI": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "F14.4"),
    },
    "ANTENNA: ZERODIR XYZ": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "3F14.4"),
    },
    "CENTER OF MASS: XYZ": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "3F14.4"),
    },
    "DOI": {
        "versions": _v(V4, "O"),
        "format": _v(V4, "A60"),
        "notes": _v(V4, "Digital Object Identifier for data citation (4.00 p.9, p.56)."),
    },
    "LICENSE OF USE": {
        "versions": _v(V4, "O"),
        "format": _v(V4, "A60"),
        "repeat": "'Line(s)'.",
    },
    "STATION INFORMATION": {
        "versions": _v(V4, "O"),
        "format": _v(V4, "A60"),
        "repeat": "'Line(s)'.",
    },
    "WAVELENGTH FACT L1/2": {
        "versions": {"2.10": "M", "2.11": "O"},
        "format": {"2.10": "2I6,I6", "2.11": "2I6,I6"},
        "continuation": None,
        "notes": {
            "2.10": "The default line (2I6,I6: L1 and L2 factors, then zero or blank) is "
                    "required and must precede the satellite-specific lines (l.852-862, "
                    "sec. 5.2 l.475). Optional satellite-specific lines: "
                    "2I6,I6,7(3X,A1,I2) = factors, number of satellites, PRN list "
                    "(l.864-877). Factor 1 full cycle, 2 half cycle, 0 in L2 single "
                    "frequency.",
            "2.11": "Optional for GPS, obsolete for other systems, factors default to 1 "
                    "(l.1107-1118, sec. 10.1.2 l.992-1001). If present the default line "
                    "must precede the satellite-specific lines 2I6,I6,7(3X,A1,I2) "
                    "(l.1120-1133).",
        },
        "satellite_format": {"2.10": "2I6,I6,7(3X,A1,I2)", "2.11": "2I6,I6,7(3X,A1,I2)"},
        "repeat": "Satellite-specific lines: 'Repeat record if necessary' (2.10 l.877, "
                  "2.11 l.1133).",
    },
    "# / TYPES OF OBSERV": {
        "versions": _v(V2, "M"),
        "format": {"2.10": "I6,9(4X,A2)", "2.11": "I6,9(4X,A1,A1)"},
        "continuation": {"2.10": "6X,9(4X,A2)", "2.11": "6X,9(4X,2A1)"},
        "notes": {
            "2.10": "One list for the whole file (codes in obscodes.V2_HEADER_CODES).",
            "2.11": "Continuation lines must include the header label in columns 61-80 "
                    "(l.1141-1142). Observation code + frequency code, uppercase.",
        },
        "repeat": "Continuation lines for more than 9 types.",
    },
    "SYS / # / OBS TYPES": {
        "versions": _v(_V3V4, "M"),
        "format": _v(_V3V4, "A1,2X,I3,13(1X,A3)"),
        "continuation": _v(_V3V4, "6X,13(1X,A3)"),
        "notes": {
            **_v(_V3V4, "Should precede SYS / DCBS APPLIED and SYS / SCALE FACTOR (3.00 "
                        "p.17 sec. 6.5)."),
            "3.02": "Table A2 lists the system code as G/R/E/J/C/S/M; the M was removed in "
                    "3.03 (rinex303_update1.txt p.8, revision 03-Dec-2013).",
        },
        "repeat": "Once per satellite system in mixed files, plus continuation lines for "
                  "more than 13 descriptors.",
    },
    "SIGNAL STRENGTH UNIT": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "A20,40X"),
        "notes": _v(_V3V4, "e.g. DBHZ."),
    },
    "INTERVAL": {
        "versions": _v(_ALL, "O"),
        "format": _v(_ALL, "F10.3"),
    },
    "TIME OF FIRST OBS": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "5I6,F13.7,5X,A3"),
        "notes": {
            "2.10": "Time system GPS or GLO; compulsory in mixed GPS/GLONASS files; defaults "
                    "GPS for pure GPS, GLO for pure GLONASS (l.916-922).",
            "2.11": "Time system GPS, GLO or GAL; compulsory in mixed GPS/GLONASS files "
                    "(l.1183-1191).",
            **_v(("3.00", "3.01"), "Time system GPS, GLO, GAL; compulsory in mixed files."),
            "3.02": "Time system GPS, GLO, GAL, QZS, BDT; compulsory in mixed files.",
            **_v(("3.03", "3.04", "3.05") + V4,
                 "Time system GPS, GLO, GAL, QZS, BDT, IRN; compulsory in mixed files."),
        },
    },
    "TIME OF LAST OBS": {
        "versions": _v(_ALL, "O"),
        "format": _v(_ALL, "5I6,F13.7,5X,A3"),
        "notes": _v(_ALL, "Time system must equal the one in TIME OF FIRST OBS."),
    },
    "RCV CLOCK OFFS APPL": {
        "versions": _v(_ALL, "C"),
        "format": _v(_ALL, "I6"),
        "conditions": _v(_ALL, "Starred (optional) in the table, but 'Record required if "
                               "clock offsets are reported' in the epoch records. "
                               "1=yes, 0=no, default 0."),
    },
    "SYS / DCBS APPLIED": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "A1,1X,A17,1X,A40"),
        "repeat": "'Repeat for each satellite system.'",
    },
    "SYS / PCVS APPLIED": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "A1,1X,A17,1X,A40"),
        "repeat": "'Repeat for each satellite system.'",
    },
    "SYS / SCALE FACTOR": {
        "versions": _v(_V3V4, "O"),
        "format": _v(_V3V4, "A1,1X,I4,2X,I2,12(1X,A3)"),
        "continuation": _v(_V3V4, "10X,12(1X,A3)"),
        "notes": _v(_V3V4, "Factor 1, 10, 100 or 1000; 1 assumed if the record is missing."),
        "repeat": "'Repeat record if different factors are applied to different "
                  "observation types.'",
    },
    "SYS / PHASE SHIFT": {
        "versions": {**_v(("3.01", "3.02", "3.03", "3.04", "3.05"), "M"),
                     **_v(V4, "O-deprecated")},
        "format": _v(V3[1:] + V4, "A1,1X,A3,1X,F8.5,2X,I2.2,10(1X,A3)"),
        "continuation": _v(V3[1:] + V4, "18X,10(1X,A3)"),
        "spelling": {"3.01": "SYS / PHASE SHIFTS"},
        "notes": {
            "3.01": "Printed 'SYS / PHASE SHIFTS' in Table A1 (p.32) and the sec. 9.1 example "
                    "(p.25); renamed in 3.02 (p.7, revision 9-May-2012). Mandatory (p.25 "
                    "sec. 9.1). Unknown corrections: leave code and rest blank.",
            **_v(("3.02", "3.03", "3.04", "3.05"),
                 "Mandatory (3.02 p.41 sec. 9.1). Three states: values 0 = aligned at "
                 "source; code given, rest blank = only reference signals; all blank = "
                 "alignment unknown (exceptional). phase(RINEX) = phase(orig) + correction."),
            **_v(V4, "'Strongly deprecated'; allowed for compatibility but 'should be ignored "
                     "by RINEX decoders and encoders' (4.00 p.25 sec. 5.2.12, p.60). "
                     "Correction field: cycles 'or blank if none'."),
        },
        "repeat": "'Repeat the record for all affected codes', plus continuation lines for "
                  "more than 10 satellites.",
    },
    "GLONASS SLOT / FRQ #": {
        "versions": {"3.01": "O", **_v(("3.02", "3.03", "3.04", "3.05") + V4, "M")},
        "format": {"3.01": "I3,1X,8(A1,I2.2,1X,I2)",
                   **_v(("3.02", "3.03", "3.04", "3.05") + V4, "I3,1X,8(A1,I2.2,1X,I2,1X)")},
        "continuation": {"3.01": "4X,8(A1,I2.2,1X,I2)",
                         **_v(("3.02", "3.03", "3.04", "3.05") + V4,
                              "4X,8(A1,I2.2,1X,I2,1X)")},
        "notes": {
            "3.01": "Optional (p.25 sec. 9.5). The printed format has no 1X after each "
                    "frequency number, but the example on p.27 has one; 3.02 'corrected' "
                    "the format (rinex302.txt p.7).",
            "3.02": "Mandatory in Table A2 (p.56) and revision 29-Nov-2012 (p.7), but "
                    "sec. 9.5 (p.43) still says 'optional'. Corrected to mandatory in "
                    "3.03 sec. 9.5.",
            **_v(("3.03", "3.04", "3.05") + V4,
                 "Mandatory. The table does not say whether it is required in files "
                 "without GLONASS; see docs/SPEC_TABLES.md."),
        },
        "repeat": "Continuation lines for more than 8 satellites.",
    },
    "GLONASS COD/PHS/BIS": {
        "versions": {**_v(("3.02", "3.03", "3.04", "3.05"), "M"), **_v(V4, "O-deprecated")},
        "format": _v(("3.02", "3.03", "3.04", "3.05") + V4, "4(X1,A3,X1,F8.3)"),
        "notes": {
            **_v(("3.02", "3.03", "3.04", "3.05") + V4,
                 "Format printed as 4(X1,A3,X1,F8.3); 'X1' must mean 1X (the examples, "
                 "e.g. 3.02 p.44, read ' C1C  -10.000 C1P ...'). Signals C1C, C1P, C2C, "
                 "C2P, biases in metres."),
            "3.02": "Mandatory (p.44 sec. 9.10, p.56). The p.44 example prints the label "
                    "with an errant trailing '#' ('GLONASS COD/PHS/BIS#').",
            **_v(("3.03", "3.04", "3.05"),
                 "Mandatory; may contain zeros if aligned; if the biases are unknown all "
                 "fields are left blank and only the label is written (3.03 p.47, p.60)."),
            **_v(V4, "'Strongly deprecated', to be ignored by decoders and encoders; omit "
                     "the line if the values are unknown or 0.00 (4.00 p.26 sec. 5.2.16, "
                     "p.61)."),
        },
    },
    "LEAP SECONDS": {
        "versions": _v(_ALL, "O"),
        "format": {**_v(V2, "I6"), "3.00": "I6",
                   **_v(("3.01", "3.02"), "4I6"),
                   **_v(("3.03", "3.04", "3.05") + V4, "4I6,A3")},
        "notes": {
            "2.10": "Leap seconds since 6-Jan-1980; recommended for mixed GPS/GLONASS files.",
            "2.11": "Recommended for mixed files.",
            "3.00": "As transmitted by the GPS almanac; recommended for mixed GLONASS files.",
            **_v(("3.01", "3.02"), "Fields: current dt_LS, future/past dt_LSF, week WN_LSF "
                                   "(continuous), day DN; zero or blank if not known."),
            **_v(("3.03", "3.04"), "As 3.02 plus a time-system identifier: 'only GPS and "
                                   "BDS are valid identifiers', blank = GPS. DN 0-6 for "
                                   "BeiDou, 1-7 for GPS and others."),
            "3.05": "As 3.04 but the identifier text reads 'only GPS and BDT'.",
            **_v(V4, "Leap seconds since 6 Jan 1980, week since 6-Jan-1980, DN 1-7; 'only "
                     "GPS is valid identifier', blank = GPS. BDS-derived values must be "
                     "converted to the GPS convention (4.00 p.62)."),
        },
    },
    "# OF SATELLITES": {
        "versions": _v(_ALL, "O"),
        "format": _v(_ALL, "I6"),
        "notes": _v(_ALL, "If present, should be immediately followed by the PRN / # OF OBS "
                          "records."),
    },
    "PRN / # OF OBS": {
        "versions": _v(_ALL, "O"),
        "format": {**_v(V2, "3X,A1,I2,9I6"), **_v(_V3V4, "3X,A1,I2.2,9I6")},
        "continuation": _v(_ALL, "6X,9I6"),
        "notes": {
            "2.11": "Continuation lines must include the header label (l.1215-1216).",
            **_v(V3[1:] + V4, "99999 means >= 99999 observations."),
        },
        "repeat": "Once per satellite, plus continuation lines for more than 9 types.",
    },
    "END OF HEADER": {
        "versions": _v(_ALL, "M"),
        "format": _v(_ALL, "60X"),
        "repeat": "Once, last header line.",
    },
}


def _fill_cites():
    for label, entry in OBS_HEADER.items():
        cite = {}
        for ver in entry["versions"]:
            loc = _LOC[ver][label]
            where = f"l.{loc}" if ver in V2 else f"p.{loc}"
            cite[ver] = f"{SOURCE_FILES[ver]} {where} {HEADER_TABLE[ver]}"
        entry["cite"] = cite
        entry.setdefault("conditions", {})
        entry.setdefault("notes", {})
        entry.setdefault("spelling", {})
        entry.setdefault("continuation", {})
        if entry["continuation"] is None:
            entry["continuation"] = {}
        entry.setdefault("repeat", None)


_fill_cites()
del _fill_cites

# Machine-readable location of each label's row (for the unit tests).
LABEL_LOCATIONS = _LOC

# ---------------------------------------------------------------------------
# PGM / RUN BY / DATE: date format and repetition
# ---------------------------------------------------------------------------
PGM_RUN_BY_DATE = {
    "date_format": {
        **_v(V2, (None, "No format prescribed: 'Date of file creation' A20 (2.10 l.829, "
                        "2.11 l.1084).")),
        **_v(_V3V4, ("yyyymmdd hhmmss zone",
                     "zone is a 3-4 character time-zone code; UTC recommended; LCL if local "
                     "time with unknown zone (3.00 p.13 sec. 5.8; 3.05 p.23 sec. 5.2.2; "
                     "4.00 p.22 sec. 5.2.2).")),
    },
    "may_repeat": {
        **_v(V2, (False, "Not stated. Nothing in 2.10/2.11 allows a second line (inference: "
                         "one record).")),
        **_v(V3, (False, "Not stated; the text calls it 'the second header record' (3.00 "
                         "p.13 sec. 5.8, 3.05 p.23 sec. 5.2.2), i.e. one record in second "
                         "position (inference).")),
        **_v(V4, (True, "4.00 Table A2 p.54 note: it 'must be the second line'; "
                        "'Additional lines of this type can appear together after the second "
                        "line' to preserve the file's history. Same in sec. 5.2.1-5.2.2 "
                        "(4.00 p.22, 4.01 p.23, 4.02 p.24) and Table A2 (4.01 p.58, 4.02 p.60). "
                        "Added 15 Sep 2021 (4.00 p.119).")),
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm(version):
    ver = normalize_version(version)
    if ver not in VERSIONS:
        raise ValueError(f"no observation header table for RINEX {ver}")
    return ver


def labels_for(version):
    """Canonical labels defined for ``version``, in table order."""
    ver = _norm(version)
    return tuple(label for label, e in OBS_HEADER.items() if ver in e["versions"])


def status(version, label):
    """Status code of ``label`` in ``version``, or None if the version lacks it.

    ``label`` may be canonical or a version-specific spelling.
    """
    ver = _norm(version)
    entry = OBS_HEADER.get(canonical_label(label))
    if entry is None:
        return None
    return entry["versions"].get(ver)


def label_text(version, label):
    """The label exactly as ``version`` prints it (e.g. 3.01 'SYS / PHASE SHIFTS')."""
    ver = _norm(version)
    entry = OBS_HEADER[canonical_label(label)]
    if ver not in entry["versions"]:
        raise KeyError(f"{label!r} is not defined in RINEX {ver}")
    return entry["spelling"].get(ver, canonical_label(label))


def canonical_label(text):
    """Map a label as read from columns 61-80 to its canonical key.

    Strips trailing blanks; maps known version-specific spellings (e.g.
    'SYS / PHASE SHIFTS'). Unknown labels are returned stripped, unchanged.
    """
    label = text.rstrip()
    if label in OBS_HEADER:
        return label
    for canon, entry in OBS_HEADER.items():
        if label in entry["spelling"].values():
            return canon
    return label
