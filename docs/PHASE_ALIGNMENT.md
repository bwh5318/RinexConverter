# RINEX phase-alignment tables, 3.01 to 4.02

Research for `--align-phases` (review round 32, 2026-11-02). The user chose "old versions only":
`--align-phases` applies the 3.02 (A19) and 3.03-3.05 (A23) values below and refuses every code for
which the target's table gives no number, and 4.x is not supported (docs/DECISIONS.md, "the user's
answers, implemented"). The converter's table is `rinexcore/spec/phaseshift.py`, the independent
checker's `tests/independent/phase_shift_tables.json`.

**Page citations.** "p. N" is the PDF page, which is the same as the `===== page N =====` marker in `specs/text/`. The printed page number is in [brackets].

**PDF check.** The only PDF readers installed (pypdf, pypdfium2) come from the `pypi` channel, which CLAUDE.md rule 1 forbids. I used a stdlib-only reader instead (zlib plus a content-stream parser with ToUnicode; a throw-away script, not kept). For every table below, the codes and values in the PDF match the `specs/text` extraction exactly (identical token multisets for 3.02, 3.03, 3.03 Update 1, 3.04, 3.05, 4.00, 4.01 and 4.02). The disputed cells in §4 were also checked by their x/y position in the PDF.

## 1. Tables, sign convention, and where alignment is required

| Ver | Table (pages) | Section requiring alignment | Sign convention |
|---|---|---|---|
| 3.00 | none | p.7: phase shifts between channels "are not corrected" | — |
| 3.01 | **none** | §9.1 p.24–25 [21–22]; §1 p.6 | p.25: "φRINEX = φoriginal + Δφ; φoriginal: Uncorrected, i.e. as sent by the satellite; Δφ: Phase correction to align the phase to other phases of the same frequency but different channel / modulation band" |
| 3.02 | **A19** p.80–82 [A34–A36] (the revision history calls it "Table 19") | §9.1 p.41–42 [36–37]; §5.1 p.20 | p.42: "φRINEX = φ original + ∆φ; φ original: Uncorrected or corrected, i.e. as issued by the GNSS receiver or in a standardized data stream such as RTCM-MSM; ∆φ: Phase correction to align the phase to other phases of the same frequency but different channel / modulation band" |
| 3.03, 3.03 U1 | A23 p.92–94 [A43–A45], notes p.95 (the two are identical) | §9.1 p.43–44 [38–39] | p.44, Table 25: same wording as 3.02 |
| 3.04 | A23 p.97–100 [A43–A46] | §9.1 p.45–47 [40–42] | p.47, Table 25: same |
| 3.05 | A23 p.88–91 [87–90] | §5.2.12 p.26–28 [25–27] | p.27, Table 9: same |
| 4.00 | **A39** p.111–114 [110–113], §8.6 | §5.2.12 p.25 [24]; p.18 | **none, and no values** |
| 4.01 | **A39** p.115–118 [114–117] | §5.2.12 p.26 | none |
| 4.02 | **A45** p.128–131 [127–130] | §5.2.12 p.27 | none |

The 3.02–3.05 table headers read: "Phase Correction applied to each observed phase to obtain aligned phase. (φRINEX = φ original (as issued by the SV) + Δφ)".

The alignment requirement, quoted:
- 3.03 and 3.04 §9.1, and 3.05 §5.2.12: "All phase observations must be aligned to the designated constellation and frequency reference signal as specified in Appendix [Table] A23, either directly by the receiver or by a correction program or the RINEX conversion program, prior to RINEX file generation. Additionally, all data must be aligned with the appropriate reference signal indicated in Appendix [Table] A23 even when the receiver or reporting device is not tracking and/or providing data from that reference signal e.g. Galileo L5X phase data must be aligned to L5I."
- 3.02 says the same in less detail (p.41): "All phase observations must be aligned in RINEX 3.01 and later files and the new SYS / PHASE SHIFT header is mandatory. … If the phase alignment is not known then the observation data should not be published in a RINEX 3.0x file."

## 2. Per-code table

