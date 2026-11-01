# Decisions

Newest first. Each entry says what was decided, why, and whether the user still has to
confirm it. "Verified" means checked by a test or a corpus run; "assumed" means not yet.

## 2026-11-01 — review round 28 fixes (not yet re-reviewed)

Reviewers: Sonnet 9/10, then 8/10 (a checker hole on BRD400DLR 2026-001); Codex Sol 6.1
(xhigh) 8/10 (not confident, 1 blocker). Sonnet judged the round-27 count rule right.
Fixtures: `tests/unit/test_round28.py`.

- **Unknown leap fields (Sol).** "Zero or blank if not known" (rinex302.txt Table A5 p.63):
  a BeiDou-only `0` became GPS 14, `4 0 0 0` became `18 14 1356 1GPS` (an invented leap
  date), and an unknown `0` merged first overrode a GPS 18 and claimed it lost. Now
  (`leap.known`, `_shift`): an unknown field is kept as written and never shifted, a day goes
  with its week, the BDS-basis rule needs a count above 0, and merges reconcile only known
  fields; the checker the same (`_to_gps`, `_bds_count`, `_leap_gps`). Where writing a
  BeiDou-only 3.02 output in BDS terms would turn a known field into 0 (a past leap of 14 s),
  the GPS terms stay, which the count rule reads back as GPS.
- **Subtype claims counted exactly (Sonnet).** From 3.02 several QZSS sets are kept, and
  deleting one of the J:LNAV / J:CNVX `nav-subtype-not-representable` claims passed on
  BRD400DLR 2026-001. `compare_nav` now finds, for each kept Klobuchar set, the input record
  it came from (first in file order of its place with its values) and requires each
  (system, message) claim to equal the count of kept sets from subtyped records.

Unit suite: 851 passed, 26 skipped, 13 xfailed. Fresh generator seeds on this code
(140000-140499): 29,027 subtests pass. These fixes have not been through a review round.

**Corpus run 18** (started on round-23 code; later fixes landed while its obs rows ran, so it
spans code versions): 5,280 conversions (726 met, 1,199 nav, 3,355 obs), 5,208 converted, 33
refused corrupt, 39 refused not representable (the refusals of earlier runs), 0 problems.
Its nav rows are superseded by the rerun on the final code, data/out/corpus_r18nav6: 1,199
conversions, 0 problems. A full corpus run on the final code is still to do.

## 2026-11-01 — review round 27 fixes

Reviewers: Sonnet 9/10, then 8/10 (a checker false alarm on a real BRD400DLR 4.02 file,
converter right), Codex Sol 6.1 (xhigh) 8/10 (not confident, 2 blockers). Fixtures:
`tests/unit/test_round27.py` (and `test_round26.test_marked_sets_to_301`).

- **Pre-2006 leap week (Sol 1).** `leap.from_gps` blanked a week before BDS week 0; it is
  now negative (I6 holds it) and converts back exactly.
- **Ionosphere sets pair only in their own place (Sonnet, Sol 2).** From 3.02 the checker
  pairs an input set only with an output set in its own (type, time mark, SV) place; sets of
  equal values at other hours had paired out of order (BRD400DLR 2026-001 G24 and three
  other corpus files), and a set left out consumed another place's output.
- **What the third nav corpus rerun (round-26 code) found, 25 rows, all fixed:**
  - ADIS00ETH_R_20262740000_01D_CN, a 3.04 BeiDou-only file with LEAP SECONDS `4 4 573 6`
    and no identifier, in BeiDou terms ("When BDS only file leap seconds specified, weeks
    since 1-Jan-2006": rinex303-305 Table A5): round 26 took it for GPS and wrote
    `-10 -10 _ 5` to 3.02. But KLSQ00GRL and QAQ100GRL (3.05, BeiDou-only, no identifier)
    write `18`, GPS terms ("Blank defaults to GPS"). Real files do both, so the basis is
    decided per record by the count: GPS-UTC has been 14 s or more since 2006 (BDS week 0),
    BDT-UTC 4 s at most, so a count below 14 in a BeiDou-only 3.02-3.05 file without an
    identifier is a BDS one (assumption reported), anything else GPS (`_leap_basis(src,
    rec)`; checker `_bds_count`). A same-version conversion carries the record as written.
    Round 26's "a BeiDou-only 3.02 file is read on the BDS basis" became "when its count is
    below 14"; the writer still uses BDS terms for such outputs, which read back the same.
  - The checker's free-place rule for `nav-correction-extra` counted BeiDou BDGIM (CNVX)
    records against a Klobuchar claim; it now looks at the claim's own model.
  - The pairing above (21 rows).
- **Found while probing, fixed:** 3.05 ionosphere sets marked A/01 and B/02 were written
  unmarked into 3.00/3.01, two GPSA/GPSB pairs in one place; the slot rule now applies to
  RINEX 3-origin sets too (the file's own version carries what it has), and the checker
  rejects two sets in one place. GPSA with SV ID '01' and GPSB with ' 1' are one set (Sol,
  during the round).
- **Generator seeds 120000-120799 found two more, fixed:** the checker's merge rule required
  the leap-seconds-basis assumption for any BeiDou-only input, also when its record had an
  identifier (179 subtests); and 3.x to 4 claimed a deprecated SYS / PHASE SHIFT entry of a
  system the output keeps no type of (BeiDou L1N, no 4.02 code), which the checker, like
  the 3.05 target, leaves to the code claims (`phase_records`: entries of held systems).

Unit suite: 847 passed, 26 skipped, 13 xfailed.

## 2026-11-01 — review round 26 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; its own seeds 90000-90499, 29,181 subtests,
clean), Codex Sol 6.1 (xhigh) 8/10 (not confident, 2 blockers). Fixtures:
`tests/unit/test_round26.py`.

- **BeiDou-only 3.02 outputs (Sol 1).** Round 24 reads a BeiDou-only 3.02 nav file's leap
  count on the BDS basis, so writing must agree: a merge of two such files into 3.02 was
  written GPS 18, read back as BDS 18, and became 32 in 4.02. `leap.for_target(out_basis=
  "BDS")` writes such an output's record in BDS terms, without an identifier (`leap.from_gps`:
  -14 s, week -1356, day -1), with the assumption reported; `navconv._out_basis` says when.
  A 3.05 `4 ... BDT` or a 4.02 `18 ... GPS` BeiDou-only file to 3.02 is now `4 ...`; every
  round trip back to 4.02 gives 18. The checker reads the output on the same basis and
  flags a BeiDou identifier in a version that cannot name it.
- **Ionosphere slots for every system (Sol 2).** Round 25 kept a set per time mark and SV for
  BeiDou only; from 3.02 every system may mark its IONOSPHERIC CORR (rinex305.txt Table A5,
  Note 1), so RINEX 4 to 3.02+ keeps a set per (type, mark, SV) for all; before 3.02 one per
  type, the rest claimed. Corpus RINEX 4 files hold up to ~50 ION records per system (QZSS),
  so RINEX 3 headers from them grow by that many lines instead of losing the sets. The
  checker now rejects a `nav-correction-extra` ION claim whose place is free. Test
  `NavSubtypes.test_mixed_areas_to_v3_one_kept_set` (round 5) now expects two kept QZSS sets
  (hours 00 and 02), and `BeiDouLeapSeconds.test_nav` (round 16) the 3.02 BDS-terms record.

Unit suite: 842 passed, 26 skipped, 13 xfailed.

## 2026-11-01 — review round 25 fixes

Reviewers: Sonnet 9/10, then 8/10 after running the generators on its own seeds (the nav
cutter's refusal check, test side), Codex Sol 6.1 (xhigh) 8/10 (not confident, 3 blockers).
Fixtures: `tests/unit/test_round25.py`.

- **Nav refusals by message type (Sonnet, and Sol 3).** RINEX 2/3 hold an ephemeris only as
  LNAV, FDMA, INAV/FNAV, D1/D2 or SBAS, so GPS CNAV or BeiDou CNV2 cuts are rightly refused
  although the system is held; `test_generated.nav_messages`/`nav_holds` judge a refusal by
  (system, message type). The RINEX 2 refusal message names message types now.
- **BeiDou ionosphere slots (Sol 2).** RINEX 4 to 3 kept one BeiDou Klobuchar set; a 3.02+
  header holds one per time mark and SV, which BDS must give (rinex305.txt Table A5
  p.65-66), so `navcorr._v3_header` keeps a BeiDou set per (model, mark, SV); the other
  systems keep one set per type.
- **Merged leap seconds (Sol 1).** `_merge_leap` reads each input in its own terms (BDS/BDT
  spellings, a BeiDou-only 3.02 file's basis) before reconciling; with a BeiDou-basis input
  the merged record is written in GPS terms (the merged file is not BeiDou only) and the
  assumption reported. A 3.02 BeiDou 4 merged with a GPS 18 gave GPS 4, or a false conflict
  the other way round; now 18 both ways. The checker's merge model does the same.
- **Event GLONASS channels in their columns (found probing Sonnet's polish item).** An
  event's GLONASS SLOT / FRQ # entry one column off ('R02-4') was read as channel **+4** and
  written into the header; others ended in an internal error. `parse_glonass_slots` now
  requires I3,1X,8(A1,I2.2,1X,I2,1X) and refuses anything else (CorruptError HDR.GLOSLOT).
  (The validator still does not check records inside events; noted for later.)

Unit suite: 838 passed, 26 skipped, 13 xfailed.

## 2026-11-01 — review round 24 fixes

Reviewers: Sonnet 8/10 (two blockers, both found by running the generators on fresh seeds),
Codex Sol 6.1 (xhigh) 8/10 (not confident, 3 blockers). Fixtures: `tests/unit/test_round24.py`.

- **Merged nav corrections (Sonnet 2, and the nav cutter seed 20257).** A --merge wrote
  every input's header corrections: one input's GPSA with the other's GPSB, read as one
  Klobuchar set, and two GPUT records. A RINEX 3 header holds one set per type (rinex305.txt
  Table A5; BDS may repeat it per time mark and SV): `navcorr._v3_header` keeps each type
  from the first input that has it, and the others are claimed `nav-correction-extra` (the
  loss table already said "from RINEX 4 records or merged inputs"; its condition now also
  holds for a merge into the inputs' own version). RINEX 2 headers already kept the first;
  RINEX 4 keeps every input's as its own ION/STO record.
- **No satellite left (Sonnet 1).** A NavIC-only 3.05 file to 3.02 keeps no satellite, so
  there is no PRN / # OF OBS line to write; the checker called the record dropped.
- **BeiDou leap seconds (Sol 1, 2).** 3.03 and 3.04 spell the identifier `BDS` (rinex303.txt
  Table A2 p.60, rinex304.txt Table A2 p.65), 3.05 `BDT`: a 3.04 `4 ... BDS` was taken for
  GPS. Both are read as BeiDou now and the target's spelling is written
  (LEAP.BEIDOU-ID-SPELLING); the validator accepts the version's own spelling and warns on
  the other. A 3.02 navigation file has no identifier but counts "since 1-Jan-2006 as
  transmitted by BDS almanac" (rinex302.txt Table A5 p.63) when it is BeiDou only: it is read
  so, reported as assumption `leap-seconds-basis: BDS`, and converted (4.x: GPS terms). The
  corpus has such a file: BOR100POL_R_20262740000_01D_CN ('4' in 2026, BDT-UTC) went to 4.02
  as GPS 4, now 18. 3.02 observation files say "as transmitted by the GPS almanac" only, so
  they are unchanged. The checker applies the same reading and requires the assumption. Test
  BeiDouLeapSeconds of round 16 had expected `BDT` in 3.03; corrected.
- **Nav refusals justified (Sol 3).** The nav cutter now accepts a refusal only if no input
  (merged ones too) has a system the target's navigation files hold (allowed_losses.json
  `nav_systems`), not by the message's wording.
- **Polish (Sol):** the obs generator writes BeiDou LEAP SECONDS (BDS/BDT spellings).
  **(Sonnet):** --drop-unresolvable on a GLONASS-only file now refuses NotRepresentableError
  (was CorruptError from the output check). Not done: a malformed event GLONASS SLOT line
  (one column off) read by pattern ends in an internal error rather than a named refusal.

Unit suite: 833 passed, 26 skipped, 13 xfailed.

## 2026-11-01 — review round 23 fixes

Reviewers: Sonnet 9/10 (confident, no blocker; ran generator seeds 4000-4299 and its own met
generator, all clean), Codex Sol 6.1 (xhigh) 8/10 (not confident, 4 blockers). Fixtures:
`tests/unit/test_round23.py`.

- **RINEX 2.00/2.01 sources (Sol 1).** The round-22 "does the source version define this
  code" lookups had no 2.00/2.01 table: corpus run 16 had 66 crashes (65 in the checker, one
  ValueError in the converter, dubr1800.10d to 2.10). 2.10 added S1, S2 and SBAS to the 2.0x
  types (rinex210.txt section 0.4, l.204-214), so 2.0x defines 2.10's codes without them:
  `codemap.source_defines` (converter) and `codes.source_systems/source_codes/source_valid`
  (independent checks). The generator never wrote 2.00/2.01 files, which is how this
  slipped through.
- **Compact RINEX plain fallback from scratch (Sol 2).** The round-22 fallback reused the
  conversion made for Compact RINEX, so a loss only CRINEX 1.0 needs (LLI/SSI of a blank
  value: flags-on-missing-value-dropped) stayed in the plain output. `CrxCannotHold` now
  propagates to `convert_loaded`, which restores the report snapshot and converts again
  without Compact RINEX, as for `Crx1EventError`.
- **GLONASS channels given late (Sol 3).** A channel first given in an event holds from that
  event on (rinex305.txt section 6.5 p.42); round 22 wrote it into the header, so it also
  covered the satellite's earlier records, with nothing reported. The survey now keeps an
  event's channel only for satellites with no record before that event; one observed
  earlier needs a companion or `--glo-fcn` (reported as a glonass-fcn assumption) or the
  conversion refuses (MissingInformationError), as before round 22. The checker applies the
  same timing.
- **Generated refusals justified (Sol 4).** `test_generated` passed any RinexError. A refusal
  now passes only if it is a NotRepresentableError and the independent code tables find no
  system, or no type (with data, across layouts), of the file in the target
  (`nothing_representable`).
- **Polish:** the generator writes blank values with LLI/SSI. That showed a checker gap:
  the tokens compared value text, so CRX2RNX's `-.982` did not match `-0.982` (the corpus
  inputs are already in CRX2RNX's layout); `tokens._lead0` normalises the leading zero, the
  same F14.3 value.

Found after Sol's report, while testing these fixes:

- **2.00/2.01 sources, header table.** With 2.00/2.01 files added to the generator,
  `obsconv.foreign` asked the header table about 2.00 (ValueError): it now asks 2.10, which
  has none of the RINEX 3 records it tests either. Round 22 had made `glonass_records` call
  it for every GLONASS file to 3.02+, so corpus run 17 (stopped) had 105 such crashes
  (2.00 GLONASS files); fixed before run 18.
- **Checker, declared types per list.** The audit found a count-0 claim of GPS S1S (L1C, no
  RINEX 2 code) in a flag-4 list no data use could be deleted unnoticed: S1W of the header's
  list made the class 'G S1' look held. Each input list is now checked against its own
  output list (`compare_obs`, `paired`), all output lists only where they do not line up.
- **Loss table, blank records across layouts.** A 2.11 list 'L1' whose one record was blank:
  to RINEX 3 the list is rebuilt from columns that hold data, so the record has no column and
  its epoch is emptied (claimed, and checked by compare_obs); `with-record-removal` now holds
  between RINEX 2 and 3/4 as well (allowed_losses.json cite extended).

Also done while Sol reviewed: scratch generators for met files (2,000 seeds: 21,873 clean
conversions, 127 named refusals) and a nav fuzzer from corpus files (random record subsets,
header corrections dropped, merges and --dedupe; 1,000 seeds: 9,844 clean, 320 named
refusals), none with a problem; not in the repository yet.

Unit suite: 824 passed, 26 skipped, 13 xfailed.

## 2026-11-01 — review round 22 fixes

Reviewers: Sonnet 9/10 (confident, no blocker), Codex Sol 6.1 (xhigh) 8/10 (not confident, 5
blockers: one in the converter, four in the independent checks). Fixtures:
`tests/unit/test_round22.py`.

- **GLONASS channels given in events (Sol 1).** A flag-4 event may hold GLONASS SLOT / FRQ #
  for satellites the header's record lacks; header records in events hold from there on
  (rinex305.txt section 6.5 p.42), so those channels are the file's own. The survey collects
  them (`event_slots`); `glonass_records` fills the header's record from them (rule
  OBS.GLONASS-SLOTS-FROM-EVENTS) instead of refusing for want of a channel; the file's own
  version carries its record as written. A header channel wins over an event's for the same
  satellite. The checker accepts output channels that the input's events give.
- **Metadata compared within its own header or event (Sol 2).** ANTENNA: PHASECENTER records
  were pooled over the header and events, so two vectors could trade places unnoticed; they
  are now compared per scope (header with header, each event with its paired output event,
  `headers.event_pairs`), and only the claims add up over the file. An event's GLONASS SLOT /
  FRQ # pairs are compared too (they were skipped as a regenerated record), and an event copy
  dropped for a target without the record (before 3.01) must be claimed.
- **Losses that follow type removal (Sol 3).** The loss table allowed
  `epoch-emptied-by-system-removal` only with a system loss, and `sys-record-not-representable`
  only for a system the target lacks. Both now also follow `obs-code-not-representable`
  claims of that system (conditions `with-record-removal`, `system-gone`); which epochs and
  records that empties is still checked against the files (`compare_obs` `type_emptied`,
  `headers._sys_records`). Policy unchanged: no loss is added to the table.
- **INTERVAL of the kept epochs (Sol 4).** With rule OBS.INTERVAL.FROM-KEPT-EPOCHS the checker
  accepts an output INTERVAL that equals its own recount of the output's sampling (the most
  frequent step between flag 0/1 epochs), and still rejects any other value.
