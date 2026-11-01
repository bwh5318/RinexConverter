"""Corpus checks for the Hatanaka (CRX) codec in rinexcore/io/hatanaka.py.

Dev-only tool (PLAN §0: tools/ may run oracles; shipped code never does).

Sub-commands
------------
oracle   Run CRX2RNX.exe on every CRX file in tests/corpus/manifest.json and
         write the archive tests/oracle/crx2rnx_sha256.json (PLAN §1.5c).
decode   Decode every CRX corpus file with our decoder and compare its sha256
         with the archived digest of CRX2RNX's output (no exe needed).
encode   For every CRX corpus file: r = crx_to_rnx(crx);
           (a) crx_to_rnx(rnx_to_crx(r)) == r,
           (b) CRX2RNX.exe(rnx_to_crx(r)) == r   (skipped without the exe),
           (c) rnx_to_crx(r) == crx byte for byte, ignoring the
               CRINEX PROG / DATE line (counted, not required: the corpus
               files were written by many RNX2CRX versions).
fixtures Archive the hand-made fixtures of tests/unit/test_hatanaka.py and the
         RINEX 4.02 picosecond fixture (CRINEX 3.1) with CRX2RNX's results.
profile  cProfile our decoder and encoder on one file and print MB/s.

Every sub-command takes --start/--stop (indices into the sorted CRX list) so
long runs can be done in chunks, and --match to select files by substring.

CRX2RNX.exe on Windows writes its stdout in text mode, so every LF it writes
becomes CRLF; our decoder writes LF. The archive stores sha256_raw (the exe's
stdout as written) and sha256_lf = sha256(stdout with each CRLF turned back
into LF), plus lone_cr, the number of CRs not followed by LF. With lone_cr == 0
(all 299 files) the CRLF -> LF mapping is exact, so sha256_lf is the digest our
LF output must have; that is what a laptop without the exe checks.

Run from the repository root, e.g.  python tools/check_hatanaka.py decode
"""

import argparse
import cProfile
import datetime
import hashlib
import io
import json
import os
import pstats
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rinexcore.errors import CorruptError  # noqa: E402
from rinexcore.io.compress import unwrap  # noqa: E402

MANIFEST = os.path.join(ROOT, "tests", "corpus", "manifest.json")
CORPUS = os.path.join(ROOT, "data", "corpus")
ARCHIVE = os.path.join(ROOT, "tests", "oracle", "crx2rnx_sha256.json")
EXE_CANDIDATES = [
    os.environ.get("RINEX_ORACLE_CRX2RNX", ""),
    os.path.join(ROOT, "tools", "oracles", "rnxcmp", "CRX2RNX.exe"),
    os.path.join(ROOT, "reference", "tools", "rnxcmp-4.2.0", "CRX2RNX.exe"),
]


def find_exe():
    for p in EXE_CANDIDATES:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def crx_entries():
    with open(MANIFEST, "rb") as f:
        man = json.loads(f.read().decode("utf-8"))
    files = [e for e in man["files"] if e.get("crx")]
    files.sort(key=lambda e: e["path"])
    return files


def load_crx(entry):
    with open(os.path.join(CORPUS, entry["path"].replace("/", os.sep)), "rb") as f:
        data = f.read()
    payload, _layers = unwrap(data)
    return payload


def run_exe(exe, crx_bytes, workdir):
    """Run CRX2RNX on bytes; return (exit_code, stderr_text, out_path)."""
    inp = os.path.join(workdir, "in.crx")
    out = os.path.join(workdir, "out.rnx")
    with open(inp, "wb") as f:
        f.write(crx_bytes)
    with open(inp, "rb") as fi, open(out, "wb") as fo:
        r = subprocess.run([exe, "-"], stdin=fi, stdout=fo, stderr=subprocess.PIPE)
    os.remove(inp)
    return r.returncode, r.stderr.decode("latin-1"), out


