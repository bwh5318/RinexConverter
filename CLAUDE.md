# CLAUDE.md — RINEX Convert & Analysis

This guide is for Claude Code on the user's **laptop**. It was written on 2026-10-30 by a
Claude session on the user's desktop. That session wrote the plan, had it reviewed, built
the test corpus, and copied what you need from the desktop's other projects onto this
drive. The desktop's `E:\` drive does not exist on the laptop: everything you need is here.

## What you're building

Two Python tools that share one RINEX core. The full plan is [PLAN.md](PLAN.md), revision 2.
It was reviewed by Sonnet and Codex Astra; see `docs/REVIEW_LOG.md` for what changed, and
the one follow-up check that is still owed.

1. **rinexconv**: converts RINEX obs, nav and met files between every common version
   (2.10/2.11, 3.00–3.05, 4.00–4.02, reading 2.00/2.01 too), "100% of the time". PLAN §1
   turns "100%" into a contract that every test enforces. **Read §1 before writing any
   code.**
2. **rinexqc**: measures RINEX quality as completely as the data allows (PLAN §5).

**Status at hand-off:** nothing is built yet. The plan, the specs, the reference code and
a 480-file real-data corpus are ready. Start at milestone **M0a** (PLAN §7). Its first
step is the checklist below.

## Non-negotiable rules

1. **Python plus the packages Anaconda ships. No `pip install`, no `conda install`, ever**,
   not even "just to try". Run `conda list` to check: a package with channel `pypi` is
   **not** allowed, even if it's installed. If you think you need something Anaconda
   lacks, stop and ask the user. Which module may import what is set out in PLAN §0
   (summary: the core is stdlib only; `requests` only in `rinexcore/cddis.py` and
   `tools/`; numpy, scipy and plotly only in `rinexqc`). An AST import-purity test
   enforces this.
2. **Outside programs are dev-only oracles.** CRX2RNX, gfzrnx, RTKLIB, teqc and Anubis may
   be run by tests to cross-check, and never by shipped code (no `subprocess` in
   `rinexcore`, `rinexconv` or `rinexqc`). A test that needs a missing oracle is
   **skipped**, not failed. Oracle results are archived as digests and hashes (PLAN §1.5c).
3. **The CDDIS login file is secret.** Never print, log, copy, commit or send it anywhere
   except `urs.earthdata.nasa.gov`. Never put it, or its path's contents, in a Codex brief.