- **RINEX 2 global columns (Sol 5).** To RINEX 2 a kept system's record stays under the one
  global list, blank where its columns are gone (GLONASS C3I/L3I to 2.11); the checker no
  longer expects such an epoch to be emptied.

Also tightened while fixing Sol 2: event LEAP SECONDS are paired within each event (they
were paired over the whole file, so one could move to another event unnoticed), and an
event's GLONASS COD/PHS/BIS values and (2 -> 2) WAVELENGTH FACT L1/2 are compared.

**A structured random generator of valid files** (round 22; kept in the session scratchpad
as `gen_obs.py`, not yet in the repository): a random version, systems and types from the
independent code tables, 3-8 epochs with flags 0/1/6, flag-4 events with comments, LEAP
SECONDS, ANTENNA: PHASECENTER, SYS / PCVS APPLIED, GLONASS SLOT / FRQ # (also supplied late)
and new type lists. Each file is converted to all eleven versions, plain and Compact
RINEX, and checked by the validator, `compare_obs`, the loss table, a decode of the CRX leg
and CRX2RNX. What it found, all fixed (fixtures `test_round22.GeneratedFiles`):

- **Crash: a header list with no target code** (2.11 C2/C5 to 2.10, BeiDou B1C to 3.02) while
  a later flag-4 list has one, and data under the header's list: the header was written with
  0 types and the output failed its own validation (AssertionError). `_header_types` now
  takes the first list with a target code whenever the header's has none; the records
  under the header's list have no target column, are left out and claimed (rule
  OBS.HDR.TYPES-FROM-FIRST-DATA-LIST).
- **Compact RINEX and cycle-slip records.** RNX2CRX and CRX2RNX copy the lines of an epoch
  with event flag 6 as event lines and test columns 61-79 of their line buffer for the
  observation-type label whatever the line's length (rnx2crx.c E:505/E:521, crx2rnx.c
  C:511-516); a record shorter than that, after a flag-4 type list, is read as a type count
  from the stale label: RNX2CRX error 16 (our encoder: CorruptError CRX.ENC.MAXTYPE, a valid
  file refused) or a wrong count. The encoder now raises `CrxCannotHold`
  (CRX.ENC.STALE-LABEL) there, and the engine writes plain RINEX with warning
  OBS.CRX.EVENT-PLAIN, as the user chose for the CRINEX 1.0 flag-6 case (2026-10-31; nothing
  is lost). **For the user:** this extends that choice to RINEX 3/4 Compact output.
- **Compact RINEX and 4.02 picoseconds.** The 4.02 picosecond field is optional per epoch
  (rinex_4.02.txt Table A3); CRINEX 3.1 differences it from the previous epoch's, so where
  it stops part-way CRX2RNX would repeat the last value. The encoder refused such a valid
  file (CorruptError CRX.ENC.PICOSEC); it now raises `CrxCannotHold` there too, and the
  engine writes plain RINEX with warning OBS.CRX.PICOSEC-PLAIN (the same choice). Found when
  the generator learnt picoseconds.
- **RINEX 2 codes a system does not have.** RINEX 2's one list names every code for every
  system; SBAS P2/D2 (and a GLONASS C6, Galileo-only in 2.11) mean nothing for that system
  (rinex211.txt section 10.1.1, Table A1). Values under such a column are claimed and
  counted; an empty column now loses nothing and is not claimed, from RINEX 2 to 2 as from
  2 to 3 already (`map_code`); the checker no longer requires a claim for it, and the loss
  table allows the claim where values exist (`code_not_representable`). Test
  `EveryClaimCountedExactly` had expected the empty `S:L2` claim of the 2.10 example a17.
- **Checker, RINEX 2 targets.** The round-22 rule "a kept system's record always stays" was
  too broad: a record stays while the target list for its type state has any column, and is
  left out when that list is empty (the case above); `compare.has_columns` now says so.

- **Checker, collapses decided per type list.** Two RINEX 3 codes of one RINEX 2 code (SBAS
  S5X and S5Q are both S5) keep one column per list; a code may win in one list and lose in
  another (S5X against S5Q in the header's list, against S5I in a flag-4 list), so both are
  claimed. The checker decided per code over the file and found no column for S5Q to
  collapse into. `compare_obs` now finds the kept column per list: the only colliding column
  not claimed, or, where all are claimed, the choice that makes every claim's count add up;
  the token comparison then shows that the kept column holds its own values. Which column
  the converter prefers (`codemap.collapse_rank`) is policy and stays unchecked.

The generator, 600 seeds, before these fixes: 6,069 clean conversions, 156 with problems
(the cases above) and 375 named refusals (systems or types the target cannot hold at all);
after: 6,225 clean, 0 problems. It is now in the repository, wider (receiver clock offsets,
LLI bits 0-2, 3.00/3.01 blank attributes, SYS / SCALE FACTOR, events with flags 2, 3 and 5,
up to 24 satellites and 15 types): `tests/independent/generate.py`, run by
`tests/unit/test_generated.py` (30 seeds by default; `RINEX_GEN_SEEDS`, `RINEX_GEN_FIRST`).
2,000 seeds of it found the collapse case above (26 of 24,000 subtests), fixed.

Unit suite: 818 passed, 26 skipped, 13 xfailed.

## 2026-11-01 — review round 21 fixes

Reviewers: Sonnet 8/10 (one blocker, the cross-layout counts repair: in the round-20 entry),
Codex Sol 6.1 (xhigh) 8/10 (not confident, 4 blockers). Fixtures: `tests/unit/test_round21.py`.

- **Event copies of ANTENNA: PHASECENTER (Sol 1)** go through the code map as the header's do;
  the checker compares header and event records together.
- **SYS / DCBS APPLIED and SYS / PCVS APPLIED by system (Sol 2).** They name a system (3.00
  allows G/R/E/S: rinex300.txt Table A1 p.29); a record of a system the output does not hold
  (dropped, or with no target type left) is claimed `sys-record-not-representable:<sys>:<LABEL>`
  (loss-table condition `system-gone`), header and events alike (`_filter_sys_record`,
  `_holds`); checker `headers._sys_records`.
- **Records left out, followed through (Sol 3).** A record with no target column (round 20) was
  still counted in TIME OF FIRST/LAST OBS, the counts and the output's systems: a file
  starting with a BeiDou B1C-only epoch failed to 3.02. The survey now records each epoch's
  type list, and kept epochs, present satellites and output systems count only records the
  output writes. The source's TIME OF FIRST/LAST OBS and INTERVAL are checked against the
  source's own epochs (all of them), so records left out are no repair; the output's follow
  the kept epochs (rule OBS.INTERVAL.FROM-KEPT-EPOCHS when that changes INTERVAL). The checker
  counts an epoch whose every record is left out as emptied (`compare_obs` `type_emptied`,
  from the tokenizer's `record_lists`).
- **Optional count records (Sol 4).** A correct # OF SATELLITES without PRN / # OF OBS was a
  repair (and refused under --strict); only the records a file has are checked now
  (`_counts_agree`).

Corpus run 14 (round-20 code plus the counts fix) was stopped at 3,366 rows (all nav and
met, 1,441 obs), 0 problems; run 15 on this code follows. Unit suite: 802 passed, 26 skipped,
13 xfailed; audit mode 3,890 mutations of 159 distinct claims, none survived.

## 2026-11-01 — review round 20 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; a real 3.05 + 4.00 merge clean with 0
mutation survivors; polish: leave a name whose date disagrees with its data unchanged, done),
Codex Sol 6.1 (xhigh) 8/10 (not confident, 3 converter blockers). Fixtures:
`tests/unit/test_round20.py`.

- **ANTENNA: PHASECENTER codes (Sol 1).** The record names a system and an observation code
  (A1,1X,A3,F9.4,2F14.4: rinex305.txt Table A2 p.53); it was copied unchanged, so a 3.02
  BeiDou 'C L1X' (B1I) stayed 'L1X' in 3.05, where it names B1C. The code now goes through
  the data's code map (`_phasecenter`: renamed, or claimed
  `antenna-phasecenter-code-not-representable:<sys>:<code>` when the target has no such code
  or drops the system; carried to the file's own version). The checker compares it by signal
  (`_phasecenter_checks`).
- **PRN / # OF OBS checked against the source (Sol 2).** The source's counts were compared with
  the output's, so a type the target cannot hold (3.05 C1S to 3.00) was a false HDR.COUNTS
  repair and --strict refused the file. They are compared with the source's own data now
  (`_source_count_records`); the output's records are regenerated as before, and the source's
  are kept as written only when they equal them. Count rows compare in any order.
- **A met file with no type left (Sol 3).** A wind-only 3.05 file to 2.10 (WD is from 2.11)
  failed the output check as an internal error; it is refused not representable now.
- **A system none of whose types the target holds (found writing Sol 1's test).** Its
  satellite records were written with no fields, and the output failed its own check (a
  valid 3.05 BeiDou B1C file to 3.02). Such records are left out (each value is claimed
  obs-code-not-representable), and so are the satellites from PRN / # OF OBS.

Unit suite: 797 passed, 26 skipped, 13 xfailed; audit mode 3,858 mutations of 157 distinct
claims, none survived.

**Corpus run 13** (round-16 code, full): 5,280 conversions in 8,543 s; 5,208 converted, 33
refused-corrupt, 39 refused-not-representable (the same files as runs 8 and 10); 0 crashes,
loss-table violations, token problems, idempotence failures and wrapper problems (454 legs);
round trips as before (holb274a00.26d's obs-type order).

**Round 21, Sonnet 8/10 (one blocker).** A wrong source PRN / # OF OBS was corrected
unreported on RINEX 3 -> 2 (the repair check still skipped cross-layout conversions). It runs
for every target now, and the checker requires HDR.COUNTS whenever the input's counts
disagree with its own data (`headers._input_counts_repaired`; inputs whose counts fit either
reading of flag-6 records are not required to have one). Corpus run 14 on this code follows.

## 2026-11-01 — review round 19 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; its round-18 pair, three-version merges with
--dedupe and BDT epochs across midnight all clean; polish: keep the corpus mutation audit in
the repo, now `tools/mutation_audit.py`, README "Tests"), Codex Sol 6.1 (xhigh) 8/10 (not
confident, 2 blockers, 1 polish). Fixtures: `tests/unit/test_round18.py` `SolRound19`.

- **The BDT shift reported as a repair (Sol 1).** TIME OF FIRST OBS was compared with the
  shifted first epoch, so a valid BDT file got HDR.TIME-OF-FIRST-OBS and --strict refused it.
  The source record is now compared with the data in its own time system, before both are
  shifted; a header that disagrees with its own data is still repaired. (`_add_seconds` also
  floors now: Decimal's `//` truncates toward zero.)
- **RINEX 4 records in mixed-version merges (Sol 2).** With a RINEX 3 input the RINEX 4 STO /
  ION / EOP records were not compared (a changed EOP value passed), a duplicate EOP removed
  by --dedupe went uncounted, and QZSS CNVX handling followed the first input's version. The
  checker now keeps each input's tokens with its version: every RINEX 4 input's records are
  judged by their own version; with all inputs RINEX 4 the output must hold exactly those,
  otherwise each must be in the output or be a removed duplicate (records made from RINEX
  2/3 header corrections are matched one by one, as before). The loss table reads rule
  NAV.DEDUPE from the report for `nav-duplicate-removed`.
- **File names after a shift (Sol polish).** A short name's DDD is the day of the first
  record and f its hour (rinex211.txt section 4), a long name's YYYYDDDHHMM its start: when
  the BDT shift moves the first epoch across a day (or hour, year), the name's fields move
  with it, but only those that agreed with the unshifted first epoch (rule
  OBS.TIME-SYSTEM.NAME-DATE; `test3660.16o` becomes `test0010.17o`).

Unit suite: 792 passed, 26 skipped, 13 xfailed; audit mode 3,840 mutations of 154 distinct
claims, none survived.

## 2026-11-01 — review round 18 fixes

Reviewers: Sonnet 8/10 (the converter right in all it checked; one checker false alarm on a
real 4.02 merge; polish: MERGED FILE count), Codex Sol 6.1 (xhigh) 8/10 (not confident, 4
blockers, 1 polish). Fixtures: `tests/unit/test_round16.py` `MergedRinex4Records`,
`tests/unit/test_round18.py`.

- **Merged STO pairing (Sonnet 1).** The checker paired input and output STO records greedily
  in input order; a merge sorts records by epoch, so equal-valued records of other epochs
  paired off and their reference times looked changed. It now prefers the output record whose
  reference time matches too (`compare_nav_meta`).
- **MERGED FILE (Sonnet polish).** "Number of files merged" (rinex_4.02.txt Table A7; section
  6.11: merged files "should indicate it"): a merge now writes the sum of the inputs' numbers
  (an input without the record counts 1; a blank number makes it unknown) (`_merge_count`;
  105 + 85 = 190 for the real pair); to RINEX 2/3 each input's record is claimed.
- **BeiDou time in observation files (Sol 1).** TIME OF FIRST OBS allows GPS/GLO in 2.10,
  GPS/GLO/GAL in 2.11-3.01, + QZS/BDT in 3.02, + IRN from 3.03. A BDT file went to 2.11 still
  tagged BDT. Now every epoch (data and events) and TIME OF FIRST/LAST OBS is written 14 s
  later, in GPS time (BDT is 14 s behind GPS time, rinex305.txt l.805), rule and warning
  OBS.TIME-SYSTEM.BDT-TO-GPS; QZS, IRN and GAL, aligned with GPS time within tens of ns (below
  the 0.1 us of an epoch), are relabelled GPS with an assumption. The checker shifts a BDT
  input itself (`compare._bdt_to_gps`) and accepts a relabel only with its assumption.
- **--dedupe by value (Sol 2).** The same record with D and E exponents was kept twice; the
  converter now compares values (`_dedupe_value`), the checker's record identity too
  (`headers._body_values`).
- **Mixed-version merges (Sol 3).** The checker expected each record's RINEX 4 message type
  from the first input's version, and the loss table judged every loss by it. A record's own
  type is used now, RINEX 4 record checks run only when every input is RINEX 4, the report
  lists the merged inputs' versions (`input.merged`), and a loss is allowed if some input's
  version allows it.
- **Merged makers and receivers (Sol 4).** A navigation file has one PGM / RUN BY / DATE (only
  observation files add PGM lines: rinex_4.02.txt section 5.2.2); another input's different one
  is claimed `merge-header-record-dropped:PGM / RUN BY / DATE`. "Merged navigation files from
  multiple stations are not to include" REC # / TYPE / VERS (Table A7 note 2): kept only when
  every input has the same one, else every input's is claimed.
- **Blank merged LEAP SECONDS (Sol polish).** Raised TypeError; a blank record now counts as
  none.

Unit suite: 787 passed, 26 skipped, 13 xfailed; audit mode 3,828 mutations of 154 distinct
claims, none survived.

## 2026-11-01 — review round 17 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; polish: explain the BDT week-0 conversion,
done as warning LEAP.BDT-TO-GPS), Codex Sol 6.1 (xhigh) 8/10 (not confident, 2 blockers, both
about --merge). Fixtures: `tests/unit/test_round16.py` `MergedLeapSeconds`.

- **Merged LEAP SECONDS (Sol 1).** The other inputs' LEAP SECONDS were ignored: a second
  input's '18 18 1929 7 GPS' vanished when the first had none (4.02 then got the table's
  current-only 18) or only the current count. `navconv._merge_leap` now takes every input's
  record in GPS terms: records that agree combine, one that disagrees (inputs on either side
  of a leap second) has no room in the one record a file holds and is claimed
  `merge-header-record-dropped:LEAP SECONDS`; the result is converted once for the target.
- **Merges checked against every input (Sol 2).** The checker saw the first input only, so a
  merge claim of any count passed. `compare_nav(..., merged=[...])` now takes the other inputs:
  their EPH records, corrections and EOP records are input too, and `headers._merged_header`
  derives what the output must hold of their header records (COMMENT kept; LICENSE OF USE and
  STATION INFORMATION lines kept once; one DOI and one REC # / TYPE / VERS, others claimed;
  LEAP SECONDS combined or claimed); claims are counted exactly. A report with rule NAV.MERGE
  checked without its other inputs is a problem.
- **A GPS identifier cut off is no loss.** LEAP SECONDS 'n n w d GPS' to 3.01/3.02 (4I6, no
  identifier) was claimed `header-field-not-representable:LEAP SECONDS` by converter and
  checker alike; without an identifier the fields are GPS ones, so nothing is lost. Neither
  claims it now (a BDT record there is converted first, so its identifier never needs one).

Unit suite: 777 passed, 26 skipped, 13 xfailed; audit mode 3,770 mutations of 152 distinct
claims, none survived.

## 2026-11-01 — review round 16 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; its round-15 file re-run clean; polish: say in
the repair that unknown T/W are written 0 0, done), Codex Sol 6.1 (xhigh) 8/10 (not confident,
4 blockers). Fixtures: `tests/unit/test_round16.py`.