**Legend:**
- **R** = "None (Reference Signal)"
- **0** = "None"
- **+¼ / −¼ / +½ / −½** = Δφ in cycles
- **→X** = "Must be aligned to X" (no value given)
- **Rst** = "Restricted (See Note 3)"
- **NA** = "N/A"
- **—** = no row in that version

3.01 has no table, so it has no column. In the PDFs the minus sign is a hyphen glyph.

**GPS.** Pages: 3.02 p.80; 3.03 p.92; 3.04 p.97; 3.05 p.88; 4.00 p.111; 4.01 p.115; 4.02 p.128.

| Band | Code | 3.02 | 3.03 | 3.04 | 3.05 | 4.00 | 4.01 | 4.02 |
|---|---|---|---|---|---|---|---|---|
| L1 | L1C | R | R | R | R | R | R | R |
| L1 | L1S, L1L, L1X, L1P, L1W, L1N | +¼ | +¼ | +¼ | +¼ | →L1C | →L1C | →L1C |
| L1 | L1R | — | — | — | — | — | Rst | Rst |
| L2 | L2C | Block II/IIA/IIR: 0; IIR-M/IIF/III: −¼ (Note 2) | same | same | same | II/IIA/IIR: 0; IIR-M/IIF/III: →L2P | same | same |
| L2 | L2D, L2W, L2N | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| L2 | L2S, L2L, L2X | −¼ | −¼ | −¼ | −¼ | →L2P | →L2P | →L2P |
| L2 | L2P | R | R | R | R | R | R | R |
| L2 | L2R | — | — | — | — | — | Rst, printed "L1R" (§4.1) | same |
| L5 | L5I | R | R | R | R | R | R | R |
| L5 | L5Q | −¼ | −¼ | −¼ | −¼ | →L5I | →L5I | →L5I |
| L5 | L5X | →L5I | →L5I | →L5I | →L5I | →L5I | →L5I | →L5I |

**GLONASS.** Pages: 3.02 p.80–81; 3.03 p.92–93; 3.04 p.97–98; 3.05 p.88–89; 4.00 p.111–112; 4.01 p.115–116; 4.02 p.128–129.

| Band | Code | 3.02 | 3.03 | 3.04 | 3.05 | 4.00 | 4.01 | 4.02 |
|---|---|---|---|---|---|---|---|---|
| G1 | L1C | R | R | R | R | R | R | R |
| G1 | L1P | +¼ | +¼ | +¼ | +¼ | →L1C | →L1C | →L1C |
| G1a | L4A / L4B / L4X | — | — | R / 0 / 0 | R / 0 / 0 | same | same | same |
| G2 | L2C | R | R | R | R | R | R | R |
| G2 | L2P | +¼ | +¼ | +¼ | +¼ | →L2C | →L2C | →L2C |
| G2a | L6A / L6B / L6X | — | — | R / 0 / 0 | R / 0 / 0 | same | same | same |
| G3 | L3I | R | R | R | R | R | R | R |
| G3 | **L3Q** | **−¼** | **−¼** | **+¼** | **→L3I** | →L3I | →L3I | →L3I |
| G3 | L3X | →L3I | →L3I | →L3I | →L3I | →L3I | →L3I | →L3I |

**Galileo.** Pages: 3.02 p.81; 3.03 p.93; 3.04 p.98; 3.05 p.89; 4.00 p.112; 4.01 p.116; 4.02 p.129.

| Band | Code | 3.02–3.05 | 4.00–4.02 |
|---|---|---|---|
| E1 | L1B | R | R |
| E1 | L1C | +½ | →L1B |
| E1 | L1X | →L1B | →L1B |
| E5a / E5b / E5 | L5I / L7I / L8I | R | R |
| E5a / E5b / E5 | L5Q / L7Q / L8Q | −¼ | →L5I / →L7I / →L8I |
| E5a / E5b / E5 | L5X / L7X / L8X | →L5I / →L7I / →L8I | same |
| E6 | L6B | R | R |
| E6 | L6C | −½ | →L6B |
| E6 | L6X | →L6B | →L6B |

