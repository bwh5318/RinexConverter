# rinexqc metrics — v0

Milestone Q0a (PLAN.md rev. 4, §5 and §7), 2026-11-06. This document is the method reference that
every rinexqc result points to (`method` in docs/QC_SCHEMA.md). It holds:

1. the observation semantics the adapter applies (§1);
2. the frequencies and the pairs (§2);
3. the shared definitions (§3);
4. every metric: definition, unit, scope, pairs, arc resets, cadence limits, inputs (§4);
5. the input matrix (§5);
6. the threshold set `qc-thresholds/0` (§6);
7. **Q1's numeric gates** (§7), including the expected outcomes for corrupt files;
8. the station split rule (§8);
9. what the user still has to decide or sign off (§9), and the references (§10).

**Status of v0.** §1 and §2 were checked against `specs/text/` row by row (2026-11-06; about 35
citations re-checked by the review). **The user signed off the gates of §7 and accepted proposals
[P1]-[P8] on 2026-11-06** (docs/DECISIONS.md, "Q0a"); they are frozen with the commit that records
this, and changing one needs the user's sign-off again (PLAN §5.9). The tuned thresholds of §6 are
not frozen yet: they are tuned on the calibration half in Q1, then frozen. Metrics of Q2-Q6 are
defined to the level their milestone needs to start; each of those milestones begins by freezing its
own gates here.

---

## 0. Conventions

- **Citations.** Pages are the `===== page N =====` markers of `specs/text/*.txt`, which are PDF
  page numbers, not the numbers printed in the footers (as docs/SPEC_TABLES.md does). The RINEX 2
  texts have no markers and are cited by line (`l.N`). For 3.03 the text is 3.03 Update 1.
  RINEX 2.00, 2.01 and 2.12 have no text here: rinexcore reads them under the 2.10/2.11 rules, and
  so does the adapter.
- **Status values** (docs/QC_SCHEMA.md §3): `ok`, `degraded(reason)`, `cannot-compute(reason)`,
  `not-applicable(reason)`. Reasons come from a closed list (QC_SCHEMA.md §4). A missing value is
  `null` with a reason, never 0.
- **Units.** `m`, `cycles`, `s`, `Hz`, `dB-Hz`, `relative` (receiver units, D5), `ordinal` (the
  SSI digit), `TECU` (10¹⁶ el/m²), `TECU/min`, `count`, `fraction`, `deg`, and the met units of §4.3.
