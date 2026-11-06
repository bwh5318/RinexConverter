# RINEX Convert & Analysis — Plan

Two tools that share one RINEX core:

1. **rinexconv**: converts RINEX observation, navigation and meteorological files between
   the common versions (2.x, 3.x and 4.x), correctly for every valid input.
2. **rinexqc**: measures the quality of a RINEX file as completely as the data allows,
   and writes a JSON result, an offline HTML report and a short text summary.

The guide for the Claude that builds this is [CLAUDE.md](CLAUDE.md). This file is the plan.
Revision 3 (2026-10-30) took in three review rounds by Sonnet and Codex Astra. Revision 4
(2026-11-06) rewrites the QC plan (§3.9, §5, §6, the Q milestones) after a review by Codex
Sol 6.1 and Opus, once rinexconv was finished. Scores and changes are in `docs/REVIEW_LOG.md`;
newer decisions in `docs/DECISIONS.md` win over this plan where they differ. Every factual correction from those reviews was
checked against the spec text in `specs/text/` before it went in.

---

## 0. Hard constraints

| Constraint | Consequence |
|---|---|
| **Python plus the packages Anaconda ships, nothing else.** No `pip install`, no `conda install`. | Any package that `conda list` shows with channel `pypi` is off limits, even if installed. `unlzw3`, `georinex`, `hatanaka`, `hypothesis`, `gnsspy` and `pypdf` are all out. We write our own LZW (`.Z`) and Hatanaka (CRX) codecs. |
| The finished tools run with no outside programs. | CRX2RNX, gfzrnx, RTKLIB, teqc and Anubis are allowed **only as optional dev-time oracles** in tests. Their results are also **archived**, as digests and hashes (§1.5c), so a machine without them keeps the coverage. Shipped code never calls `subprocess`. |
| Credentials are never committed, printed or sent anywhere but the Earthdata login host. | See CLAUDE.md and `docs/CDDIS.md`. |

**Which module may import what.** This is enforced by an AST import-purity test (the
pattern in `reference/nav2sp3`).

| Module | Allowed imports |
|---|---|
| `rinexcore/` except `cddis.py`, and all of `rinexconv/` | Standard library only |
| `rinexcore/cddis.py`, `tools/` | Standard library + `requests` |
| `rinexqc/` | The standard library, rinexcore (never rinexconv: §3.9), numpy, scipy, matplotlib, plotly, jinja2; numba is optional, always with a pure-Python fallback. Network access only through `rinexcore/cddis.py` |
| `tests/independent/` (including `qc/`) | The standard library and numpy; nothing from rinexcore, rinexconv or rinexqc |

Anaconda 2024.10, the desktop's version, ships numpy 1.26, scipy 1.13, pandas 2.2,
matplotlib 3.9, plotly 5.24, bokeh 3.6, numba 0.60, pyerfa, astropy, requests, jinja2,
beautifulsoup4, lxml and pytest 7.4. The `conda list` of the machine in use is the source of truth,
recorded in `docs/ENVIRONMENT.md` (the desktop and the laptop both).

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
     of the token multisets, plus counts per system, signal and epoch. A machine without
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
- Out of scope for conversion: clock RINEX, ANTEX, IONEX, SINEX. They are different formats;
  rinexqc reads some of them as inputs (§3.9).
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
- `python -m rinexqc IN [--nav FILE] [--sp3 FILE] [--clk FILE] [--atx FILE] [--fetch]
  [--glo-fcn FILE] [--overrides FILE] [--lenient] [--html FILE] [--json FILE]`, plus
  `python -m rinexqc nav FILE` and `python -m rinexqc met FILE`. No network call without
  `--fetch` (§5.1).
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

### 3.3 Canonical model (`rinexcore/obs.py`, `nav.py`, `met.py`, `header.py`)

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

  Memory stays bounded: about 2 to 2.5 times the decoded file, linear in its size
  (`tests/unit/test_memory.py`; the 24 h 1 Hz test in docs/DECISIONS.md). Temporary disk space is about the output size.
- **Performance** is measured, not guessed. A 1 Hz, 24 h, multi-GNSS file is about 1 GB of
  text. Throughput (MB/s) is measured on the corpus at M2 and M3 and recorded in
  `docs/ENVIRONMENT.md` with the machine's hardware. Budgets are set from those numbers.
  Batch mode parallelises per file.

### 3.5 Conversion rules (`rinexconv/obsconv.py`, `codemap.py`, `navconv.py`, `metconv.py`)

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

### 3.8 Validator (`rinexcore/validate.py`)

A per-version linter driven by the spec tables. It checks:

- mandatory headers per target version and system set;
- column layout, label spelling and placement;
- obs-type counts against the data;
- the time and count headers against the data;
- epoch ordering, epoch-flag syntax and event-record structure;
- nav record line counts per message type and version.

It gates conversion output, it implements `--strict`, and it is QC's "format compliance"
section. Its findings are classed as header-only (repairable) or data-level.

### 3.9 rinexqc (`rinexqc/`)

rinexqc imports rinexcore, never rinexconv, so a QC result cannot depend on a conversion rule.
The import-purity test gains that rule. What both need moves into rinexcore: the GLONASS
channel lookup in `rinexconv/companion.py`, and the named nav fields (§5.4). Tests may use
rinexconv, to make the version-invariance check and the injected files of §5.9.

```
rinexqc/
  semantics.py   the adapter of §5.2: raw fields -> (system, band, attribute, value, flags), once
  signals.py     frequencies and pairs (rinexqc/spec/, cited rows, as rinexcore/spec/ does)
  run.py         one streaming pass over the epochs, feeding the accumulators
  metrics/       time, availability, snr, clock, combos (mw, gf, mp, iono), slips
  nav.py  met.py nav and met QC (§5.4, §5.5)
  orbits/        broadcast propagation per message type, sp3, time scales, az/el (§5.6)
  products/      readers for SP3, clock RINEX, ANTEX, bias SINEX, SINEX coordinates
  spp.py         single point positioning
  report/        json (schema docs/QC_SCHEMA.md), text, html
  cli.py
```