**QZSS.** Pages: 3.02 p.81–82; 3.03 p.93–94; 3.04 p.98–99; 3.05 p.89–90; 4.00 p.112–113; 4.01 p.116–117; 4.02 p.129–130.

| Band | Code | 3.02 | 3.03 | 3.04 | 3.05 | 4.00 | 4.01 | 4.02 |
|---|---|---|---|---|---|---|---|---|
| L1 | L1C | R | R | R | R | R | R | R |
| L1 | L1E (C/B) | — | — | — | — | R (Note 6) | R | R |
| L1 | **L1S** | **0** | **0** | **+¼** (Block II; Block I 0, Note 5) | +¼ (Note 5) | →L1C/L1E | →L1C/L1E | →L1C/L1E |
| L1 | L1L, L1X | +¼ | +¼ | +¼ | +¼ | →L1C/L1E | →L1C/L1E | →L1C/L1E |
| L1 | L1Z | NA ("L1-SAIF") | NA ("L1-SAIF") | NA ("L1S") | NA | NA | NA | NA |
| L1 | L1B (L1Sb) | — | — | — | — | NA | NA | NA |
| L2 | L2S | R | R | R | R | R | R | R |
| L2 | L2L, L2X | 0 | 0 | 0 | 0 | 0 | 0 | **→L2S** |
| L5 | L5I / L5Q / L5X | R / −¼ / →L5I | same | same | same | R / →L5I / →L5I | same | same |
| L5S | L5D / L5P / L5Z | — | — | R / −¼ / "None must be aligned to L5D" | same | R / →L5D / →L5D | same | same |
| L6 (named "LEX(6)" in 3.02–3.03) | L6S / L6L / L6X | R / 0 / 0 | R / 0 / 0 | R / 0 / 0 | same | same | same | same |
| L6 | L6E, L6Z | — | — | 0 | 0 | 0 | 0 | 0 |

**BDS.** Pages: 3.02 p.82; 3.03 p.94; 3.04 p.99; 3.05 p.90; 4.00 p.113; 4.01 p.117; 4.02 p.130.

| Band | Code | 3.02 | 3.03 | 3.04 | 3.05 | 4.00–4.02 |
|---|---|---|---|---|---|---|
| B1 (B1I) | ref | L1I R | L2I R (Note 4) | L2I R (labelled "B1-2") | L2I R | L2I R |
| B1 (B1I) | Q | L1Q −¼ | L2Q −¼ | L2Q −¼ | **L2Q →L2I** | L2Q →L2I |
| B1 (B1I) | X | L1X "→L2I" (sic, §4.2) | L2X →L2I | L2X →L2I | L2X →L2I | L2X →L2I |
| B1C | L1D / L1P / L1X | — | — | R / +¼ (preliminary) / →L1D (labelled "B1") | R / →L1D / →L1D | same as 3.05 |
| B1A | L1S / L1L / L1Z | — | — | — | R / →L1S / →L1S | same |
| B2a | L5D / L5P / L5X | — | — | R / +¼ (preliminary) / →L5D | R / →L5D / →L5D | same |
| B2 (BDS-2) | L7I / L7Q / L7X | R / −¼ / →L7I | same | same (labelled "B2b (BDS-2)") | R / **−¼** / →L7I | R / →L7I / →L7I |
| B2b (BDS-3) | L7D / L7P / L7Z | — | — | R / +¼ (preliminary) / →L7D | R / →L7D / →L7D | same |
| B2a+B2b | L8D / L8P / L8X | — | — | R / +¼ (preliminary) / →L8D | R / →L8D / →L8D | same |
| B3 | L6I / L6Q / L6X | R / −¼ / →L6I | same | same | R / **→L6I** / →L6I | same |
| B3A | L6A | — | — | →L6I | — | — |
| B3A | L6D / L6P / L6Z | — | — | — | R / →L6D / →L6D | same |

