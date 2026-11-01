# Spec tables: observation codes and observation header

Transcribed by hand on 2026-10-30 from the text extractions in `specs/text/`.
Page numbers are the `===== page N =====` markers of each text, which are PDF
page numbers, not the numbers printed in the page footers. The RINEX 2 texts
have no page markers, so they are cited by line number (`l.N`). For 3.03 the
cited text is 3.03 Update 1 (`rinex303_update1.txt`).

## What is where

| File | Contents |
|---|---|
| `rinexcore/spec/obscodes.py` | `SYSTEMS` (systems allowed in observation files, per version); `SIGNAL_ROWS` (the rows of each RINEX 3/4 observation-code table: band, attribute, which of C/L/D/S exist, signal name); `OBS_CODES` (version, system, set of codes); `V2_HEADER_CODES` (the RINEX 2 global list); `PSEUDO_OBS` (`I` and `X`); `BLANK_ATTRIBUTE`; `BDS_B1_READ_RULE`; `CITATIONS` and `SOURCE_SPANS` (file, pages and exact line range of every table); `INFERRED`; helpers `normalize_version`, `valid_codes`, `is_valid`, `pseudo_obs_codes`, `blank_attribute_allowed` |
| `rinexcore/spec/obsheader.py` | `OBS_HEADER`: every observation-header label of every version, with status (M, O, C, O-deprecated), citation, field format, continuation format, conditions, notes, version-specific spelling and repetition rule; `PGM_RUN_BY_DATE` (date format and whether the line may repeat); helpers `labels_for`, `status`, `label_text`, `canonical_label`. The module docstring summarises what changes between versions |
| `tests/unit/test_spec_tables.py` | 33 tests, stdlib `unittest` |

## How it was checked

These checks run against the spec text every time the tests run:

- **Codes, exactly.** For every RINEX 3/4 version and system, the test takes
  the line range of that system's printed table and collects every token that
  looks like a code. That set must equal the transcribed set. The only tokens
  allowed to differ are QZSS signal names in the "Channel or Code" column
  (`L2C`, `L5S`, `L6D`, `L6P`). The same check runs on the original 3.03 text.
  RINEX 2.11 is checked row by row; 2.10 against its single list.
- **Pages.** Every code is printed on the page range its citation gives.
- **Header rows and stars.** Every header label is found at its cited page
  (or line, for RINEX 2), including the labels that 3.02 wraps over two lines.
  Whether the table prints the optional marker `*` must agree with the status.
  The three conditional rows are checked separately (see below).
- **Wording.** "Optional for moving platforms", "Record required except for
  GEODETIC", "strongly deprecated" (4.x) and the 4.x note that allows more
  than one `PGM / RUN BY / DATE` line are found on the cited pages.

A mutation check (changing two statuses, one page and two codes in memory)
made the tests fail in all five places.

Not checked automatically: the `format` strings (except a few), the notes,
and anything that only the PDF shows (see "Check against the PDF" below).

## Version gates (all verified in the text)

**Systems.**
- 2.10: G R S T. Transit is 2.10 only (2.11 l.989-990: "removed").
- 2.11 adds E.
- 3.01 adds C ("Compass"; Table 1, p.8).
- 3.02 adds J (p.13, p.51).
- 3.03 adds I (p.54).

**RINEX 2 codes.** 2.10 has no `C2` (l.886-897). 2.11 adds C2, C5, C6, C7, C8
with their L/D/S partners (l.961-980).

**GPS.**
- L1C `1S/1L/1X` from 3.01 (p.10).
- RMP-antenna M code `1R` and `2R` from 4.01 (4.01 p.29; revision Aug 2022,
  p.9).

**GLONASS.**
- G3 `3I/3Q/3X` from 3.02 (p.18).
- CDMA G1a `4A/4B/4X` and G2a `6A/6B/6X` from 3.04 (p.23).

**BeiDou.**
- B1I is `C2I` in 3.01 (p.11), `C1I` in 3.02 (p.20) and `C2I` again from 3.03
  (p.24).