- **Constants.** c = 299 792 458 m/s. λ = c / f.
- **Robust statistics.** median; σ̂ = 1.4826 × MAD (median absolute deviation from the median).
- **Decisions D1-D5** (the user's answers, 2026-11-06; PLAN §5.10):
  - D1: a file the reader refuses gets its compliance findings only; `--lenient` reads it with the
    lenient reader, every metric keeps its own status and carries `lenient_read`. (What counts as
    "refused" is set out in §3 and proposal [P6].)
  - D2: `igs20.atx`, `rcvr_ant.tab`, the IGS satellite metadata SINEX, site logs (files.igs.org),
    Anubis and RTKLIB are each fetched once in Q0b and pinned (URL, version, date, sha256).
  - D3: Galileo single-frequency SPP uses Klobuchar as a reported approximation; NeQuick-G later
    only if the user asks.
  - D4: the grading profile is drafted at Q5 and approved by the user; no grade before Q5.
  - D5: without `SIGNAL STRENGTH UNIT DBHZ`, S values are relative and the SSI digit ordinal; dB-Hz
    only for receiver types the user lists (`--snr-table`, each entry the user's).

---

## 1. Observation semantics (the adapter, `rinexqc/semantics.py`)

The adapter turns rinexcore's raw fields into `(system, signal key, value, flags)` and applies each
meaning of this table exactly once. Every metric reads the adapter's output.

### 1.1 The table

| # | Item | RINEX 2 | RINEX 3 and 4 | Source (checked) |
|---|---|---|---|---|
| 1 | Missing value | blank or `0.0` | blank or `0.0` | rinex210.txt l.1018; rinex211.txt Table A2 l.1288-1289; rinex300.txt p.30 l.1965; rinex305.txt §6.7 p.43; rinex_4.02.txt §6.7 p.49 l.2612 |
| 2 | Which observations carry an LLI | bits 0 and 1 for phase only; bit 2 on any type | 3.00-3.04: bit 0 "for phase observations only", bits 1 and 2 not restricted by the text. 3.05 and 4.x: the LLI field exists "only for phase observation" | rinex210.txt l.1037; rinex211.txt l.1308; rinex301.txt p.34 l.2220-2222; rinex305.txt §6.7 p.43 l.2319, §6.7.1 p.43, change log l.526; rinex_4.02.txt §6.7.1 p.49 |
| 3 | LLI bit 0 | lost lock between the previous and current observation: slip possible | same | rinex211.txt l.1297-1299; rinex300.txt p.30 l.1973; rinex305.txt §6.7.1 p.43; rinex_4.02.txt p.49 l.2620 |
| 4 | LLI bit 1 | opposite wavelength factor to the one set by `WAVELENGTH FACT L1/2` (or the default), this epoch only. Wavelength factors are defined for GPS L1/L2 only | half-cycle ambiguity or slip possible, this epoch only; software that cannot handle half cycles skips the observation | rinex211.txt l.999-1001, l.1300-1303; rinex300.txt p.30 l.1976; rinex305.txt §6.7.1 p.43 and §5.2.13 p.28; rinex_4.02.txt §6.7.1 p.49 |
| 5 | LLI bit 2 | observation under antispoofing (may be noisier) | 3.00: not defined (bits 0 and 1 only). 3.01-3.04: "Galileo BOC-tracking of an MBOC-modulated signal". 3.05 and 4.x: "BOC-tracking of an MBOC-modulated signal" (no system named) | rinex211.txt l.1305-1306 and §7 l.739-753; rinex300.txt p.30 l.1973-1979; rinex301.txt p.34 l.2227; rinex303_update1.txt p.62 l.3186; rinex304.txt p.67 l.3479; rinex305.txt §6.7.1 p.43; rinex_4.02.txt §6.7.1 p.49 |
| 6 | Wavelength factor | `WAVELENGTH FACT L1/2`: GPS L1 and L2 only; a default line, then satellite lines, in the header and in events. 1 full-cycle, 2 half-cycle ambiguities (squaring), 0 in L2 single-frequency. Half cycles are converted to whole cycles before writing: values stay in whole cycles, nothing is rescaled. Mandatory in 2.10, optional in 2.11 | no record. Codeless squaring has its own attribute (`N`); half-wavelength observations are stored in full cycles; a possible half-cycle ambiguity is LLI bit 1 | rinex211.txt l.233 (2.10 change list), l.447-449, §10.1.2 l.992-1001, Table A1 l.1107-1131; rinex305.txt §5.2.13 p.28; rinex_4.02.txt §5.2.13 p.28 l.1445 |
| 7 | SSI digit | 1-9 "projected" by the receiver; 5 = threshold for good S/N; 0 or blank unknown. No standard mapping | 1-9; standardised as sn_rnx = MIN(MAX(INT(sn_raw/6),1),9) **when the raw value is in dB-Hz**; 0 or blank unknown | rinex211.txt l.1310-1314; rinex300.txt p.13 l.799; rinex305.txt §6.7.2 p.43, Table 23 p.44; rinex_4.02.txt §6.7.2 p.49 l.2632 |
| 8 | S observations | "raw signal strengths or SNR values as given by the receiver"; unit "receiver-dependent". S1, S2 from 2.10 | `Sna` per signal; unit in `SIGNAL STRENGTH UNIT` (optional from 3.00; `DBHZ` in the examples) | rinex211.txt l.231, l.1154-1156, l.1175; rinex300.txt p.28 l.1827; rinex305.txt Table A2 p.55 l.3011; rinex_4.02.txt Table A2 p.65 l.3518 |
| 9 | Epoch flags | 0 OK; 1 power failure between the previous and current epoch; 2 start of moving antenna; 3 new site occupation; 4 header information follows; 5 external event; 6 cycle-slip records follow (observation format, slip in place of the value). Header records may follow flags 2-5 (from 2.10) | same | rinex211.txt Table A2 l.1236-1273, l.230 and errata l.241-242; rinex300.txt p.30-31 l.1945-2016; rinex305.txt §5.3.2 p.37, Table A3 p.59 l.3208-p.60 l.3261; rinex_4.02.txt §5.3.2 p.37, Table A3 p.69 l.3747-p.70 l.3801 |
| 10 | Validity of header values | a value stays valid until changed by another header record (also inside events) | same | rinex211.txt §5.3 l.608-615; rinex305.txt §6.5 p.42; rinex_4.02.txt §6.5 p.48 l.2580 |
| 11 | Scale factors | none in 2.10/2.11. The unofficial RINEX 2.20 `OBS SCALE FACTOR`, which `SYS / SCALE FACTOR` "is a modification of", occurs in real files: the adapter divides by it **[P7]** | `SYS / SCALE FACTOR` (10, 100, …): the stored value is the observation times the factor; the adapter divides. In the header and after events | rinex300.txt p.12 l.756-758; rinex305.txt §5.2.11 p.26, Table A2 p.56 l.3068; rinex_4.02.txt §5.2.11 p.27, Table A2 p.66 l.3582; docs/DECISIONS.md (round 32, `OBS.V2V3.OBS-SCALE-FACTOR`) |
| 12 | Applied corrections | none | `SYS / DCBS APPLIED`, `SYS / PCVS APPLIED` (optional from 3.00): reported, and named by every metric they affect | rinex305.txt §5.2.9-5.2.10 p.26, Table A2 p.56 l.3052; rinex_4.02.txt §5.2.9-5.2.10 p.27 |
| 13 | Phase alignment | unknown (no record) | 3.00 unknown (no record); 3.01 shifts applied, a blank value ambiguous; 3.02-3.05 three record states (zeros: aligned at source; reference codes only; fully blank: unknown); 4.x aligned by definition | PLAN §3.3; docs/PHASE_ALIGNMENT.md (every table PDF-checked) |
| 14 | Receiver clock | `RCV CLOCK OFFS APPL` (from 2.10; required if epoch lines carry offsets): 1 = epoch, code and phase corrected by the receiver's real-time offset. Epoch-line offset F12.9 s | same; epoch-line offset F15.12 s | rinex211.txt l.232, Table A1 l.1198-1202, Table A2 l.1246; rinex305.txt §5.2.14 p.28, Table A2 p.56 l.3047; rinex_4.02.txt §5.2.14 p.28, Table A2 p.65 l.3544 |
| 15 | Time system | `TIME OF FIRST OBS` names it: GPS, GLO (= UTC), and GAL from 2.11; compulsory in mixed GPS/GLONASS files; defaults GPS, GLO, GAL for pure files; GEO (SBAS) payload data default to GPS | single-system files default to their system's time; mixed files must name it in `TIME OF FIRST OBS`. RINEX `GLO` tags have UTC hours, not UTC+3 h | rinex210.txt l.916-921 (GPS, GLO only); rinex211.txt §8.1.1 l.760-778, §10.1.4 l.1010, l.883-884, Table A1 l.1182-1191; rinex305.txt §4.1 p.15 l.755-760, §4.1.2 p.15 l.773-778, Table A2 p.56 l.3034; rinex_4.02.txt §4.1 p.16 l.813-819, §4.1.2 p.16 l.837-843, Table A2 p.65 l.3521-3529 |
| 16 | Phase overflow | a phase past F14.3 is clipped by ±10⁹ cycles and LLI set | same, LLI bit 0 | rinex211.txt l.1291-1293; rinex305.txt §6.7 p.43; rinex_4.02.txt §6.7 p.49 |
| 17 | Observation types | one list for all systems (`# / TYPES OF OBSERV`), 2-character codes. 2.10: L1 L2 C1 P1 P2 D1 D2 T1 T2 S1 S2. 2.11: C pseudorange (GPS C/A or L2C; GLONASS C/A; Galileo all), P pseudorange (GPS and GLONASS P code), L phase, D Doppler, S signal strength; frequency codes GPS 1, 2, 5; GLONASS 1, 2; Galileo 1, 5, 6, 7, 8; SBAS 1, 5. AS observations are written as L2/P2 with LLI bit 2 | per-system lists (`SYS / # / OBS TYPES`), 3-character `tna` codes; a blank attribute is not allowed from 3.02 (except the `X` channel pseudo-observation) | rinex210.txt Table A1 l.886-897; rinex211.txt Table A1 l.1144-1175; rinex_4.02.txt Table 9 p.29 l.1494-1513 |
| 18 | BeiDou band digits | not defined (BeiDou in RINEX 2 is non-standard) | B1I (1561.098 MHz) is band 2 in 3.01 and from 3.03, band 1 in 3.02 (`C1I`); from 3.04 band 1 is B1C (1575.42 MHz). The adapter maps 3.02 band 1 to B1I; never in 3.04+ | rinex301.txt p.11 Table 5; rinex302.txt p.20 Table 7; rinex303_update1.txt p.24 (read rule); rinex_4.02.txt Table 15 p.34; `rinexcore/spec/obscodes.py` `BDS_B1_READ_RULE` |
| 19 | GLONASS FDMA channel | none in the file | `GLONASS SLOT / FRQ #`: optional in 3.01, mandatory from 3.02. The record's field allows −7…+6; Table 11's frequency formula gives k = −7…+12. The adapter accepts −7…+12 and reports a value outside −7…+6 as a compliance finding | rinex301.txt Table A1 p.32 l.2122; rinex305.txt Table A2 p.57 l.3110; rinex_4.02.txt Table A2 p.67 l.3628-3632, Table 11 p.31 |
| 20 | Systems | 2.10: G R S T; 2.11: G R E S (T removed). C, J and I satellites in a RINEX 2 file are non-standard | 3.00 G R E S; + C in 3.01; + J in 3.02; + I in 3.03 | `tests/expectations/allowed_losses.json` `systems` (rinex210.txt Table A1, rinex211.txt §10.1.3, rinex301.txt p.8, rinex302.txt, rinex303.txt) |

### 1.2 Rules that follow from the table

- **Missing.** An observation is *missing* when its field is blank or its value (after any scale
  factor) is exactly 0 at the file's resolution (`0.000`). Its LLI and SSI are then not used; they
  are counted apart as "flags on a missing value". A `0.000` is never a measurement.
- **LLI on the wrong type.** An LLI bit where the version allows none (rows 2): in RINEX 2 bits 0-1
  on code, Doppler or S; in 3.00-3.04 bit 0 on a non-phase type; in 3.05/4.x any bit on a non-phase
  type. It is ignored and counted in `obs.avail.flags`.
- **LLI bit 2** is reported under its version's meaning: `as` (RINEX 2), `boc` (3.01 on),
  `undefined` (3.00). The adapter never translates one into the other.
- **Half-cycle state** (one canonical count in every version, `obs.avail.flags`):
  - RINEX 2, GPS L1/L2 phase: the ambiguity spacing factor in force (the header default, then
    satellite lines, then event records), flipped by LLI bit 1 for that epoch; *half-cycle* when it
    is 2. Phase values are never rescaled.
  - RINEX 2, any other phase: LLI bit 1 is taken as half-cycle **[P8]**. RINEX 2 defines wavelength
    factors for GPS L1/L2 only (rinex211.txt l.999-1001), so bit 1 elsewhere has no defined meaning;
    this is an interpretation, labelled as one, and it matches rinexconv, which copies bit 1 there
    verbatim (rinexconv/obsconv.py `_copy_plan`).
  - RINEX 3/4: LLI bit 1.
- **SNR unit.** `dB-Hz` only when the header says `DBHZ` or the user's table lists the receiver
  type (D5); otherwise `relative`. The SSI digit is always `ordinal`, never converted to dB-Hz.
- **Signal keys.** Every observable gets a canonical scope key, the same in every version for the
  same data:
  - RINEX 3/4: `<system>:<code>` with the 3-character code, band digits normalised (3.02 BeiDou
    `C1I` becomes `C:C2I`): `G:C1C`, `G:L2W`, `C:C2I`.
  - RINEX 2: `<system>:<code>` with the 2-character code: `G:C1`, `G:P1`, `G:P2`, `G:L2`. The type is
    the code's letter (P is a pseudorange), the band its digit read with the RINEX 3 meaning for the
    system; the attribute is unknown. C2 is "GPS L2C, component unknown" (rinex211.txt l.1148); P2 is
    "P(Y), Z-tracking or semi-codeless". `--overrides` sets attributes as in rinexconv, and then the
    key is the 3-character code; rinexconv's defaults are never borrowed silently. Results name the
    code that fed them ("MP2 from P2").
  - A code listed twice in one type list keeps both columns (as rinexconv does,
    `OBS.DUPLICATE-CODE-KEPT`): the second column's key gets `#2` (`G:C1C#2`), and the duplicate is a
    compliance finding.
- **Non-standard systems in RINEX 2 [P1].** C, J and I satellites in a RINEX 2 file are read as
  rinexcore reads them; their band digits get the RINEX 3 meaning for that system, the attribute is
  unknown, and every metric scoped to them is `degraded(non-standard-system)`.
- **Phase overflow.** A clip is identified, as a *candidate*, when an epoch has LLI bit 0 and the
  phase changed by ±10⁹ cycles to within 10⁷ cycles (a 30 s epoch can move the phase by about 10⁵
  cycles, so the window is wide). It is counted as `overflow-clip-candidate`, as an inference; the
  LLI bit 0 stays in the `lost-lock` count, since resemblance alone does not prove a clip.
- **Events.** Header records after flags 2-5 take effect from that epoch (type lists, scale factors,
  wavelength factors, GLONASS channels). Flag-6 records are receiver-reported slips: evidence, not
  observations.
- **Time.** Epochs are kept in the file's time system; RINEX `GLO` tags get no 3 h shift. Time-scale
  conversions (Q2) are explicit and cited there.

### 1.3 Corrections to PLAN.md rev. 4 found in the check

These are corrections of the plan's text, recorded here and in docs/DECISIONS.md; the plan's §5.1,
§5.2 and §5.6 wording is left for the user to approve (Q0a may edit only PLAN §5.10).

1. §5.2 frequency table: "rinex_4.02.txt Tables 10-16, printed pp.29-34" are **pp.30-35** in the
   project's page convention (the PDF page markers).
2. §5.6: "rinex_4.02.txt §4.1.2 p.15" is **p.16** (printed 15).
3. §5.2 row "Event flags", source "rinex305.txt §6.5 p.42": §6.5 is the validity rule (row 10). The
   flags themselves are §5.3.2 p.37 and Table A3 p.59-60.
4. §5.2 row "Wavelength factor", RINEX 3/4 "none": add that codeless squaring has its own attribute
   N and that a possible half-cycle ambiguity is LLI bit 1 (rinex305.txt §5.2.13 p.28).
5. §5.2 row "LLI bit 2": 3.01-3.04 word it "Galileo BOC-tracking"; 3.05 and 4.x drop "Galileo".
6. §5.2 row "S observations": the record exists from 3.00 (rinex300.txt p.28), not only rinex303.txt.
7. **§5.1 item 4: the plan's example is wrong.** It says a source's C2 "is the target's assumed
   C2W". rinexconv maps a RINEX 2 GPS **C2 to C2X** and **P2 to C2W** (rinexconv/codemap.py:26-30,
   assumption `obs-code-attribute:G`, detail `C2->C2X`); with C2 and no P2, L2/D2/S2 follow the code
   (2X). The invariance table uses the converter's actual mapping, through the report.
8. §5.2 row "Scale factors", RINEX 2 "none": real RINEX 2 files can carry the unofficial 2.20
   `OBS SCALE FACTOR`, which rinexconv honours (row 11).
9. New rows the plan lacked: 2 (LLI scope), 10 (validity), 16 (overflow), 17 (type lists), 18 (BDS
   band digits), 19 (FDMA channel record and its two ranges), 20 (systems), and in row 15 the
   2.10/2.11 difference and the GEO default.

---

## 2. Frequencies and pairs

Checked against rinex_4.02.txt Tables 10-16 (pp.30-35); the version in which each band first appears
is from the per-version tables as transcribed in `rinexcore/spec/obscodes.py`, whose tests check
every code against the spec text (docs/SPEC_TABLES.md), and from rinex210.txt l.886-897 and
rinex211.txt l.1158-1165 for RINEX 2.

| System | RINEX band: MHz (signals) | Band appears in | Pairs (preferred first) |
|---|---|---|---|
| GPS | 1: 1575.42 (L1); 2: 1227.60 (L2); 5: 1176.45 (L5) | 1, 2: 2.10; 5: 2.11; all three in 3.00 | L1/L2, L1/L5, L2/L5 |
| GLONASS FDMA | 1: 1602 + k·9/16 (G1); 2: 1246 + k·7/16 (G2); k = −7…+12 | 1, 2: 2.10 | G1/G2 (needs k) |
| GLONASS CDMA | 4: 1600.995 (G1a); 6: 1248.06 (G2a); 3: 1202.025 (G3) | 3: 3.02; 4, 6: 3.04 | G1a/G2a, G1a/G3 |
| Galileo | 1: 1575.42 (E1); 5: 1176.45 (E5a); 7: 1207.140 (E5b); 8: 1191.795 (E5 AltBOC); 6: 1278.75 (E6) | all five: 2.11 and 3.00 | E1/E5a, E1/E5b, E1/E5, E1/E6 |
| BeiDou | 2: 1561.098 (B1I); 1: 1575.42 (B1C, B1A); 5: 1176.45 (B2a); 7: 1207.140 (B2I, B2b); 8: 1191.795 (B2a+B2b); 6: 1268.52 (B3I, B3A) | 2, 6, 7: 3.01 (3.02: B1I as band 1); 1 (B1C), 5, 8: 3.04 | BDS-2: B1I/B3I, B1I/B2I. BDS-3: B1I/B3I, B1C/B2a |
| QZSS | 1: 1575.42; 2: 1227.60; 5: 1176.45; 6: 1278.75 | 3.02 | L1/L2, L1/L5 |
| NavIC | 1: 1575.42 (L1); 5: 1176.45 (L5); 9: 2492.028 (S) | 5, 9: 3.03; 1: 4.01 | L5/S, L1/L5 |
| SBAS | 1: 1575.42; 5: 1176.45 | 1: 2.10 (single frequency, rinex210.txt l.750-753); 5: 2.11 | L1/L5 |

- Every pair is computed where the file has it, each under its own name; the preferred pair is only
  what the summary and the grade show.
- BDS-2 or BDS-3 comes from a dated PRN table built from the IGS satellite metadata SINEX (D2), never
  from the PRN alone. Without it, BeiDou pair metrics are `cannot-compute(missing-sat_meta)` except
  B1I/B3I, which both generations transmit.
- **GLONASS k** (PLAN §5.2): the file's `GLONASS SLOT / FRQ #` epoch by epoch (an event record applies
  from its epoch, to every satellite it names; a change is reported), then `--glo-fcn`, then a
  same-day nav file. Disagreeing sources are reported, never reconciled. Without k, every metric that
  needs a GLONASS FDMA wavelength is `cannot-compute(no-channel)`.