- **One pass, bounded state.** rinexcore's reader yields epochs. It holds the decoded file in
  memory, so QC's floor is the decoded size. Each metric is an accumulator, and its state is
  bounded explicitly:
  - windows (detrending, ROT, ROTI, slip tests) of a fixed number of epochs;
  - online sufficient statistics (counts, sums, moments) for whole-arc results. An arc can last
    the whole file (a BeiDou GEO for 24 h at 1 Hz). An estimator that needs a whole arc, such
    as an arc median, either spools the arc to a temporary file (as rinexcore's spool does) or
    uses a stated approximation. `QC_METRICS.md` says which quantiles are exact and which are
    approximate;
  - display buffers of a fixed size, filled only after the numbers are computed at full rate.

  The epoch times and the receiver-clock series are the only per-epoch series kept for the
  whole file. Within a window the work is numpy; numba is optional, with a pure-Python
  fallback.
- **Compliance is the validator's.** The reader checks fields as it goes (`iter_epochs`), but
  reading a file is not validating it: a file can read cleanly and still lack mandatory header
  records. The compliance findings come from rinexcore's validator (`validate.py`), run as its
  own pass and budgeted in the resource targets with the reader. The converter's whole-file
  check (`presurvey`) is in rinexconv, which QC does not import.
- **A refusal part-way through.** If the reader refuses at epoch N, what was accumulated is
  discarded and the file gets its compliance findings (D1). Under `--lenient`, the lenient
  reader runs, and every metric keeps its own status (`ok`, `cannot-compute`, `not-applicable`) and carries a separate `lenient-read` flag.
- **Resource targets, set in Q0b and met in Q1** (docs/ENVIRONMENT.md), on two files:
  - the 24 h 1 Hz MIZU00JPN day 2026/290 (1.6 GB of RINEX 3.05, 7 systems; in
    `data/highrate/`);
  - a daily 30 s file.

  Q0b measures the reader alone on both (its time and its peak memory) and sets targets against
  it: QC's peak memory as the decoded size plus a bounded margin, its time as a multiple of the
  reader's, and the size of the JSON and HTML outputs. Q1 must meet those targets; recording
  what the finished code happens to use is not enough.
- **Products** are inputs, never converted. §2's "out of scope" (clock RINEX, ANTEX, SINEX)
  is about conversion; rinexqc reads them. Each product reader gets its own spec citations
  and fixtures.
- **Downloads** happen only through `rinexcore/cddis.py` with `--fetch`, into a local cache with a
  sha256 manifest. The input matrix (`QC_METRICS.md`) lists, per metric, the files it needs. §6
  lists where each product lives.

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

rinexqc measures; it never changes the data. It works from three kinds of input, and each metric
names the inputs it needs:

- **the file alone:** an obs, nav or met file (§5.3 to §5.5);
- **plus orbits:** broadcast nav or SP3 for the same span (§5.6);
- **plus precise products and station metadata** (§5.7).

The architecture is §3.9; the milestones, Q0a to Q6, are in §7. Every formula, threshold and table
goes in `docs/QC_METRICS.md` with a reference, checked against the source as the converter's
spec tables were.

### 5.1 The QC contract

1. **Every number says what it is.** Each metric in the JSON result carries: its value or `null`;
   its unit; its support (epochs, satellites, arcs used, and how many were excluded and why);
   a status, one of `ok`, `degraded(reason)`, `cannot-compute(reason)` or
   `not-applicable(reason)`; the method (a section of `QC_METRICS.md`); the threshold set and
   its commit; and the inputs, by name and sha256. A missing value is `null` with a reason,
   never 0.
2. **Evidence apart from inference.** What a test saw is reported apart from what it is taken
   to mean: "Δ geometry-free above threshold at these epochs" is evidence, "cycle slip" is an
   inference. Anything that needs outside knowledge to be sure is labelled a **hypothesis**:
   obstruction, scintillation, clock steering. Each detector states its detection limit
   (§5.3.2).
3. **Offline by default.** QC makes no network call unless asked (`--fetch`, through
   `rinexcore.cddis`). A missing product disables only the metrics that need it, each with
   `cannot-compute(missing <product>)`. The input matrix in `QC_METRICS.md` lists each
   metric's inputs.
4. **The version must not change the physics.** A file and its rinexconv conversion to a write
   version give the same values for an enumerated list of physical metrics: counts, gaps,
   clock jumps, SNR statistics and, from Q3, the combinations. They are compared on the
   observations both files hold, with the same metadata and inputs. A conversion may also,
   legitimately, change what QC is allowed to know, with or without a reported loss:
   - `SIGNAL STRENGTH UNIT` is lost going to 2.x, so dB-Hz becomes relative;
   - `GLONASS SLOT / FRQ #` is lost going to 2.x or 3.00 (a reported loss; rinexconv carries it
     to 3.01), so FDMA metrics then need a nav file;
   - going from v2 to v3, rinexconv's assumed attributes name an "attribute unknown" code;
   - header repairs change `INTERVAL` and the counts.

   So Q0a writes an **invariance table**, `tests/expectations/qc_invariance.json`, from the specs
   before any Q1 code. It is keyed by the conversion report's categories (losses, repairs,
   normalisations, assumptions), and says which QC fields may change and how (value, unit,
   status). Compliance findings, provenance and metadata-dependent statuses get their own
   expected changes. Signals are matched through the conversion report (a source's C2 with
   "attribute unknown" is the target's assumed C2W, and the assumption is listed). This is a Q1
   gate.
5. **Damaged input** is decision D1 (§5.10). Proposed: QC reads what rinexcore reads. A file
   the reader refuses gets its compliance findings only (the reader's `refused-corrupt` with
   line, column and rule), plus the validator's. `--lenient` reads it with the lenient reader;
   every metric keeps its own status (`ok`, `cannot-compute`, `not-applicable`) and carries a separate `lenient-read` flag.

### 5.2 Observation semantics: one adapter

rinexcore yields raw fields. Their meaning changes with the version (CLAUDE.md "RINEX
gotchas"), so one adapter, `rinexqc/semantics.py`, applies each meaning **exactly once**.
Every metric reads the adapter's output, never the raw fields:

| Item | RINEX 2 | RINEX 3 and 4 | Source |
|---|---|---|---|
| Missing value | blank or `0.0` | blank or `0.0` | rinex211.txt Table A2; rinex305.txt §6.7 p.43 |
| LLI bit 0 | lost lock: slip possible | same | as above |
| LLI bit 1 | opposite wavelength factor to `WAVELENGTH FACT L1/2`, this epoch only | half-cycle ambiguity or slip possible | rinex211.txt Table A2; rinex305.txt §6.7.1 p.43, §5.2.13 p.28 |
| LLI bit 2 | observed under antispoofing | BOC tracking of an MBOC signal, from 3.01 (3.00 defines bits 0 and 1 only) | rinex211.txt Table A2; rinex300.txt, rinex301.txt, rinex305.txt §6.7.1 p.43 |
| Wavelength factor | `WAVELENGTH FACT L1/2` (header and events), GPS L1 and L2 only: factor 2 means the ambiguity spacing is half a wavelength (squaring receivers). Phase values stay in whole carrier cycles; nothing is rescaled | none | rinex211.txt §10.1.2, Table A1 |
| SSI digit | 1-9, receiver-dependent projection | 1-9 mapped from dB-Hz when the raw value is in dB-Hz | rinex211.txt Table A2; rinex305.txt §6.7.2 p.43 |
| S observations | units "receiver-dependent" | `SIGNAL STRENGTH UNIT` (optional, from 3.00; `DBHZ`) | rinex211.txt Table A1; rinex303.txt |
| Event flags | 2 moving antenna, 3 new site, 4 header records follow, 5 external event; header records may follow flags 2-5. Flag 6 is followed by slip records, not header records | same | rinex211.txt §0.4 and Table A2; rinex305.txt §6.5 p.42 |
| Scale factors | none | `SYS / SCALE FACTOR`, in the header and after events | rinex305.txt §5.2.11 p.26 |
| Applied corrections | none | `SYS / DCBS APPLIED`, `SYS / PCVS APPLIED`: reported, and named by every metric they affect | rinex305.txt §5.2.9-5.2.10 p.26 |
| Phase alignment | unknown | the alignment state of §3.3: unknown for 3.00 (no record) and for a blank 3.01 record; 3.01-3.05 records list the shifts applied, or the states of §3.3; 4.x aligned by definition | §3.3; docs/PHASE_ALIGNMENT.md |
| Receiver clock | `RCV CLOCK OFFS APPL`, epoch-line offset | same | rinex211.txt Table A1; rinex305.txt |
| Time system | GPS, except GLONASS-only files, which are in UTC; `GAL` allowed from 2.11; `TIME OF FIRST OBS` names it | the header's time system | rinex211.txt Table A1 and change log |

What follows from the table:

- **SNR** is in dB-Hz only when the unit is known: the header says `DBHZ`, or a user table names
  the receiver as reporting dB-Hz (D5). Otherwise it is reported as relative values, and the
  SSI digit as an ordinal value, never as dB-Hz.
- **Signal identity** is (system, band, attribute). A RINEX 2 code has no attribute: C2 is the
  L2C pseudorange in 2.11 (rinex211.txt Table A1), but which L2C component (S, L or X) is not
  said, and P2 may be P(Y) or semi-codeless. The adapter keeps "attribute unknown". It never borrows rinexconv's
  conversion default silently; `--overrides` sets attributes, as in rinexconv. The result says
  which code fed each combination ("MP2 from P2", "MP2 from C2").

**Frequencies and pairs** (`QC_METRICS.md`; from rinex_4.02.txt Tables 10-16, printed pp.29-34;
checked against the PDF):

| System | Bands (RINEX band: MHz) | Pairs supported (the preferred one first) |
|---|---|---|
| GPS | 1: 1575.42; 2: 1227.60; 5: 1176.45 | L1/L2, L1/L5, L2/L5 |
| GLONASS FDMA | 1: 1602 + k·9/16; 2: 1246 + k·7/16 (channel k) | G1/G2 (needs k) |
| GLONASS CDMA | 4: 1600.995; 6: 1248.06; 3: 1202.025 | G1a/G2a, G1a/G3 |
| Galileo | 1: 1575.42; 5: 1176.45; 7: 1207.14; 8: 1191.795; 6: 1278.75 | E1/E5a, E1/E5b, E1/E5 (AltBOC), E1/E6 |
| BeiDou | 2: 1561.098 (B1I, `C1I` in 3.02); 1: 1575.42 (B1C); 5: 1176.45 (B2a); 7: 1207.14 (B2I, B2b); 8: 1191.795; 6: 1268.52 (B3I) | BDS-2: B1I/B3I, B1I/B2I. BDS-3: B1I/B3I, B1C/B2a |
| QZSS | 1: 1575.42; 2: 1227.60; 5: 1176.45; 6: 1278.75 | L1/L2, L1/L5 |
| NavIC | 1: 1575.42 (from 4.01); 5: 1176.45; 9: 2492.028 | L5/S, L1/L5 |
| SBAS | 1: 1575.42; 5: 1176.45 | L1/L5 |

- Every supported pair is computed where the file has it, each reported under its own name.
  The preferred pair is only the one the summary and the grade show.
- BDS-2 or BDS-3 is decided by a dated PRN table from the satellite metadata (D2), not
  guessed from the PRN alone.
- **The GLONASS FDMA channel k** is found in the order rinexconv uses (§1 clause 8,
  `rinexconv/companion.py`):
  1. the file's own `GLONASS SLOT / FRQ #` (optional in 3.01, mandatory from 3.02). Unlike the
     converter, which needs one channel per satellite for the header, QC follows the record
     epoch by epoch: one in an event (flags 2-5) applies from that epoch on, to every satellite
     it names, already tracked or not, and a change of channel is reported;
  2. then `--glo-fcn`;
  3. then a same-day nav file.

  Sources that disagree are reported, never reconciled silently. Without a channel, every
  metric that needs the wavelength is `cannot-compute(no-channel)`; the channel is never
  assumed. RINEX 2 and 3.00 files have no channel record.

### 5.3 Observation QC from the file alone

#### 5.3.1 Counts, time, clock, SNR (Q1)

- **Format compliance:** the validator's findings, header-only and data-level apart.
- **Header consistency:**
  - `INTERVAL` against the actual sampling; first and last obs times against the data; the
    counts; declared obs types that are always blank.
  - The approximate position: non-zero, and within 50 km of the Earth's surface.
  - Receiver and antenna names against IGS `rcvr_ant.tab`, and the antenna and radome pair
    against `igs20.atx` (downloads: D2).
- **Time:**
  - The evaluation interval is from the first to the last epoch. The sampling grid comes from
    `INTERVAL`, or else from the modal spacing.
  - Duplicate and out-of-order epochs; epoch-tag jitter (offset from the grid) and epoch-tag
    jumps.
  - Gaps, for the whole file and per satellite.
  - Arcs: a satellite's run of epochs. An arc ends at a gap longer than the threshold, at
    flags 2 and 3 (a moving antenna, a new site) and at a change of type list. Slips split the
    phase arcs of §5.3.2, not these.
- **Availability:**
  - Observed counts per (satellite, signal). An *observed count* is the number of epochs with a
    **non-missing** value of that type; missing is blank **or** `0.0`, whatever LLI or SSI says.
  - Code with phase, dual- and triple-frequency coverage, and LLI and half-cycle flags, read
    through the adapter.
- **SNR:** the distribution per signal and satellite, in the unit the adapter allows; drop-outs
  against the arc's running median.
- **Receiver clock, from the file alone.** Three discontinuity series are reported separately,
  each with its support count:
  - **code:** a step common to all satellites in epoch-differenced code;
  - **phase:** the same test on phase, in metres;
  - **epoch tags:** jumps of the time tags themselves.

  Also reported: `RCV CLOCK OFFS APPL` and the epoch-line clock offset, as given. Doppler, where
  the file has it, is a cross-check: 75 of the 120 RINEX 2 corpus files have none. Millisecond
  jumps (about 300 km in code) are found at any cadence; smaller steps only above a noise
  floor per cadence (`QC_METRICS.md`).

  The receiver is classed as "jumps in code only", "jumps in code and phase", "no jumps" or
  "undetermined". **Steering and drift are not inferred here.** They need a clock series from
  the epoch-line offset or from SPP (§5.6); without one, they are `cannot-compute`.

#### 5.3.2 Combinations (Q3)

Each combination is defined in `QC_METRICS.md` with:

- its formula and unit;
- its pair, from the table in §5.2, and which code and phase attributes feed it;
- where its arcs reset (a gap, LLI bit 0, a flag-6 record, a type change);
- its detrending and window;
- the cadences it is valid at;
- its noise amplification.

The combinations:

- **Melbourne–Wübbena** (wide-lane cycles): ionosphere-free, and blind to slips of equal cycles
  on both frequencies.
- **Geometry-free phase** (m). A GPS (1,1) slip moves it by λ2 − λ1 = 0.0539 m, which at 30 s
  is within ordinary ionospheric change at low elevation. **At 30 s such a slip is not reliably
  detectable. At 1 Hz detection may improve, but cadence alone guarantees nothing:** it depends
  on the noise, the ionosphere and the observables the file has. QC_METRICS.md states each
  test's eligibility and its measured precision and recall per cadence, from §5.9.
- **Single-frequency tests:** phase minus code; Doppler-integrated phase, where the file has
  Doppler, at 1 Hz or faster only.
- **Multipath** MP1, MP2 and MP5, and per-signal code minus carrier. The per-arc bias estimator
  is named (squidy uses the arc median and drops arcs under 10 epochs: `math.md`); dropped arcs
  are counted. RMS is per satellite and signal; the result is multipath plus code noise, and is
  reported as such.
- **Phase noise:** high-order time differences, at 1 Hz or faster only, and on static segments
  only (the differences also hold receiver dynamics).
- **Ionosphere:** the geometry-free rate in TECU/min, ROT, and ROTI (the standard deviation of ROT
  over 5 minutes: Pi et al. 1997). An S4-like SNR proxy at 1 Hz or faster only, labelled a proxy.
  None of these is called scintillation.
- **Slips.** Each test's evidence is reported apart (MW, GF, single frequency, Doppler, LLI). The
  inferred slips combine them under documented rules. The result also gives observations per
  slip (teqc's `o/slps`) and the slip epochs.
- **Consistency:** code against Doppler, phase against Doppler, and between signals; the last
  needs the phase-alignment state.

### 5.4 Navigation QC

**From the file alone (Q1):**

- Ephemeris coverage per satellite, and gaps.
- Health and accuracy flags as broadcast (URA, SISA).
- IOD consistency: IODE and IODC; Galileo IODnav; BeiDou AODE and AODC; GLONASS tb.
- Toe, toc, transmission time and the fit interval.
- Duplicates, identical apart from conflicting (same satellite and toc, different values).
- Parameter ranges against each ICD (√A, e, i, clock terms).
- The GLONASS tk basis (day or week: the known damage in real 3.x files).
- RINEX 4 message types per system.

This needs fields by name. Today `NavRecord.vals` holds them by position (rinexcore/nav.py), so
a named-field table goes into `rinexcore/spec/`, with its own spec citations.
`tests/independent/navfields.py` stays the independent check, and nothing may import it.

**With SP3 and clocks (Q4): SISRE.**

- SP3 positions refer to the centre of mass. Broadcast orbits refer to the antenna phase
  centre, except GLONASS, which probably refers to the centre of mass (to be checked against
  Montenbruck et al. 2015 before it is relied on). The ionosphere-free satellite PCO from
  `igs20.atx` is applied, with nominal yaw.
- The broadcast clock's reference is declared per system and message, from each ICD.
  - The GPS L1/L2 ionosphere-free clock takes **no** further TGD correction: TGD is for
    single-frequency users.
  - Galileo: I/NAV refers to E1/E5b and F/NAV to E1/E5a. BeiDou: B3I, with TGD1/TGD2 for B1I and
    B2I, and the BDS-3 CNAV TGD_B1Cp and TGD_B2ap.
  - The references for GLONASS, QZSS, NavIC and SBAS are written in `QC_METRICS.md`, each with
    its source.
  - Each single-signal clock is derived explicitly from these.
- Before any comparison, `QC_METRICS.md` fixes the precise clock's reference, the clock datum
  per constellation (the ensemble removed per epoch) and the relativistic convention.
- When the precise clocks are missing, the result is orbit-only SISRE.
- Radial, along-track and cross-track errors are weighted per constellation and orbit class
  (MEO, IGSO, GEO), with the weights cited.
- Published SISRE values are context only, never a gate.

### 5.5 Meteorological QC (Q1)

Met QC needs no products:

- ranges per observation type (PR, TD, HR, ZW, ZD, ZT, WD, WS, RI, HI);
- gaps and sampling;
- jumps, with thresholds in `QC_METRICS.md`;
- sensor headers (`SENSOR MOD/TYPE/ACC`, `SENSOR POS XYZ/H`): present, and consistent with the
  data.

### 5.6 Obs QC with orbits: broadcast nav or SP3 (Q2, Q4)

**Orbits.** For each system and message type, `QC_METRICS.md` gives:

- the propagation:
  - Keplerian for GPS, Galileo, BeiDou MEO and IGSO, QZSS and NavIC, with the CNAV, CNV2 and
    BDS CNV1-3 terms (Ȧ, Δṅ0 rate);
  - BeiDou GEO with its −5° rotation;
  - GLONASS by RK4 in PZ-90, with the broadcast accelerations;
  - SBAS from its ECEF state;
  - SP3 by interpolation, with the order, window and edge handling stated;
- the selection and expiry rules (fit interval, health, IOD tie-break);
- the time scale (GPST, GST, BDT, GLONASST, QZSST, IRNSST), converted explicitly. RINEX `GLO`
  time tags, in obs and nav files, have UTC hours, not the UTC+3 h of GLONASS system time
  (rinex_4.02.txt §4.1.2 p.15), so they get no 3 h conversion;
- the frame;
- the clock polynomial and relativistic term;
- the group delays per signal (TGD, BGD, the BeiDou TGDs relative to B3I, ISCs).

Satellite positions include the signal travel time and the Earth's rotation during it.
Azimuth and elevation come from the header position, an SPP position or the IGS20
coordinates, whichever is given (the result says which).

**Completeness:** three numbers per satellite and signal, over the evaluation interval, never
merged into one. The grid is the declared cadence (`INTERVAL`) and the inferred one (the modal
spacing), both reported. Where they disagree, the result says which one it used and why: real
files often have `INTERVAL` wrong.

- **geometric visibility:** above the elevation mask (configurable), from the orbits;
- **healthy-nav availability:** a healthy ephemeris exists ("healthy" defined per system from
  each ICD's health fields, in `QC_METRICS.md`). SP3 carries no broadcast health, so
  with SP3 alone this number is `cannot-compute`, and so is health-conditioned tracking
  completeness. A "visible only" variant is reported instead, under its own name and status;
- **tracking completeness:** observed / expected. The expected count is the epochs when the
  satellite is visible and healthy × the signals the receiver declares at that epoch (type lists
  may change mid-file) × the signals that satellite transmits. That last factor comes from a
  dated PRN → SVN → block table, built from the IGS satellite metadata SINEX (D2).

Block metadata says what a satellite can transmit, not that it did. So each completeness
result gives, apart:
- the known-eligible trials: *K* expected, of which *k* observed;
- the trials whose eligibility is unknown (the transmission or the receiver configuration),
  split into *U*ₒ observed and *U*ₘ missing.

The bounds come from varying the unknown trials' eligibility, with numerator and denominator
changing together:
- lowest: *k* / (*K* + *U*ₘ), the missing unknowns counted as eligible and the observed ones
  left out;
- highest: (*k* + *U*ₒ) / (*K* + *U*ₒ), the reverse.

A zero denominator is `cannot-compute`, and so is a result with nothing known. Unknown trials
are never dropped silently. Fixtures test both kinds of unknown and the zero cases.

**Sky plots** of SNR, multipath, slips and gaps. The **obstruction map** (missing or low SNR by
azimuth and elevation) is labelled a hypothesis: obstruction, multipath and the antenna pattern
look alike. SNR and multipath against elevation, binned.

**Single point positioning** per epoch:

- models named in `QC_METRICS.md`:
  - the troposphere: Saastamoinen with a standard atmosphere, as RTKLIB's SPP uses, so the Q4
    comparison matches models;
  - the ionosphere-free combination with dual frequencies;
  - with one frequency, Klobuchar for GPS and QZSS, the BeiDou Klobuchar coefficients, and for
    Galileo NeQuick-G or Klobuchar as an approximation (D3);
- group delays for the signals used, and an inter-system clock offset per system;
- a rank check (at least 3 + the number of systems satellites), convergence and residual checks;
- Selective Availability: the 15 corpus obs files from 1998 have SA on (until 2 May 2000), so
  their SPP scatter is reported with that note, not graded against modern files;
- Sagnac and relativity.

Outputs: the scatter against the header position and the IGS20 coordinates, DOPs, code
residuals per satellite, and the receiver clock. That clock series is what §5.3.1's steering
and drift need.

### 5.7 With precise products and station metadata (Q6)

- Code residuals against precise orbits and clocks, with the corrections listed explicitly:
  satellite and receiver PCO/PCV from ATX, receiver ARP, troposphere, relativity, Sagnac, and
  code biases (OSB). Squidy's correction chain is the starting point, but it is approximate:
  block-level PCOs, and see its `math.md` "not modelled" list. Each addition is listed.
- Comparison with the IGS20 coordinate solution and the site log (antenna height, types).
- **Multi-day trends:** a station health history, like squidy's calendar heatmap.

### 5.8 Outputs

- A JSON result with a versioned schema (`docs/QC_SCHEMA.md`), as §5.1 describes.
- A **self-contained offline HTML report**: plotly, with the library embedded. Everything is
  computed at full rate; series are thinned only for display.
- A one-screen text summary in the style of teqc.
- An overall grade, from a grading profile the user approves (D4). A metric that cannot be
  computed is shown as such, and its weight is never silently given to the others. The grade
  never hides the numbers behind it.

### 5.9 Validation of the QC numbers

- **Gates are numbers, frozen before the code.** Each Q milestone starts by writing its numeric
  gates (per metric, cadence and event class, including the expected outcomes for corrupt
  files) into `QC_METRICS.md`. The user signs them off before calibration starts.
- **Independent checks** in `tests/independent/qc/`, with their own frequency table and their own
  combination code, written from the specs. They import nothing from rinexqc, rinexcore or
  rinexconv; the existing meta-test covers the folder. This is the converter's round-32
  lesson: a checker that shares code with what it checks cannot see a shared mistake.
- **Hand-written fixtures** for every metric, with **negative controls** and **confounders**:
  an ionospheric gradient, a noisy low-elevation arc, a kinematic segment. They must stay
  within the frozen false-alarm limits for slips and clock jumps. The ionosphere and SNR metrics
  must still respond to the real variability in them.
- **Synthetic injection into real files.** Known events are written with rinexconv's writer:
  - slips, including **equal-cycle slips on both frequencies**;
  - gaps and epoch-tag jumps;
  - millisecond and smaller clock jumps, code-only and code-and-phase;
  - SNR drops, and multipath-like code errors.

  A truth ledger lists every field changed. The independent token comparator checks that each
  injected file differs from its source by exactly the ledger.

  Results are precision and recall per event class and size, with confidence intervals, and
  false alarms per satellite-hour. Real files hold real events, so false alarms on them are
  counted as **incremental** only. Absolute false-alarm rates come from fully synthetic
  observations built from SP3 by independent test code.
- **Calibrate, freeze, then validate on held-out files.**
  - The obs corpus is split by station, using the 4-character ID **from the file name** (MARKER
    NAME is free text). Every file from one station goes into the same half, whatever its day,
    cadence or encoding.
  - The split is stratified by cadence, version, receiver and constellations, with its coverage
    published (`tests/corpus/qc_split.json`). Q0a fixes the rule; the corpus additions of Q0b
    join by the same station rule, and the split is frozen only then, before any calibration.
  - Thresholds are tuned on the calibration half only, then frozen in `QC_METRICS.md` with the
    commit hash. Only then are the acceptance numbers computed on the held-out half.
  - Retuning after a held-out evaluation needs fresh validation files.
- **Corpus additions before Q3**, from CDDIS:
  - more 1 Hz data (today 25 files of 15 minutes, 6.25 h in all, every one from 2026 day 274);
  - more hourly files;
  - ionospherically active days (a storm day);
  - RINEX 2 files with Doppler;
  - a kinematic file.
- **Oracles (dev only, archived as digests):**
  - **teqc** is not available (the user has no copy): historical context only.
  - **Anubis** (G-Nut/Anubis), pinned by version and sha256, with its configuration archived.
    It is the oracle for observed counts, multipath and slips on the files it reads. For the
    other versions, the file is converted with rinexconv to one Anubis reads, and both are QC'd.
    To check when it is fetched: whether it reports slip epochs, and its multipath arc and mask
    rules.
  - **RTKLIB** for SPP (Q4).
  - Before any tolerance is compared, pairs, arcs, masks and statistics are matched to the
    oracle's; its eligibility rules are written per oracle in `QC_METRICS.md`.
  - A skipped oracle test says what it left unverified, and skips alone cannot meet acceptance.
- **Controlled numerical fixtures** for every computed quantity: orbits, az/el, SPP, SISRE and
  residuals. They are synthetic inputs with known answers: a broadcast record and an SP3 built
  from the same state with known offsets, or a station with known geometry. Sensitivity tests
  belong with them, each placed where it can fail:
  - **the orbit gate** (broadcast minus SP3 at a common epoch): each of these faults, injected
    alone, must fail it:
    - BDT taken as GPST;
    - a 3 h shift wrongly applied to RINEX `GLO` time tags (they are UTC hours);
    - the UTC-GPST leap seconds left out;
    - a wrong week rollover;
    - the BeiDou GEO rotation left out;
  - **geometric range and az/el**, checked against independent test code (Q2), and **SPP** (Q4):
    a missing Sagnac term, no signal travel time, or a 1 s time-tag offset on the observation
    side must each fail. A broadcast–SP3 comparison at a common epoch involves no travel time,
    so it cannot catch these.
- Every formula goes in `QC_METRICS.md` with a reference: Estey & Meertens 1999 (teqc);
  Vaclavovic & Dousa 2016 (Anubis); Blewitt 1990 (TurboEdit); Pi et al. 1997 (ROTI); IS-GPS-200,
  the Galileo OS SIS ICD, the BDS ICDs, the GLONASS ICD and the NavIC ICD for orbits; Montenbruck
  et al. for SISRE weights. Squidy's `math.md` is the template.

### 5.10 Decisions (the user's)

D1-D5 were put to the user in Q0a and answered on 2026-11-06; each answer is the proposal
(docs/DECISIONS.md, "Q0a"). D6 came up in Q0a and was answered the same day.

| # | Decision | Proposed | The user's answer |
|---|---|---|---|
| D1 | What QC does with a file the reader refuses as damaged | Compliance findings only; `--lenient` reads it, each metric keeping its own status plus a `lenient-read` flag | **As proposed** (2026-11-06) |
| D2 | Downloads from outside CDDIS and BKG: `igs20.atx`, `rcvr_ant.tab`, the IGS satellite metadata SINEX, site logs (files.igs.org), and fetching Anubis and RTKLIB | Fetch each once, record its version and sha256, as for the oracles | **As proposed**: once each, pinned (URL, version, date, sha256), gitignored, re-fetched only when the user asks (2026-11-06) |
| D3 | Galileo single-frequency ionosphere in SPP | Klobuchar as a reported approximation first; NeQuick-G later if wanted | **As proposed** (2026-11-06) |
| D4 | The grading profile (weights, which metrics count) | Drafted at Q5, shown with the report, approved by the user | **As proposed**: no grade before Q5 (2026-11-06) |
| D5 | SNR units when the header does not say | Relative values; dB-Hz only for receivers the user lists | **As proposed** (2026-11-06). In the corpus, 55 of the 185 RINEX 3/4 obs files have no `SIGNAL STRENGTH UNIT`, and RINEX 2 cannot state one |
| D6 | The ICD texts (IS-GPS-200, Galileo OS SIS ICD, BDS ICDs, GLONASS ICD, IS-QZSS, NavIC ICD) that nav QC (§5.4), healthy-nav completeness (§5.6) and SISRE cite: not in `specs/`, a download outside CDDIS and BKG, and `specs/` is read-only | Fetch each once from its operator, pinned as D2, into a new gitignored folder | **As proposed**, in Q0b, with the text extracted with page markers as `specs/text/` (2026-11-06) |

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

**Products rinexqc reads.** Each location is checked on the live archive when `cddis.py` is
built (Q0b), and recorded in `docs/CDDIS.md`:

| Product | Used for | Where |
|---|---|---|
| Merged broadcast nav: `BRDC00IGS_R_…_MN.rnx.gz` (3.x), `BRD400DLR_S_…_MN.rnx.gz` (4.02) | Orbits, nav QC | CDDIS `data/daily/YYYY/brdc/` |
| SP3 orbits: IGS final (GPS, GLONASS); MGEX multi-GNSS (for example `COD0MGXFIN`, `GFZ0MGXRAP`, `WUM0MGXFIN`) | SP3 orbits, SISRE | CDDIS `products/WWWW/` (older MGEX weeks: `products/mgex/WWWW/`, to verify) |
| Clock RINEX, 30 s | SISRE, residuals | as for SP3 |
| Observable-specific biases (bias SINEX) | SPP group delays, residuals | CDDIS `products/bias/` (to verify) |
| IGS20 coordinates (SINEX) | az/el station position, coordinate check | CDDIS `products/WWWW/` |
| `igs20.atx`, `rcvr_ant.tab`, the IGS satellite metadata SINEX, site logs | PCO/PCV, name checks, PRN → SVN → block, station metadata | files.igs.org: outside CDDIS and BKG, so the user decides (D2) |

---

## 7. Milestones

Each milestone ends with three things: tests green, a short entry in `docs/DECISIONS.md`,
and a review round with the reviewer skill (a Claude reviewer plus one Codex reviewer),
fixing what they find.

| # | Milestone | Done when |
|---|---|---|
| M0a | Environment check, repo, .gitignore, `rinexcore.cddis`, import-purity test, corpus verified against its manifest | `python -m rinexcore.cddis --selftest` passes (not built in M0a: moved to Q0b); `python tools/build_corpus.py --verify` passes |
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
| Q0a | QC documents and decisions: `docs/QC_METRICS.md` v0 (the semantics table, the frequency and pair table, each metric's definition and inputs, Q1's numeric gates), `docs/QC_SCHEMA.md` v0, the invariance table (§5.1), the station split's rule, decisions D1-D5 put to the user | Reviewed by the user and one reviewer; the user signs off Q1's gates |
| Q0b | QC groundwork: `rinexcore/cddis.py` (§6) with its selftest; the named nav fields in `rinexcore/spec/`; the GLONASS channel lookup moved to rinexcore; the corpus additions of §5.9; Anubis and RTKLIB fetched and pinned (D2); the split frozen once the additions are in (§5.9); the reader's own time and memory on the two budget files, and the resource targets set from them (§3.9) | Selftest and tests green; the downloads recorded with versions and sha256. Q1 starts when Q0a and Q0b are both done |
| Q1 | Obs QC from the file alone, part 1 (§5.3.1); nav QC from the file (§5.4); met QC (§5.5); JSON and text summary | On the whole corpus: (a) observed counts per (satellite, signal) equal the independent checker's, and Anubis's on the files it reads; (b) the enumerated physical metrics of §5.1 item 4 agree between each file and its rinexconv conversions to every write version, and every other difference is one `tests/expectations/qc_invariance.json` allows for a category in the conversion report; (c) injected gaps, epoch-tag jumps, clock jumps (millisecond and smaller; code-only and code-and-phase) and SNR drops meet the frozen targets on the held-out half, each injected file checked against its ledger; (d) every metric has a status; (e) the MIZU 1.6 GB day and the daily file meet the resource targets set in Q0b (§3.9) |
| Q2 | Orbits per message type, SP3, time scales, az/el, completeness, sky plots (§5.6) | Broadcast minus SP3 3D position per system and orbit class (the clock comparison is Q4's, under §5.4's conventions), within bounds frozen at Q2's start (broadcast orbits refer to the antenna phase centre, SP3 to the centre of mass: with `igs20.atx` (D2) the PCO is applied, otherwise the bounds carry a stated APC–CoM allowance per system); the sensitivity tests fail as they must; az/el against an independent implementation in the tests (pyerfa or astropy, in test code only); the controlled fixtures pass |
| Q3 | Combinations, slips, multipath, phase noise, ionosphere (§5.3.2) | Injected slips above each cadence's stated detection limit: precision and recall at the frozen targets on the held-out half, with confidence intervals; multipath RMS within max(2 cm, 10%) of Anubis once pairs, arcs and masks are matched; slip epochs within ±1 epoch of Anubis's where it reports them, slip counts as context; the confounder fixtures stay within the frozen false-alarm limits, while the ionosphere and SNR metrics still respond to their real variability (§5.9) |
| Q4 | SPP; nav QC with SISRE (§5.4, §5.6) | Controlled SPP and SISRE fixtures pass. RTKLIB SPP agrees on matched epochs and satellites with the same signals and corrections, within tolerances frozen at Q4's start. Published SISRE values are context only, never a gate |
| Q5 | HTML report, grade (§5.8) | The grading profile approved by the user (D4); the report reviewed by the user |
| Q6 | Precise products and station metadata (§5.7) | Controlled residual fixtures pass, with each correction term tested alone. Squidy's ORD is a sanity check only, since its corrections differ |

rinexconv was finished on 2026-11-06 (M0a-M8); QC starts with Q0a and Q0b. Each Q milestone ends as the M
milestones do, and starts by freezing its numeric gates (§5.9).

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
| The machine's Anaconda is older or newer | Checked at setup; the core stays stdlib; versions recorded (numpy 1.26 here: test any numpy code on both machines' versions) |
| CDDIS changes or goes down | BKG mirror, FTPS fallback, local cache, the corpus kept locally with its manifest |
| QC and its checks share a mistake | `tests/independent/qc/` with its own tables and code, the import meta-test, hand-written fixtures (§5.9) |
| QC claims more than the data show | Evidence apart from inference, hypotheses labelled, detection limits per cadence (§5.1, §5.3.2) |
| An oracle defines a metric differently | Pairs, arcs, masks and statistics matched before any tolerance; each oracle's rules written down (§5.9) |
| A 1.6 GB file exhausts memory | One pass with per-arc state; budgets measured on the MIZU day (§3.9) |
| Oracle licences: gfzrnx needs its own registration; teqc is retired | All oracles optional; the user downloads them; results archived once |

---

## 9. Reuse from the desktop projects

Copied into `reference/`. Read it and port ideas; don't import it. Details, with line
references, are in `reference/README.md`.

| From | Use for | Caveat |
|---|---|---|
| `cddis_https/sp3_downloader.py`, `config.py` | Earthdata auth class, hop-by-hop redirects, HTML check, credentials lookup | Imports `unlzw3` (from pip) and `backend.*` (not copied); whole-body downloads; no resume, cache manifest or checksum support |
| `cddis_https/cddis_browser.py` | — | Parses HTML listings with bs4. Use `*?list` instead |
| `squidy/` | `math.md` formulas; MP, ROTI, slip-detection lessons; pseudorange sanity gates; troposphere; FTPS fetcher | GPS only. Reads the whole file into memory. Seconds rounded to 1e-6 (can produce second = 1000000 µs). Probably mis-parses v2 event epochs (flag ≥ 2, `parse_rinex.py` ~123–141). Corrections approximate. Its slip detector gives up small slips on purpose (`math.md`), so its 2–25 slips per day is no gate |
| `customkf/rinex.py`, `broadcast.py` | Fail-closed streaming ideas; the GLONASS 4/5-line nav switch (~line 212); GPS LNAV equations | GPS only; a 10,000-epoch cap; GPS-time check only; rejects Hatanaka |
| `customkf/bkg_fetch.py` | The BKG URL layout (`obs/YYYY/DDD`, `BRDC/YYYY/DDD`, `products/<week>`) | Calls curl and CRX2RNX through `subprocess`; imports modules that weren't copied |
| `nav2sp3/` | Ephemeris selection rules (nearest TOE, IODE tie-break, health) | **GPS RINEX 2 nav only** |
| `converter_prototype/211to305rinex.py` | A list of pitfalls | GPS only, naive code map, no continuation lines, no event flags. **Not a base to build on** |
| `tools/rnxcmp-4.2.0/CRX2RNX.exe` | The dev oracle for CRX decoding (it supports CRINEX 3.1) | Dev-only. RNX2CRX.exe came later from the same GSI zip (`tools/oracles/ORACLES.md`). The `specs/hatanaka/` source is for reading, not building |