- **BeiDou leap seconds (Sol 1).** From 3.03 LEAP SECONDS ends in a time system, "only GPS and
  BDT"; with BDT the values count from 1-Jan-2006, the week is a BDS week and the day 0-6
  (rinex305.txt Table A2 l.3143, Table A5 l.3746). RINEX 4 allows only GPS and says to adapt
  BDS values to GPS conventions (rinex_4.02.txt Tables A2/A7); before 3.03 there is no
  identifier, so the fields are GPS ones. A '4 ... BDT' record went to 4.02 unchanged and to
  2.11 as 4. `rinexconv/leap.py` now converts it exactly where the target cannot hold BDT:
  dtLS_BDS = dtLS - 14 s (rinex_4.02.txt l.943), BDT week 0 = GPS week 1356 (l.871), day + 1
  (rule LEAP.BDT-TO-GPS), then cuts to the target's width as before (obs and nav, header and
  events). The validator checks the identifier (`VAL.HDR.LEAP.SYSTEM`), the checker
  (`check_leap`) derives the GPS values itself. No corpus file has a BDT record (30 have GPS).
- **Merged inputs' header records (Sol 2).** `--merge` kept only the other inputs' COMMENT
  lines. Now their LICENSE OF USE and STATION INFORMATION lines ("Line(s)", rinex_4.02.txt
  Table A7) are added unless already there; a DOI or REC # / TYPE / VERS different from the
  first input's (one per file) is claimed `merge-header-record-dropped:<LABEL>` (loss-table
  condition `merge`: rule NAV.MERGE in the report); to RINEX 2/3 each input's records are
  claimed not representable.
- **The 3.00-3.02 Galileo zero (Sol 3).** The fourth GAL parameter is "zero" in 3.00-3.02
  (rinex302.txt l.3289), a placeholder, not disturbance flags. To RINEX 4 it became flags 0
  with no assumption; it now gets the assumption a blank gets
  (`ion-galileo-disturbance-flags`, source `default:zero-placeholder-in-v3.00-3.02`), and the
  checker reads it as unknown. A non-zero value there is off spec and is kept as data.
- **Foreign records (Sol 4).** A record a file's version does not define is carried as
  written in a same-version conversion: obs (already, for plain records), now met and nav too
  (RINEX 4 records in a 3.0x file), with rule `<KIND>.HDR.NONSTANDARD-CARRIED`. Records the
  converter interprets (SYS / SCALE FACTOR, SYS / PHASE SHIFT, GLONASS SLOT / FRQ #, GLONASS
  COD/PHS/BIS) in a version that does not define them mean nothing to that version's
  readers, so they are never interpreted (a 2.11 SYS / SCALE FACTOR was dropped while the
  report said "applied", and a v2->v3 conversion would have written it, making readers divide
  values nobody had scaled): carried to the file's own version, else claimed
  `header-/event-record-foreign-dropped:<LABEL>`, the target getting its own generated form.
  **A choice for the user to review**: a foreign GLONASS SLOT / FRQ # in a RINEX 2 file is not
  used for channels (--nav or --glo-fcn give them); using it, reported as an assumption, would
  also be defensible. A corpus scan found no such record (19 3.03 files have a RINEX 2
  WAVELENGTH FACT L1/2, which keeps its own handling; one 3.05 file a DOI).

Corpus run 12 (round-14 code) was cut off by the session end at 4,169 rows (all nav and met,
2,244 obs): 0 problems. Run 13 on this code: below when finished. Unit suite: 772 passed, 26
skipped, 13 xfailed; audit mode 3,736 mutations of 147 distinct claims, none survived.

## 2026-10-31 — review round 15 fixes

- **A correction under another version's label (Sonnet 1, a real corpus file).**
  `nav/v3.02/BOR100POL_R_20262740000_01D_SN` (cnvtToRINEX 3.09) writes its SBUT TIME SYSTEM
  CORR, a0 and a1 only, under the RINEX 2 label CORR TO SYSTEM TIME. The nav header writer
  consumes every correction label, but the readers went by the file's version (RINEX 3: only
  IONOSPHERIC CORR and TIME SYSTEM CORR), so the correction vanished from all 11 targets with
  no repair, claim or finding; the checker read labels by version too, so corpus runs 10-12
  passed it. `navcorr._read_foreign` now reads every correction label by its own layout in any
  version (a CORR TO SYSTEM TIME whose columns 1-4 are a time-system code as TIME SYSTEM CORR,
  rinex305.txt Table A5; a0/a1 without T and W read by pattern), reports
  `NAV.HDR.FOREIGN-LABEL`, and carries the record as written in a same-version conversion
  (which then changes nothing); other targets get it converted. The checker
  (`headers.nav_corrections`) reads both versions' labels in every file. A corpus scan found one
  other file with a foreign label, `nav/v4.00/BRDX00DLR_..._MN` (TIME SYSTEM CORR in a RINEX 4
  header); it stays refused-corrupt for its damaged data. Both files re-run on all targets:
  BOR100POL SN 11 converted, 0 problems. Fixtures: `test_round14.py`
  `CorrectionUnderAnotherVersionsLabel` (the file's record, and v2/v3 labels both ways).

- **Legacy SBAS ids upgraded to RINEX 4 (Sol 1).** The 1X,A5,1X field of 2.11 D-UTC and
  RINEX 3 TIME SYSTEM CORR holds a satellite ('Snn', 'G10') or a provider name (EGNOS, WAAS,
  MSAS: rinex211.txt Table A15, rinex305.txt Table A5); RINEX 4 STO records keep them apart
  (rinex_4.02.txt Table A33). The readers put the field in one slot by format, so 3.05 'EGNOS'
  became an STO record without a provider and 2.11 'S27' a provider. `navcorr._sat_or_provider`
  now tells them apart; a provider of a code other than SBUT has no RINEX 4 field and is
  claimed (`:SBAS-ID:`). The checker verifies an upgraded STO record's satellite, SBAS ID and
  UTC ID.
- **Ionosphere transmission time and satellite (Sol 2).** RINEX 4 ION records carry both
  (Table A35); 3.02+ IONOSPHERIC CORR keeps the hour as a time mark A-X and the PRN as SV ID
  (rinex305.txt Table A5 p.64-65, optional except for BDS); 3.00/3.01 and RINEX 2 keep
  neither. The time mark is now written for every system, not only BDS; what has no room is
  claimed per record (`:ION-TTM:<sys>`, the date, minutes and seconds always; `:ION-SAT:<sys>`);
  a 3.02+ set's marks go to 3.00/3.01 stripped (they were copied into columns those versions
  do not define) and claimed. The checker derives the same (`headers._ion_fields`).
- **`--approx-position` (Sol polish).** NaN, infinities and values that do not fit F14.4
  escaped as AssertionError/OverflowError; `engine.check_options` makes them an
  InvocationError (exit 2), for the CLI and the library alike.
- **Another reading for the user.** A RINEX 3 SBUT with UTC number 5 ('Europe Lab') becomes
  the RINEX 4 UTC ID 'UTC(Europe Lab)', which 4.02 Table 27 (p.43-44) does not list (its SBAS
  entries are UTC(USNO), UTC(NICT), UTC(NIST), UTC(OP), UTC(NTSC)); EGNOS's would presumably be
  UTC(OP). Kept as is and put to the user with the other UTC readings.

Unit suite: 764 passed, 26 skipped, 13 xfailed; audit mode 3,706 mutations of 143 distinct
claims, none survived. Fixtures: `tests/unit/test_round15.py`.

## 2026-10-31 — review round 14 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; its own mutation audit of 11 conversions had
no survivor; polish: document the audit mode, done in the README), Codex Sol 6.1 (xhigh) 8/10
(not confident, 3 blockers, all in the converter). Fixtures: `tests/unit/test_round14.py`.

