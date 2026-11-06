# rinexqc JSON result — schema v0

Milestone Q0a (PLAN.md rev. 4 §5.1, §5.8), 2026-11-06. Schema id: `rinexqc-result/0`. v0 may change
until Q1 is accepted; Q1 freezes it as `rinexqc-result/1`. After that an added optional field is a
minor change; anything else needs a new major id. A stdlib-only validator in the tests checks every
result against this document (docs/QC_METRICS.md §7, gate E4).

One JSON document per input file. Field order as below; keys are lower-case with underscores;
times are ISO 8601 with the time system named beside them; numbers are JSON numbers (never strings,
never NaN or Infinity: a value that cannot be a finite number is `null` with a reason).

## 1. The document

```json
{
  "schema": "rinexqc-result/0",
  "tool": {"name": "rinexqc", "version": "0.1.0", "commit": "<git hash>"},
  "run": {
    "started_utc": "2026-11-20T10:00:00Z",
    "options": {"lenient": false, "fetch": false, "elevation_mask_deg": null, "select": null},
    "offline": true
  },
  "input": {
    "id": "in0",
    "path": "data/corpus/obs/v3.05/AUCK00NZL_R_20262740000_01D_30S_MO.rnx.gz",
    "kind": "obs",
    "version": "3.05",
    "wrappers": ["gz"],
    "sha256": "<of the file as given>",
    "decoded_sha256": "<of the decoded RINEX bytes>",
    "reader": "default",
    "read": "ok",
    "refusal": null
  },
  "inputs": [
    {"id": "in0", "role": "obs", "name": "AUCK00NZL_R_…_MO.rnx.gz", "sha256": "…", "version": "3.05",
     "source": "local"},
    {"id": "in1", "role": "nav", "name": "BRDC00IGS_R_…_MN.rnx.gz", "sha256": "…", "version": "3.04",
     "source": "fetched", "url": "https://cddis.nasa.gov/archive/gnss/…"}
  ],
  "methods": {"document": "docs/QC_METRICS.md", "version": "v0", "commit": "<git hash>"},
  "thresholds": {"set": "qc-thresholds/0", "commit": "<git hash>", "split": "<sha256 of qc_split.json>"},
  "lenient_read": false,
  "compliance": { "...": "§2" },
  "metrics": [ { "...": "§3" } ]
}
```

- `input.reader`: `default` or `lenient` (`--lenient` given). `input.read`: `ok` or
  `refused-corrupt`. `input.refusal` is `null` or `{"source", "rule", "line", "column", "message"}`,
  with `source` `reader` (rinexcore's `CorruptError`) or `validator` (a data-damage finding the
  reader read past; QC_METRICS §3, [P6]). An invocation fault (wrong kind, unreadable path, bad
  option) produces no document: rinexqc exits as rinexconv does (QC_METRICS §7.3).
- `run.options.select`: `null`, or the systems and signal keys the run was restricted to
  (`--select`, e.g. `{"systems": "GRE", "signals": ["G:C1C", "G:L1C"]}`). Everything else in the file
  is ignored as if absent, and every metric's support says so. The version-invariance test uses it to
  run the source on exactly what the converted file holds (QC_METRICS §7 E3).
- `inputs` lists every file the run used, the QC'd file first. `role` is one of `obs`, `nav`, `met`,
  `sp3`, `clk`, `atx`, `rcvr_ant`, `sat_meta`, `bias`, `crd`, `sitelog`, `icd`, `snr_table`,
  `overrides`, `glo_fcn` (QC_METRICS §5). `source` is `local` or `fetched` (with `url`). Command-line
  values (`--glo-fcn`, `--overrides`) are recorded as an input whose `sha256` is that of their
  canonical JSON form; the ICD tables, as the `rinexcore/spec/` module and its commit.
- `lenient_read` (top level and on every metric, §3): `true` exactly when `input.reader` is
  `lenient`, whether or not the lenient reader had to repair anything (QC_METRICS §3). What it
  repaired is in `compliance.reader.repairs`.

## 2. Compliance

```json
"compliance": {
  "reader": {"refusal": null,
             "repairs": [{"rule": "OBS.BLANKLINE", "line": 4410, "message": "…", "lenient_only": false},
                         {"rule": "OBS.TRUNCATED", "line": 81233, "message": "…", "lenient_only": true}]},
  "validator": {
    "header_only": [{"rule": "…", "line": 12, "column": 61, "message": "…"}],
    "data_level": [],
    "damage": [],
    "counts": {"header_only": 0, "data_level": 0, "damage": 0}
  }
}
```

