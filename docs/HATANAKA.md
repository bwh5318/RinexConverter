# Compact RINEX (Hatanaka) grammar

This is the grammar our codec (`rinexcore/io/hatanaka.py`) implements. It was written
from the GSI reference source before the code:
`specs/hatanaka/src/RNXCMP_4.2.0_src/source/crx2rnx.c` (decoder, "C:" line numbers below)
and `rnx2crx.c` (encoder, "E:" line numbers), both RNXCMP 4.2.0, plus
`specs/hatanaka/src/RNXCMP_4.2.0_src/docs/RNXCMP.txt`. The format is due to

> Hatanaka, Y. (2008), A Compression Format and Tools for GNSS Observation Data,
> Bulletin of the Geospatial Information Authority of Japan, 55, 21–30.

The GSI licence asks anyone who ports or modifies the tools to cite that paper.

Where the C programs and "the format" could differ, **the decoder follows what CRX2RNX
4.2.0 does**, because PLAN §3.2 requires byte equality with it. Places where we
deliberately do something else are listed in §9.

## 1. Versions

| CRINEX | Written for | Line 1, columns 1–3 |
|---|---|---|
| 1.0 | RINEX 2.xx | `1.0` |
| 3.0 | RINEX 3.xx, 4.00, 4.01 | `3.0` |
| 3.1 | RINEX 4.02 and later (adds the picosecond record, §6) | `3.1` |

E:393–396 picks the version from the RINEX version (`>= 4.02` → 3.1, `2` → 1.0, else 3.0).
C:413–417 accepts exactly `1.0`, `3.0` or `3.1` in columns 1–3. Two numbers are derived
(C:414–415): `crinex_version = atoi(line)` (1 or 3) and `crinex_version_full`
(10, 30 or 31). The RINEX major version is `atoi()` of the RINEX VERSION / TYPE line
(C:425): 2 selects the RINEX 2 layout everywhere, anything else the RINEX 3/4 layout.

## 2. Lines

* A line ends at LF. One CR immediately before the LF is removed (C:110 `CHOP_CR`,
  C:863–865 `read_chk_line`). Other CRs are data.
* CRX2RNX reads lines with `fgets(…, 2048)`. A header, clock or data line without a final
  LF is "truncated" (C:854–858, error 8). A final *epoch* line without LF is read normally
  (C:218).
* `CHOP_BLANK` (C:111) removes trailing blanks (only `' '`), but a line made only of
  blanks keeps **one** blank. All header lines, event lines and epoch lines are written
  out through it, so CRX2RNX output never has trailing blanks, except a 1-blank line.

## 3. Header

| CRX line | Content | CRX2RNX |
|---|---|---|
| 1 | `CRINEX VERS   / TYPE`, version in cols 1–3, label at col 61 | checked, not printed (C:413–417) |
| 2 | `CRINEX PROG / DATE` | read, not printed (C:418) |
| 3 | `RINEX VERSION / TYPE` of the original | printed; label must be at col 61 and col 6 must be `2`, `3` or `4` (C:420–425) |
| 4… | the rest of the RINEX header, verbatim | printed after `CHOP_BLANK`, up to and including `END OF HEADER` (C:427–437) |

While copying the header, CRX2RNX takes the number of observation types from
`# / TYPES OF OBSERV` (RINEX 2: `ntype = atoi(line)` when col 6 is not blank) and from
`SYS / # / OBS TYPES` (RINEX 3/4: `ntype_gnss[sys] = atoi(&line[3])` when col 1 is not
blank) (C:431–436). The label test reads columns 61–79 of a 2048-byte buffer that is
reused line after line, so a line shorter than 59 characters is compared against
whatever an earlier, longer line left there. We emulate that buffer exactly (§9).

The encoder writes line 1 as `"%-20.20s%-40.40s%-20.20s"` (version, `COMPACT RINEX
FORMAT`, label) and line 2 as program name (40 chars), date `%d-%b-%y %H:%M` UTC
(20 chars) and `CRINEX PROG / DATE` (E:393–400). Every RINEX header line is copied after
its trailing blanks are removed (E:402–411).

## 4. Epoch line (text-differenced)

The epoch line of the CRX file is the RINEX epoch line, rearranged so that it holds the
whole satellite list and no clock:

* **RINEX 2 / CRINEX 1.0:** RINEX columns 1–68 (the satellite list stops at col 68), then
  the satellite IDs of all continuation lines appended, 3 characters each (E:255,
  E:609–625). The clock (cols 69–80) is moved to the clock line. Old files whose
  continuation lines lack the 32 leading blanks are read too (E:617–621) and come back in
  the standard layout.