- **A system declared only by a flag-4 event (Sol 1).** Galileo declared in an event and never
  observed vanished from a RINEX 3/4 output, unreported (the round-13 count-0 check rejects
  it). `choose_systems` took the data's systems and the header's type lists only; it now takes
  every type list's systems.
- **STO fields with no room (Sol 2).** A RINEX 4 STO record's transmission time t_tm
  (rinex_4.02.txt Table A33) has no RINEX 2/3 field, and GPS DELTA-UTC has no satellite field
  (rinex211.txt Table A3); both went unclaimed. Now claimed per record written:
  `header-field-not-representable:STO-TTM:<code>`, `:STO-SAT:<code>`, and for DELTA-UTC a UTC
  id other than USNO (`:DELTA-UTC:UTC-ID:<id>`).
- **SBAS provider ids wider than A5 (Sol 3).** 2.11 D-UTC and RINEX 3 TIME SYSTEM CORR hold
  one 1X,A5,1X field: the SBAS provider "derived from MT17" (EGNOS, WAAS, MSAS), else the MT12
  satellite as 'Snn' (rinex211.txt Table A15, rinex305.txt Table A5). 'A-SBAS' was written in
  six columns and pushed the UTC identifier out of its I2. `navcorr._ident` writes the provider
  when it fits, else the satellite, and claims what has no room (`:SBAS-ID:<id>`,
  `:STO-SAT:<code>`); a v4 SBUT record to RINEX 3 now writes its provider rather than its
  satellite, as the spec text says. `navcorr._utc` writes a UTC id the target cannot number
  (2.11: 1-6; 3.05: 1-7) as 0 and claims it (`:D-UTC:UTC-ID:` / `:TIME SYSTEM CORR:UTC-ID:`).
  The validator now requires the 1X separators around that field to be blank
  (`VAL.HDR.SEPARATOR`), so such an overflow fails the output check; the real file BOR100POL
  (values three columns right) gets that error too, added to its known violations.
- **The checker** (`headers._sto_fields`) derives the same from the specs for every time
  correction written into another record type: the A5 field's content, the UTC number, and
  which of t_tm, satellite, provider and UTC id are lost; each claim is counted exactly.

Corpus run 11 (round-13 code) was stopped at 3,685 rows (all met and nav, 1,760 obs) with no
problem, to rerun on this code (run 12). Unit suite: 757 passed, 26 skipped, 13 xfailed; in
audit mode 3,472 mutations of 136 distinct claims, none survived.

## 2026-10-31 — review round 13 fixes: every loss claim counted exactly

Reviewers: Sonnet 9/10 (confident, no blockers; its run of the unit suite matched), Codex
Sol 6.1 (xhigh) 8/10 (not confident, 3 blockers, all in the independent checks; every round-12
reproduction passed). Fixtures: `tests/unit/test_round13.py` (`SolRound13`,
`EveryClaimCountedExactly`).

- **Blank attributes in the phase readers (Sol 1).** The SYS / PHASE SHIFT entry, event and
  output type-list readers of `tests/independent/headers.py` split 'L1 ' to 'L1', so the
  converter's correct claim `phase-shift-entry-dropped:G:L1 ` was "missing". They keep A3
  identity now (`_phase_code`, `_type_codes`).
- **Blank-attribute pseudoranges in the loss table (Sol 2).** A 3.00/3.01 'C1 ' to RINEX 2 is
  claimed not representable (no tracking family: v2 C1 is C/A, P1 is P); `allowed.py` read it
  as representable. It now treats a blank attribute on a GPS/GLONASS band whose v2 codes name a
  family as not representable. Sonnet raised the same case from the other side (polish: could
  'C1 ' map to v2 C1?); it would assert C/A tracking the file does not state, so it stays a
  reported loss unless the user wants otherwise.
