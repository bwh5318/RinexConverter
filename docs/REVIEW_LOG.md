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
| | | | | 29 | 9 | 7 |
| | | | | 30 | 9 | 8 |
| | | | | **31** | **9, confident** | **9, confident** |

("9 → 8": confident in the report, then lowered by its own follow-up runs.) Sonnet said "yes,
confident" in most rounds from 5 on; Sol said "not confident" in rounds 1-30, each time with
1-5 concrete blockers, all fixed. After the user's answers of 2026-11-01 they allowed at most
rounds 29-31; in round 31 both reviewers were confident with no blocker (Sonnet 9/10, Sol
9/10), which ends the loop. The polish of round 31 (malformed LEAP SECONDS records refused;
a temporary-file failure as an io-error) was fixed after it and is not re-reviewed.

From round 22 seeded generators (`tests/independent/generate.py`, `tests/unit/test_generated.py`:
random valid obs and met files, and corpus nav files cut at random) found most of the later
issues, and the reviewers ran them on seeds of their own. Evidence at the stop: unit suite
851 passed; mutation audit 7,314 mutations of 274 claims, none survived (round-27 code);
generator seed ranges 0-12299, 20000-20599, 30000-31499, 50000-50399, 60000-61499,
80000-80999, 90000-90499, 100000-100999, 110000-110399, 120000-120799, 130000-130799,
140000-140499 clean on the code of their time; corpus run 18 (obs rows valid for the final
code) 5,214+ rows and the final nav rerun 1,188+ rows, 0 problems.

## rinexconv converter, rounds 32-35 — 2026-11-02 (desktop session)

The project moved to the desktop (`E:\pythontests\RINEXConvert_Analysis`). The user asked for a fresh
review by Claude agents and Codex Sol 6.1 at high effort, and for work to continue "until you're
confident it will always do the conversions correctly". Reviewers: three Opus `reviewer` agents with
one lens each (observation files; navigation files; whether the checks could pass a wrong converter,
plus the plumbing) and Codex Sol 6.1 (high) on a fresh thread, all kept across rounds.

| Round | Sol 6.1 | Opus obs | Opus nav | Opus checks |
|---|---|---|---|---|
| 32 | 7 | 9, confident | 6 | 6 |
| 33 (verify) | 8 | 8 | 8 | 7 |
| 34 (verify) | 8 | **9, confident** | **9, confident** | 8 |
| 35 (verify, Sol + checks only) | 8 | — | — | 9, confident |
| 36 (write path) | 8 | — | — | 9, confident |
| 37 (write path) | 8 | — | — | 9, confident |
| **38** (write path) | **9, confident** | — | — | **9, confident** |

The obs and nav reviewers were not asked again after round 34: their areas did not change. From
round 35 Sol's blockers were all in the write path (concurrent jobs, --force, interruptions), not in
any converted value; each was fixed (docs/DECISIONS.md, "write path, rounds 34-38").

Round 32 found what 31 rounds had not: values whose *meaning* changes between versions (GLONASS
and SBAS message frame time on a day versus a week basis, the RINEX 2.00 GLONASS signs, the QZSS
Klobuchar region code of 4.00/4.01, truncated reference weeks), event clock offsets dropped, and
3.02 phase-shift records misread. All three reviewers who looked at nav found the frame-time bug
independently. The nav comparator shared the converter's premise that a field's position means the
same in every version, so a separate field-by-name checker (`tests/independent/navfields.py`) was
written from the spec tables and wired into the corpus harness. Rounds 33-34 closed narrower items
(spare-versus-real fields in RINEX 2/3, NavIC/Galileo system weeks, scale-factor precedence inside
events, the write path under --force and under concurrent jobs). Every item, with its citation, is
in docs/DECISIONS.md (entries "review round 32" and "review round 33 (verify) fixes").