- Worked numbers for GPS L1/L2 (used in §4.4): λ1 = 0.190294 m, λ2 = 0.244210 m, λ2 − λ1 = 0.053917 m,
  γ = (f1/f2)² = 1.646944, wide-lane λ_WL = c/(f1 − f2) = 0.861918 m.

---

## 3. Shared definitions

- **Reading and refusal (D1, [P6]).** A file is *refused* when rinexcore's reader raises
  `CorruptError`, **or** when rinexcore's validator finds data-level damage the reader read past
  (text beyond the last field, a value such as `12.3.4`, a truncated record): the rule set rinexconv
  refuses by default (`_DAMAGE_RULES`, rinexconv/engine.py:343-377, PLAN §1 clause 9). rinexqc may not
  import rinexconv, so Q0b moves that rule set into `rinexcore/validate.py` as a named set used by both.
  Under `--lenient` the lenient reader reads the file and the damage findings are reported in
  compliance. A file even the lenient reader refuses stays refused.
- **Lenient read.** `lenient_read` is `true` exactly when the run used the lenient reader
  (`--lenient`), whether or not it had to repair anything; the repairs it made are listed in
  compliance (QC_SCHEMA §2). One definition, used everywhere.
- **Data epoch:** an epoch with flag 0 or 1. Events (flags 2-6) are not data epochs.
- **Evaluation interval:** from the first to the last data epoch, in the file's time system.
- **Sampling interval Δ.** *Declared* = `INTERVAL`; *inferred* = the modal spacing of consecutive
  distinct data epochs (ties: the smallest). They *agree* when |declared − inferred| ≤ 1 ms. QC uses
  the declared value when they agree and the inferred one otherwise, and says which and why.
- **Grid:** the epochs 00:00:00 (of the first data epoch's day) + m + n·Δ for every integer n (the
  same grid continues across midnight), where m is the median, over the data epochs, of their offset
  from the midnight grid. Offsets are taken signed and unwrapped around the first epoch's offset o₁
  (each in (o₁ − Δ/2, o₁ + Δ/2]), so epochs near half a grid step do not split the median. The *grid
  offset* of an epoch is o = t − (nearest grid epoch). A constant offset is reported
  (`obs.time.grid`), not jitter.