- **Counts compared exactly (Sol 3).** Sol deleted claims and set counts to 999 for phase
  records, phase entries, met types and LEAP SECONDS, and the checks passed. Rather than
  patch those four, every claim was mutation-tested: for each loss of a report, the claim
  deleted and its count raised by one must both be rejected. A scratch audit over 52 corpus
  rows (two per loss kind, smallest files) and an opt-in mode of the unit suite
  (`RINEX_MUTATION_AUDIT=<file>`, `tests/conftest.py`) found these survivors, all now caught:
  - phase records: `phase-shift-record-not-representable` (to 2.x/3.00, one per header entry
    when any names a code) and `phase-shift-record-deprecated` (RINEX 3 to 4, one per entry
    of an output system when any has a value), and `phase-shift-entry-dropped` summed over the
    header and every event (`phase_claims`);
  - `event-record-deprecated:*` (was not compared at all) and `event-record-not-representable`
    for SYS / PHASE SHIFT and GLONASS COD/PHS/BIS, whose deletion passed because both are
    regenerated records;
  - `header-record-not-representable:GLONASS SLOT / FRQ #` and `:GLONASS COD/PHS/BIS`
    (`glonass_claims`; a file with no data counts its declared systems, as the converter does);
  - `met-type-not-representable` (the type's input values), `header-field-not-representable:
    LEAP SECONDS` (obs: header and event records; nav: once per input record);
  - claims of count 0: a declared type or system without data that the target cannot hold.
    The converter claims those within one layout, in a file without data and in a type list no
    data epoch uses (across layouts it rebuilds the lists from the columns with data); the
    checker now requires a claim for each such type or system the output lacks
    (`compare_obs`, with `records_by_list` from the tokenizer);
  - `header-field-not-representable:TIME SYSTEM CORR:UTC-ID:*` (a RINEX 4 UTC ID with no 3.05
    number) and `:CORR TO SYSTEM TIME:T-W-S-U` (nav).
- **Two converter fixes the audit turned up (navcorr `_tswu`).** RINEX 2 CORR TO SYSTEM TIME
  holds the reference date and a0 only (rinex211.txt Table A10 l.1689, Table A15 l.1908). For
  2.10 GEO the T-W-S-U claim ignored a RINEX 3 satellite id and a RINEX 4 UTC ID string; for
  GLONASS g files nothing was claimed when T, a satellite or a UTC identifier went. Both now
  claim it; the loss-table cite names the record.
- **A reading for the user to confirm.** RINEX 4.02 names UTC sources (UTCGAL, UTC(NICT),
  UTC(NPLI), UTCIRN, UTC(OP), rinex_4.02.txt Table 27); 3.05 numbers them (1 NIST, 2 USNO, 3 SU,
  4 BIPM, 5 Europe Lab, 6 CRL, 7 NTSC: rinex305.txt Table A5). The converter (navcorr
  `UTC_IDS_REV`) writes UTC(NICT) as 6 (the CRL became part of NICT in 2004) and UTCGAL as 5
  ("Europe Lab"); the checker now uses the same reading. The others are claimed lost.

- **Loss kinds neither audit reached** got a fixture each (`LossKindsNoAuditReached`):
  Galileo disturbance flags, Klobuchar alpha only to RINEX 4, a fractional RINEX 2 nav epoch
  second, receiver clock overflow, an epoch emptied by system removal. Two were wrong:
  `compare_nav` did not model `nav-epoch-precision` at all (RINEX 3/4 nav seconds are I2,
  rinex305.txt Table A6; it now floors the expected epoch, as the converter does, and counts
  the claim), and the converter claimed `clock-precision` as well as `clock-overflow` for a
  clock it drops (`obsconv._clock_v2`: the overflow only).

Corpus mutation audit on the final checker and a full corpus run: below when finished. Unit
suite: 753 passed, 26 skipped, 13 xfailed; in audit mode 3,170 mutations of 121 distinct
claims, none survived.

## 2026-10-31 — cycle-slip epochs in Compact RINEX 1.0: written plain (the user's choice)

The open question from round 11. After an event flag above 1, flag 6 included, RNX2CRX and
CRX2RNX copy one line per satellite (rnx2crx.c `put_event_data`, line 491), so Compact RINEX
1.0 cannot hold a RINEX 2 flag-6 epoch whose records take two lines (more than 5 types) or
whose satellite list continues past 12. Of the three options (refuse, drop the epoch with a
loss, write plain RINEX 2), the user chose **plain RINEX 2 with a warning**: no data lost.

The converter raises `obsconv.Crx1EventError` (a NotRepresentableError) at the first such
epoch; `engine.convert_loaded` restores the report to its state before the attempt and
converts again with `crx=False`, then warns `OBS.CRX1.EVENT-PLAIN`, naming the epoch's input
line. The second pass costs one more conversion, only for such files. This applies whether
Hatanaka came from the input (the default, "as the input") or from an explicit `--crx`: the
output name says which was written (`.YYo`, not `.YYd`), and `report.output.crx` is false.
RINEX 3/4 targets are unaffected (CRINEX 3 copies a flag-6 record per line, which RINEX 3/4
writes unwrapped). The corpus harness accepts a plain output on a `+crx` leg only with the
warning, and then compares it byte for byte with the plain conversion. No corpus file has
such an epoch. Fixtures: `tests/unit/test_round13.py`; `test_round11.py`
`CycleSlipEpochInCompactRinex1.test_written_plain`. Unit suite: 742 passed, 26 skipped, 13 xfailed.

## 2026-10-31 — corpus run 10 (full, on the round-11 code)

5,280 conversions in 8,059 s with 4 workers: 5,208 converted, 33 refused-corrupt, 39
refused-not-representable; 0 crashes, 0 loss-table violations, 0 idempotence failures, 0
token problems (run 8 had 5, all CMUM00THA, fixed in round 4), 0 wrapper problems (454
crx/gz/Z legs, now with the round-11 checks: every leg decoded and compared, CRX2RNX on every
leg). Round trips clean except the known holb274a00.26d obs-type order (v2 -> 3.00 -> v2).
The refusals are the same files as run 8: 11 BRDX00DLR (damaged), 39 E/C/I-only nav files to
RINEX 2, 22 met rows (DARW00AUS, mate1800; both convert with `--lenient`). The round-12
changes touch only blank-attribute codes, STO/ION/EOP identity and the harness's output
count, none of which a corpus row reaches, so this run stands for the current code.
Output: `data/out/corpus_r10/`.

## 2026-10-31 — review round 12 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; asks for an answer to the flag-6 question,
its vote: fall back to plain RINEX 2 with a warning), Codex Sol 6.1 (xhigh) 7/10 (not
confident, 3 blockers, 1 polish). Fixtures: `tests/unit/test_round12.py`.

- **Scale factors on blank-attribute codes (Sol 1: a silent tenfold error).** RINEX 3.00/3.01
  allow a blank attribute ('L1 ', rinex300.txt l.690; 3.02 dropped it, rinex303.txt l.451).
  The type lists keep such a code as A3 'L1 ', but both SYS / SCALE FACTOR readers split on
  blanks ('L1'), so the factor never matched: a 3.00 phase stored x10 went to RINEX 2
  undivided, and a same-version conversion dropped the scale record and kept the stored
  value, with no loss. Both readers now keep A3 identity (`obsconv._a3_codes`), as does the
  SYS / PHASE SHIFT reader.
- **Blank attributes elsewhere (Sol 2).** The validator rejected a 3.01 SYS / PHASE SHIFT
  naming 'L1 '; it now accepts a blank attribute where the version allows one
  (`obscodes.blank_attribute_allowed`). The independent tokenizer read 'L1 ' as 'L1', so a
  claim naming 'L1 ' found nothing; it now keeps A3 identity for RINEX 3 type lists and scale
  factors (`tokens._a3`).
- **Record identity and blank separators (Sol 3).** A repaired blank line after one of two
  identical RINEX 4 STO/ION/EOP records made their identities differ, so `--dedupe` looked
  like a loss; blank lines are left out of the identity.
- **Split outputs counted (Sol polish 1).** `_wrapper_leg` paired outputs with `zip`, so a
  missing split output passed; the counts must now match.

No corpus file has a blank-attribute code (checked: the five 3.00/3.01 obs files), so the
corpus rows are unaffected. Unit suite: 734 passed.

## 2026-10-31 — review round 11 fixes

Reviewers: Sonnet 9/10 (confident, no blockers, 2 polish), Codex Sol 6.1 (xhigh): see the
loop state. Fixtures: `tests/unit/test_round11.py`.

- **RINEX 2 cycle-slip epochs in Compact RINEX 1.0 (Sonnet 1).** After an event flag above
  1, flag 6 included, RNX2CRX and CRX2RNX copy as many lines as the epoch line counts, one per
  satellite (rnx2crx.c `put_event_data`, line 491; our encoder ports it). A RINEX 2 flag-6
  record spans ceil(types / 5) lines, so with more than 5 types (or a satellite list past 12)
  the format cannot hold the epoch: the encoder failed on our own output, reported as
  refused-corrupt on a valid file. It is now refused-not-representable, naming the epoch and
  suggesting `--no-crx`. **Open question for the user:** drop such epochs (cycle-slip records
  are optional information) with a reported loss instead of refusing the Hatanaka output?
  No corpus file has one.
- **System losses counted (Sonnet 2).** `system-not-representable:<s>` and
  `system-removed-unresolvable:<s>` count the system's satellite records; the checker took
  the claim's name only. The tokenizer now counts records per system (`records`) and the
  claim must equal it.
- **The corpus harness skipped a wrapper leg (Sol 1).** When a Compact RINEX leg claimed
  `flags-on-missing-value-dropped`, `_wrapper_leg` compared nothing, so a changed value inside
  the `.crx.gz` passed. The decoded leg is now compared with the input under the leg's own
  report, and CRX2RNX's decoding with ours on every leg.
- **EOP duplicates (Sol 2).** `compare_nav_meta` counted an EOP record removed by `--dedupe`
  as an unclaimed EOP loss. EOP records carry an identity now (system, PRN, message,
  subtype, text); identical ones beyond the first are credited when the claim is present.
- **Repeated identical type lists (Sol 3).** A flag-4 event repeating a list made a new
  state in the tokenizer, while the converter keys states by content, so a collapse spanning
  both was "without a collision". An identical list now reuses its earlier index.
- **LLI zero form (Sol polish 1).** With wavelength factor 2, a v2 LLI 6 became blank in the
  converter (bit 2 cleared first, then bit 1) and '0' in the checker (the other order). Both
  now keep a written LLI written: a result of 0 from a non-blank LLI is '0'
  (rinex305.txt §6.7.1 p.43: blank and 0 both mean no flag).
- **Same-version duplicate code with only flags (Sol polish 2).** The second column of a code
  listed twice was kept only if it held values; one holding only flags was collapsed, a loss
  the loss table refuses for same-version conversions. Flags count too now.

Unit suite: 728 passed. Corpus r9 (round-10 code) stopped at 2,871 rows, 0 problems; r10 on
this code is running.

## 2026-10-31 — review round 10 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; polish: close the spool's temporary file on
an error, done), Codex Sol 6.1 (xhigh) 8/10 (not confident, 3 blockers and 1 polish).
Fixtures: `tests/unit/test_round10.py`, `test_compress.py` `test_member_ending_at_the_piece_limit`.

- **gunzip hung (Sol 1, a regression of the 16 MB pieces).** When a member's output passed a
  piece by one byte, zlib reached the member's end holding the next member in both
  `unused_data` and `unconsumed_tail`; further calls never emptied the tail. The loop now
  stops at the member's end and continues from `unused_data`; `flush()` runs only before the
  end (after it, it decoded the tail a second time). Zero padding between members is skipped,
  as Python's gzip module and gzip(1) do (Sol polish 1; padding at the end already was).
- **Flag-only fields in the loss counts (Sol 2).** The survey counted only values, so a
  dropped column whose fields held only flags was `obs-code-collapsed-empty` (no loss), and
  clearing LLI bit 2 counted only fields with a value. The survey now counts flag-only fields
  per column (`flag_counts`); `obs-code-collapsed` and `obs-code-not-representable` count
  values plus flag-only fields (detail `flag_only`), and `lli-bit2-meaning-differs` every
  field it changes. The checker requires these counts exactly (the bit-2 claim was an upper
  bound, so a forged 0 passed).
- **Nav duplicates (Sol 3).** `compare_nav` allowed `--dedupe` removals for ephemerides only
  and never compared the count: duplicate CNVX records failed, and a claim of 999 for two
  removed ephemerides passed. Removals of every record kind are now summed and must equal
  `nav-duplicate-removed`; `compare_nav_meta` does not count a RINEX 4 correction record
  identical (same text) to one already matched as a loss when the claim is present.

Unit suite: 721 passed.

## 2026-10-31 — review round 9 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; polish: finish the 24 h test), Codex Sol 6.1
(xhigh) 8/10 (not confident, 3 blockers). Fixtures: `tests/unit/test_round9.py`.

- **`--qzss-ion-area` per source file (Sol 1).** Eligibility was decided from the primary
  file's version, so a 4.00 file merged into a 4.02 one lost its CNVX records even with the
  option. Every record is now judged by its own file's version (`_convert_record` already
  was; the gate before it and the conflict check now are too).
- **Coefficients compared as numbers (Sol 3).** The two-sets refusal compared token text, so
  `1.000000000000D-08` and `0.100000000000D-07` were "different sets". It compares values now
  (`navconv._value_or_text`; damaged text under `--lenient` stays text).
- **Flag-only fields compared (Sol 2).** A blank or zero value with an LLI or SSI flag is data
  the converter keeps (blank + flags; cleared bit 2 where the meaning differs; dropped and
  claimed `flags-on-missing-value-dropped` for Compact RINEX 1.0). The independent tokenizer
  skipped such fields, so it neither saw a flag-only column as a collapse partner (Sol's
  `C1C L1C L1W` false alarm) nor noticed a lost flag. They are now items with value `''`,
  counted apart (`flags`, `flags_by_state`): compared like values, accepted as a collapse
  partner, kept when a scaled value rounds to zero, and counted against the Compact RINEX 1.0
  claim.
- **Wavelength-factor rule on observed phases only (found while fixing Sol 2).** For a
  RINEX 2 factor-2 file the converter XORed LLI bit 1 into every L1/L2 field, so a missing
  phase got an LLI '2' it never had. It now applies to fields with a value; flag-only fields
  keep their flags. No corpus file has factor 2, which is why no run showed it.

Unit suite: 711 passed.

## 2026-10-31 — 24 h 1 Hz test, and two whole-file copies removed

**The file.** MIZU00JPN (Mizusawa, Septentrio PolaRx5, G R E C J I S), 2026 day 290: CDDIS
keeps 1 Hz data only as 15-minute Hatanaka files, so `tools/fetch_highrate_day.py` downloads
the 96 of them, decodes them with our decoder, checks they declare the same types and follow
on, and splices one RINEX 3.05 file: 1,576 MB, 86,400 epochs, 5.74 million data lines
(`data/highrate/`, not committed). The header is the first file's, with TIME OF LAST OBS set,
the per-file counts left out and GLONASS SLOT / FRQ # merged over all 96 files (a 15-minute
file lists only the satellites it saw).

**First run: the laptop paged** (7.7 GB RAM, of which the Claude app and Firefox held about
3.6 GB; free RAM fell to 0.7 GB and a reviewer agent stalled). Measured per step with
tracemalloc on synthetic files (scratchpad `mem_steps.py`), two costs grew with the file:
- `engine.load_bytes` decoded and split the whole payload into lines to read its first line,
  then dropped them for obs files: 2.5x the input, about 4 GB here. It now sniffs the version
  line only (`rinexfile.first_line`) and counts line ends on the bytes (`eol_of`, the same
  rule as `split_lines`); obs payloads are never split whole. Load peak at 18 MB: 2.5x -> 1.1x
  (the rest is the reader's fixed 4 MB chunk).
- `rinexfile.join_lines` kept its chunks and then joined them: 2x the output. Growing one
  buffer (BytesIO, bytearray) measured the same 2x peak commit on Windows, so past 64 MB
  (`SPILL_BYTES`) the chunks now go to a temporary file (stdlib `tempfile`, deleted on close)
  and come back in one `read(n)`, which allocates the result once (400 MB test: 802 -> 401 MB
  peak commit). Outputs over 2 GB need one extra copy (Windows caps a read at 2 GB).
Fixtures: `tests/unit/test_memory.py` `NoWholeFileCopies`. Unit suite: 703 passed.

**Second run** (each target alone, through the CLI, peak from GetProcessMemoryInfo):

| target | time | peak commit | result |
|---|---|---|---|
| 4.02 | 215 s | 3,146 MB | converted; loss `phase-shift-record-deprecated` (29); data section identical to the input's, 14,400 epoch lines written in standard F11.7 (`00.0000000` -> ` 0.0000000`) |
| 2.11 | 216 s | 2,512 MB | converted (903 MB); the expected RINEX 2 collapses and unrepresentable header records |
| 3.02 | 209 s | 2,917 MB | converted (1,337 MB); BeiDou-3 signals 3.02 does not define, claimed per code |
| 3.05 `.crx.gz` | 440 s | **5,722 MB** | converted (150 MB), but the laptop paged |
| 3.05 `.crx.gz`, after the codec change below | 412 s | 3,546 MB | converted (150 MB, the same size) |
| that `.crx.gz` as the input -> 4.02 (`.crx.gz` kept) | 496 s | 3,696 MB | converted (150 MB); with GLONASS SLOT / FRQ # merged over the day, no warning |
| that `.crx.gz` as the input -> 2.11 `.crx.gz` (CRINEX 1.0) | 510 s | 3,015 MB | converted; the expected RINEX 2 collapses and unrepresentable codes |

The remaining peak of the plain targets is one copy of the input plus one of the output, as
designed. A file of this size needs about twice its size in free memory; going lower would
mean streaming the output to disk and reading the input through a memory map.

**The Hatanaka leg** had the same two patterns inside the codec, and gunzip a third:
`hatanaka._split_lines` split the whole file into one bytes object per line (6 million for
this file), both codec directions joined their output in memory, and `compress.gunzip` grew
a bytearray and copied it to bytes. The line lists are now an index of line starts
(`hatanaka._Lines`, an `array('q')`: 8 bytes a line, the same indexing and slices), and
`crx_to_rnx`, `rnx_to_crx`, `gunzip` and `join_lines` all write through one helper,
`rinexcore/io/spool.py` (the spill-to-temporary-file join above; gunzip decodes in 16 MB
pieces). `tests/unit/test_memory.py` `CodecsThroughTheSpool` forces the spill path and
requires the same bytes (two gzip members, CRLF, a last line without LF). Unit suite: 712.
`rnx_to_crx` closes its spool in a `finally` (Sonnet round 10 polish: the temporary file
went only at garbage collection when encoding failed).

**A CLI crash the 24 h test found** (by a mistyped input path): `run_one` looked for same-day
nav files next to the input before reading it, and `sibling_nav` listed a folder that did not
exist: a FileNotFoundError traceback instead of exit code 2. The input is now read first, and
an unreadable folder offers no companions. Fixture: `test_streaming_cli.py`
`test_missing_input_is_an_invocation_error`.

## 2026-10-31 — the user's answers to the open policy questions

Asked after corpus run 8; answered the same day.

1. **QZSS CNVX ION area to 4.02:** yes to an option. `--qzss-ion-area WIDE|JAPN` gives every
   QZSS CNVX ION record of a 4.00/4.01 source that area on the way to 4.02 (rinex_4.02.txt
   Table 25 p.40, Table A35 note 3*), reported as assumption `qzss-ion-area/<area>/user`.
   Without it the records are dropped and reported, as before. Both areas are broadcast
   (p.47), so a source with two different CNVX sets for one satellite and time contradicts a
   single area: that refuses as an invocation error. The independent `compare_nav` accepts
   the area only with the assumption, and checks its count.
2. **APPROX POSITION XYZ to RINEX 2:** yes to a teqc-style option. `--approx-position-zero`
   writes `0 0 0` when a RINEX 3/4 source has no position (optional there for moving
   platforms, mandatory in RINEX 2). The spec gives zeros no meaning, so it is reported as
   assumption `approx-position/0 0 0 (unknown)/teqc-convention` plus warning
   `OBS.APPROX-POSITION-ZERO`; `--approx-position X Y Z` wins if both are given, and a source
   with a position keeps it. `headers.py` accepts the zeros only with that assumption.
   Fixtures for both: `tests/unit/test_user_options.py`. Unit suite: 701 passed.
3. **LLI bit 2** cleared and reported where its meaning differs (`--keep-lli-bit2` keeps it):
   confirmed. This settles the older "Open question for the user" further down.
4. **RINEX 2 -> 3 attribute defaults** (codemap.py; `--overrides` changes any): confirmed.
5. **SYS / PHASE SHIFT details:** zero entries carried to 3.01/3.02 (not blank), `1C` read as
   `L1C`, a blank line left out and reported: confirmed.
6. **refused-not-representable** as a fifth outcome (exit code 6): confirmed.
7. **Validator policy 6** (no SYS / PHASE SHIFT needed without phase types): confirmed.

## 2026-10-31 — corpus run 8 (full, on the round-7 code)

5,280 conversions in 8,230 s with 4 workers: 5,208 converted, 33 refused-corrupt, 39
refused-not-representable; 0 crashes, 0 loss-table violations, 0 idempotence failures, 0
wrapper (crx/gz/Z, 454 legs) problems; round trips clean except the known holb274a00.26d
obs-type order (v2 -> 3.00 -> v2). CMUM00THA, refused in run 5, now converts (round 4).

| | obs | nav | met |
|---|---|---|---|
| rows clean | 3,350 | 1,149 | 704 |
| refused (expected) | 0 | 11 BRDX00DLR (damaged) + 39 E/C/I-only files to RINEX 2 | 22 (DARW00AUS, mate1800; both convert with `--lenient`) |
| flagged | 5 (below) | 0 | 0 |

- **CMUM00THA 3.02 -> 3.01..3.05 wrote 'aligned' zeros (converter bug, round 4).** Its only
  `SYS / PHASE SHIFT` line is blank, so nothing can be carried and the same-family fallback
  writes the per-system 'unknown' form. The harness passes `--assume-phase-aligned`, and the
  fallback honoured it, writing `G L1C 0.00000` and so on: a claim of alignment that a source
  record of explicit 'unknown' (`G` alone) never gets, since that is carried as written. The
  flag is for 4.x targets (PLAN §3.3 rule 2; the CLI help says so), so the fallback now
  ignores it. Fixture: `test_round3.py` `EmptyPhaseShiftRecord.test_assume_flag_does_not_turn_it_into_zeros`.
  A header scan of the 154 v3.01-3.05 obs files shows CMUM is the only one that reaches this
  fallback; its 11 targets re-run clean on the fixed code. Unit suite: 688 passed.
- The round-8 checker changes (collapse claims) came after this run's code; every corpus row
  with an `obs-code-collapsed` claim (348) was re-run on the round-8 code: all clean
  (`data/out/corpus_collapse_recheck`).

## 2026-10-31 — review round 8 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; tried to fool the filtered comparison with a
wrong kept column, an over-claim, a swapped and a missing claim: all caught), Codex Sol 6.1
(xhigh) 8/10 (not confident, 3 blockers). Fixtures: `tests/unit/test_round7.py` `SolRound8`.
Not yet re-reviewed.

- **Collapse claims need a collision (Sol 1).** An `obs-code-collapsed` claim is accepted only
  for the type lists where another column of the same signal (`tokens.signal_class`) holds
  values and survives, or where the code is listed twice; its count must equal those lists'
  values. Blanking L1 and claiming it 'collapsed' in a `C1C L1C` file now fails.
- **Collapse per type list (Sol 2).** The tokenizer records every obs-type list in force and
  counts values per list (`lists`, `by_state`), and the filtered re-read drops a collapsed code
  only in the lists where it collided. A code that collapses under the header list but not
  under a later flag-4 list is no longer a false alarm.
- **Unsupported header list replaced before the data (Sol 3).** Round 7 kept an unused list's
  declared types; when none of them exists in the target (e.g. only `X1 `), the output header
  now takes the first list that holds data (rule `OBS.HDR.TYPES-FROM-FIRST-DATA-LIST`), which
  the following event declares again. It failed the gate with an empty type list.

## 2026-10-31 — review round 7 fixes

Reviewers: Sonnet 9/10 (confident, no blockers), Codex Sol 6.1 (xhigh) 8/10 (not confident, 3
blockers). Fixtures: `tests/unit/test_round7.py`.

- **Type list replaced before any data (Sol 1).** For a layout change (RINEX 3 -> 2) each list
  keeps only its columns with data; a header list that a flag-4 list replaces before the first
  observation has none, so it became empty and the file was refused 'not representable'. A
  list no data epoch uses now keeps its declared types, and the refusal looks at every list.
- **Collapsed signal identity (Sol 2).** `compare_obs` now re-reads the input without the
  columns the report claims lost (`obs_tokens(drop=...)`: all of a code's columns, or those
  after its first when a duplicated code collapses), and requires the rest in the output
  exactly. A RINEX 2 L1 holding L1W's value while the report says L1W was the one dropped now
  fails; before, only per-system totals were compared.
- **Rounding expectations (Sol 3)** follow from the same filtered input, so only kept columns
  need a `scale-factor-rounding` claim.
- Sonnet polish: the `HDR.COUNTS` repair message states the counting rule (every satellite of
  flags 0/1/6; observations counted in flag 0/1 epochs).

Corpus: corpus_r7 (round-5 code) stopped at 3,421 rows: only the 20 BRD400DLR 4.02 -> 3.x
rows of the round-5 subtype check's false alarm (fixed in round 6). corpus_r8 runs on the
current code.

## 2026-10-31 — review round 6 fixes

Reviewers: Sonnet 8/10 ("yes for the converter"; one checker false alarm, 9 once fixed),
Codex Sol 6.1 (xhigh) 8/10 (not confident, 5 blockers). Fixtures: `tests/unit/test_round6.py`,
`test_round5.py` `NavSubtypes.test_mixed_areas_to_v3_one_kept_set`.

- **Subtype claim check for RINEX 3 targets (Sonnet 1, Sol 5).** BRD400DLR 4.02 holds QZSS LNAV
  and CNVX sets, each WIDE and JAPN; the RINEX 3 header keeps one, so only its subtype is
  claimed. The check demanded a claim per message type (a false alarm on the corpus), and with
  mixed sources it could not tell which record was kept. It now matches the kept QZSA/QZSB (or
  GPSA/BDSA/IRNA) values, at D12.4 precision, to the input records: if every matching record
  has a subtype the claim is required, if none has it is refused; claims never exceed the kept
  sets.
- **Satellites seen only in cycle-slip records (Sol 1).** They are data too: now listed in
  # OF SATELLITES and PRN / # OF OBS (with no flag 0/1 counts). Such files failed the gate.
- **Compact RINEX 1.0 after scaling (Sol 2).** The removal of LLI/SSI from blank values now runs
  after the value rules, so a scaled value that rounds to blank loses its flags too (claimed
  `flags-on-missing-value-dropped`); `--crx` to 2.x failed with CRX.ENC.FLAG2.
- **Unreadable scaled values (Sol 3).** The load-time survey skips an unreadable value (the
  damage gate refuses the file by default); under `--lenient` the RINEX 2 division refuses it
  as `OBS.DATA.SCALE` (carried undivided it would change meaning). `decimal.InvalidOperation`
  escaped before.
- **Rounding claims per signal (Sol 4).** `compare_obs` expects RINEX 2 rounding only for values
  the output keeps (system and signal not claimed lost) and compares counts per signal class.

## 2026-10-31 — review round 5 fixes

Reviewers: Sonnet 9/10 (confident, no blockers; wants the obs half of a full corpus run on the
new code), Codex Sol 6.1 (xhigh) 8/10 (not confident, 4 blockers). Fixtures:
`tests/unit/test_round5.py`; Sonnet's polish 3 is `test_round4.py` `ComparatorMustFail`.

- **Scaled values that round to zero (Sol 1).** RINEX 3 -> 2 divides by SYS / SCALE FACTOR
  and writes F14.3; 0.001 / 10 rounds to 0.000, which is 'missing'. Such a value is now
  written blank, still claimed `scale-factor-rounding`, and not counted in PRN / # OF OBS:
  pass 1 counts them per column (`scaled_zero`, following event factors the same way the
  writer does, `merge_scale`). It used to fail the output gate.
- **Alignment per interval (Sol 2).** The RINEX 4 alignment gate walks the file: SYS / PHASE
  SHIFT in effect (header, then each event's records per system) against the type list of the
  data epochs that follow (`phase_seq`, `_unknown_phase_periods`). A system is unknown only
  while its list has phase types; a file whose phases arrive together with a zero record now
  converts. The refusal names where the unknown alignment starts (Sol polish 1).
- **Scale factors checked independently (Sol 3).** `tokens.obs_tokens` divides each value by
  the factor in effect (header, then flag 3/4 events), so a wrong factor in a RINEX 3/4 output
  fails; `compare_obs` accepts the F14.3 rounding of a RINEX 2 target only as claimed
  `scale-factor-rounding`. An event emptied because RINEX 2 applied its factor is accepted
  (`allowed.py`, rule `OBS.V3V2.EVENT-SCALE-APPLIED`).
- **Nav subtypes (Sol 4).** `nav_tokens` keeps the 4.02 subtype ('CNVX WIDE'): it is compared
  between 4.02 files and claimed `nav-subtype-not-representable` going to 4.00/4.01, and now
  also going to RINEX 3, whose IONOSPHERIC CORR has no area field (rinex305.txt Table A5
  l.3634; the loss rule's target range widened to 3.01-4.01). The corpus's BRD400DLR 4.02
  files hold such records, so their 3.x conversions now carry this claim.

## 2026-10-31 — review round 4 fixes

Reviewers: Sonnet 8/10 ("yes for well-formed files and the corpus", one blocker), Codex Sol 6.1
(xhigh) 7/10 (not confident, 5 blockers). Round 4 was the planned last round; the user asked
to continue until both are confident, so a round 5 follows. Fixtures: `tests/unit/test_round4.py`
and `test_round3.py` `EmptyPhaseShiftRecord`.

- **Empty SYS / PHASE SHIFT line (Sonnet; CMUM00THA, JAXA dconv).** A wholly blank record
  was read as a continuation without a first line, so every target was refused and no flag
  helped. Every defined form starts with the system (rinex302.txt Table A2, p.41-42), so it
  records nothing: left out as repair `HDR.PHASESHIFT.EMPTY` (refused under `--strict`), the
  alignment reads as not recorded. 3.01-3.05 targets get the per-system 'unknown' form (the
  record is mandatory; rinex301.txt Table A2 l.2113), only when the source had the record but
  nothing of it can be carried; RINEX 4 targets need `--assume-phase-aligned`. The validator
  now flags a blank record and a continuation line without a first line (`VAL.HDR.PHASESHIFT`).
- **Phase alignment from events (Sol 1).** (a) An event's SYS / PHASE SHIFT holds from that
  epoch ('each value remains valid until changed by an additional header record',
  rinex305.txt §6.5 p.41): pass 1 now collects them, and a system an event leaves 'unknown'
  needs `--assume-phase-aligned` for RINEX 4. (b) RINEX 4 (aligned) -> 3.01-3.05: the zero
  form covers the phase codes of every type list, so a file whose first phase type comes in a
  flag-4 list keeps its mandatory record; a file with no phase type at all gets the
  system-only form (rule `OBS.PHASESHIFT.NO-PHASE-TYPES`). Both used to fail the output gate.
- **99999 counts (Sol 2).** '99999 indicates >= 99999 observations' is defined from 3.01
  (rinex301.txt Table A2 l.2157). 2.x and 3.00 now get the actual count (I6); the validator
  and the independent recount accept the sentinel only from 3.01 (Sol polish 1). An I6
  overflow (over 999,999 values of one type and satellite) leaves the optional record out
  with a warning. Verified on a 100,000-epoch 2 Hz fixture.
- **Merged nav inputs (Sol 3).** `--merge` inputs now get the primary input's policy: data
  damage refused unless `--lenient`, any validator error refused under `--strict`, their
  reader repairs reported.
- **Phase-shift values checked independently (Sol 4).** `headers.phase_compare` compares
  SYS / PHASE SHIFT of the header and of every event: carried entries keep value, satellites
  and signal (only the BeiDou B1I band digit may change, via `tokens.signal_class`); generated
  ones (from RINEX 2/3.00 or 4) have no satellite lists, are 'unknown' or zero, cover every
  phase type, and say 'aligned' for a RINEX 2 source only with the reported assumption.
- **Nav message identity (Sol 5).** `compare_nav` now compares message types: kept between
  RINEX 4 versions, and going up derived independently (`compare.v4_message`: G/J/I LNAV,
  R FDMA, S SBAS, BeiDou D2 for GEO PRNs else D1, Galileo from the data-source bits). The GEO
  PRN list (C01-C05, C59-C63) is not in the RINEX specs; the check shares it with navconv.
- **Checker false alarms from the item-13 changes** (found by the recheck of corpus run 5):
  the 3.01 label spelling in 3.02 files (repaired, not non-standard), and emptied events
  checked for targets that never carry event phase records (3.00, RINEX 3 -> 4).

Not done: Sonnet polish 1 (a `--lenient` hint on every refusal --lenient can rescue: the
current ones, DARW00AUS and mate1800, already carry it), `--align-phases`, `.tar`, the QZSS
ION area option.

## 2026-10-31 — corpus run 5 (full, on the round-3 code)

5,280 conversions in 6,130 s with 4 workers: 5,197 converted, 44 refused-corrupt, 39
refused-not-representable; 0 crashes, 0 idempotence failures, 0 wrapper (crx/gz/Z) problems;
round trips clean except the known holb274a00.26d obs-type order (v2 -> 3.00 -> v2).

| | obs | nav | met |
|---|---|---|---|
| rows clean | 3,342 | 1,149 | 704 |
| refused (expected) | 11 (CMUM00THA: `SYS / PHASE SHIFT` continuation without a first line) | 11 BRDX00DLR (damaged) + 39 E/C/I-only files to RINEX 2 | 22 (DARW00AUS 2-digit-year epochs, mate1800 F8.2 humidity), both convert with `--lenient` |
| flagged | 2 (below) | 0 | 0 |

Both flagged rows were the independent checker's, not the converter's (verified by re-running
them and by mutation tests in `tests/unit/test_round3.py`):

- **HRAG00ZAF 3.05 -> 3.05 keeps its DOI.** Round 3 made same-version conversions carry the
  file's own non-standard records (rule `OBS.HDR.NONSTANDARD-CARRIED`); `headers.py` still
  demanded the drop. It now treats them as defined when target = source version, header and
  events, and requires the rule in the report.
- **DLF100NLD 3.03 -> 3.01: a flag-4 event with only `J L2X 0.25000 SYS / PHASE SHIFT`** is
  emptied, because QZSS is defined from 3.02 (rinex301.txt never mentions it). The loss table
  accepted `event-emptied` only next to a record-level loss; it now also accepts a system or
  phase-entry loss, and `headers._event_checks` checks each phase entry of an emptied event (its
  system absent from the output, or a zero/blank or claimed-dropped value).

A re-run of every row these touch (5 files with emptied events, 272 same-version obs rows)
is in `data/out/corpus_r5_recheck/`.

## 2026-10-31 — review round 3 fixes

Reviewers: Sonnet 8/10 ("yes, provisionally": no blockers, 9 once the obs half of the full
corpus run is clean), Codex Sol 6.1 (xhigh) 7/10 (not confident, 6 blockers). Fixed, each with
a fixture in `tests/unit/test_round3.py` (class `SolRound3` and the classes below it):

- **Phase alignment across type lists.** Whether a system has phases is now decided over
  every obs-type list of the file (header and flag-4 events), not the header's alone. A 3.00
  file whose phase type arrives by flag 4 no longer reaches RINEX 4 without
  `--assume-phase-aligned`. The validator's policy 6 (no SYS / PHASE SHIFT needed without
  phases) also looks at the event lists.
- **SYS / PHASE SHIFT inside events** goes through the header's repair and code renaming
  (e.g. BDS `L1I` → `L2I` for 3.02 → 3.05). The independent event check now requires every
  event phase-shift code to be an obs type of the output.
- **Picoseconds of event epochs** (4.02 → earlier) are counted as `epoch-precision` losses like
  those of observation epochs.
- **Data damage is refused by default** (PLAN §1 clause 9). The output gate used to accept an
  input's data error as "inherited" (e.g. an F14.3 field `12.3.4`, which passes the reader's
  character check), and damage the writer drops (text after column 80 of a nav line) was not
  seen at all. The input is now validated once before converting (cached across targets; it
  adds about 20–25% to a single conversion), and an error that means unreadable values or
  broken structure (`engine._DAMAGE_RULES`) refuses (`refused-corrupt`); `--lenient` converts
  it as read with a `VAL.INPUT-DAMAGE` warning. A well-formed record the version does not define (e.g. the 4.00
  spec example's STO type `LEG`) is not damage and is still carried. A scan of all 480 corpus
  inputs found one such file besides the already refused DARW00AUS: `mate1800.03m.Z`, whose
  HR values are written F8.2 (`   73.91`). Read by the F7.1 columns this gave 73.9 and a stray
  `1`, silently changing every HR value. The met reader now refuses text beyond the declared
  values (`MET.DATA.COLUMNS`); `--lenient` reads the values by pattern and reports the repair.
- **`nav-correction-extra` claims are checked.** The independent check requires a kept
  correction of the same type in the output and more of them in the input than the output
  keeps; the loss rule is limited to RINEX 2/3 targets (RINEX 4 has no one-slot limit).
- **PRN / # OF OBS for a code listed twice** is counted per column (code and occurrence), not
  summed by code name.
- **Header records inside events** (found while checking the above; no corpus file has one):
  LEAP SECONDS, TIME OF FIRST/LAST OBS and GLONASS SLOT / FRQ # in a flag-4 event were dropped
  with a false "not representable" claim. They are now carried (LEAP SECONDS in the target's
  width, a dropped field reported as for the header), and the independent check compares
  event LEAP SECONDS records field by field.
- **Output gate key** blanks only standalone numbers (counts, line numbers, versions), so
  `1C` and `9C`, or `G05` and `G06`, stay different violations.
- Reports now carry each validator finding's text (`validation.findings`, first 20), and the
  one-line summary says when the output keeps errors the input already had (Sonnet).
- `docs/CONVERSION_MATRIX.md` regenerated: it lists the new loss rules, including the QZSS CNVX
  area drop (Sonnet).

## 2026-10-31 — corpus run 3 findings

The full corpus run on the round-2 code (`data/out/corpus_r3`, 5,280 conversions) found 15
crashes (the stricter output gate catching real converter bugs), 15 token mismatches and 18
loss-table violations, in 9 files. Every one was a real defect, in the converter or in the
independent checks; none was fixed by loosening a check. Each has a hand-written fixture
in `tests/unit/test_round3.py`.

- **SYS / PHASE SHIFT codes without the type letter** (MOBS00AUS, STJ300CAN, VILL00ESP;
  gfzrnx/Septentrio exports write `G  1C` or `G 1C`). The converter dropped the entries, so
  3.0x outputs lost a mandatory record. The record holds carrier phase codes only
  (rinex305.txt p.57, "Carrier phase observation code: A3"), so `1C` is read as `L1C`,
  rewritten and reported as a repair (`HDR.PHASESHIFT.CODE`). The validator now flags such
  a code (`VAL.HDR.PHASESHIFT`, error).
- **PRN / # OF OBS kept a dropped column** (KOKV00USA 3.03 → 3.01, GLONASS band 3). The
  "numerically equal, keep the source's formatting" shortcut ignores trailing zero counts,
  so a dropped type whose counts were all 0 kept its column. The shortcut now also requires
  each system to keep the same number of types.
- **Loss counts per column and per type list** (KMNM00TWN: QZSS C1C/L1C/S1C listed twice,
  second column always blank). Lost values were counted by code name over all type lists,
  which credited the blank column with the first one's 11,012 values and would count a
  value once per flag-4 type list. Counts are now per (type list, system, column). A
  duplicate column that holds no value is a normalisation (`obs-code-collapsed-empty`), not a
  loss. A duplicate column that does hold values is kept, between RINEX 3/4 versions (lists
  are per system, so both columns are written as the source had them; warning
  `OBS.DUPLICATE-CODE-KEPT`); to RINEX 2 it collapses into one column, with the loss counted
  for that column only. The independent comparator counts values of a code's repeated columns
  separately (`later`), so it checks either reading of a claim.
- **BeiDou band 2 in a 3.02 file** (WARK00NZL, Trimble NetR9 4.81 writes `C2I` in 3.02). The
  converter already read it as B1I (repair `OBS.BDS-B1I-BAND`); the independent comparator
  did not. Band 2 I/Q/X (1561.098 MHz) is B1I in every version that defines it
  (rinex301.txt Table 5 "E2", rinex305.txt Table 19), and 3.02 defines no band 2, so the
  comparator's own table now says so.
- **Deprecated records inside events** (UZHL00UKR: a flag-4 event holding only GLONASS
  COD/PHS/BIS, 3.05 → 4.x). The converter claimed `event-record-not-representable`, which is
  false: 4.x defines the label but strongly deprecates it ("should be ignored by RINEX
  decoders and encoders", rinex_4.00.txt Table A2 p.61). Events now follow the header rule
  (known non-zero biases kept, otherwise dropped) and the drop is reported as
  `event-record-deprecated:<label>` (new loss rule, cited).
- **QZSS ION CNVX area** (BRD400DLR 4.00 → 4.02 crashed the gate). 4.02 requires WIDE or
  JAPN on QZSS CNVX ION records (rinex_4.02.txt Table 25 p.40, Table A35 note 3*); 4.00/4.01
  records carry no area and the spec gives no "unknown" value. The records are dropped and
  reported (`nav-correction-not-representable:ION:CNVX-area-unknown:J`); no area is
  invented. The other way, 4.02 subtypes (DLR writes WIDE and JAPN on both LNAV and CNVX)
  were written into 4.00/4.01 files, which have no subtype field: the subtype is now removed
  with the values kept, reported as `nav-subtype-not-representable` (new loss rule). **User
  to confirm both** (an option such as `--qzss-ion-area WIDE|JAPN` could supply the area).
- **A record another version defines, in the source's own version** (HRAG00ZAF: DOI in a
  3.05 file from JPS2RIN 2.1). A same-version conversion dropped it; it is now carried as
  written, as non-standard codes already are. The DOI / LICENSE OF USE / STATION
  INFORMATION loss rules no longer assume only 4.x files have them.
- **IONOSPHERIC CORR GAL fourth slot** (CKIS00COK round trip). The 3.00–3.02 tables define it
  as "zero" (rinex302.txt l.3289), 3.03+ as "Blank" (rinex305.txt l.3641); the converter
  wrote blank for every version and now writes zero below 3.03.
- **`--drop-unresolvable` report counted twice** (found while reviewing, not by the corpus,
  which does not use the option). The retry without GLONASS kept the first attempt's report
  entries: every code mapping counted twice, and the removed system's assumptions stayed.
  The report is now restored to its state before the first attempt (`Report.snapshot`).
- **Corpus harness (round-trip check).** A forward leg that added GLONASS SLOT / FRQ # from a
  companion nav file (reported) is treated like an added LEAP SECONDS (USN900USA, WUHN00CHN
  3.01 → 3.0x → 3.01: the record is optional in 3.01 and kept on the way back). RINEX VERSION /
  TYPE is compared by version, file-type letter and system letter only; the rest of the type
  field is free text ("Navigation" and "N: GPS NAV DATA" both say N).

## 2026-10-31 — review round 2 fixes

Reviewers: Sonnet 8/10, Codex Sol 6.1 (xhigh) 6/10, neither yet confident. Changes:

- **Observation states keyed by content.** The streaming reader re-parses type definitions on
  every pass, so the converter's tables were keyed by `id()` of objects that no longer existed
  in pass 2: a valid file with a flag-4 type change raised `KeyError`. `ObsTypes.key` is now
  (layout, v2 list, per-system lists). Verified: `tests/unit/test_round2.py` (3.05 → 3.05,
  3.03, 4.02, 2.11).
- **Scale factors per code.** A flag-4 SYS / SCALE FACTOR for one code no longer wipes the
  other codes' factors; a factor for all types of a system (no code list) replaces that
  system's factors (rinex305.txt Table A2). Verified by a hand-computed 3.05 → 2.11 fixture.
- **Pseudo-observables and blank attributes** count as valid codes when mapping between RINEX
  3/4 versions: `X1 ` (channel, 3.05/4.x) and `In ` (3.00–3.04) per `obscodes.pseudo_obs_codes`,
  and a blank attribute in 3.00/3.01 for a listed type and band (rinex301.txt §5.1).
- **Validator gate matches specific violations.** An output error is inherited only if the
  input has the same rule *and* message (numbers blanked), counted. Exception: the nav record
  line-count rule, whose wording differs between RINEX 2/3 and 4 by design, is counted per rule.
  `--strict` now validates the input and refuses it on any error.
- **APPROX POSITION XYZ to RINEX 2.** Mandatory in RINEX 2 (rinex211.txt Table A1) but optional
  for moving platforms from 3.00. A RINEX 3/4 file without it now refuses with
  `refused-missing-information` naming the record (PLAN §1 clause 8), unless the user passes
  `--approx-position X Y Z`, which is written and reported as a user-sourced assumption. The old
  gate let the missing record through. No value (such as 0 0 0) is invented. **User to confirm**
  whether a "write 0 0 0" option is wanted (teqc-style).
- **Validator policy 6:** SYS / PHASE SHIFT (mandatory 3.01–3.05) is not required when the
  file has no phase observation type at all. rinex305.txt §5.2.12 defines its content for
  files with phases (values; reference signals only; unknown) but says nothing for a file
  without any. Same reasoning as policy 1 for GLONASS records. **Confirmed by the user, 2026-10-31.**
- **Nav corrections:** a correction of a type the target can hold, but whose single header
  slot is already taken (several IRUT records, merged inputs), is now `nav-correction-extra`,
  not `nav-correction-not-representable`. The independent loss check
  (`tests/independent/allowed.py`) now authorises `nav-correction-not-representable` per type
  against what each target can hold (its own spec-derived table, independent of `navcorr.py`).
  A false "not representable" claim for GPUT in 3.05 is rejected.
- **RINEX 2 nav split:** losses for the corrections written to the second or third file (GLONASS
  CORR TO SYSTEM TIME, SBAS D-UTC) were suppressed with the duplicated header-record losses;
  each file's corrections are now counted. Found by the corpus run: BRD400DLR / MAS100ESP
  RINEX 4 → 2.10/2.11 claimed one rounding too few. GLONASS nav files are labelled
  `GLONASS NAV DATA`, as the spec example spells it (rinex211.txt line 1755).
- **Independent comparator:** within RINEX 3/4 the signal attribute is part of the comparison
  key (BeiDou B1I band digit normalised), so swapped attributes are caught; a GLONASS line 5
  with real values dropped going below 3.05 must be claimed with the right count.
- **PGM / RUN BY / DATE:** one creation time per input for every output made from it;
  `SOURCE_DATE_EPOCH` (if set) fixes it. The corpus harness sets it, so A→B→A round trips do
  not differ by timestamp. A round trip whose forward leg added LEAP SECONDS from the dated
  table (reported) no longer counts as a data difference.

## 2026-10-30 (later) — review round 1 fixes

Reviewers: Sonnet 7/10, Codex Sol 6.1 (xhigh) 6/10, neither yet confident. Spec-example
fixtures (123, from every version's printed examples) found 8 more issues. Changes:

- **Streaming two-pass engine** (replaces deviation 1 below). Epochs are parsed lazily from
  the decoded bytes (`ObsFile.iter_epochs`, a chunked `LineCursor`); pass 1 (the survey) also
  collects everything the header needs; pass 2 streams converted epochs into the output; the
  output is re-parsed as a stream. Largest corpus file (89 MB RINEX): peak RSS 205–250 MB for
  plain output and 330–380 MB while Hatanaka decoding/encoding (was ~1 GB); 4–8 s per target
  (was 17 s). Remaining: the decoded source and the output are each held once, so a 1 GB 24 h
  1 Hz file needs about 2.2–2.5 GB.
- **LLI bit 2** is now carried only between versions where it means the same thing
  (anti-spoofing in 2.x, undefined in 3.00, BOC tracking from 3.01: rinex211.txt Table A2,
  rinex300.txt ~1970, rinex301.txt ~2227). Elsewhere it is cleared and reported
  (`lli-bit2-meaning-differs`); `--keep-lli-bit2` carries it verbatim. **Confirmed by the user, 2026-10-31.**
- Scale factors: SYS / SCALE FACTOR rebuilt for renamed/dropped codes; factor changes in
  flag-4 events applied when going to RINEX 2.
- Blank-attribute and pseudo-observable codes read as fixed-width A3 fields.
- RINEX 4.02-only nav messages (GLONASS L1OC/L3OC, NavIC L1NV; LXOC/L1NV STO/EOP/ION) are
  dropped with a loss going to 4.00/4.01.
- Validation: observation fields checked (digits, point, sign; LLI/SSI digit or blank),
  calendar dates, finite numbers; nav record line counts per version/message; `--strict`
  refuses any repair or input-side warning.
- LEAP SECONDS is compulsory in RINEX 4 nav (rinex_4.00.txt Table A7): taken from the source,
  else `--leap-seconds`, else the built-in dated table `rinexcore/leapseconds.py` (GPS-UTC =
  18 s since 2017-01-01; IERS Bulletin C 72 of 2026-07-06 announced no leap second at the end
  of 2026, so the table is valid to 2027-06-30; later dates refuse).
- Compact RINEX 1.0 cannot hold LLI/SSI on a blank RINEX 2 value (rnx2crx.c): with Hatanaka
  output to RINEX 2 those flags are dropped and reported (`flags-on-missing-value-dropped`).
- A same-version conversion carries codes and SYS / PHASE SHIFT entries the source's own
  version does not define (warning, refused under `--strict`); an incomplete GLONASS SLOT /
  FRQ # in a ≥ 3.02 source is carried with a warning instead of refused.
- Nav: an `M` file stays `M`; the writer's own file-type text is kept; header-only output is
  refused as not representable; nav systems per version (3.00/3.01 G E R S, + C J 3.02, + I
  3.03); split RINEX 2 outputs count correction losses once; GLONASS line 5 holding only the
  spec's "unknown" values is dropped without a loss.
- Met 3.00 and 3.01 use 2-digit years (rinex300.txt ~2672, rinex301.txt ~2944); 4 digits
  from 3.02. Both the reader and the independent tokenizer had this wrong.
- RINEX 2 output from RINEX 3 gets the default WAVELENGTH FACT L1/2 (mandatory in 2.10).
- `.bz2` and single-file `.zip` inputs; an internal error in one file no longer stops a batch
  (outcome `internal-error`, exit 7).
- Independent checks: obs comparison keyed by (epoch, satellite) records (5x faster); nav
  comparison positional; an independent transcription of every version's code tables
  (`tests/expectations/code_validity.json`) agrees exactly with `rinexcore/spec/obscodes.py`
  (test `test_code_tables_agree.py`) and authorises each `obs-code-not-representable` claim per
  code; the corpus harness now also checks gz/.Z/Hatanaka output (decoded back, and by
  CRX2RNX.exe) and A→B→A round trips.

## 2026-10-30 — first laptop session: M0a through M6 in one pass

The user asked for the converter to be built and reviewed until it converts every common
RINEX file type to every other. This session built M0a–M6 together (codecs, obs, nav,
met, engine, CLI, harness) instead of one milestone at a time, so that the corpus could
exercise the whole path early. QC (rinexqc, Q1–Q6) has not been started.

### Environment

- Anaconda 2026.07-1 (Python 3.14.6) installed per user at `C:\Users\benha\anaconda3`, with
  the user's permission; not on PATH. See `docs/ENVIRONMENT.md`.
- Code keeps to Python 3.10 syntax. `rinexcore` and `rinexconv` import only the standard
  library (AST test `tests/unit/test_import_purity.py`).
- Git: initialised, but git refuses the folder (files owned by the desktop's Windows
  account). Not overridden: the fix is a global git security setting, left to the user.

### Deviations from PLAN.md (need the user's sign-off)

1. **Engine is in-memory, not a spooling two-pass engine** (PLAN §3.4). The model keeps each
   satellite record as its original 16-character fields, so a daily file costs about its
   text size; pass 1 (which types carry data) and pass 2 (write) run over that model. Peak
   resident memory on the largest corpus file (89 MB of RINEX) is about 1 GB, above the
   500 MB ceiling. A 24 h 1 Hz file (~1 GB of text) would not fit on this laptop. To do:
   drop the decoded line list after parsing, stream the output, or spool.
2. **A fifth outcome, `refused-not-representable`** (exit code 6). PLAN §1 has four
   outcomes, but none fits "the input is valid, and the target version cannot hold any of
   its data" (a BeiDou-only nav file to RINEX 2, whose nav files hold only GPS, GLONASS and
   SBAS: rinex211.txt Tables A3, A10, A15). Nothing is written.
3. **SYS / PHASE SHIFT zero entries are carried to 3.01/3.02** rather than written blank
   (PLAN §3.3 rule 1, second bullet). In 3.01/3.02 a value is "the correction applied", so a
   zero says truthfully that nothing was applied, and 3.05 → 3.02 → 3.05 keeps the
   aligned-at-source information. A 4.x source going to 3.01/3.02 gets the zero form too.
4. **Within the 3.01–3.05 family SYS / PHASE SHIFT records are carried verbatim** (codes
   renamed only where the target spells them differently, e.g. BeiDou B1I), and nothing is
   synthesised. The blank "unknown" form is only generated for sources without a record
   concept (RINEX 2, 3.00).
5. **Same-layout conversions keep declared observation types that carry no data**
   (v3 → v3, v2 → v2), so same-version identity holds. Across layouts (v2 ↔ v3) only types
   with data are kept, per system (PLAN §3.5).
6. `--align-phases` is not implemented yet (needs Table A23/A45 of shifts). The CLI does not
   offer it.

### Policy defaults the user should confirm (CLAUDE.md "stop and ask")

- **RINEX 2 → 3 attributes** (rinexconv/codemap.py): GPS C1→C1C P1→C1W L1→L1C P2→C2W L2→L2W
  C2→C2X C5→C5X; GLONASS C1→C1C P1→C1P L1→L1C C2→C2C P2→C2P L2→L2P; Galileo band n → nX;
  SBAS C1→C1C, band 5 → 5X. When a v2 file has C2 but no P2 (an L2C receiver), GPS L2/D2/S2
  become 2X and GLONASS 2C. Every use is reported as an assumption; `--overrides` changes any.
- **RINEX 3 → 2 collapse priority** (several attributes onto one v2 code): GPS band 1
  C>W>P>Y…, band 2 W>P>Y>D…>C>L>S>X (so L2 stays consistent with P2); GLONASS band 1 C>P,
  band 2 P>C; Galileo C>X>B>A>Z (pilot first), bands 5/7/8 Q>X>I. Only codes that carry data
  compete. Dropped codes are reported per code with counts.
- **LLI bits are carried verbatim** between v2 and v3. Bit 2 means "under anti-spoofing" in
  RINEX 2 (rinex211.txt Table A2), is undefined in 3.00, and means "BOC tracking of an
  MBOC signal" from 3.02 (rinex302.txt ~3055). So a v2 AS flag on a GPS L2W phase reads
  differently in v3. The alternative is clearing bit 2 on the way to v3 (and losing it).
  **Superseded:** bit 2 is now cleared where its meaning differs (confirmed by the user, 2026-10-31).
- **WAVELENGTH FACT L1/2 → LLI bit 1**: for GPS L1/L2 phase with factor 2, v3 bit 1 =
  v2 bit 1 XOR (factor = 2); factor-1 files (all of the corpus) are unchanged.
- **BeiDou 3.04-only codes** C1A, C6A and codeless L1N have no 3.05+ code; they are dropped
  with a loss entry rather than renamed (the spec agent's question 2).
- **GLONASS records in GPS-only files**: written only when GLONASS data are present, though
  the 3.02+ tables mark them mandatory without an "if GLONASS" condition.
- **GLUT T and W**: rinex305.txt Table A5 says GLONASS T and W are zero, but the same
  table's example (rinex305.txt line ~4110) shows `345600 1849`. We compute W/T from the
  v2 CORR TO SYSTEM TIME date. Spec inconsistency, shown here per PLAN §1 clause 10.

### Real files that break the spec, and what we do

| File (corpus) | What | Default | `--lenient` |
|---|---|---|---|
| 3.01 files from several writers, and 3.02 BRUX/KOUR/MAS1 | label `SYS / PHASE SHIFTS` | 3.01's own spelling (rinex301.txt p.32), so standard in 3.01; in 3.02 read as SYS / PHASE SHIFT with a repair entry | — |
| NRCan 3.03 files (ALG2, BAKE, DRAO …) | v2-only `WAVELENGTH FACT L1/2` | carried verbatim within v3 (non-standard record) | — |
| `met/v3.03/DARW00AUS_…_MM` (ssrcrin 13.0.0x) | epochs in the RINEX 2 layout (2-digit year) | refused-corrupt | read, repair entry |
| `nav/v4.00/BRDX00DLR_S_2020…` | pre-release RINEX 4 (`G01 LNAV … *` record headers, header TIME SYSTEM CORR) | refused-corrupt | read, repair entry |
| `nav/v3.02/BOR100POL_…` (cnvtToRINEX 3.09) | TIME SYSTEM CORR values three columns off | read by pattern, repair entry | — |
| merged IGS 3.03 nav (BRDC00IGS 2017) | Galileo data-source value 519: I/NAV and F/NAV bits both set | v4 type from clock bits 8/9 (9 → INAV), reported as an assumption | — |
| a 3.04 merged nav | 4.x-only codes IRGA/IRGL in TIME SYSTEM CORR | carried verbatim within v3, STO records in v4, a loss in v2 | — |
| many 3.x files | `0.000` for missing observations | read as missing (rinex305.txt §6.7), written blank | — |

### Independent checks in place

- `tests/independent/` (no rinexcore imports): its own tokenizer and signal classes
  (`code_expectations.json`); obs diff ⇔ report with equal counts per system and per lost
  code; nav positional multisets per record; met tokens.
- `tests/expectations/allowed_losses.json`: loss categories by kind and version range, each
  with a spec citation; `tests/independent/allowed.py` checks every report.
- Hand-written fixtures (`tests/unit/test_obs_fixtures.py`, `test_nav_fixtures.py`): v2.11 ↔
  3.05 obs, 2.11 spec nav example → 3.05, GLONASS 4/5-line nav, picosecond epochs, BeiDou
  B1I band, refusals.
- Seeded fuzzing (`tests/unit/test_fuzz.py`; 18,000 cases at `RINEX_FUZZ_SEEDS=1500`): it
  found two real bugs (unvalidated nav correction numbers; `str.isdigit()` accepting `²`).

### Corpus pass counts

Filled in from `tools/corpus_run.py` runs (all files × all 11 write versions; same-day
GLONASS companions; `--assume-phase-aligned`).

| Kind | Conversions | converted | refusals | token problems | idempotence failures | loss-table violations |
|---|---|---|---|---|---|---|
| met | 726 | 715 | 11 refused-corrupt (DARW, by design) | 0 | 0 | 0 |
| nav | 1,199 | 1,195 | 4 refused-not-representable (BDS/GAL-only → v2) | 0 | 0 | 0 after the same-version fixes |
| obs | 3,355 | (run in progress) | | | | |

## Validator

`rinexcore/validate.py` (PLAN §1 clause 2, §3.8): `validate(payload) -> list[Finding]` on plain
RINEX bytes. It reads the version and file kind from the first line, raises only `CorruptError`
(empty, compressed, no `RINEX VERSION / TYPE` first line, unreadable version or type), and
scans the data with slicing and precompiled patterns, without building a model. Measured on
this laptop, single process: 90 MB 3.04 obs file in 2.1–3.7 s, 59 MB 3.05 file with
`PRN / # OF OBS` in 2.6 s. A finding has severity (`error` = breaks a rule of its own
version; `warning` = readable but off spec, deprecated or non-standard), rule (`VAL.*`, all
listed in `RULES`), message, line, column and scope (`header`/`data`). The header count and
time records that clause 9 repairs by default (TIME OF FIRST/LAST OBS, # OF SATELLITES,
PRN / # OF OBS) are flagged `repairable`. A rule is listed at most 50 times; the rest are
counted in `VAL.FINDINGS.SUPPRESSED`. Versions outside the 11 write versions (2.00, 2.01,
2.12) are checked against the nearest table with a warning.

**Checked.**
- All kinds: label placement in columns 61-80, labels defined for the version (others: warning;
  3.01's `SYS / PHASE SHIFTS`, `GLONASS COD/PHS/BIS#` and `ANTENNA:PHASECENTER` count as the
  record with a spelling warning), mandatory records, repeated single records, END OF HEADER,
  numeric header fields, F9.2 version field, and for 4.x that PGM / RUN BY / DATE is line 2.
- Obs headers: `rinexcore.spec.obsheader` statuses and `obscodes` codes; type counts and the
  4X,A2 / 1X,A3 grids; TIME OF FIRST/LAST OBS against the first/last flag 0/1 epoch at 0.1 µs
  (a 4.02 picosecond epoch is floored, Table A3); time-system letters; # OF SATELLITES
  (satellites in flag 0/1/6 records) and PRN / # OF OBS (non-blank, non-zero values in flag
  0/1 records, blank count = 0, 99999 = "at least"); GLONASS SLOT / FRQ # count and coverage.
