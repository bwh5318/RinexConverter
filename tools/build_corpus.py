"""Build the RINEX test corpus from CDDIS.

Screens candidate files by downloading only their first few KB (enough to read
the header through gzip, Unix-compress or Hatanaka wrappers), then picks a
receiver-diverse set per (kind, version) and downloads those files whole.

    python tools/build_corpus.py                 # screen + download
    python tools/build_corpus.py --screen-only   # just write the screen table
    python tools/build_corpus.py --check-login   # one listing + one header, then stop
    python tools/build_corpus.py --verify        # re-hash data/corpus against the manifest

Output, relative to the repository root:
    data/corpus/<kind>/<version>/<file>          files as CDDIS serves them
    data/corpus/screen.json                      every header screened
    tests/corpus/manifest.json                   what was kept, with sha256
    data/corpus/CORPUS.md                        counts per bucket

Credentials: a two-line file (Earthdata username, password). Looked up in
$RINEX_CDDIS_LOGIN, then ../RINEXConvert_Analysis_secrets/cddislogin.txt,
then ~/.cddis/cddislogin.txt. The password is sent only to the exact host
urs.earthdata.nasa.gov.

Uses the standard library plus requests (bundled with Anaconda).
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
MANIFEST = ROOT / "tests" / "corpus" / "manifest.json"
BASE = "https://cddis.nasa.gov/archive/gnss/"
EARTHDATA_HOST = "urs.earthdata.nasa.gov"
USER_AGENT = "rinexconvert-corpus/0.1"
SAMPLE_BYTES = 24 * 1024
WORKERS = 4

# --------------------------------------------------------------------------
# Credentials and HTTP (same rules as the desktop's autocomparesp3 downloader)
# --------------------------------------------------------------------------


def credential_paths():
    return [p for p in (
        os.environ.get("RINEX_CDDIS_LOGIN"),
        str(ROOT.parent / "RINEXConvert_Analysis_secrets" / "cddislogin.txt"),
        str(Path.home() / ".cddis" / "cddislogin.txt"),
    ) if p]


def load_credentials():
    for p in credential_paths():
        if os.path.isfile(p):
            lines = Path(p).read_text().strip().splitlines()
            if len(lines) < 2:
                sys.exit(f"Credentials file needs 2 lines (username, password): {p}")
            return lines[0].strip(), lines[1].strip()
    sys.exit("No CDDIS credentials file. Looked in:\n  " + "\n  ".join(credential_paths()))


class EarthdataAuth(requests.auth.AuthBase):
    """Send credentials only to the exact Earthdata login host."""

    def __init__(self, username, password):
        self._basic = requests.auth.HTTPBasicAuth(username, password)

    def __call__(self, r):
        if urlparse(r.url).hostname == EARTHDATA_HOST:
            return self._basic(r)
        return r


_local = threading.local()
_creds = None


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.auth = EarthdataAuth(*_creds)
        s.headers["User-Agent"] = USER_AGENT
        _local.s = s
    return s


def get(url, stream=False, headers=None, timeout=120):
    """GET following the login redirects hop by hop; https only."""
    for _ in range(10):
        r = session().get(url, allow_redirects=False, stream=stream,
                          headers=headers, timeout=timeout)
        if r.status_code not in (301, 302, 303, 307, 308):
            break
        r.close()
        url = urljoin(url, r.headers["Location"])
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
    else:
        raise RuntimeError(f"too many redirects: {url}")
    if r.status_code == 401:
        raise RuntimeError("Earthdata login rejected (401)")
    return r


def listdir(rel):
    """[(name, size)] of the files in an archive directory, [] if absent."""
    try:
        r = get(BASE + rel + "*?list", timeout=60)
    except Exception as e:  # network trouble: treat as empty, but say so
        print(f"  list failed {rel}: {e}", flush=True)
        return []
    if r.status_code != 200 or b"<html" in r.content[:500].lower():
        return []
    out = []
    for ln in r.text.splitlines():
        parts = ln.split()
        if len(parts) == 2 and not ln.startswith("#") and parts[1].isdigit():
            out.append((parts[0], int(parts[1])))
    return out


def fetch_head(url, nbytes=SAMPLE_BYTES):
    r = get(url, stream=True, headers={"Range": f"bytes=0-{nbytes - 1}"}, timeout=60)
    try:
        if r.status_code not in (200, 206):
            raise RuntimeError(f"HTTP {r.status_code}")
        buf = b""
        for chunk in r.iter_content(8192):
            buf += chunk
            if len(buf) >= nbytes:
                break
        return buf[:nbytes]
    finally:
        r.close()


# --------------------------------------------------------------------------
# Decompression of a file's first bytes
# --------------------------------------------------------------------------


def unlzw(data):
    """Decode Unix compress (.Z) data; a truncated stream yields what it can.

    Codes are LSB-first, 9..maxbits wide. The compressor writes codes in groups
    of eight; whenever the width changes (growth or CLEAR) the rest of the
    current group is padding, so the reader skips to the group boundary.
    """
    if data[:2] != b"\x1f\x9d":
        raise ValueError("not a .Z stream")
    maxbits = data[2] & 0x1F
    block = bool(data[2] & 0x80)
    if not 9 <= maxbits <= 16:
        raise ValueError(f"bad maxbits {maxbits}")
    stream = data[3:]
    total_bits = len(stream) * 8
    first_free = 257 if block else 256
    table = [bytes([i]) for i in range(256)] + ([b""] if block else [])
    nbits, pos, seg_start = 9, 0, 0
    prev = None
    out = bytearray()

    def realign(width):
        nonlocal pos, seg_start
        group = width * 8
        pos = seg_start + -(-(pos - seg_start) // group) * group
        seg_start = pos

    while pos + nbits <= total_bits:
        byte, bit = divmod(pos, 8)
        word = int.from_bytes(stream[byte:byte + 3], "little")
        code = (word >> bit) & ((1 << nbits) - 1)
        pos += nbits
        if block and code == 256:
            realign(nbits)
            del table[first_free:]
            nbits, prev = 9, None
            continue
        if prev is None:
            if code >= 256:
                raise ValueError("bad first code")
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            if len(table) < (1 << maxbits):
                table.append(table[prev] + entry[:1])
        elif code == len(table):
            entry = table[prev] + table[prev][:1]
            table.append(entry)
        else:
            raise ValueError(f"bad code {code} at bit {pos}")
        out += entry
        prev = code
        if len(table) > (1 << nbits) - 1 and nbits < maxbits:
            realign(nbits)
            nbits += 1
    return bytes(out)


def unwrap_head(name, data):
    """Text of the first bytes of a (possibly compressed) RINEX/CRX file."""
    if name.endswith(".gz"):
        raw = zlib.decompressobj(31).decompress(data)
    elif name.endswith(".Z"):
        raw = unlzw(data)
    else:
        raw = data
    return raw.decode("ascii", errors="replace")


# --------------------------------------------------------------------------
# Header screening
# --------------------------------------------------------------------------


def parse_header(text):
    lines = text.splitlines()
    info = {"crx": None}
    if lines and "CRINEX VERS" in lines[0]:
        info["crx"] = lines[0][:20].strip()
        lines = lines[2:]
    if not lines or "RINEX VERSION / TYPE" not in lines[0]:
        return None
    first = lines[0].ljust(80)
    try:
        info["version"] = float(first[:9])
    except ValueError:
        return None
    info["version_str"] = first[:9].strip()
    info["ftype"] = first[20]
    info["sys"] = first[40].strip()
    obs_sys, v2_types = set(), []
    complete = False
    for ln in lines[1:]:
        label = ln[60:80].strip()
        body = ln[:60]
        if label == "REC # / TYPE / VERS":
            info["receiver"] = body[20:40].strip()
            info["rec_fw"] = body[40:60].strip()
        elif label == "ANT # / TYPE":
            info["antenna"] = body[20:40].strip()
        elif label == "MARKER NAME":
            info["marker"] = body.strip()
        elif label == "PGM / RUN BY / DATE":
            info.setdefault("pgm", body[:20].strip())
        elif label == "INTERVAL":
            try:
                info["interval"] = float(body[:10])
            except ValueError:
                pass
        elif label == "SYS / # / OBS TYPES" and body[:1].strip():
            obs_sys.add(body[0])
        elif label == "# / TYPES OF OBSERV":
            v2_types += body[6:].split()
        elif label == "END OF HEADER":
            complete = True
            break
    if obs_sys:
        info["obs_systems"] = "".join(sorted(obs_sys))
    if v2_types:
        info["v2_obs_types"] = " ".join(v2_types)
    info["header_complete"] = complete
    return info


def norm_version(version_str):
    """'2' -> '2.00', '2.1' -> '2.10': the folder name. The raw field stays in the
    manifest as version_str, because writers really do emit '2' and '2.1'."""
    return f"{float(version_str):.2f}"


def kind_of(info):
    t = info["ftype"]
    if t == "O":
        return "obs"
    if t == "M":
        return "met"
    if t in "NGHLBCQJI" or info.get("version", 0) >= 3 and t == "N":
        return "nav"
    return "other"


BRANDS = ["TRIMBLE", "SEPT", "LEICA", "JAVAD", "JPS", "NOV", "TPS", "TOPCON",
          "ASHTECH", "ROGUE", "AOA", "TURBOROGUE", "CHC", "UNICORE", "HEMISPHERE",
          "STONEX", "GEOMAX", "SOKKIA", "SPECTRA", "TRM", "HI-TARGET", "COMNAV",
          "ALLYSTAR", "ZEISS", "MINIMAC", "TI4100", "ESA", "GFZ"]


def brand(receiver):
    r = (receiver or "").upper()
    for b in BRANDS:
        if r.startswith(b):
            return {"JPS": "JAVAD", "TOPCON": "TPS", "TURBOROGUE": "ROGUE"}.get(b, b)
    return r.split(" ")[0] if r else "UNKNOWN"


# --------------------------------------------------------------------------
# What to screen
# --------------------------------------------------------------------------

# (archive dir, filename regex, max files to screen, cadence tag)
OBS_DIRS = [
    ("data/daily/2026/274/26d/", r".", 9999, "daily"),
    ("data/daily/2026/274/26o/", r".", 9999, "daily"),
    ("data/daily/2023/180/23d/", r".", 200, "daily"),
    ("data/daily/2020/180/20d/", r".", 200, "daily"),
    ("data/daily/2017/180/17d/", r".", 160, "daily"),
    ("data/daily/2015/180/15d/", r".", 120, "daily"),
    ("data/daily/2010/180/10d/", r".", 80, "daily"),
    ("data/daily/2003/180/03d/", r".", 60, "daily"),
    ("data/daily/1998/180/98d/", r".", 40, "daily"),
    ("data/daily/1998/180/98o/", r".", 40, "daily"),
    ("data/highrate/2026/274/26d/00/", r"0000_15M_01S|a00\.26d", 60, "highrate"),
    ("data/hourly/2026/274/00/", r"_MO\.|0\.26d|a\.26d", 60, "hourly"),
]

NAV_DIRS = [
    ("data/daily/2026/274/26p/", r".", 80),
    ("data/daily/2026/274/26n/", r"^(?!brdc)", 40),
    ("data/daily/2026/274/26g/", r"^(?!brdc)", 40),
    ("data/daily/2026/274/26l/", r".", 30),
    ("data/daily/2026/274/26f/", r".", 30),
    ("data/daily/2026/274/26q/", r".", 30),
    ("data/daily/2026/274/26h/", r".", 30),
    ("data/daily/2026/274/26i/", r".", 30),
    ("data/daily/2020/180/20p/", r".", 40),
    ("data/daily/2020/180/20n/", r"^(?!brdc)", 20),
    ("data/daily/2017/180/17p/", r".", 30),
    ("data/daily/2015/180/15n/", r"^(?!brdc)", 20),
    ("data/daily/2003/180/03n/", r"^(?!brdc)", 15),
]

# Merged broadcast files, all kept: (year, doy) per era.
BRDC_DAYS = [(2026, 274), (2026, 1), (2025, 180), (2024, 180), (2023, 180), (2022, 180),
             (2020, 180), (2017, 180), (2015, 180), (2010, 180), (2003, 180)]

MET_DIRS = [
    ("data/daily/2026/274/26m/", r".", 9999),
    ("data/daily/2020/180/20m/", r".", 40),
    ("data/daily/2015/180/15m/", r".", 30),
    ("data/daily/2003/180/03m/", r".", 20),
]

QUOTA = {"obs": 30, "nav": 8, "met": 10}
QUOTA_OVERRIDE = {("obs", "2.11", "daily"): 45, ("obs", "*", "highrate"): 6,
                  ("obs", "*", "hourly"): 4}


def quota(kind, version, cadence):
    return (QUOTA_OVERRIDE.get((kind, version, cadence))
            or QUOTA_OVERRIDE.get((kind, "*", cadence))
            or QUOTA[kind])


def candidates():
    rnd = random.Random(20261030)
    out = []

    def add(rel, rx, cap, cadence):
        names = [(n, s) for n, s in listdir(rel)
                 if re.search(rx, n) and not n.endswith(("SUMS", ".status", "V3status"))]
        rnd.shuffle(names)
        print(f"  {rel}: {len(names)} files, screening {min(cap, len(names))}", flush=True)
        for n, s in names[:cap]:
            out.append({"url": BASE + rel + n, "name": n, "size": s,
                        "dir": rel, "cadence": cadence})

    print("Listing directories...", flush=True)
    for rel, rx, cap, cad in OBS_DIRS:
        add(rel, rx, cap, cad)
    for rel, rx, cap in NAV_DIRS:
        add(rel, rx, cap, "daily")
    for rel, rx, cap in MET_DIRS:
        add(rel, rx, cap, "daily")
    for year, doy in BRDC_DAYS:
        yy = year % 100
        rx = rf"brdc{doy:03d}0\.{yy:02d}[a-z]|{year}{doy:03d}0000_01D_[A-Z]N\.rnx"
        add(f"data/daily/{year}/brdc/", rx, 20, "brdc")
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def screen_one(c):
    try:
        info = parse_header(unwrap_head(c["name"], fetch_head(c["url"])))
    except Exception as e:
        return {**c, "error": f"{type(e).__name__}: {e}"}
    if info is None:
        return {**c, "error": "no RINEX header found"}
    return {**c, **info, "kind": kind_of(info)}


def select(screened):
    by_bucket = defaultdict(list)
    for s in screened:
        if "error" in s or s.get("kind") == "other":
            continue
        cad = s["cadence"]
        if s["kind"] != "obs":
            cad = "brdc" if cad == "brdc" else "daily"
        by_bucket[(s["kind"], norm_version(s["version_str"]), cad)].append(s)
    # The same file can be listed in two directories (merged brdc files also appear
    # in the per-station YYp/ directories); keep the first by name.
    seen_names = set()
    for key in list(by_bucket):
        unique = []
        for s in by_bucket[key]:
            if s["name"] not in seen_names:
                seen_names.add(s["name"])
                unique.append(s)
        by_bucket[key] = unique
    chosen = []
    for (kind, ver, cad), items in sorted(by_bucket.items()):
        if cad == "brdc":  # merged broadcast files: keep all
            chosen += items
            continue
        # Round-robin over receiver brands, then distinct receiver models,
        # varying source directory (era) and wrapper.
        groups = defaultdict(list)
        for s in sorted(items, key=lambda s: (s["dir"], s["name"])):
            groups[brand(s.get("receiver"))].append(s)
        seen_models, picked = set(), []
        q = quota(kind, ver, cad)
        while len(picked) < q and any(groups.values()):
            for b in sorted(groups, key=lambda b: len(groups[b])):
                if not groups[b] or len(picked) >= q:
                    continue
                fresh = [s for s in groups[b] if (s.get("receiver"), s["dir"]) not in seen_models]
                s = (fresh or groups[b])[0]
                groups[b].remove(s)
                seen_models.add((s.get("receiver"), s["dir"]))
                picked.append(s)
        chosen += picked
    return chosen


def download(s):
    dest_dir = CORPUS / s["kind"] / f"v{norm_version(s['version_str'])}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / s["name"]
    if not (dest.exists() and dest.stat().st_size == s["size"]):
        for attempt in range(3):
            try:
                r = get(s["url"], timeout=300)
                if r.status_code != 200 or b"<html" in r.content[:500].lower():
                    raise RuntimeError(f"HTTP {r.status_code}")
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(r.content)
                tmp.replace(dest)
                break
            except Exception as e:
                if attempt == 2:
                    return {**s, "error": f"download: {e}"}
                time.sleep(5 * (attempt + 1))
    data = dest.read_bytes()
    try:  # integrity: the wrapper must decode end to end
        if s["name"].endswith(".gz"):
            d = zlib.decompressobj(31)
            d.decompress(data)
            if not d.eof:
                raise ValueError("truncated gzip")
        elif s["name"].endswith(".Z"):
            unlzw(data)
    except Exception as e:
        return {**s, "error": f"integrity: {e}"}
    rel = dest.relative_to(CORPUS).as_posix()
    keep = ("url", "dir", "cadence", "kind", "version_str", "ftype", "sys", "crx",
            "marker", "receiver", "rec_fw", "antenna", "pgm", "interval",
            "obs_systems", "v2_obs_types", "header_complete")
    return {"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "version": norm_version(s["version_str"]),
            **{k: s[k] for k in keep if k in s}}


def write_summary(kept):
    rows = Counter((k["kind"], k["version"]) for k in kept)
    brands = defaultdict(Counter)
    for k in kept:
        brands[(k["kind"], k["version"])][brand(k.get("receiver"))] += 1
    total = sum(k["bytes"] for k in kept)
    lines = ["# RINEX test corpus", "",
             f"{len(kept)} files, {total / 1e6:.0f} MB, built by tools/build_corpus.py "
             f"on {time.strftime('%Y-%m-%d')}. Manifest with sha256: tests/corpus/manifest.json.",
             "Files are stored exactly as CDDIS serves them (gzip, .Z, Hatanaka).", "",
             "| Kind | Version | Files | Receiver brands (obs) / systems (nav) |",
             "|---|---|---|---|"]
    for (kind, ver), n in sorted(rows.items()):
        if kind == "nav":
            detail = ", ".join(f"{s or '?'}×{c}" for s, c in sorted(Counter(
                (k["ftype"] if k["version"].startswith("2") else k.get("sys"))
                for k in kept if (k["kind"], k["version"]) == (kind, ver)).items()))
        else:
            detail = ", ".join(f"{b}×{c}" for b, c in brands[(kind, ver)].most_common())
        lines.append(f"| {kind} | {ver} | {n} | {detail} |")
    (CORPUS / "CORPUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify():
    """Check every manifest file is present with the recorded sha256 (no network)."""
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    bad = 0
    for f in files:
        p = CORPUS / f["path"]
        if not p.exists():
            print(f"MISSING {f['path']}")
            bad += 1
        elif hashlib.sha256(p.read_bytes()).hexdigest() != f["sha256"]:
            print(f"CHANGED {f['path']}")
            bad += 1
    print(f"{len(files) - bad}/{len(files)} corpus files OK")
    sys.exit(1 if bad else 0)


def check_login():
    rel = "data/daily/2026/brdc/"
    names = listdir(rel)
    if not names:
        sys.exit(f"Listing {rel} returned nothing: login or network problem.")
    name = next(n for n, _ in names if n.startswith("BRDC00IGS"))
    info = parse_header(unwrap_head(name, fetch_head(BASE + rel + name)))
    print(f"Login OK: listed {len(names)} files in {rel}; "
          f"{name} is RINEX {info['version_str']} {info['ftype']}")


def main():
    global _creds
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--screen-only", action="store_true")
    ap.add_argument("--check-login", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    if args.verify:
        verify()
    _creds = load_credentials()
    if args.check_login:
        check_login()
        return
    CORPUS.mkdir(parents=True, exist_ok=True)

    cands = candidates()
    print(f"Screening {len(cands)} headers...", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        screened = list(ex.map(screen_one, cands))
    (CORPUS / "screen.json").write_text(json.dumps(screened, indent=1), encoding="utf-8")
    errs = [s for s in screened if "error" in s]
    found = Counter((s["kind"], s["version_str"]) for s in screened if "error" not in s)
    print(f"Screened: {len(screened) - len(errs)} ok, {len(errs)} errors", flush=True)
    for (k, v), n in sorted(found.items()):
        print(f"  {k:4s} {v:6s} {n}", flush=True)
    for e in errs[:10]:
        print(f"  ERR {e['name']}: {e['error']}", flush=True)
    if args.screen_only:
        return

    chosen = select(screened)
    print(f"Downloading {len(chosen)} files "
          f"({sum(c['size'] for c in chosen) / 1e6:.0f} MB)...", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(download, chosen))
    kept = [r for r in results if "error" not in r]
    for r in results:
        if "error" in r:
            print(f"  FAILED {r['name']}: {r['error']}", flush=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"base_url": BASE, "files": kept}, indent=1),
                        encoding="utf-8")
    write_summary(kept)
    print(f"Kept {len(kept)} files. See data/corpus/CORPUS.md", flush=True)


if __name__ == "__main__":
    main()