def digest_exe_output(path):
    """sha256 of the raw stdout, and of it with CRLF -> LF; counts of stray CR."""
    h_raw = hashlib.sha256()
    h_lf = hashlib.sha256()
    n = 0
    lone_cr = 0
    carry = b""
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h_raw.update(chunk)
            n += len(chunk)
            chunk = carry + chunk
            if chunk.endswith(b"\r"):
                carry, chunk = b"\r", chunk[:-1]
            else:
                carry = b""
            lf = chunk.replace(b"\r\n", b"\n")
            lone_cr += lf.count(b"\r")
            h_lf.update(lf)
    if carry:
        lone_cr += 1
        h_lf.update(carry)
    return h_raw.hexdigest(), h_lf.hexdigest(), n, lone_cr


def select(entries, args):
    if args.match:
        entries = [e for e in entries if args.match in e["path"]]
    return entries[args.start:args.stop]


# --------------------------------------------------------------------------
def cmd_oracle(args):
    exe = find_exe()
    if not exe:
        print("CRX2RNX.exe not found; nothing to do")
        return 1
    if os.path.exists(ARCHIVE):
        with open(ARCHIVE, "rb") as f:
            arch = json.loads(f.read().decode("utf-8"))
    else:
        arch = {}
    arch.update({
        "tool": "CRX2RNX",
        "version": "4.2.0",
        "exe": "reference/tools/rnxcmp-4.2.0/CRX2RNX.exe",
        "exe_sha256": sha256_file(exe),
        "source": "https://terras.gsi.go.jp/ja/crx2rnx/RNXCMP_4.2.0_Windows_mingw_64bit.zip",
        "command": "CRX2RNX.exe -  < in.crx > out.rnx   (in.crx = corpus file after "
                   "rinexcore.io.compress.unwrap; stdin/stdout redirected to files "
                   "opened in binary mode by tools/check_hatanaka.py)",
        "platform": "Windows 11 x64; the mingw build writes stdout in text mode, so each LF "
                    "is written as CRLF",
        "fields": {
            "crx_sha256": "sha256 of the unwrapped CRX bytes fed to stdin",
            "exit_code": "CRX2RNX exit code (0 ok, 1 error, 2 warning)",
            "stderr": "CRX2RNX stderr text",
            "out_bytes": "length of the raw stdout",
            "sha256_raw": "sha256 of the raw stdout (CRLF line ends)",
            "sha256_lf": "sha256 of the raw stdout with every CRLF replaced by LF; "
                         "our decoder's output (LF) must have this digest",
            "lone_cr": "number of CR bytes not followed by LF (0 means sha256_lf is unambiguous)",
        },
    })
    files = arch.setdefault("files", {})
    entries = select(crx_entries(), args)
    with tempfile.TemporaryDirectory(dir=args.tmp) as work:
        for i, e in enumerate(entries):
            t0 = time.time()
            crx = load_crx(e)
            code, err, out = run_exe(exe, crx, work)
            raw, lf, n, lone = digest_exe_output(out)
            os.remove(out)
            files[e["path"]] = {
                "crx_sha256": hashlib.sha256(crx).hexdigest(),
                "exit_code": code,
                "stderr": err,
                "out_bytes": n,
                "sha256_raw": raw,
                "sha256_lf": lf,
                "lone_cr": lone,
            }
            print(f"{i + args.start:4d} {e['path']:70s} exit={code} out={n:>11d} "
                  f"{time.time() - t0:6.1f}s {err.strip()[:60]}", flush=True)
    arch["created_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    arch["files"] = dict(sorted(files.items()))
    os.makedirs(os.path.dirname(ARCHIVE), exist_ok=True)
    tmp = ARCHIVE + ".part"
    with open(tmp, "wb") as f:
        f.write((json.dumps(arch, indent=1) + "\n").encode("utf-8"))
    os.replace(tmp, ARCHIVE)
    print(f"archive: {len(arch['files'])} files in {ARCHIVE}")
    return 0


def _decode_digest(crx):
    """Stream our decoder: (sha256 of LF output, bytes, error or None)."""
    from rinexcore.io import hatanaka
    h = hashlib.sha256()
    n = 0
    try:
        for chunk in hatanaka.iter_crx_to_rnx(crx):
            h.update(chunk)
            n += len(chunk)
    except CorruptError as exc:
        return h.hexdigest(), n, exc
    return h.hexdigest(), n, None


def cmd_decode(args):
    with open(ARCHIVE, "rb") as f:
        arch = json.loads(f.read().decode("utf-8"))["files"]
    entries = select(crx_entries(), args)
    ok = bad = 0
    tot_in = tot_out = 0
    tot_t = 0.0
    for i, e in enumerate(entries):
        a = arch.get(e["path"])
        crx = load_crx(e)
        t0 = time.perf_counter()
        dig, n, err = _decode_digest(crx)
        dt = time.perf_counter() - t0
        tot_in += len(crx)
        tot_out += n
        tot_t += dt
        if a is None:
            status = "NO-ARCHIVE"
            bad += 1
        elif a["exit_code"] == 0 and err is None and dig == a["sha256_lf"]:
            status = "ok"
            ok += 1
        elif a["exit_code"] != 0 and err is not None:
            status = f"both-refuse exe={a['exit_code']} ours={err}"
            ok += 1
        else:
            status = (f"MISMATCH exe={a['exit_code']} out={a['out_bytes']} ours={n} "
                      f"err={err}")
            bad += 1
        print(f"{i + args.start:4d} {e['path']:70s} {status} {n / 1e6 / max(dt, 1e-9):6.1f} MB/s",
              flush=True)
    print(f"decode: {ok} ok, {bad} not ok, of {len(entries)}; "
          f"{tot_out / 1e6:.1f} MB out in {tot_t:.1f} s = {tot_out / 1e6 / max(tot_t, 1e-9):.2f} MB/s "
          f"(RINEX output), {tot_in / 1e6 / max(tot_t, 1e-9):.2f} MB/s (CRX input)")
    return 0 if bad == 0 else 1


def _compare_crx(orig, ours):
    """'identical' (ignoring line 2, CRINEX PROG / DATE), 'identical-after-line-2'
    (the CRINEX VERS line differs too), or 'differs@<line>:<why>'."""
    a = orig.split(b"\n")
    b = ours.split(b"\n")
    if a[0] == b[0] and a[2:] == b[2:]:
        return "identical"
    if a[2:] == b[2:]:
        return "identical-after-line-2"
    if b"\r\n" in orig:
        a2 = orig.replace(b"\r\n", b"\n").split(b"\n")
        if a2[0] == b[0] and a2[2:] == b[2:]:
            return "identical-except-crlf"
        a = a2
    for k, (x, y) in enumerate(zip(a, b)):
        if k >= 2 and x != y:
            why = "trailing-blanks" if x.rstrip(b" ") == y.rstrip(b" ") else "content"
            return f"differs@{k + 1}:{why}"
    return f"differs@length:{len(a)}vs{len(b)}"


def cmd_encode(args):
    from rinexcore.io import hatanaka
    exe = find_exe()
    entries = select(crx_entries(), args)
    rt_ok = rt_bad = exe_ok = exe_bad = exe_skip = same = same_body = same_crlf = differ = 0
    t_enc = 0.0
    n_rnx = 0
    with tempfile.TemporaryDirectory(dir=args.tmp) as work:
        for i, e in enumerate(entries):
            crx = load_crx(e)
            try:
                rnx = hatanaka.crx_to_rnx(crx)
            except CorruptError as exc:
                print(f"{i + args.start:4d} {e['path']:70s} decoder refuses: {exc}")
                continue
            t0 = time.perf_counter()
            try:
                crx2 = hatanaka.rnx_to_crx(rnx)
            except CorruptError as exc:
                rt_bad += 1
                print(f"{i + args.start:4d} {e['path']:70s} ENCODER REFUSES: {exc}", flush=True)
                continue
            dt = time.perf_counter() - t0
            t_enc += dt
            n_rnx += len(rnx)
            msg = []
            want = hashlib.sha256(rnx).hexdigest()
            dig, n, err = _decode_digest(crx2)
            if err is not None:
                msg.append(f"decode-of-ours refuses: {err}")
            if err is None and n == len(rnx) and dig == want:
                rt_ok += 1
                msg.append("rt=ok")
            else:
                rt_bad += 1
                msg.append("RT=FAIL")
            if exe:
                code, err, out = run_exe(exe, crx2, work)
                raw, lf, n, lone = digest_exe_output(out)
                os.remove(out)
                if code == 0 and lf == hashlib.sha256(rnx).hexdigest():
                    exe_ok += 1
                    msg.append("exe=ok")
                else:
                    exe_bad += 1
                    msg.append(f"EXE=FAIL({code} {err.strip()[:80]})")
            else:
                exe_skip += 1
            verdict = _compare_crx(crx, crx2)
            if verdict == "identical":
                same += 1
            elif verdict == "identical-after-line-2":
                same_body += 1
            elif verdict == "identical-except-crlf":
                same_crlf += 1
            else:
                differ += 1
            msg.append("reencode=" + verdict)
            prog = crx.split(b"\n", 2)[1][:40].strip().decode("latin-1")
            msg.append("orig_prog=" + prog.replace(" ", "_"))
            print(f"{i + args.start:4d} {e['path']:70s} {' '.join(msg)} "
                  f"{len(rnx) / 1e6 / max(dt, 1e-9):6.1f} MB/s", flush=True)
            del rnx, crx2
    print(f"encode: round-trip {rt_ok} ok / {rt_bad} bad; CRX2RNX(ours) {exe_ok} ok / "
          f"{exe_bad} bad / {exe_skip} skipped; re-encode identical to original "
          f"(ignoring CRINEX PROG / DATE) {same}, identical after line 2 {same_body}, "
          f"identical except CRLF {same_crlf}, "
          f"different {differ}; "
          f"{n_rnx / 1e6:.1f} MB RINEX in {t_enc:.1f} s = {n_rnx / 1e6 / max(t_enc, 1e-9):.2f} MB/s")
    return 0 if rt_bad == 0 and exe_bad == 0 else 1


def cmd_fixtures(args):
    """Archive the hand-made fixtures and the RINEX 4.02 picosecond fixture.

    For each: our encoding (CRINEX 3.1 for the 4.02 file), CRX2RNX's decoding
    of it, and whether that equals the expected RINEX. The 4.02 fixture's
    RINEX and CRX texts are stored in full (PLAN §1.5c keeps full oracle
    outputs only for small hand-made fixtures; CRX2RNX's output is the input).
    """
    from rinexcore.io import hatanaka
    from tests.unit import test_hatanaka as th
    exe = find_exe()
    if not exe:
        print("CRX2RNX.exe not found; nothing to do")
        return 1
    with open(ARCHIVE, "rb") as f:
        arch = json.loads(f.read().decode("utf-8"))
    fx = arch.setdefault("fixtures", {})
    ok = True
    with tempfile.TemporaryDirectory(dir=args.tmp) as work:
        def oracle(crx):
            code, err, out = run_exe(exe, crx, work)
            raw, lf, n, lone = digest_exe_output(out)
            os.remove(out)
            return {"exit_code": code, "stderr": err, "sha256_raw": raw, "sha256_lf": lf,
                    "lone_cr": lone}

        rnx = th.make_rinex402_fixture()
        crx = hatanaka.rnx_to_crx(rnx, program="rinexcore fixture", date=th.DATE)
        res = oracle(crx)
        res["equals_rinex"] = res["sha256_lf"] == th.sha(rnx)
        ok &= res["equals_rinex"] and res["exit_code"] == 0
        fx["rinex402_picosec"] = {
            "description": "RINEX 4.02 obs with picosecond epoch fields, made by "
                           "tests/unit/test_hatanaka.py:make_rinex402_fixture(); encoded by "
                           "rinexcore.io.hatanaka.rnx_to_crx (CRINEX 3.1, program "
                           "'rinexcore fixture', date '30-Oct-26 00:00'); crx2rnx = CRX2RNX "
                           "4.2.0 run on that CRX",
            "rinex_sha256": th.sha(rnx), "rinex_bytes": len(rnx),
            "crx_sha256": th.sha(crx), "crx_bytes": len(crx),
            "crinex_version": crx[:3].decode("ascii"),
            "rinex": rnx.decode("latin-1"), "crx": crx.decode("latin-1"),
            "crx2rnx": res,
        }
        print(f"rinex402_picosec: CRINEX {crx[:3].decode()} exit={res['exit_code']} "
              f"equals_rinex={res['equals_rinex']}")
        for name, (hcrx, hrnx) in th.HANDMADE.items():
            res = oracle(hcrx)
            res["equals_expected"] = res["sha256_lf"] == th.sha(hrnx)
            ok &= res["equals_expected"] and res["exit_code"] == 0
            fx["handmade_" + name] = {
                "description": "hand-written fixture in tests/unit/test_hatanaka.py",
                "crx_sha256": th.sha(hcrx), "expected_rinex_sha256": th.sha(hrnx),
                "crx2rnx": res,
            }
            print(f"handmade_{name}: exit={res['exit_code']} equals_expected="
                  f"{res['equals_expected']}")
    arch["fixtures_created_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")
    tmp = ARCHIVE + ".part"
    with open(tmp, "wb") as f:
        f.write((json.dumps(arch, indent=1) + "\n").encode("utf-8"))
    os.replace(tmp, ARCHIVE)
    return 0 if ok else 1


def cmd_profile(args):
    from rinexcore.io import hatanaka
    path = args.file or os.path.join(CORPUS, "obs", "v3.04",
                                     "AC2300USA_R_20231800000_01D_15S_MO.crx.gz")
    with open(path, "rb") as f:
        crx, _ = unwrap(f.read())
    for name, fn, arg in (("decode", hatanaka.crx_to_rnx, crx),):
        pr = cProfile.Profile()
        t0 = time.perf_counter()
        pr.enable()
        rnx = fn(arg)
        pr.disable()
        dt = time.perf_counter() - t0
        print(f"{name}: {len(crx) / 1e6:.1f} MB CRX -> {len(rnx) / 1e6:.1f} MB RINEX in {dt:.2f} s "
              f"(profiled) = {len(rnx) / 1e6 / dt:.2f} MB/s RINEX")
        s = io.StringIO()
        pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(12)
        print(s.getvalue())
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    crx2 = hatanaka.rnx_to_crx(rnx)
    pr.disable()
    dt = time.perf_counter() - t0
    print(f"encode: {len(rnx) / 1e6:.1f} MB RINEX -> {len(crx2) / 1e6:.1f} MB CRX in {dt:.2f} s "
          f"(profiled) = {len(rnx) / 1e6 / dt:.2f} MB/s RINEX")
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(12)
    print(s.getvalue())
    # unprofiled timings
    t0 = time.perf_counter()
    rnx = hatanaka.crx_to_rnx(crx)
    t1 = time.perf_counter()
    crx2 = hatanaka.rnx_to_crx(rnx)
    t2 = time.perf_counter()
    print(f"unprofiled: decode {len(rnx) / 1e6 / (t1 - t0):.2f} MB/s RINEX "
          f"({len(crx) / 1e6 / (t1 - t0):.2f} MB/s CRX), "
          f"encode {len(rnx) / 1e6 / (t2 - t1):.2f} MB/s RINEX")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["oracle", "decode", "encode", "fixtures", "profile"])
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=None)
    ap.add_argument("--match", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--tmp", default=None, help="directory for temporary files")
    args = ap.parse_args(argv)
    return {"oracle": cmd_oracle, "decode": cmd_decode, "encode": cmd_encode,
            "fixtures": cmd_fixtures, "profile": cmd_profile}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