- Obs data: epoch columns per layout (fields, reserved 6X, F12.9/F15.12 clock, 4.02-only
  `1X,I5.5` picoseconds), flags 0-6, time order (warning), satellite counts against records,
  12-per-line satellite lists and 32X continuations, F14.3+LLI+SSI fields, no more fields than
  types, satellite systems with a type list, duplicate satellites, event records (count, header
  labels, MARKER NAME after flag 3, new type lists after flags 3/4 apply to later epochs).
- Nav: record line counts per version, system and message type (v2 GPS 8 / GLONASS 4 / GEO 4;
  v3 8, GLONASS 4 to 3.04 and 5 from 3.05, SBAS 4; v4 from Tables A9-A40, STO 2, EOP 3, ION by
  model 1-7), message types and 4.02-only types, ION subtypes (4.02 only), numbers and
  two-digit exponents, one exponent letter (error in 4.x, warning in 3.05), D/d in 4.x
  (warning), LEAP SECONDS in 4.x, the system letter against the records.
- Met: types and codes per version, sensor records (SENSOR POS XYZ/H "required for
  barometer"), epoch layout (2-digit year up to 3.01, 4-digit from 3.02), F7.1 values and
  continuation lines, time order.

**Not checked.** INTERVAL against the sampling; PGM / RUN BY / DATE date format; free-text
records; the contents of SYS / PHASE SHIFT, SCALE FACTOR, DCBS/PCVS APPLIED, ANTENNA:
records beyond their numbers; navigation parameter values (only that they are numbers); STO
text fields; LLI/SSI meaning; mixing blank and non-blank attributes (3.00/3.01); anything that
needs a second file.

**Choices (inferences, for the user to confirm).**
1. GLONASS SLOT / FRQ # (3.02+) and GLONASS COD/PHS/BIS (3.02-3.05) are required only when
   GLONASS data are present (docs/SPEC_TABLES.md item 17; same policy as the converter).
2. RINEX 3 is not checked for "PGM / RUN BY / DATE is the second line": 3.x only describes it
   ("the second header record", rinex300.txt p.13) and its own examples put a COMMENT first.
3. RCV CLOCK OFFS APPL missing while clock offsets are reported is a warning: the tables star
   it optional with default 0 and also say "Record required if clock offsets are reported".
4. A blank line inside a RINEX 4 nav record is a warning and not counted as a record line, as
   our reader does (see the converter finding below).
5. 3.02 GLONASS SLOT / FRQ # stays mandatory (Table A2) although 3.02 sec. 9.5 says optional
   (docs/SPEC_TABLES.md item 6).

**Corpus (480 files, 2026-10-30).** No exceptions. Of the 478 files our reader accepts, 419
have no error, 15 only repairable header errors, and 44 non-repairable errors. All 44 were
checked against the spec text and are real violations:
- obs 3.02-3.05: mandatory GLONASS SLOT / FRQ # missing with GLONASS data (13 files),
  GLONASS COD/PHS/BIS (13), SYS / PHASE SHIFT (8);
- met: SENSOR POS XYZ/H missing for PR (10), no SENSOR MOD/TYPE/ACC (3), no PGM / RUN BY / DATE
  (3, gfzrnx merges, line 2 is a COMMENT);
- numbers out of their columns: BOR100POL nav TIME SYSTEM CORR, ARUC00ARM obs APPROX POSITION
  XYZ (13-column fields), GOPE00CZE met (UTF-8 bytes in SENSOR POS XYZ/H);
- WUHN00CHN 3.01 obs says `G (GPS)` but holds BDS and GLONASS; mate1800.03m (2.00) writes F7.2.
Repairable header errors were confirmed by an independent count where checked (e.g. conz1800.03d
counts `0.000` as observations in PRN / # OF OBS; ASCG00SHN 2023 lists 2867 C2I observations
for C05, whose data a COMMENT says were dropped). The two files the reader refuses (DARW met,
BRDX nav) are reported as errors too. `tests/unit/test_validate.py` holds eight of these
files in KNOWN_VIOLATIONS with their citations.

**Spec examples.** The validator sees errata E-01, E-02, E-08, E-09, E-10, E-13 and E-15. New
candidates for tests/fixtures/spec_errata.md (unverified against the PDFs):
- 3.01 and 3.02 obs examples have no SYS / PHASE SHIFT(S), which those versions make mandatory;
- the 3.02 met example (rinex302.txt p.79) prints SENSOR POS XYZ/H 3 columns right, so the
  label starts at column 64;
- the 4.00-4.02 STO/EOP/ION examples use message type `LEG` (`> STO E   LEG`), which Table 21
  does not define;
- the 2.10/2.11 mixed obs example (Table A7) has no time system in TIME OF FIRST OBS, which is
  "compulsory in mixed GPS/GLONASS files" (warning).

**Converter finding.** A 3.05 nav file with IONOSPHERIC CORR GPSA but no GPSB converts to 4.02
with a `> ION G   LNAV` record whose third line (beta3) is written empty, so it reads as 2 lines
where Table A35 defines 3, and our own reader also stops the record there; the STO t_tm is
written `552960.0` (no exponent). `ConverterOutput.test_nav_ionospheric_corr_without_beta_to_402`
is an expected failure until this is fixed.