Evidence at the end: unit suite 1,015 passed, 27 skipped (missing oracles), 13 xfailed; full corpus
run on the frozen conversion code (corpus_r34): 5,280 conversions, 5,208 converted, 72 by-design
refusals, 0 crashes, 0 token problems (both nav checkers), 0 idempotence failures, 0 loss-table
violations, 454 wrapper legs clean, no round trip with different data. More than 120 kinds of wrong
output built by the checks reviewer over rounds 32-38 are caught. Write path: Sol's 2,620 in-memory
fault/interruption runs, the checks reviewer's 88 fault cases and real-process races of 3-4 concurrent
runs, and a test that interrupts every executed line of the write code: each run leaves the folder as it
was or holding the whole new set.

Open for the user (policy, not defects): `--align-phases` (the 4.x tables give no shift values;
docs/PHASE_ALIGNMENT.md); QZSS LNAV area into 4.02; GLONASS frame time across the Sunday week
boundary; the QZSS L2P flag written by real 3.02 files in a spare; the scale-factor precedence
inside events (an inference both converter and checker share).

## rinexconv, after the user's policy answers — Codex Astra (xhigh), 2026-11-02/03

The user answered the five policy questions and asked: "after that run it by codex astra on xhigh".
Astra's first run hit the Codex 5-hour usage limit; an Opus reviewer took the slot meanwhile and the
Astra review ran after the reset (the user chose to wait, then to run one more verify near 80% of the
weekly Codex budget).

| Pass | Reviewer | Score | What it found (all fixed; docs/DECISIONS.md) |
|---|---|---|---|
| 39 | Opus (in the Codex slot) | 8 | --align-phases: a RINEX 2 attribute default decided a physical shift; un-align to 3.00 dropped zero entries before precedence |
| 40 | Astra review | 7 | Header records after event flags 2/5 ignored by converter and checker alike (all conversions); four --align-phases edge cases (undone accounting, 5-decimal corrections, overflow clipping, non-finite numbers) |
| 41 | Astra verify 1 | 8 | Avoidable rounding where a 3.00 scale factor holds the value; checker dispatch on a rule-name prefix |
| 42 | Astra verify 2 | 8 | Checker merged scale-factor scopes; planner sized factors from unapplied corrections |
| **43** | **Astra verify 3** | **9, confident** | none: "I would ship this version" |

Only pass 40's first item touched ordinary conversions (no corpus file has such an event); every later
item was inside `--align-phases` un-aligning to 3.00 with corrections finer than a quarter cycle.
Evidence at the end: unit suite 1,060 passed, 27 skipped, 13 xfailed; full corpus run on the final code (corpus_r41): 5,280 conversions,
5,208 converted, 72 by-design refusals (the same files as every run), 0 crashes, 0 token problems (both
nav checkers), 0 idempotence failures, 0 loss-table violations, 454 wrapper legs clean, no round trip
with different data.

## rinexconv speed work — Codex Sol 6.1 (xhigh), 2026-11-05/06

The user: "first i want you to try to optimize the speed of the conversions as much as you can. review with
sol on xhigh". Sol (high) wrote a plan first; four Claude agents optimised four areas; Sol (xhigh) reviewed
the result for any input where the optimised code differs from the original (docs/DECISIONS.md, "speed work").

| Pass | Reviewer | Score | What it found (all fixed) |
|---|---|---|---|
| 44 | Sol review | 7 | The batch companion listing was kept while the folder's modification time was unchanged (a nav file added within its resolution was missed: a refusal where the original converted); the survey's distinct-mask table had no bound (pass-1 peak 2.38x -> 3.67x the file on a synthetic all-distinct file); test_memory's bound too loose; the --jobs memory scheduling described too strongly |
| **45** | **Sol verify** | **9, confident** | none blocking: "both blockers are resolved; independent verification found no new output, report, refusal, warning, or ordering difference" |

Evidence at the end: unit suite 1,108 passed, 27 skipped, 13 xfailed; whole-corpus digests (13,915
conversions x outputs, reports, refusals) identical between the original code and the final code; the corpus
run on the final code (corpus_opt) identical to corpus_r41 in every field of all 5,280 rows; whole
conversions 1.7-1.9x faster (obs and large nav files), 1.25-1.3x on small files.