- **Cadence class:** `1 s` (Δ ≤ 1 s), `2-15 s`, `30 s` (Δ = 30 s), `other` (every other Δ).
- **File gap:** a maximal run of grid epochs inside the evaluation interval with no data epoch within
  Δ/2 of it. Epochs missing before the first or after the last data epoch are not gaps: they shorten
  the span (and show in `obs.header.first_last` when the header says otherwise).
- **Availability arc** of a satellite: a maximal run of data epochs from an epoch at which it has a
  non-missing observation to a later such epoch, such that the time elapsed between any two
  consecutive epochs with its observations is at most G_arc (G_arc = max(300 s, 10·Δ), **[P2]**;
  exactly G_arc does not split). An arc also ends at an epoch with flag 1, 2 or 3 (**[P3]**: PLAN
  lists 2 and 3; flag 1, a power failure, is added) and where a type-list change leaves the satellite
  no type.
- **Satellite gap:** inside an arc, a maximal run of data epochs at which the satellite has no
  non-missing observation. On a regular grid, N missing epochs leave the surviving observations
  (N + 1)·Δ apart: a satellite gap when (N + 1)·Δ ≤ G_arc, an arc split when it is larger (at 30 s:
  up to 9 epochs is a gap, 10 or more a split).
- **Phase arc** (Q3) of a (satellite, signal): as an availability arc of that phase, broken also by a
  missing phase, LLI bit 0, LLI bit 1 in RINEX 3/4 (or a half-cycle change in RINEX 2), a flag-6
  record naming the satellite, an overflow-clip candidate, a type-list change removing the signal, a
  change of its wavelength factor (RINEX 2) or of its GLONASS channel. Its gap threshold is frozen at
  Q3's start (v0 default: any missing epoch).
- **Support:** the counts behind a value (epochs, satellites, arcs, observations) and, apart, how
  many were excluded and why. A test needing N satellites at an epoch is *testable* there only if
  N are available; untestable epochs are counted, never treated as negatives.