- BDS-3 signals from 3.04 (p.26).
- 3.04 only: `1A` (B1A), `6A` (B3A) and codeless `L1N/D1N/S1N`.
- From 3.05, B1A is coded `1S/1L/1Z` and B3A `6D/6P/6Z` (3.05 p.34; revision
  19-Aug-2020, p.8).

**QZSS.**
- From 3.02 (p.19).
- Block II `5D/5P/5Z` and `6E/6Z` from 3.04 (p.25).
- L1Sb `1B` in 3.05, 4.00 and 4.01 only (3.05 p.33). 4.02 Table 14 prints
  "-" for it, with a footnote saying it is covered by the SBAS table (4.02
  p.33, revision Jun 2025 p.11).
- C/B `1E` from 4.00 (p.30).

**NavIC/IRNSS.**
- From 3.03 (p.24): `5A/5B/5C/5X`, `9A/9B/9C/9X`.
- L1 `1D/1P/1X` from **4.01** (4.01 p.34; revision Jun 2023, p.9).

**Galileo and SBAS.** The codes are identical in every version 3.00-4.02.

**Pseudo-observables.**
- `I` (ionosphere) bands 1-8 in 3.00-3.03 and 1-9 in 3.04. Removed in 3.05
  (revision 26-Aug-2020, p.9).
- `X` (channel number) band 0 in 3.00 and 3.01; bands 1-9 from 3.05.
- 3.02-3.04 contradict themselves on the band of `X` (see below).

**Blank attribute** ("unknown tracking mode"). Allowed in 3.00 and 3.01 (3.00
p.11, 3.01 p.12). Removed from 3.02 on (see below).

**Header records.**
- `WAVELENGTH FACT L1/2`: M in 2.10, O in 2.11, gone in 3.x.
- `# / TYPES OF OBSERV` is 2.x only. `SYS / # / OBS TYPES` is 3.00+.
- `SYS / PHASE SHIFT`: new in 3.01, M in 3.01-3.05, O-deprecated in 4.x.
- `GLONASS SLOT / FRQ #`: O in 3.01, M from 3.02.
- `GLONASS COD/PHS/BIS`: M in 3.02-3.05, O-deprecated in 4.x.
- `DOI`, `LICENSE OF USE` and `STATION INFORMATION`: O from 4.00.
- `LEAP SECONDS` format:
  - `I6` in 2.x and 3.00;
  - `4I6` in 3.01 and 3.02;
  - `4I6,A3` from 3.03.
- `GLONASS SLOT / FRQ #` format gains a trailing `1X` per satellite from 3.02.
- `PRN / # OF OBS`: the satellite number is `I2` in 2.x and `I2.2` in 3.x.
- `# / TYPES OF OBSERV` is `9(4X,A2)` in 2.10 and `9(4X,A1,A1)` in 2.11.

**`PGM / RUN BY / DATE`.**
- No date format in 2.x. `yyyymmdd hhmmss zone` from 3.00 (p.13 sec. 5.8).
- It may be repeated only from 4.00. 4.00 Table A2 p.54 says it "must be the
  second line in the header" and that "Additional lines of this type can
  appear together after the second line" to keep the file's history. Before
  4.00 nothing allows a second line; 3.x calls it "the second header record".

## Corrections to the brief and to CLAUDE.md (verified)

1. **NavIC L1 observation codes are in 4.01, not 4.02.** 4.02 adds the NavIC
   L1 *navigation* message (L1NV, 4.02 revision Sep 2023). PLAN.md says the
   same thing about the nav message, which is correct.