* **RINEX 3/4 / CRINEX 3.x:** RINEX columns 1–41 (padded with blanks to 41, E:457), then
  the satellite IDs taken from the first 3 columns of each observation line (E:708).

Each epoch line is written as a **text difference** against the previous epoch line
(E:673–694 `strdiff`), and rebuilt with `repair` (C:691–705):

| Difference character | Meaning |
|---|---|
| blank | character unchanged |
| `&` | character becomes a blank |
| anything else | the new character |

If the new line is longer than the old one, the extra characters are copied as they are.
If it is shorter, each non-blank character of the old line beyond the end becomes `&`.
Trailing blanks of the difference are removed (E:691–692), so an unchanged line is empty.

**Re-initialisation.** The encoder starts with `oldline = "&"` and resets it to `"&"`
after every event record (E:149, E:484–489). The first character of an epoch line is
therefore `&` for RINEX 2 (blank in RINEX) or `>` for RINEX 3 (because `'>'` differs from
`'&'`). CRX2RNX treats a line starting with `ep_top_from` (`&` for CRINEX 1, `>` for
CRINEX 3) as a fresh epoch: the first character becomes `ep_top_to` (blank / `>`), the
previous epoch text is discarded and every satellite is new (C:229–236). In ordinary
epochs the first character of the difference is a blank.

After `repair`, CRX2RNX checks the line (C:242–247); with `offset` 3 (RINEX 2) or 6
(RINEX 3/4) it needs `line[0] == ep_top_to`, `strlen(line) >= 26+offset`, blanks at
`offset+23` and `offset+24` and a digit (the epoch flag) at `offset+25`. Failing that,
CRX2RNX skips to the next initialised epoch and prints a flag-4 comment
`*** Some epochs are skipped by CRX2RNX ***` with exit code 2 (C:535–569). **We raise
`CorruptError` (rule `CRX.EPOCH`) instead.**

Then trailing blanks are removed (C:248), `nsat = atoi(&line[29])` (RINEX 2) or
`atoi(&line[32])` (RINEX 3/4) (C:250), and the satellite list starts at col 33 / col 42
(C:205, C:213). Each satellite is matched with the previous epoch's list by its 3-character
ID (C:605–614); unmatched satellites are new (their arcs must be initialised).

**CRINEX 3 escape lines.** In CRINEX 3, a line starting with `&` where an epoch line is
expected is skipped (C:222–228). The skip also applies after event records (C:523).

**DOS EOF.** A line starting with `\x1a` where an epoch line is expected ends the file
successfully (C:237–239).

## 5. Clock line (numeric difference)

The line after the epoch line holds the receiver clock offset (C:255–266), as an integer
with the decimal point removed: units of 10⁻⁹ s for RINEX 2 (`F12.9`), 10⁻¹² s for RINEX 3/4
(`F15.12`) (E:530–543: the point is moved right by 1 or 4 digits). An empty line means
"no clock in this epoch" (C:445–446) and resets the clock arc.

`N&value` starts a new arc of difference order N (C:448–453), and the value is the clock
itself. In the following epochs the line holds the next difference: order 1, 2, … up to
N, then stays at N (C:469–492). Our encoder uses N = 3, like RNX2CRX (E:106, E:541,
E:826). A clock that comes back after a gap always starts with `3&` (E:249, E:541).

Numbers are split into an upper part and the lower 8 digits in C (C:454–465); a value
`-0ddddddddd` (a minus, leading zero, at least 9 digits) loses its sign there. We
reproduce that.

**Output** (`print_clock`, C:809–848): the clock is printed as 12 (RINEX 2) or 15
(RINEX 3/4) characters, with **no leading zero** before the decimal point
(`  .123456789`, ` -.000123456789`). CRX2RNX 4.2.0 prints a wrong value when the clock is
negative and its last 8 digits are all zero (the "extra digit" at C:821–822 uses the sign
of the lower part only): for example `-100000000` (RINEX 2, −0.1 s) comes out as
` -.000000000`. We reproduce this by default; our encoder refuses to write such a clock
(§8).

RINEX 2 epoch line: `"%-68.68s"` + clock + LF when there is a clock, else `"%.68s"` + LF;
then one continuation line per further 12 satellites, `32 blanks + "%.36s"` (C:282–290).
RINEX 3/4: `"%.41s"` + clock, or `"%.41s"` with trailing whitespace removed when there is
no clock (C:294–320).