4. **Never commit data.** `data/`, `reference/` (it contains the user's e-mail address)
   and oracle binaries are gitignored.
5. **Don't edit `reference/` or `specs/`.** They're read-only inputs.
6. **Never weaken the contract to make a test pass.** Never add a loss or a rule to
   `allowed_losses.json` to hide a bug. Every rule and every spec-table row cites a spec
   version and page. If the spec and the oracles disagree, follow PLAN §1 clause 10: show
   it, and let the user decide.
7. **Bytes, not text.** Read and write RINEX as bytes and decode as latin-1. Never use
   text mode for RINEX files: on Windows it rewrites line endings.

## First session on the laptop

Work through this with the user. Tick each item in `docs/ENVIRONMENT.md` as you go.

1. **Where things are.** The user copies `F:\RINEXConvert_Analysis` to the laptop (suggest
   `C:\dev\RINEXConvert_Analysis`: not OneDrive-synced, no spaces in the path). They copy
   `F:\RINEXConvert_Analysis_secrets\` to sit **beside** it
   (`C:\dev\RINEXConvert_Analysis_secrets\cddislogin.txt`), where the code looks for it. If
   they'd rather keep it elsewhere, set `RINEX_CDDIS_LOGIN` to its path. Then restrict the
   file to the user:
   `icacls C:\dev\RINEXConvert_Analysis_secrets\cddislogin.txt /inheritance:r /grant:r "%USERNAME%:F"`.
2. **Skills.** If the user hasn't yet, have them unzip `F:\Laptop-Setup.zip` and run
   `SETUP.bat`. It installs the **codex** and **reviewer** skills and the Codex helper
   script, which the reviewer loop needs. It also installs **sp3-report**, which belongs
   to a desktop-only project (`E:/pythontests/autocomparesp3`): ignore it here. Codex
   needs the Codex app installed and signed in. After setup, the user restarts the Claude
   app.
3. **Python.** Run `where python` (it must be the Anaconda one), `python --version` and
   `conda list`. Save the `conda list` output to `docs/ENVIRONMENT.md`, with the laptop's
   CPU, RAM and disk. Don't use language features newer than this Python. If it's older
   than 3.10, tell the user.
4. **Git.** `git init`; write `.gitignore` (template below); make a first commit with the
   user's go-ahead.
5. **CDDIS.** `python tools/build_corpus.py --check-login` should print `Login OK …`.
6. **Corpus.** `python tools/build_corpus.py --verify` should report `480/480 corpus files
   OK`. If `data/` wasn't copied, re-running `python tools/build_corpus.py` rebuilds it
   (about 20 minutes, 590 MB). Because CDDIS changes over time, a rebuild picks slightly
   different files; keep the new manifest.
7. **Oracles (optional; ask the user).** See "Oracles" below.

`.gitignore` template:

```
data/
reference/
.codex-agents/
tools/oracles/*/
__pycache__/
*.pyc
*.part
cddislogin.txt
specs/hatanaka/*.tar.gz
```

## Map of this folder

| Path | What |
|---|---|
| `PLAN.md` | The plan: contract (§1), scope (§2), architecture (§3), tests (§4), QC (§5), CDDIS (§6), milestones (§7), risks (§8), reuse (§9) |
| `docs/CDDIS.md` | **How to download from CDDIS**: the login file, auth, `*?list` listings, every verified directory, a minimal client, fallbacks |
| `specs/*.pdf` | Official RINEX documents: 2.10, 2.11, 3.00–3.05, 4.00–4.02 (4.02 is dated 1 Sep 2025, the newest) |
| `specs/text/*.txt` | **Plain-text extractions of every spec, with `===== page N =====` markers.** Grep these; Claude Code can't render PDFs without poppler. Table alignment is imperfect, so check important tables against the PDF page |
| `specs/hatanaka/src/` | RNXCMP 4.2.0 source (`crx2rnx.c`, `rnx2crx.c`, `docs/RNXCMP.txt`): the authority for the Hatanaka grammar |
| `reference/` | Read-only code from the desktop projects. **Read `reference/README.md` first**: it says what each item is good for and where it's wrong |
| `reference/tools/rnxcmp-4.2.0/CRX2RNX.exe` | The CRX decode oracle (dev-only) |
| `tools/build_corpus.py` | Builds and verifies the corpus. Has a working Earthdata client and a pure-Python `.Z` decoder (`unlzw`, byte-identical to `unlzw3`) |
| `data/corpus/<obs\|nav\|met>/v<version>/` | 480 real CDDIS files, kept exactly as served. Summary in `data/corpus/CORPUS.md`; every header screened is in `data/corpus/screen.json` |
| `tests/corpus/manifest.json` | sha256 and header facts (receiver, systems, interval, CRX version, raw version string) for each corpus file |

## How to work

- **Milestones in order** (PLAN §7). Each one:
  1. Write the tests first, from the spec, not from your code.
  2. Implement.
  3. Run `python -m pytest -q`.
  4. Write a short entry in `docs/DECISIONS.md`.
  5. Run a review round (below).
  6. Commit, with the user's go-ahead.
- **Specs first.** Before implementing a record type, grep `specs/text/` for its label in
  *every* version, and write the table rows with page citations. For example,
  `grep -n "SYS / PHASE SHIFT" specs/text/*.txt` shows it strongly deprecated in 4.02.
- **Hatanaka:** write `docs/HATANAKA.md` (the grammar) from `crx2rnx.c` before coding the
  codec. The GSI licence requires citing Hatanaka, Y. (2008), *A Compression Format and
  Tools for GNSS Observation Data*, Bull. GSI 55, 21–30, in the codec docstring and the
  README.
- **Run on the corpus early and often.** Real files break the spec in ways the spec
  examples don't. Track pass counts per bucket in `docs/DECISIONS.md`.
- **Reviews.** Run the reviewer skill at the end of each milestone, for example "have
  opus and astra review M2". Codex usage is limited: one Codex reviewer per round unless
  the user asks for more.
- **Performance:** measure with `cProfile` (stdlib) on the largest corpus files before
  optimising. numba is allowed only as an optional accelerator with a pure-Python fallback.
- **Running code:** packages sit at the repository root, so run `python -m rinexconv …`
  from there. There's no install step, and never use `pip install -e`.

## Oracles

Put each one in `tools/oracles/<name>/` (gitignored), and record it in
`tools/oracles/ORACLES.md` (committed): name, version, source URL, date, sha256. Tests find
them through a `conftest.py` helper that skips when one is missing.

| Oracle | Status | Get it |
|---|---|---|
| CRX2RNX 4.2.0 | **Already here** (`reference/tools/rnxcmp-4.2.0/`) | — |
| RNX2CRX 4.2.0 | Not here | The same GSI zip as CRX2RNX: `https://terras.gsi.go.jp/ja/crx2rnx/RNXCMP_4.2.0_Windows_mingw_64bit.zip` (ask first) |
| gfzrnx | Not here | The user must download it from GFZ themselves, since it needs a licence |
| RTKLIB (`rnx2rtkp`, `convbin`) | Not here | rtklibexplorer "demo5" Windows release on GitHub (ask first). RINEX 4 support unconfirmed |
| teqc | Not here | Retired by EarthScope/UNAVCO; only if the user has a copy |
| Anubis | Not here | G-Nut/Anubis from GOP (ask first) |

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

## RINEX gotchas that are already known

These were found in the corpus or the specs on 2026-10-30. Each deserves a fixture.

**Version and type fields**

- The version field is written as `2`, `2.1`, `2.10` or `3.05`: parse it as a number. The
  raw string is kept in the manifest as `version_str`.
- RINEX 2 SBAS nav normally has type `H`, but one real 2.11 file uses `S`. RINEX 2 files
  can contain C, J and I satellites (non-standard).

**Compression**

- **Hatanaka versions:** CRINEX 1.0 for RINEX 2, 3.0 for 3.x–4.01, **3.1** for 4.02+
  (it adds a picosecond record). `&` is arc init in `N&value` fields, "becomes a blank"
  in text diffs, and epoch re-init; an **empty field means missing**.

**Changes between versions**

- **BeiDou B1I** is `C1I` in 3.02 and `C2I` from 3.03 on.
- **GLONASS nav records** have 4 orbit lines up to 3.04, and **5 from 3.05**.
- **RINEX 4.02** adds an optional **picosecond** extension to the epoch seconds field,
  and strongly deprecates `SYS / PHASE SHIFT`.
- **Layout:**
  - RINEX 2 has one global obs list, 5 observations per line, 12 satellites per epoch
    line, and 9 obs types per header line.
  - RINEX 3/4 has per-system lists, one unwrapped line per satellite, and 13 obs types per
    header line.
- **Precision:** v2 `DELTA-UTC` is D19.12; v3 `TIME SYSTEM CORR` a0/a1 are D17.10/D16.9.
  The receiver clock is F12.9 in v2 and F15.12 in v3.
- **Nav exponent letter:** `D19.12` up to 4.00, **`E19.12` from 4.01**. In 4.01+, `D` is
  "strongly deprecated", exponents are two zero-padded digits, and one letter is used per
  file. 4.02 also deprecates the SSI flag in favour of `Sna` observations.

**Semantics**

- **Event flags 2–5** put header lines inside the data, and flag 4 can redefine obs types
  and wavelength factors mid-file.
- `WAVELENGTH FACT L1/2` (v2) changes the meaning of LLI bit 1. In v3, that bit means
  half-cycle ambiguity.
- **Phase alignment changes between versions** (the full table and rules are in PLAN
  §3.3).
  - 3.00 leaves quarter-cycle shifts uncorrected.
  - 3.01–3.05 require aligned phases. A converter may apply the shifts, and records them
    in `SYS / PHASE SHIFT` (φRINEX = φoriginal + Δφ).
  - **From 3.03 the record has three states:** zeros mean "aligned at the source", a code
    with the rest blank means "only reference signals", and fully blank means "unknown".
    3.05 says unknown-alignment data "should not be published".
  - 4.00+ requires aligned phases and says to ignore the record.

  By default the converter never changes phase values. Converting unknown alignment to
  4.x refuses unless the user passes `--assume-phase-aligned` or `--align-phases`.
- **Missing observations** may be written as `0.0` **or** blanks (2.11, and 3.05 §6.7).
  A `0.000` is never a measurement. A phase that overflows F14.3 is clipped by ±10⁹, with
  LLI bit 0 set.
- **Galileo nav data-source bitmask**: carry it verbatim between v3 and v4; derive the v4
  I/NAV or F/NAV type from it, never the reverse.
- GLONASS-only RINEX 2 obs files are time-tagged in UTC (GLO time): never shift them by
  leap seconds.
- GLONASS frequency channels come from nav files, but `GLONASS COD/PHS/BIS` comes only
  from the receiver or site log. Never invent either.

**Real-file damage**

- Header counts (`# OF SATELLITES`, `PRN / # OF OBS`, `TIME OF LAST OBS`, `INTERVAL`) are
  often wrong in real files. They're repaired and reported by default.
- `yell1800.10d.Z` (2010) on CDDIS is broken at the source: it decodes to nothing.

## Stop and ask the user when

- you think you need a package Anaconda doesn't ship, or an outside program at runtime;
- a conversion default is a policy choice, not a spec fact (for example, the default
  attribute for a v2 `L2`);
- an oracle disagrees with the spec, or with us, and you can't prove which is right;
- you'd download anything except CDDIS/BKG data and the oracles listed above;
- you'd delete corpus files, or spend Codex usage beyond one reviewer per round.

## About the user

The user works with GNSS data. On the desktop they run an SP3 orbit-comparison monitor, a
GPS POD Kalman-filter project and the squidy QC dashboard. Their code style favours
stdlib-first, fail-closed, well-documented Python with formulas written up (see
`reference/squidy/math.md`). Give answers in plain language, keep observation and
hypothesis apart, and say clearly what's verified and what isn't.