2. **`SYS / PHASE SHIFT` is already "strongly deprecated" in 4.00**, not first
   in 4.02. See 4.00 p.25 sec. 5.2.12 and p.60 Table A2, and the revision of
   10 Jun 2021 on p.118. CLAUDE.md says "strongly deprecates `SYS / PHASE
   SHIFT`" under 4.02. That is true of 4.02, but the change dates from 4.00.
3. **BDS codes changed between 3.04 and 3.05**, not only between 3.02 and
   3.03 (see the BeiDou gates above).

## Ambiguities and contradictions in the specs (check against the PDFs)

1. **2.10 has one global code list** (l.886-897), not one per system. The
   per-system split in `OBS_CODES["2.10"]` is an inference, recorded in
   `INFERRED["2.10"]`. G and R get L1 L2 C1 P1 P2 D1 D2 S1 S2. S gets
   C1 L1 D1 S1, from sec. 9.1 l.750-753 ("single frequency GEO payload",
   second-frequency fields blank). T gets T1 T2. For header validation of a
   2.10 file use `V2_HEADER_CODES["2.10"]`.
2. **3.01 Compass E1 (1589.74 MHz) row** prints "?" for the channel and for
   every code (p.11). It defines no codes, so it is left out.
3. **3.01 systems.** Table 1 (p.8) and sec. 9.3 (p.25) define `C`, and
   `SYS / PHASE SHIFTS` (p.32) lists G/R/E/S/C. But Table A1 `RINEX VERSION /
   TYPE` (p.29) and `SYS / # / OBS TYPES` (p.30) list only G/R/E/S. 3.01
   Table A1 also gives no band meaning for Compass. `SYSTEMS["3.01"]` includes
   C.
4. **3.01 label spelling.** It is `SYS / PHASE SHIFTS`, with a final S, in
   Table A1 (p.32) and in the sec. 9.1 example (p.25). 3.02 renamed it
   (revision 9-May-2012, p.7). It is recorded as
   `OBS_HEADER["SYS / PHASE SHIFT"]["spelling"]["3.01"]`, and
   `canonical_label()` maps it back.
5. **3.01 `GLONASS SLOT / FRQ #` format.** It is printed
   `I3,1X,8(A1,I2.2,1X,I2)` (p.32-33), with no blank after each frequency
   number. The example on p.27, `R01  1 R02  2`, has one. 3.02 says it
   "Corrected GLONASS SLOT/FRQ format" (p.7) and prints
   `8(A1,I2.2,1X,I2,1X)`. A 3.01 reader should accept both.
6. **3.02 `GLONASS SLOT / FRQ #` status.**
   - Table A2 (p.56, unstarred) and the revision of 29-Nov-2012 (p.7) make it
     mandatory.
   - Sec. 9.5 (p.43) still says "optional".
   - 3.03 fixed sec. 9.5 (revision 03-Dec-2013).

   Transcribed as M.
7. **3.02 blank attribute.**
   - The revision of 29-Nov-2012 (p.7) removed unknown tracking modes, and
     sec. 5.1 no longer allows them.
   - Table A2 (p.54) still says "blank: for types I and X (all) or unknown
     tracking mode" and "The attribute can be left blank if not known".
   - 3.03 removed both (revisions 15-Apr-2015 and 15-May-2015, p.10-11).

   Transcribed as not allowed.
8. **Band of the `X` pseudo-observable, 3.02-3.04.** Sec. 5.13 says band `1`
   (3.02 p.25, 3.03 p.29, 3.04 p.32). Table A2 says "0 for type X (all)"
   (3.02 p.53, 3.03 p.56, 3.04 p.62). `PSEUDO_OBS` lists both (`"01"`). 3.05
   removed band 0 as "not allowed" (p.9). **Policy question:** which band
   should a 3.02-3.04 writer use?
9. **3.02 `SYS / # / OBS TYPES` system list** includes `M` (p.53). 3.03
   removed it (revision 03-Dec-2013).
10. **Errant `#` in `GLONASS COD/PHS/BIS`.** The 3.02 example (p.44) and the
    original 3.03 examples (Tables 29 and 30, p.46-47) print
    `GLONASS COD/PHS/BIS#`. 3.03 Update 1 removed the `#` (revision
    7-Sep-2016). Readers may meet the `#` in real files.
11. **`GLONASS COD/PHS/BIS` format** is printed `4(X1,A3,X1,F8.3)` in every
    version. `X1` is not valid Fortran. The examples (3.02 p.44, 3.03 p.47,
    3.05 p.29) match `4(1X,A3,1X,F8.3)`.
