# RINEX Convert & Analysis — Plan

Two tools that share one RINEX core:

1. **rinexconv**: converts RINEX observation, navigation and meteorological files between
   the common versions (2.x, 3.x and 4.x), correctly for every valid input.
2. **rinexqc**: measures the quality of a RINEX file as completely as the data allows,
   and writes a JSON result, an offline HTML report and a short text summary.

The guide for the Claude that builds this is [CLAUDE.md](CLAUDE.md). This file is the plan.
Revision 3 (2026-10-30) takes in three review rounds by Sonnet and Codex Astra; scores
and changes are in `docs/REVIEW_LOG.md`. Every factual correction from those reviews was
checked against the spec text in `specs/text/` before it went in.

---

## 0. Hard constraints

| Constraint | Consequence |
|---|---|
| **Python plus the packages Anaconda ships, nothing else.** No `pip install`, no `conda install`. | Any package that `conda list` shows with channel `pypi` is off limits, even if installed. `unlzw3`, `georinex`, `hatanaka`, `hypothesis`, `gnsspy` and `pypdf` are all out. We write our own LZW (`.Z`) and Hatanaka (CRX) codecs. |
| The finished tools run with no outside programs. | CRX2RNX, gfzrnx, RTKLIB, teqc and Anubis are allowed **only as optional dev-time oracles** in tests. Their results are also **archived**, as digests and hashes (§1.5c), so a laptop without them keeps the coverage. Shipped code never calls `subprocess`. |
| Credentials are never committed, printed or sent anywhere but the Earthdata login host. | See CLAUDE.md and `docs/CDDIS.md`. |

**Which module may import what.** This is enforced by an AST import-purity test (the
pattern in `reference/nav2sp3`).

| Module | Allowed imports |
|---|---|
| `rinexcore/` except `cddis.py`, and all of `rinexconv/` | Standard library only |
| `rinexcore/cddis.py`, `tools/` | Standard library + `requests` |
| `rinexqc/` | The above + numpy, scipy, matplotlib, plotly, jinja2; numba is optional, always with a pure-Python fallback |

Anaconda 2024.10, the desktop's version, ships numpy 1.26, scipy 1.13, pandas 2.2,
matplotlib 3.9, plotly 5.24, bokeh 3.6, numba 0.60, pyerfa, astropy, requests, jinja2,
beautifulsoup4, lxml and pytest 7.4. The laptop's `conda list` is the source of truth,
recorded in `docs/ENVIRONMENT.md` at setup.

---

## 1. What "100%" means

"Converts correctly every time" has to be checkable, and the checks must not be able to
pass a wrong converter. The converter is judged against this contract, and every clause has
a test.

1. **Every conversion decision ends in exactly one of four named outcomes**, and the
   report and exit code say which:
   - **`converted`**: complete output.
   - **`converted-with-removal`**: the user chose `--drop-unresolvable`, and a whole
     system was removed, with a loss entry, because a value the target makes mandatory
     couldn't be resolved.
   - **`refused-missing-information`**: a clause-8 stop. The target needs a value that
     no source supplied, such as GLONASS frequency channels for 3.02+, and the message
     names it. The input was valid; it just lacked that information.
   - **`refused-corrupt`**: data-level corruption that the validator can point to (file,
     line, column, rule).

   The two refusals are `RinexError`s. No other exception ever escapes, and fuzz tests
   check this. **Every valid input, given the information its target needs, ends in
   `converted`.** The corpus harness always supplies the same-day merged nav file, from
   the corpus or downloaded, as the companion file. So any refusal on the corpus is a bug.

   **Invocation and I/O failures are a separate class**, outside the four outcomes: bad
   arguments, a missing input, a permission error, a full disk. They get their own exit
   codes and messages, and **must never be reported as `refused-corrupt`**. A partial
   output is deleted, never left looking complete.
2. **Output is valid** for the target version. Our validator checks it, and so does every
   available oracle (live, or from archived results).
3. **Zero unexplained differences, both ways.** Every conversion writes a machine-readable
   *conversion report*. Its entries and the measured differences must match **exactly**:
   diff ⊆ report **and** report ⊆ diff, with equal counts. A loss the report claims must
   actually happen, and every difference must be claimed.
4. **Losses are pre-authorised, not self-declared.** `tests/expectations/allowed_losses.json`
   is written by hand from the specs, with page citations, before the rules that use it.
   It is keyed by **(source version, target version, file type, loss category)**, for
   example `("3.05", "2.11", "obs", "system-not-representable:C")`, **not** by rule ID, so
   it doesn't depend on how the rules are written. A report entry outside its cell's
   categories fails the test, even if the diff matches.
