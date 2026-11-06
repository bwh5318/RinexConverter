"""The two outcomes the corpus run never produces, checked on the corpus (PLAN §4, "Acceptance
for rinexconv 1.0": "The two other outcomes are tested on their own").

Every corpus observation file with GLONASS data in a version before 3.02 (RINEX 2, 3.00, 3.01:
no GLONASS SLOT / FRQ # record) is converted to every target from 3.02 on, which makes that record
mandatory (rinex302.txt Table A2), WITHOUT the same-day GLONASS nav companion the corpus run gives:

  1. plain: the outcome must be refused-missing-information, and the message must name the
     missing value (the GLONASS frequency channels);
  2. with --drop-unresolvable: the outcome must be converted-with-removal, the report must list
     GLONASS (R) as removed, and the independent checks (tests/independent: token comparator,
     header checks, loss table) must accept the output.

--assume-phase-aligned is passed to both, as in the corpus run, so that the 4.x targets are not
refused for phase alignment instead.

    python tools/outcome_check.py [--jobs 8] [--out data/out/outcome_check]

Standard library only.
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("SOURCE_DATE_EPOCH", "1793404800")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rinexconv.engine import WRITE_VERSIONS, Options, convert_data, load_bytes  # noqa: E402
from rinexcore.errors import (CONVERTED_WITH_REMOVAL, REFUSED_MISSING,  # noqa: E402
                              RinexError)
from tests.independent.allowed import check as allowed_check  # noqa: E402
from tests.independent.compare import compare_obs  # noqa: E402

CORPUS = ROOT / "data" / "corpus"
MANIFEST = ROOT / "tests" / "corpus" / "manifest.json"
TARGETS = [v for v in WRITE_VERSIONS if v >= "3.02"]


def opts(target, drop):
    return Options(target=target, nav=[], auto_nav=False, assume_phase_aligned=True,
                   drop_unresolvable=drop, crx=False, compression="none")


def has_glonass(payload):
    """GLONASS satellites in the data: 'Rnn' in a RINEX 2 epoch line's satellite list (columns
    33-68 and its continuation lines) or at the start of a RINEX 3 satellite record."""
    body = payload.split(b"END OF HEADER", 1)[-1]
    v3 = payload[5:6] == b"3" or payload[:9].strip().startswith(b"3")
    if v3:
        return re.search(rb"(?m)^R\d\d", body) is not None
    return re.search(rb"(?m)^.{32}(?:[A-Z ]\d\d)*R\d\d", body) is not None


def run(path):
    rows = []
    raw = (CORPUS / path).read_bytes()
    try:
        inp = load_bytes(raw).container.payload
    except RinexError as e:
        return [dict(path=path, target="*", mode="load", ok=False, why=f"input refused: {e}"[:300])]
    if not has_glonass(inp):
        return [dict(path=path, target="*", mode="skipped", ok=True, why="no GLONASS data")]
    for target in TARGETS:
        # 1. no companion: refused, naming the missing value
        row = dict(path=path, target=target, mode="missing")
        try:
            convert_data(raw, os.path.basename(path), opts(target, False))
            row.update(ok=False, why="converted although no GLONASS channel source was given")
        except RinexError as e:
            named = "GLONASS" in str(e) and ("channel" in str(e).lower() or "FRQ" in str(e))
            row.update(outcome=e.outcome, ok=e.outcome == REFUSED_MISSING and named,
                       missing=str(getattr(e, "missing", ""))[:120], message=str(e)[:200])
            if not row["ok"]:
                row["why"] = "wrong outcome" if e.outcome != REFUSED_MISSING else "message names no GLONASS channel"
        except Exception as e:  # noqa: BLE001 - a crash is a finding
            row.update(ok=False, why=f"CRASH {type(e).__name__}: {e}"[:300], tb=traceback.format_exc()[-800:])
        rows.append(row)
        # 2. --drop-unresolvable: GLONASS removed and reported; the independent checks agree
        row = dict(path=path, target=target, mode="drop")
        try:
            outs = convert_data(raw, os.path.basename(path), opts(target, True))
            rep = outs[0].report.to_dict()
            losses = rep["losses"]
            removed = [k for k in losses if k == "system-removed-unresolvable:R"]
            probs = compare_obs(inp, outs[0].data, rep)
            # the removal is allowed only because the user asked for it (allowed.py 'when':
            # drop-unresolvable); without the flag the same claim is a violation
            viol = allowed_check(rep, {"drop_unresolvable": True})
            unasked = "system-removed-unresolvable:R" in allowed_check(rep)
            # no GLONASS satellite record left in the RINEX 3/4 data section ('Rnn' + data)
            body = outs[0].data.split(b"END OF HEADER", 1)[1]
            no_r = not any(re.match(rb"R\d\d ", line) and len(line) > 3 + 14 for line in body.splitlines())
            row.update(outcome=rep["outcome"], removed=removed, problems=probs[:3], violations=viol[:3],
                       ok=(rep["outcome"] == CONVERTED_WITH_REMOVAL and bool(removed) and not probs and not viol
                           and no_r and unasked))
            if not row["ok"]:
                row["why"] = ("outcome " + rep["outcome"] if rep["outcome"] != CONVERTED_WITH_REMOVAL else
                              "no removal claim" if not removed else "checker problems" if probs else
                              "loss-table violation")
        except RinexError as e:
            row.update(ok=False, outcome=e.outcome, why=f"refused: {e}"[:300])
        except Exception as e:  # noqa: BLE001
            row.update(ok=False, why=f"CRASH {type(e).__name__}: {e}"[:300], tb=traceback.format_exc()[-800:])
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "data" / "out" / "outcome_check"))
    a = ap.parse_args()
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    # 'sys' is the file's own system letter (G, R, M or blank): GLONASS data can only be in an R
    # or M file, and run() checks the data itself
    sel = [f["path"] for f in files if f["kind"] == "obs" and f["version"] < "3.02"
           and (f.get("sys") or "G") in "RM"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rows = []
    with Pool(a.jobs) as pool, open(out / "results.jsonl", "w", encoding="utf-8") as fh:
        for rs in pool.imap_unordered(run, sel):
            for r in rs:
                fh.write(json.dumps(r) + "\n")
            rows.extend(rs)
    c = Counter((r["mode"], r["ok"]) for r in rows)
    print(f"{len(sel)} files with GLONASS before 3.02, {len(rows)} conversions in {time.time() - t0:.0f} s")
    for mode in ("missing", "drop", "load", "skipped"):
        if c[(mode, True)] or c[(mode, False)]:
            print(f"  {mode}: {c[(mode, True)]} as expected, {c[(mode, False)]} not")
    for r in [r for r in rows if not r["ok"]][:15]:
        print("   ", r["mode"], r["path"], "->", r["target"], r.get("why", ""), r.get("message", "")[:120])
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