12. **`ANTENNA: PHASECENTER` without the space.** The 3.02, 3.03 and 3.04
    Table A2 text prints `ANTENNA:PHASECENTER` (19 characters; 3.02 wraps it as
    `ANTENNA:PHASE` / `CENTER`). The body text and 3.00, 3.01 and 3.05+ print
    `ANTENNA: PHASECENTER`, which is exactly 20 characters. The canonical label
    keeps the space. **Check the 3.02-3.04 PDFs.** The missing space may be a
    PDF typo, or it may come from the extraction.
13. **`LEAP SECONDS` time-system identifier.**
    - 3.03 (p.60) and 3.04 (p.65): "only GPS and BDS are valid identifiers".
    - 3.05 (p.58): "only GPS and BDT".
    - 4.x (4.00 p.62): "only GPS".

    BDS time is `BDT` everywhere else in RINEX 3. **Policy question:** should
    a 3.03/3.04 reader accept both `BDS` and `BDT`?
14. **BeiDou B1I in 3.02 files.**
    - 3.03, 3.04 and 3.05 say both `1I/Q/X` and `2I/Q/X` should be accepted
      in a 3.02 file and treated as `2I/Q/X` (3.03 p.24, 3.04 p.26, 3.05
      p.34).
    - 4.00 and 4.01 generalise the note to "When reading a RINEX file" (4.00
      p.31, 4.01 p.33).
    - 4.02 removed it as obsolete (revision Jun 2025, p.11).

    From 3.04, `C1X/L1X/...` are also BDS-3 B1C codes. So the mapping is safe
    only for 3.02 input (`BDS_B1_READ_RULE`).
15. **3.04 vs 3.05 BeiDou B1A and B3A.** The same signals are coded `1A` and
    `6A` in 3.04 but `1S/1L/1Z` and `6D/6P/6Z` in 3.05+. 3.04 has a codeless
    `L1N` row for BDS-3 B1; 3.05 has none. **Policy question for the
    converter:** how should 3.04 `C1A`/`C6A`/`L1N` map to 3.05+? Should they
    map at all? The spec gives no mapping.
16. **4.02 QZSS L1Sb.** The observation table drops `1B` (p.33), but the 4.02
    phase-alignment table still lists "L1Sb L1B N/A" (p.129). The footnote
    sends L1Sb to the SBAS table. **Policy question:** should a 4.01 `J ... C1B`
    observation going to 4.02 be dropped, or rewritten as SBAS?
17. **Mandatory GLONASS records in files without GLONASS.** Table A2 marks
    `GLONASS SLOT / FRQ #` (3.02+) and `GLONASS COD/PHS/BIS` (3.02-3.05) as
    mandatory, with no "if GLONASS present". Requiring them in GPS-only files
    reads the table literally, and the spec does not say so. **Policy
    question.** The same applies to `SYS / PHASE SHIFT` in 3.01-3.05: it is
    mandatory, but nothing says it is needed per system present.
18. **Conditional rows.** Three rows are marked `C`:
    - `MARKER TYPE` (3.x/4.x): unstarred, but "Record required except for
      GEODETIC and NON_GEODETIC marker types".
    - `APPROX POSITION XYZ` (3.x/4.x): unstarred, "Optional for moving
      platforms".
    - `RCV CLOCK OFFS APPL` (all versions): starred, but "Record required if
      clock offsets are reported".
19. **3.03 Figure 1** (satellite system identifiers, p.17) is an image, so it
    is missing from the extraction. The 3.03 system list comes from Table A2
    (p.54).
20. **RINEX 2 non-standard systems.** Real 2.11 files may carry C, J and I
    satellites (CLAUDE.md). No 2.x spec defines them, so they are not in
    `SYSTEMS`. Treat them as a flagged extension in the reader.

## Inferences (not spec text)

- The 2.10 per-system split (item 1 above).
- `PGM / RUN BY / DATE` before 4.00 allowed exactly once. The 2.x and 3.x
  specs never say it may repeat, and 3.x calls it "the second header record".
- `ANTENNA: PHASECENTER` once per system and code. Repetition is not stated;
  the inference is from 3.00 sec. 5.9 (p.14).