5. **Independent checks, so a shared mistake can't hide.**
   - (a) **A naive token comparator.** It uses no model and no converter tables.
     - **Obs:** it tokenises input and output into (epoch, satellite, **signal**, value
       text, LLI, SSI) tuples, using the effective obs-type list at each epoch, so a
       swap between, say, C1C and C2W is caught.
     - **Signals across versions** are matched through its own small, hand-written
       expectation table (`tests/independent/code_expectations.json`, from the spec),
       which is kept separate from `rinexcore/spec/`.
     - **Nav, v1:** compared as **positional numeric multisets per record** (satellite,
       time of clock, message type → the multiset of numeric values). That needs no
       second copy of every nav layout. Fields that a version pair adds or drops (for
       example GLONASS 3.05's fifth line) are accounted for through the loss report.
       Field-by-name comparison is added only for v2 ↔ v3 GPS/GLONASS, where the layouts
       are small.
     - **Met:** compared as (epoch, met type, value).

     It checks that nothing moved, swapped, duplicated or vanished beyond the reported
     losses.
   - (b) **Hand-written expected outputs** for small fixtures, written from the spec, not
     produced by our writer.
   - (c) **Oracle results, archived** in `tests/oracle/ATTESTATION.json`: the tool, its
     version and sha256, and the command. Our output will never be byte-equal to gfzrnx's,
     so the archive stores **canonical digests** of each oracle output: per-system hashes
     of the token multisets, plus counts per system, signal and epoch. A laptop without
     the oracle can still compare against them. **CRX2RNX is the exception:** our decoder
     must match it byte for byte, so the archive stores the **sha256 of its decompressed
     output** per corpus file, which is checked directly. Full oracle outputs are kept only
     for the small hand-made fixtures.
   - (d) **Spec examples:** every example record printed in the specs. Known spec typos
     are annotated in `tests/fixtures/spec_errata.md`, rather than "fixed" silently.
6. **Lossless where the target can hold the data.** A → B → A gives back an equal canonical
   model and passes the token comparator. Here A must be a **write** version; files in a
   read-only version (2.00, 2.01, 2.12) are tested as A → B → B′ instead.
7. **Idempotent.** `write(parse(write(parse(x))))` equals `write(parse(x))`, byte for byte,
   for every file.
   **Same-version identity** applies only to write versions and **only to files that needed
   no clause-9 repair**. It is gated on *normalised* equality: line endings, trailing blanks
   where the spec allows them, the `D`/`E` letter, and missing values written as `0.0`
   versus blank (both mean "missing"; see §3.3).
   For files that **did** need repairs, the output must equal the input with exactly the
   expected repairs applied. Those expected repairs are computed independently, by the
   naive comparator's header checker. The raw byte-identical rate is a tracked metric,
   reported per receiver and program.
8. **Explicit where the target needs data the source lacks.** Each value is resolved in
   this order: (1) explicit user override; (2) a companion file the user passes (nav file,
   site log); (3) a built-in **dated** table with its source cited; (4) the spec's own
   "unknown" convention. The report records which source each value came from. **A
   physical value is never invented.** For example, there is no default GLONASS frequency
   channel and no default code-phase bias. If a mandatory value can't be resolved, the
   conversion stops and names the missing value, unless the user chose
   `--drop-unresolvable`, which drops the affected system with a loss entry.
9. **Input repairs are explicit.** Header-only inconsistencies are repaired by default and
   reported: wrong counts, `TIME OF LAST OBS`, `INTERVAL`, `# OF SATELLITES`, `PRN / # OF
   OBS`. Real files get these wrong constantly. Data-level damage is an error by default;
   `--lenient` repairs what it can and reports each repair. `--strict` refuses anything off
   spec, for people who want a linter.
10. **Oracle disagreements** count as resolved only if they're shown, with a spec citation,
    to be an oracle bug or an allowed convention difference, and the user signs off in
    `docs/DECISIONS.md`. A documented disagreement is not, by itself, a pass.

`docs/CONVERSION_MATRIX.md` is generated from `allowed_losses.json` and the rule tables. It
shows every cell of version × version × file type: identity, lossless,
lossless-with-assumptions or lossy, with the rule list.

---

## 2. Scope

### Versions

| Role | Versions |
|---|---|
| Read | 2.00, 2.01, 2.10, 2.11, 2.12 (non-standard, if met), 3.00–3.05, 4.00–4.02 |
| Write | 2.10, 2.11, 3.00–3.05, 4.00–4.02 |

**Why 2.01:** CDDIS still publishes the merged GLONASS nav file `brdcDDD0.YYg` as RINEX
**2.01** (verified 2026-10-30). These checks were made against
<https://files.igs.org/pub/data/format/> on 2026-10-30: **4.02 is the newest version**
(dated 1 Sep 2025), and its text is in `specs/text/`.

Every rule is gated by **target minor version**, not by major version. Systems, signals,
message types and header records each come with a "valid from/to version" column in the
spec tables. Examples: BeiDou B1I is `C1I` in 3.02 and `C2I` from 3.03 on. GLONASS nav
records grow from 4 to 5 lines in 3.05. NavIC L1 nav and GLONASS L1OC/L3OC nav appear in
4.02. The 4.02 optional picosecond epoch extension exists only in 4.02.

### File types and wrappers

- **Observation (O)**, **Navigation (N)** and **Meteorological (M)**. Navigation covers
  every system, RINEX 2's per-system files (`n` GPS, `g` GLONASS, `h` SBAS), and the
  non-standard `l` and `p` files where they turn up. A RINEX 2 reader also accepts C/J/I
  satellite ids in 2.11 files, as a flagged extension.
- Out of scope for now: clock RINEX, ANTEX, IONEX, SINEX. They are different formats.
- Wrappers, read and write: plain, `.gz` and `.Z` (Unix compress, LZW), for every file
  type. **Hatanaka (observation files only):** CRINEX 1.0 (RINEX 2), 3.0 (RINEX
  3.x–4.01) and **3.1 (RINEX 4.02+, with the picosecond record)**, plain or combined with
  gz/Z (`.crx.gz`, `.YYd.Z`).
- File names: RINEX 2 short names, daily `ssssdddf.yyt` and high-rate `ssssdddhmm.yyt`,
  converted to and from RINEX 3/4 long names
  (`SSSSMRCCC_S_YYYYDDDHHMM_PPU_FFU_TT.FMT[.cmp]`). Going short → long needs the 9-character
  ID: user override first, then the header, then a dated IGS station table. The report
  records which.

### Interfaces

- CLI: `python -m rinexconv IN [IN...] --to 3.05 [--out DIR] [--crx] [--gz] [--lenient |
  --strict] [--nav FILE] [--glo-fcn FILE] [--overrides FILE] [--drop-unresolvable]
  [--assume-phase-aligned | --align-phases] [--dedupe] [--report FILE] [--eol lf|crlf]`.
  Batch mode over a directory, with one process per file (stdlib `multiprocessing`).
- `python -m rinexqc IN [--nav FILE | --fetch-nav] [--sp3 FILE | --fetch-sp3] [--html]
  [--json]`, plus `python -m rinexqc nav FILE` and `python -m rinexqc met FILE`.
- A library API. A small tkinter GUI (tkinter is stdlib) is optional, after the CLI is solid.

---

## 3. Architecture

One repository, three packages at the root, so `python -m <pkg>` works with no install
step. Converter and QC share one parser, so a parsing bug is fixed once.

```
RINEXConvert_Analysis/
  CLAUDE.md  PLAN.md  README.md
  rinexcore/      spec tables, codecs, model, readers, writers, validator, diff, names, cddis
  rinexconv/      conversion rules, engine, report, CLI
  rinexqc/        orbits, metrics, SPP, report, CLI
  specs/          official spec PDFs, text extractions, Hatanaka source, extracted tables
  tools/          build_corpus.py, build_tables.py, oracle wrappers
  tests/          unit/ corpus/ oracle/ fuzz/ fixtures/ expectations/
  docs/           CDDIS.md CONVERSION_MATRIX.md QC_METRICS.md ENVIRONMENT.md DECISIONS.md
  reference/      read-only copies of desktop code (gitignored: it contains an e-mail address)
  data/           gitignored: corpus/, cache/, out/
```

### 3.1 Spec tables (`rinexcore/spec/`)

Everything that varies by version lives in data, not code:

- header labels, with mandatory, optional or conditional status and column layout;
- observation codes per system;
- nav record layouts per system and message type, with each field's format;
- met observation types;
- time systems;
- the from/to versions of each item.

The tables are written by hand from `specs/text/`, with a spec page on every row. They are
the single source of truth for the converter, but **not** for the independent checks of
§1.5, which must not read them.

### 3.2 Byte-level I/O and codecs (`rinexcore/io/`)

- **Bytes, always.** Never use text mode, which on Windows turns `\n` into `\r\n`.
  Decode as latin-1, which maps bytes to characters one to one, so any byte survives.
  Record the input's line-ending style. Output uses LF unless `--eol crlf` is given.
- gzip: stdlib. Concatenated members must work.
- `.Z`: pure-Python LZW decoder and encoder. Codes are 9 to maxbits wide, in groups of
  eight; when the width changes, the rest of the group is padding. The decoder already
  exists in `tools/build_corpus.py:unlzw`, and it matches `unlzw3` byte for byte on a
  2015 CDDIS file.
- **Hatanaka:** a pure-Python CRINEX 1.0/3.0/3.1 decoder and encoder, ported from
  `specs/hatanaka/src/.../crx2rnx.c` and `rnx2crx.c`, citing Hatanaka (2008) as the GSI
  licence requires. The grammar is specified in `docs/HATANAKA.md` **before** coding:
  - **Epoch lines** are text-differenced. In the differences, a blank means "unchanged"
    and `&` means "becomes a blank". A leading `&` (CRINEX 1) or `>` (CRINEX 3)
    re-initialises the epoch.
  - **Numeric fields** are differenced to order N. `N&value` starts a new arc of order N;
    an **empty field means missing**.
  - **Flag fields** (LLI/SSI) are text-differenced.
  - Also covered: receiver-clock arcs, the CRINEX 3.1 picosecond record, satellite-list
    changes between epochs, event records (passed through verbatim), and CRINEX 3 escape
    lines starting with `&`.

  The decoder must match CRX2RNX byte for byte on the whole corpus. That equality is also
  archived, per §1.5c. The encoder must round-trip through our decoder and through CRX2RNX.

### 3.3 Canonical model (`rinexcore/model/`)

This is a version-neutral representation that **never stores a value as a float on the
write path**, and that keeps the raw bytes of each record for diagnostics:

- **Epoch time:** a calendar date, the seconds as an exact decimal digit string (up to
  picoseconds, for the 4.02 extension), and an explicit time system. GLONASS-only RINEX 2
  files stay in GLO/UTC time and are never shifted by leap seconds. Precision lost on the
  way to an older version (12 → 7 decimals) is a reported loss.
- **Observation value:** an exact decimal, held as an integer mantissa plus a decimal
  exponent, with an explicit *missing* state. In a plain file it is the F14.3 field, i.e.
  thousandths. A scale factor (`OBS SCALE FACTOR` / `SYS / SCALE FACTOR`) can make the true
  value finer than a thousandth, which 4.02 §5.2.11 explicitly permits. Exact decimals keep
  that. Rounding back to F14.3 when a scale factor is removed or converted is a reported
  loss, with the rounding rule stated. LLI and SSI are kept as characters, with blank and
  `0` distinct.
  - **A missing observation may be written as `0.0` or as blanks** (`rinex211.txt` around
    line 1288; `rinex305.txt` §6.7, around line 2328). Both mean *missing*, never a
    measured zero. The model stores the missing state plus the original form, for
    diagnostics only; writers emit blanks. QC must never count a `0.000` as an observation.
  - **Phase overflow:** a phase value beyond F14.3 is clipped into range by ±10⁹, with LLI
    bit 0 set (same §6.7). Readers recognise this, the converter carries it, and QC treats
    it as a slip.
- **Nav and header numeric parameter:** a decimal (sign, digit string, exponent) parsed from
  `D`/`E`/`d`/`e`. A mantissa is preserved where the target field has the digits. Where
  it doesn't, the loss is reported, as with v2 `DELTA-UTC` (D19.12) → v3 `TIME SYSTEM
  CORR` a0/a1 (D17.10/D16.9).
- **Header state is a timeline, not a block.** Event records (flags 2–5), especially
  flag 4 "header information follows", can change obs types, scale factors, antenna,
  marker and `WAVELENGTH FACT L1/2` mid-file. The model keeps the **effective metadata per
  epoch**, and the converter applies it epoch by epoch. Flag 6 cycle-slip records and
  flag 1 power-failure epochs are first-class.
- **Semantics, not just characters.**
  - RINEX 2 `WAVELENGTH FACT L1/2` and its effect on LLI bit 1 has no RINEX 3 equivalent:
    v3 LLI bit 1 means a half-cycle ambiguity. It gets an explicit rule with fixtures.
  - **Phase alignment is a convention that changes between versions**, so the converter
    tracks it explicitly.

    **What each version says** (from `specs/text/`):

    | Source | Convention | What its record means |
    |---|---|---|
    | v2 | None | No record: alignment **unknown** |
    | 3.00 | Inter-channel shifts "are not corrected" (`rinex300.txt` ~417), but a receiver may already deliver aligned phases | No record: **unknown** |
    | 3.01–3.02 | Phases must be aligned, by the receiver, a correction program or "the RINEX conversion program". `SYS / PHASE SHIFT` is mandatory and lists the Δφ applied, where φRINEX = φoriginal + Δφ, optionally per satellite (`rinex301.txt` ~1505–1540) | Values: **applied Δφ**. Blank: "none, or not known" (ambiguous) |
    | 3.03–3.05 | The same, with reference signals and shifts in **Table A23**. Data whose alignment isn't known "should not be published" (`rinex305.txt` §5.2.12, ~1396–1402) | Zeros: **already aligned at the source, nothing applied**. Code set, rest blank: **only reference signals present**. Values: **applied Δφ**. Fully blank: **unknown** (for exceptional use only) |
    | 4.00–4.02 | Phases must be aligned (Table A39 in 4.00, A45 in 4.02). The record is optional, strongly deprecated, and "should be ignored by RINEX decoders and encoders" (`rinex_4.00.txt` §5.2.12, ~1292) | **Aligned** by definition; ignore any record |

    **The model keeps two separate things**, per system and signal, with satellite scope:
    - the **alignment state**: aligned, unaligned or unknown;
    - the **corrections recorded as applied**: the Δφ values and the form of the record.

    A zero record and an applied-Δφ record both mean "aligned", but only the second says a
    correction was made. So "reverse the recorded shifts" never reconstructs a receiver's
    raw phase.

    **Rules:**
    1. **By default, phase values are never changed.** Only the metadata is mapped to the
       target's form.
       - To 3.03–3.05: aligned becomes the zero form, or the applied Δφ values carried
         over. Unknown becomes the fully blank form, with an assumption entry and a
         validator **warning** citing §5.2.12.
       - To 3.01–3.02: applied values are carried over; aligned-at-source and unknown both
         become blank, which is reported.
    2. **Converting to 4.x needs aligned phases.** If the source state is unknown (v2,
       3.00, or a blank 3.0x record), the result is a clause-8
       `refused-missing-information`, unless the user either:
       - asserts `--assume-phase-aligned` (an override, reported); or
       - chooses `--align-phases`, which asserts the source is *unaligned* and applies the
         reference shifts of the target's table (A23 for 3.03+, A39/A45 for 4.x), each
         one reported.

       The corpus harness passes `--assume-phase-aligned` for these cells. A separate test
       checks the refusal without it.
    3. **`--align-phases` toward 3.00's unaligned convention** subtracts only Δφ values a
       record says *were applied*. Zero-form ("aligned at source") data can't be un-aligned:
       they stay as they are, and that's reported. Without the flag, the data stay unchanged
       and the lost metadata is reported.
    4. **Never apply a shift twice.** Shifts recorded as applied are never applied again,
       and `--align-phases` refuses a source whose record already shows them.
    5. **To RINEX 2:** `SYS / PHASE SHIFT` has no v2 form. That is the named loss category
       `phase-shift-record-not-representable`.
    6. **From 4.x to 3.x:** the source is aligned by definition, so write the zero form for
       3.03+, or blank for 3.01–3.02.

    **Fixtures:** every source form × every target, including a receiver-aligned zero
    record, a missing record (3.00 and v2), applied values with a satellite list, the
    code-only form, the fully blank form, and a v4 source. Each `--align-phases` path also
    gets a round-trip fixture.
  - Scale factors are either applied or carried, never both.
- **Observation codes:** the **source** code, plus the resolved target code and where it
  came from (`source`, `override`, `companion`, `table`, `receiver-rule`, `default`).
- Comments, `PGM / RUN BY / DATE` and unknown header lines are kept verbatim, in order.

### 3.4 Readers, writers and the two-pass engine

- **Readers:** one per (major version, file type), streaming, reporting line and column on
  error. Layout rules:
  - RINEX 2: 5 observations per data line, 12 satellites per epoch line before
    continuation, 9 obs types per header line.
  - RINEX 3/4: one line per satellite, no wrapping, 13 obs types per header line.
- **Writers:** one per write version, driven by the spec tables.
- **Two passes.** Header records must come before the data, yet some depend on the data
  and on what the conversion drops: `TIME OF LAST OBS`, `# OF SATELLITES`, `PRN / # OF OBS`,
  and the per-system obs-type lists. So the engine works in two passes:
  1. Pass 1 streams the input, resolves the code mapping, and collects statistics, such as
     which obs types each system actually has data for. It spools **canonical records**
     (a compact binary form of the model, not formatted text) to a temporary file.
  2. Pass 2 fixes the final per-system obs-type lists and writes the header. It then
     **formats** every spooled record against those lists.

  Memory stays bounded: a **ceiling of 500 MB resident per file**, tested on the largest
  1 Hz corpus file. Temporary disk space is about the output size.
- **Performance** is measured, not guessed. A 1 Hz, 24 h, multi-GNSS file is about 1 GB of
  text. Throughput (MB/s) is measured on the corpus at M2 and M3 and recorded in
  `docs/ENVIRONMENT.md` with the laptop's hardware. Budgets are set from those numbers.
  Batch mode parallelises per file.

### 3.5 Conversion rules (`rinexconv/rules/`)

Every transformation is a named rule (`OBS.V2V3.CODEMAP.GLO.P2`, `NAV.V4V3.DROP.CNAV`, …)
with a spec citation, a lossiness class and a report emitter.

**Observation, v2 → v3/v4**

- RINEX 2 has **one global obs-type list**; RINEX 3 has **one per system**. Each system
  gets the subset of types it actually has data for, mapped per system.
- The 2-character → 3-character map resolves through layered rules: user override, then
  receiver-type rules, then a default table aligned with IGS and gfzrnx conventions,
  **per system**. Examples:
  - GPS: C1→C1C, P1→C1W, P2→C2W, L1→L1C, L2→L2W (or L2X/L2L by receiver), C5→C5X.
  - GLONASS: C1→C1C, P1→C1P, P2→C2P, L2→L2P/L2C by receiver.
  - Galileo: C1→C1X, C5→C5X, C7→C7X, C8→C8X.
  - BeiDou: band numbering per target version (3.02 uses `1I`; 3.03+ uses `2I` for B1I).

  Every assumed attribute is reported.
- Header records RINEX 3/4 needs and RINEX 2 lacks are resolved per §1.8:
  - `GLONASS SLOT / FRQ #`, mandatory from 3.02 when GLONASS is present. Sources: user,
    then a companion nav file, then a dated table. Otherwise stop, or use
    `--drop-unresolvable`.
  - `GLONASS COD/PHS/BIS`: receiver calibration values. **These come only from the user or
    a site log, never from nav.** If unknown, the spec's unknown convention, reported.
  - `SYS / PHASE SHIFT`, where the target version requires it, with its "unknown" form.
  - `SIGNAL STRENGTH UNIT` is **optional**. Write it only if known.
- `WAVELENGTH FACT L1/2` → explicit LLI rule (§3.3).

**Observation, v3/v4 → v2**

- Per-system lists are merged into the global list; a system lacking a type gets blanks.
- 3-character → 2-character codes are collapsed. Where several codes map to one RINEX 2
  code (L1C and L1W both → L1), a documented priority picks one; the rest are reported.
- Systems RINEX 2.11 lacks (C, J, I) are dropped and reported. An option writes them with
  non-standard letters, flagged.
- The receiver clock offset is truncated from F15.12 to F12.9; the epoch seconds lose
  everything below 1e-7 s. Both are reported.
- 2-digit years: 80–99 → 19xx.

**Observation, v3 ↔ v4.** Header-record and code-vocabulary changes, and the 4.02
picosecond extension, all table-driven. The 4.x deprecations are gated too:

- **From 4.00 on**, `SYS / PHASE SHIFT` is optional and strongly deprecated, and decoders
  and encoders should ignore it (`rinex_4.00.txt` §5.2.12). See the phase-alignment rules
  in §3.3.
- `GLONASS COD/PHS/BIS` is deprecated.
- The SSI flag is deprecated in favour of explicit `Sna` signal-strength observations
  (`rinex_4.02.txt` around line 3769).

Writers follow the target version's recommendation, and the report notes each deprecated
record that is carried or dropped.

**Navigation**

- **Merge and split** between v2 per-system files and v3/v4 mixed files. Records with
  distinct message types, IODs or transmission times are never merged. **Duplicates are
  preserved by default**, since the target can hold them and dropping them would be a
  loss. `--dedupe` collapses exact duplicates (every field equal) and reports the count. A
  merge of several v2 files that brings in a duplicate is reported but not removed. Output
  order is deterministic: system, satellite, time of clock, transmission time, then source
  order.
- **Header corrections:** v2 `ION ALPHA/BETA`, `DELTA-UTC` and `LEAP SECONDS` ↔ v3
  `IONOSPHERIC CORR`, `TIME SYSTEM CORR` and `LEAP SECONDS`, with the precision changes
  reported (§3.3).
- **v3 → v4:** header corrections become ION and STO records. Their reference and
  transmission times have to be chosen, and those choices are reported as assumptions.
  **The Galileo data-source bitmask is preserved verbatim in both directions.** It
  distinguishes the E1-B, E5a-I and E5b-I sources and the clock-reference signals, and 4.02
  Table A13 still carries it. The v4 message type (I/NAV or F/NAV) is *derived* from the
  bitmask and *validated* against it; it never replaces it. A record whose type and
  bitmask disagree is a validator finding.
- **v4 → v3:** only messages with a v3 form survive. They are GPS/QZSS LNAV, Galileo I/NAV
  and F/NAV (bitmask carried as is), GLONASS FDMA, BeiDou
  D1/D2, NavIC LNAV and SBAS. Dropped, and reported: CNAV, CNV1–3, L1OC/L3OC, NavIC L1NV,
  EOP, and every ION/STO record beyond what one header value can hold (the choice is
  reported).
- **GLONASS 3.05's fifth line:** when the target is ≤ 3.04, it is dropped (lossy). When
  converting from ≤ 3.04 to ≥ 3.05, it is filled with the spec's defaults (an assumption).
- **Field formats are version-gated, down to the exponent letter.**
  - v2: `3X,4D19.12`. v3 and 4.00: `4X,4D19.12`.
  - **4.01 and 4.02: `4X,4E19.12`.** `D` is "allowed but strongly deprecated", exponents
    must be zero-padded to two digits, and one exponent letter is used throughout a file
    (`rinex_4.02.txt` §6.8, around line 2677).
  - Our writers emit the letter the target version specifies, and the validator checks
    it. D/E is normalised only when *comparing* input to output, never on output.
  - The epoch/SV lines change too.

**Meteorological.** Header and epoch-format changes (4-digit year), with the full matrix
tests.

**Naming.** Short ↔ long, daily and high-rate, with the period and frequency fields taken
from the data.

### 3.6 Conversion report

One JSON file per output, with a versioned schema. It holds:

- the input and output files with their sha256 hashes;
- the source and target versions;
- every rule fired, with counts and up to N examples, given by line number;
- every assumption, with the source of its value;
- every loss, with exact counts per system and signal;
- every input repair;
- the validator result.

A one-line human summary goes to stderr.

### 3.7 Semantic diff and token comparator

- **Semantic diff** (`rinexcore/diff/`): compares canonical models after normalising
  version-only differences. It is used for clause 3.
- **Token comparator** (`tests/independent/`): implemented **separately**, with no imports
  from `rinexcore` model or spec tables. It is used for clause 5a.

### 3.8 Validator (`rinexcore/validate/`)

A per-version linter driven by the spec tables. It checks:

- mandatory headers per target version and system set;
- column layout, label spelling and placement;
- obs-type counts against the data;
- the time and count headers against the data;
- epoch ordering, epoch-flag syntax and event-record structure;
- nav record line counts per message type and version.

It gates conversion output, it implements `--strict`, and it is QC's "format compliance"
section. Its findings are classed as header-only (repairable) or data-level.

---

## 4. Test strategy

| Layer | What | Pass criterion |
|---|---|---|
| Spec examples | Every example record in the spec texts, as fixtures | Parses; the writer reproduces it (spec errata annotated) |
| Hand-made edge cases | See the list below | Contract clauses 1–9 |
| Unit | Every rule, codec, field formatter and table row | pytest, standard library only |
| **Corpus** | The real files in `data/corpus/` (§4.1); manifest `tests/corpus/manifest.json` | Normalised same-version identity; idempotence; all-to-all conversion; diff ⇔ report; token comparator; outputs validate; losses ⊆ allowed |
| Round trip | A → B → A for every lossless cell; A → B → A matches the loss report for lossy cells | Canonical equality |
| Oracles (dev, archived) | CRX2RNX: CRX decode bytes. gfzrnx: `-chk`, and its conversions compared by our diff and the token comparator. RTKLIB `rnx2rtkp`: SPP from original vs converted, on retained observations, with a tolerance justified by the reported precision losses. teqc: v2 files | Agreement, or clause 10 |
| Fuzz | A seeded stdlib-`random` mutator (byte flips, truncation, column shifts, label damage, CRX corruption) | Only `RinexError` escapes; a valid prefix still converts under `--lenient` |
| Performance | Measured throughput per file kind | Within the budgets set at M3 |

**Hand-made edge cases** (rare in the wild):

- **Epochs:** flags 1–6, including flag 4 changing obs types and wavelength factors
  mid-file; empty epochs.
- **Line layout:** more than 12 satellites, more than 9 or 13 obs types, F14.3 overflow.
- **Field values:** blank vs 0 LLI, a missing clock offset, scale factors, the 4.02
  picosecond epoch extension.
- **Years and time:** 2-digit years on either side of 1980 and 2000, GLONASS-only UTC files.
- **System-specific:** BeiDou 3.02 vs 3.03 codes, GLONASS 4-line vs 5-line nav, Galileo
  I/NAV vs F/NAV, duplicate nav records.
- **Damage and encoding:** a file truncated mid-epoch, CRLF endings, tabs, non-ASCII
  comment bytes.

**Acceptance for rinexconv 1.0:**

- The whole corpus, all-to-all, with the same-day nav as companion.
  - **Outcome:** every run ends `converted`. No crashes, no `refused-*` and no
    `converted-with-removal`, except where the input itself decides the outcome (the user's
    decision of 2026-11-03; docs/DECISIONS.md "rinexconv 1.0 close-out"):
    - `refused-corrupt` for the three damaged corpus inputs, each of which `--lenient` reads:
      mate1800.03m (met values out of their F7.1 columns), DARW00AUS 2020 3.03 met (epochs in
      the RINEX 2 layout) and BRDX00DLR 2020 "4.00" nav (a pre-release RINEX 4 format);
    - `refused-not-representable` where the target defines no record for any of the input's
      data: BeiDou-, Galileo- or NavIC-only nav files to RINEX 2, BeiDou- and NavIC-only ones
      to 3.00/3.01, and NavIC-only to 3.02.
    These are 72 (file, target) cells, and a run must show exactly these and no other.
  - **Output:** 0 invalid files, 0 unexplained or over-claimed differences, 0 losses outside
    the allowed list.
- The two other outcomes are tested on their own:
  - `refused-missing-information`: run without the companion file; the message must name
    the missing value.
  - `converted-with-removal`: the same run with `--drop-unresolvable`; the report must
    list the removed system.
- The token comparator is clean.
- Every oracle disagreement is resolved per clause 10.
- Golden oracle results are archived for every corpus file where the oracle exists.

### 4.1 Corpus

Built on 2026-10-30 by `tools/build_corpus.py`.

- **Screened:** 2,362 CDDIS headers, across eras from 1998 to 2026.
- **Kept:** **480 unique files (586 MB)**, a receiver-diverse set per kind and
  version, in
  `data/corpus/<obs|nav|met>/v<version>/`.
- Counts per bucket are in `data/corpus/CORPUS.md`; sha256 hashes are in
  `tests/corpus/manifest.json`.
- Files are kept exactly as served (gz, .Z, Hatanaka; daily, hourly and 1 Hz high-rate).
- The raw version field is kept as `version_str`, because writers really do emit `2` and
  `2.1`.

| Kind | Versions present (files) |
|---|---|
| obs | 2.00 (33), 2.10 (32), 2.11 (55), 3.00 (2), 3.01 (3), 3.02 (32), 3.03 (39), 3.04 (40), 3.05 (40), 4.00 (4), 4.01 (20), 4.02 (5) |
| nav | 2.00 (16), 2.01 (9, GLONASS), 2.10 (13), 2.11 (8, incl. SBAS `h`), 3.02–3.05 (48, all systems + mixed), 4.00 (8), 4.01 (2), 4.02 (5, `BRD400DLR`) |
| met | 2.00 (10), 2.10 (16), 2.11 (10), 3.02–3.05 (29), 4.00 (1) |

Gaps to fill (with `tools/build_corpus.py`, by adding days and directories) or to document:

- **Thin buckets:** 3.00, 3.01 and 4.00 obs; met 4.0x.
- **Single-brand buckets:** 4.01 and 4.02 obs are all Septentrio.
- **Not found at all:** RINEX 2 Galileo nav, 2.12, and files heavy with event flags.

Where no real file exists, coverage comes from hand-made fixtures plus gfzrnx-generated
files, and the gap is recorded in `docs/DECISIONS.md`. One real broken file turned up,
`yell1800.10d.Z` (2010), which decodes to nothing even with `unlzw3`. Keep files like it as
robustness fixtures.

---

## 5. rinexqc — quality analysis

It works in tiers, each needing more inputs. With obs only, you still get tier A.

### Tier A — the obs file alone

- **Format compliance:** the validator's findings, header-only versus data-level.
- **Header consistency:**
  - `INTERVAL` against the actual sampling; first and last obs times against the data;
    the counts; declared obs types that are always blank.
  - The approximate position: non-zero, and near the Earth's surface.
  - Receiver and antenna names against IGS `rcvr_ant.tab`, and the antenna+radome pair
    against `igs20.atx` (both optional downloads).
- **Time:** duplicate or out-of-order epochs, epoch-tag jitter and **epoch-tag jumps**,
  sampling regularity, gaps (whole file and per satellite), arc counts and lengths.
- **Receiver clock.** Code minus phase alone can't see a clock jump that hits code and
  phase equally, so each is tested separately:
  - **Code jumps:** a step common to all satellites in epoch-differenced code, against
    Doppler or geometry.
  - **Phase jumps:** the same test on phase.
  - **Receiver offset:** `RCV CLOCK OFFS APPL` and the epoch-line clock offset.

  The result classifies the receiver as code-only, both, or steered, and gives the drift.
- **Availability:** observations per system, signal and satellite. Code with phase,
  dual- and triple-frequency coverage, LLI and half-cycle flags.
- **SNR:** distribution per signal and satellite, and drop-outs.
- **Cycle slips.** No single test catches every slip, so several run together:
  - **Melbourne–Wübbena** is ionosphere-free, but blind to equal-cycle slips on both
    frequencies.
  - **Geometry-free** catches those, but must be gated against ionospheric activity.
    Squidy found that geometry-free alone counts scintillation as slips.
  - **Single-frequency** checks: phase minus code, and Doppler-integrated phase.
  - **LLI against detected slips**, as a cross-check.

  Results: slip counts, observations per slip (teqc's `o/slps`) and slip epochs.
- **Multipath:** MP1/MP2/MP5 and per-signal code-minus-carrier, with the per-arc mean
  removed, as RMS per satellite and signal. Formulas in `docs/QC_METRICS.md`.
- **Phase noise:** high-order time differences per signal.
- **Ionosphere:** IOD and geometry-free rate, ROT and ROTI, an S4-like SNR proxy (caveat:
  true S4 needs 50 Hz data).
- **Consistency:** code against Doppler, phase against Doppler, inter-signal.

### Tier B — plus broadcast nav or SP3 (downloadable from CDDIS)

- **Orbits:**
  - Keplerian for GPS, Galileo, BeiDou MEO/IGSO, QZSS and NavIC.
  - **BeiDou GEO** gets its own −5° rotation.
  - GLONASS: RK4 integration in PZ-90 with the broadcast accelerations.
  - SBAS from its ECEF state.
  - SP3: interpolation.

  Time scales (GPST, GST, BDT, GLONASST, QZSST, IRNSST) are converted explicitly.
  GLONASS wavelengths are per channel. The result is azimuth and elevation.
- **Completeness:** expected against observed observations above the mask. The expected
  count is *satellites above the mask with a healthy ephemeris* × *signals the receiver
  declares* × *signals that satellite transmits*. That last factor comes from a dated
  per-block signal table (L2C from IIR-M on, L5 from IIF, and so on). Tracked against
  visible satellites.
- **Sky plots** of SNR, multipath, slips and gaps, plus an **obstruction map** (missing or
  low SNR by azimuth and elevation).
- SNR and multipath against elevation, binned.
- **Single point positioning** per epoch:
  - Inter-system clock offsets estimated per system; TGD/BGD/ISC applied for the signal
    used.
  - Ionosphere-free combination when dual-frequency, else Klobuchar (or the BDS
    equivalent).
  - A troposphere model; Sagnac and relativity corrections.

  Outputs: scatter against the header position and the IGS reference, DOPs, code residuals
  per satellite, receiver clock.
- **Nav file QC** (`rinexqc nav`): ephemeris coverage, gaps, health and accuracy flags, IOD
  consistency, duplicates. **SISRE** against SP3:
  - Broadcast orbits refer to the antenna phase centre and SP3 to the centre of mass, so
    satellite PCOs from `igs20.atx` are applied.
  - Clock conventions are aligned: the relativistic term, the TGD reference signal, and a
    per-epoch clock-datum removal.
  - Radial, along-track and cross-track errors are weighted per constellation, with the
    weights cited.

### Tier C — plus precise products and station metadata

- Code residuals against precise orbits and clocks, with the corrections listed
  explicitly: satellite and receiver PCO/PCV from ATX, receiver ARP, troposphere,
  relativity, Sagnac, and code biases (OSB/DCB).
  Squidy's correction chain is the starting point, but it is approximate: block-level PCOs,
  and see its `math.md` "not modelled" list. Each addition is listed.
- Comparison with the IGS20 coordinate solution and the site log (antenna height, types).
- **Multi-day trends:** a station health history, like squidy's calendar heatmap.
- **Met QC** (`rinexqc met`): ranges, gaps, sensor headers.

### Outputs

- A JSON result with a versioned schema.
- A **self-contained offline HTML report**: plotly with the library embedded.
- A teqc-style one-screen text summary.
- An overall grade with documented, configurable weights. The grade never hides the
  numbers behind it.

### Validation of the QC numbers

- **Calibrate, freeze, then validate on held-out files.** The obs corpus is split by a
  fixed seed into a *calibration* half and a *held-out* half, listed in
  `tests/corpus/qc_split.json`. The split is **by station**, using the 4-character marker:
  every file from one station goes into the same half, whatever its day, cadence
  (daily, hourly, high-rate) or encoding. The corpus has several such groups, for example
  HKSL daily and hourly, and EBRE plain and Hatanaka. Without grouping, the held-out
  numbers would leak. Thresholds are tuned on the calibration half only, then
  frozen in `docs/QC_METRICS.md` along with the commit hash. Only after that are the QC
  acceptance numbers computed on the held-out half.
- **Synthetic injection:** use rinexconv's writer to put known events into real files:
  slips (including **equal-cycle slips on both frequencies**), gaps, code-only and
  code+phase clock jumps, multipath and SNR drops. Then measure the detection rate and
  false alarms per day: calibration targets first, held-out results reported.
- **Controlled numerical fixtures** for every computed quantity: orbits, az/el, SPP,
  SISRE and residuals. Synthetic inputs with known answers, such as a broadcast record
  and an SP3 built from the same state with known offsets, or a station with known
  geometry.
- **Oracles (dev):** teqc `+qc` on RINEX 2 and Anubis on RINEX 3.
  - Observed counts must match exactly.
    - An *observed count* is the number of (epoch, satellite) pairs with a **non-missing**
      value for that obs type.
    - **Missing** follows the format's own rule: blank **or** `0.0` (§3.3). Any LLI or SSI
      present doesn't change that.
    - Each oracle's own eligibility rules come on top, for example teqc counting pairs with
      both code and phase. Those rules are written per oracle in `docs/QC_METRICS.md`.
    - Zero-versus-blank fixtures test the definition.
  - Expected counts are compared loosely, because the elevation mask and orbit source
    differ.
  - Multipath RMS within max(2 cm, 10%).
  - Slips: match the slip epochs within ±1 epoch, with an absolute-or-relative band on the
    count of max(2, 20%). Counts are small, often 2–25 per day.
- **RTKLIB SPP** within a justified tolerance.
- Every formula goes in `docs/QC_METRICS.md` with a reference: Estey & Meertens 1999
  (teqc); Vaclavovic & Dousa 2016 (Anubis); Blewitt 1990 (TurboEdit); Pi et al. 1997
  (ROTI); IS-GPS-200, the Galileo OS SIS ICD, the BDS ICDs, the GLONASS ICD and the NavIC
  ICD for orbits; Montenbruck et al. for SISRE weights. Squidy's `math.md` is the template.

---

## 6. Shared: CDDIS data access (`rinexcore/cddis.py`)

These were verified against the live archive on 2026-10-30 (see `docs/CDDIS.md`):

- HTTPS with the Earthdata login, ported from `autocomparesp3`:
  - credentials go **only** to the exact host `urs.earthdata.nasa.gov`;
  - redirects are followed hop by hop, and an HTML reply is treated as an auth failure;
  - one session per thread.
- Listing: append `*?list` to a directory URL. It returns `name size` lines, files only.
- `Range` requests work through the login, so a header can be screened from the first
  24 KB.
- Per-directory `SHA512SUMS` and `MD5SUMS` files exist; use them to verify downloads.
- Fallbacks: anonymous FTPS to `gdc.cddis.eosdis.nasa.gov` (as squidy does), and the BKG
  mirror `https://igs.bkg.bund.de/root_ftp/IGS/` (no login).

**New work, not in the reference code:** resumable downloads, a local cache with a sha256
manifest, a cap of 4 parallel connections, and checksum verification.
`tools/build_corpus.py` already has the parallel fetch, the header screen and the manifest.

---

## 7. Milestones

Each milestone ends with three things: tests green, a short entry in `docs/DECISIONS.md`,
and a review round with the reviewer skill (a Claude reviewer plus one Codex reviewer),
fixing what they find.

| # | Milestone | Done when |
|---|---|---|
| M0a | Environment check, repo, .gitignore, `rinexcore.cddis`, import-purity test, corpus verified against its manifest | `python -m rinexcore.cddis --selftest` passes; `python tools/build_corpus.py --verify` passes |
| M0b | `docs/HATANAKA.md` grammar from `crx2rnx.c`; `allowed_losses.json` v0 by (source, target, type, category) from the specs; the obs-count and token definitions used by the independent checks | Reviewed by the user and one reviewer before M1 |
| M1 | Codecs: gz, `.Z` decode/encode, CRX decode (1.0/3.0/3.1) | The CRX decoder matches CRX2RNX on the whole corpus; results archived. The corpus has **no CRINEX 3.1 file**: the five real 4.02 obs files carry CRINEX 3.0 headers. So a 3.1 fixture with picosecond epochs is made with RNX2CRX 4.2.0 and archived. RNX2CRX.exe comes from the same GSI zip as CRX2RNX.exe (URL in `reference/tools/rnxcmp-4.2.0/provenance.json`), with its sha256 recorded. The laptop has no C compiler, so don't plan to build it |
| M2 | Obs spec tables (all versions), model with header timeline, obs readers 2/3/4, validator v1, token comparator | All corpus obs files parse; throughput measured |
| M3 | Obs writers, normalised same-version identity, idempotence, CRX encoder, two-pass engine | Gates met on the corpus; budgets set |
| M4 | Obs cross-version rules, report, diff ⇔ report, naming | All-to-all obs on the corpus: clauses 1–9 hold |
| M5a | Nav v2 ↔ v3 (all systems, merge/split, header corrections, the GLONASS fifth line) | The same, for v2/v3 nav |
| M5b | Nav v4 (all message types, ION/STO/EOP) ↔ v3 | The same, for v4 nav, against gfzrnx (RTKLIB's v4 support is unconfirmed) |
| M6 | Met | The same, for met |
| M7 | Oracle sweep and archiving, fuzz, performance, corpus gap fill | rinexconv 1.0 acceptance (§4) |
| M8 | CLI polish, batch mode, docs, generated conversion matrix | Ready to hand to someone else |
| Q1 | QC tier A + JSON + text summary; nav and met QC basics | Runs on the whole corpus; injection targets set and met |
| Q2 | Orbits (all systems + SP3), az/el, completeness, sky plots | Elevation within 0.01° of SP3-derived values |
| Q3 | Slips, multipath, phase noise, ionosphere | Within the §5 tolerances of teqc and Anubis |
| Q4 | SPP, nav file QC with SISRE | Controlled SPP and SISRE fixtures pass. RTKLIB SPP agrees on matched epochs and satellites with the same signals and corrections. Published SISRE values are context only, never a gate |
| Q5 | HTML report, grade | Report reviewed by the user |
| Q6 | Tier C: precise-product residuals, metadata checks, multi-day trends | Controlled residual fixtures pass, with each correction term tested alone. Squidy's ORD is a sanity check only, since its corrections differ |

QC can start once M4 is done. Q1 can run alongside M5 and M6.

---

## 8. Risks and how they are handled

| Risk | Mitigation |
|---|---|
| v2 → v3 attributes are inherently ambiguous: no conversion can know whether L2 was L2C or P(Y) | Layered rules with user override first; every assumption reported. The contract says *explicit*, not *omniscient* |
| GLONASS channel numbers, or other mandatory values, are unknown | Resolution order (§1.8); never invented; stop or `--drop-unresolvable` |
| Real files break the spec | Header-only repairs by default, `--lenient` for data-level damage, a corpus spanning receivers and vintages |
| Converter, diff and validator share a mistake | The independent checks of §1.5: token comparator, hand-written expectations, archived oracle output, pre-authorised losses |
| The RINEX 4 nav message zoo grows | Table-driven layouts with version gating; a new message type is a table row plus fixtures |
| Hatanaka edge cases | Grammar written first; byte equality against CRX2RNX on every corpus file; CRX fuzzing |
| Pure-Python speed | Two-pass streaming, measured budgets, per-file multiprocessing, optional numba |
| The laptop's Anaconda is older or newer | Checked at setup; the core stays stdlib; versions recorded |
| CDDIS changes or goes down | BKG mirror, FTPS fallback, local cache, corpus kept on the F: drive |
| Oracle licences: gfzrnx needs its own registration; teqc is retired | All oracles optional; the user downloads them; results archived once |

---

## 9. Reuse from the desktop projects

Copied into `reference/`. Read it and port ideas; don't import it. Details, with line
references, are in `reference/README.md`.

| From | Use for | Caveat |
|---|---|---|
| `cddis_https/sp3_downloader.py`, `config.py` | Earthdata auth class, hop-by-hop redirects, HTML check, credentials lookup | Imports `unlzw3` (from pip) and `backend.*` (not copied); whole-body downloads; no resume, cache manifest or checksum support |
| `cddis_https/cddis_browser.py` | — | Parses HTML listings with bs4. Use `*?list` instead |
| `squidy/` | `math.md` formulas; MP, ROTI, slip-detection lessons; pseudorange sanity gates; troposphere; FTPS fetcher | GPS only. Reads the whole file into memory. Seconds rounded to 1e-6 (can produce second = 1000000 µs). Probably mis-parses v2 event epochs (flag ≥ 2, `parse_rinex.py` ~123–141). Corrections approximate |
| `customkf/rinex.py`, `broadcast.py` | Fail-closed streaming ideas; the GLONASS 4/5-line nav switch (~line 212); GPS LNAV equations | GPS only; a 10,000-epoch cap; GPS-time check only; rejects Hatanaka |
| `customkf/bkg_fetch.py` | The BKG URL layout (`obs/YYYY/DDD`, `BRDC/YYYY/DDD`, `products/<week>`) | Calls curl and CRX2RNX through `subprocess`; imports modules that weren't copied |
| `nav2sp3/` | Ephemeris selection rules (nearest TOE, IODE tie-break, health) | **GPS RINEX 2 nav only** |
| `converter_prototype/211to305rinex.py` | A list of pitfalls | GPS only, naive code map, no continuation lines, no event flags. **Not a base to build on** |
| `tools/rnxcmp-4.2.0/CRX2RNX.exe` | The dev oracle for CRX decoding (it supports CRINEX 3.1) | Dev-only. There is no RNX2CRX.exe here; download it from the same GSI zip (see M1). The `specs/hatanaka/` source is for reading, not building |