## 6. CRINEX 3.1: the picosecond record

RINEX 4.02 Table A3 (`specs/text/rinex_4.02.txt`, page 69) allows, after the receiver
clock (`F15.12`, cols 42–56), an optional `1X,I5.5` field: 5 more digits of the epoch
second, giving picosecond resolution. The full RINEX epoch line is then 62 characters.

* Encoder (E:228–243, E:282–288): when the RINEX version is ≥ 4.02 and the epoch line,
  after trailing blanks are removed, is exactly 62 characters long, columns 58–62 must be
  five digits. They are text-differenced against the previous epoch's picosecond text
  (initially empty) and appended to the clock line after one blank: `"<clock> <diff>"`.
  The trailing-blank trim of `strdiff` also eats the separating blank when the
  picosecond text is unchanged, and an absent clock leaves the clock part empty
  (`" 12345"`).
* Decoder (C:259–266, C:878–997): for CRINEX 3.1 the clock line is split at its first
  blank into the clock part (at most 31 characters) and the picosecond difference (at
  most 5); anything longer is error 17. A non-empty picosecond difference is applied with
  `repair` to the stored picosecond text (C:277). The stored text is never cleared, so
  once set it is printed in every later epoch.
* Output (C:296–314): clock and picosecond → `"%.41s"` + clock + `" %5.5s"`;
  picosecond only → `"%.41s"` + 16 blanks + `"%5.5s"`.

Because the stored text is never cleared, a file in which some epochs carry the
picosecond field and later ones do not cannot be represented: CRX2RNX would repeat the
old value. Our encoder refuses such files (`CRX.ENC.PICOSEC`).

## 7. Observation lines (numeric and flag differences)

One CRX line per satellite (C:268–271, `getdiff` C:707–770). The line holds `ntype`
fields separated by single blanks, then the flag difference:

```
field_1 field_2 … field_ntype flags
```

* `ntype` is `ntype` (RINEX 2) or `ntype_gnss[system letter]` (RINEX 3/4; an undefined
  system is error 20, C:579–582).
* The split (C:715–724) counts blanks: the text after the `ntype`-th blank is the flag
  difference, so it may contain blanks. A line that ends early leaves the remaining fields
  empty and the flag difference empty.
* **Empty field = missing observation** (C:731–734). Its arc ends; the next value must
  start a new arc (error 12 otherwise, C:745–748).
* `N&value` starts an arc of order N (C:736–740); in a new satellite every non-empty
  field must do so (error 11, C:741–744). Otherwise the field holds the next difference and
  the order rises by one per epoch up to N (C:749–753).
* Values are integers: the observation × 1000 (F14.3 without the point). The decoder
  rebuilds the value by summing differences (C:657–665) and prints it as F14.3
  (`putfield`, C:772–807) with **no leading zero** (`.123`, `-.123`, and zero as
  `.000`). A value outside the F14.3 range is error 17. Like the clock, a field is split
  into an upper part and its lower 5 digits (C:755–765), so `-000123` (a minus, leading
  zeros, at least 6 digits) is read as +123; RNX2CRX never writes leading zeros.
* The encoder (E:627–671) uses order 3 and restarts the arc (`3&value`) when a satellite
  is new, when the field was blank in the previous epoch, or when the *upper part*
  (`value / 100000`, truncated) of the 3rd difference exceeds 100000 in magnitude
  (E:648–651, "large cycle slip"). Numbers are written with `%ld` (E:800–814).

**Flags** (LLI and SSI, 2 characters per field, in field order) are text-differenced
against the satellite's flags in the previous epoch, with the same blank/`&` rules as the
epoch line (E:668):

* CRINEX 3, new satellite: all 2·ntype characters are written, blanks as `&`, nothing
  trimmed (E:663–666). CRX2RNX takes the difference with `&` → blank as the flags
  (C:645–646, C:653).
* CRINEX 1, new satellite: the flags are written as they are, trailing blanks trimmed
  (E:662); CRX2RNX pads them with blanks to 2·ntype (C:647–648).
* CRINEX 1 assumes the flags of a blank field are blank: the encoder resets the old flags
  of a blank field (E:654–657) and refuses a blank field with flags (E:743, error 20);
  the decoder prints 16 blanks and resets them (C:670–672).
* CRINEX 3 keeps flags of blank fields: CRX2RNX prints 14 blanks and the two flag
  characters (C:673–675).

