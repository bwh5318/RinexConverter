"""Mutation audit of the independent loss checks on corpus files (review round 13).

For corpus rows with losses (from a tools/corpus_run.py results.jsonl), the conversion is run
again, then for every loss in its report the claim is deleted, and separately its count raised
by one. The independent checks (compare_* and the loss table) must reject each mutation; one
they accept "survives", a loss they do not count exactly. Up to per_group rows (smallest files
first) are taken for each kind of loss. The unit suite has the same audit built in
(RINEX_MUTATION_AUDIT, tests/conftest.py).

Usage: python tools/mutation_audit.py <results.jsonl> <out.json> [per_group] [jobs]
"""
import copy
import json
import os
import re
import sys
import time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)

import corpus_run as CR  # noqa: E402
from rinexconv.engine import Options, convert_loaded, load_bytes  # noqa: E402
from tests.independent.allowed import check as allowed_check  # noqa: E402
from tests.independent.compare import compare_met, compare_nav, compare_obs  # noqa: E402


def group(k):
    parts = k.split(":")
    if k.startswith(("header-", "event-", "nav-")):
        return ":".join(parts[:2])
    return parts[0]


def checks(kind, inp, outs, rep, tin):
    if kind == "obs":
        p = compare_obs(inp, outs[0], rep, tin=tin)
    elif kind == "nav":
        p = compare_nav(inp, outs, rep)
    else:
        p = compare_met(inp, outs[0], rep)
    return p + allowed_check(rep)


def audit(task):
    path, kind, target, comp = task
    t0 = time.time()
    res = {"path": path, "target": target, "kind": kind, "survivors": [], "caught": 0}
    try:
        ld = load_bytes((CR.CORPUS / path).read_bytes(), False)
        outs = convert_loaded(ld, os.path.basename(path), Options(
            target=target, nav=comp, assume_phase_aligned=True, crx=False, compression="none"))
        rep = outs[0].report.to_dict()
        data = [o.data for o in outs]
        tin = {}
        base = checks(kind, ld.container.payload, data, rep, tin)
        if base:
            res["baseline"] = base[:3]
            return res
        for k, e in rep["losses"].items():
            for how in ("del", "plus1"):
                bad = copy.deepcopy(rep)
                if how == "del":
                    del bad["losses"][k]
                else:
                    bad["losses"][k]["count"] = e["count"] + 1
                if checks(kind, ld.container.payload, data, bad, tin):
                    res["caught"] += 1
                else:
                    res["survivors"].append(f"{how} {k} (count {e['count']})")
    except Exception as ex:  # noqa: BLE001
        res["error"] = f"{type(ex).__name__}: {ex}"[:300]
    res["seconds"] = round(time.time() - t0, 1)
    return res


def main():
    src, out = sys.argv[1], sys.argv[2]
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    jobs = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    files = json.loads(CR.MANIFEST.read_text(encoding="utf-8"))["files"]
    comp = CR.build_companions(files)
    size = {f["path"]: os.path.getsize(CR.CORPUS / f["path"]) for f in files}
    rows = [json.loads(l) for l in open(src, encoding="utf-8")]
    rows = [r for r in rows if r.get("losses")]
    rows.sort(key=lambda r: size.get(r["path"], 1 << 40))
    chosen, seen = [], {}
    for r in rows:
        gs = {(r["kind"], group(k)) for k in r["losses"]}
        if any(seen.get(g, 0) < per for g in gs):
            chosen.append(r)
            for g in gs:
                seen[g] = seen.get(g, 0) + 1
    tasks = []
    for r in chosen:
        d = CR.file_date(os.path.basename(r["path"]))
        c = [p for p in comp.get(d, []) if not p.endswith(r["path"].replace("/", os.sep))]
        navs = [p for p in c if "nav" in p.replace("\\", "/").split("/")[-3:-1][0:1] or "companions" in p]
        c = navs[:4] + [p for p in c if p not in navs][:2]
        tasks.append((r["path"], r["kind"], r["target"], c))
    print(f"{len(tasks)} rows, {len(seen)} groups", flush=True)
    results = []
    with Pool(jobs) as pool:
        for res in pool.imap_unordered(audit, tasks):
            results.append(res)
            flag = "SURVIVORS" if res["survivors"] else ("BASELINE" if res.get("baseline") else
                                                        ("ERROR" if res.get("error") else "ok"))
            print(f"{flag} {res['path']} -> {res['target']} caught {res['caught']} "
                  f"{res['survivors'][:6]} {res.get('baseline') or res.get('error') or ''} "
                  f"({res.get('seconds')} s)", flush=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    surv = sorted({re.sub(r" \(count \d+\)", "", s) for r in results for s in r["survivors"]})
    print("SURVIVING MUTATIONS:", len(surv))
    for s in surv:
        print("  ", s)


if __name__ == "__main__":
    main()
