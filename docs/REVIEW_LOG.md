# Review log

## PLAN.md — 2026-10-30 (desktop session)

The user chose the reviewers: a Sonnet subagent, and Codex Astra (`gpt-6-astra`) at xhigh
effort. Each reviewer scored the plan independently, then reviewed the fixes in a verify
round.

| Round | Sonnet | Astra | What changed |
|---|---|---|---|
| 1, rev 1 | 7/10 | 6/10 | — |
| 2 (verify), rev 2 | 8/10 | 7/10 | Full rewrite; the 482-file corpus added |
| 3 (verify), rev 2.1 | 8/10 | 7/10 | The verify-round items below |
| After round 3, rev 3 | not re-scored | not re-scored | The round-3 items below |

### Round 1: accepted, after checking against `specs/text/` and the RNXCMP source

- **The "100%" contract could pass a wrong converter** (both reviewers). Fixed with:
  - diff ⇔ report, in both directions;
  - pre-authorised `allowed_losses.json`;
  - an independent token comparator;
  - hand-written expectations;
  - archived oracle results;
  - idempotence;
  - a rule that oracle disagreements need proof and the user's sign-off.
- **Hatanaka `&` was described wrongly** (both). Corrected from `crx2rnx.c`, and CRINEX
  3.1 was added for RINEX 4.02.
- **GLONASS COD/PHS/BIS does not come from nav files** (both). Physical values are never
  invented, and there is a fixed order of sources for each value.
- **RINEX 4.02 picosecond epochs** (Astra). The model now stores exact decimal seconds.
- **Header-state timeline:** event flags and `WAVELENGTH FACT` semantics (both).
- **Gating by minor version** (Astra):
  - BeiDou `C1I` in 3.02, `C2I` from 3.03;
  - GLONASS nav's fifth line from 3.05;
  - rules for merging and splitting nav files.
- **The streaming engine needs two passes**; performance budgets are measured, not
  guessed; byte-level I/O on Windows (Sonnet).
- **QC:** clock jumps tested separately in code and phase; equal-cycle slips; realistic
  slip tolerances; BeiDou GEO orbits; SISRE with APC/CoM and clock datum; a denominator
  for completeness (both).
- **§9 reuse claims overstated the reference code** (both). Corrected in PLAN.md and
  `reference/README.md`.

### Verify round: accepted

- **Nav exponent letter is version-gated** (Sonnet). `D19.12` up to 4.00, `E19.12` from
  4.01, with `D` "strongly deprecated" (`rinex_4.02.txt` §6.8).
- **Four named run outcomes** (both): `converted`, `converted-with-removal`,
  `refused-missing-information`, `refused-corrupt`. The corpus harness supplies the
  same-day nav file.
- **The spool holds canonical records**, formatted in pass 2 (Sonnet).
- **Phase alignment** (Astra): 3.00 leaves shifts unaligned, 3.01+ requires them aligned
  (`rinex301.txt` §9.1), and a converter may apply them. The earlier rule "never apply a
  shift" was wrong and has been replaced by convention-aware rules.
- **The Galileo data-source bitmask is preserved verbatim** (Astra).
- **The token comparator includes signal identity**, and nav and met get field-level
  comparison (Astra).
- **QC gates:** calibration and held-out halves, controlled numerical fixtures, and
  published SISRE and squidy ORD as context only (Astra).
- **Scale factors:** values are exact decimals (Astra).
- **Archived oracle digests**, and `allowed_losses.json` keyed by loss category (Sonnet).
- **Corpus:** two duplicate manifest entries removed, leaving 480 unique files. There is
  no CRINEX 3.1 file in the corpus, so M1 must create one (Astra).

### Round 3: accepted, after checking against `specs/text/`

Both reviewers confirmed that every round-2 change had landed.

- **Phase alignment was misread** (both reviewers). From 3.03 the record has three states:
  zero, code-only and fully blank (`rinex303.txt` ~2200–2216). 3.05 says unknown-alignment
  data "should not be published" (§5.2.12). Table A23 only exists from 3.03. 4.00 already
  says to ignore the record (A39; A45 in 4.02). The rewrite (§3.3):
  - keeps alignment *state* separate from *recorded corrections*, with satellite scope;
  - never changes phase values by default;
  - makes an unknown alignment going to 4.x a clause-8 refusal, unless the user passes
    `--assume-phase-aligned` or `--align-phases`;
  - adds rules for v4 → v3 and for going to v2;
  - adds a fixture matrix.