**Output layout** (C:633–682): RINEX 3/4 writes the 3-character satellite ID and all fields
on one line; RINEX 2 writes 5 fields per line. Trailing blanks of each line are removed,
so a RINEX 2 line of five blank fields comes out as an empty line.

## 8. Event records (epoch flag > 1)

The encoder (E:220–224, E:491–528) writes an event epoch line verbatim except that RINEX 2
lines get `&` as their first character (RINEX 3 lines start with `>` already), then
the number of special records announced in the line (`atoi` of cols 30–32 / 33–35),
verbatim. Then it re-initialises everything (E:484–489). Header lines inside the event can
change `# / TYPES OF OBSERV` or `SYS / # / OBS TYPES` (E:505–509, E:521–525).

CRX2RNX (C:494–533) prints the event line (first character → `ep_top_to`) and, if the line
is longer than 29 characters, `atoi(&line[29])` / `atoi(&line[32])` further lines, all
through `CHOP_BLANK`, updating `ntype`/`ntype_gnss` like the header does. The next
epoch line (after any CRINEX 3 escape lines) must be an initialised epoch line with a digit
for its flag, else error 9 (C:520–531). End of file right after an event is a normal end.

## 9. Where our codec differs from the C programs

Decoder (`crx_to_rnx`), relative to CRX2RNX 4.2.0:

1. **Fails closed.** Every situation where CRX2RNX would print an error, skip epochs, or
   read memory it never wrote (a satellite list shorter than `3·nsat`, new-satellite
   CRINEX 3 flags shorter than `2·ntype`, NUL bytes, non-numeric fields such as `12a`,
   `3&` with no digits) raises `CorruptError` with a rule ID. CRX2RNX's `-s` (skip) mode
   is not offered.
2. **The same table sizes.** Like CRX2RNX we refuse more than 100 satellites per epoch
   (`CRX.MAXSAT`, its error 6), more than 100 observation types (`CRX.MAXTYPE`, error 16;
   CRX2RNX has no test for RINEX 2 and would overrun its arrays), arc orders above 5
   (`CRX.ARC_ORDER`, error 7; the format would allow 9) and lines longer than 2046
   characters (`CRX.LINE_TOO_LONG`, error 13).
3. **Line endings.** We emulate CRX2RNX as built on Unix: one CR before LF is removed;
   output uses LF. The Windows build reads and writes in text mode, so its output has CRLF
   and a `\x1a` anywhere ends its input; the corpus comparison maps LF → CRLF. Only
   inputs with `\r\r\n` or a stray `\x1a` can tell the two apart.
4. The stale-buffer behaviour of the header/event label tests and of the epoch flag is
   reproduced with a byte buffer that is updated the way `fgets`, `CHOP_CR`, `CHOP_BLANK`
   and `read_clock` update CRX2RNX's buffers. Values that would overflow a 32-bit `long`
   in CRX2RNX (Windows `long` is 32-bit) are not reproduced; out-of-range results raise
   `CRX.RANGE`.
5. Two value quirks of CRX2RNX are reproduced because they are what it prints, and checked
   against the exe: a negative clock whose last 8 digits are zero (§5; `fix_clock_bug=True`
   prints the true value instead), and the lost sign of a numeric field `-0ddddd…` (§5, §7;
   RNX2CRX never writes leading zeros).
6. On an error, `iter_crx_to_rnx` first yields exactly what CRX2RNX would have printed
   before stopping (whole epochs, event lines, header lines), then raises.

Encoder (`rnx_to_crx`), relative to RNX2CRX 4.2.0: it follows the same choices (order 3,
the 100000 slip threshold on the upper part, the same text differences and layout), but
refuses (`CorruptError`) any input that RNX2CRX would silently change or that CRX2RNX
would not give back, instead of warning or skipping:

* fields that are not `F14.3` + 2 flag characters or 14 blanks + 2 flags; a `&` or a
  non-printable character where text is differenced (epoch line, flags), or a line that
  would end in a CR;
* clock fields not exactly `F12.9` (RINEX 2) or `F15.12` (RINEX 3/4) — RNX2CRX misreads
  other widths and ignores text after the clock — and clock values CRX2RNX 4.2.0 would
  print wrongly (`CRX.ENC.CLOCKBUG`, §5);
* picosecond fields that are not five digits, and files where they stop part-way (§6);
* RINEX 3/4 epochs with a clock or picosecond field but no satellites (CRX2RNX would print
  the clock at the wrong column);