The reader records some repairs in both modes (blank lines skipped: `HDR.BLANKLINE`,
`OBS.BLANKLINE`, `NAV.BLANKLINE`, `MET.BLANKLINE`) and others only under `--lenient`
(`OBS.TRUNCATED`, `MET.DATA.COLUMNS`, `MET.EPOCH.V2LAYOUT`, `NAV.V4.DRAFT-HEADER`); notes about damage
it read past (`OBS.DATA.SKIPPED-TEXT`) are listed too. `lenient_only` says which. `damage` lists the
validator's data-damage findings (the rule set of QC_METRICS §3); by default the first of them is the
refusal. The validator runs as its own pass on every file the decoder can decode, refused or not
(D1). Finding lists may be capped (first 100 per rule) with the full count in `counts`.

## 3. The metric record

Every metric of the catalogue (QC_METRICS §4) for the file's kind appears once in `metrics`, in
catalogue order, whatever happened (gate E4). A metric with per-scope results carries them in `per`;
the fields of the parent (`unit`, `method`, `thresholds`, `inputs`, `nature`) apply to each entry.

```json
{
  "id": "obs.snr.dist",
  "nature": "evidence",
  "unit": "dB-Hz",
  "unit_source": "header:SIGNAL STRENGTH UNIT",
  "value": null,
  "status": {"code": "ok", "reason": null, "detail": null},
  "support": {"epochs": 2880, "satellites": 41, "arcs": 96, "observations": 512331,
              "excluded": [{"reason": "missing-value", "count": 1204}]},
  "method": {"section": "QC_METRICS.md §4.1", "estimator": "exact"},
  "thresholds": {"set": "qc-thresholds/0", "commit": "<git hash>", "used": {}},
  "inputs": ["in0"],
  "lenient_read": false,
  "detection_limit": null,
  "per": [
    {"scope": {"satellite": "G05", "signal": "G:S1C", "code": "S1C"},
     "value": {"count": 2770, "mean": 44.1, "median": 45.0, "sigma_robust": 4.4,
               "p5": 33.0, "p95": 51.0, "min": 21.0, "max": 53.0,
               "ssi_hist": {"code": {"5": 120, "7": 2650}, "phase": {"7": 2770}}},
     "status": {"code": "ok", "reason": null, "detail": null},
     "support": {"epochs": 2770, "excluded": []},
     "flags": []}
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `id` | string | The catalogue id (QC_METRICS §4) |
| `nature` | `evidence` \| `inference` \| `hypothesis` | PLAN §5.1 item 2: what a test saw, what it is taken to mean, or what needs outside knowledge to be sure |
| `unit` | string | Always present, also when `value` is `null` (the unit the value would have). Units of QC_METRICS §0 |
| `unit_source` | string or null | For units that depend on the input: `header:SIGNAL STRENGTH UNIT`, `snr_table:<receiver>`, `default:relative` (D5) |
| `value` | number, object, array or `null` | The file-level value. `null` only with a status other than `ok` or `degraded`, or when the metric is per-scope only (`per` holds the values) |
| `status.code` | `ok` \| `degraded` \| `cannot-compute` \| `not-applicable` | PLAN §5.1 item 1 |
| `status.reason` | string or null | `null` for `ok`, else a code of §4 |
| `status.detail` | string or null | Free text for people (which product, which epochs) |
| `support` | object | `epochs`, `satellites`, `arcs`, `observations`, `trials` (whichever apply; integers) and `excluded`: a list of `{reason, count}`. Untestable epochs are an `excluded` entry, never negatives |
| `method.section` | string | The section of QC_METRICS.md that defines the metric |
| `method.estimator` | string | `exact`, `approx-0.01` (quantile histogram), or the named estimator (`arc-median`, …) |
| `thresholds` | object | The set, its commit, and `used`: the tuned values this metric applied (`{"T-clk": 6.0}`) |
| `inputs` | list of input ids | Each id resolves to an entry of the top-level `inputs`, which holds the name and sha256. By reference, so per-satellite results do not repeat the hashes; the validator fails a dangling id |
| `lenient_read` | boolean | §1 |
| `detection_limit` | object or null | For detectors: `{"value": 3.1, "unit": "m", "test": "code-only"}` (QC_METRICS §4.1.1) |
| `per` | list or absent | Per-scope results. `scope` keys: `system`, `satellite`, `signal`, `band`, `pair`, `code`, `type`, `field`, as apply. `signal` is the adapter's canonical key (QC_METRICS §1.2): `<system>:<code>` with the RINEX 3/4 code, band digits normalised (`G:C1C`, `C:C2I`), or the RINEX 2 code (`G:C1`, `G:P1`, `G:P2`: the attribute unknown), and `#2` for a code's second column; `code` is the code as the file wrote it. Each entry has its own `value`, `status`, `support` and optional `flags` |
| `events` | list or absent | For detectors: `{"epoch", "time_system", "size", "unit", "support", "class"}` per event |

