"""SHA-256 of every corpus conversion's output and report, to prove that a change (such as a speed
optimisation) leaves every byte the converter writes unchanged.

For every corpus file x every write version, in up to three modes:
  plain    no compression, no Hatanaka (as tools/corpus_run.py converts)
  crx      Hatanaka output (observation files only)
  keep     the input's own wrappers (gz, .Z, Hatanaka) kept
with the same companions and --assume-phase-aligned as the corpus run. Each line of the output file
holds the outcome, the sha256 of each output (name and bytes) and of the JSON report; a refusal is
recorded by its outcome and message.

    python tools/digest_outputs.py --out data/out/digests_before.jsonl [--jobs 12]
    python tools/digest_outputs.py --compare data/out/digests_before.jsonl data/out/digests_after.jsonl
    python tools/digest_outputs.py --kinds nav --match BRD4 --out x.jsonl        (a subset)
    python tools/digest_outputs.py --compare before.jsonl x.jsonl --subset       (only x's keys)
    python tools/digest_outputs.py --out data/out/digests_before.jsonl --resume  (after an interrupted run)

Standard library only.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("SOURCE_DATE_EPOCH", "1793404800")      # the corpus run's fixed stamp
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import corpus_run  # noqa: E402  (companions, exactly as the corpus run chooses them)
from rinexconv.engine import WRITE_VERSIONS, Options, convert_data  # noqa: E402
from rinexcore.errors import RinexError  # noqa: E402
from rinexcore.io import hatanaka as _hatanaka  # noqa: E402

# Hatanaka output holds the minute it was written in 'CRINEX PROG / DATE' (hatanaka._crx_date with
# no date: datetime.now(); SOURCE_DATE_EPOCH fixes only the RINEX PGM line), so two runs a minute
# apart differ. Pinned here, in the tool only, to a date of the same 15-character shape; every other
# byte is the converter's own. (Found by the obs optimiser, 2026-11-03.)
_crx_date_orig = _hatanaka._crx_date
_hatanaka._crx_date = lambda date=None: _crx_date_orig(b"01-Nov-26 00:00" if date is None else date)


def sha(b):
    return hashlib.sha256(b).hexdigest()


# A report names its companion files by full path, and so holds the folder the tool runs from:
# that folder is replaced by '<ROOT>' before hashing, in plain and in JSON-escaped form, so that a
# checkout in another folder gives the same report hash (found by the obs optimiser, 2026-11-03).
_ROOTS = sorted({str(ROOT), str(ROOT).replace("\\", "/"), json.dumps(str(ROOT))[1:-1]}, key=len, reverse=True)


def _neutral(text):
    for r in _ROOTS:
        text = text.replace(r, "<ROOT>")
    return text


def digest_one(task):
    path, kind, companions = task
    raw = (corpus_run.CORPUS / path).read_bytes()
    modes = [("plain", dict(crx=False, compression="none")), ("keep", {})]
    if kind == "obs":
        modes.insert(1, ("crx", dict(crx=True, compression="none")))
    rows = []
    for target in WRITE_VERSIONS:
        for mode, kw in modes:
            row = {"path": path, "target": target, "mode": mode}
            t0 = time.perf_counter()
            try:
                outs = convert_data(raw, os.path.basename(path), Options(
                    target=target, nav=companions, assume_phase_aligned=True, **kw))
                row["outcome"] = outs[0].report.outcome
                row["outputs"] = [[o.name, sha(o.data), len(o.data)] for o in outs]
                row["report"] = sha(_neutral(outs[0].report.to_json()).encode("utf-8"))
            except RinexError as e:
                row["outcome"] = e.outcome
                row["message"] = sha(_neutral(str(e)).encode("utf-8"))
            except Exception as e:  # noqa: BLE001 - a crash is recorded, not hidden
                row["outcome"] = "CRASH"
                row["message"] = f"{type(e).__name__}: {e}"[:300]
            row["seconds"] = round(time.perf_counter() - t0, 3)
            rows.append(row)
    return rows


def tasks(kinds="obs,nav,met", match=""):
    # companions always come from the whole manifest, so that a --kinds/--match subset converts
    # with exactly the companions of a full run (found by the obs optimiser, 2026-11-03)
    files = json.loads(corpus_run.MANIFEST.read_text(encoding="utf-8"))["files"]
    comp = corpus_run.build_companions(files)
    out = []
    for f in files:
        if f["kind"] not in kinds.split(",") or match not in f["path"]:
            continue
        d = corpus_run.file_date(os.path.basename(f["path"]))
        c = [p for p in comp.get(d, []) if not p.endswith(f["path"].replace("/", os.sep))]
        navs = [p for p in c if "nav" in p.replace("\\", "/").split("/")[-3:-1][0:1] or "companions" in p]
        c = navs[:4] + [p for p in c if p not in navs][:2]
        out.append((f["path"], f["kind"], c))
    # largest first, so the long ones do not finish last
    out.sort(key=lambda t: -(corpus_run.CORPUS / t[0]).stat().st_size)
    return out


def _resume(out, todo):
    """An interrupted run: keep the files whose every row is in `out` (a worker writes a file's rows
    together, but a kill can cut that short or leave half a line), rewrite `out` with only those
    rows, and return the tasks still to do and how many files were kept."""
    rows = {}
    for line in open(out, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue                      # the cut-off last line
        rows.setdefault(r["path"], []).append(r)
    expected = {t[0]: len(WRITE_VERSIONS) * (3 if t[1] == "obs" else 2) for t in todo}
    done = {p for p, rs in rows.items() if len(rs) == expected.get(p)}
    with open(out, "w", encoding="utf-8") as fh:
        for p in done:
            for r in rows[p]:
                fh.write(json.dumps(r) + "\n")
    return [t for t in todo if t[0] not in done], len(done)


def compare(a_path, b_path, subset=False):
    def load(p):
        d = {}
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            d[(r["path"], r["target"], r["mode"])] = r
        return d
    a, b = load(a_path), load(b_path)
    if subset:                            # only the conversions the second file holds
        a = {k: v for k, v in a.items() if k in b}
    keys = ("outcome", "outputs", "report", "message")
    diff = [k for k in a if k not in b or any(a[k].get(x) != b[k].get(x) for x in keys)]
    extra = [k for k in b if k not in a]
    ta = sum(r["seconds"] for r in a.values())
    tb = sum(r["seconds"] for r in b.values() if (r["path"], r["target"], r["mode"]) in a)
    print(f"{len(a)} conversions compared: {len(diff)} differ, {len(extra)} only in the second file")
    for k in diff[:20]:
        print("  DIFF", k, {x: (a[k].get(x), b.get(k, {}).get(x)) for x in keys
                            if a[k].get(x) != b.get(k, {}).get(x)})
    print(f"conversion time, summed over workers: {ta:.0f} s -> {tb:.0f} s ({ta / tb if tb else 0:.2f}x)")
    return 1 if diff or extra else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--subset", action="store_true", help="--compare only the second file's keys")
    ap.add_argument("--kinds", default="obs,nav,met")
    ap.add_argument("--match", default="")
    ap.add_argument("--resume", action="store_true", help="keep the files --out already holds in full; digest the rest")
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare, subset=a.subset)
    t0 = time.time()
    n = 0
    todo = tasks(a.kinds, a.match)
    mode = "w"
    if a.resume and os.path.exists(a.out):
        todo, kept = _resume(a.out, todo)
        mode = "a"
        print(f"resuming: {kept} files already digested, {len(todo)} to go")
    with Pool(a.jobs) as pool, open(a.out, mode, encoding="utf-8") as fh:
        for rows in pool.imap_unordered(digest_one, todo):
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            n += len(rows)
    print(f"{n} conversions digested in {time.time() - t0:.0f} s -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