* epoch lines that CRX2RNX's own check (C:243) would reject, even where RNX2CRX's looser
  check (E:440–459) accepts them;
* satellite lists whose length does not match the count; duplicate satellites; more than
  100 satellites or observation types (CRX2RNX could not read the result); a system with
  zero observation types (CRX2RNX would glue its id to the next line); RINEX 2 blank
  fields with flags (as RNX2CRX, error 20); trailing empty lines (as RNX2CRX, error 6).

Where RNX2CRX is stricter than needed, the encoder is lenient: the version field may read
`2.1` or `2` (RNX2CRX 4.2.0 refuses `2.1`; two corpus files use it), a missing final LF is
accepted, and a value written with leading zeros and a minus sign (`-00012.345`, where
RNX2CRX loses the sign) is encoded with its true value. Header and event lines are
emulated through the same stale buffer as the decoder, so the encoder sees the observation
type counts that CRX2RNX will see.

Value formatting is not preserved by any Hatanaka round trip: CRX2RNX prints `.123`
rather than `0.123`, `-.000123456789` rather than `-0.000123456789`, and drops trailing
blanks. The guarantee is therefore `crx_to_rnx(rnx_to_crx(r)) == r` for files `r` already
in CRX2RNX's layout (for example any output of `crx_to_rnx`), and the same *values* for any
other valid file.

The `CRINEX PROG / DATE` line of our encoder names `rinexcore` (not RNX2CRX) and takes an
explicit date, so output can be made reproducible.

## 10. Verification (2026-10-30)

Run with `tools/check_hatanaka.py`; digests in `tests/oracle/crx2rnx_sha256.json`.

* **Decoder vs CRX2RNX 4.2.0:** 299/299 corpus CRX files (CRINEX 1.0: 116, 3.0: 183)
  byte-identical (4.52 GB of RINEX). CRX2RNX exits 0 with no message on all 299.
* **Encoder:** for every decoded corpus file `r`, `crx_to_rnx(rnx_to_crx(r)) == r` (299/299)
  and CRX2RNX applied to our output returns `r` (299/299).
* **Re-encoding the original CRX:** all 245 files written by RNX2CRX 4.x come out
  identical apart from line 2 (223 byte for byte; 17 differ only because the original has
  CRLF line ends; 5 are RINEX 4.02 files that RNX2CRX 4.1.0 wrote as CRINEX 3.0, where
  4.2.0 and we write 3.1). The other 54 were written by RNX2CRX 2.x betas or receiver
  firmware (Alloy, NetR9): 33 differ in trailing blanks and 19 in where an arc restarts
  (those versions used a different slip rule), 2 are identical.
* **CRINEX 3.1:** no corpus file uses it. A RINEX 4.02 fixture with picosecond epochs
  (with and without clock, unchanged values, an event, a slip) is encoded by us as
  CRINEX 3.1 and CRX2RNX returns it exactly; archived with its digests.
* **Encoder vs RNX2CRX 4.2.0 (2026-11-01, `tools/check_hatanaka.py rnx2crx`; digests in
  `tests/oracle/rnx2crx_sha256.json`):** on every corpus obs file (299 decoded CRX files and
  6 plain ones) RNX2CRX's output and ours are byte-identical apart from line 2, and our
  decoder reads RNX2CRX's output back, except ebre1800.10d and sulp1800.10d, whose version
  field reads `2.1`, which RNX2CRX refuses (the leniency above). RNX2CRX's own CRINEX 3.1
  encoding of the picosecond fixture is archived in full: identical to ours apart from
  line 2, and our decoder gives the fixture back. Live, the two leniencies above are
  confirmed (a missing final LF is "truncated" to RNX2CRX; `-0000000.123` loses its sign),
  every input our encoder refuses is one that RNX2CRX refuses or that CRX2RNX does not give
  back, and a 3,000-case differential fuzz found no other difference (the inputs we refuse
  that the official pair carries all fail our validator: `&` or bytes 0x80-0xFF in epoch
  lines or fields).
* **Fuzzing:** seeded byte flips, truncation, line deletion/duplication/swaps (including
  bytes 0x80–0xFF in digit positions) raise only `CorruptError`. Against the exe,
  1500 mutated CRX files: every file we decode, CRX2RNX decodes to the same bytes; of the
  files we refuse, CRX2RNX also stops (exit 1) or skips epochs (exit 2) except for those
  with garbage in numeric fields, which its `atol` reads silently. 700 mutated RINEX files:
  whatever our encoder accepts, CRX2RNX decodes exactly as our decoder does.