Rules:
- A metric whose input is missing: `value: null`, `status: cannot-compute(missing-<role>)`, `per`
  absent; it is still listed.
- A refused file (D1, [P6]): every metric `value: null`, `cannot-compute(refused-corrupt)`, except
  `*.compliance`.
- `degraded` keeps its value: the reason says why it is weaker (an approximation, an unknown
  attribute, a relative unit).
- A per-scope entry may have a status different from its parent; the parent's status summarises:
  `ok` if every entry is `ok`; else the worst entry's code with reason `some-scopes` and the counts in
  `detail`.

## 4. Status reasons (closed list, v0)

| Reason | Use |
|---|---|
| `refused-corrupt` | The file was refused (D1): the reader's `CorruptError`, or a validator data-damage finding ([P6], QC_METRICS §3) |
| `missing-<role>` | A needed input is absent: `missing-nav`, `missing-sp3`, `missing-clk`, `missing-atx`, `missing-rcvr_ant`, `missing-sat_meta`, `missing-bias`, `missing-crd`, `missing-sitelog`, `missing-icd` |
| `no-record` | A header record the metric reads is absent (e.g. no `INTERVAL`, no `PRN / # OF OBS`) |
| `not-in-version` | The file's version defines no such item (e.g. `SIGNAL STRENGTH UNIT` in RINEX 2) |
| `no-channel` | GLONASS FDMA k unknown for the satellite |
| `no-phase`, `no-code`, `no-doppler`, `single-frequency` | The observables the test needs are absent |
| `too-few-epochs`, `too-few-satellites`, `too-few-testable` | Support below the test's minimum |
| `cadence-too-coarse`, `cadence-too-fine` | Outside the metric's cadence limits (QC_METRICS §4) |
| `snr-unit-relative` | S values in receiver units (D5) |
| `attribute-unknown` | A RINEX 2 code fed the metric; the attribute is not known |
| `phase-alignment-unknown` | The metric needs the alignment state and it is unknown |
| `non-standard-system` | A C, J or I satellite in a RINEX 2 file ([P1]) |
| `approximation` | A stated approximation (e.g. Klobuchar for Galileo, D3) |
| `selective-availability` | Data before 2000-05-02 (SA on): reported, not graded |
| `kinematic-segment`, `static-only` | The metric needs static data, or the segment moves |
| `some-scopes` | Parent summary of per-scope statuses (§3) |
| `no-data` | The file holds no observation of the metric's kind (e.g. no S types) |

A new reason is added to this list (and to the validator) before code uses it.

## 5. Example: a refused file

```json
{
  "schema": "rinexqc-result/0",
  "input": {"id": "in0", "kind": "met", "version": "2.00", "reader": "default", "read": "refused-corrupt",
            "refusal": {"source": "reader", "rule": "MET.DATA.COLUMNS", "line": 23, "column": 8,
                        "message": "values off their F7.1 columns; --lenient reads them by pattern"}},
  "lenient_read": false,
  "metrics": [
    {"id": "met.compliance", "value": {"reader": 1, "header_only": 0, "data_level": 1},
     "unit": "count", "status": {"code": "ok", "reason": null, "detail": null}, "…": "…"},
    {"id": "met.time", "value": null, "unit": "s",
     "status": {"code": "cannot-compute", "reason": "refused-corrupt", "detail": "line 23"},
     "lenient_read": false, "…": "…"}
  ]
}
```

(The rule names and messages here illustrate the shape; the real ones are the reader's.)
