# CLAUDE.md — RINEX Convert & Analysis

Guide for Claude Code sessions on this project. It lives on the user's **desktop** at
`E:\pythontests\RINEXConvert_Analysis` (since 2026-11-02; the first build happened on the laptop)
and on GitHub as `bwh5318/RinexConverter` (public, MIT for the user's code; branch `main`).

## What this is

Two Python tools that share one RINEX core. The plan is [PLAN.md](PLAN.md) (rev. 2, amended
since: newer decisions in `docs/DECISIONS.md` win over the plan where they differ).

1. **rinexconv**: converts RINEX obs, nav and met files between 2.10/2.11, 3.00–3.05 and
   4.00–4.02 (reading 2.00/2.01/2.12 too), plain, gz, .Z, bz2, zip, tar and Hatanaka 1.0/3.0/3.1.
   PLAN §1 turns "converts correctly every time" into a contract every test enforces. **Read §1
   before changing any conversion code.**
2. **rinexqc**: measures RINEX quality as completely as the data allows (PLAN §5).

**Status (2026-11-03):**
- **rinexconv 1.0 is done** (milestones M0a–M8). 43 review rounds (Sonnet, Opus, Codex Sol 6.1 and
  Astra) ended with every reviewer at 9/10 and confident (`docs/REVIEW_LOG.md`). Unit suite 1,060+
  green; full corpus run: 5,280 conversions, 0 crashes, token problems, idempotence failures or
  loss-table violations; the PLAN §4 acceptance, including the two outcome checks
  (`tools/outcome_check.py`), is met.
- **Speed work (2026-11-06):** conversions 1.7-1.9x faster with not one output, report or refusal byte
  changed (`tools/digest_outputs.py`: 13,915 corpus conversions identical to the original code); Codex
  Sol 6.1 xhigh 9/10, confident. Suite 1,108 passed. A change to a fast path must keep its fallback and
  pass a `--compare` of two digest runs (docs/DECISIONS.md, "speed work").
- **rinexqc is not started.** Its plan is PLAN.md revision 4 (§3.9, §5, Q milestones; reviewed by
  Codex Sol 6.1 xhigh and Opus, 2026-11-06). Next: **Q0a** (`docs/QC_METRICS.md` v0, the schema, the
  invariance table, Q1's gates, and the user's decisions D1-D5 of PLAN §5.10) and **Q0b**
  (`rinexcore/cddis.py`, corpus additions, Anubis and RTKLIB), then Q1. The working Earthdata client
  is in `tools/build_corpus.py`.

## Non-negotiable rules

1. **Python plus the packages Anaconda ships. No `pip install`, no `conda install`, ever**,
   not even "just to try". Run `conda list` to check: a package with channel `pypi` is
   **not** allowed, even if it's installed (pypdf and pypdfium2 are, and must not be used).
   If you think you need something Anaconda lacks, stop and ask the user. Which module may
   import what is set out in PLAN §0: the core is stdlib only; `requests` only in
   `rinexcore/cddis.py` and `tools/`; numpy, scipy, matplotlib, plotly and jinja2 only in `rinexqc`
   (which never imports rinexconv: PLAN §3.9). An AST
   import-purity test enforces this.
2. **Outside programs are dev-only oracles.** CRX2RNX, RNX2CRX, gfzrnx, RTKLIB, teqc and Anubis
   may be run by tests to cross-check, and never by shipped code (no `subprocess` in
   `rinexcore`, `rinexconv` or `rinexqc`). A test that needs a missing oracle is **skipped**,
   not failed. Oracle results are archived as digests and hashes (PLAN §1.5c).
3. **The CDDIS login file is secret.** It sits beside the repository at
   `..\RINEXConvert_Analysis_secrets\cddislogin.txt`. Never print, log, copy, commit or send it
   anywhere except `urs.earthdata.nasa.gov`. Never put it, or its contents, in a Codex brief.
4. **Never commit data.** `data/`, `reference/` (it contains the user's e-mail address),
   `.codex-agents/` and oracle binaries are gitignored. The repository is public: check what a
   commit adds before pushing.
5. **Don't edit `reference/` or `specs/`.** They're read-only inputs.
6. **Never weaken the contract to make a test pass.** Never add a loss or a rule to
   `allowed_losses.json` to hide a bug. Every rule and every spec-table row cites a spec
   version and page. If the spec and the oracles disagree, follow PLAN §1 clause 10: show
   it, and let the user decide.
7. **Bytes, not text.** Read and write RINEX as bytes and decode as latin-1. Never use
   text mode for RINEX files: on Windows it rewrites line endings.
8. **Independent checks stay independent.** `tests/independent/` must not import rinexcore or
   rinexconv (`tests/unit/test_independent_meta.py`); when a conversion rule changes, the checker
   gets its own spec-derived code for it, never a copy of the converter's.

## Map of this folder

| Path | What |
|---|---|
| `PLAN.md` | The plan: contract (§1), scope (§2), architecture (§3), tests (§4), QC (§5), CDDIS (§6), milestones (§7), risks (§8), reuse (§9) |
| `docs/DECISIONS.md` | **Every decision, newest first**, with spec citations, and which ones the user confirmed. Read the newest entries first |
| `docs/REVIEW_LOG.md` | All review rounds and scores |
| `docs/CONVERSION_MATRIX.md` | Generated (`tools/build_matrix.py`) from `tests/expectations/allowed_losses.json` |
| `docs/HATANAKA.md` | The Compact RINEX grammar, from `crx2rnx.c` |
| `docs/PHASE_ALIGNMENT.md` | Every phase-shift table 3.01–4.02, PDF-checked, behind `--align-phases` |
| `docs/SPEC_TABLES.md`, `docs/CDDIS.md`, `docs/ENVIRONMENT.md` | Spec-table notes; how to download from CDDIS; the machines, packages and **performance budgets** |
| `rinexcore/` | Readers/writers (`obs.py`, `nav.py`, `met.py`, `header.py`), spec tables (`spec/`), codecs (`io/`: hatanaka, compress, archive, spool), validator (`validate.py`) |
| `rinexconv/` | Rules (`obsconv.py`, `codemap.py`, `navconv.py`, `navcorr.py`, `leap.py`, `metconv.py`), `engine.py` (`convert_data` and the transactional writer), `cli.py`, `report.py` |
| `tests/unit/` | pytest suite: `python -m pytest -q -p no:cacheprovider tests/unit` (about 3-4 min) |
| `tests/independent/` | The independent checks: token comparators, header checker, field-by-name nav checker (`navfields.py`), loss table check, generators, and their own tables (JSON) |
| `tests/expectations/` | `allowed_losses.json` (losses each cell may report, cited) and `code_validity.json` |
| `tools/corpus_run.py` | Every corpus file to every version with all checks: `python tools/corpus_run.py --kinds obs,nav,met --jobs 12 --out data/out/<name>` (45-80 min); prints throughput against the budgets |
| `tools/outcome_check.py` | The two PLAN §4 outcome checks (no companion -> refused-missing-information; --drop-unresolvable -> converted-with-removal) |
| `tools/build_corpus.py`, `tools/check_hatanaka.py`, `tools/fetch_*.py` | Corpus builder/verifier with the Earthdata client; Hatanaka oracle comparison; companion and high-rate fetchers |
| `specs/*.pdf`, `specs/text/*.txt` | Official RINEX documents 2.10–4.02 and text extractions with `===== page N =====` markers. Grep the text; check important tables against the PDF |
| `specs/hatanaka/src/` | RNXCMP 4.2.0 source: the authority for the Hatanaka grammar (GSI licence: cite Hatanaka 2008) |
| `reference/` | Read-only code from the desktop projects (gitignored). Read `reference/README.md` first |
| `data/corpus/<obs\|nav\|met>/v<version>/` | 480 real CDDIS files (gitignored); manifest `tests/corpus/manifest.json` |

## How to work

- **Milestones in order** (PLAN §7). Each one:
  1. Write the tests first, from the spec, not from your code.
  2. Implement.
  3. Run the unit suite.
  4. Write a short entry in `docs/DECISIONS.md`.
  5. Run a review round (below).
  6. Commit, with the user's go-ahead; push to `origin main` only when the user asks.
- **Specs first.** Before implementing a record type, grep `specs/text/` for its label in
  *every* version, and write the table rows with page citations.
- **Run on the corpus early and often.** Real files break the spec in ways the spec
  examples don't. A change to conversion code is finished only after a full corpus run on it.
- **Reviews.** Run the reviewer skill at the end of each milestone. The user's usual choice:
  Claude agents (Opus lenses) plus one Codex reviewer (Sol 6.1 high, or Astra xhigh when they say
  so). Codex usage is limited: one Codex reviewer per round unless the user asks for more; check
  `python E:/pythontests/call_codex/codex_agent.py usage` first and say so at 80% or more.
- **Performance:** measure with `cProfile` (stdlib) on the largest corpus files before
  optimising. numba is allowed only as an optional accelerator with a pure-Python fallback.
- **Running code:** packages sit at the repository root, so run `python -m rinexconv …`
  from there. There's no install step, and never use `pip install -e`. Set
  `PYTHONDONTWRITEBYTECODE=1` in scripts and reviewer briefs.

## Oracles

Each one lives in `tools/oracles/<name>/` (gitignored) and is recorded in
`tools/oracles/ORACLES.md` (committed): name, version, source URL, date, sha256. Tests find
them through a `conftest.py` helper that skips when one is missing.

| Oracle | Status | Get it |
|---|---|---|
| CRX2RNX 4.2.0 | Here (`reference/tools/rnxcmp-4.2.0/`, `tools/oracles/rnxcmp/`) | — |
| RNX2CRX 4.2.0 | Here (`tools/oracles/rnxcmp/`); our encoder matches it byte for byte on the corpus | — |
| RTKLIB (`rnx2rtkp`, `convbin`) | Not here; the user said: when rinexqc starts (needed for Q4) | rtklibexplorer "demo5" Windows release on GitHub (ask first) |
| Anubis | Not here; the user said: when rinexqc starts (needed for Q3) | G-Nut/Anubis from GOP (ask first) |
| gfzrnx | Not here ("not now": it needs the user's licence) | The user downloads it from GFZ |
| teqc | None (retired; the user has no copy) | — |

## CDDIS in one screen

Full details are in `docs/CDDIS.md`.

- **Base URL:** `https://cddis.nasa.gov/archive/gnss/`. NASA Earthdata login, with the
  credentials sent only to `urs.earthdata.nasa.gov`, redirects followed hop by hop.
- **List a directory:** add `*?list` → `name size` lines (files only).
- **Daily obs:** `data/daily/YYYY/DDD/YYd/` (Hatanaka: v3/v4 `…_01D_30S_MO.crx.gz` and v2
  `ssssDDD0.YYd.gz`) and `YYo/` (plain).
- **Nav:** per station in `YYp/` (mixed), `YYn/ YYg/ YYl/ YYf/ YYq/ YYh/ YYi/` (by system);
  merged in `data/daily/YYYY/brdc/`. There: `brdcDDD0.YYn.gz` (GPS v2.00),
  `brdcDDD0.YYg.gz` (GLONASS **v2.01**), `BRDC00IGS_R_…_MN.rnx.gz` (v3), and
  `BRD400DLR_S_…_MN.rnx.gz` (**v4.02**).
- **Met:** `YYm/`. **High-rate:** `data/highrate/YYYY/DDD/YYd/HH/` (15-min, 1 Hz).
  **Hourly:** `data/hourly/YYYY/DDD/HH/`. **Orbits and clocks:** `products/WWWW/`.
- **Compression:** `.Z` before about 2021, `.gz` after; both coexist.
- **Fallbacks:** anonymous FTPS on `gdc.cddis.eosdis.nasa.gov`; the BKG mirror
  `https://igs.bkg.bund.de/root_ftp/IGS/` (no login).

## RINEX gotchas (each has fixtures; details and citations in docs/DECISIONS.md)

**Version and type fields**
- The version field is written `2`, `2.1`, `2.10` or `3.05`: parse it as a number.
- RINEX 2 SBAS nav normally has type `H`, but one real 2.11 file uses `S`. RINEX 2 files
  can contain C, J and I satellites (non-standard).

**Compression**
- Hatanaka: CRINEX 1.0 for RINEX 2, 3.0 for 3.x–4.01, **3.1** for 4.02+ (picosecond record).
  `&` is arc init in `N&value` fields; an empty field means missing. RNX2CRX copies event
  lines (flag > 1) verbatim.

**Fields whose meaning changes between versions** (the round-32 lesson: a comparator that
matches fields by position cannot see these, hence `tests/independent/navfields.py`)
- **GLONASS message frame time:** seconds of the UTC day in RINEX 2, seconds of the UTC week in
  3.x/4.x (from RINEX 2: counted from Toc's week, may be negative or ≥ 604800; user's choice).
  **SBAS:** seconds of day in 2.10, GPS seconds of the week from 2.11.
- **RINEX 2.00 GLONASS nav** stores −GammaN and +TauC; 2.01 and later +GammaN and −TauC.
- **QZSS Klobuchar area:** 4.00/4.01 ION region code (0/blank wide, 1 Japan) ↔ 4.02 `WIDE`/`JAPN`;
  written on 4.02 LNAV too, as DLR does (user's choice).
- **Reference weeks:** truncated (mod 256/1024) or system-based (NavIC/Galileo +1024, BDS −1356)
  weeks in header corrections are repaired and reported.
- **Spare vs real fields:** GEO IODN (2.11+, spare in 2.10), QZSS L2P flag (3.03+, spare in 3.02);
  RINEX 4 spares are left blank.
- **BeiDou B1I** is `C1I` in 3.02 and `C2I` from 3.03. **GLONASS nav** has 4 orbit lines up to
  3.04, 5 from 3.05. **Nav exponent letter:** `D` up to 4.00, `E` from 4.01.
- **Layout:** RINEX 2: one obs list, 5 obs per line, 12 satellites per epoch line, 9 types per
  header line; RINEX 3/4: per-system lists, one line per satellite, 13 types per header line.
- **Precision:** v2 `DELTA-UTC` D19.12 vs v3 `TIME SYSTEM CORR` D17.10/D16.9; receiver clock F12.9
  (v2) vs F15.12 (v3).

**Semantics**
- **Event flags 2–5 may all carry header records** (RINEX 2.10: "Header records now allowed after
  all epoch flags >1"): type lists, scale factors and WAVELENGTH FACT apply from any of them.
  Event epochs can carry a receiver clock offset.
- `WAVELENGTH FACT L1/2` (v2) changes the meaning of LLI bit 1; in v3 that bit means half-cycle
  ambiguity.
- **Phase alignment** (PLAN §3.3, docs/PHASE_ALIGNMENT.md): 3.00 unaligned; 3.01 records applied
  shifts (blank ambiguous); **3.02 onwards** has three record states (zeros = aligned at source,
  code-only = reference signals only, fully blank = unknown); 4.x aligned by definition. By
  default phase values never change; unknown alignment to 4.x needs `--assume-phase-aligned`.
  `--align-phases` works for 3.02–3.05 targets (and un-aligning to 3.00) only where the target's
  table prints a number; RINEX 2 inputs must state signal attributes with `--overrides`.
- **Missing observations** may be `0.0` or blank; a `0.000` is never a measurement. A phase past
  F14.3 is clipped by ±10⁹ with LLI bit 0.
- **Galileo nav data-source bitmask:** carried verbatim; the v4 I/NAV or F/NAV type derives from it.
- GLONASS-only RINEX 2 obs files are in UTC: never shift them by leap seconds.
- GLONASS frequency channels come from nav files; `GLONASS COD/PHS/BIS` only from the receiver
  or site log. Never invent either.

**Real-file damage**
- Header counts (`# OF SATELLITES`, `PRN / # OF OBS`, `TIME OF LAST OBS`, `INTERVAL`) are often
  wrong: repaired and reported by default.
- Some real 3.x files store GLONASS tk on the day basis (BRDC00IGS 2017, BOR100POL, CKIS00COK):
  carried with a warning, refused under `--strict`, repaired under `--lenient`.
- The corpus has exactly 72 refused (file, target) cells by design (PLAN §4 acceptance): three
  damaged files (mate1800.03m, DARW00AUS 3.03 met, BRDX00DLR "4.00") and single-system nav files
  going to versions without that system. `yell1800.10d.Z` on CDDIS decodes to nothing.

## Stop and ask the user when

- you think you need a package Anaconda doesn't ship, or an outside program at runtime;
- a conversion default is a policy choice, not a spec fact (for example, the default
  attribute for a v2 `L2`);
- an oracle disagrees with the spec, or with us, and you can't prove which is right;
- you'd download anything except CDDIS/BKG data and the oracles listed above;
- you'd delete corpus files, or spend Codex usage beyond one reviewer per round;
- you'd push, or change what is public on GitHub.

## About the user

The user works with GNSS data. On the desktop they run an SP3 orbit-comparison monitor
(`E:/pythontests/autocomparesp3`), a GPS POD Kalman-filter project and the squidy QC dashboard.
Their code style favours stdlib-first, fail-closed, well-documented Python with formulas written
up (see `reference/squidy/math.md`). Give answers in plain language, keep observation and
hypothesis apart, and say clearly what's verified and what isn't.
