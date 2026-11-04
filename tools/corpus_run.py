"""Run rinexconv over the corpus, all files x all write versions (PLAN §4 "Corpus").

For every (file, target):
  1. convert, with the same-day GLONASS channels as companion (nav file from the
     corpus or a RINEX >= 3.02 obs header of the same day) and --assume-phase-aligned;
  2. the outcome must be `converted` (refusals are listed);
  3. the independent token comparator: diff <=> report (tests/independent);
  4. idempotence: converting the output again to the same target gives the same bytes.

    python tools/corpus_run.py [--kinds obs,nav,met] [--targets 3.05,2.11] [--jobs 6]
                               [--limit N] [--match SUBSTR] [--out data/out/corpus_run]

Results: one JSON line per (file, target) in <out>/results.jsonl, and a summary.
Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

# Reproducible PGM / RUN BY / DATE stamps (rinexconv/engine.py _stamp): every leg of a round
# trip writes the same creation time, so two generated lines differ only if their text does.
os.environ.setdefault("SOURCE_DATE_EPOCH", "1793404800")      # 2026-10-31 00:00:00 UTC

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rinexconv.engine import (WRITE_VERSIONS, Options, convert_data, convert_loaded,  # noqa: E402
                              load_bytes)
from rinexcore.errors import RinexError  # noqa: E402
from rinexcore.io.compress import unwrap  # noqa: E402
from tests.independent.compare import compare_met, compare_nav, compare_obs  # noqa: E402
from tests.independent.navfields import compare_nav_fields  # noqa: E402
from tests.independent.tokens import lines_of, met_tokens, nav_tokens, obs_tokens  # noqa: E402
from tests.independent.allowed import check as allowed_check  # noqa: E402

CORPUS = ROOT / "data" / "corpus"
MANIFEST = ROOT / "tests" / "corpus" / "manifest.json"


def file_date(name):
    m = re.match(r"^[A-Z0-9]{9}_[RSU]_(\d{4})(\d{3})", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^[a-z0-9]{4}(\d{3})[0a-x].*\.(\d{2})[a-z]", name, re.I)
    if m:
        y = int(m.group(2))
        return (1900 + y if y >= 80 else 2000 + y), int(m.group(1))
    return None


def build_companions(files):
    """{(year, doy): [paths]} of GLONASS channel sources: nav files with GLONASS
    records first, then RINEX >= 3.02 obs headers."""
    comp = defaultdict(list)
    for f in files:
        name = os.path.basename(f["path"])
        d = file_date(name)
        if d is None or name.startswith("BRDX"):
            continue
        if f["kind"] == "nav" and ("R" in (f.get("sys") or "") or f.get("ftype") == "G"
                                   or name.endswith(("g.gz", "g.Z")) or "_MN" in name or "_RN" in name):
            comp[d].insert(0, str(CORPUS / f["path"]))
        elif f["kind"] == "obs" and f["version"] >= "3.02":
            comp[d].append(str(CORPUS / f["path"]))
    # same-day GLONASS nav fetched by tools/fetch_companions.py
    for p in sorted((ROOT / "data" / "companions").glob("*g.*")):
        d = file_date(p.name)
        if d is not None:
            comp[d].insert(0, str(p))
    return comp


def payload(data):
    """Plain RINEX bytes of a (possibly gz/Z/CRX) file."""
    from rinexcore.rinexfile import open_container
    return open_container(data).payload


def _first_diff(a_bytes, b_bytes, name):
    a = a_bytes.decode("latin-1").split("\n")
    b = b_bytes.decode("latin-1").split("\n")
    k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    xa = a[k] if k < len(a) else "<eof>"
    xb = b[k] if k < len(b) else "<eof>"
    return f"{name}: first difference at line {k + 1}: {xa!r} vs {xb!r}"


_TOKRE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][+-]?\d+)?|\S+?(?=[+-]?\.?\d|\s|$)|\S+")
_NUMTOK = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([DdEe][+-]?\d+)?$")


def _norm_header_line(line):
    """Header line with numbers compared by value, exponent letters and blanks ignored.
    RINEX VERSION / TYPE: version, file-type letter (column 21) and system letter (column
    41) only; the rest of the A20 type field and the system description are free text
    ('N: GPS NAV DATA', 'Navigation', 'NAVIGATION DATA' all say N; rinex211.txt Table A3)."""
    label = line[60:80].strip()
    body = line[:60]
    if label == "RINEX VERSION / TYPE":
        body = body[:9] + " " + body[20:21] + " " + body[40:41]
    if label == "LEAP SECONDS" and body[24:27].strip() == "GPS":
        # time system identifier: 'Blank defaults to GPS' (rinex303.txt Table A2 p.60,
        # rinex305.txt Table A2 p.58); a version without the field has GPS fields (round 32)
        body = body[:24] + body[27:]
    from decimal import Decimal
    toks = []
    for t in _TOKRE.findall(body):
        if _NUMTOK.match(t):
            toks.append(str(Decimal(t.replace("D", "E").replace("d", "e")).normalize()))
        else:
            toks.append(t)
    if label == "TIME SYSTEM CORR" and len(toks) == 6 and toks[-1] == "0":
        toks.pop()      # UTC identifier: blank and 0 both mean unknown (rinex305.txt Table A5)
    return label, tuple(toks)


def _canonical_diff(kind, a_bytes, b_bytes, rep):
    """PLAN §1 clause 6: equal canonical model. Data must match token for token; header
    lines must match after number normalisation. Returns (verdict, header differences)."""
    a = lines_of(a_bytes)
    b = lines_of(b_bytes)
    if kind == "obs":
        data_ok = not compare_obs(a_bytes, b_bytes, rep)
    elif kind == "nav":
        # the same records with the same values (round 32: compare_nav would judge A' as a
        # conversion from B's version and apply B -> A's value changes, e.g. the GLONASS tk
        # basis, to A's values). Zero and blank are one value where neither says anything: a
        # spare position RINEX 4 does not define (rinex305.txt section 6.4: spares hold no
        # defined content), which a RINEX 4 leg leaves blank, and the 4.00/4.01 Klobuchar
        # Region code, '0 or blank (wide area parameters)' (rinex_4.00.txt Table A32 p.104)
        from decimal import Decimal
        from tests.independent.compare import _KLOB, fields4, spares4, v4_message
        v4 = float(a[0][:9]) >= 4

        def norm(key, m, v):
            v = list(v)
            s, m0 = key[1][0], m.split(" ")[0]
            zero = set()
            if key[0] == "EPH":
                msg = m0 or next(iter(v4_message(key[1], v)), "")
                f = fields4("4.02", "EPH", s, msg)
                if f is not None:
                    pos = 0
                    for line, n in enumerate(f):
                        width = 3 if line == 0 else 4
                        zero.update(range(pos + n, pos + width))
                        pos += width
                zero.update(spares4("4.02", "EPH", s, msg))      # spares a RINEX 4 leg leaves blank
            elif key[0] == "EOP":
                zero.update(spares4("4.02", "EOP", s, m0))
            elif key[0] == "ION" and v4 and (s, m0) in _KLOB:
                zero.add(8)
            v = [None if k in zero and x == Decimal(0) else x for k, x in enumerate(v)]
            while v and v[-1] is None:
                v.pop()
            return m, tuple(v)

        def recs(x):
            return {k: Counter(norm(k, m, v) for m, v in lst) for k, lst in nav_tokens(x).items()}
        data_ok = recs(a) == recs(b)
    else:
        data_ok = not compare_met(a_bytes, b_bytes, rep)
    ha = [_norm_header_line(x) for x in a[:next(i for i, x in enumerate(a) if "END OF HEADER" in x)]]
    hb = [_norm_header_line(x) for x in b[:next(i for i, x in enumerate(b) if "END OF HEADER" in x)]]
    hdiff = [x for x in ha if x not in hb][:3] + [("+",) + x for x in hb if x not in ha][:3]
    if not data_ok:
        return "data-differs", hdiff
    return ("ok-canonical" if not hdiff else "header-differs"), hdiff


CRX2RNX = ROOT / "reference" / "tools" / "rnxcmp-4.2.0" / "CRX2RNX.exe"
WRAP_TARGETS = ("2.11", "3.05", "4.02")


def _wrapper_leg(ld, path, kind, target, plain, companions, with_z=True):
    """The same conversion written Hatanaka-compressed (obs) and gz / .Z wrapped must decode
    back to the plain output byte for byte; CRX2RNX.exe (dev oracle) must agree too."""
    import subprocess
    from rinexcore.rinexfile import open_container
    problems = []
    legs = [("gz", True if kind == "obs" else None)]
    if with_z:                        # the pure-Python LZW encoder is slow on big files
        legs.append(("Z", True if kind == "obs" else None))
    for comp, crx in legs:
        outs = convert_loaded(ld, os.path.basename(path), Options(
            target=target, nav=companions, assume_phase_aligned=True, crx=crx, compression=comp))
        if len(outs) != len(plain):            # zip would pass over a missing split output
            problems.append(f"{comp}{'+crx' if crx else ''} {target}: {len(outs)} outputs, the plain "
                            f"conversion wrote {len(plain)}")
        for o, p in zip(outs, plain):
            back = open_container(o.data).payload
            if crx and not o.report.output.get("crx"):
                # written plain: a cycle-slip epoch Compact RINEX 1.0 cannot hold (warned)
                if not any(w["rule"] in ("OBS.CRX1.EVENT-PLAIN", "OBS.CRX.EVENT-PLAIN",
                                         "OBS.CRX.PICOSEC-PLAIN") for w in o.report.warnings):
                    problems.append(f"{comp}+crx {target}: written plain without the warning")
                if back != p:
                    problems.append(_first_diff(p, back, f"{comp}+crx(plain)"))
                continue
            if crx and o.report.losses.get("flags-on-missing-value-dropped"):
                # CRINEX 1.0 cannot hold flags on blank values, so the plain output differs
                # there: the decoded output is checked against the input with this leg's own
                # report instead (it used to be skipped: Sol round 11)
                probs = compare_obs(ld.container.payload, back, o.report.to_dict())
                if probs:
                    problems.append(f"{comp}+crx {target}: {probs[0]}")
            elif back != p:
                problems.append(_first_diff(p, back, f"{comp}{'+crx' if crx else ''}"))
            if crx and CRX2RNX.exists():
                # the oracle must decode the Compact RINEX to what our decoder gives
                from rinexcore.io.compress import unwrap
                crxtext = unwrap(o.data)[0]
                r = subprocess.run([str(CRX2RNX), "-"], input=crxtext, capture_output=True)
                if r.returncode != 0 or r.stdout.replace(b"\r\n", b"\n") != back:
                    problems.append(f"CRX2RNX disagrees on the {target} crx output (exit {r.returncode})")
    return problems


def run(task):
    """All targets for one file: the input is decoded, parsed and tokenised once."""
    path, kind, targets, companions = task
    recs = []
    t_load = time.time()
    try:
        data = (CORPUS / path).read_bytes()
        try:
            ld = load_bytes(data, False)
        except RinexError as e:
            for t in targets:
                recs.append({"path": path, "kind": kind, "target": t, "outcome": e.outcome,
                             "message": str(e)[:400]})
            return recs
        inp = ld.container.payload
        if kind == "obs":
            tin = {}                  # filled per comparison mode by compare_obs
        elif kind == "nav":
            tin = nav_tokens(lines_of(inp))
        else:
            tin = met_tokens(lines_of(inp))
    except Exception as e:
        return [{"path": path, "kind": kind, "target": t, "outcome": "CRASH",
                 "message": f"load: {type(e).__name__}: {e}"[:400],
                 "traceback": traceback.format_exc()[-1500:]} for t in targets]
    load_s = round(time.time() - t_load, 2)
    src_v = ld.info.version
    # the expensive checks (idempotence, round trip, wrappers) run on the source version and on
    # three targets that rotate from file to file, so every cell is covered across the corpus
    k0 = sum(path.encode()) % len(targets)
    heavy = {targets[(k0 + 4 * j) % len(targets)] for j in range(3)} | {src_v}
    small = len(ld.container.payload) < 5_000_000
    identity = None
    identity_tk = None
    if src_v in WRITE_VERSIONS:
        try:
            idouts = convert_loaded(ld, os.path.basename(path), Options(
                target=src_v, nav=companions, assume_phase_aligned=True, crx=False,
                compression="none"))
            identity = [o.data for o in idouts]
            if any(w["rule"] == "NAV.GLO.TK-DAY-BASIS" for w in idouts[0].report.warnings):
                # GLONASS tk written as seconds of the day (an input off spec, reported): A -> A
                # carries it, a round trip through RINEX 2 brings it back on the week basis, as
                # --lenient writes it: the reference for those round trips (round 32)
                identity_tk = [o.data for o in convert_loaded(ld, os.path.basename(path), Options(
                    target=src_v, nav=companions, assume_phase_aligned=True, crx=False,
                    compression="none", lenient=True))]
        except Exception:
            identity = None
    for target in targets:
        rec = {"path": path, "kind": kind, "target": target, "load_seconds": load_s}
        t0 = time.time()
        try:
            opts = Options(target=target, nav=companions, assume_phase_aligned=True, crx=False,
                           compression="none")
            try:
                outs = convert_loaded(ld, os.path.basename(path), opts)
            except RinexError as e:
                rec["outcome"] = e.outcome
                rec["message"] = str(e)[:400]
                rec["source_version"] = ld.info.version
                recs.append(rec)
                continue
            rep = outs[0].report.to_dict()
            rec["outcome"] = rep["outcome"]
            rec["source_version"] = rep["source_version"]
            rec["losses"] = {k: v["count"] for k, v in rep["losses"].items()}
            rec["repairs"] = len(rep["repairs"])
            rec["assumptions"] = len(rep["assumptions"])
            rec["seconds"] = round(time.time() - t0, 2)
            if kind == "obs":
                probs = compare_obs(inp, outs[0].data, rep, tin=tin)
            elif kind == "nav":
                probs = compare_nav(inp, [o.data for o in outs], rep, rin=tin)
                # the second, separate nav check (round 32): fields by name, with its own layouts
                # and the spec's transformations between versions (tests/independent/navfields.py)
                probs += ["navfields: " + p for p in compare_nav_fields(inp, [o.data for o in outs])[:5]]
            else:
                probs = compare_met(inp, outs[0].data, rep, tin=tin)
            rec["token_problems"] = probs[:5]
            rec["loss_violations"] = allowed_check(rep)
            idem = []
            for o in (outs if target in heavy else []):
                again = convert_data(o.data, o.name, Options(target=target, nav=companions,
                                                             assume_phase_aligned=True, crx=False,
                                                             compression="none"))
                if again[0].data != o.data:
                    idem.append(_first_diff(o.data, again[0].data, o.name))
            rec["idempotence"] = idem[:3]
            if target == sorted(heavy)[k0 % len(heavy)]:
                rec["wrappers"] = _wrapper_leg(ld, path, kind, target, [o.data for o in outs], companions,
                                               with_z=small)
            # round trip (PLAN §1 clause 6): a loss-free A -> B -> A equals A -> A
            overrides = any(str(a["source"]).startswith("override") for a in rep["assumptions"])
            if (identity is not None and not rep["losses"] and not overrides and target != src_v
                    and len(outs) == 1 and target in heavy):
                back = convert_data(outs[0].data, outs[0].name, Options(
                    target=src_v, nav=companions, assume_phase_aligned=True, crx=False,
                    compression="none"))
                bdata = back[0].data
                # A -> B added a record from a reported source (LEAP SECONDS, mandatory in
                # RINEX 4, from the dated table; GLONASS SLOT / FRQ #, mandatory from 3.02,
                # from a companion nav file); B -> A keeps it where A's version allows it.
                # Information added on the way, not changed.
                ident_head = identity[0].split(b"END OF HEADER")[0]
                for cat, label in (("leap-seconds", b"LEAP SECONDS"), ("glonass-fcn", b"GLONASS SLOT / FRQ #")):
                    if any(a["category"] == cat for a in rep["assumptions"]) and label not in ident_head:
                        head, sep, body = bdata.partition(b"END OF HEADER")
                        head = b"".join(x for x in head.splitlines(True) if not x.rstrip().endswith(label))
                        bdata = head + sep + body
                        rec["roundtrip_note"] = (rec.get("roundtrip_note", "") + f" {label.decode()} added by "
                                                 "A->B (reported assumption)").strip()
                # B -> A runs with --assume-phase-aligned (as every leg here does): a source of
                # unknown alignment (no SYS / PHASE SHIFT, e.g. HRAG00ZAF 3.02) comes back with the
                # aligned form that override asserts, reported as an override assumption. That
                # record is information the user's assertion added, not a changed value; the
                # data are still compared in full (round 40: 3.02 has its three-state record now)
                if (b"SYS / PHASE SHIFT" not in ident_head and any(
                        a["category"] == "phase-alignment" and str(a["source"]).startswith("override")
                        for a in back[0].report.to_dict()["assumptions"])):
                    head, sep, body = bdata.partition(b"END OF HEADER")
                    head = b"".join(x for x in head.splitlines(True) if not x.rstrip().endswith(b"SYS / PHASE SHIFT"))
                    bdata = head + sep + body
                    rec["roundtrip_note"] = (rec.get("roundtrip_note", "") + " SYS / PHASE SHIFT added by B->A "
                                             "(--assume-phase-aligned, reported)").strip()
                if back[0].report.losses:
                    rec["roundtrip"] = "lossy-return"     # B cannot go back without loss (reported)
                elif [bdata] + [o.data for o in back[1:]] == identity:
                    rec["roundtrip"] = "ok"
                elif identity_tk is not None and target < "3" and [bdata] + [o.data for o in back[1:]] == identity_tk:
                    rec["roundtrip"] = "ok"
                    rec["roundtrip_note"] = (rec.get("roundtrip_note", "") + " GLONASS tk on the day basis in the "
                                             "input came back on the week basis (NAV.GLO.TK-DAY-BASIS)").strip()
                else:
                    ref = identity_tk if identity_tk is not None and target < "3" else identity
                    rec["roundtrip"], rec["roundtrip_header"] = _canonical_diff(
                        kind, ref[0], bdata, back[0].report.to_dict())
        except Exception as e:  # a crash is a bug: record it
            rec["outcome"] = "CRASH"
            rec["message"] = f"{type(e).__name__}: {e}"[:400]
            rec["traceback"] = traceback.format_exc()[-1500:]
        rec["seconds_total"] = round(time.time() - t0, 2)
        recs.append(rec)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", default="obs,nav,met")
    ap.add_argument("--targets", default=",".join(WRITE_VERSIONS))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--match", default="")
    ap.add_argument("--versions", default="", help="only sources of these versions")
    ap.add_argument("--out", default=str(ROOT / "data" / "out" / "corpus_run"))
    a = ap.parse_args()
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    comp = build_companions(files)
    kinds = set(a.kinds.split(","))
    targets = a.targets.split(",")
    sel = [f for f in files if f["kind"] in kinds and a.match in f["path"]
           and (not a.versions or f["version"] in a.versions.split(","))]
    if a.limit:
        sel = sel[:a.limit]
    tasks = []
    for f in sel:
        d = file_date(os.path.basename(f["path"]))
        c = [p for p in comp.get(d, []) if not p.endswith(f["path"].replace("/", os.sep))]
        navs = [p for p in c if "nav" in p.replace("\\", "/").split("/")[-3:-1][0:1] or "companions" in p]
        c = (navs[:4] + [p for p in c if p not in navs][:2])
        tasks.append((f["path"], f["kind"], targets, c))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    results = []
    with Pool(a.jobs) as pool, open(out / "results.jsonl", "w", encoding="utf-8") as fh:
        for rs in pool.imap_unordered(run, tasks, chunksize=1):
            for r in rs:
                results.append(r)
                fh.write(json.dumps(r) + "\n")
            fh.flush()
    summarise(results, time.time() - t0, out)


def summarise(results, elapsed, out):
    outc = Counter(r["outcome"] for r in results)
    tok = [r for r in results if r.get("token_problems")]
    idem = [r for r in results if r.get("idempotence")]
    viol = [r for r in results if r.get("loss_violations")]
    wr = [r for r in results if r.get("wrappers")]
    print(f"wrapper legs checked: {sum(1 for r in results if 'wrappers' in r)}, problems: {len(wr)}")
    for r in wr[:8]:
        print("   WRAP", r["path"], r["target"], r["wrappers"][:2])
    rtc = Counter(r.get("roundtrip") for r in results if r.get("roundtrip"))
    print(f"round trips: {dict(rtc)}")
    for r in [x for x in results if x.get("roundtrip") in ("data-differs", "header-differs")][:12]:
        print("   RT", r["roundtrip"], r["path"], r["target"], r.get("roundtrip_header"))
    print(f"loss-table violations: {len(viol)}")
    for r in viol[:10]:
        print("   LOSS", r["path"], r.get("source_version"), "->", r["target"], r["loss_violations"][:3])
    print(f"{len(results)} conversions in {elapsed:.0f} s: {dict(outc)}")
    print(f"token problems: {len(tok)}; idempotence failures: {len(idem)}")
    by = defaultdict(Counter)
    for r in results:
        key = (r["kind"], r.get("source_version", "?"))
        ok = (r["outcome"] == "converted" and not r.get("token_problems") and not r.get("idempotence")
              and not r.get("loss_violations") and r.get("roundtrip") != "data-differs"
              and not r.get("wrappers"))
        by[key]["ok" if ok else "bad"] += 1
    lines = ["| kind | source | ok | bad |", "|---|---|---|---|"]
    for k in sorted(by):
        lines.append(f"| {k[0]} | {k[1]} | {by[k]['ok']} | {by[k]['bad']} |")
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    for r in [x for x in results if x["outcome"] not in ("converted",)][:15]:
        print("  ", r["outcome"], r["path"], "->", r["target"], r.get("message", "")[:200])
    for r in tok[:10]:
        print("   TOKENS", r["path"], "->", r["target"], r["token_problems"][:2])
    for r in idem[:10]:
        print("   IDEM", r["path"], "->", r["target"], r["idempotence"][:1])


if __name__ == "__main__":
    main()
