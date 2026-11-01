# RINEX Convert & Analysis

- **rinexconv** converts RINEX observation, navigation and meteorological files between
  versions 2.10, 2.11, 3.00–3.05 and 4.00–4.02 (it also reads 2.00 and 2.01). Inputs may be
  plain, gzip, Unix compress (`.Z`), bzip2, single-file zip, and Hatanaka (Compact RINEX
  1.0/3.0/3.1) in any combination.
- **rinexqc** (quality analysis) is not built yet.

The plan is [PLAN.md](PLAN.md); decisions and open questions are in
[docs/DECISIONS.md](docs/DECISIONS.md).

## Using rinexconv

Python 3.10+ with the standard library only. Run from the repository root (no install step):

```
python -m rinexconv INPUT [INPUT ...] --to 3.05 --out DIR
```

Useful options:

| Option | What it does |
|---|---|
| `--to V` | target version: 2.10, 2.11, 3.00–3.05, 4.00–4.02 |
| `--crx` / `--no-crx` | write observation files Hatanaka-compressed or plain (default: as the input). Exceptions, each written plain with a warning (nothing is lost): Compact RINEX 1.0 cannot hold a RINEX 2 cycle-slip epoch (event flag 6) whose records span two lines (more than 5 obs types) or whose satellite list runs past 12, so such a file is written as plain RINEX 2 (`.YYo`), with warning `OBS.CRX1.EVENT-PLAIN`. Likewise, in any version, a cycle-slip record line that RNX2CRX/CRX2RNX would misread as an observation-type count (it is shorter than column 79 and an earlier line left that label in their buffer) makes the file plain RINEX, with warning `OBS.CRX.EVENT-PLAIN`; and so does a RINEX 4.02 picosecond epoch field that stops part-way through the file (CRINEX 3.1 differences it, so CRX2RNX would repeat the last value), with warning `OBS.CRX.PICOSEC-PLAIN` |
| `--gz` / `--Z` / `--no-compress` | output compression (default: as the input) |
| `--nav FILE` / `--glo-fcn FILE` | GLONASS frequency channels for RINEX 3.02+ output from RINEX 2/3.00/3.01 input (a nav file, a RINEX ≥ 3.02 obs file, or `R01 1` lines). Without either, a same-day GLONASS/mixed nav file next to the input is used if there is one (`--no-auto-nav` turns that off) |
| `--assume-phase-aligned` | assert aligned phases when converting data of unknown phase alignment (RINEX 2, 3.00) to RINEX 4 |
| `--drop-unresolvable` | drop a system whose mandatory target values cannot be found, instead of refusing |
| `--leap-seconds N` | GPS−UTC for RINEX 4 nav output when the source has none and the date is outside the built-in table |
| `--merge` | merge several navigation inputs into one output; `--dedupe` removes exact duplicates |
| `--lenient` / `--strict` | repair data-level damage where possible / refuse anything off spec |
| `--report DIR` | write a JSON conversion report per input |
| `--keep-lli-bit2` | carry LLI bit 2 even where its meaning changes between versions |
| `--approx-position X Y Z` | APPROX POSITION XYZ (WGS84, m) for RINEX 2 output from a RINEX 3/4 file that has none (moving platforms; RINEX 2 makes it mandatory, so without it the conversion refuses) |
| `--approx-position-zero` | write teqc's `0 0 0` placeholder there instead; reported as an assumption and a warning, since zeros are not a position (`--approx-position` wins if both are given) |
| `--qzss-ion-area WIDE\|JAPN` | area of the QZSS CNVX ION records of a 4.00/4.01 nav file, which 4.02 requires; without it those records are dropped and reported |

Every conversion ends in one outcome, which is also the exit code:

| Outcome | Exit | Meaning |
|---|---|---|
| converted | 0 | complete output; the report lists every loss, assumption and repair |
| converted-with-removal | 1 | `--drop-unresolvable` removed a system |
| invocation-error / io-error | 2 / 5 | bad arguments, unreadable input, unwritable output |
| refused-missing-information | 3 | the target needs a value no source gives (the message names it) |
| refused-corrupt | 4 | the input is damaged (file, line, column, rule) |
| refused-not-representable | 6 | the target version cannot hold any of the input's data |
| internal-error | 7 | a bug: please report the file |

**Memory and speed.** A file is held in memory once as input and once as output, so a
conversion needs about twice the file's decompressed size in free RAM. Outputs above 64 MB are
assembled through a temporary file (in the system temp folder; deleted afterwards). The
largest file tested is a 24 h, 1 Hz, seven-system day (MIZU00JPN, 2026-290): 1.6 GB of
RINEX 3.05, 150 MB as `.crx.gz`. On an 8 GB laptop (i5-12450H) each conversion took 3.5 to
8 minutes, with a peak of 2.5 to 3.7 GB (details: docs/DECISIONS.md, "24 h 1 Hz test").

## Tests

```
python -m pytest -q -p no:cacheprovider tests/unit
python tools/corpus_run.py --kinds obs,nav,met --jobs 4      # all corpus files x all versions
```

The independent checks (`tests/independent/`) count every loss a report claims. To test the
checks themselves, run the unit suite with `RINEX_MUTATION_AUDIT` set to a file path
(PowerShell: `$env:RINEX_MUTATION_AUDIT = "audit.jsonl"`; bash: `RINEX_MUTATION_AUDIT=audit.jsonl
python -m pytest …`). Every clean comparison is then repeated with each claim deleted and with
its count raised by one; each attempt is written to the file as a JSON line, and one with
`"caught": false` is a loss the checks do not count exactly (`tests/conftest.py`). It takes
about 50% longer than a normal run. `python tools/mutation_audit.py <results.jsonl> <out.json>`
does the same on corpus files: it takes the rows of a corpus run that have losses (a few per
kind of loss, smallest files first) and reports any mutation the checks accept.

`tests/unit/test_generated.py` converts seeded random observation files
(`tests/independent/generate.py`: random version, systems and codes, events, cycle slips,
clock offsets, picoseconds, scale factors, wrong header counts) to every version, plain and
Compact RINEX, and checks each result as above, with CRX2RNX when it is present. The same file
also converts generated met files, and nav files cut at random from the corpus (record
subsets, header corrections dropped, `--merge`/`--dedupe`; skipped without `data/corpus`). It
runs 30 seeds by default (90 for met); set `RINEX_GEN_SEEDS` (and `RINEX_GEN_FIRST`) for more,
e.g. 3000 seeds take about 20 minutes.

## Credits

The Hatanaka codec (`rinexcore/io/hatanaka.py`) is a Python port of RNXCMP 4.2.0 by the
Geospatial Information Authority of Japan. As its licence asks: Hatanaka, Y. (2008), *A
Compression Format and Tools for GNSS Observation Data*, Bulletin of the Geospatial
Information Authority of Japan, 55, 21–30.

## What's in here

| Folder | Contents |
|---|---|
| `rinexcore/` | shared core: codecs, spec tables, readers and writers |
| `rinexconv/` | conversion rules, engine, report, CLI |
| `tests/` | unit tests, hand-written and spec-example fixtures, the independent comparator, the pre-authorised loss table |
| `tools/` | corpus builder and harness, Hatanaka check, companion fetcher |
| `specs/` | the official RINEX documents (2.10–4.02) and text extractions |
| `data/corpus/` | 480 real CDDIS files (not in git) |
| `docs/` | CDDIS access, Hatanaka grammar, spec tables, decisions, environment |
