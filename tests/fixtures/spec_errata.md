# Spec errata and extraction repairs: the spec-example fixtures

This file goes with `tests/fixtures/spec_examples/` and `tests/unit/test_spec_examples.py`
(PLAN §1 clause 5d, §4). Following PLAN §1.5d, errors in the specs are **annotated here,
not fixed** in the fixtures. The only changes made to the printed text are:

- removing page furniture, ruler lines, and the 4-6 column indentation of the 3.00/3.01 examples;
- undoing the spec's own typographic devices: elision markers, wrapped lines, and record
  examples printed without a header (§c);
- repairing damage done by the PDF-to-text extraction, only where the column layout is
  obvious (§b).

Files named `*_derived_*.rnx` are not as printed. Each is a small, listed edit of an example
that is invalid as printed, so that the rest of that example can still be tested (§d).

**Sources.** Line numbers are 1-based lines of `specs/text/*.txt`. Page numbers come from
the `===== page N =====` markers. The 2.10 and 2.11 texts are the original plain-text
documents, so they have no page markers; they are cited by table and line. Fixtures are
latin-1 bytes with LF line endings, and trailing blanks are removed.

**Not extracted.**
- The short in-text snippets (for example rinex305.txt Tables 10-12 and 21-22, or
  rinex302.txt Tables 10-11). They are not complete files, and their records repeat the
  appendix examples.
- RINEX 3.03 Update 1 (`rinex303_update1.txt`). All 12 of its examples are byte-identical,
  after extraction, to those of 3.03 (checked), so they are not duplicated.

**How to read §b.** Many repairs say "restored from the same line of <version>/<example>".
The same example is printed in several spec versions. When a damaged line equals a clean
copy in a neighbouring version once all blanks are ignored, the clean copy's layout was
used. Lines with no such copy were repaired by rule: numbers re-laid in 19-column D19.12
fields, or a header label moved back to column 61. Every case is listed below. The
judgement calls are marked *unverified*: they could not be checked against the PDF page,
because the PDF renderer (poppler) is not available here.

---

## a. Errors in the specs themselves (kept as printed)