**NavIC/IRNSS.** Pages: 3.03 p.94; 3.04 p.99–100; 3.05 p.91; 4.00 p.114; 4.01 p.118; 4.02 p.131. It is not in 3.02.
- L5: L5A R; L5B Rst; L5C 0; L5X →L5A. Band S: L9A R; L9B Rst; L9C 0; L9X →L9A. The same in 3.03–4.02.
- L1 (4.01 and 4.02 only): L1D R; L1P →L1D; L1X →L1D.

**SBAS** is in **no** table, in any version, although SBAS L1C and L5I/Q/X observation codes exist (for example 3.05 p.32). Also absent from every table: GPS L1Y, L1M, L2Y, L2M (3.05 p.30) and Galileo L1A, L1Z, L6A, L6Z (3.05 p.32).

**Notes, 3.03–3.05.**
1. "The GPS L2 phase shift values ignore FlexPower when the phases of the L2W and L2C can be changed on the satellite." 3.02 writes "L2E".
2. "The phase of the L2 C/A signal is dependent on the GPS satellite generation."
3. Restricted-service signals: no public information.
4. "Both C1x and C2x (RINEX 3.01 definition) have been used to identify the B1 frequency signals in RINEX 3.02 files. If C2x coding is read in a RINEX 3.02 file treat it as equivalent to C1x."
5. (3.04+) QZSS: "Block I corrections: L1S none, L1L +¼."

From 4.00, Note 1 adds: "The phases L2C shall be aligned to L2P when FlexPower is off, the phase shift shall remain applied even if FlexPower is enabled." Note 6 (4.00+) reads: "Either L1C or L1E is broadcast from each QZSS Block IIA or later."

**BeiDou B1I codes by version.** The band is coded 2 in 3.01 (Compass "E2" C2I, p.11), 1 in 3.02 (C1I, p.20), and 2 again from 3.03 (C2I: 3.03 p.24, 3.04 p.26, 3.05 p.34).

## 3. What 3.01/3.02 and 4.x say about the record

| Ver | Spec text (quoted) | Page |
|---|---|---|
| 3.01 | No table and no reference signal: "Either one or the other group of phase observations have to be shifted … The applied corrections are to be reported in a new SYS / PHASE SHIFT header record to allow the reconstruction of the original values, if needed. The uncorrected group of observations is not reported in the SYS / PHASE SHIFT records." | §9.1 p.24 [21] |
| 3.01 | "If the file does not contain any observation pairs affected by phase shifts or if (exceptionally) the applied corrections are not known, the observation code field and the rest of the SYS / PHASE SHIFT header record field of the respective satellite system(s) are left blank." The only number is the example `G L2S -0.25000  03 G15 G16 G17   SYS / PHASE SHIFTS` (plural label; Table A1 p.32 [A4]). | p.25 [22] |
| 3.02 | Already has Table A19, "should not be published", and all four 3.03 bullets: zeros = aligned at the source, nothing applied; code with blanks = only reference signals; satellite list; fully blank = unknown, "for exceptional situations". | §9.1 p.41–42 [36–37] |
| 4.00–4.02 | "By convention, phase observations in RINEX files must always be aligned to a predefined reference signal. Table A39 [A45 in 4.02] specifies the reference signal for each frequency and constellation, and which signals shall align to the reference. … There is no ambition to align phases across constellations. The SYS / PHASE SHIFT header lines are now optional in the RINEX observation files and strongly deprecated. They are retained in the RINEX observation file header definition (Table A2) for compatibility with previous RINEX versions but they should be ignored by RINEX decoders and encoders." | §5.2.12: 4.00 p.25, 4.01 p.26, 4.02 p.27. Table A2: p.60 / p.64 / p.66 |
| 4.00 | The 4.x tables have **no Δφ values**. History entry of 10 Jun 2021: "Updated Table A39 to remove specific correction values and instead indicate the reference signal to be aligned to per frequency band. For RINEX creators how they align depends on the internal tracking characteristics of each receiver design." | p.118 [117] |

**Correction to PLAN §3.3:** 3.02 does not belong with 3.01. Only 3.01 has the ambiguous blank record.

**Name clash:** "Table A39" in 4.02 is the NavIC ION NeQuick-N table, and "Table A23" in 4.x is a BDS navigation table.