- **Quantiles.** SNR quantiles are exact: values are counted by distinct value (S is written to
  three decimals). If a counter passes 4096 distinct values it switches to a 0.01-unit histogram and
  the method says `approx-0.01`. Arc medians for multipath (Q3) are exact by spooling the arc
  (rinexcore's spool), or a stated approximation frozen at Q3.
- **Header counts.** Satellites are counted from the records of flag 0, 1 and 6 epochs; observations
  per (satellite, type) are the non-missing values in flag 0 and 1 epochs (rinex305.txt Table A2
  "number of observations"), as rinexconv counts them (repair `HDR.COUNTS`, rinexconv/obsconv.py).
- **Event matching** (gates, §7): a detected event *matches* an injected one when it is of the same
  class at the injected epoch (clock steps, tag jumps, gaps: the same epoch exactly; SNR drops: the
  events overlap and start within one epoch). An *incremental false alarm* is a detected event on
  an injected file that matches nothing injected and is not on the source file (same class, same
  epoch ± 1). Recall = matched / injected-and-testable; precision = matched / (matched + incremental
  false alarms).
- **Confidence intervals.** Trials made from real files are clustered by their **original source
  file**, however many copies were made from it: a cluster bootstrap over source files (2000
  resamples, seed 20261106, percentile 95%; each resampled file brings all its trials, so files
  weigh by their trial counts). The Wilson 95% score interval is used only for trials that are
  independent by construction: each from its own fully synthetic file.

---

## 4. Metric catalogue

Each entry gives: **definition**; unit; scope (`file`, `system`, `satellite`, `signal`,
`(satellite, signal)`, `pair`); arc resets; cadence limits; inputs (codes of §5); milestone. All are
*evidence* unless marked *inference* or *hypothesis* (PLAN §5.1 item 2). "Signal" means the
observable's key of §1.2.

### 4.1 Observation files, from the file alone (Q1, PLAN §5.3.1)

| Id | Definition | Unit | Scope | Cadence | Inputs |
|---|---|---|---|---|---|
| `obs.compliance` | Refusal (§3) if any: the reader's `CorruptError` (rule, line, column, message) or the first damage finding; the reader's repairs (default and lenient); the validator's findings, split into header-only and data-level | count + list | file | any | OBS |
| `obs.header.interval` | Declared and inferred Δ (§3), whether they agree, which one is used | s | file | any; needs 2 data epochs | OBS |
| `obs.header.first_last` | `TIME OF FIRST OBS` / `TIME OF LAST OBS` minus the first / last data epoch | s | file | any | OBS |
| `obs.header.counts` | `# OF SATELLITES` and `PRN / # OF OBS` against the counts from the data, counted as §3 "Header counts" | count (differences) | file, (satellite, type) | any | OBS |
| `obs.header.blank_types` | Declared types with no non-missing value in the whole file (per system in RINEX 3/4) | list | system | any | OBS |
| `obs.header.position` | `APPROX POSITION XYZ`: zero, or ellipsoidal height h (GRS80) with \|h\| > 50 km, is a finding | m | file | any | OBS |
| `obs.header.names` | Receiver and antenna type against `rcvr_ant.tab`; antenna + radome against `igs20.atx` | finding list | file | any | OBS, RAT, ATX |
| `obs.time.span` | First and last data epoch, duration, time system and where it came from (header or default) | s | file | any | OBS |
| `obs.time.grid` | Δ used, the grid offset m, the fraction of data epochs with \|o\| ≤ 1 µs | s, fraction | file | any | OBS |
| `obs.time.order` | Duplicate epochs (same time; identical or differing content) and out-of-order epochs (t_k < t_k−1) | count + epochs | file | any | OBS |
| `obs.time.jitter` | Grid-offset statistics (median, σ̂, max \|o\|) and **epoch-tag jumps**: \|o_k − o_k−1\| above T-tag, with σ̂ taken over the W-clk epochs before k | s | file | any | OBS |
| `obs.time.gaps` | File gaps and satellite gaps (§3): count, missing epochs, start and end of each | count, s | file, satellite | any | OBS |
| `obs.arcs` | Availability arcs per satellite (§3): count, length (min, median, max), why each ended | count, s | satellite | any | OBS |
| `obs.avail.observed` | **Observed count**: data epochs with a non-missing value of that observable (missing = blank or 0.0, whatever LLI or SSI say) | count | (satellite, signal), signal | any | OBS |
| `obs.avail.coverage` | Code with phase: fraction of a satellite's data epochs (in its arcs) with both a code and a phase on the band. Dual- and triple-frequency: fraction of satellite-epochs with phase on ≥ 2 and ≥ 3 bands | fraction | (satellite, band), system | any | OBS |
| `obs.avail.flags` | Raw LLI bit counts by version meaning (bit 0; bit 1 as `opposite-wavelength-factor` (2.x) or `half-cycle` (3/4); bit 2 as `as` (2.x), `boc` (3.01+), `undefined` (3.00)); flags on missing values; LLI where the version allows none. **Canonical counts**, the same in every version: `lost-lock` (bit 0 on a phase), `half-cycle` (§1.2), `overflow-clip-candidate` (§1.2, a subset of `lost-lock`) | count | (satellite, signal) | any | OBS |
| `obs.snr.dist` | Distribution of S values: count, mean, median, σ̂, p5, p95, min, max; SSI digit histogram (code and phase) | dB-Hz or relative; ordinal | (satellite, signal), signal | any | OBS, RT |
| `obs.snr.dropouts` | Drop events of §4.1.2 | count, dB-Hz or relative | (satellite, signal) | any | OBS, RT |
| `obs.snr.ssi_consistency` | Fraction of observations whose SSI digit equals MIN(MAX(INT(S/6),1),9) of the same band and attribute's S | fraction | signal | any; only RINEX 3/4 with dB-Hz | OBS, RT |
| `obs.clock.code_jumps` | Steps in code (§4.1.1: tests T1 and T3) | m and s; count | file | any (sub-ms limits per cadence) | OBS, FCN for GLONASS FDMA |
| `obs.clock.phase_jumps` | Steps in code and phase together (§4.1.1: test T2) | m and s; count | file | any (sub-ms limits per cadence) | OBS, FCN |
| `obs.clock.tag_jumps` | The epoch-tag jumps of `obs.time.jitter`, as the third clock series | s; count | file | any | OBS |
| `obs.clock.class` | *Inference*: "jumps in code only", "jumps in code and phase", "no jumps", "undetermined" (§4.1.1) | class | file | any | OBS |
| `obs.clock.offset` | `RCV CLOCK OFFS APPL` as given; the epoch-line offset series as given (count, first, last, min, max). Steering and drift are **not** inferred here (Q4) | s | file | any | OBS |

#### 4.1.1 Receiver-clock steps

Three tests per data epoch k whose predecessor k−1 is the previous grid epoch (no gap between). Each
has a support n_k (satellites with the needed observations at the epochs it uses) and a noise σ_k:
the σ̂ of its common estimate over the W-clk testable epochs **before** k, excluding epochs where a
step was found (one-sided, so a step at k does not inflate its own noise). Once a step b̂ is found at
k, every later window of that test uses the series with b̂ removed from the epochs ≥ k (for T2's
cubic, the phases; for the noise windows, the common estimates), so one step gives one event and the
fits after it do not ring.

| Test | Statistic, per satellite s | Common estimate | Responds to | Testable when |
|---|---|---|---|---|
| T1 code minus phase | d_s = Δ(P_s − Φ_s), Φ in metres (λ·L), Δ the epoch difference | b̂ = median_s d_s | a step b in code only (code-and-phase steps cancel; so do geometry and the clock common to both) | n_k ≥ 4 satellites with code and phase at k−1 and k |
| T2 phase | with Doppler: r_s = ΔΦ_s + λ(D_s,k + D_s,k−1)/2·Δt (phase changes in the sense of the range, the negative Doppler: rinex211.txt l.451). Without: r_s = Φ_s,k − p_s(t_k), p_s a cubic fitted to the W-clk epochs before k | b̂ = median_s r_s | a step b in phase (with code or not); not a code-only step | n_k ≥ 4 satellites with phase (and Doppler, or W-clk earlier epochs) |
| T3 millisecond | the second difference of code, Δ²P_s,k = P_s,k − 2P_s,k−1 + P_s,k−2 | b̂ = median_s Δ²P_s | any code step of millisecond size (+b at k, −b at k+1); needs no phase | n_k ≥ 2 satellites with code at k−2, k−1, k |

- A test *fires* at k when \|b̂\| > max(T-clk·σ_k, floor); floors (§6): T1 and T2 1 m; T3 fires only for
  \|b̂\| > c·0.5 ms and reports m = round(b̂/(c·1 ms)) when \|b̂/(c·1 ms) − m\| < 0.01.
- **T3's two lobes.** A step at k gives Δ²P = +b at k and −b at k+1. A T3 alarm at k+1 whose estimate
  is within 1% of −b̂_k is the second lobe of the step at k, not a second step; the pair is one event at
  k. A lone lobe (k+1 untestable) is still one event at k.
- **Classification of a step at k:**
  - *code only*: T1 fires and T2 does not; size from T1 (and m from T3 when it fires);
  - *code and phase*: T2 fires and T1 does not; size from T2 (and m from T3 when it fires);
  - *code and phase, unequal*: both fire; both sizes reported;
  - *code, phase unknown*: only T3 fires (no phase to test).
- **Worked examples.** A 1 ms code-only jump adds 299 792.458 m to every P_s at k: T1 gives
  b̂ = 299 792.458 m and fires; T2 sees no change; T3 gives +b̂ at k and fires with m = 1: "code only,
  1 ms". A 1 µs code-and-phase jump adds 299.792 m to every P_s and Φ_s: T1 sees 0; T2 gives
  b̂ = 299.792 m and fires; T3 stays below c·0.5 ms: "code and phase, 0.001 ms".
- **Detection limit**, stated per file and test: max(T-clk·median_k σ_k, floor), in metres and seconds.
- **Class** (`obs.clock.class`): "no jumps" when ≥ 90% of data epochs were testable by both T1 and T2
  and no test fired; "jumps in code only" / "jumps in code and phase" when every step found is of
  that class; "undetermined" otherwise, with the reason (`too-few-testable`, `mixed`, or `ms-only`
  when only T3 could test: then the detail says whether any millisecond jump was found). Every class
  is stated with the file's detection limits.

#### 4.1.2 SNR drops

Per (satellite, signal), within an arc: the reference r_k is the median of the last W-snr values
before k that are not part of a drop event (at least 5, else k is untestable). Epoch k is *low* when
S_k ≤ r_k − T-snr. A drop event is a run of consecutive low epochs (start, length m, depth = the
largest r_k − S_k). A run longer than W-snr epochs is closed as a `level-change` and the reference
restarts after it, so a permanent change is not reported as an endless drop. The detection limit is
T-snr, stated.

### 4.2 Navigation files, from the file alone (Q1, PLAN §5.4)

These read fields by name from the named-field table that Q0b adds to `rinexcore/spec/`. Every limit
cites its ICD; the ICDs are not in `specs/` yet (§9, D6).

| Id | Definition | Unit | Scope | Inputs |
|---|---|---|---|---|
| `nav.compliance` | Refusal (§3) and validator findings, as for obs | count + list | file | NAV |
| `nav.coverage` | Per satellite, the union of each record's validity window (per system and message, from its ICD: fit interval, or the nominal validity) inside the file's span | s, fraction | satellite | NAV, ICD |
| `nav.gaps` | Spans of the file's interval no valid record covers | s, list | satellite | NAV, ICD |
| `nav.health` | Health and accuracy fields as broadcast (URA, SISA, SV health, GLONASS Bn): counts per value | count | satellite | NAV |
| `nav.iod` | IOD consistency: GPS/QZSS LNAV IODE = IODC mod 256; Galileo IODnav; BeiDou AODE/AODC; GLONASS tb against the epoch; changes of IOD without a change of data, and the reverse | count + list | satellite | NAV, ICD |
| `nav.times` | Toe and Toc, transmission time, fit interval: Toc ≠ Toe where the ICD has them equal; transmission time after Toe + validity; fit flag | count + list | satellite | NAV, ICD |
| `nav.duplicates` | Records with the same satellite, message and Toc: identical, or conflicting (different values) | count + list | satellite | NAV |
| `nav.ranges` | Parameters against each ICD's range (√A, e, i, clock terms, GLONASS state); a value out of range is a finding | count + list | satellite, field | NAV, ICD |
| `nav.glo_tk_basis` | GLONASS tk on the day or the week basis (the known damage in real 3.x files) | class | file | NAV |
| `nav.msg_types` | Records per system and message type: RINEX 4 as written; RINEX 3 as the record kind (LNAV, FDMA, INAV/FNAV from the Galileo data-source bits, D1/D2, SBAS) | count | system | NAV |

### 4.3 Meteorological files (Q1, PLAN §5.5)

Types and units: PR mbar, TD °C, HR %, ZW mm, ZD mm, ZT mm, WD deg, WS m/s, RI 1/10 mm, HI
indicator (rinex211.txt Table A5 l.1455-1468; WD, WS, RI, HI from 2.11; rinex_4.02.txt p.125-126
l.7203-7229).

| Id | Definition | Unit | Scope | Inputs |
|---|---|---|---|---|
| `met.compliance` | Refusal (§3) and validator findings | count + list | file | MET |
| `met.time` | Span, Δ (declared/inferred as §3), gaps, duplicate and out-of-order epochs | s, count | file | MET |
| `met.ranges` | Values outside T-met-range (§6) per type | count + list | type | MET |
| `met.jumps` | \|Δvalue\| between consecutive epochs ≤ 15 min apart above T-met-jump (§6) | count + list | type | MET |
| `met.sensors` | `SENSOR MOD/TYPE/ACC` present for every type in the data, `SENSOR POS XYZ/H` present; types declared but never observed; sensors with no data | finding list | file | MET |

### 4.4 Later milestones (definitions; gates frozen at each milestone's start)

**Q2: orbits and geometry (PLAN §5.6).** Inputs NAV or SP3 (+ATX for the PCO, SMS for blocks).

| Id | Definition | Unit | Scope | Inputs |
|---|---|---|---|---|
| `orb.azel` | Azimuth and elevation per satellite and epoch from the header position (or SPP, or IGS20, said which), signal travel time and Earth rotation included | deg | satellite | OBS, NAV or SP3 |
| `obs.complete.visibility` | Epochs above the elevation mask (configurable, default 10° [P4]) | count | satellite | OBS, NAV or SP3 |
| `obs.complete.healthy_nav` | Epochs with a healthy ephemeris ("healthy" per system from each ICD) | count | satellite | OBS, NAV, ICD |
| `obs.complete.tracking` | k, K, Uₒ, Uₘ and the bounds k/(K+Uₘ) and (k+Uₒ)/(K+Uₒ) (PLAN §5.6); declared and inferred grid both reported | fraction | (satellite, signal) | OBS, NAV, SMS |
| `obs.complete.visible_only` | As above without health (SP3 alone) | fraction | (satellite, signal) | OBS, SP3, SMS |
| `obs.sky.*`, `obs.snr.vs_elevation` | Sky plots and elevation bins of SNR, multipath, slips, gaps | — | — | as above |
| `obs.obstruction` | *Hypothesis*: missing or low SNR by azimuth and elevation | map | file | as above |

**Q3: combinations (PLAN §5.3.2).** Phase Φᵢ = λᵢLᵢ (m), code Pᵢ (m); pair (i, j), γ = (fᵢ/fⱼ)².
Arc resets: the phase arc of §3 for both signals. All need the pair's wavelengths (GLONASS FDMA: k).

| Id | Formula | Unit | Cadence | Noise (GPS L1/L2, equal code noise σ_P) |
|---|---|---|---|---|
| `obs.combo.mw` | MW = (fᵢΦᵢ − fⱼΦⱼ)/(fᵢ − fⱼ) − (fᵢPᵢ + fⱼPⱼ)/(fᵢ + fⱼ), in cycles of λ_WL = c/(fᵢ − fⱼ) | cycles | any | ≈ 0.71 σ_P / λ_WL; blind to equal-cycle slips on both bands |
| `obs.combo.gf` | GF = Φᵢ − Φⱼ | m | eligibility per cadence frozen at Q3 | √2 σ_Φ; a GPS (1,1) slip moves it by 0.0539 m |
| `obs.combo.sf` | Single-frequency phase minus code, Pᵢ − Φᵢ | m | any | ≈ σ_P; drifts by 2Iᵢ |
| `obs.combo.doppler` | ΔΦᵢ + λᵢ(Dᵢ,k + Dᵢ,k−1)/2·Δt | m | ≤ 1 s | — |
| `obs.mp` | MPᵢ = Pᵢ − (1 + 2/(γ−1))Φᵢ + (2/(γ−1))Φⱼ, minus the arc bias (the arc median; arcs under 10 epochs dropped and counted, as squidy `math.md` l.276-277); RMS per satellite and signal. GPS: 4.0914 and 3.0914 on L1/L2 | m | any | code noise + multipath |
| `obs.cmc` | Pᵢ − Φᵢ per signal, detrended per arc | m | any | — |
| `obs.phase_noise.gf` | σ_GF = σ(Δ³GF)/√20 (the third difference of white noise has variance 20σ²), static segments only; also σ_GF/√2, the per-phase noise if both phases are equally noisy, labelled as that assumption | m | ≤ 1 s | — |
| `obs.iono.gf_rate`, `obs.iono.rot` | dSTEC/dt from GF, with fᵢ > fⱼ: STEC = (Φᵢ − Φⱼ)/(40.3·(1/fⱼ² − 1/fᵢ²)) up to a constant (el/m², divided by 10¹⁶ for TECU) | TECU/min | ≤ 30 s | — |
| `obs.iono.roti` | σ of ROT over 5 min (Pi et al. 1997); the ROT interval is named | TECU/min | ≤ 30 s | — |
| `obs.snr.s4_proxy` | *Proxy*: √((⟨I²⟩ − ⟨I⟩²)/⟨I⟩²), I = 10^(S/10), 60 s windows, detrended; never called scintillation | — | ≤ 1 s; dB-Hz only | — |
| `obs.slips.evidence.*` | Per test (mw, gf, sf, doppler, lli, flag6): epochs where it fired | list | per test | — |
| `obs.slips.inferred` | *Inference*: slips under documented combination rules; observations per slip (teqc `o/slps`) | count | (satellite, signal) | — |
| `obs.consistency.*` | Code vs Doppler, phase vs Doppler, between signals (needs the alignment state) | m | — | — |

**Q4: SPP and SISRE (PLAN §5.4, §5.6).** `obs.spp.*` (positions, scatter against header and IGS20,
DOPs, code residuals, receiver clock; models of PLAN §5.6; Galileo single-frequency ionosphere:
Klobuchar, `degraded(approximation)` (D3)); `obs.clock.steering` and `obs.clock.drift` from the SPP
clock or the epoch-line series; `nav.sisre`, `nav.sisre_orbit_only` (SP3, CLK, ATX; conventions of
PLAN §5.4 frozen at Q4).

**Q6: precise products (PLAN §5.7).** `obs.resid.precise` (SP3, CLK, ATX, BSX, CRD; each correction
listed), `obs.coord.igs20` (CRD), `obs.sitelog` (LOG), `trend.*` (multi-day).

---

## 5. Input matrix

Codes: OBS, NAV (same span), MET; SP3; CLK (clock RINEX); ATX (`igs20.atx`); RAT (`rcvr_ant.tab`);
SMS (IGS satellite metadata SINEX); BSX (bias SINEX); CRD (IGS20 SINEX coordinates); LOG (site log);
FCN (`GLONASS SLOT / FRQ #`, or `--glo-fcn`, or a same-day NAV); RT (the user's SNR receiver table,
D5); OVR (`--overrides`); ICD (the ICD texts, §9 D6, as tables in `rinexcore/spec/` with citations).
Without a needed input the metric is `cannot-compute(missing-<input>)`; an optional input only adds
detail. The roles in QC_SCHEMA §1 match these codes.

| Metric group | Needs | Optional |
|---|---|---|
| `obs.compliance`, `obs.header.*` (except names), `obs.time.*`, `obs.arcs`, `obs.avail.*` | OBS | OVR |
| `obs.header.names` | OBS, RAT, ATX | — |
| `obs.snr.*` | OBS | RT |
| `obs.clock.*` | OBS | FCN (GLONASS FDMA satellites enter T1 and T2 only with k) |
| `nav.*` (Q1) | NAV | ICD needed for coverage, gaps, iod, times, ranges |
| `met.*` | MET | — |
| `orb.azel`, `obs.complete.visibility` | OBS + (NAV or SP3) | ATX, CRD |
| `obs.complete.healthy_nav` | OBS, NAV, ICD | — |
| `obs.complete.tracking` | OBS, NAV, SMS | — |
| `obs.combo.*`, `obs.mp`, `obs.cmc`, `obs.iono.*`, `obs.slips.*`, `obs.phase_noise.gf` | OBS (two bands), FCN for GLONASS FDMA, SMS for BDS-2/3 pairs | OVR |
| `obs.snr.s4_proxy` | OBS at ≤ 1 s with dB-Hz | RT |
| `obs.spp.*`, `obs.clock.steering`, `obs.clock.drift` | OBS, NAV (or SP3 + CLK) | BSX, ATX, CRD |
| `nav.sisre` | NAV, SP3, CLK, ATX | — |
| `nav.sisre_orbit_only` | NAV, SP3, ATX | — |
| `obs.resid.precise` | OBS, SP3, CLK, ATX, BSX, CRD | LOG |
| `obs.coord.igs20`, `obs.sitelog` | OBS, CRD / LOG | — |

---

## 6. Threshold set `qc-thresholds/0`

*Definitions* are fixed by this document. *Tuned* thresholds get a v0 default here, are tuned on the
calibration half only (§8) and then frozen with the commit hash; every result names the set and the
commit.

| Name | Kind | v0 value | Used by |
|---|---|---|---|
| Δ agreement | definition | 1 ms | `obs.header.interval`, `met.time` |
| G_arc | definition **[P2]** | max(300 s, 10·Δ) | `obs.arcs`, satellite gaps |
| on-grid | definition | \|o\| ≤ 1 µs | `obs.time.grid` |
| position | definition (PLAN §5.3.1) | non-zero and \|h\| ≤ 50 km (GRS80) | `obs.header.position` |
| overflow window | definition | \|ΔL ∓ 10⁹\| < 10⁷ cycles with LLI bit 0 | `obs.avail.flags` |
| T-tag | tuned | 10·σ̂(Δo), at least 0.2 µs (twice the 0.1 µs resolution) | `obs.time.jitter` |
| W-clk | tuned | 21 epochs | `obs.clock.*`, `obs.time.jitter` |
| T-clk | tuned | 6 (× σ_k) | `obs.clock.*` |
| floors | definition | T1, T2: 1 m; T3: c·0.5 ms | `obs.clock.*` |
| ms tolerance | definition | \|b̂/(c·1 ms) − m\| < 0.01 | `obs.clock.*` |
| W-snr | tuned | max(11, ⌈300 s/Δ⌉) epochs, at most 301 | `obs.snr.dropouts` |
| T-snr | tuned | 8 dB-Hz (dB-Hz files); 4·σ̂ of the arc (relative files) | `obs.snr.dropouts` |
| T-met-range | definition **[P5]** | PR 500-1100 mbar; TD −80…+60 °C; HR 0-100 %; ZW 0-600 mm; ZD 1000-2600 mm; ZT 1000-3000 mm; WD 0-360 deg; WS 0-75 m/s; RI ≥ 0; HI ≥ 0 | `met.ranges` |
| T-met-jump | definition **[P5]** | PR 3 mbar, TD 5 °C, HR 25 %, ZW/ZD/ZT 50 mm per step; none for WD, WS, RI, HI | `met.jumps` |

---

## 7. Q1 numeric gates (signed off by the user, 2026-11-06)

Q1 is accepted when every gate below holds (PLAN §7 row Q1, items a-e). Exact gates allow no
exception. Statistical gates are measured on the **held-out half** (§8) with thresholds frozen from
the calibration half; each is met when the point estimate reaches the target and the lower bound of
its 95% interval (§3) is at least the target − 0.02, over **≥ 300 trials per (event class, size,
cadence class) spread over ≥ 10 source files** (or every held-out file of that cadence class, if
fewer; the gate is then marked provisional until Q0b's additions give 10). Intervals are clustered by
source file (§3). Trials in one file copy are at least 2·max(W-clk, W-snr) epochs apart and at least
10 epochs from the file's edges and from any event on the source file; trials whose support is below
the test's minimum are counted and reported, not used. An injected event that produces more than one
detected event counts once; the extra events are false alarms.
A skipped oracle test says what it left unverified and cannot meet a gate. The `other` cadence class
has no gate: its results are reported.

Corpus today: 240 obs files at 30 s, 22 at 1 s, 7 at 15 s, 1 at 5 s, 35 without `INTERVAL`
(inferred).

### 7.1 Exact gates

| Gate | What | Target | Test set |
|---|---|---|---|
| E1 (a) | Equality with the independent checker (`tests/independent/qc/`, its own code from the specs, no project imports) for every deterministic Q1 output: `obs.avail.observed`, `obs.avail.coverage`, `obs.avail.flags` (raw and canonical), `obs.header.counts`, `obs.header.interval`, `obs.header.first_last`, `obs.header.blank_types`, `obs.time.span`, `obs.time.grid`, `obs.time.order`, `obs.time.gaps`, `obs.arcs`, `obs.snr.dist` (every statistic and histogram), `obs.snr.ssi_consistency`, `obs.clock.offset`; `nav.coverage`, `nav.gaps`, `nav.duplicates`, `nav.msg_types`, `nav.health`; `met.time`, `met.ranges`, `met.jumps` | integers and classes exactly, reals within 10⁻⁹ relative, every file | whole corpus |
| E2 (a) | `obs.avail.observed` against Anubis, after its counting rule is matched (written per oracle here when it is fetched); a residual difference goes to the user (PLAN §1 clause 10), never accepted silently | 100% of files Anubis reads | whole obs corpus (others: converted with rinexconv to a version Anubis reads) |
| E3 (b) | Version invariance: every metric listed as physical in `tests/expectations/qc_invariance.json` equal between each file and its rinexconv conversion to every write version, run with the same inputs and options, the source run restricted to the systems and signals the target holds (`--select`, QC_SCHEMA §1), within the file's bounds; every other difference allowed for a category in that conversion's report | 0 unexplained differences | every (corpus file, write version) cell that converts |
| E4 (d) | Every catalogue metric of the file's kind present with exactly one status; no non-null value without a unit; no null without a reason; the JSON valid against QC_SCHEMA v0 | 100% | corpus, fixtures, fuzz outputs |
| E5 | Known-answer fixtures, hand-written, for every Q1 metric including the detectors, each with a negative control: the stated values exactly (integers, classes) or within 10⁻⁹ relative (reals) | 100% | fixtures, each version family |
| E6 | Header fixtures: an injected wrong `INTERVAL`, `TIME OF FIRST/LAST OBS`, `# OF SATELLITES`, `PRN / # OF OBS`, an always-blank declared type, a zero or off-Earth position, an unknown receiver or antenna name: each reported; none on its clean source beyond what the source already had | 100% | fixtures, each version family |
| E7 (c) | Injected removals, with the outcome the ledger states for each placement: whole epochs removed inside the span (1, 2, 10, 100 in a row) give file gaps of exactly those epochs; removed at the start or end, they shorten `obs.time.span` by exactly that and give no gap. N consecutive epochs of one satellite removed inside an arc leave its observations (N + 1)·Δ apart: a satellite gap of exactly those epochs when (N + 1)·Δ ≤ G_arc, a split of the arc there when larger, with N chosen to include both sides of the boundary and (N + 1)·Δ = G_arc exactly; removed at an arc's edge, the arc shortens by exactly that | recall = precision = 100% | held-out half, every cadence class except `other` |
| E8 | Injected duplicate (identical, differing) and out-of-order epochs | 100% / 100% | fixtures, held-out half |
| E9 (c) | Injected epoch-tag jumps (tags only; observations unchanged; always \|δ\| ≤ 0.01·Δ) of ±1 ms and ±10 ms on every file, and of ±1, ±10, ±100 µs on files whose grid offset is constant at the file's 0.1 µs resolution. On files with drifting tags, the sub-ms sizes fall under the stated-limit rule of §7.2 | recall = precision = 100% | held-out half, every cadence class except `other` |
| E10 | Nav: `nav.glo_tk_basis` flags day basis on exactly the three known files (BRDC00IGS 2017, BOR100POL, CKIS00COK) and on no other | exact | whole nav corpus |
| E11 | Nav: one injected fault per check (`iod`, `times`, `ranges`, `health`) per system and message type present in the corpus: found; on the clean corpus every finding appears in a reviewed list | 100%; 0 unreviewed | fixtures; whole nav corpus |
| E12 | Met: injected out-of-range values (every type), steps above T-met-jump, removed epochs, missing sensor records: found; clean-corpus findings reviewed | 100%; 0 unreviewed | fixtures; whole met corpus |
| E13 | Corrupt and damaged inputs give the outcomes of §7.3 | 100% | the files of §7.3, fixtures |
| E14 | Fuzz (the seeded mutator of PLAN §4, same seeds and count as the converter's, on obs, nav, met): a schema-valid JSON for every mutant, or an `InvocationError` for an invocation fault; never another exception; under `--lenient`, every metric `lenient_read: true` | 100% | fuzz set |
| E15 (e) | MIZU00JPN 2026/290 (24 h 1 Hz, 1.6 GB) and the daily 30 s file meet the time, memory and output-size targets set in Q0b (PLAN §3.9) | met | the two budget files |

### 7.2 Statistical gates (injected events, held-out half)

Injection uses rinexconv's writer; each injected file is checked by the independent token comparator
against its truth ledger. Matching, recall, precision and intervals as §3.

**Receiver-clock steps** (`obs.clock.code_jumps`, `obs.clock.phase_jumps`, `obs.clock.class`). A step b
added to every satellite's code (*code only*) or to code and phase (*code and phase*; phase by b/λ).
Sizes: 1 ms (299 792 m), 1 µs (300 m), 100 ns (30 m), 10 ns (3 m); both signs.

| Class | Size | 1 s | 2-15 s | 30 s |
|---|---|---|---|---|
| code only | 1 ms | R ≥ 0.995, P ≥ 0.995 | same | same |
| code only | 1 µs | R ≥ 0.99, P ≥ 0.99 | same | same |
| code only | 100 ns | R ≥ 0.95, P ≥ 0.99 | same | same |
| code only | 10 ns | R ≥ 0.80, P ≥ 0.99 | stated limit only | stated limit only |
| code and phase | 1 ms | R ≥ 0.995, P ≥ 0.995 | same | same |
| code and phase | 1 µs | R ≥ 0.95, P ≥ 0.99 | with Doppler R ≥ 0.90; without: stated limit only | as 2-15 s |
| code and phase | 100 ns | R ≥ 0.90, P ≥ 0.99 | stated limit only | stated limit only |
| code and phase | 10 ns | stated limit only | stated limit only | stated limit only |

- Also, for every class: estimated size within max(1 m, 1%) of the injected one in ≥ 99% of
  detections; class (code only / code and phase, §4.1.1) right in ≥ 99%; **the stated detection
  limit honoured**: R ≥ 0.95 for injected steps ≥ 2× the limit the result states, at every cadence
  class; and the stated T1 limit ≤ 30 m on ≥ 90% of held-out files with ≥ 4 satellites tracked in
  code and phase.
- False alarms: incremental ≤ 0.01 per trial; on fully synthetic observations built from SP3 by
  independent test code (no steps, with noise, ionosphere and a random-walk clock): 0 in ≥ 100
  receiver-days at 30 s and ≥ 10 receiver-days at 1 s.
- Confounder fixtures (PLAN §5.9): an ionospheric gradient, a noisy low-elevation arc, a kinematic
  segment: 0 false steps.

**SNR drops** (`obs.snr.dropouts`, §4.1.2), on files with dB-Hz only (relative-unit files: reported, not
gated, `degraded(snr-unit-relative)`). S lowered by ΔS for m consecutive epochs on one (satellite,
signal) or on every signal of one satellite; SSI digits re-derived by the 3.x mapping where the file's
digits follow it (the ledger lists both).

| ΔS, m | every cadence class except `other` |
|---|---|
| ≥ 10 dB, 3 ≤ m < W-snr | R ≥ 0.95, P ≥ 0.95 |
| 20 dB, m = 1 | R ≥ 0.90, P ≥ 0.95 |
| ΔS ≥ T-snr + 2 dB (as frozen), 3 ≤ m < W-snr | R ≥ 0.80, P ≥ 0.95 (the stated limit honoured) |

- Confounders: a smooth 20 dB decline over 30 min (a setting satellite) and a 30-min arc with 2 dB σ
  noise: 0 drop events. Synthetic files (S = a smooth elevation-dependent curve plus Gaussian noise of
  σ = 1 dB-Hz, stated in the generator): at most 1 drop event per 100 satellite-days.
- The SNR statistics must still move with real change: on the confounder fixtures `obs.snr.dist`
  reports the decline (p5 and median follow it), PLAN §5.9.

### 7.3 Corrupt and damaged inputs: expected outcomes

"Refused" as §3: the reader's `CorruptError`, or a data-damage finding of the validator.

| Input | Default | `--lenient` |
|---|---|---|
| A file the reader refuses: mate1800.03m (met values off their F7.1 columns), DARW00AUS 2020 3.03 met (RINEX 2 epoch layout), BRDX00DLR 2020 "4.00" nav (pre-release format) | `input.read = refused-corrupt`; `*.compliance` holds the reader's rule, line, column and message plus the validator's findings; every other metric of that kind present with `value: null`, `cannot-compute(refused-corrupt)` | read with the reader's repairs (`MET.DATA.COLUMNS`, `MET.EPOCH.V2LAYOUT`, `NAV.V4.DRAFT-HEADER`) listed in compliance; every metric computed with its own status |
| Truncated file (partial last epoch) | refused-corrupt, as above | `OBS.TRUNCATED`: the partial epoch dropped; the evaluation interval ends at the last complete epoch |
| Damage the reader reads past (text beyond the last field, a malformed number, [P6]) | refused-corrupt (the validator's damage finding); the reader's own notes listed | read as read; the damage findings and the reader's notes (`OBS.DATA.SKIPPED-TEXT`, …) listed in compliance |
| A file even the lenient reader refuses | refused-corrupt | refused-corrupt |
| An input that decodes to nothing (e.g. `yell1800.10d.Z` as CDDIS has it) | refused-corrupt with the reader's rule | same |
| Header-only damage (wrong `INTERVAL`, counts, first/last times) | read; metrics `ok`; `obs.header.*` report the mismatch; the validator's header-only findings in compliance | same |
| Data-level findings the reader accepts that are not damage (duplicates, out-of-order epochs) | read; `obs.time.order` reports them; compliance lists them | same |
| A file of another kind (nav given as obs), an unreadable path, bad options | `InvocationError`, exit code as rinexconv's; no JSON result, never `refused-corrupt` | same |

Under `--lenient`, every result has `lenient_read: true` on every metric (§3), whatever was repaired.

---

## 8. Station split rule (PLAN §5.9)

The rule is fixed here; the split itself is computed and frozen in Q0b, after the corpus additions,
as `tests/corpus/qc_split.json`, before any calibration.

1. **Members:** every obs file in `tests/corpus/manifest.json` at the freeze, high-rate and hourly
   files included. Met files join their station's half. Merged nav files (BRDC, BRD4) are not split:
   Q1's nav checks are rule-based, with nothing tuned; if a nav threshold is ever tuned, its split is
   decided then. The two resource files of §7 E15 are members only if they are in the manifest.
2. **Station ID:** the first four characters of the file name, upper-cased: `ssss` of a short name
   `ssssDDDf.YYt`, `SSSS` of a long name `SSSSMRCCC_…`. MARKER NAME is not used (free text).
   Co-located monuments (`SSSS00CCC`, `SSSS01CCC`) share an ID, and so a half. A name that does not
   parse stops the split with an error; no file is assigned by guess.
3. **One station, one half:** every file of a station goes to the same half, whatever its day,
   cadence, version or encoding.
4. **Strata** (each file is counted in one value of each):
   - cadence class (§3, from the inferred Δ);
   - version family: `2.x`, `3.00-3.03`, `3.04-3.05`, `4.x`;
   - receiver maker: the first word of the receiver type in `REC # / TYPE / VERS`, upper-cased;
   - receiver type: the whole type, upper-cased, runs of spaces as one (`TRIMBLE NETR9`,
     `JAVAD TRE_3 DELTA`), so receiver generations are balanced, not only makers;
   - constellation set: the systems with at least one observation, as sorted letters (`G`, `GR`,
     `CEGR`, …).
5. **Assignment, deterministic:** stations are taken in ascending order of
   sha256(`"qc-split/1:" + ID`). Each goes to the half that, after adding its files, gives the smaller
   sum over every value of every stratum of \|files in calibration − files in held-out\|, plus
   \|total calibration − total held-out\|. A tie goes by the parity of the hash's last byte (even:
   calibration). Balancing is by marginal counts (each stratum on its own), since the joint cells are
   too sparse.
6. **Published coverage:** `qc_split.json` holds the rule version and salt, each station's half, each
   file's half, and per stratum value the files and stations in each half; values present in one half
   only are listed (a single-station value cannot be in both).
7. **Discipline:** calibration code reads only calibration files (a test refuses a held-out path);
   acceptance numbers are computed on the held-out half only after the thresholds are frozen; files
   added after the freeze join neither half and serve as fresh validation sets (retuning after a
   held-out evaluation needs them, PLAN §5.9).

---

## 9. The user's sign-off (2026-11-06)

- **Signed off:** the gates of §7 (Q1's, PLAN §5.9), as written. **Accepted**, as written, the
  proposals:
  - **[P1]** non-standard systems in RINEX 2 read with the RINEX 3 band meaning, `degraded`;
  - **[P2]** G_arc = max(300 s, 10·Δ);
  - **[P3]** flag 1 (power failure) also ends availability arcs;
  - **[P4]** default elevation mask 10° (Q2; configurable);
  - **[P5]** the met range and jump limits of §6. They have no external source: plausibility limits
    proposed here;
  - **[P6]** "refused" includes the validator's data-damage findings, as rinexconv refuses them by
    default (PLAN §1 clause 9), not only the reader's `CorruptError`. D1 as answered speaks of "a file
    the reader refuses"; the reader reads past some damage (text beyond the last field), so without
    [P6] such a file would get metrics by default. Q0b moves the rule set into rinexcore;
  - **[P7]** the unofficial RINEX 2.20 `OBS SCALE FACTOR` is applied by the adapter, as rinexconv
    honours it;
  - **[P8]** in RINEX 2, LLI bit 1 on a phase other than GPS L1/L2 is read as half-cycle.
- **D6, answered: fetch once, pinned.** `nav.coverage`, `nav.iod`, `nav.times`, `nav.ranges`,
  healthy-nav completeness (Q2) and SISRE (Q4) must cite IS-GPS-200, the Galileo OS SIS ICD, the BDS
  ICDs, the GLONASS ICD, IS-QZSS and the NavIC ICD; none is in `specs/`. In Q0b each is fetched once
  from its operator, with URL, version, date and sha256 recorded as for D2, into a new gitignored
  folder (`specs/` stays read-only), and its text extracted with page markers as `specs/text/` is.

## 10. References

RINEX 2.10-4.02 (`specs/`); docs/PHASE_ALIGNMENT.md; docs/SPEC_TABLES.md; Estey & Meertens 1999
(teqc); Vaclavovic & Dousa 2016 (Anubis); Blewitt 1990 (TurboEdit); Pi et al. 1997 (ROTI);
squidy `reference/squidy/math.md` (multipath arc rule, l.276-277). ICDs: §9 D6.