| ID | Where | What is wrong | Effect on the tests |
|---|---|---|---|
| E-01 | Table A7, rinex210.txt line 1326 | The last event record (flag 4) announces 4 special records, but only 3 COMMENT lines follow before the example ends. 2.11 prints `4  3` (rinex211.txt line 1605). | `2.10/a7_obs_mixed.rnx` must fail strict loading (expectedFailure). `2.10/a7_obs_mixed_derived_count.rnx` fixes the count. |
| E-02 | Table A18, rinex211.txt line 2051 | `D-UTC A0,A1,T,W,S,U` is printed one column left of its layout `2D19.12,I7,I5,X,A5,X,I2` (Table A15, rinex211.txt lines 1913-1928). A0 gets 18 columns, so the A0 field reads `0.133179128170D-06-`. | Every conversion of `2.11/a18_nav_geo.rnx` must end `refused-corrupt`, and it does. `2.11/a18_nav_geo_derived_columns.rnx` has the record re-aligned. |
| E-03 | Table A13 of 2.10 and 2.11 (2.11: rinex211.txt line 1800, 1804, 1808, ...) | The epoch satellite lists start with `  2`, a blank system identifier, in a GLONASS-only (`R`) file. rinex211.txt line 184: "A blank satellite identifier is allowed in pure GPS files only". The revision history ("Table A13 contained blank satellite identifiers: Sept 1998") says this was fixed, but one is still there. | Our reader and the token comparator both read it as R02 (the file's system). The identity normalisation does the same (blank → the system in RINEX VERSION / TYPE col 41, else G). |
| E-04 | Table A8 rinex211.txt line 1623 vs Table A6 rinex300.txt line 2273 (p. 34), also 3.01 rinex301.txt line 2529 (p. 38), 3.02 rinex302.txt line 3430 (p. 65), 3.03 rinex303.txt line 3823 (p. 73), 3.04 rinex304.txt line 4105 (p. 78), 3.05 rinex305.txt line 3909 (p. 70) | The same GPS broadcast message (1999-09-02/03, identical G06/G13 records) is printed with ION alpha2 and alpha3 = **-**.1192D-06 in 2.11, and **+**.1192D-06 (GPSA) in 3.00-3.05. One of the two is wrong. Which one can't be settled without the original broadcast data. | None: each fixture is tested as printed. |
| E-05 | Table A15, rinex300.txt line 2701 (p. 40) | The RINEX 3.00 met example has the version field `2.11`. Its body follows the 3.00 met layout, which is also the RINEX 2 layout: 3.00 and 3.01 define the met epoch with a 2-digit year, `1X,I2.2,5(1X,I2)` (rinex300.txt line 2672 (p. 39); rinex301.txt line 2944 (p. 43)). 3.02 changes it to `1X,I4.4` (rinex302.txt line 4218 (p. 79)). | `3.00/a15_met.rnx` is tested as a 2.11 file. *The 2-digit year in 3.00/3.01 met files is not an erratum*: `3.01/a15_met.rnx` is valid as printed. |
| E-06 | rinex300.txt lines 2402-2406 (p. 36), rinex301.txt lines 2673-2677 (p. 40), rinex302.txt lines 3594-3598 (p. 68) | The Galileo navigation example (A8/A9) is three header lines followed by "To be supplied later". It has no END OF HEADER and no records. | No fixture. |
| E-07 | Obs example #1 in 3.02 (rinex302.txt lines 3154-3156 (p. 60) vs data rinex302.txt line 3169 (p. 60)), 3.03 (rinex303.txt line 3293 (p. 64)), 3.04 (rinex304.txt line 3576 (p. 69)), 3.05 (rinex305.txt line 3347 (p. 61)), 4.00 (rinex_4.00.txt line 3465 (p. 64)), 4.01 (rinex_4.01.txt line 3746 (p. 68)), 4.02 (rinex_4.02.txt line 3835 (p. 70) vs data rinex_4.02.txt line 3858 (p. 71)) | The data observe R21 and R22, but `GLONASS SLOT / FRQ #` lists only R01-R18. The record exists to give each GLONASS satellite's channel, so the example is internally inconsistent. | Without channels for R21/R22, the converter refuses (`refused-missing-information`) even the same-version conversion. Whether it should is a policy question. The tests supply a test-only channel table (`R21 1`, `R22 1`; 3.00/3.01 have no slot record at all) and leave `GLONASS SLOT / FRQ #` out of the identity comparison. |
| E-08 | Obs examples #2 and #3 in 3.03 (rinex303.txt line 3443 (p. 66), rinex303.txt line 3515 (p. 67)), 3.04 (rinex304.txt line 3726 (p. 71), rinex304.txt line 3798 (p. 72)), 3.05 (rinex305.txt line 3509 (p. 63), rinex305.txt line 3586 (p. 64)); example #3 in 4.00 (rinex_4.00.txt line 3737 (p. 68)), 4.01 (rinex_4.01.txt line 4018 (p. 72)), 4.02 (rinex_4.02.txt line 4104 (p. 74)) | Each is a header, then one epoch line announcing 28 or 25 satellites with no satellite records. In 3.0x this is followed by an `END OF FILE` COMMENT line outside any event record. These are header examples with the data elided, so they are not valid files. | Strict loading must fail (expectedFailure); conversions are skipped. `*_derived_header.rnx` keeps the header only. |
| E-09 | 4.00 Table A5 rinex_4.00.txt line 3595 (p. 66), 4.01 rinex_4.01.txt line 3876 (p. 70), 4.02 rinex_4.02.txt line 3962 (p. 72) | The epoch announces 42 satellites, and 21 are printed (the rest are elided with `[…]`). | Strict loading must fail (expectedFailure). `*_derived_count.rnx` sets the count to 21. |
| E-10 | Obs example #1 `TIME OF FIRST OBS` in 3.05 (rinex305.txt line 3346 (p. 61)), 4.00 (rinex_4.00.txt line 3464 (p. 64)), 4.01 (rinex_4.01.txt line 3745 (p. 68)), 4.02 (rinex_4.02.txt line 3834 (p. 70)) | The record is printed 2 columns left of `5I6,F13.7,5X,A3`: the year is in cols 1-4, and the time system in cols 47-49 instead of 49-51. 3.02-3.04 print it correctly (for example rinex304.txt line 3575 (p. 69)). The 4.02 extraction is otherwise clean, so this is read as a spec error, not extraction damage. | Read by its format, the time system is `S`. In 3.05-4.01 our converter copies the record verbatim. In 4.02 it makes a spurious repair (the picosecond epoch) and rewrites the record with time system `S`, which fails identity for `4.02/a4_obs_example1.rnx`. |
| E-11 | obs example #3, rinex303.txt line 3495 (p. 67) | `SYS / PHASE SHIFT` gives `G L2Q -0.25000`, but the GPS observation types (C1C L1C D1C S1C C2S L2S D2S S2S C2W L2W D2W S2W C5Q L5Q D5Q S5Q) have no L2Q. 3.04 prints `G L5Q` (rinex304.txt line 3778 (p. 72)). | The converter drops the entry with the loss `phase-shift-entry-dropped:G:L2Q`, so identity of `3.03/a4_obs_example3_derived_header.rnx` also fails for this reason. |
| E-12 | Table A9 example #2, rinex304.txt line 4304 (p. 81); rinex305.txt line 4114 (p. 73); rinex303.txt line 4013 (p. 76) | `LEAP SECONDS 18` for data of 2015-06-19, when GPS-UTC was 16 s. 3.03 prints 16 (rinex303.txt line 4020 (p. 76)), and Galileo example #1 in the same table prints `16 17 1851 3`. Separately, 3.03's `BDUT` gives W = 1849 (a GPS week) where a BDS week is expected; 3.04 prints 492. | Content only; no effect on the tests. |
| E-13 | Table A12, `> EPH G04 CNV2` at rinex_4.01.txt line 4581 (p. 81) | The CNV2 record lacks `BROADCAST ORBIT - 7` (ISC_L1CA ... ISC_L5Q5): it has 9 lines, and Table A11 (rinex_4.01.txt lines 4499-4545 (p. 80)) requires 10. The 4.02 change log says "Table A12: add missing example data" (rinex_4.02.txt line 563 (p. 11)), and 4.02 has the line. | Strict loading should reject it (expectedFailure). **Our reader accepts it**, so the test reports an unexpected success (see the converter findings). |
| E-14 | various | Format nits that a Fortran reader accepts and our identity normalisation allows: I2.2 fields written as I2 (`> 2006  3 24` at rinex300.txt line 2072 (p. 31) and in every later version, the R02 seconds ` 0` at rinex300.txt line 2492 (p. 37), the SBAS epochs ` 0  1  4` at rinex300.txt line 2560 (p. 38)); epoch seconds `   .0490000` (2.10/2.11 Table A13, rinex211.txt line 1808); F14.3 cycle-slip values with one decimal (`123456789.0`, 2.10/2.11 Table A7, rinex211.txt line 1595); `INTERVAL` written as I6 (`     1`) and TIME OF FIRST/LAST OBS seconds with 6 decimals (2.10/2.11 Table A17, rinex211.txt lines 2008-2010); D and E exponent letters mixed in one file (3.05 Table A7); the COMMENT typo `VERSIOIN` (3.00/3.01). | None (normalised, or carried verbatim). |
| E-15 | 2.10/2.11 Table A17, rinex211.txt line 2010 | `TIME OF LAST OBS` 15:00:00, but the printed data end at 14:45:02 (the example is an excerpt). | The converter repairs it under clause 9 and reports `HDR.TIME-OF-LAST-OBS`. The identity check accepts a reported repair of that record. |

---

## b. Damage done by the PDF-to-text extraction (repaired)

The 2.10, 2.11 and 4.02 texts are essentially clean. 3.00-3.04 are clean apart from page
furniture. **3.05, 4.00 and 4.01 are heavily damaged**: blanks are inserted inside numbers
(`.107469589D        -12`), inside labels (`SYS / # / OBS T                  YPES`) and inside
message types (`> EPH S30 S   BAS`), and labels are pushed past column 80. Two repairs are
judgement calls (*unverified*):

- The event line `>                                     4  1` puts the flag at col 39 in
  3.05, 4.00 and 4.01. It is at col 32 in 3.02-3.04 and 4.02.
- `ANT # / TYPE` is shifted 5 columns right in 3.05, 4.00 and 4.01, and correct in 3.04 and 4.02.

Both are read as extraction damage, because every other line of those tables carries inserted
blanks and the 4.02 copy (clean extraction, not mentioned in its change log) is correct.

**3.05/a11_nav_mixed.rnx**

- rinex305.txt line 4268, p. 76: restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     3.05           N: GNSS NAV DATA    M: MIXED                           RINEX VERSION / TYPE`
  - fixture: `     3.05           N: GNSS NAV DATA    M: MIXED            RINEX VERSION / TYPE`
- rinex305.txt line 4272, p. 76: restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `GPSB   0.8806E+05  0.0000E+00        -0.1966E+06 -0.6554E+05       IONOSPHERIC CORR`
  - fixture: `GPSB   0.8806E+05  0.0000E+00 -0.1966E+06 -0.6554E+05       IONOSPHERIC CORR`
- rinex305.txt line 4273, p. 76: restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `GPUT  0.2793967723E-08 0.000000000E+00          147456 1395   G10  2       TIME SYSTEM CORR`
  - fixture: `GPUT  0.2793967723E-08 0.000000000E+00 147456 1395   G10  2 TIME SYSTEM CORR`
- rinex305.txt line 4274, p. 76: restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `GLUT  0.7823109626E-06 0.000000000E+00               0 1395   R10  0       TIME SYSTEM CORR`
  - fixture: `GLUT  0.7823109626E-06 0.000000000E+00      0 1395   R10  0 TIME SYSTEM CORR`
- rinex305.txt line 4277, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `G01 2006 10 01 00 00 00 0.798045657575E-04 0.227373675443E              -11 0.000000000000E+00`
  - fixture: `G01 2006 10 01 00 00 00 0.798045657575E-04 0.227373675443E-11 0.000000000000E+00`
- rinex305.txt line 4278, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.560000000000E+02     -0.78750000   0000E+01   0.375658504827E    -08 0.265129935612E+01`
  - fixture: `     0.560000000000E+02-0.787500000000E+01 0.375658504827E-08 0.265129935612E+01`
- rinex305.txt line 4279, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `    -0.411644577980E     -06 0.640150101390E-02 0.381097197533E         -05 0.515371852875E+04`
  - fixture: `    -0.411644577980E-06 0.640150101390E-02 0.381097197533E-05 0.515371852875E+04`
- rinex305.txt line 4280, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.000000000000E+00      0.782310962677E     -07 0.188667086536E+00     -0.391155481338E    -07`
  - fixture: `     0.000000000000E+00 0.782310962677E-07 0.188667086536E+00-0.391155481338E-07`
- rinex305.txt line 4284, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `    -0.600000000000E+02      0.40000000000    0E+01`
  - fixture: `    -0.600000000000E+02 0.400000000000E+01`
- rinex305.txt line 4285, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `G02 2006 10 01 00 00 00 0.402340665460E-04 0.386535248253E              -11 0.000000000000E+00`
  - fixture: `G02 2006 10 01 00 00 00 0.402340665460E-04 0.386535248253E-11 0.000000000000E+00`
- rinex305.txt line 4286, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.135000000000E+03      0.467500000000E+02      0.478269921862E    -08-0.238713891022E+01`
  - fixture: `     0.135000000000E+03 0.467500000000E+02 0.478269921862E-08-0.238713891022E+01`
- rinex305.txt line 4287, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.250712037086E     -05 0.876975362189E-02 0.819191336632E         -05 0.515372778320E+04`
  - fixture: `     0.250712037086E-05 0.876975362189E-02 0.819191336632E-05 0.515372778320E+04`
- rinex305.txt line 4288, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.000000000000E+00     -0.260770320892E     -07-0.195156738598E+01      0.128522515297E    -06`
  - fixture: `     0.000000000000E+00-0.260770320892E-07-0.195156738598E+01 0.128522515297E-06`
- rinex305.txt line 4292, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `    -0.600000000000E+02      0.400000000000E+01`
  - fixture: `    -0.600000000000E+02 0.400000000000E+01`
- rinex305.txt line 4293, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `R01 2006 10 01 00 15 00-0.137668102980E-04-0.454747350886E              -11 0.900000000000E+02`
  - fixture: `R01 2006 10 01 00 15 00-0.137668102980E-04-0.454747350886E-11 0.900000000000E+02`
- rinex305.txt line 4294, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.157594921875E+05     -0.145566368103E+01      0.000000000000E+00      0.000000000000E+00`
  - fixture: `     0.157594921875E+05-0.145566368103E+01 0.000000000000E+00 0.000000000000E+00`
- rinex305.txt line 4295, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `    -0.813711474609E+04      0.205006790161E+01      0.931322574615E    -09 0.700000000000E+01`
  - fixture: `    -0.813711474609E+04 0.205006790161E+01 0.931322574615E-09 0.700000000000E+01`
- rinex305.txt line 4296, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.183413398438E+05      0.215388488770E+01     -0.186264514923E    -08 0.100000000000E+01`
  - fixture: `     0.183413398438E+05 0.215388488770E+01-0.186264514923E-08 0.100000000000E+01`
- rinex305.txt line 4297, p. 76: blanks inserted inside numbers by the extraction removed; fields re-laid at 19 columns.
  - printed: `     1.790000000000E+02 8.381903171539E          -09 2.000000000000E+00      3.000000000000E+00`
  - fixture: `     1.790000000000E+02 8.381903171539E-09 2.000000000000E+00 3.000000000000E+00`
- rinex305.txt line 4298, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `R02 2006 10 01 00 15  0-0.506537035108E          -04 0.181898940355E    -11 0.300000000000E+02`
  - fixture: `R02 2006 10 01 00 15  0-0.506537035108E-04 0.181898940355E-11 0.300000000000E+02`
- rinex305.txt line 4299, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.155536342773E+05     -0.419384956360E+00      0.000000000000E+00      0.000000000000E+00`
  - fixture: `     0.155536342773E+05-0.419384956360E+00 0.000000000000E+00 0.000000000000E+00`
- rinex305.txt line 4300, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `    -0.199011298828E+05 0.324192047119E+00          -0.931322574615E    -09 0.100000000000E+01`
  - fixture: `    -0.199011298828E+05 0.324192047119E+00-0.931322574615E-09 0.100000000000E+01`
- rinex305.txt line 4301, p. 76: blanks inserted by the extraction removed; line restored from the same line of 3.04/a11_nav_mixed.rnx.
  - printed: `     0.355333544922E+04      0.352666091919E+01     -0.186264514923E    -08 0.100000000000E+01`
  - fixture: `     0.355333544922E+04 0.352666091919E+01-0.186264514923E-08 0.100000000000E+01`
- rinex305.txt line 4302, p. 76: blanks inserted inside numbers by the extraction removed; fields re-laid at 19 columns.
  - printed: `     5.200000000000E+01 9.456379289034E          -09 0.000000000000E+00 0.000000000000E+00`
  - fixture: `     5.200000000000E+01 9.456379289034E-09 0.000000000000E+00 0.000000000000E+00`

**3.05/a13_nav_qzss.rnx**

- rinex305.txt line 4417, p. 78: blanks inserted by the extraction removed; line restored from the same line of 3.04/a13_nav_qzss.rnx.
  - printed: `J01 2014 05 13 08 15 12 3.323303535581D-04-1.8189894035             46D-11 0.000000000000D+00`
  - fixture: `J01 2014 05 13 08 15 12 3.323303535581D-04-1.818989403546D-11 0.000000000000D+00`
- rinex305.txt line 4420, p. 78: blanks inserted by the extraction removed; line restored from the same line of 3.04/a13_nav_qzss.rnx.
  - printed: `     2.025120000000D+05-8.381903171539D-07-9.211997910060D             -01-2.041459083557D     -06`
  - fixture: `     2.025120000000D+05-8.381903171539D-07-9.211997910060D-01-2.041459083557D-06`

**3.05/a15_nav_beidou.rnx**

- rinex305.txt line 4530, p. 80: blanks inserted by the extraction removed; line restored from the same line of 3.04/a15_nav_beidou.rnx.
  - printed: `     1.000000000000e+00 4.365468750000e+02 1.318269196918e-09-3.118148933476e+                     00`
  - fixture: `     1.000000000000e+00 4.365468750000e+02 1.318269196918e-09-3.118148933476e+00`
- rinex305.txt line 4535, p. 80: blanks inserted by the extraction removed; line restored from the same line of 3.04/a15_nav_beidou.rnx.
  - printed: `     2.000000000000e+00 0.000000000000e+00 1.420000000000e-08-1.040000000000e                    -08`
  - fixture: `     2.000000000000e+00 0.000000000000e+00 1.420000000000e-08-1.040000000000e-08`

**3.05/a17_nav_sbas.rnx**

- rinex305.txt line 4623, p. 82: restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `     3.05           N: GNSS NAV DATA    S: SBAS                            RINEX VERSION / TYPE`
  - fixture: `     3.05           N: GNSS NAV DATA    S: SBAS             RINEX VERSION / TYPE`
- rinex305.txt line 4624, p. 82: restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `SBAS2RINEX 3.0      CNES                          20031018 140100     PGM / RUN BY / DATE`
  - fixture: `SBAS2RINEX 3.0      CNES                20031018 140100     PGM / RUN BY / DATE`
- rinex305.txt line 4626, p. 82: restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `SBUT  -.1331791282D-06 -.107469589D         -12 552960 1025 EGNOS  5 TIME SYSTEM CORR`
  - fixture: `SBUT  -.1331791282D-06 -.107469589D-12 552960 1025 EGNOS  5 TIME SYSTEM CORR`
- rinex305.txt line 4631, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `S22 2003 10 18  0  1  4-1.005828380585D          -07 6.366462912410D     -12 5.184420000000D+05`
  - fixture: `S22 2003 10 18  0  1  4-1.005828380585D-07 6.366462912410D-12 5.184420000000D+05`
- rinex305.txt line 4632, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `     2.482832392000D+04      -3.593750000000D    -04-1.375000000000D     -07 0.000000000000D+00`
  - fixture: `     2.482832392000D+04-3.593750000000D-04-1.375000000000D-07 0.000000000000D+00`
- rinex305.txt line 4633, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -3.408920872000D+04      -1.480625000000D    -03-5.000000000000D     -08 4.000000000000D+00`
  - fixture: `    -3.408920872000D+04-1.480625000000D-03-5.000000000000D-08 4.000000000000D+00`
- rinex305.txt line 4634, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -1.650560000000D+01       8.360000000000D    -04 6.250000000000D     -08 2.300000000000D+01`
  - fixture: `    -1.650560000000D+01 8.360000000000D-04 6.250000000000D-08 2.300000000000D+01`
- rinex305.txt line 4635, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `S22 2003 10 18  0  5 20-9.872019290924D-08 5.456968210638D               -12 5.186940000000D+05`
  - fixture: `S22 2003 10 18  0  5 20-9.872019290924D-08 5.456968210638D-12 5.186940000000D+05`
- rinex305.txt line 4636, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `     2.482822744000D+04      -3.962500000000D    -04-1.375000000000D     -07 0.000000000000D+00`
  - fixture: `     2.482822744000D+04-3.962500000000D-04-1.375000000000D-07 0.000000000000D+00`
- rinex305.txt line 4637, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -3.408958936000D+04      -1.492500000000D    -03-5.000000000000D     -08 4.000000000000D+00`
  - fixture: `    -3.408958936000D+04-1.492500000000D-03-5.000000000000D-08 4.000000000000D+00`
- rinex305.txt line 4638, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -1.628960000000D+01       8.520000000000D    -04 6.250000000000D     -08 2.400000000000D+01`
  - fixture: `    -1.628960000000D+01 8.520000000000D-04 6.250000000000D-08 2.400000000000D+01`
- rinex305.txt line 4639, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `S22 2003 10 18  0  9 36-9.732320904732D-08 4.547473508865D               -12 5.189510000000D+05`
  - fixture: `S22 2003 10 18  0  9 36-9.732320904732D-08 4.547473508865D-12 5.189510000000D+05`
- rinex305.txt line 4640, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `     2.482812152000D+04      -4.325000000000D    -04-1.375000000000D     -07 0.000000000000D+00`
  - fixture: `     2.482812152000D+04-4.325000000000D-04-1.375000000000D-07 0.000000000000D+00`
- rinex305.txt line 4641, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -3.408997304000D+04      -1.505000000000D    -03-5.000000000000D     -08 4.000000000000D+00`
  - fixture: `    -3.408997304000D+04-1.505000000000D-03-5.000000000000D-08 4.000000000000D+00`
- rinex305.txt line 4642, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -1.606960000000D+01       8.800000000000D    -04 6.250000000000D     -08 2.500000000000D+01`
  - fixture: `    -1.606960000000D+01 8.800000000000D-04 6.250000000000D-08 2.500000000000D+01`
- rinex305.txt line 4643, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `S22 2003 10 18  0 13 52-9.592622518539D-08 4.547473508865D               -12 5.192110000000D+05`
  - fixture: `S22 2003 10 18  0 13 52-9.592622518539D-08 4.547473508865D-12 5.192110000000D+05`
- rinex305.txt line 4644, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `     2.4828006320    00D+04-4.681250000000D      -04-1.375000000000D     -07 0.000000000000D+00`
  - fixture: `     2.482800632000D+04-4.681250000000D-04-1.375000000000D-07 0.000000000000D+00`
- rinex305.txt line 4645, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -3.409035992000D+04      -1.518125000000D    -03-3.750000000000D     -08 4.000000000000D+00`
  - fixture: `    -3.409035992000D+04-1.518125000000D-03-3.750000000000D-08 4.000000000000D+00`
- rinex305.txt line 4646, p. 82: blanks inserted by the extraction removed; line restored from the same line of 3.04/a17_nav_sbas.rnx.
  - printed: `    -1.584240000000D+01       8.960000000000D    -04 6.250000000000D     -08 2.600000000000D+01`
  - fixture: `    -1.584240000000D+01 8.960000000000D-04 6.250000000000D-08 2.600000000000D+01`

**3.05/a19_nav_irnss.rnx**

- rinex305.txt line 4822, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `    -1.898035407066e    -05 2.257102518342e     -03-1.068413257599e    -05 6.493487739563e+03`
  - fixture: `    -1.898035407066e-05 2.257102518342e-03-1.068413257599e-05 6.493487739563e+03`
- rinex305.txt line 4823, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `     1.728000000000e+05 6.705522537231e         -08-8.912102146884e    -01-5.215406417847e     -08`
  - fixture: `     1.728000000000e+05 6.705522537231e-08-8.912102146884e-01-5.215406417847e-08`
- rinex305.txt line 4829, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `     1.000000000000e+00-5.101875000000e+02 4.945920303147e-09-8.741766987741e                  -01`
  - fixture: `     1.000000000000e+00-5.101875000000e+02 4.945920303147e-09-8.741766987741e-01`
- rinex305.txt line 4830, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `    -1.684948801994e-05 2.254169434309e-03-1.182407140732e             -05 6.493469217300e+03`
  - fixture: `    -1.684948801994e-05 2.254169434309e-03-1.182407140732e-05 6.493469217300e+03`
- rinex305.txt line 4831, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `     1.800000000000e+05 2.346932888031e         -07-8.912408598963e    -01-1.117587089539e     -08`
  - fixture: `     1.800000000000e+05 2.346932888031e-07-8.912408598963e-01-1.117587089539e-08`
- rinex305.txt line 4837, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `     2.000000000000e+00-5.100000000000e+02 5.217360181136e-09-3.491339518362e                  -01`
  - fixture: `     2.000000000000e+00-5.100000000000e+02 5.217360181136e-09-3.491339518362e-01`
- rinex305.txt line 4838, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `    -1.697987318039e-05 2.254509832710e-03-1.2125819            92149e-05 6.493469842911e+03`
  - fixture: `    -1.697987318039e-05 2.254509832710e-03-1.212581992149e-05 6.493469842911e+03`
- rinex305.txt line 4839, p. 85: blanks inserted by the extraction removed; line restored from the same line of 3.04/a19_nav_irnss.rnx.
  - printed: `     1.872000000000e+05 1.378357410431e         -07-8.912725364615e    -01 2.942979335785e     -07`
  - fixture: `     1.872000000000e+05 1.378357410431e-07-8.912725364615e-01 2.942979335785e-07`

**3.05/a22_met.rnx**

- rinex305.txt line 4976, p. 87: restored from the same line of 3.04/a22_met.rnx.
  - printed: `     3    PR    TD    HR                                                 # / TYPES OF OBSERV`
  - fixture: `     3    PR    TD    HR                                    # / TYPES OF OBSERV`
- rinex305.txt line 4978, p. 87: restored from the same line of 3.04/a22_met.rnx.
  - printed: `HAENNI                                                       0.1    TD SENSOR MOD/TYPE/ACC`
  - fixture: `HAENNI                                            0.1    TD SENSOR MOD/TYPE/ACC`
- rinex305.txt line 4979, p. 87: restored from the same line of 3.04/a22_met.rnx.
  - printed: `ROTRONIC                I-240W                               5.0    HR SENSOR MOD/TYPE/ACC`
  - fixture: `ROTRONIC            I-240W                        5.0    HR SENSOR MOD/TYPE/ACC`
- rinex305.txt line 4980, p. 87: restored from the same line of 3.04/a22_met.rnx.
  - printed: `        0.0000             0.0000        0.0000     1234.5678 PR SENSOR POS XYZ/H`
  - fixture: `        0.0000        0.0000        0.0000     1234.5678 PR SENSOR POS XYZ/H`
- rinex305.txt line 4981, p. 87: restored from the same line of 3.04/a22_met.rnx.
  - printed: `                                                                         END OF HEADER`
  - fixture: `                                                            END OF HEADER`

**3.05/a4_obs_example1.rnx**

- rinex305.txt line 3413, p. 62: event flag and record count printed 7 columns right of cols 32-35 (flag at col 39); the same record is at col 32 in 3.02-3.04 and 4.02, and other lines of this table carry blanks inserted by the extraction, so read as extraction damage.
  - printed: `>                                     4  1`
  - fixture: `>                              4  1`
- rinex305.txt line 3347, p. 61: restored from the same line of 3.04/a4_obs_example1.rnx.
  - printed: ` 18 R01  1 R02  2 R03  3 R04  4 R05  5 R06 -6 R07 -5 R08 -4 GLONASS                 SLOT / FRQ #`
  - fixture: ` 18 R01  1 R02  2 R03  3 R04  4 R05  5 R06 -6 R07 -5 R08 -4 GLONASS SLOT / FRQ #`
- rinex305.txt line 3349, p. 61: restored from the same line of 3.04/a4_obs_example1.rnx.
  - printed: `    R17  5 R18 -5                                                         GLONASS   SLOT / FRQ #`
  - fixture: `    R17  5 R18 -5                                           GLONASS SLOT / FRQ #`
- rinex305.txt line 3351, p. 61: restored from the same line of 3.04/a4_obs_example1.rnx.
  - printed: `G L1W  0.00000                                                            SYS / PHASE SHIFT`
  - fixture: `G L1W  0.00000                                              SYS / PHASE SHIFT`
- rinex305.txt line 3354, p. 61: restored from the same line of 3.04/a4_obs_example1.rnx.
  - printed: `E L1B                                                                     SYS / PHASE SHIFT`
  - fixture: `E L1B                                                       SYS / PHASE SHIFT`
- rinex305.txt line 3357, p. 61: restored from the same line of 3.04/a4_obs_example1.rnx.
  - printed: ` C1C  -10.000 C1P      -10.123 C2C     -10.432 C2P     -10.634           GLONASS    COD/PHS/BIS`
  - fixture: ` C1C  -10.000 C1P  -10.123 C2C  -10.432 C2P  -10.634        GLONASS COD/PHS/BIS`
- rinex305.txt line 3358, p. 61: restored from the same line of 3.04/a4_obs_example1.rnx.
  - printed: `                                                                          END OF HEADER`
  - fixture: `                                                            END OF HEADER`
- rinex305.txt line 3409, p. 62: restored from the same line of 3.04/a4_obs_example1.rnx.
  - printed: `           *** LOST LOCK ON G 06                                          COMMENT`
  - fixture: `           *** LOST LOCK ON G 06                            COMMENT`

**3.05/a4_obs_example3.rnx**

- rinex305.txt line 3541, p. 64: blanks inserted/shifted by the extraction; restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `       24-29dBHz     -> 4; 30-35dBHz -> 5; 36-41dBHz -> 6       COMMENT`
  - fixture: `       24-29dBHz -> 4; 30-35dBHz -> 5; 36-41dBHz -> 6       COMMENT`
- rinex305.txt line 3547, p. 64: blanks inserted/shifted by the extraction; restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `                         LEIAS10         NONE                    ANT # / TYPE`
  - fixture: `                    LEIAS10         NONE                    ANT # / TYPE`
- rinex305.txt line 3551, p. 64: blanks inserted/shifted by the extraction; restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `        L5Q D5Q S5Q                                          SYS / # / OBS TYPES`
  - fixture: `       L5Q D5Q S5Q                                          SYS / # / OBS TYPES`
- rinex305.txt line 3554, p. 64: blanks inserted/shifted by the extraction; restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `        L8Q D8Q S8Q                                          SYS / # / OBS TYPES`
  - fixture: `       L8Q D8Q S8Q                                          SYS / # / OBS TYPES`
- rinex305.txt line 3542, p. 64: restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `        42-47dBHz    -> 7; 48-53dBHz -> 8; >= 54dBHz         -> 9       COMMENT`
  - fixture: `       42-47dBHz -> 7; 48-53dBHz -> 8; >= 54dBHz -> 9       COMMENT`
- rinex305.txt line 3543, p. 64: restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `Tokio                                                                     MARKER NAME`
  - fixture: `Tokio                                                       MARKER NAME`
- rinex305.txt line 3546, p. 64: restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `1870023             LEICA GR25                   3.08/6.401          REC # / TYPE / VERS`
  - fixture: `1870023             LEICA GR25          3.08/6.401          REC # / TYPE / VERS`
- rinex305.txt line 3549, p. 64: restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `        0.0000        0.0000        0.0000                                ANTENNA: DELTA H/E/N`
  - fixture: `        0.0000        0.0000        0.0000                  ANTENNA: DELTA H/E/N`
- rinex305.txt line 3552, p. 64: restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `R   12 C1C L1C D1C S1C C2P L2P D2P S2P C2C L2C D2C S2C      SYS / # / OBS T                  YPES`
  - fixture: `R   12 C1C L1C D1C S1C C2P L2P D2P S2P C2C L2C D2C S2C      SYS / # / OBS TYPES`
- rinex305.txt line 3556, p. 64: restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `J   12 C1C   L1C D1C S1C C2S L2S D2S S2S C5Q L5Q D5Q S5Q      SYS / # / OBS TYPES`
  - fixture: `J   12 C1C L1C D1C S1C C2S L2S D2S S2S C5Q L5Q D5Q S5Q      SYS / # / OBS TYPES`
- rinex305.txt line 3559, p. 64: restored from the same line of 3.04/a4_obs_example3.rnx.
  - printed: `     1.000                                                                INTERVAL`
  - fixture: `     1.000                                                  INTERVAL`

**3.05/a7_nav_gps.rnx**

- rinex305.txt line 3907, p. 70: restored from the same line of 3.04/a7_nav_gps.rnx.
  - printed: `     3.05           N: GNSS NAV DATA    G: GPS                            RINEX VERSION / TYPE`
  - fixture: `     3.05           N: GNSS NAV DATA    G: GPS              RINEX VERSION / TYPE`
- rinex305.txt line 3911, p. 70: restored from the same line of 3.04/a7_nav_gps.rnx.
  - printed: `GPUT   .1331791282D-06  .107469589D        -12 552960 1025   G12  2 TIME SYSTEM CORR`
  - fixture: `GPUT   .1331791282D-06  .107469589D-12 552960 1025   G12  2 TIME SYSTEM CORR`
- rinex305.txt line 3914, p. 70: blanks inserted by the extraction removed; line restored from the same line of 3.04/a7_nav_gps.rnx.
  - printed: `G06 1999 09 02 17 51 44 -.839701388031D-03 -.165982783074D              -10  .000000000000D+00`
  - fixture: `G06 1999 09 02 17 51 44 -.839701388031D-03 -.165982783074D-10  .000000000000D+00`

**3.05/a9_nav_mixed_galileo.rnx**

- rinex305.txt line 4107, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `BDUT  5.5879354477e-09-2.042810365e        -14     14  492   B10  7 TIME SYSTEM CORR`
  - fixture: `BDUT  5.5879354477e-09-2.042810365e-14     14  492   B10  7 TIME SYSTEM CORR`
- rinex305.txt line 4108, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `GAUT  3.7252902985e    -09 5.329070518e    -15 345600 1849   E10  5 TIME SYSTEM CORR`
  - fixture: `GAUT  3.7252902985e-09 5.329070518e-15 345600 1849   E10  5 TIME SYSTEM CORR`
- rinex305.txt line 4109, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `GLGP -3.7252902985e    -09 0.000000000e+00 345600 1849   R10  0 TIME            SYSTEM CORR`
  - fixture: `GLGP -3.7252902985e-09 0.000000000e+00 345600 1849   R10  0 TIME SYSTEM CORR`
- rinex305.txt line 4110, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `GLUT  1.0710209608e    -08 0.000000000e+00 345600 1849   R10  0 TIME SYSTEM CORR`
  - fixture: `GLUT  1.0710209608e-08 0.000000000e+00 345600 1849   R10  0 TIME SYSTEM CORR`
- rinex305.txt line 4111, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `GAGP -2.0081643015e    -09-9.769962617e    -15 432000 1849   E12  0 TIME SYSTEM CORR`
  - fixture: `GAGP -2.0081643015e-09-9.769962617e-15 432000 1849   E12  0 TIME SYSTEM CORR`
- rinex305.txt line 4112, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `GPUT  4.5110937208e    -09 7.105427358e    -15 372608 1849   G10  2 TIME SYSTEM CORR`
  - fixture: `GPUT  4.5110937208e-09 7.105427358e-15 372608 1849   G10  2 TIME SYSTEM CORR`
- rinex305.txt line 4113, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `QZUT  1.9557774067e    -08 1.598721155e    -14  61440 1850   J01  0 TIME SYSTEM CORR`
  - fixture: `QZUT  1.9557774067e-08 1.598721155e-14  61440 1850   J01  0 TIME SYSTEM CORR`
- rinex305.txt line 4115, p. 73: restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `                                                                          END OF HEADER`
  - fixture: `                                                            END OF HEADER`
- rinex305.txt line 4116, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `E12 2015 06 19 02 10 00     -1.383925089613e    -03-1.314646169703e     -10 0.000000000000e+00`
  - fixture: `E12 2015 06 19 02 10 00-1.383925089613e-03-1.314646169703e-10 0.000000000000e+00`
- rinex305.txt line 4117, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `     9.300000000000e+01     -1.655312500000e+02 2.857976189037e         -09 1.382758884589e+00`
  - fixture: `     9.300000000000e+01-1.655312500000e+02 2.857976189037e-09 1.382758884589e+00`
- rinex305.txt line 4118, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `    -7.824972271919e     -06 3.466791240498e    -04 1.143850386143e     -05 5.440625097275e+03`
  - fixture: `    -7.824972271919e-06 3.466791240498e-04 1.143850386143e-05 5.440625097275e+03`
- rinex305.txt line 4119, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `     4.398000000000e+05 2.980232238770e         -08-2.961851013120e+00      -1.117587089539e   -08`
  - fixture: `     4.398000000000e+05 2.980232238770e-08-2.961851013120e+00-1.117587089539e-08`
- rinex305.txt line 4120, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `     9.656832940254e-01 9.937500000000e+01-6.293609760051e-01-5.415939881349e                  -09`
  - fixture: `     9.656832940254e-01 9.937500000000e+01-6.293609760051e-01-5.415939881349e-09`
- rinex305.txt line 4122, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `     3.120000000000e+00 0.000000000000e+00-6.519258022308e-09-6.053596735001e                  -09`
  - fixture: `     3.120000000000e+00 0.000000000000e+00-6.519258022308e-09-6.053596735001e-09`
- rinex305.txt line 4124, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `E12 2015 06 19 02 10 00-1.383925322443e-03-1.314504061156e              -10 0.000000000000e+00`
  - fixture: `E12 2015 06 19 02 10 00-1.383925322443e-03-1.314504061156e-10 0.000000000000e+00`
- rinex305.txt line 4125, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `     9.300000000000e+01     -1.655312500000e+02 2.857976189037e         -09 1.382758884589e+00`
  - fixture: `     9.300000000000e+01-1.655312500000e+02 2.857976189037e-09 1.382758884589e+00`
- rinex305.txt line 4126, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `    -7.824972271919e     -06 3.466791240498e    -04 1.143850386143e     -05 5.440625097275e+03`
  - fixture: `    -7.824972271919e-06 3.466791240498e-04 1.143850386143e-05 5.440625097275e+03`
- rinex305.txt line 4127, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `     4.398000000000e+05 2.980232238770e         -08-2.961851013120e+00      -1.117587089539e   -08`
  - fixture: `     4.398000000000e+05 2.980232238770e-08-2.961851013120e+00-1.117587089539e-08`
- rinex305.txt line 4128, p. 73: blanks inserted by the extraction removed; line restored from the same line of 3.04/a9_nav_mixed_galileo.rnx.
  - printed: `     9.656832940254e-01 9.937500000000e+01-6.293609760051e-01-5.415939881349e                  -09`
  - fixture: `     9.656832940254e-01 9.937500000000e+01-6.293609760051e-01-5.415939881349e-09`

**4.00/a12_nav_gps.rnx**

- rinex_4.00.txt line 4297, p. 77: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_gps.rnx.
  - printed: `     0.000000000000e+00 7.000000000000e+00          -8.789356797934e    -09 5.000000000000e+00`
  - fixture: `     0.000000000000e+00 7.000000000000e+00-8.789356797934e-09 5.000000000000e+00`
- rinex_4.00.txt line 4298, p. 77: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_gps.rnx.
  - printed: `    -5.820766091347e     -10-6.606569513679e-09-1.178705133498e         -08-1.178705133498e     -08`
  - fixture: `    -5.820766091347e-10-6.606569513679e-09-1.178705133498e-08-1.178705133498e-08`
- rinex_4.00.txt line 4307, p. 77: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_gps.rnx.
  - printed: `     0.000000000000e+00 1.000000000000e+00          -8.789356797934e    -09 5.000000000000e+00`
  - fixture: `     0.000000000000e+00 1.000000000000e+00-8.789356797934e-09 5.000000000000e+00`
- rinex_4.00.txt line 4309, p. 77: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_gps.rnx.
  - printed: `    -3.492459654808e     -10-7.858034223318e-10`
  - fixture: `    -3.492459654808e-10-7.858034223318e-10`

**4.00/a14_nav_galileo.rnx**

- rinex_4.00.txt line 4452, p. 80: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_galileo.rnx.
  - printed: `E12 2020 09 15 00 40 00 5.605182959698e-03-1.881517164293e               -11 0.000000000000e+     00`
  - fixture: `E12 2020 09 15 00 40 00 5.605182959698e-03-1.881517164293e-11 0.000000000000e+00`
- rinex_4.00.txt line 4454, p. 80: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_galileo.rnx.
  - printed: `     5.209818482399e     -06 1.468013506383e     -04 1.532956957817e     -06 5.440609727859e+03`
  - fixture: `     5.209818482399e-06 1.468013506383e-04 1.532956957817e-06 5.440609727859e+03`
- rinex_4.00.txt line 4455, p. 80: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_galileo.rnx.
  - printed: `     1.752000000000e+05      -1.676380634308e    -08 8.103706855689e     -01 7.450580596924e    -09`
  - fixture: `     1.752000000000e+05-1.676380634308e-08 8.103706855689e-01 7.450580596924e-09`
- rinex_4.00.txt line 4456, p. 80: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_galileo.rnx.
  - printed: `     9.891660140720e-01 3.219375000000e+02 5.171049929386e-01-5.815956543649e                   -09`
  - fixture: `     9.891660140720e-01 3.219375000000e+02 5.171049929386e-01-5.815956543649e-09`
- rinex_4.00.txt line 4458, p. 80: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_galileo.rnx.
  - printed: `     3.120000000000e+00 0.000000000000e+00-1.303851604462e-08-1.280568540096e                   -08`
  - fixture: `     3.120000000000e+00 0.000000000000e+00-1.303851604462e-08-1.280568540096e-08`
- rinex_4.00.txt line 4462, p. 80: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_galileo.rnx.
  - printed: `     4.500000000000e+01 1.730312500000e+02 2.871548182937e-09-1.103934352668e                   -01`
  - fixture: `     4.500000000000e+01 1.730312500000e+02 2.871548182937e-09-1.103934352668e-01`
- rinex_4.00.txt line 4464, p. 80: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_galileo.rnx.
  - printed: `     2.574000000000e+05-5.774199962616e-08 8.098963343817e-01-1.005828380585e                   -07`
  - fixture: `     2.574000000000e+05-5.774199962616e-08 8.098963343817e-01-1.005828380585e-07`

**4.00/a20_nav_qzss.rnx**

- rinex_4.00.txt line 4951, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `J01 2021 01 23 02 00 00-3.374307416379e-04-1.364242052659e               -12 0.000000000000e+00`
  - fixture: `J01 2021 01 23 02 00 00-3.374307416379e-04-1.364242052659e-12 0.000000000000e+00`
- rinex_4.00.txt line 4952, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     1.330000000000e+02 9.578125000000e+01 1.388272112820e               -09-2.070362217868e+00`
  - fixture: `     1.330000000000e+02 9.578125000000e+01 1.388272112820e-09-2.070362217868e+00`
- rinex_4.00.txt line 4953, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     2.535060048103e     -06 7.562357175630e     -02 5.446374416351e     -06 6.493648595810e+03`
  - fixture: `     2.535060048103e-06 7.562357175630e-02 5.446374416351e-06 6.493648595810e+03`
- rinex_4.00.txt line 4954, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     5.256000000000e+05      -1.164153218269e-06 4.173927833877e         -01-3.390014171600e     -06`
  - fixture: `     5.256000000000e+05-1.164153218269e-06 4.173927833877e-01-3.390014171600e-06`
- rinex_4.00.txt line 4960, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e               -12 0.000000000000e+00`
  - fixture: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e-12 0.000000000000e+00`
- rinex_4.00.txt line 4961, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `    -2.224636077881e     -02 9.925390625000e+01 2.809759894921e          -09-2.070460582285e+00`
  - fixture: `    -2.224636077881e-02 9.925390625000e+01 2.809759894921e-09-2.070460582285e+00`
- rinex_4.00.txt line 4962, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     2.630054950714e     -06 7.561515661655e     -02 6.853602826595e     -06 6.493646338351e+03`
  - fixture: `     2.630054950714e-06 7.561515661655e-02 6.853602826595e-06 6.493646338351e+03`
- rinex_4.00.txt line 4963, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     5.256000000000e+05 2.942979335785e          -07 4.174090012975e     -01 2.151355147362e     -07`
  - fixture: `     5.256000000000e+05 2.942979335785e-07 4.174090012975e-01 2.151355147362e-07`
- rinex_4.00.txt line 4966, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `    -8.000000000000e+00 0.000000000000e+00           -5.675246939063e    -09 0.000000000000e+00`
  - fixture: `    -8.000000000000e+00 0.000000000000e+00-5.675246939063e-09 0.000000000000e+00`
- rinex_4.00.txt line 4967, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     0.000000000000e+00 3.667082637548e          -09 2.561137080193e     -09 1.949956640601e     -09`
  - fixture: `     0.000000000000e+00 3.667082637548e-09 2.561137080193e-09 1.949956640601e-09`
- rinex_4.00.txt line 4970, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e               -12 0.000000000000e+00`
  - fixture: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e-12 0.000000000000e+00`
- rinex_4.00.txt line 4971, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `    -2.224636077881e     -02 9.925390625000e+01 2.8       09759894921e   -09-2.070460582285e+00`
  - fixture: `    -2.224636077881e-02 9.925390625000e+01 2.809759894921e-09-2.070460582285e+00`
- rinex_4.00.txt line 4972, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     2.630054950714e     -06 7.561515661655e     -02 6.853602826595e     -06 6.493646338351e+03`
  - fixture: `     2.630054950714e-06 7.561515661655e-02 6.853602826595e-06 6.493646338351e+03`
- rinex_4.00.txt line 4973, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     5.256000000000e+05 2.942979335785e          -07 4.174090012975e     -01 2.151355147362e     -07`
  - fixture: `     5.256000000000e+05 2.942979335785e-07 4.174090012975e-01 2.151355147362e-07`
- rinex_4.00.txt line 4974, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     7.304471282263e-01-5.480078125000e+01-1.559404111189e+00-2.726307082255e                    -09`
  - fixture: `     7.304471282263e-01-5.480078125000e+01-1.559404111189e+00-2.726307082255e-09`
- rinex_4.00.txt line 4976, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `    -8.000000000000e+00 0.000000000000e+00           -5.675246939063e    -09 0.000000000000e+00`
  - fixture: `    -8.000000000000e+00 0.000000000000e+00-5.675246939063e-09 0.000000000000e+00`
- rinex_4.00.txt line 4977, p. 88: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_qzss.rnx.
  - printed: `     0.000000000000e+00 3.667082637548e          -09 2.561137080193e     -09 1.94995664    0601e-09`
  - fixture: `     0.000000000000e+00 3.667082637548e-09 2.561137080193e-09 1.949956640601e-09`

**4.00/a25_nav_beidou.rnx**

- rinex_4.00.txt line 5456, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `C05 2021 07 05 22 00 00     -5.836377386004e    -05 1.694644424788e     -11 0.000000000000e+00`
  - fixture: `C05 2021 07 05 22 00 00-5.836377386004e-05 1.694644424788e-11 0.000000000000e+00`
- rinex_4.00.txt line 5457, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     0.000000000000e+00     -5.881250000000e+01 1.949724070976e         -09-1.593114605012e+0     0`
  - fixture: `     0.000000000000e+00-5.881250000000e+01 1.949724070976e-09-1.593114605012e+00`
- rinex_4.00.txt line 5458, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `    -1.817941665649e     -06 7.691901409999e    -04 1.800991594791e     -05 6.493525815964e+03`
  - fixture: `    -1.817941665649e-06 7.691901409999e-04 1.800991594791e-05 6.493525815964e+03`
- rinex_4.00.txt line 5459, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     1.656000000000e+05 2.072192728519e         -07 2.624951167227e+00      -1.122243702412e    -07`
  - fixture: `     1.656000000000e+05 2.072192728519e-07 2.624951167227e+00-1.122243702412e-07`
- rinex_4.00.txt line 5460, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     1.151558582809e-01-5.497031250000e+02-4.954214719500e-01-8.100337411567e                   -10`
  - fixture: `     1.151558582809e-01-5.497031250000e+02-4.954214719500e-01-8.100337411567e-10`
- rinex_4.00.txt line 5466, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     1.000000000000e+00-2.265625000000e+00 4.092313318419e-09-1.556359938124e                   -01`
  - fixture: `     1.000000000000e+00-2.265625000000e+00 4.092313318419e-09-1.556359938124e-01`
- rinex_4.00.txt line 5468, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     9.360000000000e+04 2.328306436539e-09-2.772255179876e+              00-1.164153218269e     -08`
  - fixture: `     9.360000000000e+04 2.328306436539e-09-2.772255179876e+00-1.164153218269e-08`
- rinex_4.00.txt line 5469, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     9.665781566257e-01 2.337656250000e+02-6.218441883865e-01-6.809926517917e                   -09`
  - fixture: `     9.665781566257e-01 2.337656250000e+02-6.218441883865e-01-6.809926517917e-09`
- rinex_4.00.txt line 5476, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     7.729977369308e     -08 8.434175979346e    -04 7.596798241138e     -06 5.282624978926e+03`
  - fixture: `     7.729977369308e-08 8.434175979346e-04 7.596798241138e-06 5.282624978926e+03`
- rinex_4.00.txt line 5477, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     1.656000000000e+05     -4.190951585770e    -08-2.772741033988e+00      -2.514570951462e    -08`
  - fixture: `     1.656000000000e+05-4.190951585770e-08-2.772741033988e+00-2.514570951462e-08`
- rinex_4.00.txt line 5478, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     9.666057809078e-01 2.101328125000e+02-6.122205141961e-01-6.644205329250e                   -09`
  - fixture: `     9.666057809078e-01 2.101328125000e+02-6.122205141961e-01-6.644205329250e-09`
- rinex_4.00.txt line 5481, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `    -3.492459654808e-10                    2.328306436539e-08-2.968590706587e                   -09`
  - fixture: `    -3.492459654808e-10                    2.328306436539e-08-2.968590706587e-09`
- rinex_4.00.txt line 5487, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     0.000000000000e+00       8.432919275947e   -04 7.565133273602e     -06 5.282623812254e+03`
  - fixture: `     0.000000000000e+00 8.432919275947e-04 7.565133273602e-06 5.282623812254e+03`
- rinex_4.00.txt line 5488, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     1.692000000000e+05     -4.656612873077e    -08-2.772764954893e+00      -3.632158041000e    -08`
  - fixture: `     1.692000000000e+05-4.656612873077e-08-2.772764954893e+00-3.632158041000e-08`
- rinex_4.00.txt line 5489, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     9.666074588748e-01 2.102968750000e+02-6.120578881764e-01-6.652598536003e                   -09`
  - fixture: `     9.666074588748e-01 2.102968750000e+02-6.120578881764e-01-6.652598536003e-09`
- rinex_4.00.txt line 5492, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `                       -2.502929419279e-09 2.328306436539e-08-2.968590706587e                   -09`
  - fixture: `                       -2.502929419279e-09 2.328306436539e-08-2.968590706587e-09`
- rinex_4.00.txt line 5498, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `    -6.891787052155e     -08 8.444703416899e    -04 6.626360118389e     -06 5.282619899994e+03`
  - fixture: `    -6.891787052155e-08 8.444703416899e-04 6.626360118389e-06 5.282619899994e+03`
- rinex_4.00.txt line 5499, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     8.6400000000    00e+04 3.725290298462e     -08-2.772205880999e+00 0.000000000000e+00`
  - fixture: `     8.640000000000e+04 3.725290298462e-08-2.772205880999e+00 0.000000000000e+00`
- rinex_4.00.txt line 5500, p. 97: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_beidou.rnx.
  - printed: `     9.665752168918e     -01 2.300390625000e+02     -6.230324874839e    -01-6.829570193298e     -09`
  - fixture: `     9.665752168918e-01 2.300390625000e+02-6.230324874839e-01-6.829570193298e-09`

**4.00/a27_nav_sbas.rnx**

- rinex_4.00.txt line 5588, p. 99: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sbas.rnx.
  - printed: `S28 2020 09 15 23 56 48 5.075708031654e-08-2.091837814078e              -11 2.589840000000e+0      5`
  - fixture: `S28 2020 09 15 23 56 48 5.075708031654e-08-2.091837814078e-11 2.589840000000e+05`
- rinex_4.00.txt line 5589, p. 99: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sbas.rnx.
  - printed: `     5.159782400000e+03 7.125000000000e          -04-2.500000000000e    -08 0.000000000000e+00`
  - fixture: `     5.159782400000e+03 7.125000000000e-04-2.500000000000e-08 0.000000000000e+00`
- rinex_4.00.txt line 5590, p. 99: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sbas.rnx.
  - printed: `     4.185231736000e+04      -2.462500000000e    -04-3.750000000000e    -08 4.096000000000e+03`
  - fixture: `     4.185231736000e+04-2.462500000000e-04-3.750000000000e-08 4.096000000000e+03`
- rinex_4.00.txt line 5591, p. 99: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sbas.rnx.
  - printed: `    -8.261200000000e+00      -1.328000000000e    -03 6.250000000000e    -08 1.200000000000e+01`
  - fixture: `    -8.261200000000e+00-1.328000000000e-03 6.250000000000e-08 1.200000000000e+01`
- rinex_4.00.txt line 5594, p. 99: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sbas.rnx.
  - printed: `    -3.228075088000e+04 1.990000000000e-03-1.375000000000e              -07 1.000000000000e+00`
  - fixture: `    -3.228075088000e+04 1.990000000000e-03-1.375000000000e-07 1.000000000000e+00`
- rinex_4.00.txt line 5595, p. 99: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sbas.rnx.
  - printed: `     2.711642576000e+04      -1.374375000000e    -03-1.000000000000e    -07 3.276700000000e+04`
  - fixture: `     2.711642576000e+04-1.374375000000e-03-1.000000000000e-07 3.276700000000e+04`
- rinex_4.00.txt line 5596, p. 99: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sbas.rnx.
  - printed: `    -1.045603600000e+03      -3.671600000000e    -02 2.750000000000e    -06 5.900000000000e+01`
  - fixture: `    -1.045603600000e+03-3.671600000000e-02 2.750000000000e-06 5.900000000000e+01`

**4.00/a29_nav_navic.rnx**

- rinex_4.00.txt line 5745, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_navic.rnx.
  - printed: `     1.690000000000e+02-5.793750000000e+02 4.834487090078e-09-4.281979621524e                    -01`
  - fixture: `     1.690000000000e+02-5.793750000000e+02 4.834487090078e-09-4.281979621524e-01`
- rinex_4.00.txt line 5746, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_navic.rnx.
  - printed: `    -1.904368400574e-05 2.015684265643e-03-3.430992364883e               -06 6.493289550781e+03`
  - fixture: `    -1.904368400574e-05 2.015684265643e-03-3.430992364883e-06 6.493289550781e+03`
- rinex_4.00.txt line 5747, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_navic.rnx.
  - printed: `     1.803360000000e+05 2.49594449996          9e-07-1.337499015334e+00 7.450580596924e          -08`
  - fixture: `     1.803360000000e+05 2.495944499969e-07-1.337499015334e+00 7.450580596924e-08`
- rinex_4.00.txt line 5754, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_navic.rnx.
  - printed: `     1.700000000000e+02-5.798125000000e+02 4.847344768509e-09-3.616804200470e                    -01`
  - fixture: `     1.700000000000e+02-5.798125000000e+02 4.847344768509e-09-3.616804200470e-01`
- rinex_4.00.txt line 5755, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_navic.rnx.
  - printed: `    -1.905485987663e-05 2.015971462242e-03-3.460794687271e               -06 6.493290285110e+03`
  - fixture: `    -1.905485987663e-05 2.015971462242e-03-3.460794687271e-06 6.493290285110e+03`
- rinex_4.00.txt line 5756, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_navic.rnx.
  - printed: `     1.812480000000e+05 2.346932888031e          -07-1.337503058840e+00 8.568167686462e          -08`
  - fixture: `     1.812480000000e+05 2.346932888031e-07-1.337503058840e+00 8.568167686462e-08`

**4.00/a35_nav_sto_eop_ion.rnx**

- rinex_4.00.txt line 6048, p. 106: blanks inserted/shifted by the extraction; restored from the same line of 4.01/a35_nav_sto_eop_ion.rnx.
  - printed: `> STO I02   LNAV`
  - fixture: `> STO I02 LNAV`
- rinex_4.00.txt line 6051, p. 106: blanks inserted/shifted by the extraction; restored from the same line of 4.01/a35_nav_sto_eop_ion.rnx.
  - printed: `> STO I02   LNAV`
  - fixture: `> STO I02 LNAV`
- rinex_4.00.txt line 6054, p. 106: blanks inserted/shifted by the extraction; restored from the same line of 4.01/a35_nav_sto_eop_ion.rnx.
  - printed: `> STO J02   LNAV`
  - fixture: `> STO J02 LNAV`
- rinex_4.00.txt line 6081, p. 107: blanks inserted/shifted by the extraction; restored from the same line of 4.01/a35_nav_sto_eop_ion.rnx.
  - printed: `> EOP C20   CNVX`
  - fixture: `> EOP C20 CNVX`
- rinex_4.00.txt line 6085, p. 107: blanks inserted/shifted by the extraction; restored from the same line of 4.01/a35_nav_sto_eop_ion.rnx.
  - printed: `> EOP J01   CNVX`
  - fixture: `> EOP J01 CNVX`
- rinex_4.00.txt line 6044, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     2.532240000000e+05 9.895302355289e-10-1.154631945610e              -14 0.000000000000e+00`
  - fixture: `     2.532240000000e+05 9.895302355289e-10-1.154631945610e-14 0.000000000000e+00`
- rinex_4.00.txt line 6047, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     2.173000000000e+05 2.299202606082e         -09 0.000000000000e+00 0.000000000000e+00`
  - fixture: `     2.173000000000e+05 2.299202606082e-09 0.000000000000e+00 0.000000000000e+00`
- rinex_4.00.txt line 6049, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 00 04 48 IRUT                                                 UTCIRN`
  - fixture: `    2020 09 15 00 04 48 IRUT                                  UTCIRN`
- rinex_4.00.txt line 6050, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     1.731720000000e+05     -8.614733815193e    -09-1.776356839400e     -15 0.000000000000e+00`
  - fixture: `     1.731720000000e+05-8.614733815193e-09-1.776356839400e-15 0.000000000000e+00`
- rinex_4.00.txt line 6052, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 00 04 48 IRUT                                                 UTC(NPLI)`
  - fixture: `    2020 09 15 00 04 48 IRUT                                  UTC(NPLI)`
- rinex_4.00.txt line 6053, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     1.732200000000e+05 2.619344741106e         -10 3.996802888651e     -15 0.000000000000e+00`
  - fixture: `     1.732200000000e+05 2.619344741106e-10 3.996802888651e-15 0.000000000000e+00`
- rinex_4.00.txt line 6055, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 18 02 52 48 QZUT                                                 UTC(NICT)`
  - fixture: `    2020 09 18 02 52 48 QZUT                                  UTC(NICT)`
- rinex_4.00.txt line 6056, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     1.837140000000e+05     -9.313225746155e    -10 0.000000000000e+00 0.000000000         000e+00`
  - fixture: `     1.837140000000e+05-9.313225746155e-10 0.000000000000e+00 0.000000000000e+00`
- rinex_4.00.txt line 6059, p. 106: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     1.714860000000e+05     -3.768946044147e    -08-3.730349362741e     -13-2.168404344971e     -19`
  - fixture: `     1.714860000000e+05-3.768946044147e-08-3.730349362741e-13-2.168404344971e-19`
- rinex_4.00.txt line 6078, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 18 19 56 48 2.070846557617e-01-2.679824829102e              -04 0.000000000000e     +00`
  - fixture: `    2020 09 18 19 56 48 2.070846557617e-01-2.679824829102e-04 0.000000000000e+00`
- rinex_4.00.txt line 6079, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `                              3.392457962036e    -01-1.400947570801e    -03 0.000000000000e+00`
  - fixture: `                        3.392457962036e-01-1.400947570801e-03 0.000000000000e+00`
- rinex_4.00.txt line 6080, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     2.532480000000e+05     -1.759799122810e     -01-7.975101470947e    -05 0.000000000000e+00`
  - fixture: `     2.532480000000e+05-1.759799122810e-01-7.975101470947e-05 0.000000000000e+00`
- rinex_4.00.txt line 6082, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 00 00 00 2.084112167358e          -01-3.948211669922e    -04 0.000000000000e+00`
  - fixture: `    2020 09 15 00 00 00 2.084112167358e-01-3.948211669922e-04 0.000000000000e+00`
- rinex_4.00.txt line 6083, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `                              3.408145904541e    -01-1.317977905273e    -03 0.000000000000e+00`
  - fixture: `                        3.408145904541e-01-1.317977905273e-03 0.000000000000e+00`
- rinex_4.00.txt line 6084, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     1.749900000000e+05     -1.752023100853e     -01 2.140104770660e    -04 0.000000000000e+00`
  - fixture: `     1.749900000000e+05-1.752023100853e-01 2.140104770660e-04 0.000000000000e+00`
- rinex_4.00.txt line 6086, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 01 00 00 2.082471847534e          -01-6.551742553711e    -04 0.000000000000e+00`
  - fixture: `    2020 09 15 01 00 00 2.082471847534e-01-6.551742553711e-04 0.000000000000e+00`
- rinex_4.00.txt line 6087, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `                              3.444433212280e    -01-9.121894836426e    -04 0.000000000000e+00`
  - fixture: `                        3.444433212280e-01-9.121894836426e-04 0.000000000000e+00`
- rinex_4.00.txt line 6088, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `     1.729860000000e+05     -1.754972934723e     -01 5.635917186737e    -04 0.000000000000e+00`
  - fixture: `     1.729860000000e+05-1.754972934723e-01 5.635917186737e-04 0.000000000000e+00`
- rinex_4.00.txt line 6091, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2021 07 05 23 30 42 7.450580596924e-09 2.235174179077e-08-5.960464477539e                   -08`
  - fixture: `    2021 07 05 23 30 42 7.450580596924e-09 2.235174179077e-08-5.960464477539e-08`
- rinex_4.00.txt line 6101, p. 107: blanks inserted by the extraction removed; line restored from the same line of 4.01/nav_sto_eop_ion.rnx.
  - printed: `    2021 07 05 00 09 00 7.450580596924e-09 4.470348358154e-08-4.172325134277e                   -07`
  - fixture: `    2021 07 05 00 09 00 7.450580596924e-09 4.470348358154e-08-4.172325134277e-07`

**4.00/a4_obs_example1.rnx**

- rinex_4.00.txt line 3524, p. 65: event flag and record count printed 7 columns right of cols 32-35 (flag at col 39); the same record is at col 32 in 3.02-3.04 and 4.02, and other lines of this table carry blanks inserted by the extraction, so read as extraction damage.
  - printed: `>                                     4  1`
  - fixture: `>                              4  1`
- rinex_4.00.txt line 3465, p. 64: restored from the same line of 4.01/obs_example1.rnx.
  - printed: ` 18 R01  1 R02  2 R03  3 R04  4 R05  5 R06 -6 R07 -5 R08 -4 GLONASS                 SLOT / FRQ #`
  - fixture: ` 18 R01  1 R02  2 R03  3 R04  4 R05  5 R06 -6 R07 -5 R08 -4 GLONASS SLOT / FRQ #`
- rinex_4.00.txt line 3467, p. 64: restored from the same line of 4.01/obs_example1.rnx.
  - printed: `    R17  5 R18 -5                                                         GLONASS   SLOT / FRQ #`
  - fixture: `    R17  5 R18 -5                                           GLONASS SLOT / FRQ #`
- rinex_4.00.txt line 3468, p. 64: restored from the same line of 4.01/obs_example1.rnx.
  - printed: ` C1C  -10.000 C1P      -10.123 C2C     -10.432 C2P      -10.634        GLONASS      COD/PHS/BIS`
  - fixture: ` C1C  -10.000 C1P  -10.123 C2C  -10.432 C2P  -10.634        GLONASS COD/PHS/BIS`
- rinex_4.00.txt line 3469, p. 64: restored from the same line of 4.01/obs_example1.rnx.
  - printed: `                                                                          END OF HEADER`
  - fixture: `                                                            END OF HEADER`
- rinex_4.00.txt line 3520, p. 65: restored from the same line of 4.01/obs_example1.rnx.
  - printed: `           *** LOST LOCK ON G 06                                           COMMENT`
  - fixture: `           *** LOST LOCK ON G 06                            COMMENT`

**4.00/a5_obs_example2.rnx**

- rinex_4.00.txt line 3613, p. 66: blanks inserted by the extraction inside the wrapped record (lines 3613-3616); record restored from the same record of 4.01/obs_example2.rnx.
  - printed: `E07  23635638.708 8 124206162.80708      -871.617 8        48.750    23635637.971 8 | 100816721.15408      -707.498 8        52.500    23635640.586 8  92751411.05508 | -650.899 8        53.000    23635639.032 8  95171010.23608                      -667.883 8 | 53.750    23635639.494 9  93961204.71809                 -659.388 9        56.500`
  - fixture: `E07  23635638.708 8 124206162.80708      -871.617 8        48.750    23635637.971 8 100816721.15408      -707.498 8        52.500    23635640.586 8  92751411.05508      -650.899 8        53.000    23635639.032 8  95171010.23608      -667.883 8        53.750    23635639.494 9  93961204.71809      -659.388 9        56.500`
- rinex_4.00.txt line 3617, p. 66: blanks inserted by the extraction inside the wrapped record (lines 3617-3620); record restored from the same record of 4.01/obs_example2.rnx.
  - printed: `E08  24972516.642 6 131231506.27606              -2679.842 6        40.000    24972519.075 7 | 106519133.68107          -2175.224 7           43.250    24972516.933 7  97997606.95207 | -2001.200 7        43.500    24972515.374 7 100554056.30907                     -2053.459 7 | 44.250    24972516.248 7  99275831.20407                -2027.334 7        46.750`
  - fixture: `E08  24972516.642 6 131231506.27606     -2679.842 6        40.000    24972519.075 7 106519133.68107     -2175.224 7        43.250    24972516.933 7  97997606.95207     -2001.200 7        43.500    24972515.374 7 100554056.30907     -2053.459 7        44.250    24972516.248 7  99275831.20407     -2027.334 7        46.750`
- rinex_4.00.txt line 3653, p. 67: continuation marker lost in extraction; line treated as a wrap.
  - printed: `49.250`
- rinex_4.00.txt line 3656, p. 67: blanks inserted by the extraction inside the wrapped record (lines 3656-3659); record restored from the same record of 4.01/obs_example2.rnx.
  - printed: `R09  24411449.113 6 130355805.45406      4217.981 6        36.000    24411450.687 6 | 130355790.41406      4218.252 6        36.500    24411457.447 5 101387862.28405 | 3280.773 5        35.750    2441145         8.534 6 101387898.24806      3280.926 6 | 37.250    24411444.199 5  97878261.11305      3167.148 5        34.500`
  - fixture: `R09  24411449.113 6 130355805.45406      4217.981 6        36.000    24411450.687 6 130355790.41406      4218.252 6        36.500    24411457.447 5 101387862.28405      3280.773 5        35.750    24411458.534 6 101387898.24806      3280.926 6        37.250    24411444.199 5  97878261.11305      3167.148 5        34.500`

**4.00/a6_obs_example3.rnx**

- rinex_4.00.txt line 3715, p. 68: blanks inserted/shifted by the extraction; restored from the same line of 4.02/a6_obs_example3.rnx.
  - printed: `                         ANTENNA         NONE                    ANT # / TYPE`
  - fixture: `                    ANTENNA         NONE                    ANT # / TYPE`
- rinex_4.00.txt line 3709, p. 68: restored from the same line of 4.01/obs_example3.rnx.
  - printed: `       24-29dBHz -> 4; 30-35dBHz -> 5; 36-41dBHz              -> 6       COMMEN    T`
  - fixture: `       24-29dBHz -> 4; 30-35dBHz -> 5; 36-41dBHz -> 6       COMMENT`
- rinex_4.00.txt line 3710, p. 68: restored from the same line of 4.01/obs_example3.rnx.
  - printed: `       42-47dBHz -> 7; 48-53dBHz -> 8; >= 54dBHz              -> 9       COMMENT`
  - fixture: `       42-47dBHz -> 7; 48-53dBHz -> 8; >= 54dBHz -> 9       COMMENT`
- rinex_4.00.txt line 3711, p. 68: restored from the same line of 4.01/obs_example3.rnx.
  - printed: `Tokyo                                                                      MARKER NAME`
  - fixture: `Tokyo                                                       MARKER NAME`
- rinex_4.00.txt line 3713, p. 68: restored from the same line of 4.01/obs_example3.rnx.
  - printed: `USER                Organization                                           OBSERVER / AGENCY`
  - fixture: `USER                Organization                            OBSERVER / AGENCY`
- rinex_4.00.txt line 3714, p. 68: restored from the same line of 4.01/obs_example3.rnx.
  - printed: `1870023                  RECEIVER NAME          3.08/6.401          REC # / TYPE / VERS`
  - fixture: `1870023             RECEIVER NAME       3.08/6.401          REC # / TYPE / VERS`
- rinex_4.00.txt line 3716, p. 68: restored from the same line of 4.01/obs_example3.rnx.
  - printed: ` -3956196.8609  3349495.1794  3703988.8347                  APPRO                 X POSITION XYZ`
  - fixture: ` -3956196.8609  3349495.1794  3703988.8347                  APPROX POSITION XYZ`
- rinex_4.00.txt line 3725, p. 68: restored from the same line of 4.01/obs_example3.rnx.
  - printed: `S    4 C1C L1C D1C S1C                                                     SYS / # / OBS TYPES`
  - fixture: `S    4 C1C L1C D1C S1C                                      SYS / # / OBS TYPES`

**4.01/a12_nav_gps.rnx**

- rinex_4.01.txt line 4578, p. 81: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_gps.rnx.
  - printed: `     0.000000000000e+00 7.000000000000e+00          -8.789356797934e    -09 5.000000000000e+00`
  - fixture: `     0.000000000000e+00 7.000000000000e+00-8.789356797934e-09 5.000000000000e+00`
- rinex_4.01.txt line 4579, p. 81: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_gps.rnx.
  - printed: `    -5.820766091347e     -10-6.606569513679e-09-1.178705133498e         -08-1.178705133498e     -08`
  - fixture: `    -5.820766091347e-10-6.606569513679e-09-1.178705133498e-08-1.178705133498e-08`
- rinex_4.01.txt line 4588, p. 81: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_gps.rnx.
  - printed: `     0.000000000000e+00 1.000000000000e+00          -8.789356797934e    -09 5.000000000000e+00`
  - fixture: `     0.000000000000e+00 1.000000000000e+00-8.789356797934e-09 5.000000000000e+00`
- rinex_4.01.txt line 4590, p. 81: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_gps.rnx.
  - printed: `    -3.492459654808e     -10-7.858034223318e    -10`
  - fixture: `    -3.492459654808e-10-7.858034223318e-10`

**4.01/a14_nav_galileo.rnx**

- rinex_4.01.txt line 4733, p. 84: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_galileo.rnx.
  - printed: `E12 2020 09 15 00 40 00 5.605182959698e-03-1.881517164293e               -11 0.000000000000e+     00`
  - fixture: `E12 2020 09 15 00 40 00 5.605182959698e-03-1.881517164293e-11 0.000000000000e+00`
- rinex_4.01.txt line 4735, p. 84: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_galileo.rnx.
  - printed: `     5.209818482399e     -06 1.468013506383e     -04 1.532956957817e     -06 5.440609727859e+03`
  - fixture: `     5.209818482399e-06 1.468013506383e-04 1.532956957817e-06 5.440609727859e+03`
- rinex_4.01.txt line 4736, p. 84: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_galileo.rnx.
  - printed: `     1.752000000000e+05      -1.676380634308e    -08 8.103706855689e     -01 7.450580596924e     -09`
  - fixture: `     1.752000000000e+05-1.676380634308e-08 8.103706855689e-01 7.450580596924e-09`
- rinex_4.01.txt line 4737, p. 84: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_galileo.rnx.
  - printed: `     9.891660140720e-01 3.219375000000e+02 5.171049929386e-01-5.815956543649e                    -09`
  - fixture: `     9.891660140720e-01 3.219375000000e+02 5.171049929386e-01-5.815956543649e-09`
- rinex_4.01.txt line 4739, p. 84: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_galileo.rnx.
  - printed: `     3.120000000000e+00 0.000000000000e+00-1.303851604462e-08-1.280568540096e                    -08`
  - fixture: `     3.120000000000e+00 0.000000000000e+00-1.303851604462e-08-1.280568540096e-08`
- rinex_4.01.txt line 4743, p. 84: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_galileo.rnx.
  - printed: `     4.500000000000e+01 1.730312500000e+02 2.871548182937e-09-1.103934352668e                    -01`
  - fixture: `     4.500000000000e+01 1.730312500000e+02 2.871548182937e-09-1.103934352668e-01`
- rinex_4.01.txt line 4745, p. 84: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_galileo.rnx.
  - printed: `     2.574000000000e+05-5.774199962616e-08 8.098963343817e-01-1.005828380585e                    -07`
  - fixture: `     2.574000000000e+05-5.774199962616e-08 8.098963343817e-01-1.005828380585e-07`

**4.01/a20_nav_qzss.rnx**

- rinex_4.01.txt line 5232, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `J01 2021 01 23 02 00 00-3.374307416379e-04-1.364242052659e               -12 0.000000000000e+0      0`
  - fixture: `J01 2021 01 23 02 00 00-3.374307416379e-04-1.364242052659e-12 0.000000000000e+00`
- rinex_4.01.txt line 5233, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     1.330000000000e+02 9.578125000000e+01 1.388272112820e               -09-2.070362217868e+00`
  - fixture: `     1.330000000000e+02 9.578125000000e+01 1.388272112820e-09-2.070362217868e+00`
- rinex_4.01.txt line 5234, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     2.535060048103e     -06 7.562357175630e     -02 5.446374416351e     -06 6.493648595810e+03`
  - fixture: `     2.535060048103e-06 7.562357175630e-02 5.446374416351e-06 6.493648595810e+03`
- rinex_4.01.txt line 5235, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     5.256000000000e+05      -1.164153218269e    -06 4.173927833877e     -01-3.390014171600e     -06`
  - fixture: `     5.256000000000e+05-1.164153218269e-06 4.173927833877e-01-3.390014171600e-06`
- rinex_4.01.txt line 5241, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e               -12 0.000000000000e+00`
  - fixture: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e-12 0.000000000000e+00`
- rinex_4.01.txt line 5242, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `    -2.224636077881e     -02 9.925390625000e+01 2.809759894921e          -09-2.070460582285e+0      0`
  - fixture: `    -2.224636077881e-02 9.925390625000e+01 2.809759894921e-09-2.070460582285e+00`
- rinex_4.01.txt line 5243, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     2.630054950714e     -06 7.561515661655e     -02 6.853602826595e     -06 6.493646338351e+03`
  - fixture: `     2.630054950714e-06 7.561515661655e-02 6.853602826595e-06 6.493646338351e+03`
- rinex_4.01.txt line 5244, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     5.256000000000e+05 2.942979335785e          -07 4.174090012975e     -01 2.151355147362e     -07`
  - fixture: `     5.256000000000e+05 2.942979335785e-07 4.174090012975e-01 2.151355147362e-07`
- rinex_4.01.txt line 5247, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `    -8.000000000000e+00 0.000000000000e+00           -5.675246939063e    -09 0.000000000000e+00`
  - fixture: `    -8.000000000000e+00 0.000000000000e+00-5.675246939063e-09 0.000000000000e+00`
- rinex_4.01.txt line 5248, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     0.000000000000e+00 3.667082637548e          -09 2.561137080193e     -09 1.949956640601e     -09`
  - fixture: `     0.000000000000e+00 3.667082637548e-09 2.561137080193e-09 1.949956640601e-09`
- rinex_4.01.txt line 5251, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e               -12 0.000000000000e+00`
  - fixture: `J01 2021 01 23 02 00 00-3.374309453648e-04-1.364242052659e-12 0.000000000000e+00`
- rinex_4.01.txt line 5252, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `    -2.224636077881e     -02 9.925390625000e+01 2.809759894921e          -09-2.070460582285e+00`
  - fixture: `    -2.224636077881e-02 9.925390625000e+01 2.809759894921e-09-2.070460582285e+00`
- rinex_4.01.txt line 5253, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     2.630054950    714e-06 7.561515661655e      -02 6.853602826595e     -06 6.493646338351e+03`
  - fixture: `     2.630054950714e-06 7.561515661655e-02 6.853602826595e-06 6.493646338351e+03`
- rinex_4.01.txt line 5254, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     5.256000000000e+05 2.942979335785e          -07 4.174090012975e     -01 2.151355147362e     -07`
  - fixture: `     5.256000000000e+05 2.942979335785e-07 4.174090012975e-01 2.151355147362e-07`
- rinex_4.01.txt line 5257, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `    -8.000000000000e+00 0.000000000000e+00           -5.675246939063e    -09 0.000000000000e+00`
  - fixture: `    -8.000000000000e+00 0.000000000000e+00-5.675246939063e-09 0.000000000000e+00`
- rinex_4.01.txt line 5258, p. 92: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_qzss.rnx.
  - printed: `     0.000000000000e+00 3.667082637548e          -09 2.561137080193e     -09 1.949956640601e     -09`
  - fixture: `     0.000000000000e+00 3.667082637548e-09 2.561137080193e-09 1.949956640601e-09`

**4.01/a25_nav_beidou.rnx**

- rinex_4.01.txt line 5737, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `C05 2021 07 05 22 00 00     -5.836377386004e    -05 1.694644424788e     -11 0.000000000000e+00`
  - fixture: `C05 2021 07 05 22 00 00-5.836377386004e-05 1.694644424788e-11 0.000000000000e+00`
- rinex_4.01.txt line 5738, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     0.000000000000e+00     -5.881250000000e+01 1.949724070976e         -09-1.593114605012e+00`
  - fixture: `     0.000000000000e+00-5.881250000000e+01 1.949724070976e-09-1.593114605012e+00`
- rinex_4.01.txt line 5739, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `    -1.817941665649e     -06 7.691901409999e    -04 1.800991594791e     -05 6.493525815964e+03`
  - fixture: `    -1.817941665649e-06 7.691901409999e-04 1.800991594791e-05 6.493525815964e+03`
- rinex_4.01.txt line 5740, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     1.656000000000e+05 2.072192728519e         -07 2.624951167227e+00      -1.122243702412e    -07`
  - fixture: `     1.656000000000e+05 2.072192728519e-07 2.624951167227e+00-1.122243702412e-07`
- rinex_4.01.txt line 5741, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     1.151558582809e-01-5.497031250000e+02-4.954214719500e-01-8.100337411567e                   -10`
  - fixture: `     1.151558582809e-01-5.497031250000e+02-4.954214719500e-01-8.100337411567e-10`
- rinex_4.01.txt line 5747, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     1.000000000000e+00-2.265625000000e+00 4.092313318419e-09-1.556359938124e                   -01`
  - fixture: `     1.000000000000e+00-2.265625000000e+00 4.092313318419e-09-1.556359938124e-01`
- rinex_4.01.txt line 5749, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     9.360000000000e+04 2.328306436539e-09-2.772255179876e+00               -1.164153218269e    -08`
  - fixture: `     9.360000000000e+04 2.328306436539e-09-2.772255179876e+00-1.164153218269e-08`
- rinex_4.01.txt line 5750, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     9.665781566257e-01 2.337656250000e+02-6.218441883865e-01-6.809926517917e                   -09`
  - fixture: `     9.665781566257e-01 2.337656250000e+02-6.218441883865e-01-6.809926517917e-09`
- rinex_4.01.txt line 5757, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     7.729977369308e     -08 8.434175979346e    -04 7.596798241138e     -06 5.282624978926e+03`
  - fixture: `     7.729977369308e-08 8.434175979346e-04 7.596798241138e-06 5.282624978926e+03`
- rinex_4.01.txt line 5758, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     1.656000000000e+05     -4.190951585770e    -08-2.772741033988e+00      -2.514570951462e    -08`
  - fixture: `     1.656000000000e+05-4.190951585770e-08-2.772741033988e+00-2.514570951462e-08`
- rinex_4.01.txt line 5759, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     9.666057809078e-01 2.101328125000e+02-6.122205141961e-01-6.644205329250e                   -09`
  - fixture: `     9.666057809078e-01 2.101328125000e+02-6.122205141961e-01-6.644205329250e-09`
- rinex_4.01.txt line 5762, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `    -3.492459654808e-10                    2.328306436539e-08-2.968590706587e                   -09`
  - fixture: `    -3.492459654808e-10                    2.328306436539e-08-2.968590706587e-09`
- rinex_4.01.txt line 5768, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     0.000000000000e+00 8.432919275947e         -04 7.565133273602e     -06 5.282623812254e+03`
  - fixture: `     0.000000000000e+00 8.432919275947e-04 7.565133273602e-06 5.282623812254e+03`
- rinex_4.01.txt line 5769, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     1.692000000000e+05     -4.656612873077e    -08-2.772764954893e+00      -3.632158041000e    -08`
  - fixture: `     1.692000000000e+05-4.656612873077e-08-2.772764954893e+00-3.632158041000e-08`
- rinex_4.01.txt line 5770, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     9.666074588748e-01 2.102968750000e+02-6.120578881764e-01-6.652598536003e                   -09`
  - fixture: `     9.666074588748e-01 2.102968750000e+02-6.120578881764e-01-6.652598536003e-09`
- rinex_4.01.txt line 5773, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `                       -2.502929419279e-09 2.328306436539e-08-2.968590706587e                   -09`
  - fixture: `                       -2.502929419279e-09 2.328306436539e-08-2.968590706587e-09`
- rinex_4.01.txt line 5779, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `    -6.891787052155e     -08 8.444703416899e    -04 6.626360118389e     -06 5.282619899994e+03`
  - fixture: `    -6.891787052155e-08 8.444703416899e-04 6.626360118389e-06 5.282619899994e+03`
- rinex_4.01.txt line 5780, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     8.640000000000e+04 3.72529029        8462e-08-2.772205880999e+00 0.000000000000e+00`
  - fixture: `     8.640000000000e+04 3.725290298462e-08-2.772205880999e+00 0.000000000000e+00`
- rinex_4.01.txt line 5781, p. 101: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_beidou.rnx.
  - printed: `     9.665752168918e     -01 2.300390625000e+02     -6.230324874839e    -01-6.829570193298e     -09`
  - fixture: `     9.665752168918e-01 2.300390625000e+02-6.230324874839e-01-6.829570193298e-09`

**4.01/a27_nav_sbas.rnx**

- rinex_4.01.txt line 5873, p. 103: blanks inserted/shifted by the extraction; restored from the same line of 4.02/a29_nav_sbas.rnx.
  - printed: `> EPH S30 S   BAS`
  - fixture: `> EPH S30 SBAS`
- rinex_4.01.txt line 5883, p. 103: blanks inserted/shifted by the extraction; restored from the same line of 4.02/a29_nav_sbas.rnx.
  - printed: `> EPH S23 SBA   S`
  - fixture: `> EPH S23 SBAS`
- rinex_4.01.txt line 5869, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `S28 2020 09 15 23 56 48 5.075708031654e-08-2.091837814078e                -11 2.589840000000e+0      5`
  - fixture: `S28 2020 09 15 23 56 48 5.075708031654e-08-2.091837814078e-11 2.589840000000e+05`
- rinex_4.01.txt line 5870, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `     5.159782400000e+03 7.125000000000e           -04-2.500000000000e     -08 0.000000000000e+00`
  - fixture: `     5.159782400000e+03 7.125000000000e-04-2.500000000000e-08 0.000000000000e+00`
- rinex_4.01.txt line 5871, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `     4.185231736000e+04      -2.462500000000e     -04-3.750000000000e     -08 4.096000000000e+03`
  - fixture: `     4.185231736000e+04-2.462500000000e-04-3.750000000000e-08 4.096000000000e+03`
- rinex_4.01.txt line 5872, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `    -8.261200000000e+00      -1.328000000000e     -03 6.250000000000e     -08 1.200000000000e+01`
  - fixture: `    -8.261200000000e+00-1.328000000000e-03 6.250000000000e-08 1.200000000000e+01`
- rinex_4.01.txt line 5874, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `S30 2020 09 15 00 00 00 1.937150955200e           -07 0.000000000000e+00 1.728330000000e+05`
  - fixture: `S30 2020 09 15 00 00 00 1.937150955200e-07 0.000000000000e+00 1.728330000000e+05`
- rinex_4.01.txt line 5875, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `    -3.228075088000e+04 1.990000000000e           -03-1.375000000000e     -07 1.000000000000e+00`
  - fixture: `    -3.228075088000e+04 1.990000000000e-03-1.375000000000e-07 1.000000000000e+00`
- rinex_4.01.txt line 5876, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `     2.711642576000e+04      -1.374375000000e     -03-1.000000000000e     -07 3.276700000000e+04`
  - fixture: `     2.711642576000e+04-1.374375000000e-03-1.000000000000e-07 3.276700000000e+04`
- rinex_4.01.txt line 5877, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `    -1.045603600000e+03      -3.671600000000e     -02 2.750000000000e     -06 5.900000000000e+01`
  - fixture: `    -1.045603600000e+03-3.671600000000e-02 2.750000000000e-06 5.900000000000e+01`
- rinex_4.01.txt line 5882, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `     0.000000000000e+00 0.000000000000e+00 0.000000000000e+00                  5.800000000000e+0     1`
  - fixture: `     0.000000000000e+00 0.000000000000e+00 0.000000000000e+00 5.800000000000e+01`
- rinex_4.01.txt line 5887, p. 103: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sbas.rnx.
  - printed: `     0.000000000000e+00 0.000000000000e+00 0.000000000000e+00                  5.900000000000e+01`
  - fixture: `     0.000000000000e+00 0.000000000000e+00 0.000000000000e+00 5.900000000000e+01`

**4.01/a29_nav_navic.rnx**

- rinex_4.01.txt line 6025, p. 105: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_navic.rnx.
  - printed: `     1.690000000000e+02-5.793750000000e+02 4.834487090078e-09-4.281979621524e                     -01`
  - fixture: `     1.690000000000e+02-5.793750000000e+02 4.834487090078e-09-4.281979621524e-01`
- rinex_4.01.txt line 6026, p. 105: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_navic.rnx.
  - printed: `    -1.904368400574e-05 2.015684265643e-03-3.430992364883e               -06 6.493289550781e+03`
  - fixture: `    -1.904368400574e-05 2.015684265643e-03-3.430992364883e-06 6.493289550781e+03`
- rinex_4.01.txt line 6027, p. 105: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_navic.rnx.
  - printed: `     1.803360000000e+05 2.495944499969e          -07-1.33749901533     4e+00 7.450580596924e      -08`
  - fixture: `     1.803360000000e+05 2.495944499969e-07-1.337499015334e+00 7.450580596924e-08`
- rinex_4.01.txt line 6034, p. 105: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_navic.rnx.
  - printed: `     1.700000000000e+02-5.798125000000e+02 4.847344768509e-09-3.616804200470e                     -01`
  - fixture: `     1.700000000000e+02-5.798125000000e+02 4.847344768509e-09-3.616804200470e-01`
- rinex_4.01.txt line 6035, p. 105: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_navic.rnx.
  - printed: `    -1.905485987663e-05 2.015971462242e-03-3.460794687271e               -06 6.493290285110e+03`
  - fixture: `    -1.905485987663e-05 2.015971462242e-03-3.460794687271e-06 6.493290285110e+03`
- rinex_4.01.txt line 6036, p. 105: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_navic.rnx.
  - printed: `     1.812480000000e+05 2.346932888031e          -07-1.337503058840e+00 8.568167686462e           -08`
  - fixture: `     1.812480000000e+05 2.346932888031e-07-1.337503058840e+00 8.568167686462e-08`

**4.01/a35_nav_sto_eop_ion.rnx**

- rinex_4.01.txt line 6326, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     2.532240000000e+05 9.895302355289e-10-1.154631945610e              -14 0.000000000000e+00`
  - fixture: `     2.532240000000e+05 9.895302355289e-10-1.154631945610e-14 0.000000000000e+00`
- rinex_4.01.txt line 6329, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     2.173000000000e+05 2.299202606082e         -09 0.000000000000e+00 0.000000000000e+00`
  - fixture: `     2.173000000000e+05 2.299202606082e-09 0.000000000000e+00 0.000000000000e+00`
- rinex_4.01.txt line 6331, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 00 04 48 IRUT                                                 UTCIRN`
  - fixture: `    2020 09 15 00 04 48 IRUT                                  UTCIRN`
- rinex_4.01.txt line 6332, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     1.731720000000e+05     -8.614733815193e    -09-1.776356839400e     -15 0.000000000000e+00`
  - fixture: `     1.731720000000e+05-8.614733815193e-09-1.776356839400e-15 0.000000000000e+00`
- rinex_4.01.txt line 6334, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 00 04 48 IRUT                                                 UTC(NPLI)`
  - fixture: `    2020 09 15 00 04 48 IRUT                                  UTC(NPLI)`
- rinex_4.01.txt line 6335, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     1.732200000000e+05 2.619344741106e         -10 3.996802888651e     -15 0.000000000000e+00`
  - fixture: `     1.732200000000e+05 2.619344741106e-10 3.996802888651e-15 0.000000000000e+00`
- rinex_4.01.txt line 6337, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 18 02 52 48 QZUT                                                 UTC(NICT)`
  - fixture: `    2020 09 18 02 52 48 QZUT                                  UTC(NICT)`
- rinex_4.01.txt line 6338, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     1.837140000000e+05     -9.313225746155e    -10 0.000000000000e+00 0.000000000000e+00`
  - fixture: `     1.837140000000e+05-9.313225746155e-10 0.000000000000e+00 0.000000000000e+00`
- rinex_4.01.txt line 6341, p. 110: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     1.714860000000e+05     -3.768946044147e    -08-3.730349362741e     -13-2.168404344971e     -19`
  - fixture: `     1.714860000000e+05-3.768946044147e-08-3.730349362741e-13-2.168404344971e-19`
- rinex_4.01.txt line 6360, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 18 19 56 48 2.070846557617e-01-2.679824829102e              -04 0.000000000000e+00`
  - fixture: `    2020 09 18 19 56 48 2.070846557617e-01-2.679824829102e-04 0.000000000000e+00`
- rinex_4.01.txt line 6361, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `                              3.392457962036e    -01-1.400947570801e    -03 0.000000000000e+00`
  - fixture: `                        3.392457962036e-01-1.400947570801e-03 0.000000000000e+00`
- rinex_4.01.txt line 6362, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     2.532480000000e+05     -1.759799122810e     -01-7.975101470947e    -05 0.000000000000e+00`
  - fixture: `     2.532480000000e+05-1.759799122810e-01-7.975101470947e-05 0.000000000000e+00`
- rinex_4.01.txt line 6364, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 00 00 00 2.084112167358e          -01-3.948211669922e    -04 0.000000000000e+00`
  - fixture: `    2020 09 15 00 00 00 2.084112167358e-01-3.948211669922e-04 0.000000000000e+00`
- rinex_4.01.txt line 6365, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `                              3.408145904541e    -01-1.317977905273e    -03 0.000000000000e+00`
  - fixture: `                        3.408145904541e-01-1.317977905273e-03 0.000000000000e+00`
- rinex_4.01.txt line 6366, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `     1.749900000000e+05     -1.752023100853e     -01 2.140104770660e    -04 0.000000000000e+00`
  - fixture: `     1.749900000000e+05-1.752023100853e-01 2.140104770660e-04 0.000000000000e+00`
- rinex_4.01.txt line 6368, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2020 09 15 01 00 00 2.082471847534e          -01-6.551742553711e    -04 0.000000000000e+00`
  - fixture: `    2020 09 15 01 00 00 2.082471847534e-01-6.551742553711e-04 0.000000000000e+00`
- rinex_4.01.txt line 6369, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `                              3.444433212280e    -01-9.121894836426e    -04 0.000000000000e+     00`
  - fixture: `                        3.444433212280e-01-9.121894836426e-04 0.000000000000e+00`
- rinex_4.01.txt line 6373, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2021 07 05 23 30 42 7.450580596924e-09 2.235174179077e-08-5.960464477539                   e-08`
  - fixture: `    2021 07 05 23 30 42 7.450580596924e-09 2.235174179077e-08-5.960464477539e-08`
- rinex_4.01.txt line 6383, p. 111: blanks inserted by the extraction removed; line restored from the same line of 4.02/nav_sto_eop_ion.rnx.
  - printed: `    2021 07 05 00 09 00 7.450580596924e-09 4.470348358154e-08-4.172325134277e                   -07`
  - fixture: `    2021 07 05 00 09 00 7.450580596924e-09 4.470348358154e-08-4.172325134277e-07`

**4.01/a4_obs_example1.rnx**

- rinex_4.01.txt line 3805, p. 69: event flag and record count printed 7 columns right of cols 32-35 (flag at col 39); the same record is at col 32 in 3.02-3.04 and 4.02, and other lines of this table carry blanks inserted by the extraction, so read as extraction damage.
  - printed: `>                                     4  1`
  - fixture: `>                              4  1`
- rinex_4.01.txt line 3746, p. 68: restored from the same line of 4.02/obs_example1.rnx.
  - printed: ` 18 R01  1 R02  2 R03  3 R04  4 R05  5 R06 -6 R07 -5 R08 -4 GLONASS                 SLOT / FRQ #`
  - fixture: ` 18 R01  1 R02  2 R03  3 R04  4 R05  5 R06 -6 R07 -5 R08 -4 GLONASS SLOT / FRQ #`
- rinex_4.01.txt line 3748, p. 68: restored from the same line of 4.02/obs_example1.rnx.
  - printed: `    R17  5 R18 -5                                                         GLONASS   SLOT / FRQ #`
  - fixture: `    R17  5 R18 -5                                           GLONASS SLOT / FRQ #`
- rinex_4.01.txt line 3749, p. 68: restored from the same line of 4.02/obs_example1.rnx.
  - printed: ` C1C  -10.000 C1P      -10.123 C2C     -10.432 C2P      -10.634        GLONASS      COD/PHS/BIS`
  - fixture: ` C1C  -10.000 C1P  -10.123 C2C  -10.432 C2P  -10.634        GLONASS COD/PHS/BIS`
- rinex_4.01.txt line 3750, p. 68: restored from the same line of 4.02/obs_example1.rnx.
  - printed: `                                                                          END OF HEADER`
  - fixture: `                                                            END OF HEADER`
- rinex_4.01.txt line 3801, p. 69: restored from the same line of 4.02/obs_example1.rnx.
  - printed: `           *** LOST LOCK ON G 06                                           COMMENT`
  - fixture: `           *** LOST LOCK ON G 06                            COMMENT`

**4.01/a5_obs_example2.rnx**

- rinex_4.01.txt line 3921, p. 71: continuation marker lost in extraction; line treated as a wrap.
  - printed: `26.750`
- rinex_4.01.txt line 3935, p. 71: continuation marker lost in extraction; line treated as a wrap.
  - printed: `49.250`
- rinex_4.01.txt line 3938, p. 71: blanks inserted by the extraction inside the wrapped record (lines 3938-3941); record restored from the same record of 4.02/obs_example2.rnx.
  - printed: `R09  24411449.113 6 130355805.45406      4217.981 6        36.000    24411450.687 6 | 130355790.41406      4218.252 6        36.500    24411457.447 5 101387862.28405 | 3280.773 5        35.750    2441145         8.534 6 101387898.24806      3280.926 6 | 37.250    24411444.199 5  97878261.11305      3167.148 5        34.500`
  - fixture: `R09  24411449.113 6 130355805.45406      4217.981 6        36.000    24411450.687 6 130355790.41406      4218.252 6        36.500    24411457.447 5 101387862.28405      3280.773 5        35.750    24411458.534 6 101387898.24806      3280.926 6        37.250    24411444.199 5  97878261.11305      3167.148 5        34.500`

**4.01/a6_obs_example3.rnx**

- rinex_4.01.txt line 3996, p. 72: blanks inserted/shifted by the extraction; restored from the same line of 4.02/a6_obs_example3.rnx.
  - printed: `                         ANTENNA         NONE                    ANT # / TYPE`
  - fixture: `                    ANTENNA         NONE                    ANT # / TYPE`
- rinex_4.01.txt line 3990, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `       24-29dBHz -> 4; 30-35dBHz -> 5; 36-41dBHz              -> 6       COMMEN    T`
  - fixture: `       24-29dBHz -> 4; 30-35dBHz -> 5; 36-41dBHz -> 6       COMMENT`
- rinex_4.01.txt line 3991, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `       42-47dBHz -> 7; 48-53dBHz -> 8; >= 54dBHz              -> 9       COMMENT`
  - fixture: `       42-47dBHz -> 7; 48-53dBHz -> 8; >= 54dBHz -> 9       COMMENT`
- rinex_4.01.txt line 3992, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `Tokyo                                                                      MARKER NAME`
  - fixture: `Tokyo                                                       MARKER NAME`
- rinex_4.01.txt line 3994, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `USER                     Organization                                      OBSERVER / AGENCY`
  - fixture: `USER                Organization                            OBSERVER / AGENCY`
- rinex_4.01.txt line 3995, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `1870023                  RECEIVER NAME          3.08/6.401          REC # / TYPE / VERS`
  - fixture: `1870023             RECEIVER NAME       3.08/6.401          REC # / TYPE / VERS`
- rinex_4.01.txt line 3997, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: ` -3956196.8609  3349495.1794  3703988.8347                                 APPROX POSITION XYZ`
  - fixture: ` -3956196.8609  3349495.1794  3703988.8347                  APPROX POSITION XYZ`
- rinex_4.01.txt line 4000, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `       L5Q D5Q S5Q                                                         SYS / # / OBS TYPES`
  - fixture: `       L5Q D5Q S5Q                                          SYS / # / OBS TYPES`
- rinex_4.01.txt line 4003, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `       L8Q D8Q S8Q                                          SYS / # / OBS TY                    PES`
  - fixture: `       L8Q D8Q S8Q                                          SYS / # / OBS TYPES`
- rinex_4.01.txt line 4007, p. 72: restored from the same line of 4.02/obs_example3.rnx.
  - printed: `DBHZ                                                                       SIGNAL STRENGTH UNIT`
  - fixture: `DBHZ                                                        SIGNAL STRENGTH UNIT`

**4.02/a5_obs_example2.rnx**

- rinex_4.02.txt line 4020, p. 73: continuation marker lost in extraction; line treated as a wrap.
  - printed: `49.250`

---

## c. Typographic devices of the spec undone

- Page furniture (page headers and footers, `===== page N =====`), ruler lines
  (`----|---1|0---|...`), blank lines and the example indentation (4-6 columns in 3.00 and 3.01)
  are removed everywhere. They are not listed one by one.
- Table A9 in 3.03-3.05 prints two files in one box, a Galileo file and a mixed
  (BCEmerge) file. They are split into `a9_nav_galileo.rnx` and `a9_nav_mixed_galileo.rnx`.
- Table A8 in 4.0x prints two header-only navigation files. They become
  `a8_nav_header_example1.rnx` and `a8_nav_header_example2.rnx`.
- In obs example #1 (3.00-4.02), removing the ` .` elision lines leaves a valid file. The
  event before and the `END OF FILE` event after them are both complete records.

**Elision markers removed** (lines that hold only ` .` or `[…]`; the spec omits records there):

- 3.00/a3_obs_mixed.rnx: rinex300.txt lines 2105, 2106, 2107
- 3.01/a3_obs_mixed.rnx: rinex301.txt lines 2348, 2349, 2350
- 3.02/a4_obs_mixed.rnx: rinex302.txt lines 3209, 3210, 3211
- 3.03/a4_obs_example1.rnx: rinex303.txt lines 3355, 3356, 3357
- 3.04/a4_obs_example1.rnx: rinex304.txt lines 3638, 3639, 3640
- 3.05/a4_obs_example1.rnx: rinex305.txt lines 3410, 3411, 3412
- 4.00/a4_obs_example1.rnx: rinex_4.00.txt lines 3521, 3522, 3523
- 4.00/a5_obs_example2.rnx: rinex_4.00.txt lines 3608, 3621, 3643, 3660
- 4.01/a4_obs_example1.rnx: rinex_4.01.txt lines 3802, 3803, 3804
- 4.01/a5_obs_example2.rnx: rinex_4.01.txt lines 3889, 3902, 3925, 3942
- 4.02/a4_obs_example1.rnx: rinex_4.02.txt lines 3891, 3892, 3893
- 4.02/a5_obs_example2.rnx: rinex_4.02.txt lines 3975, 3988, 4010, 4027

**Wrapped observation records joined** (4.0x Table A5 prints each long satellite record on several lines; continuation lines start with `→` (4.00, 4.01) or `®` (4.02), and the blanks at each break are lost. The record is rebuilt by choosing, at each break, the smallest number of blanks that puts every decimal point at column 14+16k and every LLI/SSI position on a digit or blank (F14.3,I1,I1 fields, rinex_4.02.txt Table A3). The blank counts used are listed; a whole blank field lost at a break would be invisible to this rule.)


*4.00/a5_obs_example2.rnx*

- rinex_4.00.txt lines 3596-3599, p. 66: blanks restored [2, 1, 9] -> `C05` record of 12 fields
- rinex_4.00.txt lines 3600-3603, p. 66: blanks restored [2, 1, 6] -> `C07` record of 12 fields
- rinex_4.00.txt lines 3604-3607, p. 66: blanks restored [2, 1, 6] -> `C10` record of 12 fields
- rinex_4.00.txt lines 3609-3612, p. 66: blanks restored [1, 5, 8] -> `E02` record of 20 fields
- rinex_4.00.txt lines 3613-3616, p. 66: blanks restored n/a -> `E07` record of 20 fields
- rinex_4.00.txt lines 3617-3620, p. 66: blanks restored n/a -> `E08` record of 20 fields
- rinex_4.00.txt lines 3631-3635, p. 67: blanks restored [8, 4, 2, 7] -> `G14` record of 22 fields
- rinex_4.00.txt lines 3636-3638, p. 67: blanks restored [8, 4] -> `G15` record of 14 fields
- rinex_4.00.txt lines 3639-3642, p. 67: blanks restored [4, 2, 0] -> `G18` record of 16 fields
- rinex_4.00.txt lines 3646-3649, p. 67: blanks restored [1, 5, 8] -> `R04` record of 16 fields
- rinex_4.00.txt lines 3650-3653, p. 67: blanks restored [1, 5, 8] -> `R05` record of 16 fields
- rinex_4.00.txt lines 3654-3655, p. 67: blanks restored [1] -> `R06` record of 8 fields
- rinex_4.00.txt lines 3656-3659, p. 67: blanks restored n/a -> `R09` record of 20 fields
- rinex_4.00.txt lines 3661-3662, p. 67: blanks restored [1] -> `S23` record of 8 fields
- rinex_4.00.txt lines 3665-3666, p. 67: blanks restored [1] -> `S27` record of 8 fields
- rinex_4.00.txt lines 3667-3668, p. 67: blanks restored [1] -> `S36` record of 8 fields

*4.01/a5_obs_example2.rnx*

- rinex_4.01.txt lines 3877-3880, p. 70: blanks restored [2, 1, 9] -> `C05` record of 12 fields
- rinex_4.01.txt lines 3881-3884, p. 70: blanks restored [2, 1, 6] -> `C07` record of 12 fields
- rinex_4.01.txt lines 3885-3888, p. 70: blanks restored [2, 1, 6] -> `C10` record of 12 fields
- rinex_4.01.txt lines 3890-3893, p. 70: blanks restored [1, 5, 8] -> `E02` record of 20 fields
- rinex_4.01.txt lines 3894-3897, p. 70: blanks restored [1, 6, 8] -> `E07` record of 20 fields
- rinex_4.01.txt lines 3898-3901, p. 70: blanks restored [1, 5, 8] -> `E08` record of 20 fields
- rinex_4.01.txt lines 3912-3916, p. 71: blanks restored [8, 4, 2, 7] -> `G14` record of 22 fields
- rinex_4.01.txt lines 3917-3919, p. 71: blanks restored [8, 4] -> `G15` record of 14 fields
- rinex_4.01.txt lines 3920-3924, p. 71: blanks restored [8, 4, 2, 0] -> `G18` record of 16 fields
- rinex_4.01.txt lines 3928-3931, p. 71: blanks restored [1, 5, 8] -> `R04` record of 16 fields
- rinex_4.01.txt lines 3932-3935, p. 71: blanks restored [1, 5, 8] -> `R05` record of 16 fields
- rinex_4.01.txt lines 3936-3937, p. 71: blanks restored [1] -> `R06` record of 8 fields
- rinex_4.01.txt lines 3938-3941, p. 71: blanks restored n/a -> `R09` record of 20 fields
- rinex_4.01.txt lines 3943-3944, p. 71: blanks restored [1] -> `S23` record of 8 fields
- rinex_4.01.txt lines 3947-3948, p. 71: blanks restored [1] -> `S27` record of 8 fields
- rinex_4.01.txt lines 3949-3950, p. 71: blanks restored [1] -> `S36` record of 8 fields

*4.02/a5_obs_example2.rnx*

- rinex_4.02.txt lines 3963-3966, p. 72: blanks restored [2, 1, 9] -> `C05` record of 12 fields
- rinex_4.02.txt lines 3967-3970, p. 72: blanks restored [2, 1, 6] -> `C07` record of 12 fields
- rinex_4.02.txt lines 3971-3974, p. 72: blanks restored [2, 1, 6] -> `C10` record of 12 fields
- rinex_4.02.txt lines 3976-3979, p. 72: blanks restored [1, 5, 8] -> `E02` record of 20 fields
- rinex_4.02.txt lines 3980-3983, p. 72: blanks restored [1, 6, 8] -> `E07` record of 20 fields
- rinex_4.02.txt lines 3984-3987, p. 72: blanks restored [1, 5, 8] -> `E08` record of 20 fields
- rinex_4.02.txt lines 3998-4002, p. 73: blanks restored [8, 4, 2, 7] -> `G14` record of 22 fields
- rinex_4.02.txt lines 4003-4005, p. 73: blanks restored [8, 4] -> `G15` record of 14 fields
- rinex_4.02.txt lines 4006-4009, p. 73: blanks restored [4, 2, 0] -> `G18` record of 16 fields
- rinex_4.02.txt lines 4013-4016, p. 73: blanks restored [1, 5, 8] -> `R04` record of 16 fields
- rinex_4.02.txt lines 4017-4020, p. 73: blanks restored [1, 5, 8] -> `R05` record of 16 fields
- rinex_4.02.txt lines 4021-4022, p. 73: blanks restored [1] -> `R06` record of 8 fields
- rinex_4.02.txt lines 4023-4026, p. 73: blanks restored [1, 6, 8] -> `R09` record of 20 fields
- rinex_4.02.txt lines 4028-4029, p. 73: blanks restored [1] -> `S23` record of 8 fields
- rinex_4.02.txt lines 4032-4033, p. 73: blanks restored [1] -> `S27` record of 8 fields
- rinex_4.02.txt lines 4034-4035, p. 73: blanks restored [1] -> `S36` record of 8 fields

**Record examples wrapped in a header.** RINEX 4 navigation record examples are printed without a file header. Each fixture is the version's own Table A8 header example 1 (merged navigation file header, `MERGED FILE`, `LEAP SECONDS`) followed by the records exactly as printed:

- 4.00/a12_nav_gps.rnx: records from rinex_4.00.txt line 4281, p. 77
- 4.00/a14_nav_galileo.rnx: records from rinex_4.00.txt line 4451, p. 80
- 4.00/a16_nav_glonass.rnx: records from rinex_4.00.txt line 4607, p. 82
- 4.00/a20_nav_qzss.rnx: records from rinex_4.00.txt line 4950, p. 88
- 4.00/a25_nav_beidou.rnx: records from rinex_4.00.txt line 5455, p. 97
- 4.00/a27_nav_sbas.rnx: records from rinex_4.00.txt line 5587, p. 99
- 4.00/a29_nav_navic.rnx: records from rinex_4.00.txt line 5743, p. 101
- 4.00/a35_nav_sto_eop_ion.rnx: records from rinex_4.00.txt line 6039, p. 106
- 4.01/a12_nav_gps.rnx: records from rinex_4.01.txt line 4562, p. 81
- 4.01/a14_nav_galileo.rnx: records from rinex_4.01.txt line 4732, p. 84
- 4.01/a16_nav_glonass.rnx: records from rinex_4.01.txt line 4888, p. 86
- 4.01/a20_nav_qzss.rnx: records from rinex_4.01.txt line 5231, p. 92
- 4.01/a25_nav_beidou.rnx: records from rinex_4.01.txt line 5736, p. 101
- 4.01/a27_nav_sbas.rnx: records from rinex_4.01.txt line 5868, p. 103
- 4.01/a29_nav_navic.rnx: records from rinex_4.01.txt line 6023, p. 105
- 4.01/a35_nav_sto_eop_ion.rnx: records from rinex_4.01.txt line 6321, p. 110
- 4.02/a12_nav_gps.rnx: records from rinex_4.02.txt line 4648, p. 83
- 4.02/a14_nav_galileo.rnx: records from rinex_4.02.txt line 4813, p. 86
- 4.02/a18_nav_glonass.rnx: records from rinex_4.02.txt line 5149, p. 91
- 4.02/a22_nav_qzss.rnx: records from rinex_4.02.txt line 5563, p. 98
- 4.02/a27_nav_beidou.rnx: records from rinex_4.02.txt line 6060, p. 107
- 4.02/a29_nav_sbas.rnx: records from rinex_4.02.txt line 6185, p. 109
- 4.02/a32_nav_navic.rnx: records from rinex_4.02.txt line 6452, p. 113
- 4.02/a41_nav_sto_eop_ion.rnx: records from rinex_4.02.txt line 7027, p. 123

---

## d. Derived fixtures (not as printed)

- **2.10/a7_obs_mixed_derived_count.rnx**: derived from 2.10/a7_obs_mixed.rnx: last event record count 4 -> 3 (three COMMENT records follow; 2.11 Table A7 prints 3).
- **2.11/a18_nav_geo_derived_columns.rnx**: derived from 2.11/a18_nav_geo.rnx: D-UTC A0,A1,T,W,S,U fields moved one column right to the 2D19.12,I7,I5,X,A5,X,I2 layout of Table A15 (A0 printed in 18 columns).
- **3.03/a4_obs_example2_derived_header.rnx**: derived from 3.03/a4_obs_example2.rnx: dangling epoch record and the END OF FILE comment after it removed (header kept).
- **3.03/a4_obs_example3_derived_header.rnx**: derived from 3.03/a4_obs_example3.rnx: dangling epoch record and the END OF FILE comment after it removed (header kept).
- **3.04/a4_obs_example2_derived_header.rnx**: derived from 3.04/a4_obs_example2.rnx: dangling epoch record and the END OF FILE comment after it removed (header kept).
- **3.04/a4_obs_example3_derived_header.rnx**: derived from 3.04/a4_obs_example3.rnx: dangling epoch record and the END OF FILE comment after it removed (header kept).
- **3.05/a4_obs_example2_derived_header.rnx**: derived from 3.05/a4_obs_example2.rnx: dangling epoch record and the END OF FILE comment after it removed (header kept).
- **3.05/a4_obs_example3_derived_header.rnx**: derived from 3.05/a4_obs_example3.rnx: dangling epoch record and the END OF FILE comment after it removed (header kept).
- **4.02/a5_obs_example2_derived_count.rnx**: derived from 4.02/a5_obs_example2.rnx: satellite count of the epoch set to the satellites actually printed (epoch at line 29: satellite count 42 -> 21).
- **4.02/a6_obs_example3_derived_header.rnx**: derived from 4.02/a6_obs_example3.rnx: dangling epoch record removed (header kept).
- **4.01/a5_obs_example2_derived_count.rnx**: derived from 4.01/a5_obs_example2.rnx: satellite count of the epoch set to the satellites actually printed (epoch at line 29: satellite count 42 -> 21).
- **4.01/a6_obs_example3_derived_header.rnx**: derived from 4.01/a6_obs_example3.rnx: dangling epoch record removed (header kept).
- **4.00/a5_obs_example2_derived_count.rnx**: derived from 4.00/a5_obs_example2.rnx: satellite count of the epoch set to the satellites actually printed (epoch at line 29: satellite count 42 -> 21).
- **4.00/a6_obs_example3_derived_header.rnx**: derived from 4.00/a6_obs_example3.rnx: dangling epoch record removed (header kept).