## 4. Inconsistencies and likely typos (all confirmed in the PDFs)

| # | Where | Finding | Evidence |
|---|---|---|---|
| 1 | 4.01 and 4.02, GPS L2 band | The row "M (RMP) **L1R** Restricted" should read **L2R** (typo). | The 4.01 history (Aug 2022, p.9) says "L1R and L2R" were added. The observation tables define L2R (4.01 p.29, 4.02 p.30). PDF: 4.01 p.115 y=224; 4.02 p.128 y=226 |
| 2 | 3.02, BDS | "L1X Must be aligned to **L2I**" should read L1I. | B1 is band 1 in 3.02 (p.82) |
| 3 | GLONASS L3Q | −¼ (3.02, 3.03), **+¼** (3.04), →L3I (3.05+). | The 3.04 history mentions it only generically (25-Apr-2018, p.12). The 3.05 history gives the reason "since the alignment direction is not known" (13-Nov-2020, p.10). PDF glyphs: "- ¼" on 3.03 p.93, "+ ¼" on 3.04 p.98 |
| 4 | BDS L2Q, L6Q | −¼ through 3.04, then "→L2I"/"→L6I" in 3.05. The BDS-2 L7Q keeps −¼. | The change is **not** in the 3.05 history, which lists only L3Q, B1C/B2a and B2b/B2a+B2b. PDF 3.05 p.90 |
| 5 | BDS-3 L1P, L5P, L7P, L8P | "+¼ (preliminary)" in 3.04, withdrawn in 3.05. | "¼ cycle alignment direction is implementation dependent" (3.05 p.10) |
| 6 | QZSS L1S | 0 in 3.02–3.03, +¼ in 3.04–3.05. The value depends on the satellite block (Note 5), and so does GPS L2C. RINEX carries no block information. | 3.03 p.93; 3.04 p.98 |
| 7 | QZSS L5Z | Reads "None must be aligned to L5D" (ambiguous). QZSS L5D and BDS L8D read "None Reference Signal" without parentheses. | 3.04 p.99; 3.05 p.89–90 |
| 8 | φoriginal | Described three ways: "as sent by the satellite" (3.01), "as issued by the GNSS receiver or … RTCM-MSM" (3.02+ text), "as issued by the SV" (3.02+ table headers). | See §1 |
| 9 | BDS B3A and band labels | 3.04 `L6A` (→L6I) becomes `L6D/L6P/L6Z` in 3.05. The 3.05 history says B1A and B3A were "added", but 3.04 already listed B3A. Band labels change from 3.04 "B1-2", "B1", "B2b (BDS-2)" to 3.05 "B1", "B1C", "B2 (BDS-2)". | 3.04 p.99; 3.05 p.7, p.90 |
| 10 | Minor | 3.02 Note 1 writes "L2E" where later versions write "L2W". 4.02 still lists QZSS L1B (L1Sb) after dropping it from Table 14 (SPEC_TABLES #16). | 3.02 p.82; 4.02 p.129 |

## 5. Inferences for `--align-phases` (not spec statements)

- **Numbers usable for a 3.05 target:**
  - G: L1S, L1L, L1X, L1P, L1W, L1N +¼; L2S, L2L, L2X −¼; L2C −¼ (IIR-M/IIF/III only); L5Q −¼.
  - R: L1P, L2P +¼.
  - E: L1C +½; L5Q, L7Q, L8Q −¼; L6C −½.
  - J: L1S +¼ (Block II), L1L, L1X +¼; L5Q, L5P −¼.
  - C: L7Q −¼ only.
  - "→X" rows have no number.
- **Other 3.x targets differ:** 3.03 has L3Q −¼, C L2Q and L6Q −¼, J L1S 0. 3.04 has L3Q +¼ and the preliminary BDS-3 values. 3.01 has nothing to apply.
- **4.x has no numbers to apply.** Applying 3.05 A23 values to a 4.x target would be a policy choice, so it is a question for the user (CLAUDE.md, "stop and ask").
- **±½ are equal modulo one cycle**, but they are not byte-identical values.