- **Missing observations may be `0.0` or blank** (Astra; 2.11 ~1288, 3.05 §6.7). The model,
  the identity normalisation and the QC observed-count definition all follow that rule.
  Phase overflow is clipped by ±10⁹ with LLI bit 0.
- **Identity gates are scoped** (Astra): A → B → A only from write versions;
  same-version identity only for files that needed no repair; files that were repaired
  are compared against independently computed expected repairs.
- **Nav duplicates are preserved by default**; `--dedupe` is opt-in (Astra).
- **QC split by station**, so a station's daily, hourly, high-rate files and alternate
  encodings all go into the same half (both).
- **Invocation and I/O failures** are a separate class from the four outcomes (Astra).
- **CRX archive:** the sha256 of the decompressed output, for byte equality (Astra).
- **Nav token comparator v1:** positional numeric multisets per record (Sonnet).
- **RNX2CRX comes from the GSI zip**; there's no compiler on the laptop (Sonnet).
- Stale wording fixed: revision number, and "golden files" → digests (Sonnet).

### Not re-verified

The round-3 fixes were applied after both reviewers' last scores (Sonnet 8, Astra 7). Have
one reviewer check §3.3's phase-alignment rules at the end of M0b, when
`allowed_losses.json` and the fixtures are written against them.

## rinexconv converter — 2026-10-30 to 2026-11-01 (laptop sessions)

Reviewers (the user's choice): a Sonnet subagent and Codex Sol 6.1 at xhigh, one thread kept
across rounds. Goal: all three (Claude, Sonnet, Sol) confident that rinexconv converts any
common RINEX obs/nav/met file between 2.10 and 4.02 (reading 2.00/2.01). Every round's fixes,
with spec citations, are in `docs/DECISIONS.md`; fixtures in `tests/unit/test_round*.py`.

| Round | Sonnet | Sol | | Round | Sonnet | Sol |
|---|---|---|---|---|---|---|
| 1 | 7 | 6 | | 15 | 8 | 8 |
| 2 | 8 | 6 | | 16 | 9 | 8 |
| 3 | 8 | 7 | | 17 | 9 | 8 |
| 4 | 8 | 7 | | 18 | 8 | 8 |
| 5 | 9 | 8 | | 19 | 9 | 8 |
| 6 | 8 | 8 | | 20 | 9 | 8 |
| 7 | 9 | 8 | | 21 | 8 | 8 |
| 8 | 9 | 8 | | 22 | 9 | 8 |
| 9 | 9 | 8 | | 23 | 9 | 8 |
| 10 | 9 | 8 | | 24 | 8 | 8 |
| 11 | 9 | 8 | | 25 | 9 → 8 | 8 |
| 12 | 9 | 7 | | 26 | 9 | 8 |
| 13 | 9 | 8 | | 27 | 9 → 8 | 8 |
| 14 | 9 | 8 | | 28 | 9 → 8 | 8 |

("9 → 8": confident in the report, then lowered by its own follow-up runs.) Sonnet said "yes,
confident" in most rounds from 5 on; Sol said "not confident" in every round, each time with
1-5 concrete blockers, all fixed. The round-28 fixes have not been re-reviewed.

From round 22 seeded generators (`tests/independent/generate.py`, `tests/unit/test_generated.py`:
random valid obs and met files, and corpus nav files cut at random) found most of the later
issues, and the reviewers ran them on seeds of their own. Evidence at the stop: unit suite
851 passed; mutation audit 7,314 mutations of 274 claims, none survived (round-27 code);
generator seed ranges 0-12299, 20000-20599, 30000-31499, 50000-50399, 60000-61499,
80000-80999, 90000-90499, 100000-100999, 110000-110399, 120000-120799, 130000-130799,
140000-140499 clean on the code of their time; corpus run 18 (obs rows valid for the final
code) 5,214+ rows and the final nav rerun 1,188+ rows, 0 problems.