## rinexqc plan (PLAN.md revision 4) — Codex Sol 6.1 (xhigh) and Opus, 2026-11-06

The user: "re reveiw it with sol on xhigh and an opus agent see if we can get to the 9/10. do up to 3 rounds".
The QC part of the plan (§5, §6, §7 Q rows) dated from 2026-10-30, before any code; its last scores were
Sonnet 8 and Astra 7, with revision 3 never re-scored.

| Round | Sol | Opus | What it found (all fixed in PLAN.md revision 4) |
|---|---|---|---|
| 1 | 7 | 6 | No observation-semantics contract (version-dependent LLI, wavelength factor, SNR units, flags) and no frequency/pair table; slip, MP and ionosphere claims beyond what the data show; clock steering and drift inferred from observations alone; Q1 gates unmeasurable and teqc unavailable; no rinexqc architecture, schema, memory budget or offline rule; completeness denominators; orbit, SPP and SISRE conventions per message type; validation independence |
| 2 | 8 | 8, confident | Semantics rows (wavelength factor is ambiguity spacing; LLI bit 2 from 3.01; header records after flags 2-5; 3.00 alignment unknown); version invariance needs a table of legitimate changes; no 1 Hz detection guarantee; TGD on the GPS ionosphere-free clock; completeness with unknowns and SP3 alone; whole-day GEO arcs; sensitivity tests that could not fail |
| 3 | 8 | 8, confident ("9 once B1 fixed") | Milestone rows still carried round-1 gates; compliance needs the validator, not the reader; RINEX GLO time tags are UTC hours (rinex_4.02.txt §4.1.2); completeness bounds wrong when unknown trials were observed; GLONASS channels per epoch; lenient reads keep each status |

Round 3's items were fixed after the round (the user's limit was three rounds), and have not been
re-scored. Open for the user: decisions D1-D5 in PLAN.md §5.10.

## rinexqc Q0a documents — Opus and Codex Sol 6.1 (high), 2026-11-06

Reviewed: docs/QC_METRICS.md v0, docs/QC_SCHEMA.md v0, tests/expectations/qc_invariance.json v0, the Q0a
entry of docs/DECISIONS.md and PLAN.md §5.10. One Opus reviewer and one Codex reviewer, the user's usual
choice; no target score (review, one fix pass, one verify round).

| Round | Opus | Sol | What it found |
|---|---|---|---|
| 1 | 6 | 6 | Both: the clock classifier contradicted its tests (a code-and-phase step cancels in code minus phase); edge gaps unobservable and the arc definition circular; RINEX 2 C1/P1 and C2/P2 shared a signal key and RINEX 3→2 conversions could not be matched; the reader reads past damage the converter refuses by validation; `lenient_read` had three meanings; several Q1 outputs had no correctness gate; 2.10 has no band 5. Opus: an unmeetable SNR gate; half-cycle count broken for non-GPS RINEX 2 phases; the RINEX 2.20 OBS SCALE FACTOR; nav message-type rules missing; header counts. Sol: scale-factor rounding to zero; trial independence |
| 2 (verify) | 8, no blocking | 7 | Opus: polish only (synthetic SNR noise unstated; E7 off by one epoch; wording). Sol: one clock step gave two events (T3's two lobes, the cubic ringing); trials clustered by copy, not by source file; E7 off by one (also Opus); detector medians over different satellites after a removal; clip counts assumed |

All items of both rounds were checked against the code and the specs, and fixed: round 1 by rewriting
QC_METRICS.md; round 2 by edits (T3 lobe pairing and step removal from later fits, clustering by source
file with a fixed seed, the arc rule and gate E7 stated by the spacing (N + 1)·Δ, the invariance test's
source run restricted with `--select` to what the target holds, clip counts computed from the two files,
the synthetic SNR noise stated). The round-2 fixes have not been re-scored. Codex usage at the end:
5-hour 28%, weekly 7%. Open for the user: sign-off of Q1's gates and proposals [P1]-[P8]; decision D6
(the ICD texts).
